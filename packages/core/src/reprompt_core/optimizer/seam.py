"""Seam-level regression — re-validate downstream stages against a migrated
upstream stage's new output (PDF §2 Phase 4, §3, §7.4).

Per-call contract satisfaction is necessary but not sufficient for a pipeline.
A downstream stage's contract was validated against the *original* upstream
output distribution; swapping the upstream model shifts that distribution even
when the upstream still satisfies its own contract. This module checks the
seam: does the downstream stage, running its **original** prompt on the
**original** model, still produce correct output when the upstream changes?

Headless convention
-------------------
Zero FastAPI/DB imports. The caller (optimizer_runner.py) provides:
- ``call`` — the injected LLM-calling function
- ``budget`` — BudgetTracker to record / gate spend
- ``judge_model`` — for the downstream scoring (cross-family, as always)

Seam input substitution (v1 approximation)
------------------------------------------
The downstream stage's input dict typically contains the upstream stage's
output under the key matching the upstream ``source_id`` (e.g. a stage
``"root"`` puts its output into the downstream's ``{"root": "..."}`` input).
v1 substitutes that key. If the key is absent (the seam mapping can't be
inferred from source_id alone), the downstream is called with its original
inputs unchanged and ``SeamResult.substitution_applied`` is ``False`` — the
score then measures downstream stability rather than true seam impact.
Scoring uses det+embedding only (no judge) to keep the seam pass cheap,
mirroring the holdout pass rationale.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reprompt_core.budget import BudgetTracker
from reprompt_core.deterministic import parse_deterministic_checks
from reprompt_core.llm.client import LLMResponse
from reprompt_core.llm.model_card import apply_model_card_transform
from reprompt_core.scoring import score_candidate

__all__ = ["SeamExample", "SeamInput", "SeamResult", "evaluate_seam"]

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

logger = logging.getLogger(__name__)


class SeamExample(BaseModel):
    """One benchmark trace pair for a seam check."""

    model_config = ConfigDict(extra="forbid")

    upstream_input: dict[str, Any]
    upstream_baseline_output: str
    downstream_input: dict[str, Any]
    downstream_baseline_output: str


class SeamInput(BaseModel):
    """Everything needed to check one (upstream, downstream) stage seam."""

    model_config = ConfigDict(extra="forbid")

    upstream_stage_id: int
    upstream_source_id: str
    upstream_winning_prompt: str
    upstream_target_model: str
    upstream_params: dict[str, Any] = Field(default_factory=dict)

    downstream_stage_id: int
    downstream_original_prompt: str
    downstream_original_model: str
    downstream_rubric: dict[str, Any] = Field(default_factory=dict)

    examples: list[SeamExample] = Field(min_length=1)
    parity_threshold: float = 0.95


class SeamResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upstream_stage_id: int
    downstream_stage_id: int
    parity_score: float | None = Field(
        default=None,
        description="Mean composite score (det + embedding) of the downstream stage's output "
        "when given the migrated upstream output. None when every call failed or budget ran out.",
    )
    passed: bool
    substitution_applied: bool = Field(
        description="True when the upstream output was successfully substituted into the "
        "downstream input (keyed by upstream_source_id). False when the key was absent — "
        "score then reflects downstream stability, not true seam impact.",
    )
    reason: str


def evaluate_seam(
    seam_input: SeamInput,
    *,
    call: Callable[..., LLMResponse],
    budget: BudgetTracker,
) -> SeamResult:
    """Run one seam check: migrated upstream → original downstream → score.

    Steps per example:
    1. Run the winning upstream prompt on the upstream input → migrated output.
    2. Substitute migrated output into the downstream input under ``upstream_source_id``.
    3. Run the original downstream prompt on the (possibly modified) downstream input.
    4. Score downstream output vs baseline (det + embedding, no judge).
    Return mean score; passed = mean ≥ parity_threshold.
    """
    deterministic_checks = parse_deterministic_checks(
        seam_input.downstream_rubric.get("deterministic_checks") or []
    )
    up_prompt_transformed = apply_model_card_transform(
        seam_input.upstream_winning_prompt, seam_input.upstream_target_model
    )
    down_prompt_transformed = apply_model_card_transform(
        seam_input.downstream_original_prompt, seam_input.downstream_original_model
    )

    scores: list[float] = []
    any_substitution = False

    for ex in seam_input.examples:
        if budget.is_exhausted:
            break

        # Step 1 — run migrated upstream prompt.
        up_rendered = _render(up_prompt_transformed, ex.upstream_input)
        try:
            up_response = call(
                seam_input.upstream_target_model,
                [{"role": "user", "content": up_rendered}],
                temperature=seam_input.upstream_params.get("temperature", 0.0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Seam upstream call failed for stage %s: %s", seam_input.upstream_stage_id, exc)
            continue
        budget.record_spend(
            up_response.cost_usd or 0.0,
            candidate_id=f"seam-up-{seam_input.upstream_stage_id}",
        )
        migrated_up_output = up_response.content

        if budget.is_exhausted:
            break

        # Step 2 — substitute migrated upstream output into downstream input.
        down_input = dict(ex.downstream_input)
        substituted = seam_input.upstream_source_id in down_input
        if substituted:
            down_input[seam_input.upstream_source_id] = migrated_up_output
            any_substitution = True

        # Step 3 — run original downstream prompt on seam input.
        down_rendered = _render(down_prompt_transformed, down_input)
        try:
            down_response = call(
                seam_input.downstream_original_model,
                [{"role": "user", "content": down_rendered}],
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Seam downstream call failed for stage %s: %s", seam_input.downstream_stage_id, exc)
            continue
        budget.record_spend(
            down_response.cost_usd or 0.0,
            candidate_id=f"seam-down-{seam_input.downstream_stage_id}",
        )

        # Step 4 — score downstream output vs its baseline (det + embedding, no judge).
        try:
            composite = score_candidate(
                benchmark_output=ex.downstream_baseline_output,
                candidate_output=down_response.content,
                deterministic_checks=deterministic_checks,
                input=down_input,
                judge_score=None,
            )
            scores.append(composite.final_score)
        except ValueError as exc:
            logger.warning("Seam scoring failed for stage %s: %s", seam_input.downstream_stage_id, exc)

    if not scores:
        return SeamResult(
            upstream_stage_id=seam_input.upstream_stage_id,
            downstream_stage_id=seam_input.downstream_stage_id,
            parity_score=None,
            passed=False,
            substitution_applied=any_substitution,
            reason="No examples could be evaluated (all calls failed or budget exhausted).",
        )

    mean_score = sum(scores) / len(scores)
    passed = mean_score >= seam_input.parity_threshold
    sub_note = "" if any_substitution else " (upstream output key absent — downstream stability check only)"
    return SeamResult(
        upstream_stage_id=seam_input.upstream_stage_id,
        downstream_stage_id=seam_input.downstream_stage_id,
        parity_score=mean_score,
        passed=passed,
        substitution_applied=any_substitution,
        reason=(
            f"Downstream stage {seam_input.downstream_stage_id} scored "
            f"{mean_score:.3f} (threshold {seam_input.parity_threshold:.2f}) — "
            f"{'PASS' if passed else 'FAIL'}{sub_note}."
        ),
    )
