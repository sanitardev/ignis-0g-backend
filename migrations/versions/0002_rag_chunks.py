"""Add versioned source chunks with 384-dimensional multilingual embeddings."""
from alembic import op

revision = "0002_rag_chunks"
down_revision = "0001_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE chunks (
            id UUID PRIMARY KEY,
            source_id UUID NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding VECTOR(384) NOT NULL,
            UNIQUE (source_id, chunk_index)
        )
    """)


def downgrade():
    op.drop_table("chunks")
    op.execute("UPDATE sources SET indexed_hash = NULL WHERE indexed_hash IS NOT NULL")
