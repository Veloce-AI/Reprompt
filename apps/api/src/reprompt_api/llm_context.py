"""Per-request scoping of a workspace's stored BYOK provider key into a
single :func:`reprompt_core.llm.client.complete` call.

The gap this module closes
---------------------------
``reprompt_core.llm.client.complete()`` deliberately never accepts a raw
API key as a *public* function argument (see that module's docstring) —
it reads standard per-provider env vars (``OPENAI_API_KEY``,
``ANTHROPIC_API_KEY``, ...) via LiteLLM's own convention. But a
workspace's BYOK key lives encrypted in ``workspace_api_keys``
(:class:`reprompt_api.models.WorkspaceApiKey`), not in the process
environment. Something has to bridge the two, per request, without:

* ever logging the decrypted key,
* leaking one workspace's key into a *different* workspace's concurrent
  request — this is a multi-tenant service; two requests for two
  different workspaces (or the same workspace, two different providers)
  can genuinely be in flight in the same process at the same time, and
* permanently mutating the process-wide environment.

Two designs were considered
-----------------------------
1. **Env-var + lock.** ``os.environ[ENV_VAR] = decrypted_key`` right
   before calling ``complete()``, then restore/clear it in a ``finally``.
   The env var is process-wide *mutable, shared* state, so two concurrent
   requests racing on it is a real correctness bug, not a style nit:
   request A sets ``ANTHROPIC_API_KEY=keyA``, then yields control (every
   provider call is a network I/O await point — FastAPI can run other
   request handlers, including on other threads/tasks, while A is
   in-flight); request B (a different workspace) runs, sets
   ``ANTHROPIC_API_KEY=keyB`` before A's underlying HTTP client has
   actually consumed the value it read moments earlier — now A's call
   can end up authenticating with B's key (wrong workspace billed or
   authorized for another workspace's data), or B's own cleanup can clear
   the var out from under A mid-flight. The only way to make this safe is
   a lock that serializes *every single call* needing env-var injection,
   process-wide — i.e. the entire product's LLM throughput drops to one
   in-flight scoped call at a time. That is a real, known bottleneck this
   module deliberately avoids rather than papering over with "it'll
   probably be fine."

2. **Direct kwarg to LiteLLM — no env var involved at all.** LiteLLM's
   own ``completion()`` already accepts ``api_key`` as a plain keyword
   argument (verified directly against ``litellm/main.py``'s
   ``completion()`` signature: ``api_key: Optional[str] = None``, read
   ahead of any env-var fallback for every provider branch), completely
   independent of the env-var convention. ``reprompt_core.llm.client.complete()``
   already forwards ``**extra_params`` straight into
   ``litellm.completion(**params)`` unmodified, so a credential handed to
   it this way never touches ``os.environ`` at all. It lives only in
   local variables on *this request's own call stack*:
   :func:`resolve_workspace_credential` decrypts into a local ``str`` ->
   passed down as a keyword argument -> LiteLLM's own per-call ``api_key``
   parameter. No object shared between requests is ever written to, so
   there is nothing to race on — concurrent requests for different
   workspaces/providers proceed fully in parallel with no lock.

**Chosen: option 2** (:func:`complete_with_workspace_credentials` below).
It is strictly safer (no shared mutable state to race on, so no possible
cross-workspace leak by construction — not "leak prevented by careful
locking," but "there is no shared variable to leak through") and strictly
faster (no serializing lock, no throughput ceiling) than option 1. The
only cost was a small, explicitly-internal, clearly-named escape hatch on
``reprompt_core.llm.client.complete()`` — ``_scoped_api_key`` — rather than
a public ``api_key=`` parameter a careless caller could reach for and
have logged. Nothing outside this module ever passes that parameter.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import litellm
from sqlalchemy import select
from sqlalchemy.orm import Session

from reprompt_core.llm.client import LLMResponse, Message, complete
from reprompt_core.llm.registry import get_model_capabilities

from reprompt_api import models
from reprompt_api.crypto import decrypt

__all__ = [
    "ProviderKeyNotConfigured",
    "resolve_workspace_credential",
    "complete_with_workspace_credentials",
]


class ProviderKeyNotConfigured(Exception):
    """This workspace has no saved BYOK key for the provider a requested
    model needs.

    Deliberately distinct from :class:`reprompt_core.llm.client.MissingAPIKeyError`
    (which talks in terms of environment variables — an implementation
    detail a BYOK workspace user never configures directly and would find
    confusing). This is the "you haven't added this in Settings yet"
    message such a user can actually act on. Callers (see
    ``reprompt_api.pipelines``'s ``/test-prompt`` endpoint) catch this
    specifically and turn it into a 4xx response naming the provider and
    pointing at ``/settings``.
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(
            f"No API key configured for provider '{provider}' in this workspace. "
            "Add one at /settings before testing a model from this provider."
        )


def _provider_for_model(model: str) -> str | None:
    try:
        return litellm.get_llm_provider(model)[1]
    except Exception:
        return None


def _find_workspace_key_row(
    db: Session, workspace: models.Workspace, provider: str
) -> models.WorkspaceApiKey | None:
    return db.scalar(
        select(models.WorkspaceApiKey).where(
            models.WorkspaceApiKey.workspace_id == workspace.id,
            models.WorkspaceApiKey.provider == provider,
        )
    )


def _resolve_workspace_key_row(
    db: Session, workspace: models.Workspace, model: str
) -> models.WorkspaceApiKey:
    """Requires a saved row to exist - only call this for a model whose
    provider actually needs a credential (see the ``requires_api_key``
    check in :func:`complete_with_workspace_credentials`). Calling this
    unconditionally for *every* model, including no-key-required
    local/self-hosted ones (Ollama, vLLM), was a real bug: it demanded a
    workspace key even for a model
    :class:`reprompt_core.llm.registry.ModelCapabilities` itself reports
    as ``requires_api_key=False`` — every other surface in this codebase
    (the registry, the curated model list, Settings, the migration
    wizard) already agrees local models need no key; this function just
    hadn't been told."""
    provider = _provider_for_model(model)
    if provider is None:
        raise ProviderKeyNotConfigured(model)

    row = _find_workspace_key_row(db, workspace, provider)
    if row is None:
        raise ProviderKeyNotConfigured(provider)

    return row


def resolve_workspace_credential(db: Session, workspace: models.Workspace, model: str) -> str:
    """Decrypt and return the plaintext BYOK key ``workspace`` has saved
    for the provider ``model`` routes to.

    Raises :class:`ProviderKeyNotConfigured` if the provider can't be
    determined from ``model`` at all, or if no key is saved for it in
    this workspace. The returned string is meant to live only in a local
    variable for the duration of exactly one
    :func:`complete_with_workspace_credentials` call — see the module
    docstring for why that (rather than any shared/global placement)
    matters for concurrency safety. Propagates
    :class:`reprompt_api.crypto.EncryptionNotConfigured` (encryption key
    missing — a deployment config problem, not a per-workspace one) and
    ``ValueError`` (stored ciphertext could not be decrypted — a data
    integrity problem) unchanged; callers should treat both as 500s, not
    as "this workspace needs to add a key."
    """
    row = _resolve_workspace_key_row(db, workspace, model)
    return decrypt(row.encrypted_key)


def complete_with_workspace_credentials(
    db: Session,
    workspace: models.Workspace,
    model: str,
    messages: Sequence[Message],
    **kwargs: Any,
) -> LLMResponse:
    """:func:`reprompt_core.llm.client.complete`, scoped to ``workspace``'s
    saved key for ``model``'s provider.

    See the module docstring for why the credential is passed as a direct,
    per-call keyword argument (via ``complete()``'s internal
    ``_scoped_api_key``) rather than by mutating the process environment —
    that is what makes this safe under concurrent requests for different
    workspaces without any locking.

    If the workspace's saved key also has a ``base_url`` (customer
    self-hosted endpoint — Ollama/vLLM/LM Studio/etc), it's forwarded as
    ``api_base`` the same way: a local value on this call's own stack,
    never an env var, never shared with any other request. A caller that
    already passed its own ``api_base`` in ``**kwargs`` wins (rare —
    workspace-level config is the normal path).

    Raises :class:`ProviderKeyNotConfigured` (not
    :class:`~reprompt_core.llm.client.MissingAPIKeyError`) if ``workspace``
    has no saved key for the required provider — callers should catch
    this specifically to build a "configure it in Settings" error
    response, not ``reprompt_core.llm.client``'s env-var-flavored one.

    A model whose provider needs no credential at all (Ollama, vLLM — see
    :class:`reprompt_core.llm.registry.ModelCapabilities.requires_api_key`)
    skips the "must have a saved row" requirement entirely: no
    :class:`ProviderKeyNotConfigured`, ever, for these. A workspace row
    for that provider is still picked up and used *if one happens to
    exist* (e.g. a custom ``base_url`` pointing at a remote Ollama
    instance), purely as an optional override — its absence is never an
    error for a no-key-required model.
    """
    if not get_model_capabilities(model).requires_api_key:
        provider = _provider_for_model(model)
        row = _find_workspace_key_row(db, workspace, provider) if provider else None
        if row and row.base_url:
            kwargs.setdefault("api_base", row.base_url)
        return complete(model, messages, **kwargs)

    row = _resolve_workspace_key_row(db, workspace, model)
    scoped_key = decrypt(row.encrypted_key)
    if row.base_url:
        kwargs.setdefault("api_base", row.base_url)
    return complete(model, messages, _scoped_api_key=scoped_key, **kwargs)
