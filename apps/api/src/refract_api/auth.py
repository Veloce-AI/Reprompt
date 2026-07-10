"""Magic-link auth endpoints (M5, screen boundary per
``refract-master-build-prompt.md`` §4: "email magic-link, single workspace
per user. No teams/RBAC yet.").

Flow
----
1. ``POST /auth/request-link`` - user submits an email. A random token is
   generated, its **hash** is stored (never the raw token - see
   ``models.MagicLinkToken``), and the "email" is "sent". No ``User`` row is
   created here.
2. User clicks the link, which hits the web app's ``/auth/verify?token=...``
   route, which calls ``POST /auth/verify`` with the raw token.
3. ``/auth/verify`` looks the token up by hash, checks it's unused and
   unexpired, marks it used, and **lazily** creates the ``User`` + their
   single ``Workspace`` on first successful verification. Returns a signed
   session token.
4. Subsequent requests that need identity pass that session token as
   ``Authorization: Bearer <token>`` and get resolved via
   ``get_current_user``.

Why account creation is lazy (deferred to verify, not request)
----------------------------------------------------------------
If ``/auth/request-link`` created the ``User`` immediately, a typo'd or
someone-else's email that never actually clicks the link would still leave a
permanent, un-owned account in the database. Creating the account only once
someone has proven control of the inbox (by producing the token that was
"mailed" to it) means every ``User`` row corresponds to an address someone
actually verified.

Why the response never reveals whether an email is already registered
-------------------------------------------------------------------------
``/auth/request-link`` does the exact same thing (mint a token, "send" it)
regardless of whether a ``User`` with that email exists yet - it never even
queries the ``users`` table. That's what makes the response shape naturally
uniform: there is no account-existence branch to leak in the first place.

Dev-mode magic links: a documented, gated MVP gap
----------------------------------------------------
There is no real email-sending provider (SMTP/SendGrid/SES/etc) configured
in this environment - same situation as "no LLM key yet" elsewhere in this
codebase. Rather than fake success silently, the raw magic-link URL is
returned directly in the ``/auth/request-link`` response body (and logged to
the server console) **only** when ``REFRACT_DEV_MAGIC_LINKS`` is enabled
(defaults to **on**, since there is nothing else that could deliver the link
right now). This is intentionally loud, not silent:

* The response schema always includes a ``dev_magic_link`` field so it's
  obvious in the API docs / any client that this exists.
* Logging the link is gated behind the exact same flag as returning it in
  the response - never unconditional - because a magic link IS a live
  single-use login credential. Logging it unconditionally would mean any
  production log aggregator becomes an account-takeover vector. Flip
  ``REFRACT_DEV_MAGIC_LINKS=false`` (and wire in a real provider - not done
  yet) before any real deployment.
* With the flag off, the token is still generated and stored; there's just
  no channel yet that delivers it to the user. That is the known,
  intentional MVP gap - tracked here, not papered over.

Rate limiting is explicitly out of scope for this task (noted, not built) -
``/auth/request-link`` has no per-IP/per-email throttling yet.

Session token mechanism
------------------------
A minimal HMAC-signed token, not a library-provided JWT and not a DB-backed
session table: ``base64url(json({"user_id", "workspace_id", "exp"})) + "." +
hex(hmac_sha256(secret, payload))``. Chosen over pulling in a JWT library or
``itsdangerous`` because the entire need is "tamper-evident, expiring,
server-verifiable blob" - three stdlib primitives (``hmac``, ``hashlib``,
``base64``) cover that completely without a new dependency, and it's exactly
as auditable as reading this file. Deliberately NOT full JWT (no header/alg
negotiation, no refresh tokens, no revocation list) - this is MVP auth for a
single-workspace product, not a multi-tenant identity platform.

``REFRACT_SESSION_SECRET`` must be set to a real secret before any real
deployment - see the warning logged at import time if it isn't.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from refract_api import models
from refract_api.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Config (env-driven, see module docstring for what each flag/secret means)
# ---------------------------------------------------------------------------

MAGIC_LINK_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=7)

WEB_BASE_URL = os.environ.get("REFRACT_WEB_BASE_URL", "http://localhost:5173")


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# Defaults to True: there is no real email provider configured in this
# environment (see module docstring), so this is the only way a locally
# running instance can complete the auth flow at all right now.
DEV_MODE_LINKS = _env_flag("REFRACT_DEV_MAGIC_LINKS", default=True)

SESSION_SECRET = os.environ.get("REFRACT_SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = "dev-insecure-session-secret-do-not-use-in-production"
    logger.warning(
        "REFRACT_SESSION_SECRET is not set - falling back to an insecure "
        "default signing key. Fine for local dev; anyone who knows this "
        "default can forge session tokens, so a real secret MUST be set "
        "via REFRACT_SESSION_SECRET before any real deployment."
    )

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Session token: sign / verify
# ---------------------------------------------------------------------------


def create_session_token(user_id: int, workspace_id: int, ttl: timedelta = SESSION_TTL) -> str:
    payload = {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "exp": int((datetime.now(timezone.utc) + ttl).timestamp()),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        SESSION_SECRET.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def _verify_session_token(token: str) -> dict | None:
    """Returns the decoded payload if `token` has a valid, unexpired
    signature, else None. Never raises - any malformed input just fails
    verification.
    """
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError:
        return None

    expected_signature = hmac.new(
        SESSION_SECRET.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        return None

    if not isinstance(payload, dict) or "exp" not in payload or "user_id" not in payload:
        return None
    if datetime.now(timezone.utc).timestamp() > payload["exp"]:
        return None

    return payload


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite doesn't actually preserve tzinfo through a round-trip even on
    a `DateTime(timezone=True)` column - values read back can come back
    naive. Normalize to UTC-aware before comparing against `datetime.now()`
    so this doesn't crash on "can't compare offset-naive and offset-aware
    datetimes" depending on whether a value was just constructed in Python
    or reloaded from the DB.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ---------------------------------------------------------------------------
# get_current_user dependency
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """Reusable auth dependency for any router that wants to require a
    signed-in user. Deliberately NOT applied to pipelines.py/rubrics.py/
    migrations.py in this task - whether/how those become workspace-scoped
    is a separate, bigger decision, out of scope here (see auth.py's task
    brief). Proven via GET /auth/me below.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=401, detail="Sign in required. Request a magic link at /login."
        )

    payload = _verify_session_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="Your session is invalid or has expired. Sign in again at /login.",
        )

    user = db.get(models.User, payload["user_id"])
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Your session is invalid or has expired. Sign in again at /login.",
        )
    return user


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class RequestLinkIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL_RE.match(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


class RequestLinkOut(BaseModel):
    message: str
    # Only ever populated when DEV_MODE_LINKS is on - see module docstring.
    dev_magic_link: str | None = None


class VerifyIn(BaseModel):
    token: str = Field(min_length=1)


class UserOut(BaseModel):
    id: int
    email: str


class WorkspaceOut(BaseModel):
    id: int
    name: str


class VerifyOut(BaseModel):
    session_token: str
    user: UserOut
    workspace: WorkspaceOut


class MeOut(BaseModel):
    user: UserOut
    workspace: WorkspaceOut


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/request-link", response_model=RequestLinkOut)
def request_link(body: RequestLinkIn, db: Session = Depends(get_db)) -> RequestLinkOut:
    """Mint a magic-link token for `body.email` and "send" it. See module
    docstring for the enumeration-safety and lazy-account-creation design -
    this never touches the `users` table at all.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + MAGIC_LINK_TTL

    db.add(
        models.MagicLinkToken(
            token_hash=token_hash,
            email=body.email,
            expires_at=expires_at,
        )
    )
    db.commit()

    link = f"{WEB_BASE_URL}/auth/verify?token={raw_token}"

    dev_link: str | None = None
    if DEV_MODE_LINKS:
        # Dev-only fallback - see module docstring. Never log the raw token
        # unless this flag is explicitly on.
        logger.info("[dev-only] magic link for %s: %s", body.email, link)
        dev_link = link
    # else: no real email-sending provider is wired up in this environment
    # yet (documented MVP gap). The token is still created and valid; the
    # requester just has no channel to receive it until a real provider is
    # configured and REFRACT_DEV_MAGIC_LINKS is turned off.

    return RequestLinkOut(
        message="If that address can receive mail, a sign-in link is on its way.",
        dev_magic_link=dev_link,
    )


@router.post("/verify", response_model=VerifyOut)
def verify(body: VerifyIn, db: Session = Depends(get_db)) -> VerifyOut:
    """Exchange a raw magic-link token for a session. Lazily creates the
    User + their Workspace on first successful verification (see module
    docstring).
    """
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    record = db.scalar(
        select(models.MagicLinkToken).where(models.MagicLinkToken.token_hash == token_hash)
    )

    if record is None:
        raise HTTPException(
            status_code=400,
            detail="This link is invalid. Request a new one from the sign-in page.",
        )
    if record.used_at is not None:
        raise HTTPException(
            status_code=400,
            detail="This link has already been used. Request a new one from the sign-in page.",
        )

    now = datetime.now(timezone.utc)
    if now > _as_aware_utc(record.expires_at):
        raise HTTPException(
            status_code=400,
            detail="This link has expired. Request a new one from the sign-in page.",
        )

    record.used_at = now

    user = db.scalar(select(models.User).where(models.User.email == record.email))
    if user is None:
        user = models.User(email=record.email)
        db.add(user)
        db.flush()  # assign user.id before creating its workspace
        workspace = models.Workspace(
            name=f"{record.email.split('@')[0]}'s workspace", owner_user_id=user.id
        )
        db.add(workspace)
    else:
        workspace = db.scalar(
            select(models.Workspace).where(models.Workspace.owner_user_id == user.id)
        )
        if workspace is None:
            # Defensive only - every User is created together with a
            # Workspace above, so this shouldn't be reachable. Repair rather
            # than 500 if it ever is.
            workspace = models.Workspace(
                name=f"{user.email.split('@')[0]}'s workspace", owner_user_id=user.id
            )
            db.add(workspace)

    db.commit()
    db.refresh(user)
    db.refresh(workspace)

    session_token = create_session_token(user.id, workspace.id)

    return VerifyOut(
        session_token=session_token,
        user=UserOut(id=user.id, email=user.email),
        workspace=WorkspaceOut(id=workspace.id, name=workspace.name),
    )


@router.get("/me", response_model=MeOut)
def me(
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)
) -> MeOut:
    """Proves get_current_user works end to end. Not used by any other
    router yet - see get_current_user's docstring.
    """
    workspace = db.scalar(
        select(models.Workspace).where(models.Workspace.owner_user_id == current_user.id)
    )
    if workspace is None:
        raise HTTPException(
            status_code=500,
            detail="No workspace found for this account. This shouldn't happen.",
        )
    return MeOut(
        user=UserOut(id=current_user.id, email=current_user.email),
        workspace=WorkspaceOut(id=workspace.id, name=workspace.name),
    )
