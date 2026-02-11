"""Long-term memory with pgvector semantic search.

Stores factual knowledge about customers, deals, and agent-learned
insights. Each memory is tenant-scoped (WHERE tenant_id = ...) to
enforce strict multi-tenant isolation.

LOCKED DECISIONS:
- Long-term memory is a searchable knowledge base with permanent record
- Facts vs workflow: stores learned facts, not conversation flow
- Survives deal lifecycle (permanent)
- Vector searchable via pgvector embeddings
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg
import litellm
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class MemoryEntry(BaseModel):
    """A single long-term memory entry."""

    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    agent_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class LongTermMemory:
    """Tenant-scoped long-term memory backed by pgvector.

    Uses raw SQL via asyncpg for vector operations. Every query is
    filtered by tenant_id to enforce multi-tenant isolation.

    Usage:
        memory = LongTermMemory("postgresql://user:pass@host/db")
        await memory.setup()

        # Store a memory
        entry = MemoryEntry(
            tenant_id="t1", agent_id="sales_agent",
            content="Customer Acme has a $500k annual budget"
        )
        memory_id = await memory.store(entry)

        # Semantic search
        results = await memory.search("t1", "what is Acme's budget?")
    """

    def __init__(
        self,
        database_url: str,
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        """Initialize long-term memory.

        Args:
            database_url: PostgreSQL connection string. Converted from
                asyncpg scheme if needed (asyncpg requires plain
                postgresql:// URLs, not postgresql+asyncpg://).
            embedding_model: LiteLLM embedding model name.
        """
        # asyncpg requires plain postgresql:// URLs
        self._database_url = database_url.replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        self._embedding_model = embedding_model
        self._pool: asyncpg.Pool | None = None

    async def setup(self) -> None:
        """Initialize connection pool and create tables.

        Creates the pgvector extension and agent_memories table in the
        shared schema if they don't exist.
        """
        self._pool = await asyncpg.create_pool(
            self._database_url, min_size=2, max_size=10
        )

        async with self._pool.acquire() as conn:
            # Enable pgvector extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

            # Create the memories table in shared schema
            await conn.execute("""
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

            # Index for tenant filtering (most queries filter by tenant)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_tenant
                ON shared.agent_memories(tenant_id)
            """)

            # IVFFlat index for cosine similarity search
            # Note: IVFFlat requires rows to exist for optimal list count.
            # lists=100 is reasonable for up to ~100k memories.
            # For small datasets, the index still works but may not be
            # used by the planner until enough rows exist.
            try:
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_memories_embedding
                    ON shared.agent_memories
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """)
            except asyncpg.exceptions.InvalidParameterValueError:
                # IVFFlat index creation fails on empty tables with some
                # pgvector versions. This is fine -- exact search works
                # and the index can be created later when data exists.
                logger.warning(
                    "memory.ivfflat_index_deferred",
                    reason="table may be empty or have too few rows",
                )

        logger.info("long_term_memory.setup_complete")

    @property
    def pool(self) -> asyncpg.Pool:
        """Get the connection pool.

        Raises:
            RuntimeError: If setup() has not been called.
        """
        if self._pool is None:
            raise RuntimeError(
                "LongTermMemory not initialized -- call setup() first"
            )
        return self._pool

    async def _generate_embedding(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text.

        Uses LiteLLM for provider-agnostic embedding generation.

        Args:
            text: The text to embed.

        Returns:
            A list of floats representing the embedding vector.
        """
        response = await litellm.aembedding(
            model=self._embedding_model, input=[text]
        )
        return response.data[0]["embedding"]

    async def store(self, entry: MemoryEntry) -> str:
        """Store a memory entry with its embedding.

        Generates an embedding for the content and stores both in the
        agent_memories table.

        Args:
            entry: The memory entry to store.

        Returns:
            The memory_id of the stored entry.
        """
        # Generate embedding if not already provided
        if entry.embedding is None:
            entry.embedding = await self._generate_embedding(entry.content)

        pool = self.pool
        async with pool.acquire() as conn:
            # Convert embedding to pgvector format string
            embedding_str = "[" + ",".join(str(x) for x in entry.embedding) + "]"

            await conn.execute(
                """
                INSERT INTO shared.agent_memories
                    (id, tenant_id, agent_id, content, metadata, embedding,
                     created_at, updated_at)
                VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::vector, $7, $8)
                """,
                uuid.UUID(entry.memory_id),
                entry.tenant_id,
                entry.agent_id,
                entry.content,
                _dict_to_json(entry.metadata),
                embedding_str,
                entry.created_at,
                entry.updated_at,
            )

        logger.info(
            "memory.stored",
            memory_id=entry.memory_id,
            tenant_id=entry.tenant_id,
            agent_id=entry.agent_id,
        )
        return entry.memory_id

    async def search(
        self,
        tenant_id: str,
        query: str,
        limit: int = 10,
        agent_id: str | None = None,
    ) -> list[MemoryEntry]:
        """Search memories by semantic similarity.

        Generates an embedding for the query and performs cosine
        similarity search, filtered by tenant_id.

        Args:
            tenant_id: The tenant to search within (isolation enforced).
            query: The search query text.
            limit: Maximum number of results to return.
            agent_id: Optional filter by agent that created the memory.

        Returns:
            List of MemoryEntry objects ordered by similarity (most
            similar first).
        """
        query_embedding = await self._generate_embedding(query)
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        pool = self.pool

        async with pool.acquire() as conn:
            if agent_id:
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, agent_id, content, metadata,
                           created_at, updated_at,
                           embedding <=> $1::vector AS distance
                    FROM shared.agent_memories
                    WHERE tenant_id = $2 AND agent_id = $3
                    ORDER BY distance ASC
                    LIMIT $4
                    """,
                    embedding_str,
                    tenant_id,
                    agent_id,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, agent_id, content, metadata,
                           created_at, updated_at,
                           embedding <=> $1::vector AS distance
                    FROM shared.agent_memories
                    WHERE tenant_id = $2
                    ORDER BY distance ASC
                    LIMIT $3
                    """,
                    embedding_str,
                    tenant_id,
                    limit,
                )

        return [_row_to_entry(row) for row in rows]

    async def delete(self, memory_id: str, tenant_id: str) -> bool:
        """Delete a memory entry.

        Validates tenant_id matches to prevent cross-tenant deletion.

        Args:
            memory_id: The memory ID to delete.
            tenant_id: The tenant ID (must match the memory's tenant).

        Returns:
            True if the memory was deleted, False if not found or
            tenant mismatch.
        """
        pool = self.pool

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM shared.agent_memories
                WHERE id = $1::uuid AND tenant_id = $2
                """,
                uuid.UUID(memory_id),
                tenant_id,
            )
            deleted = result == "DELETE 1"

        if deleted:
            logger.info(
                "memory.deleted",
                memory_id=memory_id,
                tenant_id=tenant_id,
            )
        else:
            logger.warning(
                "memory.delete_not_found",
                memory_id=memory_id,
                tenant_id=tenant_id,
            )

        return deleted

    async def list_by_tenant(
        self, tenant_id: str, limit: int = 50
    ) -> list[MemoryEntry]:
        """List memories for a tenant, ordered by most recent first.

        Args:
            tenant_id: The tenant to list memories for.
            limit: Maximum number of memories to return.

        Returns:
            List of MemoryEntry objects ordered by recency.
        """
        pool = self.pool

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, agent_id, content, metadata,
                       created_at, updated_at
                FROM shared.agent_memories
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                tenant_id,
                limit,
            )

        return [_row_to_entry(row) for row in rows]

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None


def _row_to_entry(row: asyncpg.Record) -> MemoryEntry:
    """Convert a database row to a MemoryEntry."""
    import json

    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)

    return MemoryEntry(
        memory_id=str(row["id"]),
        tenant_id=row["tenant_id"],
        agent_id=row["agent_id"],
        content=row["content"],
        metadata=metadata if metadata else {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _dict_to_json(d: dict[str, Any]) -> str:
    """Serialize a dict to JSON string for JSONB insertion."""
    import json

    return json.dumps(d)
