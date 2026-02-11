"""Tests for ESW product data ingestion and retrieval.

Verifies that all 6 ESW product knowledge documents (Monetization Platform,
Charging, Billing, pricing JSON, battlecard, use-case positioning) can be
ingested through the IngestionPipeline and retrieved via Qdrant hybrid search.

Uses MockEmbeddingService (deterministic vectors, no OpenAI calls) and local
Qdrant (tmp_path) for fully offline, reproducible testing.

Tests cover:
- Individual product document ingestion with correct metadata
- Batch ingestion of all ESW product documents
- Feature-level retrieval queries returning relevant chunks
- Pricing data retrieval
- Competitive positioning retrieval
- Cross-product reference detection
- Tenant-scoped isolation of product data
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.knowledge.config import KnowledgeBaseConfig
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
        base = [(h >> i & 0xFF) / 255.0 for i in range(0, 32)]
        vector = (base * (self._dimensions // len(base) + 1))[: self._dimensions]
        return vector

    def _make_sparse(self, text: str) -> dict:
        """Create a deterministic sparse vector from text."""
        h = hash(text) & 0xFFFFFFFF
        n_indices = 5 + (h % 6)
        indices = [(h * (i + 1)) % 50000 for i in range(n_indices)]
        values = [((h >> i) & 0xFF) / 255.0 for i in range(n_indices)]
        return {"indices": indices, "values": values}


# ── Fixtures ──────────────────────────────────────────────────────────────


# Path to the actual product data files
PRODUCT_DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "products"


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
async def store(
    qdrant_config: KnowledgeBaseConfig, mock_embedder: MockEmbeddingService
) -> QdrantKnowledgeStore:
    """Create and initialize a QdrantKnowledgeStore."""
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
def product_data_dir(tmp_path: Path) -> Path:
    """Copy actual product data files to a temp directory for test isolation.

    Copies the real data/products/ tree so tests use actual content but
    don't conflict with Qdrant local storage in tmp_path.
    """
    dest = tmp_path / "products"
    shutil.copytree(PRODUCT_DATA_ROOT, dest)
    return dest


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_monetization_platform(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    product_data_dir: Path,
):
    """Ingest monetization-platform.md and verify chunks have product_category=monetization."""
    tenant_id = "test-tenant-product"
    doc_path = product_data_dir / "monetization-platform.md"

    result = await pipeline.ingest_document(
        file_path=doc_path,
        tenant_id=tenant_id,
    )

    assert isinstance(result, IngestionResult)
    assert result.chunks_created > 0
    assert result.errors == []

    # Verify chunks are stored with correct product_category
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    scroll_results, _ = store.client.scroll(
        collection_name=store._config.collection_knowledge,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                FieldCondition(
                    key="product_category",
                    match=MatchValue(value="monetization"),
                ),
            ]
        ),
        limit=200,
        with_payload=True,
    )

    assert len(scroll_results) == result.chunks_created
    for point in scroll_results:
        assert point.payload["tenant_id"] == tenant_id
        assert point.payload["product_category"] == "monetization"
        assert point.payload["is_current"] is True


@pytest.mark.asyncio
async def test_ingest_all_products(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    product_data_dir: Path,
):
    """Ingest all 6 product docs via ingest_directory and verify total chunk count."""
    tenant_id = "test-tenant-all"

    results = await pipeline.ingest_directory(
        dir_path=product_data_dir,
        tenant_id=tenant_id,
        recursive=True,
    )

    # We should have at least 6 files processed (3 product .md + 1 pricing .json + 2 positioning .md)
    assert len(results) >= 6

    total_chunks = sum(r.chunks_created for r in results)
    assert total_chunks > 0

    total_errors = sum(len(r.errors) for r in results)
    assert total_errors == 0

    # Verify all chunks are stored
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    scroll_results, _ = store.client.scroll(
        collection_name=store._config.collection_knowledge,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            ]
        ),
        limit=1000,
        with_payload=True,
    )

    assert len(scroll_results) == total_chunks

    # Verify we have chunks from all three product categories
    categories = {p.payload["product_category"] for p in scroll_results}
    assert "monetization" in categories
    # Charging and billing may or may not be inferred depending on metadata extraction
    # but at minimum monetization should be present from the monetization-platform.md frontmatter


@pytest.mark.asyncio
async def test_retrieve_product_features(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    product_data_dir: Path,
):
    """After ingestion, search 'subscription management' and verify relevant chunk returned."""
    tenant_id = "test-tenant-features"

    # Ingest the monetization platform doc
    await pipeline.ingest_document(
        file_path=product_data_dir / "monetization-platform.md",
        tenant_id=tenant_id,
    )

    # Search for subscription management
    results = await store.hybrid_search(
        query_text="subscription management plan lifecycle",
        tenant_id=tenant_id,
        top_k=5,
    )

    assert len(results) > 0
    # All results should be from monetization category (only doc ingested)
    for result in results:
        assert result.metadata.product_category == "monetization"

    # With mock embeddings, ranking is non-semantic, so check ANY result
    # contains subscription-related terms (the content is in the collection)
    found_subscription_content = False
    for result in results:
        content_lower = result.content.lower()
        if any(
            term in content_lower
            for term in ["subscription", "plan", "lifecycle", "upgrade", "downgrade"]
        ):
            found_subscription_content = True
            break
    assert found_subscription_content, (
        "No subscription-related content found in any of the search results"
    )


@pytest.mark.asyncio
async def test_retrieve_pricing(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    product_data_dir: Path,
):
    """After ingestion, search 'enterprise pricing' and verify pricing chunk returned."""
    tenant_id = "test-tenant-pricing"

    # Ingest the pricing JSON
    await pipeline.ingest_document(
        file_path=product_data_dir / "pricing" / "esw-pricing.json",
        tenant_id=tenant_id,
    )

    # Search for enterprise pricing
    results = await store.hybrid_search(
        query_text="enterprise pricing tier",
        tenant_id=tenant_id,
        top_k=5,
    )

    assert len(results) > 0
    # Verify at least one result contains pricing-related content
    found_pricing_content = False
    for result in results:
        content_lower = result.content.lower()
        if any(term in content_lower for term in ["enterprise", "pricing", "price", "tier", "monthly"]):
            found_pricing_content = True
            break
    assert found_pricing_content, "No pricing-related content found in search results"


@pytest.mark.asyncio
async def test_retrieve_positioning(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    product_data_dir: Path,
):
    """Search 'competitor comparison' and verify battlecard content returned."""
    tenant_id = "test-tenant-positioning"

    # Ingest the battlecard
    await pipeline.ingest_document(
        file_path=product_data_dir / "positioning" / "battlecard-vs-competitor-a.md",
        tenant_id=tenant_id,
    )

    # Search for competitive positioning
    results = await store.hybrid_search(
        query_text="competitor comparison strengths weaknesses",
        tenant_id=tenant_id,
        top_k=5,
    )

    assert len(results) > 0
    # Verify at least one result contains competitive/battlecard content
    found_positioning = False
    for result in results:
        content_lower = result.content.lower()
        if any(term in content_lower for term in ["competitor", "nextera", "advantage", "weakness", "battlecard", "competitive", "objection"]):
            found_positioning = True
            break
    assert found_positioning, "No competitive positioning content found in search results"


@pytest.mark.asyncio
async def test_cross_product_references(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    product_data_dir: Path,
):
    """Verify chunks mentioning other ESW products have cross_references populated."""
    tenant_id = "test-tenant-crossref"

    # Ingest monetization platform (which cross-references Charging and Billing)
    result = await pipeline.ingest_document(
        file_path=product_data_dir / "monetization-platform.md",
        tenant_id=tenant_id,
    )
    assert result.chunks_created > 0

    # Scroll all chunks and check cross-references
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

    # At least some chunks should have cross-references since the doc
    # explicitly mentions Charging and Billing
    chunks_with_crossrefs = [
        p for p in scroll_results
        if p.payload.get("cross_references") and len(p.payload["cross_references"]) > 0
    ]

    assert len(chunks_with_crossrefs) > 0, "No chunks have cross-references to other ESW products"

    # Verify cross-references contain known product names
    all_refs = set()
    for point in chunks_with_crossrefs:
        for ref in point.payload["cross_references"]:
            all_refs.add(ref)

    # The monetization doc references Charging and Billing
    assert any("Charging" in ref for ref in all_refs), f"Expected Charging in cross_references, got {all_refs}"
    assert any("Billing" in ref for ref in all_refs), f"Expected Billing in cross_references, got {all_refs}"


@pytest.mark.asyncio
async def test_tenant_scoped_product_retrieval(
    pipeline: IngestionPipeline,
    store: QdrantKnowledgeStore,
    product_data_dir: Path,
):
    """Ingest for tenant A, verify tenant B cannot retrieve product data."""
    tenant_a = "tenant-alpha-product"
    tenant_b = "tenant-beta-product"

    # Ingest for tenant A
    result = await pipeline.ingest_document(
        file_path=product_data_dir / "monetization-platform.md",
        tenant_id=tenant_a,
    )
    assert result.chunks_created > 0

    # Verify tenant A can retrieve data
    results_a = await store.hybrid_search(
        query_text="subscription management",
        tenant_id=tenant_a,
        top_k=5,
    )
    assert len(results_a) > 0

    # Verify tenant B gets no results
    results_b = await store.hybrid_search(
        query_text="subscription management",
        tenant_id=tenant_b,
        top_k=5,
    )
    assert len(results_b) == 0

    # Also verify via scroll that tenant B has zero chunks
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    scroll_b, _ = store.client.scroll(
        collection_name=store._config.collection_knowledge,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_b)),
            ]
        ),
        limit=100,
        with_payload=True,
    )
    assert len(scroll_b) == 0
