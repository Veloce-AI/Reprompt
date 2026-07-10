"""Tests for POST /auth/request-link, POST /auth/verify, GET /auth/me, and
the get_current_user dependency.

Same TestClient + in-memory SQLite pattern as test_pipelines.py /
test_rubrics.py. request-link's dev-mode-link behavior is exercised by
directly monkeypatching refract_api.auth.DEV_MODE_LINKS (computed once at
import time from an env var, so flipping the env var after import wouldn't
take effect - this is the straightforward way to test both branches).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from refract_api import models
from refract_api.auth import create_session_token
from refract_api.db import get_db
from refract_api.main import app
from refract_api.models import Base

import refract_api.auth as auth_module


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


def _request_and_extract_token(client: TestClient, email: str) -> str:
    response = client.post("/auth/request-link", json={"email": email})
    assert response.status_code == 200, response.text
    link = response.json()["dev_magic_link"]
    assert link is not None
    return _extract_token(link)


# ---------------------------------------------------------------------------
# POST /auth/request-link
# ---------------------------------------------------------------------------


def test_request_link_creates_token_but_not_a_user(
    client: TestClient, session_factory: sessionmaker
) -> None:
    response = client.post("/auth/request-link", json={"email": "new@example.com"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "message" in body
    # DEV_MODE_LINKS defaults to True (no real email provider configured).
    assert body["dev_magic_link"] is not None
    assert "token=" in body["dev_magic_link"]

    with session_factory() as db:
        tokens = db.scalars(select(models.MagicLinkToken)).all()
        assert len(tokens) == 1
        assert tokens[0].email == "new@example.com"
        # Never the raw token - only a hash.
        assert tokens[0].token_hash != _extract_token(body["dev_magic_link"])
        assert len(tokens[0].token_hash) == 64  # sha256 hex digest

        assert db.scalars(select(models.User)).all() == []
        assert db.scalars(select(models.Workspace)).all() == []


def test_request_link_response_shape_identical_for_any_email(client: TestClient) -> None:
    """Anti-enumeration: the response never depends on whether the address
    is already registered - request-link doesn't even query users, so any
    two emails get the exact same response shape.
    """
    response_a = client.post("/auth/request-link", json={"email": "first@example.com"})
    response_b = client.post("/auth/request-link", json={"email": "second@example.com"})
    assert response_a.status_code == response_b.status_code == 200
    assert set(response_a.json().keys()) == set(response_b.json().keys())
    assert response_a.json()["message"] == response_b.json()["message"]


def test_request_link_rejects_malformed_email(client: TestClient) -> None:
    response = client.post("/auth/request-link", json={"email": "not-an-email"})
    assert response.status_code == 422


def test_request_link_dev_mode_off_hides_the_link(
    client: TestClient, session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_module, "DEV_MODE_LINKS", False)

    response = client.post("/auth/request-link", json={"email": "prod@example.com"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dev_magic_link"] is None
    # Still a generic success message - not an error, not a leak.
    assert "message" in body

    # The token is still created (just has no delivery channel in this env).
    with session_factory() as db:
        tokens = db.scalars(select(models.MagicLinkToken)).all()
        assert len(tokens) == 1
        assert tokens[0].email == "prod@example.com"


# ---------------------------------------------------------------------------
# POST /auth/verify
# ---------------------------------------------------------------------------


def test_verify_valid_token_creates_user_and_workspace_and_returns_session(
    client: TestClient, session_factory: sessionmaker
) -> None:
    token = _request_and_extract_token(client, "alice@example.com")

    response = client.post("/auth/verify", json={"token": token})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["workspace"]["name"]
    assert isinstance(body["session_token"], str) and "." in body["session_token"]

    with session_factory() as db:
        users = db.scalars(select(models.User)).all()
        assert len(users) == 1
        assert users[0].email == "alice@example.com"

        workspaces = db.scalars(select(models.Workspace)).all()
        assert len(workspaces) == 1
        assert workspaces[0].owner_user_id == users[0].id

        token_row = db.scalars(select(models.MagicLinkToken)).one()
        assert token_row.used_at is not None


def test_lazy_account_creation_only_happens_on_verify_not_request(
    client: TestClient, session_factory: sessionmaker
) -> None:
    token = _request_and_extract_token(client, "lazy@example.com")

    with session_factory() as db:
        assert db.scalars(select(models.User)).all() == []
        assert db.scalars(select(models.Workspace)).all() == []

    client.post("/auth/verify", json={"token": token})

    with session_factory() as db:
        assert len(db.scalars(select(models.User)).all()) == 1
        assert len(db.scalars(select(models.Workspace)).all()) == 1


def test_verify_second_login_reuses_existing_user_and_workspace(
    client: TestClient, session_factory: sessionmaker
) -> None:
    token_1 = _request_and_extract_token(client, "repeat@example.com")
    first = client.post("/auth/verify", json={"token": token_1}).json()

    token_2 = _request_and_extract_token(client, "repeat@example.com")
    second = client.post("/auth/verify", json={"token": token_2}).json()

    assert first["user"]["id"] == second["user"]["id"]
    assert first["workspace"]["id"] == second["workspace"]["id"]

    with session_factory() as db:
        assert len(db.scalars(select(models.User)).all()) == 1
        assert len(db.scalars(select(models.Workspace)).all()) == 1


def test_verify_rejects_already_used_token(client: TestClient) -> None:
    token = _request_and_extract_token(client, "reuse@example.com")

    first = client.post("/auth/verify", json={"token": token})
    assert first.status_code == 200

    second = client.post("/auth/verify", json={"token": token})
    assert second.status_code == 400
    assert "already been used" in second.json()["detail"]


def test_verify_rejects_garbage_token(client: TestClient) -> None:
    response = client.post("/auth/verify", json={"token": "this-was-never-issued"})
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"]


def test_verify_rejects_expired_token(
    client: TestClient, session_factory: sessionmaker
) -> None:
    raw_token = "expired-raw-token"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    with session_factory() as db:
        db.add(
            models.MagicLinkToken(
                token_hash=token_hash,
                email="stale@example.com",
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        db.commit()

    response = client.post("/auth/verify", json={"token": raw_token})
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]


# ---------------------------------------------------------------------------
# get_current_user / GET /auth/me
# ---------------------------------------------------------------------------


def test_me_without_credentials_returns_401(client: TestClient) -> None:
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_with_garbage_bearer_token_returns_401(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_me_with_expired_session_token_returns_401(
    client: TestClient, session_factory: sessionmaker
) -> None:
    token = _request_and_extract_token(client, "expiredsession@example.com")
    verify_body = client.post("/auth/verify", json={"token": token}).json()

    expired_session = create_session_token(
        verify_body["user"]["id"], verify_body["workspace"]["id"], ttl=timedelta(seconds=-1)
    )

    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {expired_session}"}
    )
    assert response.status_code == 401


def test_me_with_valid_session_returns_user_and_workspace(client: TestClient) -> None:
    token = _request_and_extract_token(client, "bob@example.com")
    verify_body = client.post("/auth/verify", json={"token": token}).json()
    session_token = verify_body["session_token"]

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {session_token}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["email"] == "bob@example.com"
    assert body["workspace"]["id"] == verify_body["workspace"]["id"]
