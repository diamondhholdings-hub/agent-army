"""Add pgvector extension and agent_memories table.

Revision ID: 003_pgvector_memories
Revises: 001_initial_shared
Create Date: 2026-02-11

Creates the pgvector extension and shared.agent_memories table for
long-term semantic memory storage. Tenant isolation is enforced by
the tenant_id column with an index for efficient filtering.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_pgvector_memories"
down_revision: Union[str, None] = "001_initial_shared"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension (requires superuser or CREATE privilege)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create agent_memories table in shared schema
    op.execute("""
        CREATE TABLE IF NOT EXISTS shared.agent_memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB DEFAULT '{}',
            embedding vector(1536),
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    # Index for tenant-scoped queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_memories_tenant
        ON shared.agent_memories(tenant_id)
    """)

    # IVFFlat index for cosine similarity vector search
    # Note: This index is most effective when the table has data.
    # With an empty table, PostgreSQL may still use sequential scan.
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_memories_embedding
        ON shared.agent_memories
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shared.agent_memories")
    # Don't drop the vector extension -- other tables may use it
