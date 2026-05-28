"""add_course_embeddings_hnsw_index

Revision ID: 65ec978e2611
Revises: e3d41f3d8a7c
Create Date: 2026-05-28 10:44:24.059252

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65ec978e2611'
down_revision: Union[str, Sequence[str], None] = 'e3d41f3d8a7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_course_embeddings_embedding',
        'course_embeddings',
        ['embedding'],
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
        postgresql_with={'m': 16, 'ef_construction': 64}
    )


def downgrade() -> None:
    op.drop_index(
        'ix_course_embeddings_embedding',
        table_name='course_embeddings'
    )
