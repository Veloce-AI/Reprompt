"""Tests for GET/PATCH /settings/workspace and the /settings/api-keys CRUD
surface (screen 9 / M5).

Same TestClient + in-memory SQLite pattern as test_auth.py/test_rubrics.py.
Users/sessions are created via the real magic-link flow (request-link ->
verify) rather than hand-inserted rows, so these tests exercise the exact
auth path a real client would use - including getting a Bearer session
token to pass as Authorization on every settings call.

REFRACT_SETTINGS_ENCRYPTION_KEY is set via an autouse fixture so every test
gets a real Fernet key by default; the one test that cares about the
"not configured" path removes it and clears refract_api.crypto's cache
explicitly.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from refract_api import crypto, models
from refract_api.db import get_db
from refract_api.main import app
from refract_api.models import Base


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(crypto.ENV_VAR, Fernet.generate_key().decode())
    crypto.reset_cache_for_tests()
    yield
    crypto.reset_cache_for_tests()


@pytest.fixture()
def session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def client(session_factory: sessionmaker) -> Iterator[TestClient]:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _extract_token(dev_magic_link: str) -> str:
    query = parse_qs(urlparse(dev_magic_link).query)
    return query["token"][0]


def _sign_in(client: TestClient, email: str) -> tuple[str, int]:
    """Runs the full magic-link flow and returns (session_token, workspace_id)."""
    response = client.post("/auth/request-link", json={"email": email})
    assert response.status_code == 200, response.text
    raw_token = _extract_token(response.json()["dev_magic_link"])

    verify = client.post("/auth/verify", json={"token": raw_token})
    assert verify.status_code == 200, verify.text
    body = verify.json()
    return body["session_token"], body["workspace"]["id"]


def _auth_headers(session_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token}"}


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------


def test_all_endpoints_reject_unauthenticated_requests(client: TestClient) -> None:
    assert client.get("/settings/workspace").status_code == 401
    assert client.patch("/settings/workspace", json={"name": "x"}).status_code == 401
    assert client.get("/settings/api-keys").status_code == 401
    assert (
        client.post("/settings/api-keys", json={"provider": "openai", "api_key": "sk-abcd1234"}).status_code
        == 401
    )
    assert client.delete("/settings/api-keys/1").status_code == 401


def test_endpoints_reject_garbage_bearer_token(client: TestClient) -> None:
    headers = {"Authorization": "Bearer not-a-real-token"}
    assert client.get("/settings/workspace", headers=headers).status_code == 401
    assert client.get("/settings/api-keys", headers=headers).status_code == 401


# ---------------------------------------------------------------------------
# Workspace name
# ---------------------------------------------------------------------------


def test_get_workspace_settings_returns_current_name(client: TestClient) -> None:
    token, _ = _sign_in(client, "alice@example.com")
    response = client.get("/settings/workspace", headers=_auth_headers(token))
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "alice's workspace"


def test_patch_workspace_settings_renames_workspace(
    client: TestClient, session_factory: sessionmaker
) -> None:
    token, workspace_id = _sign_in(client, "bob@example.com")

    response = client.patch(
        "/settings/workspace", json={"name": "Bob's Team"}, headers=_auth_headers(token)
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Bob's Team"

    with session_factory() as db:
        workspace = db.get(models.Workspace, workspace_id)
        assert workspace.name == "Bob's Team"


def test_patch_workspace_settings_rejects_blank_name(client: TestClient) -> None:
    token, _ = _sign_in(client, "blank@example.com")
    response = client.patch(
        "/settings/workspace", json={"name": "   "}, headers=_auth_headers(token)
    )
    assert response.status_code == 422


def test_patch_workspace_settings_trims_whitespace(client: TestClient) -> None:
    token, _ = _sign_in(client, "trim@example.com")
    response = client.patch(
        "/settings/workspace", json={"name": "  Trimmed Name  "}, headers=_auth_headers(token)
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Trimmed Name"


# ---------------------------------------------------------------------------
# API keys: add / list / delete
# ---------------------------------------------------------------------------


def test_list_api_keys_empty_before_any_added(client: TestClient) -> None:
    token, _ = _sign_in(client, "empty@example.com")
    response = client.get("/settings/api-keys", headers=_auth_headers(token))
    assert response.status_code == 200
    assert response.json() == []


def test_add_api_key_returns_provider_and_last_four_never_the_key(client: TestClient) -> None:
    token, _ = _sign_in(client, "addkey@example.com")

    response = client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-proj-abcdEFGH1234"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["provider"] == "openai"
    assert body["last_four"] == "1234"
    assert "api_key" not in body
    assert "encrypted_key" not in body
    assert "key" not in body
    assert "created_at" in body


def test_add_api_key_stores_ciphertext_not_plaintext(
    client: TestClient, session_factory: sessionmaker
) -> None:
    token, workspace_id = _sign_in(client, "encrypted@example.com")
    raw_key = "sk-super-secret-value-98765"

    response = client.post(
        "/settings/api-keys",
        json={"provider": "anthropic", "api_key": raw_key},
        headers=_auth_headers(token),
    )
    assert response.status_code == 201, response.text

    with session_factory() as db:
        row = db.query(models.WorkspaceApiKey).filter_by(workspace_id=workspace_id).one()
        # The raw secret must never appear anywhere in the stored column,
        # and the stored value must genuinely differ from the raw key.
        assert raw_key not in row.encrypted_key
        assert row.encrypted_key != raw_key
        assert row.last_four == raw_key[-4:]
        # Round-trips back to the original via the real decrypt path.
        assert crypto.decrypt(row.encrypted_key) == raw_key


def test_add_api_key_normalizes_provider_case(client: TestClient) -> None:
    token, _ = _sign_in(client, "casing@example.com")
    response = client.post(
        "/settings/api-keys",
        json={"provider": "  OpenAI  ", "api_key": "sk-abcd1234"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 201, response.text
    assert response.json()["provider"] == "openai"


def test_add_api_key_upserts_existing_provider(
    client: TestClient, session_factory: sessionmaker
) -> None:
    token, workspace_id = _sign_in(client, "upsert@example.com")

    first = client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-firstvalue1111"},
        headers=_auth_headers(token),
    )
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-secondvalue2222"},
        headers=_auth_headers(token),
    )
    assert second.status_code == 201
    assert second.json()["id"] == first_id  # same row, replaced in place
    assert second.json()["last_four"] == "2222"

    with session_factory() as db:
        rows = db.query(models.WorkspaceApiKey).filter_by(workspace_id=workspace_id).all()
        assert len(rows) == 1  # not two rows for the same provider
        assert crypto.decrypt(rows[0].encrypted_key) == "sk-secondvalue2222"


def test_add_api_key_rejects_blank_provider(client: TestClient) -> None:
    token, _ = _sign_in(client, "blankprovider@example.com")
    response = client.post(
        "/settings/api-keys",
        json={"provider": "   ", "api_key": "sk-abcd1234"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422


def test_add_api_key_rejects_too_short_key(client: TestClient) -> None:
    token, _ = _sign_in(client, "shortkey@example.com")
    response = client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "abc"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422


def test_list_api_keys_returns_multiple_providers_sorted(client: TestClient) -> None:
    token, _ = _sign_in(client, "multi@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-openaikey1111"},
        headers=_auth_headers(token),
    )
    client.post(
        "/settings/api-keys",
        json={"provider": "anthropic", "api_key": "sk-anthropickey2222"},
        headers=_auth_headers(token),
    )

    response = client.get("/settings/api-keys", headers=_auth_headers(token))
    assert response.status_code == 200
    providers = [row["provider"] for row in response.json()]
    assert providers == ["anthropic", "openai"]  # alphabetical
    for row in response.json():
        assert set(row.keys()) == {"id", "provider", "last_four", "base_url", "created_at"}


def test_delete_api_key_removes_it(client: TestClient, session_factory: sessionmaker) -> None:
    token, workspace_id = _sign_in(client, "delete@example.com")
    add_response = client.post(
        "/settings/api-keys",
        json={"provider": "gemini", "api_key": "sk-geminikey3333"},
        headers=_auth_headers(token),
    )
    key_id = add_response.json()["id"]

    delete_response = client.delete(f"/settings/api-keys/{key_id}", headers=_auth_headers(token))
    assert delete_response.status_code == 204

    listing = client.get("/settings/api-keys", headers=_auth_headers(token))
    assert listing.json() == []

    with session_factory() as db:
        assert db.query(models.WorkspaceApiKey).filter_by(workspace_id=workspace_id).all() == []


def test_delete_unknown_api_key_returns_404(client: TestClient) -> None:
    token, _ = _sign_in(client, "deletemissing@example.com")
    response = client.delete("/settings/api-keys/999999", headers=_auth_headers(token))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------


def test_second_users_workspace_keys_are_never_visible_to_another_user(
    client: TestClient,
) -> None:
    token_a, _ = _sign_in(client, "workspace-a@example.com")
    token_b, _ = _sign_in(client, "workspace-b@example.com")

    client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-workspaceakey1111"},
        headers=_auth_headers(token_a),
    )

    # User B's listing is empty - A's key never appears.
    listing_b = client.get("/settings/api-keys", headers=_auth_headers(token_b))
    assert listing_b.status_code == 200
    assert listing_b.json() == []


def test_second_user_cannot_delete_first_users_api_key(client: TestClient) -> None:
    token_a, _ = _sign_in(client, "owner@example.com")
    token_b, _ = _sign_in(client, "intruder@example.com")

    add_response = client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-ownerkey1111"},
        headers=_auth_headers(token_a),
    )
    key_id = add_response.json()["id"]

    delete_response = client.delete(f"/settings/api-keys/{key_id}", headers=_auth_headers(token_b))
    assert delete_response.status_code == 404  # not found from B's perspective, never leaked

    # Still present for the real owner.
    listing_a = client.get("/settings/api-keys", headers=_auth_headers(token_a))
    assert len(listing_a.json()) == 1


def test_second_user_renaming_workspace_does_not_affect_first_users_workspace(
    client: TestClient,
) -> None:
    token_a, workspace_a_id = _sign_in(client, "renamer-a@example.com")
    token_b, _ = _sign_in(client, "renamer-b@example.com")

    client.patch("/settings/workspace", json={"name": "B's renamed workspace"}, headers=_auth_headers(token_b))

    response_a = client.get("/settings/workspace", headers=_auth_headers(token_a))
    assert response_a.json()["name"] != "B's renamed workspace"


# ---------------------------------------------------------------------------
# Encryption-not-configured failure mode
# ---------------------------------------------------------------------------


def test_add_api_key_fails_loudly_when_encryption_key_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _ = _sign_in(client, "noenckey@example.com")

    monkeypatch.delenv(crypto.ENV_VAR, raising=False)
    crypto.reset_cache_for_tests()

    response = client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-shouldnotpersist1111"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 500
    assert crypto.ENV_VAR in response.json()["detail"]
