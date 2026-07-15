"""merge target_model and progress_substep heads

Revision ID: 450ae8aefaa7
Revises: 8c4f6d1a3e9b, b8e1c4a7f209
Create Date: 2026-07-15 23:04:17.688888

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '450ae8aefaa7'
down_revision: Union[str, Sequence[str], None] = ('8c4f6d1a3e9b', 'b8e1c4a7f209')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
