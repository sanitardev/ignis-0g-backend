"""Resize the derived chunk index for Alem text-1024."""
from alembic import op

revision = "0003_embedding_dimension_1024"
down_revision = "0002_rag_chunks"
branch_labels = None
depends_on = None


def _replace_index(dimension: int):
    op.execute("DELETE FROM chunks")
    op.execute(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({dimension})")
    op.execute("UPDATE sources SET indexed_hash = NULL WHERE indexed_hash IS NOT NULL")


def upgrade():
    _replace_index(1024)


def downgrade():
    _replace_index(384)
