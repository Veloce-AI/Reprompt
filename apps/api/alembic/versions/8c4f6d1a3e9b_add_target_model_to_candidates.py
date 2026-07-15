"""add target_model column to candidates

Revision ID: 8c4f6d1a3e9b
Revises: f3a7b1c9d2e4
Create Date: 2026-07-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c4f6d1a3e9b'
down_revision: Union[str, Sequence[str], None] = 'f3a7b1c9d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('candidates') as batch_op:
        batch_op.add_column(sa.Column('target_model', sa.String(length=255), nullable=False, server_default='gpt-4o'))
        batch_op.alter_column('target_model', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('candidates') as batch_op:
        batch_op.drop_column('target_model')
