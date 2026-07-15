"""Model card transform rules via read-only API.

Exposes the model_card module's transform rules as JSON, so the UI can display
what prompt transformations will be applied to a candidate prompt for a given
target model family.

Zero write operations, zero database queries — pure in-memory transformation
of the model_card module's data structures.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from reprompt_core.llm.model_card import (
    applicable_rules,
    resolve_family,
    is_small_variant,
    get_transform_rules,
)

router = APIRouter(prefix="/model-cards", tags=["model-cards"])


class TransformRuleOut(BaseModel):
    """Serializable transform rule for a model family."""
    name: str
    description: str
    applies_to: str  # "all" or "small_only"
    will_apply: bool  # True if this rule will actually fire for the target model


class FamilyCardOut(BaseModel):
    """Serializable model family card with its applicable rules."""
    family: str
    version: int
    description: str
    is_small_variant: bool
    rules: list[TransformRuleOut]


@router.get("/{model:path}")
def get_model_card(model: str) -> FamilyCardOut:
    """Get transform rules for a target model.

    Returns the resolved model family, its versioned rule set, and which rules
    will actually apply to this specific model (based on size detection).
    Never raises: falls back gracefully to generic family for unrecognized models.

    Parameters
    ----------
    model: LiteLLM model string (e.g. "claude-3-5-sonnet", "gpt-4o", "ollama/llama3")

    Returns
    -------
    FamilyCardOut with:
    - family: resolved family name
    - version: family card version
    - description: human-readable family description
    - is_small_variant: True if the model looks like a small/nano variant
    - rules: list of TransformRuleOut, in apply order, with will_apply flag
    """
    family = resolve_family(model)
    card = get_transform_rules(family)
    small = is_small_variant(model)

    # Compute which rules actually fire for this model
    applicable = applicable_rules(model)
    applicable_names = {rule.name for rule in applicable}

    rules_out = [
        TransformRuleOut(
            name=rule.name,
            description=rule.description,
            applies_to=rule.applies_to,
            will_apply=rule.name in applicable_names,
        )
        for rule in card.rules
    ]

    return FamilyCardOut(
        family=family,
        version=card.version,
        description=card.description,
        is_small_variant=small,
        rules=rules_out,
    )
