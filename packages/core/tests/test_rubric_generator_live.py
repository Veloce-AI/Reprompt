"""Live test of the rubric generator against a real model — proves the
whole pipeline (prompt -> real provider call -> real JSON response ->
translation into reprompt_core.deterministic's strict types) actually works
end to end, not just against a mocked response.

Same convention as ``test_llm_ollama_live.py``: skipped, not faked, when no
real credential is available in the environment. Here the credential is
``NVIDIA_NIM_API_KEY`` (a cloud provider key, unlike Ollama's "no key
needed" story) — this module never reads, prints, or logs its value; it
only checks whether the env var is present, and lets
``reprompt_core.llm.client.complete`` read it itself via LiteLLM's normal
env-var convention.

Deliberately minimal: one short sample, ``max_samples=1``, no huge rubric —
the model confirmed working for this task (``nvidia_nim/z-ai/glm-5.2``) is
slow (~85s for even a trivial reply), so this proves one real request/
response round-trip, not a stress test. Run explicitly (this file is not
skipped by markers, only by the env-var check) when the key is actually set
in the environment `pytest` itself runs in — never pass it as a literal on
the command line (same discipline as every other credential in this
project).
"""

from __future__ import annotations

import os

import pytest

from reprompt_core.deterministic import parse_deterministic_checks
from reprompt_core.llm.client import complete
from reprompt_core.rubric_generator import RubricGenerationResult, StageOutputSample, generate_rubric

LIVE_MODEL = "nvidia_nim/z-ai/glm-5.2"

pytestmark = pytest.mark.skipif(
    not os.environ.get("NVIDIA_NIM_API_KEY"),
    reason=(
        "NVIDIA_NIM_API_KEY is not set in this environment — skipping the live rubric-generator "
        "test. This is expected when no real NVIDIA NIM credential is configured; this test was "
        "not faked to pass. Set NVIDIA_NIM_API_KEY (as a real environment variable, never as a "
        "literal on a command line) and re-run to actually exercise this path."
    ),
)

# A single, tiny sample — keep the prompt short given the model's ~85s latency.
_SAMPLE = StageOutputSample(
    input={"document": "Q1 revenue was $4.2M USD."},
    output='{"currency": "USD", "revenue": 4200000}',
)


def test_live_rubric_generation_against_real_nvidia_nim_model() -> None:
    result = generate_rubric(
        "Extract financials",
        "gpt-4o-2024-08-06",
        "Extract the currency and revenue figure as JSON: {{document}}",
        [_SAMPLE],
        call=complete,
        generator_model=LIVE_MODEL,
        max_samples=1,
        timeout=180.0,
    )

    assert isinstance(result, RubricGenerationResult)
    # judge_criteria and downstream_contract are plain-shaped lists — assert
    # the real model actually produced *something* structured, not that it
    # matches exact content (a real model's exact wording isn't ours to pin).
    assert isinstance(result.judge_criteria, list)
    assert isinstance(result.downstream_contract, list)
    # The real payoff: whatever deterministic_checks the real model proposed
    # (possibly none — that's a legitimate, valid output) round-trips through
    # the REAL strict discriminated-union parser without error.
    parsed = parse_deterministic_checks(result.deterministic_checks)
    assert isinstance(parsed, list)
    assert result.latency_ms > 0

    print("\n--- LIVE rubric generation result (nvidia_nim/z-ai/glm-5.2) ---")
    print(f"model: {result.model}")
    print(f"cost_usd: {result.cost_usd}")
    print(f"latency_ms: {result.latency_ms:.0f}")
    print(f"deterministic_checks: {result.deterministic_checks}")
    print(f"judge_criteria: {result.judge_criteria}")
    print(f"downstream_contract: {result.downstream_contract}")
    print(f"dropped_checks: {result.dropped_checks}")
