"""add holdout_score to candidates

Revision ID: e4a1b8c7f203
Revises: d3f7a2c1e5b6
Create Date: 2026-07-22

M4 holdout pass: after optimization the winning prompt is scored on
examples withheld from training. holdout_score stores that unbiased
measurement on the Candidate row (nullable — only set on the winner
after a migration that had holdout examples).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4a1b8c7f203"
down_revision: Union[str, Sequence[str], None] = "d3f7a2c1e5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.add_column(sa.Column("holdout_score", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.drop_column("holdout_score")
