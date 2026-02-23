"""Tests for SA Knowledge Base wiring: filter path, base_filters, and prompt coverage.

Covers:
1. QdrantKnowledgeStore.hybrid_search uses MatchAny for list filters, MatchValue for scalars
2. SolutionArchitectAgent._query_rag forwards content_types as base_filters to pipeline.run()
3. Each SA handler passes the correct content_types list to _query_rag
4. AgenticRAGPipeline.run() merges base_filters into sub_queries (LLM filters win on collision)
5. DECOMPOSITION_PROMPT includes all SA-specific content_types
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.app.agents.solution_architect import SolutionArchitectAgent, create_sa_registration
from src.knowledge.qdrant_client import QdrantKnowledgeStore
from src.knowledge.rag.decomposer import DECOMPOSITION_PROMPT, SubQuery
from src.knowledge.rag.pipeline import AgenticRAGPipeline, RAGState


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_store(tmp_path) -> QdrantKnowledgeStore:
    """Create a QdrantKnowledgeStore backed by a local tmp Qdrant instance."""
    from src.knowledge.config import KnowledgeBaseConfig
    from src.knowledge.embeddings import EmbeddingService

    config = KnowledgeBaseConfig(qdrant_path=str(tmp_path / "qdrant"))
    embedder = MagicMock(spec=EmbeddingService)
    return QdrantKnowledgeStore(config, embedder)


def _make_sa_agent(rag_pipeline=None) -> SolutionArchitectAgent:
    """Create a SolutionArchitectAgent with mock LLM and optional RAG pipeline."""
    registration = create_sa_registration()
    llm_service = MagicMock()
    return SolutionArchitectAgent(
        registration=registration,
        llm_service=llm_service,
        rag_pipeline=rag_pipeline,
    )


def _make_llm_json_response(data: dict) -> dict[str, str]:
    """Return a mock LLM completion response wrapping JSON data."""
    return {"content": json.dumps(data)}


# ── Test 1: MatchAny for list values, MatchValue for scalars ─────────────────


@pytest.mark.asyncio
async def test_hybrid_search_filter_accepts_list_values(tmp_path):
    """hybrid_search should use MatchAny for list filter values and MatchValue for scalars."""
    from qdrant_client.models import MatchAny, MatchValue

    store = _make_store(tmp_path)

    # Mock embed_text to return deterministic vectors
    store._embeddings.embed_text = AsyncMock(
        return_value=([0.1] * 1536, {"indices": [1, 2], "values": [0.5, 0.5]})
    )

    # Mock query_points to avoid actual Qdrant call and capture the filter arg
    mock_query_points = MagicMock(return_value=MagicMock(points=[]))
    store._client.query_points = mock_query_points

    await store.hybrid_search(
        query_text="test query",
        tenant_id="t1",
        filters={"content_type": ["product", "methodology"], "region": "apac"},
    )

    assert mock_query_points.called, "query_points should have been called"
    call_kwargs = mock_query_points.call_args.kwargs
    prefetches = call_kwargs["prefetch"]
    assert prefetches, "prefetch list should not be empty"

    # Extract must conditions from the first prefetch's filter
    query_filter = prefetches[0].filter
    must_conditions = query_filter.must

    # Build lookup: field -> match object
    field_to_match = {cond.key: cond.match for cond in must_conditions}

    # List value -> MatchAny
    assert "content_type" in field_to_match, "content_type condition missing"
    assert isinstance(
        field_to_match["content_type"], MatchAny
    ), f"expected MatchAny for list, got {type(field_to_match['content_type'])}"
    assert set(field_to_match["content_type"].any) == {"product", "methodology"}

    # Scalar value -> MatchValue
    assert "region" in field_to_match, "region condition missing"
    assert isinstance(
        field_to_match["region"], MatchValue
    ), f"expected MatchValue for scalar, got {type(field_to_match['region'])}"
    assert field_to_match["region"].value == "apac"


# ── Test 2: content_types forwarded as base_filters ──────────────────────────


@pytest.mark.asyncio
async def test_query_rag_passes_content_types_as_base_filters():
    """_query_rag should forward content_types as base_filters={'content_type': ...}."""
    mock_pipeline = MagicMock()
    mock_response = MagicMock()
    mock_response.answer = "test answer"
    mock_pipeline.run = AsyncMock(return_value=mock_response)

    agent = _make_sa_agent(rag_pipeline=mock_pipeline)

    result = await agent._query_rag(
        query="what are the integration options",
        tenant_id="t1",
        content_types=["product", "methodology"],
    )

    assert result == "test answer"
    mock_pipeline.run.assert_called_once_with(
        query="what are the integration options",
        tenant_id="t1",
        base_filters={"content_type": ["product", "methodology"]},
    )


@pytest.mark.asyncio
async def test_query_rag_passes_no_base_filters_when_content_types_is_none():
    """_query_rag should pass base_filters=None when content_types is not provided."""
    mock_pipeline = MagicMock()
    mock_response = MagicMock()
    mock_response.answer = "answer"
    mock_pipeline.run = AsyncMock(return_value=mock_response)

    agent = _make_sa_agent(rag_pipeline=mock_pipeline)
    await agent._query_rag(query="any query", tenant_id="t1")

    mock_pipeline.run.assert_called_once_with(
        query="any query",
        tenant_id="t1",
        base_filters=None,
    )


# ── Test 3: each handler uses correct content_types ──────────────────────────


@pytest.mark.asyncio
async def test_each_sa_handler_uses_correct_content_types():
    """Each handler should call _query_rag with the expected content_types."""
    mock_pipeline = MagicMock()
    mock_response = MagicMock()
    mock_response.answer = ""
    mock_pipeline.run = AsyncMock(return_value=mock_response)

    agent = _make_sa_agent(rag_pipeline=mock_pipeline)

    # Minimal valid LLM response stubs (fail-open is fine — we only care about
    # the content_types passed to _query_rag, not the parsed LLM output)
    agent._llm_service.completion = AsyncMock(
        return_value={"content": json.dumps({"error": "stub"})}
    )

    expected: dict[str, list[str] | None] = {
        "map_requirements": ["product", "methodology"],
        "generate_architecture": ["architecture_template", "product"],
        "scope_poc": ["poc_template"],
        "respond_objection": ["competitor_analysis", "positioning"],
        "technical_handoff": ["product", "architecture_template", "methodology"],
    }

    tasks: dict[str, dict[str, Any]] = {
        "map_requirements": {"type": "map_requirements", "transcript": "call transcript", "deal_context": {}},
        "generate_architecture": {"type": "generate_architecture", "tech_stack": "Python/Django", "requirements_json": "{}"},
        "scope_poc": {"type": "scope_poc", "requirements_json": "{}"},
        "respond_objection": {"type": "respond_objection", "objection": "too expensive"},
        "technical_handoff": {"type": "technical_handoff", "question": "does it scale?"},
    }
    context = {"tenant_id": "t1"}

    for handler_name, task in tasks.items():
        mock_pipeline.run.reset_mock()

        # Call the handler (may raise due to stub LLM response — that's fine)
        try:
            await agent.execute(task, context)
        except Exception:
            pass

        assert mock_pipeline.run.called, f"{handler_name}: pipeline.run not called"
        actual_base_filters = mock_pipeline.run.call_args.kwargs.get("base_filters")
        expected_types = expected[handler_name]
        assert actual_base_filters == {"content_type": expected_types}, (
            f"{handler_name}: expected base_filters={{'content_type': {expected_types}}}, "
            f"got {actual_base_filters}"
        )


# ── Test 4: pipeline merges base_filters into sub_queries ────────────────────


@pytest.mark.asyncio
async def test_pipeline_merges_base_filters_into_subqueries():
    """pipeline.run() should merge base_filters into every sub_query after decomposition.

    LLM-generated filters must win on key collision.
    """
    # LLM sub_queries: one has its own content_type (should win), one has none
    llm_sub_queries = [
        SubQuery(query="q1", source_type="product", filters={"content_type": "methodology"}),
        SubQuery(query="q2", source_type="product", filters={}),
    ]

    mock_decomposer = MagicMock()
    mock_decomposer.decompose = AsyncMock(return_value=llm_sub_queries)

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[])

    mock_synthesizer = MagicMock()
    mock_synthesizer.synthesize = AsyncMock(
        return_value=MagicMock(answer="ok", sources=[], confidence=1.0)
    )

    mock_grading_llm = MagicMock()
    mock_grading_llm.ainvoke = AsyncMock(return_value="yes")

    pipeline = AgenticRAGPipeline(
        decomposer=mock_decomposer,
        retriever=mock_retriever,
        synthesizer=mock_synthesizer,
        grading_llm=mock_grading_llm,
    )

    base_filters = {"content_type": ["product", "architecture_template"], "region": "global"}

    await pipeline.run(query="test", tenant_id="t1", base_filters=base_filters)

    retrieve_call = mock_retriever.retrieve.call_args
    merged_sub_queries: list[SubQuery] = retrieve_call.kwargs["sub_queries"]

    # q1 had its own content_type="methodology" -> LLM value should win
    assert merged_sub_queries[0].filters["content_type"] == "methodology", (
        "LLM-generated content_type should override base_filters on collision"
    )
    # region from base_filters should be present (no collision)
    assert merged_sub_queries[0].filters["region"] == "global"

    # q2 had no filters -> should get all base_filters
    assert merged_sub_queries[1].filters["content_type"] == ["product", "architecture_template"]
    assert merged_sub_queries[1].filters["region"] == "global"


# ── Test 5: DECOMPOSITION_PROMPT includes all SA content_types ───────────────


def test_decomposer_prompt_includes_all_sa_content_types():
    """DECOMPOSITION_PROMPT must list all SA-specific content_types."""
    required_types = ["competitor_analysis", "architecture_template", "poc_template"]
    for ct in required_types:
        assert ct in DECOMPOSITION_PROMPT, (
            f"DECOMPOSITION_PROMPT is missing SA content_type: {ct!r}"
        )
