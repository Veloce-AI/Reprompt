"""add activity_log to migrations

Revision ID: d3f7a2c1e5b6
Revises: 450ae8aefaa7
Create Date: 2026-07-16 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3f7a2c1e5b6'
down_revision: Union[str, Sequence[str], None] = '450ae8aefaa7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('migrations') as batch_op:
        batch_op.add_column(sa.Column('activity_log', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('migrations') as batch_op:
        batch_op.drop_column('activity_log')
