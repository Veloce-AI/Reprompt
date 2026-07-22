"""Contract mining endpoints — Phase 5.

POST   /pipelines/{pid}/stages/{sid}/mine-contract  → run two-axis mining,
                                                        persist candidate assertions
GET    /pipelines/{pid}/stages/{sid}/assertions      → list stage assertions
POST   /pipelines/{pid}/stages/{sid}/assertions/{aid}/approve  → status=approved
POST   /pipelines/{pid}/stages/{sid}/assertions/{aid}/retire   → status=retired

Mirrors the rubric review HITL pattern: mining runs → candidate rows →
human approves → Phase 8 runs approved assertions as executable predicates.
"""

from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from reprompt_core.budget import BudgetTracker
from reprompt_core.contract.mine import MineExample, MineInput, mine_contract
from reprompt_core.llm.client import PermanentLLMError, TransientLLMError

from reprompt_api import models
from reprompt_api.auth import get_current_user
from reprompt_api.crypto import EncryptionNotConfigured
from reprompt_api.db import get_db
from reprompt_api.llm_context import ProviderKeyNotConfigured, complete_with_workspace_credentials
from reprompt_api.migrations import get_available_models

logger = logging.getLogger(__name__)

router = APIRouter(tags=["contracts"])


# ---------------------------------------------------------------------------
# Pydantic I/O shapes
# ---------------------------------------------------------------------------


class AssertionOut(BaseModel):
    id: int
    stage_id: int
    kind: str
    spec: dict
    description: str
    confidence: float | None
    status: str
    source: str
    noise_floor: float | None
    entropy: float | None
    counterexamples: list
    version: int
    created_at: datetime.datetime


class MineContractIn(BaseModel):
    axis_b_repeats: int = 3
    budget: float = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_pipeline_or_404(db: Session, pipeline_id: int) -> models.Pipeline:
    pipeline = db.scalar(select(models.Pipeline).where(models.Pipeline.id == pipeline_id))
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    return pipeline


def _get_stage_or_404(db: Session, pipeline_id: int, stage_id: int) -> models.Stage:
    stage = db.scalar(
        select(models.Stage).where(
            models.Stage.id == stage_id,
            models.Stage.pipeline_id == pipeline_id,
        )
    )
    if stage is None:
        raise HTTPException(
            status_code=404,
            detail=f"Stage {stage_id} not found in pipeline {pipeline_id}",
        )
    return stage


def _get_assertion_or_404(db: Session, stage_id: int, assertion_id: int) -> models.Assertion:
    a = db.scalar(
        select(models.Assertion).where(
            models.Assertion.id == assertion_id,
            models.Assertion.stage_id == stage_id,
        )
    )
    if a is None:
        raise HTTPException(status_code=404, detail=f"Assertion {assertion_id} not found")
    return a


def _get_workspace_or_500(db: Session, user: models.User) -> models.Workspace:
    workspace = db.scalar(select(models.Workspace).where(models.Workspace.owner_user_id == user.id))
    if workspace is None:
        raise HTTPException(status_code=500, detail="No workspace found for this account.")
    return workspace


def _to_out(a: models.Assertion) -> AssertionOut:
    return AssertionOut(
        id=a.id,
        stage_id=a.stage_id,
        kind=a.kind,
        spec=a.spec,
        description=a.description,
        confidence=a.confidence,
        status=a.status,
        source=a.source,
        noise_floor=a.noise_floor,
        entropy=a.entropy,
        counterexamples=a.counterexamples,
        version=a.version,
        created_at=a.created_at,
    )


def _get_entails_fn():
    """Return the NLI entails function, or a strict equality fallback."""
    try:
        from reprompt_core.nli import entails
        return entails
    except Exception:  # noqa: BLE001
        # NLI model not available: fall back to exact-match (conservative)
        return lambda a, b: a.strip() == b.strip()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/pipelines/{pipeline_id}/stages/{stage_id}/assertions",
    response_model=list[AssertionOut],
)
def list_assertions(
    pipeline_id: int,
    stage_id: int,
    db: Session = Depends(get_db),
) -> list[AssertionOut]:
    _get_stage_or_404(db, pipeline_id, stage_id)
    assertions = db.scalars(
        select(models.Assertion)
        .where(models.Assertion.stage_id == stage_id)
        .order_by(models.Assertion.created_at)
    ).all()
    return [_to_out(a) for a in assertions]


