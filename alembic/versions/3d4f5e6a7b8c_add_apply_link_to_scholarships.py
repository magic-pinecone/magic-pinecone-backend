"""add apply_link to scholarships

Revision ID: 3d4f5e6a7b8c
Revises: 298a20ef0169
Create Date: 2026-05-25 22:47:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d4f5e6a7b8c'
down_revision: Union[str, Sequence[str], None] = '298a20ef0169'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('scholarships', sa.Column('apply_link', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('scholarships', 'apply_link')
