"""Tests for regional sales nuances and Qdrant ingestion.

Tests cover:
- Structured access to APAC, EMEA, Americas via RegionalNuances
- Pricing modifier correctness
- Compliance requirements retrieval
- Regional content ingestion into Qdrant with correct region tags
- Semantic search over regional content with region filters
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.knowledge.config import KnowledgeBaseConfig
from src.knowledge.embeddings import EmbeddingService
from src.knowledge.methodology.loader import MethodologyLoader
from src.knowledge.qdrant_client import QdrantKnowledgeStore
from src.knowledge.regional.nuances import RegionalNuances, get_regional_context


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_dense_vector(seed: float = 0.1, dims: int = 1536) -> list[float]:
    """Generate a deterministic dense vector for testing."""
    return [math.sin(seed * (i + 1)) for i in range(dims)]


def _make_sparse_vector(terms: list[int] | None = None) -> dict:
    """Generate a deterministic sparse vector for testing."""
    if terms is None:
        terms = [1, 5, 10, 50, 100]
    return {
        "indices": terms,
        "values": [1.0 / (i + 1) for i in range(len(terms))],
    }


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

    async def mock_embed_text(text: str) -> tuple[list[float], dict]:
        seed = abs(hash(text)) % 1000 / 1000.0 + 0.01
        return _make_dense_vector(seed), _make_sparse_vector()

    service.embed_text = AsyncMock(side_effect=mock_embed_text)

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


@pytest.fixture
def nuances() -> RegionalNuances:
    """Create a RegionalNuances instance."""
    return RegionalNuances()


# ── Tests: Structured Access ───────────────────────────────────────────────


class TestRegionalNuancesAccess:
    """Verify structured access to regional nuance data."""

    def test_all_regions_present(self, nuances: RegionalNuances):
        """RegionalNuances contains APAC, EMEA, and Americas."""
        assert set(nuances.regions.keys()) == {"apac", "emea", "americas"}

    def test_list_regions(self, nuances: RegionalNuances):
        """list_regions returns sorted region codes."""
        assert nuances.list_regions() == ["americas", "apac", "emea"]

    def test_get_regional_context_apac(self, nuances: RegionalNuances):
        """get_regional_context returns complete APAC context."""
        ctx = nuances.get_regional_context("apac")
        assert ctx["code"] == "apac"
        assert ctx["name"] == "Asia-Pacific"
        assert "pricing" in ctx
        assert ctx["pricing"]["modifier"] == 0.9
        assert "compliance" in ctx
        assert len(ctx["compliance"]) > 0
        assert "cultural_notes" in ctx
        assert len(ctx["cultural_notes"]) > 0
        assert "key_markets" in ctx
        assert "Japan" in ctx["key_markets"]

    def test_get_regional_context_emea(self, nuances: RegionalNuances):
        """get_regional_context returns complete EMEA context."""
        ctx = nuances.get_regional_context("emea")
        assert ctx["code"] == "emea"
        assert ctx["name"] == "Europe, Middle East, and Africa"
        assert ctx["pricing"]["currency"] == "EUR"
        assert any("GDPR" in fw for fw in ctx["compliance"])

    def test_get_regional_context_americas(self, nuances: RegionalNuances):
        """get_regional_context returns complete Americas context."""
        ctx = nuances.get_regional_context("americas")
        assert ctx["code"] == "americas"
        assert ctx["name"] == "Americas"
        assert ctx["pricing"]["currency"] == "USD"
        assert any("SOC 2" in fw for fw in ctx["compliance"])

    def test_get_regional_context_case_insensitive(self, nuances: RegionalNuances):
        """get_regional_context works with any case."""
        ctx_lower = nuances.get_regional_context("apac")
        ctx_upper = nuances.get_regional_context("APAC")
        assert ctx_lower["code"] == ctx_upper["code"]

    def test_get_regional_context_unknown_raises(self, nuances: RegionalNuances):
        """get_regional_context raises KeyError for unknown region."""
        with pytest.raises(KeyError, match="Unknown region"):
            nuances.get_regional_context("antartica")


class TestRegionalPricingModifier:
    """Verify pricing modifiers for each region."""

    def test_apac_pricing_modifier(self, nuances: RegionalNuances):
        """APAC has 0.9 pricing modifier (10% regional discount)."""
        assert nuances.get_pricing_modifier("apac") == 0.9

    def test_emea_pricing_modifier(self, nuances: RegionalNuances):
        """EMEA has 1.0 pricing modifier (no discount)."""
        assert nuances.get_pricing_modifier("emea") == 1.0

    def test_americas_pricing_modifier(self, nuances: RegionalNuances):
        """Americas has 1.0 pricing modifier (no discount)."""
        assert nuances.get_pricing_modifier("americas") == 1.0

    def test_pricing_modifier_unknown_raises(self, nuances: RegionalNuances):
        """get_pricing_modifier raises KeyError for unknown region."""
        with pytest.raises(KeyError, match="Unknown region"):
            nuances.get_pricing_modifier("mars")


class TestRegionalComplianceRequirements:
    """Verify compliance framework retrieval."""

    def test_emea_compliance_includes_gdpr(self, nuances: RegionalNuances):
        """EMEA compliance includes GDPR."""
        compliance = nuances.get_compliance_requirements("emea")
        assert any("GDPR" in fw for fw in compliance)

    def test_americas_compliance_includes_soc2(self, nuances: RegionalNuances):
        """Americas compliance includes SOC 2."""
        compliance = nuances.get_compliance_requirements("americas")
        assert any("SOC 2" in fw for fw in compliance)

    def test_apac_compliance_includes_pdpa(self, nuances: RegionalNuances):
        """APAC compliance includes PDPA (Singapore)."""
        compliance = nuances.get_compliance_requirements("apac")
        assert any("PDPA" in fw for fw in compliance)

    def test_compliance_unknown_raises(self, nuances: RegionalNuances):
        """get_compliance_requirements raises KeyError for unknown region."""
        with pytest.raises(KeyError, match="Unknown region"):
            nuances.get_compliance_requirements("nowhere")


class TestModuleLevelFunction:
    """Verify the module-level convenience function."""

    def test_get_regional_context_function(self):
        """Module-level get_regional_context works correctly."""
        ctx = get_regional_context("apac")
        assert ctx["code"] == "apac"
        assert ctx["pricing"]["modifier"] == 0.9


# ── Tests: Regional Ingestion ──────────────────────────────────────────────


class TestRegionalIngestion:
    """Verify regional content is correctly ingested into Qdrant."""

    async def test_regional_ingestion_creates_chunks(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """Loading regional data creates chunks in Qdrant."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        count = await loader.load_regional_data(tenant_id="test-tenant")

        # Should create multiple chunks (sections across 3 regional files)
        assert count > 0
        assert count >= 9  # At least ~3 substantial sections per region file

    async def test_regional_chunks_have_correct_content_type(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """All regional chunks are tagged with content_type='regional'."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        await loader.load_regional_data(tenant_id="test-tenant")

        results = await store.hybrid_search(
            query_text="regional sales nuances",
            tenant_id="test-tenant",
            filters={"content_type": "regional"},
        )

        assert len(results) > 0
        for chunk in results:
            assert chunk.metadata.content_type == "regional"

    async def test_regional_search_with_region_filter(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """Searching with region='emea' filter returns EMEA content."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        await loader.load_regional_data(tenant_id="test-tenant")

        results = await store.hybrid_search(
            query_text="GDPR compliance data protection",
            tenant_id="test-tenant",
            filters={"region": "emea"},
        )

        for chunk in results:
            assert "emea" in chunk.metadata.region

    async def test_regional_search_apac(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """Searching with region='apac' filter returns APAC content."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        await loader.load_regional_data(tenant_id="test-tenant")

        results = await store.hybrid_search(
            query_text="relationship selling hierarchy consensus",
            tenant_id="test-tenant",
            filters={"region": "apac"},
        )

        for chunk in results:
            assert "apac" in chunk.metadata.region

    async def test_regional_tenant_isolation(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """Regional data loaded for one tenant is not visible to another."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        await loader.load_regional_data(tenant_id="tenant-x")

        results = await store.hybrid_search(
            query_text="APAC regional nuances",
            tenant_id="tenant-y",
        )

        assert len(results) == 0

    async def test_load_all_loads_both_types(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """load_all loads both methodology and regional content."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        counts = await loader.load_all(tenant_id="test-tenant")

        assert counts["methodology"] > 0
        assert counts["regional"] > 0
        assert counts["methodology"] + counts["regional"] > 20  # Substantial content
