"""End-to-end tests for the IngestionPipeline.

Uses mock EmbeddingService (deterministic vectors, no OpenAI calls) and
local Qdrant (tmp_path) for fully offline, reproducible testing.

Tests cover:
- Single document ingestion through full pipeline
- Directory ingestion with multiple files
- Document update with versioning
- Tenant-scoped isolation
- Metadata overrides
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.knowledge.config import KnowledgeBaseConfig
from src.knowledge.embeddings import EmbeddingService
from src.knowledge.ingestion.chunker import KnowledgeChunker
from src.knowledge.ingestion.metadata_extractor import MetadataExtractor
from src.knowledge.ingestion.pipeline import IngestionPipeline, IngestionResult
from src.knowledge.qdrant_client import QdrantKnowledgeStore


# ── Mock Embedding Service ────────────────────────────────────────────────


class MockEmbeddingService:
    """Deterministic embedding service for testing.

    Returns fixed-dimension vectors based on text hash, avoiding OpenAI calls.
    Dense vectors are 1536-dimensional (matching text-embedding-3-small).
    Sparse vectors use deterministic indices/values.
    """

    def __init__(self, dimensions: int = 1536):
        self._dimensions = dimensions

    async def embed_text(self, text: str) -> tuple[list[float], dict]:
        """Generate deterministic embeddings for a single text."""
        dense = self._make_dense(text)
        sparse = self._make_sparse(text)
        return dense, sparse

    async def embed_batch(self, texts: list[str]) -> list[tuple[list[float], dict]]:
        """Generate deterministic embeddings for a batch of texts."""
        results = []
        for text in texts:
            dense = self._make_dense(text)
            sparse = self._make_sparse(text)
            results.append((dense, sparse))
        return results

    def _make_dense(self, text: str) -> list[float]:
        """Create a deterministic dense vector from text hash."""
        h = hash(text) & 0xFFFFFFFF
        # Create a vector that's different for different texts
        base = [(h >> i & 0xFF) / 255.0 for i in range(0, 32)]
        # Repeat to fill dimensions
        vector = (base * (self._dimensions // len(base) + 1))[: self._dimensions]
        return vector

    def _make_sparse(self, text: str) -> dict:
        """Create a deterministic sparse vector from text."""
        h = hash(text) & 0xFFFFFFFF
        # Generate 5-10 indices based on hash
        n_indices = 5 + (h % 6)
        indices = [(h * (i + 1)) % 50000 for i in range(n_indices)]
        values = [((h >> i) & 0xFF) / 255.0 for i in range(n_indices)]
        return {"indices": indices, "values": values}


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def qdrant_config(tmp_path: Path) -> KnowledgeBaseConfig:
    """Create a KnowledgeBaseConfig pointing to a tmp_path Qdrant store."""
    return KnowledgeBaseConfig(
        qdrant_path=str(tmp_path / "qdrant_data"),
        openai_api_key="test-key-not-used",
    )


@pytest.fixture
def mock_embedder() -> MockEmbeddingService:
    """Create a mock embedding service."""
    return MockEmbeddingService()


@pytest.fixture
def chunker() -> KnowledgeChunker:
    """Create a KnowledgeChunker with default settings."""
    return KnowledgeChunker(chunk_size=512, overlap_pct=0.15)


@pytest.fixture
def extractor() -> MetadataExtractor:
    """Create a MetadataExtractor with default settings."""
    return MetadataExtractor()


@pytest.fixture
async def store(qdrant_config: KnowledgeBaseConfig, mock_embedder: MockEmbeddingService) -> QdrantKnowledgeStore:
    """Create and initialize a QdrantKnowledgeStore."""
    # The real store requires a real EmbeddingService but we'll
    # override embedding generation in the pipeline
    s = QdrantKnowledgeStore(qdrant_config, mock_embedder)  # type: ignore[arg-type]
    await s.initialize_collections()
    return s


@pytest.fixture
def pipeline(
    store: QdrantKnowledgeStore,
    mock_embedder: MockEmbeddingService,
    chunker: KnowledgeChunker,
    extractor: MetadataExtractor,
) -> IngestionPipeline:
    """Create an IngestionPipeline with mock embedder."""
    return IngestionPipeline(
        store=store,
        embedder=mock_embedder,  # type: ignore[arg-type]
        chunker=chunker,
        extractor=extractor,
    )


@pytest.fixture
def docs_dir(tmp_path: Path) -> Path:
    """Create a dedicated docs subdirectory separate from qdrant_data."""
    d = tmp_path / "docs"
    d.mkdir()
    return d


@pytest.fixture
def sample_markdown(docs_dir: Path) -> Path:
    """Create a small test markdown document."""
    content = """\
