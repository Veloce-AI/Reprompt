"""Fails if docs/trace-format.schema.json drifts from the live TraceFile
models. That file is committed but generated (see
packages/core/scripts/export_schema.py) - this test is what makes "generated,
not hand-edited" actually enforced instead of just a comment.
"""

from __future__ import annotations

import json
from pathlib import Path

from reprompt_core.trace import TraceFile

# packages/core/tests/test_export_schema.py -> repo root -> docs/
REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "docs" / "trace-format.schema.json"


def test_committed_schema_matches_live_models() -> None:
    assert SCHEMA_PATH.exists(), (
        f"{SCHEMA_PATH} is missing - run "
        "`cd packages/core && uv run python scripts/export_schema.py` and commit the result."
    )

    committed_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    live_schema = TraceFile.model_json_schema()

    assert committed_schema == live_schema, (
        f"{SCHEMA_PATH} is out of date with reprompt_core.trace.TraceFile - "
        "run `cd packages/core && uv run python scripts/export_schema.py` and commit the result."
    )
