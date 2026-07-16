"""add progress_substep to migrations

Revision ID: b8e1c4a7f209
Revises: f3a7b1c9d2e4
Create Date: 2026-07-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e1c4a7f209'
down_revision: Union[str, Sequence[str], None] = 'f3a7b1c9d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('migrations') as batch_op:
        batch_op.add_column(sa.Column('progress_substep', sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('migrations') as batch_op:
        batch_op.drop_column('progress_substep')
