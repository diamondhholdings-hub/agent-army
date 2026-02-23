"""Integration tests for the Solution Architect agent.

Tests cover all 5 capability handlers (map_requirements, generate_architecture,
scope_poc, respond_objection, technical_handoff), error handling (unknown type,
fail-open on LLM error), registration correctness, handoff payload construction,
content type validation, and a full end-to-end map_requirements round-trip.

All external dependencies (LLM service, RAG pipeline) are mocked -- no
external services are required to run these tests.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.app.agents.solution_architect import (
    SolutionArchitectAgent,
    create_sa_registration,
)
from src.app.agents.solution_architect.schemas import (
    ArchitectureNarrative,
    ObjectionResponse,
    POCPlan,
    TechnicalAnswerPayload,
    TechnicalRequirementsDoc,
)


# ── Mock LLM responses ────────────────────────────────────────────────────


def _make_requirements_doc_json() -> str:
    """Return a realistic TechnicalRequirementsDoc JSON string."""
    return json.dumps(
        {
            "requirements": [
                {
                    "category": "integration",
                    "description": "REST API integration with OAuth2 authentication",
                    "priority": "must_have",
                    "source_quote": "We need REST API integration",
                    "confidence": 0.95,
                },
                {
                    "category": "security",
                    "description": "SOC2 compliance and data encryption at rest",
                    "priority": "dealbreaker",
                    "source_quote": "SOC2 compliance",
                    "confidence": 0.90,
                },
                {
                    "category": "performance",
                    "description": "99.9% uptime SLA with <200ms API response time",
                    "priority": "must_have",
                    "source_quote": "99.9% uptime SLA",
                    "confidence": 0.88,
                },
            ],
            "summary": "Prospect requires REST API integration with OAuth2, SOC2 compliance, and high availability (99.9% uptime).",
            "confidence": 0.91,
            "source_transcript_hash": "",
        }
    )


def _make_architecture_narrative_json() -> str:
    """Return a valid ArchitectureNarrative JSON string."""
    return json.dumps(
        {
            "overview": "The proposed architecture integrates Skyvera with the prospect's AWS and PostgreSQL stack via REST APIs and webhook-based event streaming.",
            "integration_points": [
                {
                    "name": "CRM Sync",
                    "integration_type": "rest_api",
                    "description": "Bidirectional sync between Skyvera and prospect CRM via REST API",
                    "complexity": "medium",
                },
                {
                    "name": "Event Notifications",
                    "integration_type": "webhook",
                    "description": "Real-time webhook notifications for billing events",
                    "complexity": "low",
                },
            ],
            "diagram_description": "AWS VPC with Skyvera SaaS connecting via API Gateway to prospect's PostgreSQL RDS instance.",
            "assumptions": ["Prospect uses AWS API Gateway", "PostgreSQL 14+"],
            "prospect_tech_stack": "AWS, PostgreSQL, Node.js",
        }
    )


def _make_poc_plan_json() -> str:
    """Return a valid POCPlan JSON string."""
    return json.dumps(
        {
            "deliverables": [
                {
                    "name": "API Integration Demo",
                    "description": "Working REST API integration with prospect sandbox",
                    "acceptance_criteria": "Successfully create, read, update billing records via API",
                },
                {
                    "name": "Data Migration Script",
                    "description": "Script to migrate sample billing data",
                    "acceptance_criteria": "100% data accuracy on sample dataset",
                },
            ],
            "timeline_weeks": 3,
            "resource_estimate": {
                "developer_days": 10,
                "qa_days": 3,
                "pm_hours": 8,
            },
            "success_criteria": [
                "API integration passing all acceptance criteria",
                "Data migration with zero data loss",
                "Performance within SLA requirements",
            ],
            "risks": ["Prospect sandbox access delays", "API rate limits"],
            "tier": "medium",
        }
    )


def _make_objection_response_json() -> str:
    """Return a valid ObjectionResponse JSON string."""
    return json.dumps(
        {
            "response": "Skyvera's API delivers p99 latency of 45ms, significantly below the industry standard of 200ms. Our global CDN ensures consistent performance across regions.",
            "evidence": [
                {
                    "claim": "p99 latency of 45ms",
                    "source_doc": "performance_benchmarks_2025.md",
                    "confidence": 0.95,
                },
                {
                    "claim": "Global CDN deployment",
                    "source_doc": "architecture_overview.md",
                    "confidence": 0.90,
                },
            ],
            "recommended_followup": "Share the performance benchmark report and offer a latency test in their environment.",
            "competitor_name": "",
        }
    )


def _make_technical_answer_json() -> str:
    """Return a valid TechnicalAnswerPayload JSON string."""
    return json.dumps(
        {
            "answer": "Skyvera handles webhook retries with exponential backoff (1s, 2s, 4s, 8s, 16s) up to 5 attempts. Failed webhooks are queued in a dead-letter queue for manual inspection.",
            "evidence": [
                "webhook_retry_policy.md",
                "infrastructure_overview.md",
            ],
            "architecture_diagram_url": None,
            "related_docs": ["webhook_configuration_guide.md"],
            "confidence": 0.92,
        }
    )


def _make_mock_llm(response_json: str) -> AsyncMock:
    """Create a mock LLM service that returns the given JSON string."""
    mock = AsyncMock()
    mock.completion = AsyncMock(return_value={"content": response_json})
    return mock


def _make_sa_agent(mock_llm: AsyncMock | None = None) -> SolutionArchitectAgent:
    """Create an SA agent with mocked LLM and no RAG pipeline."""
    registration = create_sa_registration()
    if mock_llm is None:
        mock_llm = _make_mock_llm("{}")
    return SolutionArchitectAgent(
        registration=registration,
        llm_service=mock_llm,
        rag_pipeline=None,
    )


# ── Test Cases ─────────────────────────────────────────────────────────────


class TestSAExecuteRouting:
    """Tests for SA agent execute() routing to the correct handler."""

    @pytest.mark.asyncio
    async def test_sa_execute_routes_map_requirements(self):
        """execute() routes 'map_requirements' and returns TechnicalRequirementsDoc-shaped dict."""
        mock_llm = _make_mock_llm(_make_requirements_doc_json())
        agent = _make_sa_agent(mock_llm)

        result = await agent.execute(
            {"type": "map_requirements", "transcript": "We need REST API integration with 99.9% uptime"},
            {"tenant_id": "test"},
        )

        assert "requirements" in result
        assert "summary" in result
        assert "confidence" in result
        assert isinstance(result["requirements"], list)
        assert len(result["requirements"]) > 0
        mock_llm.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_sa_execute_routes_generate_architecture(self):
        """execute() routes 'generate_architecture' and returns ArchitectureNarrative-shaped dict."""
        mock_llm = _make_mock_llm(_make_architecture_narrative_json())
        agent = _make_sa_agent(mock_llm)

        result = await agent.execute(
            {"type": "generate_architecture", "tech_stack": "AWS, PostgreSQL, Node.js"},
            {"tenant_id": "test"},
        )

        assert "overview" in result
        assert "integration_points" in result
        assert isinstance(result["integration_points"], list)
        assert len(result["integration_points"]) > 0
        mock_llm.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_sa_execute_routes_scope_poc(self):
        """execute() routes 'scope_poc' and returns POCPlan-shaped dict."""
        mock_llm = _make_mock_llm(_make_poc_plan_json())
        agent = _make_sa_agent(mock_llm)

        result = await agent.execute(
            {"type": "scope_poc", "requirements": [], "deal_stage": "evaluation"},
            {"tenant_id": "test"},
        )

        assert "deliverables" in result
        assert "timeline_weeks" in result
        assert "resource_estimate" in result
        assert isinstance(result["deliverables"], list)
        assert result["timeline_weeks"] > 0
        mock_llm.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_sa_execute_routes_respond_objection(self):
        """execute() routes 'respond_objection' and returns ObjectionResponse-shaped dict."""
        mock_llm = _make_mock_llm(_make_objection_response_json())
        agent = _make_sa_agent(mock_llm)

        result = await agent.execute(
            {"type": "respond_objection", "objection": "Your API latency is too high"},
            {"tenant_id": "test"},
        )

        assert "response" in result
        assert "evidence" in result
        assert isinstance(result["evidence"], list)
        mock_llm.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_sa_execute_routes_technical_handoff(self):
        """execute() routes 'technical_handoff' and returns TechnicalAnswerPayload-shaped dict."""
        mock_llm = _make_mock_llm(_make_technical_answer_json())
        agent = _make_sa_agent(mock_llm)

        result = await agent.execute(
            {"type": "technical_handoff", "question": "How does Skyvera handle webhook retries?"},
            {"tenant_id": "test"},
        )

        assert "answer" in result
        assert "evidence" in result
        assert isinstance(result["evidence"], list)
        mock_llm.completion.assert_called_once()


class TestSAErrorHandling:
    """Tests for error handling and fail-open behavior."""

    @pytest.mark.asyncio
    async def test_sa_execute_unknown_type_raises_valueerror(self):
        """execute() raises ValueError for unknown task type with supported types listed."""
        agent = _make_sa_agent()

        with pytest.raises(ValueError, match="map_requirements"):
            await agent.execute(
                {"type": "not_a_real_type"},
                {"tenant_id": "test"},
            )

    @pytest.mark.asyncio
    async def test_sa_execute_fail_open_on_llm_error(self):
        """execute() returns a partial/error result instead of raising when LLM fails."""
        mock_llm = AsyncMock()
        mock_llm.completion = AsyncMock(side_effect=Exception("LLM unavailable"))
        agent = _make_sa_agent(mock_llm)

        # Should NOT raise -- fail-open
        result = await agent.execute(
            {"type": "map_requirements", "transcript": "test"},
            {"tenant_id": "test"},
        )

        assert isinstance(result, dict)
        assert "error" in result
        assert "partial" in result
        assert result["partial"] is True
        assert result["confidence"] == "low"


class TestSARegistration:
    """Tests for SA agent registration and capabilities."""

    def test_sa_registration_has_correct_capabilities(self):
        """create_sa_registration() returns correct agent_id, 5 capabilities with expected names."""
        reg = create_sa_registration()

        assert reg.agent_id == "solution_architect"
        assert reg.name == "Solution Architect"
        assert len(reg.capabilities) == 5

        cap_names = {c.name for c in reg.capabilities}
        assert cap_names == {
            "map_requirements",
            "generate_architecture",
            "scope_poc",
            "respond_objection",
            "technical_handoff",
        }


class TestSAHandoffAndContentTypes:
    """Tests for handoff payload construction and content type validation."""

    def test_sa_handoff_payload_construction(self):
        """HandoffPayload validates with solution_architect as target_agent_id."""
        from src.app.handoffs.validators import HandoffPayload

        payload = HandoffPayload(
            source_agent_id="sales_agent",
            target_agent_id="solution_architect",
            handoff_type="technical_question",
            call_chain=["sales_agent"],
            tenant_id="test_tenant",
            data={"question": "How does webhook retry work?"},
        )

        assert payload.source_agent_id == "sales_agent"
        assert payload.target_agent_id == "solution_architect"
        assert payload.handoff_type == "technical_question"
        assert "sales_agent" in payload.call_chain
        assert "solution_architect" not in payload.call_chain

    def test_sa_content_types_valid(self):
        """ChunkMetadata accepts SA content types: competitor_analysis, architecture_template, poc_template."""
        from src.knowledge.models import ChunkMetadata

        for content_type in ("competitor_analysis", "architecture_template", "poc_template"):
            meta = ChunkMetadata(
                product_category="monetization",
                content_type=content_type,
                source_document=f"test_{content_type}.md",
            )
            assert meta.content_type == content_type


class TestSAEndToEnd:
    """End-to-end test proving the full map_requirements chain."""

    @pytest.mark.asyncio
    async def test_sa_map_requirements_end_to_end(self):
        """Full chain: task input -> handler routing -> LLM call -> JSON parse -> Pydantic -> dict.

        This is the key end-to-end test that proves the entire SA agent pipeline
        works correctly with a realistic, multi-requirement TechnicalRequirementsDoc.
        """
        # Build a realistic mock LLM response with 3 requirements
        mock_llm = _make_mock_llm(_make_requirements_doc_json())
        agent = _make_sa_agent(mock_llm)

        transcript = (
            "We need REST API integration with OAuth2 auth, 99.9% uptime SLA, "
            "and SOC2 compliance. Our stack is AWS with PostgreSQL."
        )

        result = await agent.execute(
            {"type": "map_requirements", "transcript": transcript},
            {"tenant_id": "test_tenant"},
        )

        # Result should be a dict (not an exception)
        assert isinstance(result, dict)

        # Requirements list with 3 items
        assert "requirements" in result
        assert isinstance(result["requirements"], list)
        assert len(result["requirements"]) == 3

        # Each requirement has the expected keys
        for req in result["requirements"]:
            assert "category" in req
            assert "description" in req
            assert "priority" in req
            assert req["category"] in (
                "integration",
                "security",
                "performance",
                "compliance",
                "scalability",
            )

        # Summary is a non-empty string
        assert "summary" in result
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

        # Confidence is a float between 0.0 and 1.0
        assert "confidence" in result
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0

        # Verify the LLM was actually called (not bypassed)
        mock_llm.completion.assert_called_once()
        call_kwargs = mock_llm.completion.call_args
        # Verify low temperature was used for JSON output
        assert call_kwargs.kwargs.get("temperature", call_kwargs[1].get("temperature")) == 0.3
