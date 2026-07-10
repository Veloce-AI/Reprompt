"""Provider-agnostic BYOK LLM access — the only place `packages/core` calls a model provider.

See :mod:`refract_core.llm.client` and :mod:`refract_core.llm.registry` for
the module-level docs. This subpackage is intentionally not imported by
``refract_core/__init__.py`` (same pattern as ``embedding.py``) so that
importing ``refract_core`` never pays LiteLLM's import cost unless a caller
actually reaches for ``refract_core.llm``.
"""

from refract_core.llm.client import (
    AuthenticationLLMError,
    LLMResponse,
    Message,
    MissingAPIKeyError,
    PermanentLLMError,
    RefractLLMError,
    TransientLLMError,
    UnknownLLMError,
    UnsupportedFeatureError,
    complete,
)
from refract_core.llm.registry import (
    ModelCapabilities,
    get_model_capabilities,
    missing_credential_env_vars,
    supports_json_mode,
)

__all__ = [
    "Message",
    "LLMResponse",
    "complete",
    "RefractLLMError",
    "MissingAPIKeyError",
    "AuthenticationLLMError",
    "TransientLLMError",
    "PermanentLLMError",
    "UnsupportedFeatureError",
    "UnknownLLMError",
    "ModelCapabilities",
    "get_model_capabilities",
    "supports_json_mode",
    "missing_credential_env_vars",
]
