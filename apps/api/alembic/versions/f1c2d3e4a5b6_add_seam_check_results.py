"""add seam_check_results table

Revision ID: f1c2d3e4a5b6
Revises: e4a1b8c7f203
Create Date: 2026-07-22

Phase 4 seam regression: stores per-(upstream, downstream) stage seam check
results for each migration. One row per (migration, upstream_stage, downstream_stage)
pair evaluated after optimization completes.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1c2d3e4a5b6"
down_revision: Union[str, Sequence[str], None] = "e4a1b8c7f203"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seam_check_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("migration_id", sa.Integer(), nullable=False),
        sa.Column("upstream_stage_id", sa.Integer(), nullable=False),
        sa.Column("downstream_stage_id", sa.Integer(), nullable=False),
        sa.Column("parity_score", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("substitution_applied", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["downstream_stage_id"], ["stages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["migration_id"], ["migrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["upstream_stage_id"], ["stages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seam_check_results_migration_id", "seam_check_results", ["migration_id"])


def downgrade() -> None:
    op.drop_index("ix_seam_check_results_migration_id", table_name="seam_check_results")
    op.drop_table("seam_check_results")
