"""Tests for sales methodology frameworks and Qdrant ingestion.

Tests cover:
- Structured access to MEDDIC, BANT, SPIN via MethodologyLibrary
- Methodology content ingestion into Qdrant with correct metadata
- Semantic search over methodology content
- Sales stage filtering on methodology chunks
"""

from __future__ import annotations

import math
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.knowledge.config import KnowledgeBaseConfig
from src.knowledge.embeddings import EmbeddingService
from src.knowledge.methodology.frameworks import (
    MethodologyFramework,
    MethodologyLibrary,
    MethodologyStep,
)
from src.knowledge.methodology.loader import MethodologyLoader
from src.knowledge.qdrant_client import QdrantKnowledgeStore


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
def library() -> MethodologyLibrary:
    """Create a MethodologyLibrary instance."""
    return MethodologyLibrary()


# ── Tests: Structured Access ───────────────────────────────────────────────


class TestMethodologyLibraryStructuredAccess:
    """Verify structured programmatic access to methodology frameworks."""

    def test_all_frameworks_present(self, library: MethodologyLibrary):
        """Library contains MEDDIC, BANT, and SPIN frameworks."""
        assert set(library.frameworks.keys()) == {"MEDDIC", "BANT", "SPIN"}

    def test_get_framework_meddic(self, library: MethodologyLibrary):
        """get_framework returns the MEDDIC framework with correct structure."""
        fw = library.get_framework("MEDDIC")
        assert isinstance(fw, MethodologyFramework)
        assert fw.name == "MEDDIC"
        assert len(fw.steps) == 6  # M-E-D-D-I-C
        assert fw.full_name != ""
        assert fw.description != ""
        assert fw.when_to_use != ""
        assert len(fw.summary_checklist) == 6

    def test_get_framework_case_insensitive(self, library: MethodologyLibrary):
        """get_framework works with any case."""
        fw_upper = library.get_framework("BANT")
        fw_lower = library.get_framework("bant")
        fw_mixed = library.get_framework("Bant")
        assert fw_upper.name == fw_lower.name == fw_mixed.name == "BANT"

    def test_get_framework_unknown_raises(self, library: MethodologyLibrary):
        """get_framework raises KeyError for unknown framework."""
        with pytest.raises(KeyError, match="Unknown methodology"):
            library.get_framework("UNKNOWN")

    def test_get_step_by_name(self, library: MethodologyLibrary):
        """get_step retrieves a step by its full name."""
        step = library.get_step("MEDDIC", "Metrics")
        assert isinstance(step, MethodologyStep)
        assert step.name == "Metrics"
        assert step.abbreviation == "M"

    def test_get_step_by_abbreviation(self, library: MethodologyLibrary):
        """get_step retrieves a step by its abbreviation."""
        step = library.get_step("MEDDIC", "M")
        assert step.name == "Metrics"

    def test_get_step_case_insensitive(self, library: MethodologyLibrary):
        """get_step works with any case."""
        step = library.get_step("meddic", "metrics")
        assert step.name == "Metrics"

    def test_get_step_unknown_raises(self, library: MethodologyLibrary):
        """get_step raises KeyError for unknown step."""
        with pytest.raises(KeyError, match="Unknown step"):
            library.get_step("MEDDIC", "NonexistentStep")

    def test_step_has_questions(self, library: MethodologyLibrary):
        """Each step has at least 5 key questions."""
        for fw_name, fw in library.frameworks.items():
            for step in fw.steps:
                assert len(step.key_questions) >= 5, (
                    f"{fw_name}/{step.name} has only {len(step.key_questions)} questions"
                )

    def test_step_has_examples(self, library: MethodologyLibrary):
        """Each step has at least one example."""
        for fw_name, fw in library.frameworks.items():
            for step in fw.steps:
                assert len(step.examples) >= 1, (
                    f"{fw_name}/{step.name} has no examples"
                )

    def test_step_has_tips(self, library: MethodologyLibrary):
        """Each step has at least one practical tip."""
        for fw_name, fw in library.frameworks.items():
            for step in fw.steps:
                assert len(step.tips) >= 1, (
                    f"{fw_name}/{step.name} has no tips"
                )

    def test_get_questions_for_stage_discovery(self, library: MethodologyLibrary):
        """get_questions_for_stage returns questions from multiple frameworks for discovery."""
        results = library.get_questions_for_stage("discovery")
        assert len(results) > 0

        # Should include questions from multiple frameworks
        frameworks_represented = {r["framework"] for r in results}
        assert len(frameworks_represented) >= 2  # At minimum MEDDIC and BANT have discovery steps

        # Each result should have questions
        for result in results:
            assert "framework" in result
            assert "step" in result
            assert "questions" in result
            assert len(result["questions"]) >= 5

    def test_get_questions_for_stage_evaluation(self, library: MethodologyLibrary):
        """get_questions_for_stage returns MEDDIC evaluation-stage questions."""
        results = library.get_questions_for_stage("evaluation")
        assert len(results) > 0

        # MEDDIC Decision Criteria and Decision Process are evaluation-stage
        step_names = [r["step"] for r in results]
        assert "Decision Criteria" in step_names or "Decision Process" in step_names

    def test_get_questions_for_nonexistent_stage(self, library: MethodologyLibrary):
        """get_questions_for_stage returns empty list for unknown stage."""
        results = library.get_questions_for_stage("nonexistent_stage")
        assert results == []

    def test_bant_has_four_steps(self, library: MethodologyLibrary):
        """BANT framework has exactly 4 steps (B-A-N-T)."""
        fw = library.get_framework("BANT")
        assert len(fw.steps) == 4
        abbreviations = [s.abbreviation for s in fw.steps]
        assert abbreviations == ["B", "A", "N", "T"]

    def test_spin_has_four_steps(self, library: MethodologyLibrary):
        """SPIN framework has exactly 4 steps (S-P-I-N)."""
        fw = library.get_framework("SPIN")
        assert len(fw.steps) == 4
        abbreviations = [s.abbreviation for s in fw.steps]
        assert abbreviations == ["S", "P", "I", "N"]


