"""New migration wizard endpoints (screen 5 / M2).

Per ``refract-master-build-prompt.md`` §4 screen 5 and §5's M2/M3 boundary:
this module is only responsible for the wizard that *creates* a Migration
record with its configuration (target model per stage, budget, parity
threshold). It does not run anything — there is no status transition logic
here. Actually optimizing stages against the new target model(s) is M3/M4's
job; ``Migration.status`` is created as ``"pending"`` and stays there.

``target_model_config`` JSON shape
-----------------------------------
Matches the shape already documented as an example in ``models.py``::

    {
        "default": "gpt-4o-mini",
        "stages": {"3": "gemini/gemini-2.0-flash"}
    }

* ``default`` — the bulk-set model string (a LiteLLM model id), applied to
  every stage that has no override.
* ``stages`` — optional per-stage overrides, keyed by the stage's **database
  id** (as a string, since JSON object keys are always strings) mapping to a
  LiteLLM model string. Every key must reference a stage that belongs to
  this pipeline — a stage id from a different pipeline (or one that doesn't
  exist at all) is rejected with a 422 that names the offending id(s), not
  silently accepted or 500'd.

Model picker data source
-------------------------
``GET /pipelines/{pipeline_id}/models`` returns a small curated list of
LiteLLM model strings spanning the major hosted providers plus a couple of
local/open options, enriched with capability facts pulled live from
``refract_core.llm.registry.get_model_capabilities`` (itself a thin,
never-raising wrapper over LiteLLM's own model metadata). This is
deliberately not the full model-card registry described for M3 — just
enough for the picker to show cost/context window/JSON-mode support per the
screen 5 spec. Any model LiteLLM doesn't fully recognize still comes back
with a row (degrading to ``None``/``False`` fields), matching
``get_model_capabilities``'s own "never raises for an unrecognized model"
contract — the picker should show fewer facts, not break.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from refract_core.llm.registry import get_model_capabilities

from refract_api import models
from refract_api.db import get_db

router = APIRouter(prefix="/pipelines", tags=["migrations"])

# A deliberately small, curated cross-section of LiteLLM model strings for
# the picker — not an attempt to enumerate every model LiteLLM knows about.
# Spans the major hosted providers plus a couple of local/open options (no
# API key required), per the task's own examples.
CURATED_MODELS: list[str] = [
    "gpt-4o",
    "gpt-4o-mini",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "gemini/gemini-2.0-flash",
    "gemini/gemini-2.0-flash-lite",
    "ollama/llama3.1",
    "ollama/qwen2.5:14b",
]


class ModelOption(BaseModel):
    model: str
    provider: str | None
    input_cost_per_1m: float | None
    output_cost_per_1m: float | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    supports_json_mode: bool
    supports_function_calling: bool
    requires_api_key: bool


class TargetModelConfig(BaseModel):
    """See module docstring for the full shape note."""

    default: str = Field(min_length=1)
    stages: dict[str, str] = Field(default_factory=dict)


class MigrationCreate(BaseModel):
    target_model_config: TargetModelConfig
    budget: float = Field(gt=0, description="Max optimization spend in $ - a hard stop.")
    parity_threshold: float = Field(default=0.95, ge=0, le=1)


class MigrationOut(BaseModel):
    id: int
    pipeline_id: int
    target_model_config: dict
    budget: float
    parity_threshold: float
    status: str


def _get_pipeline_or_404(db: Session, pipeline_id: int) -> models.Pipeline:
    pipeline = db.get(models.Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    return pipeline


def _to_option(model: str) -> ModelOption:
    caps = get_model_capabilities(model)
    input_cost_per_1m = (
        caps.input_cost_per_token * 1_000_000 if caps.input_cost_per_token is not None else None
    )
    output_cost_per_1m = (
        caps.output_cost_per_token * 1_000_000 if caps.output_cost_per_token is not None else None
    )
    return ModelOption(
        model=model,
        provider=caps.provider,
        input_cost_per_1m=input_cost_per_1m,
        output_cost_per_1m=output_cost_per_1m,
        max_input_tokens=caps.max_input_tokens,
        max_output_tokens=caps.max_output_tokens,
        supports_json_mode=caps.supports_json_mode,
        supports_function_calling=caps.supports_function_calling,
        requires_api_key=caps.requires_api_key,
    )


def _to_out(migration: models.Migration) -> MigrationOut:
    return MigrationOut(
        id=migration.id,
        pipeline_id=migration.pipeline_id,
        target_model_config=migration.target_model_config,
        budget=migration.budget,
        parity_threshold=migration.parity_threshold,
        status=migration.status,
    )


@router.get("/{pipeline_id}/models", response_model=list[ModelOption])
def list_model_options(pipeline_id: int, db: Session = Depends(get_db)) -> list[ModelOption]:
    """Model picker data source for the migration wizard's target-model step."""
    _get_pipeline_or_404(db, pipeline_id)
    return [_to_option(model) for model in CURATED_MODELS]


@router.post("/{pipeline_id}/migrations", response_model=MigrationOut, status_code=201)
def create_migration(
    pipeline_id: int, migration_in: MigrationCreate, db: Session = Depends(get_db)
) -> MigrationOut:
    """Create a Migration record from the wizard's final config. Does not
    start anything — see module docstring. Status is always "pending".
    """
    _get_pipeline_or_404(db, pipeline_id)

    stage_overrides = migration_in.target_model_config.stages
    if stage_overrides:
        try:
            override_stage_ids = {int(key) for key in stage_overrides}
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="target_model_config.stages keys must be stage ids (numeric strings).",
            ) from exc

        pipeline_stage_ids = set(
            db.scalars(
                select(models.Stage.id).where(models.Stage.pipeline_id == pipeline_id)
            ).all()
        )
        unknown_ids = sorted(override_stage_ids - pipeline_stage_ids)
        if unknown_ids:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"target_model_config.stages references stage id(s) "
                    f"{unknown_ids} which do not belong to pipeline {pipeline_id}."
                ),
            )

    migration = models.Migration(
        pipeline_id=pipeline_id,
        target_model_config=migration_in.target_model_config.model_dump(),
        budget=migration_in.budget,
        parity_threshold=migration_in.parity_threshold,
        status="pending",
    )
    db.add(migration)
    db.commit()
    db.refresh(migration)
    return _to_out(migration)


@router.get("/{pipeline_id}/migrations", response_model=list[MigrationOut])
def list_migrations(pipeline_id: int, db: Session = Depends(get_db)) -> list[MigrationOut]:
    _get_pipeline_or_404(db, pipeline_id)
    migrations = db.scalars(
        select(models.Migration)
        .where(models.Migration.pipeline_id == pipeline_id)
        .order_by(models.Migration.id)
    ).all()
    return [_to_out(migration) for migration in migrations]
