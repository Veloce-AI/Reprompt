"""add base_url to workspace_api_keys and progress/cost fields to migrations

Revision ID: f3a7b1c9d2e4
Revises: a4cde1332c73
Create Date: 2026-07-12 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a7b1c9d2e4'
down_revision: Union[str, Sequence[str], None] = 'a4cde1332c73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('workspace_api_keys') as batch_op:
        batch_op.add_column(sa.Column('base_url', sa.String(length=512), nullable=True))

    with op.batch_alter_table('migrations') as batch_op:
        batch_op.add_column(sa.Column('total_cost_usd', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('stopped_early', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('stop_reason', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('progress_stage_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('progress_current', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('progress_total', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.alter_column('stopped_early', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('migrations') as batch_op:
        batch_op.drop_column('completed_at')
        batch_op.drop_column('progress_total')
        batch_op.drop_column('progress_current')
        batch_op.drop_column('progress_stage_name')
        batch_op.drop_column('stop_reason')
        batch_op.drop_column('stopped_early')
        batch_op.drop_column('total_cost_usd')

    with op.batch_alter_table('workspace_api_keys') as batch_op:
        batch_op.drop_column('base_url')
