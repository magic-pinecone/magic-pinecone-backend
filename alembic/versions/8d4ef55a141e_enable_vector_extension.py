"""enable_vector_extension

Revision ID: 8d4ef55a141e
Revises: 298a20ef0169
Create Date: 2026-05-27 03:14:51.948846

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d4ef55a141e'
down_revision: Union[str, Sequence[str], None] = '298a20ef0169'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector;")
