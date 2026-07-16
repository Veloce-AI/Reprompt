"""Rubric review endpoints (screen 4 / M2).

Rubric.deterministic_checks / judge_criteria / downstream_contract are
free-form JSON columns (see models.py). This module is the one place that
gives them concrete shapes on the way in and out of the API:

* ``deterministic_checks`` — validated against the real check types from
  ``reprompt_core.deterministic`` (``json_schema`` / ``required_keys`` /
  ``regex`` / ``length_bounds`` / ``enum_values`` / ``no_hallucinated_ids``).
  Anything that doesn't parse as one of those is rejected with a 422, not
  silently stored.
* ``judge_criteria`` — a list of ``{name, weight, description}`` objects.
  ``weight`` is a relative weight among a stage's own criteria (see
  ``reprompt_api.seed_rubrics`` for the full shape note).
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

from reprompt_core.deterministic import parse_deterministic_checks
from reprompt_core.llm.client import PermanentLLMError, RepromptLLMError, TransientLLMError
from reprompt_core.llm.model_select import NoAvailableModelError, select_model
from reprompt_core.rubric_generator import RubricGenerationError, StageOutputSample, generate_rubric

from reprompt_api import models
from reprompt_api.auth import get_current_user
from reprompt_api.crypto import EncryptionNotConfigured
from reprompt_api.db import get_db
from reprompt_api.llm_context import ProviderKeyNotConfigured, complete_with_workspace_credentials
from reprompt_api.migrations import get_available_models

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
    generated_with_model: str | None = Field(
        default=None,
        description=(
            "Which model actually produced this rubric's content, ONLY on the response to a "
            "generate/regenerate call (POST .../generate-rubric) - null on every other response "
            "(list/patch/approve), since that identity isn't persisted on the Rubric row. Set "
            "whether the model was auto-selected or explicitly chosen by the caller, so the UI "
            "can show 'Generated using <model>' right after a generation call either way."
        ),
    )


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


def _to_out(rubric: models.Rubric, stage_name: str, *, generated_with_model: str | None = None) -> RubricOut:
    return RubricOut(
        id=rubric.id,
        stage_id=rubric.stage_id,
        stage_name=stage_name,
        deterministic_checks=rubric.deterministic_checks or [],
        judge_criteria=rubric.judge_criteria or [],
        downstream_contract=rubric.downstream_contract or [],
        approved=rubric.approved,
        generated_with_model=generated_with_model,
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


# ---------------------------------------------------------------------------
# Rubric generation (M2 rubric engine — the LLM-powered generator)
# ---------------------------------------------------------------------------
#
# Per reprompt-parity-engine-plan.md §3 ("RUBRIC ENGINE (LLM-powered, runs
# once per stage): Analyzes benchmark outputs across all traces -> emits
# deterministic checks + judge criteria + downstream contract"), this is the
# one-call-per-stage unit — a bulk "generate for every stage" endpoint would
# just loop this per stage, and isn't built here to keep the API surface
# matching the plan's own unit of work; the UI can call this once per stage
# shown in screen 4, or loop client-side across a pipeline's stages.
#
# Behind get_current_user (like test-prompt in pipelines.py) because it
# spends a workspace's own BYOK credential. Fetches the stage's real
# StageRecords, calls reprompt_core.rubric_generator.generate_rubric via
# complete_with_workspace_credentials (never complete() directly — this
# must work with whatever provider a workspace has configured, per the task
# brief), and upserts the Rubric row: create if none exists yet, or replace
# the content of an existing one. Regenerating an already-approved rubric
# resets `approved` to False — new content has not been reviewed yet, and
# silently keeping a stale "approved" flag on content nobody has actually
# looked at would defeat the HITL gate the plan calls for. This mirrors
# `update_rubric` NOT doing that (an edit isn't a full regeneration) while a
# fresh LLM-generated rubric always starts unapproved, same as a brand-new
# rubric would.


class GenerateRubricIn(BaseModel):
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description=(
            "LiteLLM model string for the 'strong model' doing the rubric analysis, e.g. "
            "'claude-sonnet-4-5'. Optional - omit (or send null) to have the server auto-select "
            "a model from this workspace's configured models via "
            "reprompt_core.llm.model_select.select_model(purpose='rubric_generation'). An "
            "explicit value here always wins outright, never second-guessed against what's "
            "auto-selectable."
        ),
    )


def _get_workspace_or_500(db: Session, user: models.User) -> models.Workspace:
    """Every authenticated User has exactly one Workspace — see
    reprompt_api.pipelines._get_workspace_or_500 (this is a small local copy
    of the same helper; that one is module-private, and this is the only
    place in this module that needs a workspace at all).
    """
    workspace = db.scalar(select(models.Workspace).where(models.Workspace.owner_user_id == user.id))
    if workspace is None:
        raise HTTPException(
            status_code=500,
            detail="No workspace found for this account. This shouldn't happen.",
        )
    return workspace


def _get_stage_or_404(db: Session, pipeline_id: int, stage_id: int) -> models.Stage:
    stage = db.scalar(
        select(models.Stage).where(models.Stage.id == stage_id, models.Stage.pipeline_id == pipeline_id)
    )
    if stage is None:
        raise HTTPException(
            status_code=404,
            detail=f"Stage {stage_id} not found in pipeline {pipeline_id}",
        )
    return stage


@router.post("/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric", response_model=RubricOut)
def generate_rubric_for_stage(
    pipeline_id: int,
    stage_id: int,
    body: GenerateRubricIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RubricOut:
    """Generate (or regenerate) `stage_id`'s rubric from its real benchmark
    outputs across all traces, using the current user's workspace's saved
    BYOK key for the generator model's provider.

    `body.model` is optional: if omitted, the model is auto-selected via
    `reprompt_core.llm.model_select.select_model(purpose="rubric_generation",
    ...)` from this workspace's configured models (the same BYOK-filtered
    curated list `GET /settings/models` shows — see
    `reprompt_api.migrations.get_available_models`). An explicit `body.model`
    always wins outright and is never second-guessed against that list.

    Error mapping mirrors `reprompt_api.pipelines.test_prompt` exactly (same
    underlying mechanism, same failure modes): no workspace key configured
    for the required provider -> 422 pointing at /settings; nothing at all
    configured to auto-select from -> 422 pointing at /settings; encryption
    misconfigured -> 500; a transient provider error (rate limit/timeout) ->
    502; any other permanent LLM error, or the generator's own
    RubricGenerationError (model's output was unusable even after one
    corrective retry — see reprompt_core.rubric_generator) -> 422.
    """
    stage = _get_stage_or_404(db, pipeline_id, stage_id)

    records = db.scalars(select(models.StageRecord).where(models.StageRecord.stage_id == stage_id)).all()
    if not records:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Stage {stage_id} has no benchmark trace records yet — import a pipeline with "
                "traces for this stage before generating a rubric."
            ),
        )
    samples = [StageOutputSample(input=record.input, output=record.output) for record in records]

    workspace = _get_workspace_or_500(db, current_user)

    if body.model:
        generator_model = body.model
    else:
        available = [option.model for option in get_available_models(db, workspace)]
        try:
            generator_model = select_model("rubric_generation", available)
        except NoAvailableModelError as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No models are configured for this workspace yet — add an API key at "
                    "/settings, or pick a model explicitly."
                ),
            ) from exc

    def _call(model: str, messages, **kwargs):
        return complete_with_workspace_credentials(db, workspace, model, messages, **kwargs)

    try:
        result = generate_rubric(
            stage.name,
            stage.model,
            stage.prompt_template,
            samples,
            call=_call,
            generator_model=generator_model,
        )
    except ProviderKeyNotConfigured as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No API key configured for provider '{exc.provider}' in this "
                "workspace. Add one at /settings before generating a rubric with this model."
            ),
        ) from exc
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except TransientLLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RubricGenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (PermanentLLMError, RepromptLLMError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = db.scalar(select(models.Rubric).where(models.Rubric.stage_id == stage_id))
    if existing is None:
        rubric = models.Rubric(
            stage_id=stage_id,
            deterministic_checks=result.deterministic_checks,
            judge_criteria=result.judge_criteria,
            downstream_contract=result.downstream_contract,
            approved=False,
        )
        db.add(rubric)
    else:
        existing.deterministic_checks = result.deterministic_checks
        existing.judge_criteria = result.judge_criteria
        existing.downstream_contract = result.downstream_contract
        # Regenerated content needs re-review — see block docstring above.
        existing.approved = False
        rubric = existing

    db.commit()
    db.refresh(rubric)
    return _to_out(rubric, stage.name, generated_with_model=result.model)
