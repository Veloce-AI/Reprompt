"""Regenerate docs/trace-format.schema.json from the live TraceFile models.

This is the one place that's allowed to write trace-format.schema.json — the
file itself is committed but generated, not hand-edited (packages/core/tests
has a drift test that fails the build if the committed file and a freshly
generated one disagree). Run this after any change to
refract_core.trace and commit the result:

    cd packages/core && uv run python scripts/export_schema.py

The generated schema is served live at GET /trace-format/schema by
apps/api (apps/api/src/refract_api/trace_format.py) for any external
product/language to consume without depending on this repo.
"""

from __future__ import annotations

import json
from pathlib import Path

from refract_core.trace import TraceFile

# packages/core/scripts/export_schema.py -> repo root -> docs/
REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "docs" / "trace-format.schema.json"


def generate_schema() -> dict:
    """Return TraceFile's JSON Schema as a plain dict."""
    return TraceFile.model_json_schema()


def main() -> None:
    schema = generate_schema()
    SCHEMA_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
