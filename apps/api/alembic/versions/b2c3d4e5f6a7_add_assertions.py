"""add assertions table (Phase 5 contract mining registry)

Revision ID: b2c3d4e5f6a7
Revises: f1c2d3e4a5b6
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "f1c2d3e4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assertions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stage_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="'candidate'"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="'mined'"),
        sa.Column("counterexamples", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("noise_floor", sa.Float(), nullable=True),
        sa.Column("entropy", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default="''"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["stage_id"], ["stages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assertions_stage_id", "assertions", ["stage_id"])


def downgrade() -> None:
    op.drop_index("ix_assertions_stage_id", table_name="assertions")
    op.drop_table("assertions")
