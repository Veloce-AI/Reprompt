"""Two-axis contract mining — structural invariant extraction (PDF §4.1, §4.4).

Axis A (vary context): run the stage on N different real inputs from existing
traces. Properties that are the same across all outputs are signals (invariants).

Axis B (repeat identical context): run the stage K times on the *same* input
at temperature > 0. Properties that vary here are noise, not invariants.

An output property is a CONTRACT INVARIANT iff it appears in all Axis A
outputs AND is not merely an Axis-B noise artefact.

This module is headless: it takes ``call`` (injected LLM callable) and
``entails`` (injected NLI boolean callable) so every function here is fully
unit-testable with fakes.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reprompt_core.budget import BudgetTracker
from reprompt_core.contract.cluster import cluster_by_meaning, semantic_entropy
from reprompt_core.llm.client import LLMResponse

__all__ = ["AssertionSpec", "MineExample", "MineInput", "MinedContract", "mine_contract"]

logger = logging.getLogger(__name__)

_TEMPLATE_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _render(template: str, data: dict[str, Any] | str) -> str:
    if not isinstance(data, dict):
        return template

    def _sub(m: re.Match[str]) -> str:
        k = m.group(1)
        v = data.get(k)
        if v is None:
            return m.group(0)
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)

    return _TEMPLATE_VAR.sub(_sub, template)


class AssertionSpec(BaseModel):
    """One mined or manual invariant — portable across the assertion registry."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="deterministic check type: required_keys, regex, enum_values, …")
    spec: dict[str, Any] = Field(description="predicate parameters matching the check type")
    description: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    id: int | None = Field(default=None, description="DB assertion row id, set by the API layer for counterexample tracking. Ignored by mining logic.")


class MineExample(BaseModel):
    """One existing trace record used as an Axis-A sample."""

    model_config = ConfigDict(extra="forbid")

    input: dict[str, Any]
    rendered_prompt: str
    output: str


class MineInput(BaseModel):
    """Everything needed to mine the contract for one stage."""

    model_config = ConfigDict(extra="forbid")

    stage_id: int
    prompt_template: str
    target_model: str
    params: dict[str, Any] = Field(default_factory=dict)
    examples: list[MineExample] = Field(min_length=1)
    axis_b_repeats: int = Field(default=3, ge=0, le=10)


class MinedContract(BaseModel):
    """Result of a two-axis mining run."""

    model_config = ConfigDict(extra="forbid")

    invariants: list[AssertionSpec]
    noise_floor: float = Field(
        ge=0.0,
        le=1.0,
        description="Proportion of Axis-B samples that fell outside the dominant cluster.",
    )
    entropy: float = Field(
        ge=0.0,
        description="Semantic entropy (nats) over Axis-A clusters — drift signal for Phase 7.",
    )
    samples_used: int
    axis_a_count: int
    axis_b_count: int


# ---------------------------------------------------------------------------
# Structural invariant extraction (heuristic, no NLI needed)
# ---------------------------------------------------------------------------


def _try_parse_json_objects(outputs: list[str]) -> list[dict[str, Any]] | None:
    """Return parsed dicts if every output is a JSON object, else None."""
    parsed = []
    for o in outputs:
        stripped = o.strip()
        try:
            val = json.loads(stripped)
            if not isinstance(val, dict):
                return None
            parsed.append(val)
        except json.JSONDecodeError:
            return None
    return parsed or None


def _longest_common_start(strings: list[str], min_length: int = 3) -> str:
    if not strings:
        return ""
    ref = strings[0]
    for i, ch in enumerate(ref):
        if not all(s[i : i + 1] == ch for s in strings[1:]):
            common = ref[:i].rstrip()
            return common if len(common) >= min_length else ""
    common = ref.rstrip()
    return common if len(common) >= min_length else ""


def _extract_invariants(outputs: list[str], noise_floor: float) -> list[AssertionSpec]:
    """Heuristic structural invariant extraction from a set of outputs."""
    if not outputs:
        return []
    confidence = max(0.0, 1.0 - noise_floor)
    invariants: list[AssertionSpec] = []

    json_objects = _try_parse_json_objects(outputs)
    if json_objects:
        common_keys = set(json_objects[0].keys())
        for obj in json_objects[1:]:
            common_keys &= set(obj.keys())
        if common_keys:
            invariants.append(
                AssertionSpec(
                    kind="required_keys",
                    spec={"keys": sorted(common_keys)},
                    description=f"Output always contains keys: {sorted(common_keys)}",
                    confidence=confidence,
                )
            )
        for key in sorted(common_keys):
            values = [str(obj[key]) for obj in json_objects if key in obj]
            unique = list(dict.fromkeys(values))
            # Only emit enum_values when the cardinality is small and sample is meaningful
            if 1 < len(unique) <= 5 and len(values) >= 3:
                invariants.append(
                    AssertionSpec(
                        kind="enum_values",
                        spec={"field": key, "values": unique},
                        description=f"Field '{key}' always has one of: {unique}",
                        confidence=confidence,
                    )
                )
    else:
        stripped = [o.strip() for o in outputs]
        common_prefix = _longest_common_start(stripped)
        if common_prefix:
            pattern = "^" + re.escape(common_prefix)
            invariants.append(
                AssertionSpec(
                    kind="regex",
                    spec={"pattern": pattern},
                    description=f"Output always starts with: '{common_prefix}'",
                    confidence=confidence,
                )
            )

    return invariants


# ---------------------------------------------------------------------------
# Two-axis mining
# ---------------------------------------------------------------------------


def mine_contract(
    mine_input: MineInput,
    *,
    call: Callable[..., LLMResponse],
    entails: Callable[[str, str], bool],
    budget: BudgetTracker,
) -> MinedContract:
    """Run the two-axis sampling protocol and return mined invariants.

    Axis A: existing outputs from ``mine_input.examples`` (no new LLM calls).
    Axis B: ``axis_b_repeats`` calls on the first example's rendered prompt
            at temperature > 0 to measure self-noise.
    """
    axis_a_outputs = [ex.output for ex in mine_input.examples]
    axis_b_outputs: list[str] = []

    # Axis B — run the first example's already-rendered prompt K times
    if mine_input.axis_b_repeats > 0 and mine_input.examples:
        rendered_b = mine_input.examples[0].rendered_prompt
        for _ in range(mine_input.axis_b_repeats):
            if budget.is_exhausted:
                break
            try:
                resp = call(
                    mine_input.target_model,
                    [{"role": "user", "content": rendered_b}],
                    temperature=0.7,
                )
                budget.record_spend(resp.cost_usd or 0.0, candidate_id="mine-axis-b")
                axis_b_outputs.append(resp.content)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Axis-B call failed: %s", exc)

    # Cluster Axis A → semantic entropy
    axis_a_clusters = cluster_by_meaning(axis_a_outputs, entails=entails)
    entropy = semantic_entropy(axis_a_clusters)

    # Noise floor from Axis B
    if axis_b_outputs:
        axis_b_clusters = cluster_by_meaning(axis_b_outputs, entails=entails)
        dominant = max(len(c) for c in axis_b_clusters) if axis_b_clusters else 0
        noise_floor = 1.0 - (dominant / len(axis_b_outputs))
    else:
        noise_floor = 0.0

    invariants = _extract_invariants(axis_a_outputs, noise_floor=noise_floor)

    return MinedContract(
        invariants=invariants,
        noise_floor=noise_floor,
        entropy=entropy,
        samples_used=len(axis_a_outputs) + len(axis_b_outputs),
        axis_a_count=len(axis_a_outputs),
        axis_b_count=len(axis_b_outputs),
    )
