"""Rubric review endpoints (screen 4 / M2).

Rubric.deterministic_checks / judge_criteria / downstream_contract are
free-form JSON columns (see models.py). This module is the one place that
gives them concrete shapes on the way in and out of the API:

* ``deterministic_checks`` — validated against the real check types from
  ``refract_core.deterministic`` (``json_schema`` / ``required_keys`` /
  ``regex`` / ``length_bounds`` / ``enum_values`` / ``no_hallucinated_ids``).
  Anything that doesn't parse as one of those is rejected with a 422, not
  silently stored.
* ``judge_criteria`` — a list of ``{name, weight, description}`` objects.
  ``weight`` is a relative weight among a stage's own criteria (see
  ``refract_api.seed_rubrics`` for the full shape note).
* ``downstream_contract`` — a plain list of field names/dot-paths the next
  stage consumes, per the plan's "the only fields that truly matter" framing.

The UI does whole-item add/edit/delete locally and saves via a single
whole-blob PATCH per section (or all three at once) — there's no per-item
endpoint. That keeps the API surface small; the JSON blobs are small enough
(a handful of checklist items per stage) that "read the whole list, edit
locally, PATCH the whole list back" is simpler than tracking item-level
identity server-side, and it's exactly what "editable/deletable" in the
screen 4 spec calls for from the frontend's perspective.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from refract_core.deterministic import parse_deterministic_checks

from refract_api import models
from refract_api.db import get_db

router = APIRouter(tags=["rubrics"])


class JudgeCriterionIn(BaseModel):
    """See module docstring for the judge_criteria shape note."""

    name: str = Field(min_length=1)
    weight: float = Field(ge=0)
    description: str = ""


_JUDGE_CRITERIA_ADAPTER: TypeAdapter[list[JudgeCriterionIn]] = TypeAdapter(list[JudgeCriterionIn])


class RubricOut(BaseModel):
    id: int
    stage_id: int
    stage_name: str
    deterministic_checks: list[dict]
    judge_criteria: list[dict]
    downstream_contract: list[str]
    approved: bool


class RubricUpdate(BaseModel):
    """Partial update: only the fields present are replaced (each field
    replaces its whole JSON blob, it does not merge item-by-item).
    """

    deterministic_checks: list[dict] | None = None
    judge_criteria: list[dict] | None = None
    downstream_contract: list[str] | None = None


def _validate_deterministic_checks(raw: list[dict]) -> list[dict]:
    try:
        parsed = parse_deterministic_checks(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid deterministic check(s): {exc}",
        ) from exc
    return [check.model_dump(by_alias=True, exclude_none=True) for check in parsed]


def _validate_judge_criteria(raw: list[dict]) -> list[dict]:
    try:
        parsed = _JUDGE_CRITERIA_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid judge criterion/criteria: {exc}",
        ) from exc
    return [criterion.model_dump() for criterion in parsed]


def _validate_downstream_contract(raw: list[str]) -> list[str]:
    if not all(isinstance(field, str) and field.strip() for field in raw):
        raise HTTPException(
            status_code=422,
            detail="downstream_contract must be a list of non-empty field names.",
        )
    return raw


def _to_out(rubric: models.Rubric, stage_name: str) -> RubricOut:
    return RubricOut(
        id=rubric.id,
        stage_id=rubric.stage_id,
        stage_name=stage_name,
        deterministic_checks=rubric.deterministic_checks or [],
        judge_criteria=rubric.judge_criteria or [],
        downstream_contract=rubric.downstream_contract or [],
        approved=rubric.approved,
    )


def _get_pipeline_or_404(db: Session, pipeline_id: int) -> models.Pipeline:
    pipeline = db.get(models.Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    return pipeline


def _get_rubric_or_404(db: Session, rubric_id: int) -> models.Rubric:
    rubric = db.get(models.Rubric, rubric_id)
    if rubric is None:
        raise HTTPException(status_code=404, detail=f"Rubric {rubric_id} not found")
    return rubric


@router.get("/pipelines/{pipeline_id}/rubrics", response_model=list[RubricOut])
def list_rubrics_for_pipeline(pipeline_id: int, db: Session = Depends(get_db)) -> list[RubricOut]:
    """All rubrics for a pipeline's stages, joined through Stage so the UI
    can group the checklist by stage name without a second round-trip.
    Stages with no rubric yet (the common case until M2's generator exists)
    are simply omitted, not returned as empty placeholders.
    """
    _get_pipeline_or_404(db, pipeline_id)

    rows = db.execute(
        select(models.Rubric, models.Stage.name)
        .join(models.Stage, models.Rubric.stage_id == models.Stage.id)
        .where(models.Stage.pipeline_id == pipeline_id)
        .order_by(models.Stage.id)
    ).all()

    return [_to_out(rubric, stage_name) for rubric, stage_name in rows]


@router.patch("/rubrics/{rubric_id}", response_model=RubricOut)
def update_rubric(rubric_id: int, update: RubricUpdate, db: Session = Depends(get_db)) -> RubricOut:
    rubric = _get_rubric_or_404(db, rubric_id)

    if update.deterministic_checks is not None:
        rubric.deterministic_checks = _validate_deterministic_checks(update.deterministic_checks)
    if update.judge_criteria is not None:
        rubric.judge_criteria = _validate_judge_criteria(update.judge_criteria)
    if update.downstream_contract is not None:
        rubric.downstream_contract = _validate_downstream_contract(update.downstream_contract)

    db.commit()
    db.refresh(rubric)
    stage = db.get(models.Stage, rubric.stage_id)
    return _to_out(rubric, stage.name if stage else "")


@router.post("/rubrics/{rubric_id}/approve", response_model=RubricOut)
def approve_rubric(rubric_id: int, db: Session = Depends(get_db)) -> RubricOut:
    rubric = _get_rubric_or_404(db, rubric_id)
    rubric.approved = True
    db.commit()
    db.refresh(rubric)
    stage = db.get(models.Stage, rubric.stage_id)
    return _to_out(rubric, stage.name if stage else "")


@router.post("/pipelines/{pipeline_id}/rubrics/approve-all", response_model=list[RubricOut])
def approve_all_rubrics(pipeline_id: int, db: Session = Depends(get_db)) -> list[RubricOut]:
    """Approve every rubric for the pipeline in one call ("Approve all once
    reviewed"). Always available regardless of per-stage view state — see
    apps/web/src/routes/rubric-review.tsx for the UI-side reasoning.
    """
    _get_pipeline_or_404(db, pipeline_id)

    rows = db.execute(
        select(models.Rubric, models.Stage.name)
        .join(models.Stage, models.Rubric.stage_id == models.Stage.id)
        .where(models.Stage.pipeline_id == pipeline_id)
        .order_by(models.Stage.id)
    ).all()

    for rubric, _ in rows:
        rubric.approved = True
    db.commit()

    return [_to_out(rubric, stage_name) for rubric, stage_name in rows]
