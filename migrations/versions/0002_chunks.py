"""Enable pgvector and add source chunks."""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = '0002_chunks'
down_revision = '0001_catalog'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table(
        'chunks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('source_id', UUID(as_uuid=True), sa.ForeignKey('sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata', JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('embedding', Vector(), nullable=False),
        sa.UniqueConstraint('source_id', 'chunk_index'),
        sa.CheckConstraint('chunk_index >= 0', name='ck_chunks_nonnegative_index'),
    )


def downgrade():
    op.drop_table('chunks')
    # Preserve the extension: it may have existed before this migration.