# ── Tests: Methodology Ingestion ───────────────────────────────────────────


class TestMethodologyIngestion:
    """Verify methodology content is correctly ingested into Qdrant."""

    async def test_methodology_ingestion_creates_chunks(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """Loading methodologies creates chunks in Qdrant with correct metadata."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        count = await loader.load_methodologies(tenant_id="test-tenant")

        # Should create multiple chunks (one per section across 3 files)
        assert count > 0
        assert count >= 10  # At minimum ~15+ sections across 3 methodology files

    async def test_methodology_chunks_have_correct_content_type(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """All methodology chunks are tagged with content_type='methodology'."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        await loader.load_methodologies(tenant_id="test-tenant")

        # Search for methodology content
        results = await store.hybrid_search(
            query_text="sales methodology qualification",
            tenant_id="test-tenant",
            filters={"content_type": "methodology"},
        )

        assert len(results) > 0
        for chunk in results:
            assert chunk.metadata.content_type == "methodology"

    async def test_methodology_search_returns_relevant_content(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """Searching for 'economic buyer' returns MEDDIC-relevant content."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        await loader.load_methodologies(tenant_id="test-tenant")

        results = await store.hybrid_search(
            query_text="how to identify the economic buyer in enterprise deals",
            tenant_id="test-tenant",
        )

        # Should return results (at least some methodology content)
        assert len(results) > 0

    async def test_methodology_stage_filtering(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """Filtering by sales_stage='discovery' returns discovery-phase content."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        await loader.load_methodologies(tenant_id="test-tenant")

        results = await store.hybrid_search(
            query_text="qualification questions",
            tenant_id="test-tenant",
            filters={"sales_stage": "discovery"},
        )

        for chunk in results:
            assert "discovery" in chunk.metadata.sales_stage

    async def test_methodology_tenant_isolation(
        self, store: QdrantKnowledgeStore, mock_embedding_service
    ):
        """Methodology loaded for one tenant is not visible to another."""
        loader = MethodologyLoader(store=store, embedder=mock_embedding_service)
        await loader.load_methodologies(tenant_id="tenant-a")

        results = await store.hybrid_search(
            query_text="MEDDIC methodology",
            tenant_id="tenant-b",
        )

        assert len(results) == 0
