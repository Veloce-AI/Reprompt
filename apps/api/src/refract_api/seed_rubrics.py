"""Dev/test-only seed helper for Rubric rows.

M2's rubric GENERATOR (an LLM call that analyzes a stage's benchmark outputs
across all traces and emits a rubric) now exists — see
``refract_core.rubric_generator.generate_rubric`` and
``POST /pipelines/{id}/stages/{id}/generate-rubric`` in this package's
``rubrics`` module. This module is NOT that generator, and is still useful
alongside it: it's just enough hand-authored, realistic rubric data -
shaped exactly like ``refract_core.deterministic``'s check types - to build
and exercise screen 4 (rubric review) end-to-end without an LLM call in the
loop: pytest fixtures, and the Playwright e2e run against a live server,
neither of which want a slow/paid/rate-limited real model call on every run.

Usage as a library (e.g. from a pytest fixture, after importing a pipeline):

    from refract_api.seed_rubrics import seed_rubrics_for_pipeline
    rubrics = seed_rubrics_for_pipeline(db, pipeline)

Usage as a one-off CLI script, against whatever DATABASE_URL points at (same
env var refract_api.db reads) - e.g. to seed a pipeline already imported into
a running dev or e2e database:

    uv run python -m refract_api.seed_rubrics --pipeline-id 1
    uv run python -m refract_api.seed_rubrics --pipeline-name "Diamond Test Pipeline"
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from refract_core.deterministic import parse_deterministic_checks

from refract_api import models

__all__ = [
    "sample_deterministic_checks",
    "sample_judge_criteria",
    "sample_downstream_contract",
    "seed_rubric_for_stage",
    "seed_rubrics_for_pipeline",
]


def sample_deterministic_checks() -> list[dict]:
    """One ``required_keys`` check + one ``length_bounds`` check - the two
    types the build brief calls out explicitly.

    Shape matches ``refract_core.deterministic.DeterministicCheck`` exactly:
    the raw dicts below are round-tripped through the real Pydantic types via
    ``parse_deterministic_checks`` before being handed back, so a shape drift
    in ``deterministic.py`` breaks this seed helper loudly at seed time
    instead of silently writing data the evaluator can't parse later.
    """
    raw = [
        {
            "type": "required_keys",
            "id": "req-keys-1",
            "keys": ["currency", "revenue"],
        },
        {
            "type": "length_bounds",
            "id": "len-1",
            "min_length": 20,
            "max_length": 800,
            "unit": "chars",
        },
    ]
    parsed = parse_deterministic_checks(raw)
    return [check.model_dump(by_alias=True, exclude_none=True) for check in parsed]


def sample_judge_criteria() -> list[dict]:
    """judge_criteria shape (documented here since ``Rubric.judge_criteria``
    is a free-form JSON column with no Pydantic type of its own yet)::

        {"name": str, "weight": float, "description": str}

    ``weight`` is a *relative* weight among a stage's own criteria - it does
    not need to sum to 1 across the list (M3's evaluator normalizes at scoring
    time, not at authoring time).
    """
    return [
        {
            "name": "Covers all key entities",
            "weight": 0.6,
            "description": (
                "Mentions every product, customer, or account name that "
                "appeared in the input - nothing the input named is dropped."
            ),
        },
        {
            "name": "Tone: formal and concise",
            "weight": 0.4,
            "description": (
                "Matches the formal, concise register used in the benchmark "
                "outputs for this stage - no filler, no casual phrasing."
            ),
        },
    ]


def sample_downstream_contract() -> list[str]:
    """downstream_contract shape: a plain list of field names (dot-paths
    into the stage's parsed JSON output) that the NEXT stage actually reads.

    Per the plan's framing ("the only fields that truly matter"), this is
    intentionally just names, not full schemas - the optimizer only needs to
    hold these fields steady between benchmark and candidate, not the entire
    output.
    """
    return ["currency", "revenue"]


def seed_rubric_for_stage(db: Session, stage: models.Stage) -> models.Rubric:
    """Create (or return the existing) hand-authored Rubric row for `stage`.

    Idempotent: ``Rubric.stage_id`` is unique, so re-running this against a
    stage that already has a rubric just returns it unchanged rather than
    erroring or duplicating.
    """
    existing = db.query(models.Rubric).filter_by(stage_id=stage.id).one_or_none()
    if existing is not None:
        return existing

    rubric = models.Rubric(
        stage_id=stage.id,
        deterministic_checks=sample_deterministic_checks(),
        judge_criteria=sample_judge_criteria(),
        downstream_contract=sample_downstream_contract(),
        approved=False,
    )
    db.add(rubric)
    db.flush()
    return rubric


def seed_rubrics_for_pipeline(
    db: Session, pipeline: models.Pipeline, *, stage_ids: list[int] | None = None
) -> list[models.Rubric]:
    """Seed one rubric per stage of `pipeline` (or a subset via `stage_ids`).

    Defaults to *every* stage rather than just one, deliberately deviating
    from "one or two rows" - the review screen groups rubrics by stage and
    exercises "Approve per stage" vs. "Approve all", both of which need more
    than a single stage's worth of data to actually test. Pass `stage_ids`
    to seed just one or two stages if that's all a given test needs.
    """
    stages = pipeline.stages
    if stage_ids is not None:
        stages = [s for s in stages if s.id in stage_ids]
    rubrics = [seed_rubric_for_stage(db, stage) for stage in stages]
    db.commit()
    for rubric in rubrics:
        db.refresh(rubric)
    return rubrics


def _main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Seed hand-authored Rubric rows for an already-imported "
            "pipeline. Dev/test helper only - not the rubric generator."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pipeline-id", type=int)
    group.add_argument("--pipeline-name", type=str)
    args = parser.parse_args()

    # Imported lazily so DATABASE_URL (read at refract_api.db import time) is
    # only touched once argparse has succeeded, and so `--help` stays fast.
    from refract_api.db import SessionLocal

    db = SessionLocal()
    try:
        query = db.query(models.Pipeline)
        if args.pipeline_id is not None:
            pipeline = query.filter_by(id=args.pipeline_id).one_or_none()
        else:
            pipeline = query.filter_by(name=args.pipeline_name).one_or_none()

        if pipeline is None:
            selector = f"id={args.pipeline_id}" if args.pipeline_id is not None else f"name={args.pipeline_name!r}"
            print(f"No pipeline found matching {selector}", file=sys.stderr)
            raise SystemExit(1)

        rubrics = seed_rubrics_for_pipeline(db, pipeline)
        print(f"Seeded {len(rubrics)} rubric(s) for pipeline {pipeline.id} ({pipeline.name}).")
    finally:
        db.close()


if __name__ == "__main__":
    _main()
