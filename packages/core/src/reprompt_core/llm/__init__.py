"""Provider-agnostic BYOK LLM access — the only place `packages/core` calls a model provider.

See :mod:`reprompt_core.llm.client` and :mod:`reprompt_core.llm.registry` for
the module-level docs. This subpackage is intentionally not imported by
``reprompt_core/__init__.py`` (same pattern as ``embedding.py``) so that
importing ``reprompt_core`` never pays LiteLLM's import cost unless a caller
actually reaches for ``reprompt_core.llm``.
"""

from reprompt_core.llm.client import (
    AuthenticationLLMError,
    LLMResponse,
    Message,
    MissingAPIKeyError,
    PermanentLLMError,
    RepromptLLMError,
    TransientLLMError,
    UnknownLLMError,
    UnsupportedFeatureError,
    complete,
)
from reprompt_core.llm.model_card import (
    FamilyCard,
    TransformRule,
    applicable_rules,
    apply_model_card_transform,
    get_transform_rules,
    is_small_variant,
    resolve_family,
)
from reprompt_core.llm.registry import (
    ModelCapabilities,
    get_model_capabilities,
    missing_credential_env_vars,
    supports_json_mode,
)

__all__ = [
    "Message",
    "LLMResponse",
    "complete",
    "RepromptLLMError",
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
    "TransformRule",
    "FamilyCard",
    "resolve_family",
    "is_small_variant",
    "get_transform_rules",
    "applicable_rules",
    "apply_model_card_transform",
]
