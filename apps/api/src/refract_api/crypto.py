"""Encryption at rest for workspace-owned secrets (BYOK provider API keys,
screen 9 / M5).

Per the master build prompt §4 screen 9 ("encrypted at rest, never displayed
after save") and working rule 6 ("Never hardcode API keys"), a BYOK provider
key must never be stored as plaintext, even though the *encryption* key
itself is a different kind of secret than the model-provider keys rule 6
talks about. Same spirit applies to both: real secret, sourced from the
environment, never hardcoded.

Approach: Fernet (symmetric, from the `cryptography` package) - the standard
simple choice for "encrypt this blob, decrypt it later with the same key."
It's authenticated (AES-128-CBC + HMAC under the hood) so tampering is
detected, not just confidentiality - more than "XOR with a secret," no more
complex than necessary for a single-tenant-per-workspace secret store.

Fail loudly, but at first *use* - not at process startup
-----------------------------------------------------------
`REFRACT_SETTINGS_ENCRYPTION_KEY` must be set to a real Fernet key (32
url-safe base64-encoded bytes - `Fernet.generate_key()`) before any BYOK key
can be stored or read. Two ways to enforce that: crash the whole app at
import time if it's missing, or raise the moment code actually tries to
encrypt/decrypt. This module does the latter (`_fernet()` reads the env var
lazily, on first call, via `lru_cache` so it's only read once).

Why not crash at startup: unlike `REFRACT_SESSION_SECRET` (auth.py), which
falls back to an insecure dev default so *something* works locally, there is
no safe fallback for an encryption key - a default value would defeat
"encrypted at rest" entirely (anyone reading the source would have the key).
But the rest of the API (health check, pipelines, rubrics, migrations, even
`/settings/workspace`'s name-only endpoints) has nothing to do with BYOK
keys and shouldn't become unusable in an environment that hasn't configured
this yet. So the failure is scoped to exactly the code path that needs
it - the moment `/settings/api-keys` (POST, list, or delete's future
decrypt use) actually calls `encrypt()`/`decrypt()`, not at process boot.
"""

from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

ENV_VAR = "REFRACT_SETTINGS_ENCRYPTION_KEY"


class EncryptionNotConfigured(RuntimeError):
    """Raised the moment encrypt()/decrypt() is called without a valid
    REFRACT_SETTINGS_ENCRYPTION_KEY set - see module docstring for why this
    is deferred to first use rather than raised at import time.
    """


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw = os.environ.get(ENV_VAR)
    if not raw:
        raise EncryptionNotConfigured(
            f"{ENV_VAR} is not set. Refract encrypts BYOK provider API keys at "
            "rest and refuses to store or read them without a real encryption "
            "key (never a hardcoded or default one - see refract_api.crypto). "
            "Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"\n'
            f"and set it as {ENV_VAR} before using the /settings/api-keys endpoints."
        )
    try:
        return Fernet(raw.encode("ascii") if isinstance(raw, str) else raw)
    except Exception as exc:  # noqa: BLE001 - re-raised as our own clear error type
        raise EncryptionNotConfigured(
            f"{ENV_VAR} is set but is not a valid Fernet key (must be 32 "
            "url-safe base64-encoded bytes, e.g. from Fernet.generate_key())."
        ) from exc


def encrypt(plaintext: str) -> str:
    """Returns Fernet ciphertext as an ASCII string, ready to store in a
    Text column. Raises EncryptionNotConfigured if the env var isn't set.
    """
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Inverse of encrypt(). Not called anywhere in this milestone (see
    refract_api.settings module docstring for the deferred runtime-injection
    work that will need it) but provided now so the storage format is
    proven round-trippable, not just write-only.
    """
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Stored value could not be decrypted - wrong encryption key or corrupted data."
        ) from exc


def reset_cache_for_tests() -> None:
    """Test-only escape hatch: `_fernet()` is cached via lru_cache, but tests
    that monkeypatch REFRACT_SETTINGS_ENCRYPTION_KEY between cases need the
    next call to re-read the env var instead of reusing a stale Fernet
    instance from an earlier test.
    """
    _fernet.cache_clear()
