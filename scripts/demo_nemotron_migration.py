#!/usr/bin/env python3
"""Demo: migrate a real legal/tax RAG pipeline from Gemini → Nemotron.

Runs the full Reprompt core optimizer against a real production trace
and prints a before/after comparison: original Gemini cost vs Nemotron cost,
parity score per stage, and winning prompt for each stage.

Usage:
  # Against Nemotron (free key from build.nvidia.com):
  NVIDIA_NIM_API_KEY=nvapi-... uv run python scripts/demo_nemotron_migration.py

  # Against local Ollama (no key needed):
  E2E_TARGET_MODEL=ollama/qwen2.5:14b uv run python scripts/demo_nemotron_migration.py

  # Against a larger trace (33 stages, slower):
  E2E_FIXTURE=0f586e25 uv run python scripts/demo_nemotron_migration.py

Hard budget ceiling: $1.00 (won't spend more regardless of runtime).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Add packages/core/src to path if running from repo root
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "core" / "src"))

from reprompt_core.budget import BudgetTracker
from reprompt_core.importers.query_log import convert_file
from reprompt_core.llm.client import LLMResponse, TransientLLMError, complete
from reprompt_core.optimizer.loop import StageOptimizationInput, StageResult, run_optimizer
from reprompt_core.trace import parse_trace_file

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NEMOTRON_MODEL = "nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1"
TARGET_MODEL = os.environ.get("E2E_TARGET_MODEL", NEMOTRON_MODEL)
HARD_BUDGET_USD = 1.00

_FIXTURE_DIR = _REPO_ROOT / "packages" / "core" / "tests" / "fixtures" / "query_log"
_FIXTURE_MAP = {
    "680d95a1": _FIXTURE_DIR / "680d95a1-d2b4-4ae4-bfae-a75529abaf1f.txt",
    "0f586e25": _FIXTURE_DIR / "0f586e25-0f0e-4ab8-911f-ec3fafed9232.txt",
}
_fixture_key = os.environ.get("E2E_FIXTURE", "680d95a1")
FIXTURE_PATH = _FIXTURE_MAP.get(_fixture_key, _FIXTURE_DIR / f"{_fixture_key}.txt")


# ---------------------------------------------------------------------------
# Throttled call (NVIDIA NIM free-tier rate limit protection)
# ---------------------------------------------------------------------------

def _call_with_backoff(model: str, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
    # Nemotron rejects response_format at the API level — strip for all
    # nvidia_nim calls so the optimizer falls back gracefully on mutation.
    if model.startswith("nvidia_nim/"):
        kwargs.pop("response_format", None)
    kwargs.setdefault("timeout", 90.0)
    for attempt in range(3):
        try:
            return complete(model, messages, **kwargs)
        except TransientLLMError:
            if attempt == 2:
                raise
            wait = 2 ** attempt
            print(f"  [rate limit] backing off {wait}s …", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 72)
    print("Reprompt — Nemotron Migration Demo")
    print("=" * 72)
    print(f"Target model : {TARGET_MODEL}")
    print(f"Hard budget  : ${HARD_BUDGET_USD:.2f}")
    print(f"Fixture      : {FIXTURE_PATH.name}")
    print()

    if TARGET_MODEL == NEMOTRON_MODEL and not os.environ.get("NVIDIA_NIM_API_KEY"):
        print("ERROR: NVIDIA_NIM_API_KEY not set.")
        print("Get a free key at https://build.nvidia.com and re-run.")
        print("Or use: E2E_TARGET_MODEL=ollama/qwen2.5:14b for a local run.")
        sys.exit(1)

    if not FIXTURE_PATH.exists():
        print(f"ERROR: Fixture not found: {FIXTURE_PATH}")
        print("Ensure the file was copied to packages/core/tests/fixtures/query_log/")
        sys.exit(1)

    # --- Import trace -------------------------------------------------------
    print("Importing trace …")
    raw_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    original_cost = raw_data.get("totals", {}).get("total_cost", 0.0)
    original_query = raw_data.get("query", "")[:80]

    trace_file = parse_trace_file(convert_file(FIXTURE_PATH))
    pipeline = trace_file.pipeline
    trace = trace_file.traces[0]
    records_by_stage = {r.stage_id: r for r in trace.records}

    print(f"Query        : {original_query!r}")
    print(f"Stages       : {len(pipeline.stages)}")
    print(f"Original cost: ${original_cost:.4f} (Gemini 2.5 flash)")
    print()

    # --- Build stage inputs -------------------------------------------------
    stage_inputs: list[StageOptimizationInput] = []
    for i, stage in enumerate(pipeline.stages):
        record = records_by_stage.get(stage.id)
        if record is None:
            continue
        stage_inputs.append(
            StageOptimizationInput(
                stage_id=i + 1,
                stage_name=stage.name,
                original_prompt_template=stage.prompt_template,
                target_model=TARGET_MODEL,
                rubric={"deterministic_checks": [], "judge_criteria": []},
                assertion_specs=[],
                examples=[{"input": record.input, "output": record.output}],
            )
        )

    # --- Run optimizer ------------------------------------------------------
    print(f"Running optimizer across {len(stage_inputs)} stage(s) …")
    print(f"(hard stop at ${HARD_BUDGET_USD:.2f})\n")

    budget = BudgetTracker(budget_usd=HARD_BUDGET_USD)

    def _on_attempt(attempt):
        score = attempt.scores.get("final") or 0.0
        print(f"  stage={attempt.stage_id}  score={score:.3f}  cost=${attempt.cost_usd:.4f}")

    result = run_optimizer(
        stage_inputs,
        call=_call_with_backoff,
        budget=budget,
        judge_model=TARGET_MODEL,
        strategy="simple",
        on_attempt=_on_attempt,
    )

    # --- Results ------------------------------------------------------------
    print()
    print("=" * 72)
    print("RESULTS")
    print("=" * 72)
    print(f"Original cost (Gemini 2.5 flash) : ${original_cost:.4f}")
    print(f"Migration cost (optimizer run)   : ${budget.spent_usd:.4f}")
    if original_cost > 0:
        savings = (original_cost - budget.spent_usd) / original_cost * 100
        print(f"Spend reduction                  : {savings:+.1f}%")
    print()

    for sr in result.stage_results:
        _print_stage_result(sr, pipeline, stage_inputs)

    if result.stop_reason:
        print(f"\n[stop reason: {result.stop_reason}]")

    print()
    print("Done. Commit the winning prompts to your config to ship the migration.")


def _print_stage_result(
    sr: StageResult,
    pipeline: Any,
    stage_inputs: list[StageOptimizationInput],
) -> None:
    stage_name = next(
        (si.stage_name for si in stage_inputs if si.stage_id == sr.stage_id),
        f"stage-{sr.stage_id}",
    )
    print(f"Stage: {stage_name}")
    if sr.error:
        print(f"  ERROR: {sr.error}")
        return
    if sr.best is None:
        print("  No winner (all attempts failed or budget exhausted before this stage)")
        return

    final = sr.best.scores.get("final") or 0.0
    emb = sr.best.scores.get("embedding_sim") or 0.0
    print(f"  Parity score : {final:.3f} (embedding_sim={emb:.3f})")
    print(f"  Attempts     : {sr.attempts_tried}")
    print(f"  Winning prompt (first 200 chars):")
    snippet = sr.best.prompt_variant[:200].replace("\n", " ")
    print(f"    {snippet!r}")
    print()


if __name__ == "__main__":
    main()
