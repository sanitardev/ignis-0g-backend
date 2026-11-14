"""Constrain source vectors to the Alem embedding dimension."""
from alembic import op

revision = "0003_embedding_dimension_1024"
down_revision = "0002_chunks"
branch_labels = None
depends_on = None


def upgrade():
    # PostgreSQL rejects incompatible stored vectors and rolls back the migration.
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024)")


def downgrade():
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector")
