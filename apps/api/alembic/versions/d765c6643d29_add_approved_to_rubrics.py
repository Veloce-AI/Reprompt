"""add approved flag to rubrics

Revision ID: d765c6643d29
Revises: c201a9fc9be2
Create Date: 2026-07-10 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd765c6643d29'
down_revision: Union[str, Sequence[str], None] = 'c201a9fc9be2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same batch-mode pattern as c201a9fc9be2: SQLite can't add a NOT NULL
    # column without a default in one step, so add it with a server_default
    # (via batch mode, for SQLite compatibility) then drop the server_default
    # once every existing row has a concrete value.
    with op.batch_alter_table('rubrics') as batch_op:
        batch_op.add_column(sa.Column('approved', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.alter_column('approved', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('rubrics') as batch_op:
        batch_op.drop_column('approved')