---
product_category: monetization
region:
  - global
---

# Test Product

A simple test product for pipeline testing.

## Features

The product has great features including subscription management
and real-time metering. The API provides integration capabilities
for enterprise customers.

## Pricing

Enterprise pricing starts at $1000/month with volume discounts.
Contact sales for custom pricing and SLA terms.
"""
    file_path = docs_dir / "test_product.md"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def sample_json(docs_dir: Path) -> Path:
    """Create a small test JSON document."""
    data = {
        "product": "Charging Platform",
        "features": [
            {"name": "Usage Metering", "description": "Real-time event metering"},
            {"name": "Rating Engine", "description": "Flexible pricing calculations"},
        ],
    }
    file_path = docs_dir / "charging_features.json"
    file_path.write_text(json.dumps(data, indent=2))
    return file_path


@pytest.fixture
def sample_text(docs_dir: Path) -> Path:
    """Create a small test text document."""
    content = "Billing Platform overview. Invoice generation and payment processing for enterprise."
    file_path = docs_dir / "billing_overview.txt"
    file_path.write_text(content)
    return file_path


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_single_document(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    sample_markdown: Path,
):
    """Ingest a single markdown document and verify chunks are stored."""
    tenant_id = "test-tenant-1"

    result = await pipeline.ingest_document(
        file_path=sample_markdown,
        tenant_id=tenant_id,
    )

    assert isinstance(result, IngestionResult)
    assert result.chunks_created > 0
    assert result.errors == []
    assert str(sample_markdown) in result.document_source

    # Verify chunks are actually in Qdrant
    # Scroll to find stored chunks
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    scroll_results, _ = store.client.scroll(
        collection_name=store._config.collection_knowledge,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            ]
        ),
        limit=100,
        with_payload=True,
    )

    assert len(scroll_results) == result.chunks_created
    for point in scroll_results:
        assert point.payload["tenant_id"] == tenant_id
        assert point.payload["is_current"] is True
        assert point.payload["version"] == 1


@pytest.mark.asyncio
async def test_ingest_directory(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    sample_markdown: Path,
    sample_json: Path,
    sample_text: Path,
):
    """Ingest a directory of mixed format documents."""
    tenant_id = "test-tenant-dir"
    # All fixtures are in docs_dir
    directory = sample_markdown.parent  # docs_dir

    results = await pipeline.ingest_directory(
        dir_path=directory,
        tenant_id=tenant_id,
    )

    assert len(results) >= 3  # At least our 3 test files
    total_chunks = sum(r.chunks_created for r in results)
    assert total_chunks > 0

    # No errors expected
    total_errors = sum(len(r.errors) for r in results)
    assert total_errors == 0

    # Verify all chunks are stored with correct tenant
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    scroll_results, _ = store.client.scroll(
        collection_name=store._config.collection_knowledge,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            ]
        ),
        limit=200,
        with_payload=True,
    )

    assert len(scroll_results) == total_chunks


@pytest.mark.asyncio
async def test_document_update_versioning(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    docs_dir: Path,
):
    """Ingest, then update a document and verify versioning."""
    tenant_id = "test-tenant-version"

    # Create initial document
    doc_path = docs_dir / "versioned_doc.md"
    doc_path.write_text("""\
---
product_category: billing
---

# Billing Features

Invoice generation with PDF output.
""")

    # Initial ingestion
    result_v1 = await pipeline.ingest_document(
        file_path=doc_path,
        tenant_id=tenant_id,
    )
    assert result_v1.chunks_created > 0
    assert result_v1.errors == []

    # Update the document content
    doc_path.write_text("""\
---
product_category: billing
---

# Billing Features V2

