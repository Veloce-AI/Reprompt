"""SQLAlchemy 2.0 declarative models for Refract's core data model.

Mirrors docs/refract-parity-engine-plan.md §2 exactly:

    Pipeline
     └── Stage[]            (depends_on[], model, prompt_template, params)
    Pipeline has:
     └── BenchmarkSet
          └── Trace[]
               └── StageRecord (input, rendered_prompt, output, tokens*, latency_ms)
    Stage has:
     └── Rubric (deterministic_checks, judge_criteria, downstream_contract)
    Migration
     └── target_model_config, budget, parity_threshold, status
          └── Candidate[] per stage

Design notes
------------
* ``Stage.depends_on`` — the plan describes it as "array of stage ids". A
  Postgres ``ARRAY`` column would work in Postgres but has no native
  equivalent in SQLite (this phase targets SQLite for fast local dev/tests
  per the M1.3 brief) and can't carry a real foreign-key constraint anyway.
  Instead this models it as a proper many-to-many self-referential
  relationship via a ``stage_dependencies`` association table
  (stage_id -> depends_on_stage_id). This is portable across SQLite/Postgres,
  gives FK integrity, and is what the DAG builder in packages/core will want
  to query (``stage.depends_on`` / ``stage.dependents``) rather than parsing
  an array.
* All "free-form" JSON fields (params, scores, target_model_config, rubric
  checks/criteria/contract) use SQLAlchemy's generic ``JSON`` type, which
  compiles to native ``JSON``/``JSONB``-ish storage on Postgres and to text
  on SQLite — both round-trip Python dict/list structures transparently.
* Timestamps use timezone-aware ``DateTime`` with a server-side default of
  "now" so both dialects populate created_at/updated_at consistently.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    stages: Mapped[list["Stage"]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan"
    )
    benchmark_sets: Mapped[list["BenchmarkSet"]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan"
    )
    migrations: Mapped[list["Migration"]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Stage + self-referential depends_on association table
# ---------------------------------------------------------------------------

stage_dependencies = Table(
    "stage_dependencies",
    Base.metadata,
    Column(
        "stage_id", ForeignKey("stages.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "depends_on_stage_id",
        ForeignKey("stages.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Stage(Base):
    __tablename__ = "stages"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "source_id", name="uq_stages_pipeline_source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The stage id as it appeared in the source trace file (e.g. "extract_financials").
    # Distinct from the DB primary key: M5's config export needs to write
    # migrated prompts back out keyed by the user's own stage ids, and names
    # alone aren't guaranteed unique. Unique per pipeline, not globally.
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    # temp / top_p / max_tokens / format_mode / ...
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    pipeline: Mapped["Pipeline"] = relationship(back_populates="stages")

    # Stages this stage depends on (upstream).
    depends_on: Mapped[list["Stage"]] = relationship(
        "Stage",
        secondary=stage_dependencies,
        primaryjoin=id == stage_dependencies.c.stage_id,
        secondaryjoin=id == stage_dependencies.c.depends_on_stage_id,
        back_populates="dependents",
    )
    # Stages that depend on this stage (downstream) — reverse of depends_on.
    dependents: Mapped[list["Stage"]] = relationship(
        "Stage",
        secondary=stage_dependencies,
        primaryjoin=id == stage_dependencies.c.depends_on_stage_id,
        secondaryjoin=id == stage_dependencies.c.stage_id,
        back_populates="depends_on",
    )

    stage_records: Mapped[list["StageRecord"]] = relationship(
        back_populates="stage", cascade="all, delete-orphan"
    )
    rubric: Mapped["Rubric | None"] = relationship(
        back_populates="stage", cascade="all, delete-orphan", uselist=False
    )
    candidates: Mapped[list["Candidate"]] = relationship(
        back_populates="stage", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# BenchmarkSet / Trace / StageRecord
# ---------------------------------------------------------------------------


class BenchmarkSet(Base):
    __tablename__ = "benchmark_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    pipeline: Mapped["Pipeline"] = relationship(back_populates="benchmark_sets")
    traces: Mapped[list["Trace"]] = relationship(
        back_populates="benchmark_set", cascade="all, delete-orphan"
    )


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benchmark_set_id: Mapped[int] = mapped_column(
        ForeignKey("benchmark_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The trace/query id as it appeared in the source file (e.g. a UUID from
    # a production query log). Was previously dropped entirely on ingest -
    # M2's rubric generation and M4's holdout re-runs both need to trace a
    # persisted row back to its original source record.
    source_trace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # The original user query/input for this trace. Free-form JSON since
    # different trace sources shape it differently (a plain string question,
    # a structured multi-field input, etc.) - importers normalize into this.
    query: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    query_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_holdout: Mapped[bool] = mapped_column(default=False, nullable=False)

    benchmark_set: Mapped["BenchmarkSet"] = relationship(back_populates="traces")
    stage_records: Mapped[list["StageRecord"]] = relationship(
        back_populates="trace", cascade="all, delete-orphan"
    )


class StageRecord(Base):
    __tablename__ = "stage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[int] = mapped_column(
        ForeignKey("traces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("stages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    input: Mapped[dict] = mapped_column(JSON, nullable=False)
    rendered_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # Model output text. JSON-typed column (not Text) even though the value
    # is always a plain str today, matching packages/core's StageRecord.output
    # - keeps the door open for structured output without another migration.
    output: Mapped[str] = mapped_column(JSON, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_thinking: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # $ cost of this call, if the source trace reported it. Nullable, not
    # defaulted to 0 - "unknown" and "free" are different things, and this
    # feeds directly into the product's cost-delta scorecard (M5).
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    trace: Mapped["Trace"] = relationship(back_populates="stage_records")
    stage: Mapped["Stage"] = relationship(back_populates="stage_records")


# ---------------------------------------------------------------------------
# Rubric
# ---------------------------------------------------------------------------


class Rubric(Base):
    __tablename__ = "rubrics"
    __table_args__ = (UniqueConstraint("stage_id", name="uq_rubrics_stage_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("stages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    deterministic_checks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    judge_criteria: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    downstream_contract: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Screen 4 (rubric review, M2): a human has looked at this stage's rubric
    # and signed off on it. Gates the first migration per the plan's HITL
    # requirement - not enforced yet at the migration-start layer (that lands
    # with M3+), just tracked here so the UI can show per-stage/"approve all"
    # state.
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    stage: Mapped["Stage"] = relationship(back_populates="rubric")


# ---------------------------------------------------------------------------
# Migration / Candidate
# ---------------------------------------------------------------------------


class Migration(Base):
    __tablename__ = "migrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # per-stage or global target model config, e.g. {"default": "gpt-4o-mini",
    # "stages": {"3": "gemini-flash-lite"}}
    target_model_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    budget: Mapped[float] = mapped_column(Float, nullable=False)
    parity_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.95)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    pipeline: Mapped["Pipeline"] = relationship(back_populates="migrations")
    candidates: Mapped[list["Candidate"]] = relationship(
        back_populates="migration", cascade="all, delete-orphan"
    )


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    migration_id: Mapped[int] = mapped_column(
        ForeignKey("migrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("stages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prompt_variant: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    # {"deterministic": 0.9, "judge": 0.85, "embedding_sim": 0.93}
    scores: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    migration: Mapped["Migration"] = relationship(back_populates="candidates")
    stage: Mapped["Stage"] = relationship(back_populates="candidates")


# ---------------------------------------------------------------------------
# Auth: User / Workspace / MagicLinkToken (M5)
# ---------------------------------------------------------------------------
#
# Per the master build prompt §4: "email magic-link, single workspace per
# user. No teams/RBAC yet." Two ways to model "single workspace per user":
# fold workspace fields directly onto User, or a real Workspace table with a
# unique owner_user_id (today's 1:1 enforced via UniqueConstraint, tomorrow's
# teams support just relaxes that constraint to many-workspaces-per-user and
# adds a membership table). The plan's own Settings screen ("workspace name")
# and the explicit backlog item "teams/RBAC" (post-MVP, not "never") both
# point at Workspace being a first-class concept later - so this goes with
# the real separate table now, to avoid a data migration + API reshape when
# teams land. The only thing enforced today is the 1:1 cardinality.


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # uselist=False + a unique constraint on Workspace.owner_user_id is what
    # actually enforces "single workspace per user" - see class docstring.
    workspace: Mapped["Workspace | None"] = relationship(
        back_populates="owner", cascade="all, delete-orphan", uselist=False
    )


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,  # enforces 1:1 - the "single workspace per user" MVP rule
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped["User"] = relationship(back_populates="workspace")


class MagicLinkToken(Base):
    """A one-time login token. Only the token's hash is ever stored - same

    principle as never logging a real API key: if this table leaked, no raw
    token (and therefore no live login credential) leaks with it. The raw
    token only ever exists in memory on the server for the request that
    minted it, and in the URL the user's email client shows them.
    """

    __tablename__ = "magic_link_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # sha256 hex digest (64 chars) of the raw token - see class docstring.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # Lowercased, not yet tied to a User row at creation time - see
    # refract_api.auth module docstring for why account creation is lazy
    # (deferred to a successful /auth/verify, not /auth/request-link).
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
