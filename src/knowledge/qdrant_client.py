"""Qdrant vector database client with tenant-scoped operations.

Wraps the Qdrant Python client to provide:
- Payload-based multi-tenant isolation (tenant_id with is_tenant=true index)
- Per-tenant HNSW indexes (payload_m=16, m=0) for efficient tenant-scoped search
- Hybrid search combining dense (semantic) + sparse (BM25) vectors via RRF fusion
- Two collections: knowledge_base (products, methodology, regional) and conversations

The tenant isolation model uses Qdrant's recommended payload-based approach:
each point carries a tenant_id field, and every query includes a mandatory
tenant_id filter. The is_tenant=true index configuration creates per-tenant
HNSW sub-indexes for optimal query performance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models.models import KeywordIndexParams
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    Query,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from src.knowledge.config import KnowledgeBaseConfig
from src.knowledge.embeddings import EmbeddingService
from src.knowledge.models import ChunkMetadata, KnowledgeChunk

logger = logging.getLogger(__name__)


class QdrantKnowledgeStore:
    """Tenant-scoped vector store backed by Qdrant.

    Manages two collections:
    - knowledge_base: Product knowledge, methodology, regional content with
      hybrid search (dense + BM25 sparse) and RRF fusion.
    - conversations: Conversation messages indexed by session and channel.

    All operations require a tenant_id parameter and enforce tenant isolation
    at the query level.

    Args:
        config: Knowledge base configuration.
        embedding_service: Service for generating dense + sparse vectors.
    """

    def __init__(
        self, config: KnowledgeBaseConfig, embedding_service: EmbeddingService
    ) -> None:
        self._config = config
        self._embeddings = embedding_service

        # Initialize Qdrant client: remote if URL provided, local otherwise
        if config.qdrant_url:
            self._client = QdrantClient(
                url=config.qdrant_url,
                api_key=config.qdrant_api_key,
            )
        else:
            self._client = QdrantClient(path=config.qdrant_path)

    @property
    def client(self) -> QdrantClient:
        """Expose the underlying Qdrant client for advanced operations."""
        return self._client

    async def initialize_collections(self) -> None:
        """Create both collections if they don't already exist.

        Sets up:
        - knowledge_base: Dense (1536d cosine) + sparse BM25 vectors, payload
          indexes for tenant_id (is_tenant), product_category, buyer_persona,
          sales_stage, region, content_type, is_current, version.
        - conversations: Dense (1536d cosine) vectors, payload indexes for
          tenant_id (is_tenant), session_id, channel, timestamp.
        """
        await self._init_knowledge_collection()
        await self._init_conversations_collection()
        logger.info("Qdrant collections initialized")

    async def _init_knowledge_collection(self) -> None:
        """Create the knowledge_base collection with hybrid search support."""
        name = self._config.collection_knowledge

        if self._client.collection_exists(name):
            logger.info("Collection %s already exists, skipping creation", name)
            return

        self._client.create_collection(
            collection_name=name,
            vectors_config={
                "dense": VectorParams(
                    size=self._config.embedding_dimensions,
                    distance=Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "bm25": SparseVectorParams(
                    index=SparseIndexParams(),
                ),
            },
        )

        # Payload indexes for filtered search
        # tenant_id with is_tenant=True for per-tenant HNSW indexes
        self._client.create_payload_index(
            collection_name=name,
            field_name="tenant_id",
            field_schema=KeywordIndexParams(
                type="keyword",
                is_tenant=True,
            ),
        )

        # Metadata indexes for filtered retrieval
        for field in [
            "product_category",
            "buyer_persona",
            "sales_stage",
            "region",
            "content_type",
        ]:
            self._client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )

        self._client.create_payload_index(
            collection_name=name,
            field_name="is_current",
            field_schema=PayloadSchemaType.BOOL,
        )

        self._client.create_payload_index(
            collection_name=name,
            field_name="version",
            field_schema=PayloadSchemaType.INTEGER,
        )

        logger.info("Created knowledge_base collection with hybrid search config")

    async def _init_conversations_collection(self) -> None:
        """Create the conversations collection for message history."""
        name = self._config.collection_conversations

        if self._client.collection_exists(name):
            logger.info("Collection %s already exists, skipping creation", name)
            return

        self._client.create_collection(
            collection_name=name,
            vectors_config={
                "dense": VectorParams(
                    size=self._config.embedding_dimensions,
                    distance=Distance.COSINE,
                ),
            },
        )

        # tenant_id with is_tenant=True
        self._client.create_payload_index(
            collection_name=name,
            field_name="tenant_id",
            field_schema=KeywordIndexParams(
                type="keyword",
                is_tenant=True,
            ),
        )

        for field in ["session_id", "channel"]:
            self._client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )

        self._client.create_payload_index(
            collection_name=name,
            field_name="timestamp",
            field_schema=PayloadSchemaType.INTEGER,
        )

        logger.info("Created conversations collection")

    async def upsert_chunks(
        self, chunks: list[KnowledgeChunk], tenant_id: str
    ) -> None:
        """Upsert knowledge chunks into the knowledge_base collection.

        Generates embeddings for any chunks missing them, then upserts all
        chunks with their tenant_id in the payload.

        Args:
            chunks: Knowledge chunks to upsert. Embeddings will be generated
                if not already present.
            tenant_id: Owning tenant ID (must match chunk.tenant_id).

        Raises:
            ValueError: If any chunk's tenant_id doesn't match the provided
                tenant_id parameter.
        """
        points: list[PointStruct] = []

        # Generate embeddings for chunks that don't have them
        texts_needing_embeddings: list[tuple[int, str]] = []
        for i, chunk in enumerate(chunks):
            if chunk.tenant_id != tenant_id:
                raise ValueError(
                    f"Chunk {chunk.id} has tenant_id={chunk.tenant_id}, "
                    f"expected {tenant_id}"
                )
            if chunk.embedding_dense is None or chunk.embedding_sparse is None:
                texts_needing_embeddings.append((i, chunk.content))

        if texts_needing_embeddings:
            indices, texts = zip(*texts_needing_embeddings, strict=True)
            embeddings = await self._embeddings.embed_batch(list(texts))
            for idx, (dense, sparse) in zip(indices, embeddings, strict=True):
                chunks[idx].embedding_dense = dense
                chunks[idx].embedding_sparse = sparse

        for chunk in chunks:
            # Flatten metadata into payload alongside tenant_id
            payload: dict[str, Any] = {
                "tenant_id": tenant_id,
                "content": chunk.content,
                "product_category": chunk.metadata.product_category,
                "buyer_persona": chunk.metadata.buyer_persona,
                "sales_stage": chunk.metadata.sales_stage,
                "region": chunk.metadata.region,
                "content_type": chunk.metadata.content_type,
                "source_document": chunk.metadata.source_document,
                "version": chunk.metadata.version,
                "valid_from": chunk.metadata.valid_from.isoformat(),
                "valid_until": (
                    chunk.metadata.valid_until.isoformat()
                    if chunk.metadata.valid_until
                    else None
                ),
                "is_current": chunk.metadata.is_current,
                "cross_references": chunk.metadata.cross_references,
                "created_at": chunk.created_at.isoformat(),
                "updated_at": chunk.updated_at.isoformat(),
            }

            # Build point with sparse vector
            sparse_data = chunk.embedding_sparse
            point = PointStruct(
                id=chunk.id,
                vector={
                    "dense": chunk.embedding_dense,
                    "bm25": SparseVector(
                        indices=sparse_data["indices"],
                        values=sparse_data["values"],
                    ),
                },
                payload=payload,
            )
            points.append(point)

        self._client.upsert(
            collection_name=self._config.collection_knowledge,
            points=points,
        )
        logger.info(
            "Upserted %d chunks for tenant %s", len(points), tenant_id
        )

    async def hybrid_search(
        self,
        query_text: str,
        tenant_id: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[KnowledgeChunk]:
        """Search the knowledge base using hybrid dense + sparse with RRF fusion.

        Performs two prefetch queries (dense semantic + sparse BM25) and fuses
        results using Reciprocal Rank Fusion. All queries are scoped to the
        specified tenant_id.

        Args:
            query_text: Natural language search query.
            tenant_id: Tenant to search within.
            filters: Optional metadata filters (e.g., {"product_category": "billing"}).
            top_k: Number of results to return. Defaults to config.default_top_k.

        Returns:
            List of KnowledgeChunk objects ranked by hybrid score.
        """
        k = top_k or self._config.default_top_k

        # Generate query embeddings
        dense_vector, sparse_vector = await self._embeddings.embed_text(query_text)

        # Build tenant + metadata filter
        must_conditions: list[FieldCondition] = [
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
        ]

        if filters:
            for field, value in filters.items():
                must_conditions.append(
                    FieldCondition(key=field, match=MatchValue(value=value))
                )

        query_filter = Filter(must=must_conditions)

        # Hybrid search with prefetch + RRF fusion
        results = self._client.query_points(
            collection_name=self._config.collection_knowledge,
            prefetch=[
                Prefetch(
                    query=dense_vector,
                    using="dense",
                    limit=k * 2,
                    filter=query_filter,
                ),
                Prefetch(
                    query=SparseVector(
                        indices=sparse_vector["indices"],
                        values=sparse_vector["values"],
                    ),
                    using="bm25",
                    limit=k * 2,
                    filter=query_filter,
                ),
            ],
            query=Query(fusion="rrf"),
            limit=k,
        )

        # Convert results back to KnowledgeChunk
        chunks: list[KnowledgeChunk] = []
        for point in results.points:
            payload = point.payload or {}
            valid_until_raw = payload.get("valid_until")
            chunks.append(
                KnowledgeChunk(
                    id=str(point.id),
                    tenant_id=payload.get("tenant_id", tenant_id),
                    content=payload.get("content", ""),
                    metadata=ChunkMetadata(
                        product_category=payload.get("product_category", "monetization"),
                        buyer_persona=payload.get("buyer_persona", []),
                        sales_stage=payload.get("sales_stage", []),
                        region=payload.get("region", []),
                        content_type=payload.get("content_type", "product"),
                        source_document=payload.get("source_document", ""),
                        version=payload.get("version", 1),
                        valid_from=payload.get("valid_from", datetime.now(timezone.utc).isoformat()),
                        valid_until=valid_until_raw,
                        is_current=payload.get("is_current", True),
                        cross_references=payload.get("cross_references", []),
                    ),
                    created_at=payload.get("created_at", datetime.now(timezone.utc).isoformat()),
                    updated_at=payload.get("updated_at", datetime.now(timezone.utc).isoformat()),
                )
            )

        return chunks

    async def delete_chunks(
        self, chunk_ids: list[str], tenant_id: str
    ) -> None:
        """Delete chunks by IDs with tenant isolation guard.

        Only deletes points that match both the provided IDs AND the tenant_id,
        preventing cross-tenant deletion.

        Args:
            chunk_ids: List of chunk IDs to delete.
            tenant_id: Owning tenant ID (deletion guard).
        """
        from qdrant_client.models import FilterSelector, HasIdCondition, PointIdsList

        self._client.delete(
            collection_name=self._config.collection_knowledge,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        HasIdCondition(has_id=chunk_ids),
                        FieldCondition(
                            key="tenant_id",
                            match=MatchValue(value=tenant_id),
                        ),
                    ]
                )
            ),
        )
        logger.info(
            "Deleted %d chunks for tenant %s", len(chunk_ids), tenant_id
        )

    async def get_chunk(
        self, chunk_id: str, tenant_id: str
    ) -> KnowledgeChunk | None:
        """Retrieve a single chunk by ID with tenant isolation guard.

        Args:
            chunk_id: The chunk's unique identifier.
            tenant_id: Expected owning tenant ID.

        Returns:
            KnowledgeChunk if found and belongs to tenant, None otherwise.
        """
        results = self._client.retrieve(
            collection_name=self._config.collection_knowledge,
            ids=[chunk_id],
        )

        if not results:
            return None

        point = results[0]
        payload = point.payload or {}

        # Tenant isolation guard
        if payload.get("tenant_id") != tenant_id:
            logger.warning(
                "Tenant isolation violation: chunk %s belongs to %s, requested by %s",
                chunk_id,
                payload.get("tenant_id"),
                tenant_id,
            )
            return None

        valid_until_raw = payload.get("valid_until")
        return KnowledgeChunk(
            id=str(point.id),
            tenant_id=payload.get("tenant_id", tenant_id),
            content=payload.get("content", ""),
            metadata=ChunkMetadata(
                product_category=payload.get("product_category", "monetization"),
                buyer_persona=payload.get("buyer_persona", []),
                sales_stage=payload.get("sales_stage", []),
                region=payload.get("region", []),
                content_type=payload.get("content_type", "product"),
                source_document=payload.get("source_document", ""),
                version=payload.get("version", 1),
                valid_from=payload.get("valid_from", datetime.now(timezone.utc).isoformat()),
                valid_until=valid_until_raw,
                is_current=payload.get("is_current", True),
                cross_references=payload.get("cross_references", []),
            ),
            created_at=payload.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=payload.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )

    def close(self) -> None:
        """Close the Qdrant client connection."""
        self._client.close()
