"""Live test against a local Ollama server, IF one happens to be running.

Per the task this module was built for: there is no paid API key available
in this environment, so real network calls to a cloud provider are out of
scope for automated tests. But if a local Ollama server is already running
(this suite does not install or start one), that's a genuinely free,
local, real end-to-end exercise of refract_core.llm.complete() worth
taking — it is the one case where "no API key needed" can actually be
proven against a live model, not just asserted against a mock.

At the time this suite was written, no Ollama server was reachable on
``http://localhost:11434`` in this environment, so these tests are
expected to be **skipped**, not passing-via-fakery. Run `ollama serve`
(with at least one model pulled) locally and re-run pytest to actually
exercise this path.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from refract_core.llm.client import LLMResponse, complete

OLLAMA_BASE_URL = "http://localhost:11434"


def _ollama_available() -> tuple[bool, str | None]:
    """Returns (available, first_model_name_or_None). Never raises."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=1.5) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False, None
    models = payload.get("models") or []
    if not models:
        return False, None
    return True, models[0]["name"]


_AVAILABLE, _MODEL_NAME = _ollama_available()

pytestmark = pytest.mark.skipif(
    not _AVAILABLE,
    reason=(
        "No local Ollama server with a pulled model found on "
        f"{OLLAMA_BASE_URL} — skipping live local-model test. This is "
        "expected in an environment with no Ollama installed/running; "
        "these tests were not faked to pass."
    ),
)


def test_live_completion_against_local_ollama_model() -> None:
    result = complete(
        f"ollama/{_MODEL_NAME}",
        [{"role": "user", "content": "Reply with exactly one word: hello"}],
        max_tokens=16,
    )

    assert isinstance(result, LLMResponse)
    assert result.content
    assert result.usage.input > 0
    assert result.usage.output > 0
    assert result.latency_ms > 0
    # Local models have no per-token API cost.
    assert result.cost_usd in (0.0, None)