Enhanced invoice generation with PDF and CSV output.
Multi-currency support added.
""")

    # Re-ingest via update_document
    result_v2 = await pipeline.update_document(
        file_path=doc_path,
        tenant_id=tenant_id,
    )
    assert result_v2.chunks_created > 0
    assert result_v2.version == 2
    assert result_v2.errors == []

    # Verify old chunks are marked as not current
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    # Get all chunks for this document
    all_chunks, _ = store.client.scroll(
        collection_name=store._config.collection_knowledge,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                FieldCondition(
                    key="source_document",
                    match=MatchValue(value=str(doc_path)),
                ),
            ]
        ),
        limit=200,
        with_payload=True,
    )

    old_chunks = [p for p in all_chunks if p.payload.get("is_current") is False]
    new_chunks = [p for p in all_chunks if p.payload.get("is_current") is True]

    assert len(old_chunks) == result_v1.chunks_created
    assert len(new_chunks) == result_v2.chunks_created

    # Verify version numbers
    for chunk in old_chunks:
        assert chunk.payload["version"] == 1

    for chunk in new_chunks:
        assert chunk.payload["version"] == 2


@pytest.mark.asyncio
async def test_tenant_scoped_ingestion(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    sample_markdown: Path,
):
    """Verify that ingestion for tenant A cannot be retrieved by tenant B."""
    tenant_a = "tenant-alpha"
    tenant_b = "tenant-beta"

    # Ingest for tenant A
    result = await pipeline.ingest_document(
        file_path=sample_markdown,
        tenant_id=tenant_a,
    )
    assert result.chunks_created > 0

    # Verify tenant A can see the chunks
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    results_a, _ = store.client.scroll(
        collection_name=store._config.collection_knowledge,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_a)),
            ]
        ),
        limit=100,
        with_payload=True,
    )
    assert len(results_a) == result.chunks_created

    # Verify tenant B cannot see the chunks
    results_b, _ = store.client.scroll(
        collection_name=store._config.collection_knowledge,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_b)),
            ]
        ),
        limit=100,
        with_payload=True,
    )
    assert len(results_b) == 0


@pytest.mark.asyncio
async def test_metadata_overrides(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    sample_markdown: Path,
):
    """Verify metadata_overrides are applied to all stored chunks."""
    tenant_id = "test-tenant-overrides"

    overrides = {
        "product_category": "charging",
        "region": ["apac"],
        "content_type": "methodology",
    }

    result = await pipeline.ingest_document(
        file_path=sample_markdown,
        tenant_id=tenant_id,
        metadata_overrides=overrides,
    )
    assert result.chunks_created > 0

    # Verify overrides are in the stored payload
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    stored, _ = store.client.scroll(
        collection_name=store._config.collection_knowledge,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            ]
        ),
        limit=100,
        with_payload=True,
    )

    assert len(stored) == result.chunks_created
    for point in stored:
        assert point.payload["product_category"] == "charging"
        assert point.payload["content_type"] == "methodology"


@pytest.mark.asyncio
async def test_ingestion_result_model():
    """Test IngestionResult model validation."""
    result = IngestionResult(
        chunks_created=5,
        document_source="test.md",
        version=2,
        errors=["some warning"],
    )
    assert result.chunks_created == 5
    assert result.document_source == "test.md"
    assert result.version == 2
    assert result.errors == ["some warning"]


@pytest.mark.asyncio
async def test_ingest_nonexistent_file(
    pipeline: IngestionPipeline,
):
    """Ingesting a nonexistent file returns error in result."""
    result = await pipeline.ingest_document(
        file_path="/nonexistent/file.md",
        tenant_id="test-tenant",
    )
    assert result.chunks_created == 0
    assert len(result.errors) > 0


@pytest.mark.asyncio
async def test_ingest_directory_nonexistent(
    pipeline: IngestionPipeline,
):
    """Ingesting from a nonexistent directory returns error."""
    results = await pipeline.ingest_directory(
        dir_path="/nonexistent/dir",
        tenant_id="test-tenant",
    )
    assert len(results) == 1
    assert len(results[0].errors) > 0


@pytest.mark.asyncio
async def test_esw_data_imports():
    """Verify ESW data module imports and constants."""
    from src.knowledge.products import (
        ESW_DEFAULT_TENANT_ID,
        PRODUCT_DATA_DIR,
        ingest_all_esw_products,
        verify_product_retrieval,
    )

    assert ESW_DEFAULT_TENANT_ID == "esw-default"
    assert PRODUCT_DATA_DIR == Path("data/products")
    assert callable(ingest_all_esw_products)
    assert callable(verify_product_retrieval)