@router.post(
    "/pipelines/{pipeline_id}/stages/{stage_id}/mine-contract",
    response_model=list[AssertionOut],
    status_code=201,
)
def mine_contract_for_stage(
    pipeline_id: int,
    stage_id: int,
    body: MineContractIn = MineContractIn(),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AssertionOut]:
    """Run two-axis contract mining for a stage and persist candidate assertions.

    Axis A = existing trace outputs (no new LLM calls).
    Axis B = `body.axis_b_repeats` calls on one input at temperature 0.7.

    Returns the newly created assertion rows (status=candidate).
    """
    _get_pipeline_or_404(db, pipeline_id)
    stage = _get_stage_or_404(db, pipeline_id, stage_id)

    records = db.scalars(
        select(models.StageRecord).where(models.StageRecord.stage_id == stage_id)
    ).all()
    if not records:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Stage {stage_id} has no benchmark trace records — import a pipeline with "
                "traces for this stage before mining its contract."
            ),
        )

    workspace = _get_workspace_or_500(db, current_user)

    examples = [
        MineExample(
            input=r.input if isinstance(r.input, dict) else {},
            rendered_prompt=r.rendered_prompt,
            output=r.output,
        )
        for r in records
    ]

    mine_input = MineInput(
        stage_id=stage_id,
        prompt_template=stage.prompt_template,
        target_model=stage.model,
        params=stage.params or {},
        examples=examples,
        axis_b_repeats=body.axis_b_repeats,
    )

    def _call(model: str, messages, **kwargs):
        return complete_with_workspace_credentials(db, workspace, model, messages, **kwargs)

    budget = BudgetTracker(budget_usd=max(body.budget, 0.01))
    entails_fn = _get_entails_fn()

    try:
        result = mine_contract(mine_input, call=_call, entails=entails_fn, budget=budget)
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ProviderKeyNotConfigured as exc:
        raise HTTPException(
            status_code=422,
            detail=f"No API key for this provider — add one at /settings. ({exc})",
        ) from exc
    except TransientLLMError as exc:
        raise HTTPException(status_code=502, detail=f"Provider error: {exc}") from exc
    except PermanentLLMError as exc:
        raise HTTPException(status_code=422, detail=f"LLM error: {exc}") from exc

    new_assertions = []
    for spec in result.invariants:
        row = models.Assertion(
            stage_id=stage_id,
            kind=spec.kind,
            spec=spec.spec,
            description=spec.description,
            confidence=spec.confidence,
            noise_floor=result.noise_floor,
            entropy=result.entropy,
            status="candidate",
            source="mined",
            counterexamples=[],
            version=1,
        )
        db.add(row)
        new_assertions.append(row)

    db.commit()
    for row in new_assertions:
        db.refresh(row)

    return [_to_out(a) for a in new_assertions]


@router.post(
    "/pipelines/{pipeline_id}/stages/{stage_id}/assertions/{assertion_id}/approve",
    response_model=AssertionOut,
)
def approve_assertion(
    pipeline_id: int,
    stage_id: int,
    assertion_id: int,
    db: Session = Depends(get_db),
) -> AssertionOut:
    _get_stage_or_404(db, pipeline_id, stage_id)
    a = _get_assertion_or_404(db, stage_id, assertion_id)
    a.status = "approved"
    db.commit()
    db.refresh(a)
    return _to_out(a)


@router.post(
    "/pipelines/{pipeline_id}/stages/{stage_id}/assertions/{assertion_id}/retire",
    response_model=AssertionOut,
)
def retire_assertion(
    pipeline_id: int,
    stage_id: int,
    assertion_id: int,
    db: Session = Depends(get_db),
) -> AssertionOut:
    _get_stage_or_404(db, pipeline_id, stage_id)
    a = _get_assertion_or_404(db, stage_id, assertion_id)
    a.status = "retired"
    db.commit()
    db.refresh(a)
    return _to_out(a)
