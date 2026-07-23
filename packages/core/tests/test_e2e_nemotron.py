"""Real end-to-end smoke test: Nemotron migration on a 3-stage legal/tax RAG trace.

Marked @pytest.mark.live — skipped automatically when NVIDIA_NIM_API_KEY is absent
(or when E2E_TARGET_MODEL is set to a keyless model like Ollama).

Purpose: prove the entire Reprompt core path (import → parse → optimize) survives
contact with a real model on real production data, not just a fake-call mock.

Run against Nemotron (free NVIDIA key required):
  NVIDIA_NIM_API_KEY=nvapi-... uv run pytest -m live -v

Run against local Ollama (no key, any ollama model pulled):
  E2E_TARGET_MODEL=ollama/qwen2.5:14b uv run pytest -m live -v

Verified model id: nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1
Provider prefix:   nvidia_nim/
Env var:           NVIDIA_NIM_API_KEY
Base URL:          https://integrate.api.nvidia.com/v1/ (LiteLLM default)
Verified 2026-07-23 via live NVIDIA NIM catalog + API test.
Note: nemotron-4-340b-instruct is listed in the catalog but gated (404 for free-tier keys).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from reprompt_core.budget import BudgetTracker
from reprompt_core.importers.query_log import convert_file
from reprompt_core.llm.client import LLMResponse, TransientLLMError, complete
from reprompt_core.optimizer.loop import StageOptimizationInput, run_optimizer
from reprompt_core.trace import parse_trace_file

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NEMOTRON_MODEL = "nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1"
E2E_TARGET_MODEL = os.environ.get("E2E_TARGET_MODEL", NEMOTRON_MODEL)
HARD_BUDGET_USD = 0.50

# 3-stage CI fixture (determine_query_type → extract_sections → response_generation)
# Originally run on Gemini 2.5 flash; real Indian Income Tax Act legal/tax RAG pipeline.
CI_FIXTURE = (
    Path(__file__).parent / "fixtures" / "query_log" / "680d95a1-d2b4-4ae4-bfae-a75529abaf1f.txt"
)

_needs_nvidia_key = (
    E2E_TARGET_MODEL == NEMOTRON_MODEL and not os.environ.get("NVIDIA_NIM_API_KEY")
)

pytestmark = pytest.mark.skipif(
    _needs_nvidia_key,
    reason=(
        "NVIDIA_NIM_API_KEY not set — skipping live Nemotron test. "
        "Set the key (free at build.nvidia.com) or override with "
        "E2E_TARGET_MODEL=ollama/qwen2.5:14b for a keyless local run."
    ),
)


# ---------------------------------------------------------------------------
# Throttled call wrapper (handles NVIDIA NIM free-tier rate limits)
# ---------------------------------------------------------------------------

def _call_with_backoff(model: str, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
    """Retry on transient errors (rate limit, timeout) with exponential backoff.

    Bounded to 3 attempts total. Keeps the backoff inside the harness rather
    than in client.complete() so existing unit tests are unaffected.
    """
    # Nemotron rejects response_format at the API level even though LiteLLM
    # reports it as supported. Strip it for all nvidia_nim calls — mutation
    # falls back to the original prompt, which the optimizer handles gracefully.
    if model.startswith("nvidia_nim/"):
        kwargs.pop("response_format", None)
    # Cap each call at 90 s — NVIDIA NIM free-tier has no server-side timeout
    # and will silently queue requests indefinitely under load.
    kwargs.setdefault("timeout", 90.0)
    for attempt in range(3):
        try:
            return complete(model, messages, **kwargs)
        except TransientLLMError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)  # 1 s, then 2 s, then raise
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_nemotron_e2e_smoke() -> None:
    """
    Full pipeline smoke test:
      1. Load real 3-stage legal/tax RAG production trace from fixture.
      2. Build StageOptimizationInputs (core path, no DB or API server needed).
      3. Run optimizer with real model calls against E2E_TARGET_MODEL.
      4. Assert: run completes, every stage has a winner, spend within budget.

    Assertions are intentionally loose — this is a smoke test proving the
    real LLM path doesn't blow up on real data, not a quality gate.
    """
    assert CI_FIXTURE.exists(), (
        f"CI fixture not found at {CI_FIXTURE}. "
        "Ensure 680d95a1-...txt was copied to packages/core/tests/fixtures/query_log/"
    )

    # --- 1. Import ----------------------------------------------------------
    trace_file = parse_trace_file(convert_file(CI_FIXTURE))
    pipeline = trace_file.pipeline
    trace = trace_file.traces[0]

    assert pipeline.stages, "Fixture produced no pipeline stages"
    records_by_stage = {r.stage_id: r for r in trace.records}

    # --- 2. Build StageOptimizationInputs -----------------------------------
    # Seed a minimal empty rubric — no deterministic checks, no judge criteria.
    # This keeps the smoke test cheap: only target-model calls are made, no judge.
    # Truncate prompt templates and examples: some stages (e.g. response_generation)
    # embed the full document corpus in the template, easily exceeding 131K tokens.
    # We're testing that the pipeline runs end-to-end, not that we can optimize
    # a 100K-token prompt — truncating here is intentional.
    _MAX_TEMPLATE = 6_000
    _MAX_EXAMPLE = 1_500
    stage_inputs: list[StageOptimizationInput] = []
    for i, stage in enumerate(pipeline.stages):
        record = records_by_stage.get(stage.id)
        if record is None:
            continue

        stage_inputs.append(
            StageOptimizationInput(
                stage_id=i + 1,
                stage_name=stage.name,
                original_prompt_template=stage.prompt_template[:_MAX_TEMPLATE],
                target_model=E2E_TARGET_MODEL,
                rubric={"deterministic_checks": [], "judge_criteria": []},
                assertion_specs=[],
                examples=[{
                    "input": (json.dumps(record.input) if isinstance(record.input, dict) else str(record.input or ""))[:_MAX_EXAMPLE],
                    "output": (record.output or "")[:_MAX_EXAMPLE],
                }],
            )
        )

    assert stage_inputs, "No StageOptimizationInputs could be built from fixture"

    # --- 3. Run optimizer ---------------------------------------------------
    budget = BudgetTracker(budget_usd=HARD_BUDGET_USD)
    result = run_optimizer(
        stage_inputs,
        call=_call_with_backoff,
        budget=budget,
        judge_model=E2E_TARGET_MODEL,
        strategy="simple",
    )

    # --- 4. Assert ----------------------------------------------------------
    assert result.stage_results, "Optimizer returned no stage results"

    for sr in result.stage_results:
        assert sr.error is None, (
            f"Stage id={sr.stage_id} failed with error: {sr.error}"
        )
        assert sr.best is not None, (
            f"Stage id={sr.stage_id} produced no winning candidate"
        )
        final = sr.best.scores.get("final")
        assert final is not None, f"Stage id={sr.stage_id} winner has no final score"
        assert 0.0 <= float(final) <= 1.0, (
            f"Stage id={sr.stage_id} final_score out of [0,1]: {final}"
        )

    assert budget.spent_usd <= HARD_BUDGET_USD, (
        f"Run exceeded hard budget: spent ${budget.spent_usd:.4f} > ${HARD_BUDGET_USD:.2f}"
    )

    # Loose aggregate parity — 0.3 floor just confirms the model produced
    # non-garbage output, not that it matches Gemini quality.
    scored = [sr for sr in result.stage_results if sr.best]
    if scored:
        avg_score = sum(
            float(sr.best.scores.get("final") or 0.0) for sr in scored
        ) / len(scored)
        assert avg_score >= 0.3, (
            f"Average parity score unexpectedly low ({avg_score:.3f}) — "
            "the model may have produced empty or nonsensical output on all stages."
        )
