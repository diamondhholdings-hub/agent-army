"""Tests for the Agentic RAG Pipeline.

Tests cover all four components:
1. QueryDecomposer - breaks complex queries into sub-queries
2. MultiSourceRetriever - fetches from multiple knowledge sources
3. ResponseSynthesizer - produces grounded answers with citations
4. AgenticRAGPipeline - LangGraph orchestration with grading and rewriting

All LLM calls are mocked to avoid external API dependencies.
Qdrant operations use mock stores returning deterministic results.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.knowledge.models import ChunkMetadata, ConversationMessage, KnowledgeChunk
from src.knowledge.rag.decomposer import QueryDecomposer, SubQuery
from src.knowledge.rag.pipeline import AgenticRAGPipeline, RAGResponse
from src.knowledge.rag.retriever import MultiSourceRetriever, RetrievedChunk
from src.knowledge.rag.synthesizer import (
    ResponseSynthesizer,
    SourceCitation,
    SynthesizedResponse,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_knowledge_chunk(
    content: str,
    tenant_id: str = "test-tenant",
    product_category: str = "monetization",
    content_type: str = "product",
    source_document: str = "test_doc.md",
    chunk_id: str | None = None,
) -> KnowledgeChunk:
    """Create a KnowledgeChunk for testing."""
    return KnowledgeChunk(
        id=chunk_id or str(uuid.uuid4()),
        tenant_id=tenant_id,
        content=content,
        metadata=ChunkMetadata(
            product_category=product_category,
            buyer_persona=["technical"],
            sales_stage=["discovery"],
            region=["global"],
            content_type=content_type,
            source_document=source_document,
        ),
    )


def _make_conversation_message(
    content: str,
    tenant_id: str = "test-tenant",
    session_id: str = "session-1",
    channel: str = "web",
    role: str = "user",
) -> ConversationMessage:
    """Create a ConversationMessage for testing."""
    return ConversationMessage(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        session_id=session_id,
        channel=channel,
        role=role,
        content=content,
        timestamp=datetime.now(timezone.utc),
    )


# ── Mock LLM ────────────────────────────────────────────────────────────────


class MockLLM:
    """Mock LLM that returns predetermined responses based on context.

    Configured with response_map: dict of trigger -> response.
    If query contains the trigger text, returns the mapped response.
    Falls back to default_response if no trigger matches.
    """

    def __init__(
        self,
        response_map: dict[str, str] | None = None,
        default_response: str = "Mock LLM response",
    ):
        self.response_map = response_map or {}
        self.default_response = default_response
        self.call_history: list[str] = []

    async def ainvoke(self, prompt: str, **kwargs: Any) -> str:
        """Simulate async LLM invocation."""
        self.call_history.append(prompt)
        for trigger, response in self.response_map.items():
            if trigger.lower() in prompt.lower():
                return response
        return self.default_response


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_llm() -> MockLLM:
    """Create a default mock LLM."""
    return MockLLM()


@pytest.fixture
def decomposer_llm() -> MockLLM:
    """Create a dedicated LLM for the decomposer."""
    return MockLLM(default_response='[{"query": "fallback query", "source_type": "product", "filters": {}}]')


@pytest.fixture
def synthesizer_llm() -> MockLLM:
    """Create a dedicated LLM for the synthesizer."""
    return MockLLM(default_response="Based on available information, here is the answer [1].")


@pytest.fixture
def grading_llm() -> MockLLM:
    """Create a dedicated LLM for document grading (defaults to 'yes')."""
    return MockLLM(default_response="yes")


@pytest.fixture
def mock_knowledge_store() -> MagicMock:
    """Create a mock QdrantKnowledgeStore."""
    store = MagicMock()

    # Default: return some chunks from hybrid_search
    product_chunks = [
        _make_knowledge_chunk(
            content="The Monetization Platform supports subscription management and usage-based pricing.",
            product_category="monetization",
            content_type="product",
            source_document="monetization_features.md",
        ),
        _make_knowledge_chunk(
            content="Monetization Platform pricing: Starter $500/mo, Growth $2000/mo, Enterprise custom.",
            product_category="monetization",
            content_type="pricing",
            source_document="monetization_pricing.md",
        ),
    ]

    methodology_chunks = [
        _make_knowledge_chunk(
            content="MEDDIC framework: Metrics, Economic Buyer, Decision Criteria, Decision Process, Identify Pain, Champion.",
            content_type="methodology",
            source_document="meddic_framework.md",
        ),
    ]

    regional_chunks = [
        _make_knowledge_chunk(
            content="APAC sales: Build consensus among stakeholders. Pricing typically 10% below Americas.",
            content_type="regional",
            source_document="apac_playbook.md",
        ),
    ]

    async def mock_hybrid_search(
        query_text: str,
        tenant_id: str,
        filters: dict | None = None,
        top_k: int | None = None,
    ) -> list[KnowledgeChunk]:
        """Return deterministic results based on filters."""
        if filters and filters.get("content_type") == "methodology":
            return methodology_chunks
        if filters and filters.get("content_type") == "regional":
            return regional_chunks
        if filters and filters.get("content_type") == "positioning":
            return product_chunks[:1]
        if filters and filters.get("content_type") == "pricing":
            return product_chunks[1:]
        return product_chunks

    store.hybrid_search = AsyncMock(side_effect=mock_hybrid_search)
    return store


@pytest.fixture
def mock_conversation_store() -> MagicMock:
    """Create a mock ConversationStore."""
    store = MagicMock()

    conversation_results = [
        _make_conversation_message(
            content="We discussed pricing for the enterprise tier last week.",
            session_id="session-prev",
        ),
    ]

    async def mock_search_conversations(
        tenant_id: str,
        query: str,
        top_k: int = 10,
        **kwargs: Any,
    ) -> list[ConversationMessage]:
        return conversation_results

    store.search_conversations = AsyncMock(side_effect=mock_search_conversations)
    return store


@pytest.fixture
def decomposer(decomposer_llm: MockLLM) -> QueryDecomposer:
    """Create a QueryDecomposer with dedicated mock LLM."""
    decomposer_llm.response_map = {
        "monetization platform pricing": '[{"query": "Monetization Platform pricing", "source_type": "product", "filters": {"content_type": "pricing"}}]',
        "position the monetization": '[{"query": "Monetization Platform key features and differentiators", "source_type": "product", "filters": {"content_type": "product"}}, {"query": "Competitive positioning", "source_type": "product", "filters": {"content_type": "positioning"}}, {"query": "APAC sales approach for technical buyers", "source_type": "regional", "filters": {"content_type": "regional"}}, {"query": "CTO engagement strategy", "source_type": "methodology", "filters": {"content_type": "methodology"}}]',
    }
    return QueryDecomposer(llm=decomposer_llm)


@pytest.fixture
def retriever(
    mock_knowledge_store: MagicMock,
    mock_conversation_store: MagicMock,
) -> MultiSourceRetriever:
    """Create a MultiSourceRetriever with mock stores."""
    return MultiSourceRetriever(
        knowledge_store=mock_knowledge_store,
        conversation_store=mock_conversation_store,
        top_k=7,
    )


@pytest.fixture
def synthesizer(synthesizer_llm: MockLLM) -> ResponseSynthesizer:
    """Create a ResponseSynthesizer with dedicated mock LLM."""
    synthesizer_llm.response_map = {
        "monetization platform": "The Monetization Platform offers subscription management and usage-based pricing [1]. Pricing starts at $500/mo for Starter tier [2].",
    }
    return ResponseSynthesizer(llm=synthesizer_llm)


@pytest.fixture
def pipeline(
    decomposer: QueryDecomposer,
    retriever: MultiSourceRetriever,
    synthesizer: ResponseSynthesizer,
    grading_llm: MockLLM,
) -> AgenticRAGPipeline:
    """Create a full AgenticRAGPipeline with mock dependencies."""
    return AgenticRAGPipeline(
        decomposer=decomposer,
        retriever=retriever,
        synthesizer=synthesizer,
        grading_llm=grading_llm,
        max_iterations=2,
    )


# ── Tests: QueryDecomposer ───────────────────────────────────────────────────


class TestQueryDecomposer:
    """Tests for query decomposition into sub-queries."""

    async def test_simple_query_decomposition(self, decomposer: QueryDecomposer):
        """Simple single-intent query produces 1 sub-query."""
        sub_queries = await decomposer.decompose("What is Monetization Platform pricing?")

        assert len(sub_queries) == 1
        assert isinstance(sub_queries[0], SubQuery)
        assert sub_queries[0].source_type == "product"
        assert "pricing" in sub_queries[0].query.lower()

    async def test_complex_query_decomposition(self, decomposer: QueryDecomposer):
        """Multi-faceted query produces multiple sub-queries with different source_types."""
        sub_queries = await decomposer.decompose(
            "How should I position the Monetization Platform vs Competitor A for a CTO in APAC?"
        )

        assert len(sub_queries) >= 3
        source_types = {sq.source_type for sq in sub_queries}
        # Should target multiple knowledge sources
        assert len(source_types) >= 2
        # Should include product and at least one of regional/methodology
        assert "product" in source_types

    async def test_sub_query_has_filters(self, decomposer: QueryDecomposer):
        """Sub-queries include filters for targeted retrieval."""
        sub_queries = await decomposer.decompose("What is Monetization Platform pricing?")

        assert len(sub_queries) >= 1
        first = sub_queries[0]
        assert isinstance(first.filters, dict)
        # Should have at least one filter
        assert len(first.filters) > 0

    async def test_decomposer_handles_empty_query(self, decomposer: QueryDecomposer):
        """Empty query returns a single pass-through sub-query."""
        sub_queries = await decomposer.decompose("")

        assert len(sub_queries) >= 1
        assert isinstance(sub_queries[0], SubQuery)

    async def test_sub_query_source_types_are_valid(self, decomposer: QueryDecomposer):
        """All sub-query source_types are from the known set."""
        valid_types = {"product", "methodology", "regional", "conversation"}

        sub_queries = await decomposer.decompose("What is Monetization Platform pricing?")

        for sq in sub_queries:
            assert sq.source_type in valid_types


# ── Tests: MultiSourceRetriever ──────────────────────────────────────────────


class TestMultiSourceRetriever:
    """Tests for multi-source retrieval and merging."""

    async def test_multi_source_retrieval(self, retriever: MultiSourceRetriever):
        """Given sub-queries for product + methodology, retriever returns merged results."""
        sub_queries = [
            SubQuery(
                query="Monetization Platform features",
                source_type="product",
                filters={"content_type": "product"},
            ),
            SubQuery(
                query="MEDDIC qualification framework",
                source_type="methodology",
                filters={"content_type": "methodology"},
            ),
        ]

        results = await retriever.retrieve(
            sub_queries=sub_queries,
            tenant_id="test-tenant",
        )

        assert len(results) > 0
        assert all(isinstance(r, RetrievedChunk) for r in results)
        # Results should come from multiple sources
        source_types = {r.source_type for r in results}
        assert len(source_types) >= 2

    async def test_retrieval_with_conversation_source(
        self, retriever: MultiSourceRetriever
    ):
        """Conversation sub-query fetches from conversation store."""
        sub_queries = [
            SubQuery(
                query="previous pricing discussions",
                source_type="conversation",
                filters={},
            ),
        ]

        results = await retriever.retrieve(
            sub_queries=sub_queries,
            tenant_id="test-tenant",
        )

        assert len(results) > 0
        # At least one result should be from conversation source
        conv_results = [r for r in results if r.source_type == "conversation"]
        assert len(conv_results) > 0

    async def test_retrieval_deduplicates_results(self, retriever: MultiSourceRetriever):
        """Duplicate chunks from overlapping sub-queries are deduplicated."""
        # Two sub-queries that would return the same product chunks
        sub_queries = [
            SubQuery(
                query="Monetization Platform features",
                source_type="product",
                filters={"content_type": "product"},
            ),
            SubQuery(
                query="Monetization Platform capabilities",
                source_type="product",
                filters={"content_type": "product"},
            ),
        ]

        results = await retriever.retrieve(
            sub_queries=sub_queries,
            tenant_id="test-tenant",
        )

        # Check no duplicate chunk IDs
        chunk_ids = [r.chunk_id for r in results]
        assert len(chunk_ids) == len(set(chunk_ids))

    async def test_retrieval_respects_top_k(self, retriever: MultiSourceRetriever):
        """Results are limited to top_k."""
        sub_queries = [
            SubQuery(
                query="Monetization Platform",
                source_type="product",
                filters={},
            ),
        ]

        results = await retriever.retrieve(
            sub_queries=sub_queries,
            tenant_id="test-tenant",
        )

        assert len(results) <= retriever.top_k

    async def test_retrieval_includes_relevance_scores(
        self, retriever: MultiSourceRetriever
    ):
        """Each retrieved chunk has a relevance score."""
        sub_queries = [
            SubQuery(
                query="Monetization Platform pricing",
                source_type="product",
                filters={"content_type": "pricing"},
            ),
        ]

        results = await retriever.retrieve(
            sub_queries=sub_queries,
            tenant_id="test-tenant",
        )

        assert len(results) > 0
        for r in results:
            assert isinstance(r.relevance_score, float)
            assert 0.0 <= r.relevance_score <= 1.0


# ── Tests: ResponseSynthesizer ───────────────────────────────────────────────


class TestResponseSynthesizer:
    """Tests for answer synthesis from retrieved chunks."""

    async def test_synthesis_produces_answer(self, synthesizer: ResponseSynthesizer):
        """Synthesizer produces a non-empty answer."""
        chunks = [
            RetrievedChunk(
                chunk_id="chunk-1",
                content="The Monetization Platform supports subscription management.",
                relevance_score=0.9,
                source_type="product",
                source_document="monetization_features.md",
                sub_query="Monetization Platform features",
            ),
        ]

        result = await synthesizer.synthesize(
            query="What does the Monetization Platform do?",
            chunks=chunks,
        )

        assert isinstance(result, SynthesizedResponse)
        assert len(result.answer) > 0

    async def test_synthesis_cites_sources(self, synthesizer: ResponseSynthesizer):
        """Synthesized answer includes source citations."""
        chunks = [
            RetrievedChunk(
                chunk_id="chunk-1",
                content="The Monetization Platform supports subscription management.",
                relevance_score=0.9,
                source_type="product",
                source_document="monetization_features.md",
                sub_query="Monetization Platform features",
            ),
            RetrievedChunk(
                chunk_id="chunk-2",
                content="Monetization Platform pricing: Starter $500/mo.",
                relevance_score=0.85,
                source_type="product",
                source_document="monetization_pricing.md",
                sub_query="Monetization Platform pricing",
            ),
        ]

        result = await synthesizer.synthesize(
            query="Tell me about the Monetization Platform",
            chunks=chunks,
        )

        assert isinstance(result, SynthesizedResponse)
        assert len(result.sources) > 0
        assert all(isinstance(s, SourceCitation) for s in result.sources)

    async def test_synthesis_includes_confidence(
        self, synthesizer: ResponseSynthesizer
    ):
        """Synthesized response includes a confidence score."""
        chunks = [
            RetrievedChunk(
                chunk_id="chunk-1",
                content="Some relevant content",
                relevance_score=0.9,
                source_type="product",
                source_document="doc.md",
                sub_query="query",
            ),
        ]

        result = await synthesizer.synthesize(
            query="What is this about?",
            chunks=chunks,
        )

        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0

    async def test_synthesis_with_no_chunks(self, synthesizer: ResponseSynthesizer):
        """Synthesizer handles empty chunk list gracefully."""
        result = await synthesizer.synthesize(
            query="Anything?",
            chunks=[],
        )

        assert isinstance(result, SynthesizedResponse)
        assert len(result.answer) > 0  # Should produce a "no info" answer
        assert result.confidence == 0.0


# ── Tests: AgenticRAGPipeline ────────────────────────────────────────────────


class TestAgenticRAGPipeline:
    """Tests for the full LangGraph pipeline orchestration."""

    async def test_full_pipeline_simple(self, pipeline: AgenticRAGPipeline):
        """End-to-end simple query produces a valid RAGResponse."""
        response = await pipeline.run(
            query="What is Monetization Platform pricing?",
            tenant_id="test-tenant",
        )

        assert isinstance(response, RAGResponse)
        assert len(response.answer) > 0
        assert len(response.sub_queries) >= 1
        assert response.iterations >= 1

    async def test_full_pipeline_complex(self, pipeline: AgenticRAGPipeline):
        """End-to-end complex multi-source query works correctly."""
        response = await pipeline.run(
            query="How should I position the Monetization Platform vs Competitor A for a CTO in APAC?",
            tenant_id="test-tenant",
        )

        assert isinstance(response, RAGResponse)
        assert len(response.answer) > 0
        assert len(response.sub_queries) >= 2

    async def test_pipeline_with_conversation_context(
        self, pipeline: AgenticRAGPipeline
    ):
        """Pipeline includes conversation history in retrieval."""
        context = [
            _make_conversation_message(
                content="We discussed enterprise pricing last call.",
            ),
        ]

        response = await pipeline.run(
            query="What is Monetization Platform pricing?",
            tenant_id="test-tenant",
            conversation_context=context,
        )

        assert isinstance(response, RAGResponse)
        assert len(response.answer) > 0

    async def test_document_grading_passes(self, pipeline: AgenticRAGPipeline):
        """When all chunks are relevant, pipeline proceeds to synthesis without rewrite."""
        # Configure grading LLM to mark everything as relevant
        pipeline._grading_llm.response_map = {
            "relevant": "yes",
        }
        pipeline._grading_llm.default_response = "yes"

        response = await pipeline.run(
            query="What is Monetization Platform pricing?",
            tenant_id="test-tenant",
        )

        assert isinstance(response, RAGResponse)
        assert response.iterations == 1  # No rewrite needed

    async def test_document_grading_triggers_rewrite(
        self, pipeline: AgenticRAGPipeline
    ):
        """When >50% chunks are irrelevant, pipeline rewrites query and retries."""
        # Configure grading LLM to mark chunks as irrelevant first, then relevant
        call_count = 0

        async def grade_with_flip(prompt: str, **kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            # First round: mostly irrelevant to trigger rewrite
            if call_count <= 3:
                return "no"
            # Second round: relevant
            return "yes"

        pipeline._grading_llm.ainvoke = grade_with_flip

        response = await pipeline.run(
            query="What is Monetization Platform pricing?",
            tenant_id="test-tenant",
        )

        assert isinstance(response, RAGResponse)
        assert response.iterations >= 2  # At least one rewrite happened

    async def test_max_iterations_respected(self, pipeline: AgenticRAGPipeline):
        """Rewrite happens at most max_iterations times, then proceeds anyway."""
        # Configure grading to always say irrelevant
        pipeline._grading_llm.default_response = "no"
        pipeline._grading_llm.response_map = {}

        response = await pipeline.run(
            query="What is Monetization Platform pricing?",
            tenant_id="test-tenant",
        )

        assert isinstance(response, RAGResponse)
        # Should not exceed max_iterations (2)
        assert response.iterations <= pipeline._max_iterations + 1
        # Should still produce an answer (uses whatever chunks are available)
        assert len(response.answer) > 0

    async def test_tenant_isolation(self, pipeline: AgenticRAGPipeline):
        """Results only come from the querying tenant."""
        response = await pipeline.run(
            query="What is Monetization Platform pricing?",
            tenant_id="test-tenant",
        )

        assert isinstance(response, RAGResponse)
        # Verify the retriever was called with correct tenant_id
        retriever = pipeline._retriever
        store = retriever._knowledge_store
        for call in store.hybrid_search.call_args_list:
            _, kwargs = call
            assert kwargs.get("tenant_id") == "test-tenant"

    async def test_rag_response_has_sources(self, pipeline: AgenticRAGPipeline):
        """RAGResponse includes source citations from synthesis."""
        response = await pipeline.run(
            query="What is Monetization Platform pricing?",
            tenant_id="test-tenant",
        )

        assert isinstance(response, RAGResponse)
        assert isinstance(response.sources, list)

    async def test_rag_response_has_confidence(self, pipeline: AgenticRAGPipeline):
        """RAGResponse includes a confidence score."""
        response = await pipeline.run(
            query="What is Monetization Platform pricing?",
            tenant_id="test-tenant",
        )

        assert isinstance(response, RAGResponse)
        assert isinstance(response.confidence, float)
        assert 0.0 <= response.confidence <= 1.0
