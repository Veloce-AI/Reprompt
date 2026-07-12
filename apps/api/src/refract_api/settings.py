"""Settings endpoints (screen 9, M5): workspace name + BYOK provider API keys.

Per the master build prompt §4 screen 9: "BYOK keys (per provider, encrypted
at rest, never displayed after save), workspace name." Every endpoint here
sits behind `get_current_user` (apps/api/src/refract_api/auth.py) - unlike
pipelines.py/rubrics.py/migrations.py, which are explicitly NOT
workspace-scoped yet, settings are inherently per-workspace secrets and must
never leak across workspaces.

Provider field: free text, not an enum - see the WorkspaceApiKey docstring
in models.py for the full reasoning (LiteLLM supports many providers; an
enum would need a migration for every new one, contradicting the "any
provider" design goal elsewhere in this project). Normalized to
lowercase/stripped here so "OpenAI" and "openai" are the same provider.

Upsert-by-provider, not delete-then-add
------------------------------------------
POST /settings/api-keys replaces any existing key for that (workspace,
provider) pair in place, rather than requiring the client to DELETE first.
A workspace has at most one *active* key per provider (enforced by
`uq_workspace_api_keys_workspace_provider`), so "add a key for a provider
that already has one" only ever means "rotate it" - there's no scenario
where a caller wants two simultaneous keys for the same provider name. Upsert
is also just less surface for the frontend to get wrong (one call instead of
"check if it exists, delete, then add").

Encryption
----------
The raw key is encrypted via refract_api.crypto.encrypt() (Fernet, keyed by
REFRACT_SETTINGS_ENCRYPTION_KEY) before it ever reaches the DB. If that env
var isn't set, crypto.encrypt() raises EncryptionNotConfigured, which this
module turns into a 500 with a clear, actionable message rather than a raw
stack trace - see _require_encryption_configured().

Explicitly OUT OF SCOPE here (deferred, not forgotten)
----------------------------------------------------------
Actually wiring a stored, encrypted key into `refract_core.llm.client`'s
runtime environment-variable lookup at call time - i.e. decrypting a
workspace's key and injecting it into the process env (or some other
per-request mechanism) before a LiteLLM call is made for that workspace.
That's a real, separate design problem (which workspace's key applies to a
given optimization run? per-request env mutation is not thread/async-safe;
does it get passed as a LiteLLM `api_key=` kwarg instead?) and deserves its
own careful design later, not bolted on as a side effect of this CRUD
surface. This module only proves storage/retrieval is correct.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from refract_api import models
from refract_api.auth import get_current_user
from refract_api.crypto import EncryptionNotConfigured, encrypt
from refract_api.db import get_db

router = APIRouter(prefix="/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class WorkspaceSettingsOut(BaseModel):
    name: str


class WorkspaceSettingsUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Workspace name can't be blank.")
        return stripped


class ApiKeyOut(BaseModel):
    id: int
    provider: str
    last_four: str
    base_url: str | None
    created_at: datetime.datetime


class ApiKeyCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    # Real provider keys (OpenAI/Anthropic/Gemini/etc) are always well over
    # 4 characters; requiring at least that many keeps last_four meaningful
    # and rejects obviously-empty/placeholder input without being precious
    # about any particular provider's exact key format (free text, per the
    # provider-field design note above).
    api_key: str = Field(min_length=4, max_length=4096)
    # Customer self-hosted endpoint (Ollama/vLLM/LM Studio/etc). Optional -
    # hosted providers never set this. Forwarded to LiteLLM as api_base by
    # refract_api.llm_context.complete_with_workspace_credentials.
    base_url: str | None = Field(default=None, max_length=512)

    @field_validator("provider")
    @classmethod
    def _normalize_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("Provider name can't be blank.")
        return normalized

    @field_validator("api_key")
    @classmethod
    def _not_blank_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("API key can't be blank.")
        return value

    @field_validator("base_url")
    @classmethod
    def _blank_base_url_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_workspace_or_500(db: Session, user: models.User) -> models.Workspace:
    """Every authenticated User has exactly one Workspace (see auth.py /
    models.py) - a missing one is a data-integrity bug, not a client error.
    """
    workspace = db.scalar(
        select(models.Workspace).where(models.Workspace.owner_user_id == user.id)
    )
    if workspace is None:
        raise HTTPException(
            status_code=500,
            detail="No workspace found for this account. This shouldn't happen.",
        )
    return workspace


def _encrypt_or_500(raw_key: str) -> str:
    try:
        return encrypt(raw_key)
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _to_api_key_out(row: models.WorkspaceApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=row.id,
        provider=row.provider,
        last_four=row.last_four,
        base_url=row.base_url,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Workspace name
# ---------------------------------------------------------------------------


@router.get("/workspace", response_model=WorkspaceSettingsOut)
def get_workspace_settings(
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)
) -> WorkspaceSettingsOut:
    workspace = _get_workspace_or_500(db, current_user)
    return WorkspaceSettingsOut(name=workspace.name)


@router.patch("/workspace", response_model=WorkspaceSettingsOut)
def update_workspace_settings(
    update: WorkspaceSettingsUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceSettingsOut:
    workspace = _get_workspace_or_500(db, current_user)
    workspace.name = update.name
    db.commit()
    db.refresh(workspace)
    return WorkspaceSettingsOut(name=workspace.name)


# ---------------------------------------------------------------------------
# BYOK API keys
# ---------------------------------------------------------------------------


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ApiKeyOut]:
    """Never returns the full key, not even to the owner - only provider,
    last_four, and created_at, per the spec's "never displayed after save."
    """
    workspace = _get_workspace_or_500(db, current_user)
    rows = db.scalars(
        select(models.WorkspaceApiKey)
        .where(models.WorkspaceApiKey.workspace_id == workspace.id)
        .order_by(models.WorkspaceApiKey.provider)
    ).all()
    return [_to_api_key_out(row) for row in rows]


@router.post("/api-keys", response_model=ApiKeyOut, status_code=201)
def add_api_key(
    body: ApiKeyCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiKeyOut:
    """Add a key for a provider, or replace it if one already exists for
    this workspace - see module docstring for the upsert-vs-delete-then-add
    decision. The raw key is encrypted before it touches the DB and is
    never echoed back in the response.
    """
    workspace = _get_workspace_or_500(db, current_user)

    encrypted = _encrypt_or_500(body.api_key)
    last_four = body.api_key[-4:]

    existing = db.scalar(
        select(models.WorkspaceApiKey).where(
            models.WorkspaceApiKey.workspace_id == workspace.id,
            models.WorkspaceApiKey.provider == body.provider,
        )
    )
    if existing is not None:
        existing.encrypted_key = encrypted
        existing.last_four = last_four
        existing.base_url = body.base_url
        existing.created_at = datetime.datetime.now(datetime.timezone.utc)
        row = existing
    else:
        row = models.WorkspaceApiKey(
            workspace_id=workspace.id,
            provider=body.provider,
            encrypted_key=encrypted,
            last_four=last_four,
            base_url=body.base_url,
        )
        db.add(row)

    db.commit()
    db.refresh(row)
    return _to_api_key_out(row)


@router.delete("/api-keys/{key_id}", status_code=204)
def delete_api_key(
    key_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    workspace = _get_workspace_or_500(db, current_user)
    row = db.scalar(
        select(models.WorkspaceApiKey).where(
            models.WorkspaceApiKey.id == key_id,
            models.WorkspaceApiKey.workspace_id == workspace.id,
        )
    )
    if row is None:
        # Same 404 whether the id never existed or belongs to a different
        # workspace - never confirm/deny another workspace's key exists.
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")
    db.delete(row)
    db.commit()
