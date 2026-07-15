"""GET /trace-format/schema — serves docs/trace-format.schema.json verbatim.

Public reference material: no auth. Any product's engineering team building
an importer/exporter for Reprompt's trace format should be able to fetch the
canonical JSON Schema without cloning this repo or reading Python source.
The file itself is generated from reprompt_core.trace.TraceFile (see
packages/core/scripts/export_schema.py) and its committed content is kept in
sync by a drift test in packages/core/tests - this endpoint just reads and
returns it, it doesn't regenerate anything at request time.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/trace-format", tags=["trace-format"])

# apps/api/src/reprompt_api/trace_format.py -> repo root -> docs/
_REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = _REPO_ROOT / "docs" / "trace-format.schema.json"


@router.get("/schema")
def get_trace_format_schema() -> dict:
    try:
        raw_text = SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"trace-format.schema.json is missing or unreadable: {exc}",
        ) from exc
    return json.loads(raw_text)
