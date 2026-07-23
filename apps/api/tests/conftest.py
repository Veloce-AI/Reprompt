"""Ensure both packages are importable under Python 3.14, where .pth files
in the venv's site-packages are not always processed automatically (a
regression in Python 3.14.0 with uv-generated editable installs).
"""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_SRC = _REPO_ROOT / "apps" / "api" / "src"
_CORE_SRC = _REPO_ROOT / "packages" / "core" / "src"

for _p in (_API_SRC, _CORE_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture(autouse=True)
def _no_stray_system_model_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """`uv run` auto-loads apps/api/.env into every subprocess, including
    test runs - so a real REPROMPT_JUDGE_MODEL/etc. an operator has set for
    their own local dev server (see reprompt_api.system_models) would
    otherwise silently leak into every test that exercises auto-select,
    making test outcomes depend on whoever's machine/`.env` runs them.
    Same belt-and-braces reasoning as test_llm_context.py's
    _no_stray_cloud_keys fixture (stripping ambient cloud API keys) - this
    module's entire premise (auto-select behavior) must be deterministic
    regardless of what's in a gitignored, per-developer .env file.
    """
    for var in ("REPROMPT_RUBRIC_MODEL", "REPROMPT_JUDGE_MODEL", "REPROMPT_MUTATOR_MODEL"):
        monkeypatch.delenv(var, raising=False)
