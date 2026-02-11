"""Tests for QdrantKnowledgeStore with mocked embeddings.

Uses Qdrant local mode with tmp_path for isolated test instances.
EmbeddingService is mocked to return deterministic vectors, avoiding
OpenAI API calls during testing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.knowledge.config import KnowledgeBaseConfig
from src.knowledge.embeddings import EmbeddingService
from src.knowledge.models import ChunkMetadata, KnowledgeChunk
from src.knowledge.qdrant_client import QdrantKnowledgeStore


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_dense_vector(seed: float = 0.1, dims: int = 1536) -> list[float]:
    """Generate a deterministic dense vector for testing."""
    import math

    return [math.sin(seed * (i + 1)) for i in range(dims)]


def _make_sparse_vector(terms: list[int] | None = None) -> dict:
    """Generate a deterministic sparse vector for testing."""
    if terms is None:
        terms = [1, 5, 10, 50, 100]
    return {
        "indices": terms,
        "values": [1.0 / (i + 1) for i in range(len(terms))],
    }


def _make_chunk(
    tenant_id: str,
    content: str = "Test content",
    product_category: str = "monetization",
    content_type: str = "product",
    buyer_persona: list[str] | None = None,
    sales_stage: list[str] | None = None,
    region: list[str] | None = None,
    dense_seed: float = 0.1,
    sparse_terms: list[int] | None = None,
) -> KnowledgeChunk:
    """Create a KnowledgeChunk with deterministic embeddings for testing."""
    return KnowledgeChunk(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        content=content,
        metadata=ChunkMetadata(
            product_category=product_category,
            buyer_persona=buyer_persona or ["technical"],
            sales_stage=sales_stage or ["discovery"],
            region=region or ["global"],
            content_type=content_type,
            source_document="test_doc.pdf",
        ),
        embedding_dense=_make_dense_vector(dense_seed),
        embedding_sparse=_make_sparse_vector(sparse_terms),
    )


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def config(tmp_path) -> KnowledgeBaseConfig:
    """Create a KnowledgeBaseConfig pointing at a temporary directory."""
    return KnowledgeBaseConfig(
        qdrant_path=str(tmp_path / "qdrant_test"),
        openai_api_key="test-key-not-used",
    )


@pytest.fixture
def mock_embedding_service(config) -> EmbeddingService:
    """Create a mock EmbeddingService returning deterministic vectors."""
    service = MagicMock(spec=EmbeddingService)

    # Mock embed_text to return deterministic vectors
    async def mock_embed_text(text: str) -> tuple[list[float], dict]:
        # Use hash of text to create slightly different vectors per query
        seed = abs(hash(text)) % 1000 / 1000.0 + 0.01
        return _make_dense_vector(seed), _make_sparse_vector()

    service.embed_text = AsyncMock(side_effect=mock_embed_text)

    # Mock embed_batch
    async def mock_embed_batch(
        texts: list[str],
    ) -> list[tuple[list[float], dict]]:
        results = []
        for text in texts:
            seed = abs(hash(text)) % 1000 / 1000.0 + 0.01
            results.append((_make_dense_vector(seed), _make_sparse_vector()))
        return results

    service.embed_batch = AsyncMock(side_effect=mock_embed_batch)

    return service


@pytest.fixture
async def store(config, mock_embedding_service) -> QdrantKnowledgeStore:
    """Create a QdrantKnowledgeStore with mocked embeddings and initialized collections."""
    store = QdrantKnowledgeStore(
        config=config,
        embedding_service=mock_embedding_service,
    )
    await store.initialize_collections()
    yield store
    store.close()


# ── Tests: Collection Initialization ────────────────────────────────────────


async def test_collection_creation(store: QdrantKnowledgeStore):
    """Collections are created with correct configuration."""
    client = store.client

    # knowledge_base collection exists
    assert client.collection_exists("knowledge_base")
    kb_info = client.get_collection("knowledge_base")
    assert kb_info.config.params.vectors["dense"].size == 1536
    assert kb_info.config.params.vectors["dense"].distance.name == "COSINE"

    # conversations collection exists
    assert client.collection_exists("conversations")
    conv_info = client.get_collection("conversations")
    assert conv_info.config.params.vectors["dense"].size == 1536


async def test_idempotent_collection_creation(
    config, mock_embedding_service
):
    """Calling initialize_collections twice does not raise errors."""
    store = QdrantKnowledgeStore(
        config=config,
        embedding_service=mock_embedding_service,
    )
    await store.initialize_collections()
    # Second call should be idempotent
    await store.initialize_collections()
    assert store.client.collection_exists("knowledge_base")
    store.close()


# ── Tests: Upsert and Retrieval ─────────────────────────────────────────────


async def test_upsert_and_get_chunk(store: QdrantKnowledgeStore):
    """Upserting a chunk and retrieving it returns correct data."""
    chunk = _make_chunk(tenant_id="tenant-1", content="Monetization overview")

    await store.upsert_chunks([chunk], tenant_id="tenant-1")

    retrieved = await store.get_chunk(chunk.id, tenant_id="tenant-1")
    assert retrieved is not None
    assert retrieved.id == chunk.id
    assert retrieved.content == "Monetization overview"
    assert retrieved.metadata.product_category == "monetization"


async def test_upsert_generates_embeddings_when_missing(
    store: QdrantKnowledgeStore,
):
    """Chunks without embeddings get them generated during upsert."""
    chunk = KnowledgeChunk(
        id=str(uuid.uuid4()),
        tenant_id="tenant-1",
        content="Test without embeddings",
        metadata=ChunkMetadata(
            product_category="billing",
            content_type="product",
            source_document="test.pdf",
        ),
        embedding_dense=None,
        embedding_sparse=None,
    )

    await store.upsert_chunks([chunk], tenant_id="tenant-1")

    # Verify it was stored (embedding service was called)
    retrieved = await store.get_chunk(chunk.id, tenant_id="tenant-1")
    assert retrieved is not None
    assert retrieved.content == "Test without embeddings"


async def test_upsert_tenant_mismatch_raises(store: QdrantKnowledgeStore):
    """Upserting a chunk with mismatched tenant_id raises ValueError."""
    chunk = _make_chunk(tenant_id="tenant-1")

    with pytest.raises(ValueError, match="expected tenant-2"):
        await store.upsert_chunks([chunk], tenant_id="tenant-2")


# ── Tests: Tenant Isolation ─────────────────────────────────────────────────


async def test_tenant_isolation_get(store: QdrantKnowledgeStore):
    """Getting a chunk with wrong tenant_id returns None."""
    chunk = _make_chunk(tenant_id="tenant-1", content="Tenant 1 secret data")
    await store.upsert_chunks([chunk], tenant_id="tenant-1")

    # Same chunk ID, different tenant -- should return None
    result = await store.get_chunk(chunk.id, tenant_id="tenant-2")
    assert result is None


async def test_tenant_isolation_search(store: QdrantKnowledgeStore):
    """Search results are scoped to the querying tenant."""
    # Insert chunks for two different tenants
    chunk_t1 = _make_chunk(
        tenant_id="tenant-1",
        content="Tenant 1 product knowledge",
        dense_seed=0.2,
    )
    chunk_t2 = _make_chunk(
        tenant_id="tenant-2",
        content="Tenant 2 product knowledge",
        dense_seed=0.3,
    )

    await store.upsert_chunks([chunk_t1], tenant_id="tenant-1")
    await store.upsert_chunks([chunk_t2], tenant_id="tenant-2")

    # Search as tenant-1: should only find tenant-1 data
    results = await store.hybrid_search(
        query_text="product knowledge",
        tenant_id="tenant-1",
    )

    tenant_ids = {r.tenant_id for r in results}
    assert "tenant-2" not in tenant_ids
    if results:
        assert all(r.tenant_id == "tenant-1" for r in results)


# ── Tests: Metadata Filtering ───────────────────────────────────────────────


async def test_filter_by_product_category(store: QdrantKnowledgeStore):
    """Filtering by product_category returns only matching chunks."""
    chunk_billing = _make_chunk(
        tenant_id="tenant-1",
        content="Billing system features",
        product_category="billing",
        dense_seed=0.4,
    )
    chunk_charging = _make_chunk(
        tenant_id="tenant-1",
        content="Charging infrastructure",
        product_category="charging",
        dense_seed=0.5,
    )

    await store.upsert_chunks(
        [chunk_billing, chunk_charging], tenant_id="tenant-1"
    )

    results = await store.hybrid_search(
        query_text="system features",
        tenant_id="tenant-1",
        filters={"product_category": "billing"},
    )

    for r in results:
        assert r.metadata.product_category == "billing"


async def test_filter_by_sales_stage(store: QdrantKnowledgeStore):
    """Filtering by sales_stage returns only matching chunks."""
    chunk_discovery = _make_chunk(
        tenant_id="tenant-1",
        content="Discovery questions for billing",
        product_category="billing",
        sales_stage=["discovery"],
        dense_seed=0.6,
    )
    chunk_demo = _make_chunk(
        tenant_id="tenant-1",
        content="Demo script for billing",
        product_category="billing",
        sales_stage=["demo"],
        dense_seed=0.7,
    )

    await store.upsert_chunks(
        [chunk_discovery, chunk_demo], tenant_id="tenant-1"
    )

    results = await store.hybrid_search(
        query_text="billing content",
        tenant_id="tenant-1",
        filters={"sales_stage": "discovery"},
    )

    for r in results:
        assert "discovery" in r.metadata.sales_stage


# ── Tests: Delete ───────────────────────────────────────────────────────────


async def test_delete_chunks(store: QdrantKnowledgeStore):
    """Deleting chunks removes them from the collection."""
    chunk = _make_chunk(tenant_id="tenant-1", content="To be deleted")
    await store.upsert_chunks([chunk], tenant_id="tenant-1")

    # Verify it exists
    assert await store.get_chunk(chunk.id, tenant_id="tenant-1") is not None

    # Delete it
    await store.delete_chunks([chunk.id], tenant_id="tenant-1")

    # Verify it's gone
    assert await store.get_chunk(chunk.id, tenant_id="tenant-1") is None


# ── Tests: Hybrid Search ────────────────────────────────────────────────────


async def test_hybrid_search_returns_results(store: QdrantKnowledgeStore):
    """Hybrid search returns results when matching chunks exist."""
    chunks = [
        _make_chunk(
            tenant_id="tenant-1",
            content=f"Knowledge chunk number {i}",
            dense_seed=0.1 * (i + 1),
            sparse_terms=[1, 5, 10 + i, 50, 100],
        )
        for i in range(5)
    ]

    await store.upsert_chunks(chunks, tenant_id="tenant-1")

    results = await store.hybrid_search(
        query_text="knowledge chunk",
        tenant_id="tenant-1",
        top_k=3,
    )

    assert len(results) <= 3
    assert len(results) > 0
    assert all(r.tenant_id == "tenant-1" for r in results)


async def test_hybrid_search_empty_for_wrong_tenant(
    store: QdrantKnowledgeStore,
):
    """Hybrid search returns empty for a tenant with no data."""
    chunk = _make_chunk(
        tenant_id="tenant-1",
        content="Only in tenant 1",
        dense_seed=0.8,
    )
    await store.upsert_chunks([chunk], tenant_id="tenant-1")

    results = await store.hybrid_search(
        query_text="Only in tenant 1",
        tenant_id="tenant-nonexistent",
    )

    assert len(results) == 0
