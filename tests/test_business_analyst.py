"""Integration tests for the Business Analyst agent.

Tests cover all 4 capability handlers (requirements_extraction, gap_analysis,
user_story_generation, process_documentation), error handling (unknown type,
fail-open on LLM error), registration correctness, handoff payload construction,
low-confidence flagging, Fibonacci story point validation, and Notion block
renderers.

All external dependencies (LLM service, RAG pipeline) are mocked -- no
external services are required to run these tests.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.app.agents.business_analyst import (
    BusinessAnalystAgent,
    create_ba_registration,
)
from src.app.agents.business_analyst.schemas import (
    BAHandoffRequest,
    BAHandoffResponse,
    BAResult,
    CapabilityGap,
    ExtractedRequirement,
    GapAnalysisResult,
    ProcessDocumentation,
    RequirementContradiction,
    UserStory,
)
from src.app.agents.business_analyst.notion_ba import (
    render_requirements_to_notion_blocks,
    render_gap_analysis_to_notion_blocks,
    render_user_stories_to_notion_blocks,
    render_process_doc_to_notion_blocks,
)


# -- Mock LLM response factories --------------------------------------------------


def _make_requirements_json() -> str:
    """Return a JSON array of 3 ExtractedRequirement objects.

    One has extraction_confidence=0.4 to test low-confidence flagging.
    """
    return json.dumps(
        [
            {
                "requirement_id": "REQ-001",
                "description": "System must integrate with Salesforce CRM via REST API",
                "category": "functional",
                "moscow_priority": "must_have",
                "stakeholder_domain": "sales",
                "priority_score": "high",
                "extraction_confidence": 0.92,
                "source_quote": "We need Salesforce integration",
            },
            {
                "requirement_id": "REQ-002",
                "description": "Response time under 200ms for all API calls",
                "category": "non_functional",
                "moscow_priority": "should_have",
                "stakeholder_domain": "tech",
                "priority_score": "med",
                "extraction_confidence": 0.85,
                "source_quote": "API response should be fast",
            },
            {
                "requirement_id": "REQ-003",
                "description": "Data must be retained for 7 years per compliance",
                "category": "constraint",
                "moscow_priority": "must_have",
                "stakeholder_domain": "ops",
                "priority_score": "high",
                "extraction_confidence": 0.4,
                "source_quote": "I think we need 7 years retention",
            },
        ]
    )


def _make_gap_analysis_json() -> str:
    """Return a GapAnalysisResult JSON with 2 requirements, 1 gap, 1 contradiction."""
    return json.dumps(
        {
            "requirements": [
                {
                    "requirement_id": "REQ-001",
                    "description": "Salesforce CRM integration",
                    "category": "functional",
                    "moscow_priority": "must_have",
                    "stakeholder_domain": "sales",
                    "priority_score": "high",
                    "extraction_confidence": 0.9,
                },
                {
                    "requirement_id": "REQ-002",
                    "description": "Response time under 200ms",
                    "category": "non_functional",
                    "moscow_priority": "should_have",
                    "stakeholder_domain": "tech",
                    "priority_score": "med",
                    "extraction_confidence": 0.85,
                },
            ],
            "gaps": [
                {
                    "requirement_id": "REQ-001",
                    "gap_description": "No native Salesforce connector exists",
                    "severity": "major",
                    "recommended_action": "build_it",
                    "workaround": "Use Zapier as interim bridge",
                    "requires_sa_escalation": False,
                },
            ],
            "contradictions": [
                {
                    "requirement_ids": ["REQ-001", "REQ-002"],
                    "conflict_description": "Real-time sync conflicts with sub-200ms latency goal",
                    "resolution_suggestion": "Use async event-driven sync instead of synchronous API",
                    "severity": "significant",
                },
            ],
            "coverage_percentage": 75.0,
            "recommended_next_action": "Build Salesforce connector and validate latency targets",
            "requires_sa_escalation": False,
        }
    )


def _make_user_stories_json() -> str:
    """Return a JSON array of 2 UserStory objects, one with is_low_confidence=True."""
    return json.dumps(
        [
            {
                "story_id": "US-001",
                "as_a": "sales manager",
                "i_want": "automatic CRM sync with Salesforce",
                "so_that": "I can track deals without manual data entry",
                "acceptance_criteria": [
                    "New deals sync within 5 minutes",
                    "Contact changes bidirectionally synced",
                ],
                "story_points": 8,
                "priority": "must_have",
                "epic_theme": "CRM Integration",
                "stakeholder_domain": "sales",
                "is_low_confidence": False,
                "source_requirement_ids": ["REQ-001"],
            },
            {
                "story_id": "US-002",
                "as_a": "compliance officer",
                "i_want": "7-year data retention policy enforcement",
                "so_that": "the company meets regulatory audit requirements",
                "acceptance_criteria": [
                    "Data older than 7 years archived, not deleted",
                ],
                "story_points": 5,
                "priority": "must_have",
                "epic_theme": "Compliance",
                "stakeholder_domain": "ops",
                "is_low_confidence": True,
                "source_requirement_ids": ["REQ-003"],
            },
        ]
    )


def _make_process_doc_json() -> str:
    """Return a ProcessDocumentation JSON with all fields populated."""
    return json.dumps(
        {
            "process_name": "Lead Qualification Workflow",
            "current_state": "Sales reps manually qualify leads by reviewing emails and CRM notes.",
            "future_state": "AI agent pre-qualifies leads using conversation analysis and scoring.",
            "delta": "Eliminates manual review; AI scores leads on first contact within 30 seconds.",
            "stakeholders": ["Sales Director", "VP Engineering", "Head of Ops"],
            "assumptions": [
                "Historical email data is available for training",
                "CRM has API access enabled",
            ],
        }
    )


def _make_mock_llm(response_json: str) -> AsyncMock:
    """Create a mock LLM service that returns the given JSON string."""
    mock = AsyncMock()
    mock.completion = AsyncMock(return_value={"content": response_json})
    return mock


# -- Fixtures ------------------------------------------------------------------


@pytest.fixture
def ba_agent():
    """Create a BA agent with mocked LLM and RAG services."""
    registration = create_ba_registration()
    mock_llm = AsyncMock()
    mock_rag = AsyncMock()
    agent = BusinessAnalystAgent(
        registration=registration,
        llm_service=mock_llm,
        rag_pipeline=mock_rag,
    )
    return agent, mock_llm, mock_rag


# -- Tests: Registration -------------------------------------------------------


class TestBARegistration:
    """Tests for BA agent registration and capabilities."""

    def test_registration_correctness(self):
        """create_ba_registration() returns agent_id='business_analyst', 4 capabilities."""
        reg = create_ba_registration()

        assert reg.agent_id == "business_analyst"
        assert reg.name == "Business Analyst"
        assert len(reg.capabilities) == 4

        cap_names = {c.name for c in reg.capabilities}
        assert cap_names == {
            "extract_requirements",
            "analyze_gaps",
            "generate_user_stories",
            "document_process",
        }


# -- Tests: Requirements Extraction Handler ------------------------------------


class TestBARequirementsExtraction:
    """Tests for requirements_extraction handler."""

    @pytest.mark.asyncio
    async def test_requirements_extraction_handler(self, ba_agent):
        """execute() routes 'requirements_extraction' and returns requirements list."""
        agent, mock_llm, _mock_rag = ba_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_requirements_json()}
        )

        result = await agent.execute(
            {
                "type": "requirements_extraction",
                "conversation_text": "We need Salesforce integration and fast API response times.",
            },
            {"tenant_id": "test"},
        )

        assert "requirements" in result
        assert isinstance(result["requirements"], list)
        assert len(result["requirements"]) == 3
        assert "error" not in result or result.get("error") is None
        mock_llm.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_requirements_extraction_low_confidence_flagging(self, ba_agent):
        """Requirement with confidence=0.4 has is_low_confidence=True."""
        agent, mock_llm, _mock_rag = ba_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_requirements_json()}
        )

        result = await agent.execute(
            {
                "type": "requirements_extraction",
                "conversation_text": "We need various features.",
            },
            {"tenant_id": "test"},
        )

        requirements = result["requirements"]
        # REQ-003 has extraction_confidence=0.4 < 0.6 threshold
        low_conf = [r for r in requirements if r["requirement_id"] == "REQ-003"]
        assert len(low_conf) == 1
        assert low_conf[0]["is_low_confidence"] is True

        # REQ-001 has extraction_confidence=0.92 >= 0.6
        high_conf = [r for r in requirements if r["requirement_id"] == "REQ-001"]
        assert len(high_conf) == 1
        assert high_conf[0]["is_low_confidence"] is False


# -- Tests: Gap Analysis Handler -----------------------------------------------


class TestBAGapAnalysis:
    """Tests for gap_analysis handler."""

    @pytest.mark.asyncio
    async def test_gap_analysis_handler(self, ba_agent):
        """execute() routes 'gap_analysis' and returns gap_analysis with gaps and contradictions."""
        agent, mock_llm, _mock_rag = ba_agent
        # First call is for RAG (which returns empty), LLM returns gap analysis
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_gap_analysis_json()}
        )

        result = await agent.execute(
            {
                "type": "gap_analysis",
                "conversation_text": "We need Salesforce integration with fast response.",
                "existing_requirements": [
                    {
                        "requirement_id": "REQ-001",
                        "description": "Salesforce CRM integration",
                        "category": "functional",
                        "moscow_priority": "must_have",
                        "stakeholder_domain": "sales",
                        "priority_score": "high",
                        "extraction_confidence": 0.9,
                    },
                ],
            },
            {"tenant_id": "test"},
        )

        assert "gap_analysis" in result
        gap = result["gap_analysis"]
        assert "gaps" in gap
        assert isinstance(gap["gaps"], list)
        assert len(gap["gaps"]) > 0

    @pytest.mark.asyncio
    async def test_gap_analysis_includes_contradictions(self, ba_agent):
        """Contradictions are included in the GapAnalysisResult output."""
        agent, mock_llm, _mock_rag = ba_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_gap_analysis_json()}
        )

        result = await agent.execute(
            {
                "type": "gap_analysis",
                "conversation_text": "Integration and latency requirements.",
                "existing_requirements": [
                    {
                        "requirement_id": "REQ-001",
                        "description": "Salesforce integration",
                        "category": "functional",
                        "moscow_priority": "must_have",
                        "stakeholder_domain": "sales",
                        "priority_score": "high",
                        "extraction_confidence": 0.9,
                    },
                ],
            },
            {"tenant_id": "test"},
        )

        gap = result["gap_analysis"]
        assert "contradictions" in gap
        assert len(gap["contradictions"]) >= 1
        contradiction = gap["contradictions"][0]
        assert "conflict_description" in contradiction
        assert "requirement_ids" in contradiction

    @pytest.mark.asyncio
    async def test_gap_analysis_coverage_percentage(self, ba_agent):
        """coverage_percentage is present and within 0-100."""
        agent, mock_llm, _mock_rag = ba_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_gap_analysis_json()}
        )

        result = await agent.execute(
            {
                "type": "gap_analysis",
                "conversation_text": "Requirements for analysis.",
                "existing_requirements": [
                    {
                        "requirement_id": "REQ-001",
                        "description": "Test requirement",
                        "category": "functional",
                        "moscow_priority": "must_have",
                        "stakeholder_domain": "sales",
                        "priority_score": "high",
                        "extraction_confidence": 0.9,
                    },
                ],
            },
            {"tenant_id": "test"},
        )

        gap = result["gap_analysis"]
        assert "coverage_percentage" in gap
        assert 0.0 <= gap["coverage_percentage"] <= 100.0
        assert gap["coverage_percentage"] == 75.0


# -- Tests: User Story Generation Handler --------------------------------------


class TestBAUserStoryGeneration:
    """Tests for user_story_generation handler."""

    @pytest.mark.asyncio
    async def test_user_story_generation_handler(self, ba_agent):
        """execute() routes 'user_story_generation' and returns user_stories list."""
        agent, mock_llm, _mock_rag = ba_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_user_stories_json()}
        )

        result = await agent.execute(
            {
                "type": "user_story_generation",
                "existing_requirements": [
                    {
                        "requirement_id": "REQ-001",
                        "description": "Salesforce CRM integration",
                        "category": "functional",
                        "moscow_priority": "must_have",
                        "stakeholder_domain": "sales",
                        "priority_score": "high",
                        "extraction_confidence": 0.9,
                    },
                ],
            },
            {"tenant_id": "test"},
        )

        assert "user_stories" in result
        assert isinstance(result["user_stories"], list)
        assert len(result["user_stories"]) == 2
        mock_llm.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_user_story_fibonacci_validation(self):
        """story_points must be valid Fibonacci numbers (1, 2, 3, 5, 8, 13)."""
        # Valid Fibonacci values should pass
        for pts in (1, 2, 3, 5, 8, 13):
            story = UserStory(
                story_id="US-test",
                as_a="user",
                i_want="feature",
                so_that="value",
                acceptance_criteria=["criterion"],
                story_points=pts,
                priority="must_have",
                epic_theme="Test",
                stakeholder_domain="tech",
            )
            assert story.story_points == pts

        # Invalid values should raise ValidationError
        import pydantic

        # 0 is caught by ge=1 before Fibonacci validator runs
        with pytest.raises(pydantic.ValidationError):
            UserStory(
                story_id="US-test",
                as_a="user",
                i_want="feature",
                so_that="value",
                acceptance_criteria=["criterion"],
                story_points=0,
                priority="must_have",
                epic_theme="Test",
                stakeholder_domain="tech",
            )

        # Values >= 1 but not in Fibonacci set are caught by the validator
        for invalid_pts in (4, 6, 7, 9, 10, 11, 21):
            with pytest.raises(pydantic.ValidationError, match="Fibonacci"):
                UserStory(
                    story_id="US-test",
                    as_a="user",
                    i_want="feature",
                    so_that="value",
                    acceptance_criteria=["criterion"],
                    story_points=invalid_pts,
                    priority="must_have",
                    epic_theme="Test",
                    stakeholder_domain="tech",
                )

    @pytest.mark.asyncio
    async def test_user_story_low_confidence_flagged(self, ba_agent):
        """Low-confidence stories are included but flagged."""
        agent, mock_llm, _mock_rag = ba_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_user_stories_json()}
        )

        result = await agent.execute(
            {
                "type": "user_story_generation",
                "existing_requirements": [
                    {
                        "requirement_id": "REQ-003",
                        "description": "Data retention",
                        "category": "constraint",
                        "moscow_priority": "must_have",
                        "stakeholder_domain": "ops",
                        "priority_score": "high",
                        "extraction_confidence": 0.4,
                    },
                ],
            },
            {"tenant_id": "test"},
        )

        stories = result["user_stories"]
        # US-002 has is_low_confidence=True
        low_conf = [s for s in stories if s["story_id"] == "US-002"]
        assert len(low_conf) == 1
        assert low_conf[0]["is_low_confidence"] is True

        # US-001 has is_low_confidence=False
        high_conf = [s for s in stories if s["story_id"] == "US-001"]
        assert len(high_conf) == 1
        assert high_conf[0]["is_low_confidence"] is False


# -- Tests: Process Documentation Handler --------------------------------------


class TestBAProcessDocumentation:
    """Tests for process_documentation handler."""

    @pytest.mark.asyncio
    async def test_process_documentation_handler(self, ba_agent):
        """execute() routes 'process_documentation' and returns process_documentation."""
        agent, mock_llm, _mock_rag = ba_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_process_doc_json()}
        )

        result = await agent.execute(
            {
                "type": "process_documentation",
                "conversation_text": "Our current lead qualification is all manual.",
            },
            {"tenant_id": "test"},
        )

        assert "process_documentation" in result
        proc_doc = result["process_documentation"]
        assert proc_doc is not None
        assert "process_name" in proc_doc
        assert "current_state" in proc_doc
        assert "future_state" in proc_doc
        assert "delta" in proc_doc
        assert "stakeholders" in proc_doc
        assert len(proc_doc["stakeholders"]) > 0
        mock_llm.completion.assert_called_once()


# -- Tests: Error Handling ------------------------------------------------------


class TestBAErrorHandling:
    """Tests for error handling and fail-open behavior."""

    @pytest.mark.asyncio
    async def test_unknown_task_type_returns_error(self, ba_agent):
        """Unknown task type returns error dict, not exception (BA-specific fail-open)."""
        agent, _mock_llm, _mock_rag = ba_agent

        # BA agent returns error dict instead of raising ValueError
        result = await agent.execute(
            {"type": "nonexistent"},
            {"tenant_id": "test"},
        )

        assert isinstance(result, dict)
        assert "error" in result
        assert result["confidence"] == "low"
        assert result["partial"] is True

    @pytest.mark.asyncio
    async def test_llm_failure_fail_open(self, ba_agent):
        """LLM failure triggers fail-open response, not exception."""
        agent, mock_llm, _mock_rag = ba_agent
        mock_llm.completion = AsyncMock(side_effect=Exception("LLM unavailable"))

        # Should NOT raise
        result = await agent.execute(
            {
                "type": "requirements_extraction",
                "conversation_text": "test data",
            },
            {"tenant_id": "test"},
        )

        assert isinstance(result, dict)
        assert "error" in result
        assert result["confidence"] == "low"
        assert result["partial"] is True


# -- Tests: Handoff Payloads ---------------------------------------------------


class TestBAHandoffPayloads:
    """Tests for handoff payload construction and serialization."""

    def test_handoff_payload_construction(self):
        """BAHandoffRequest and BAHandoffResponse serialize/deserialize correctly."""
        request = BAHandoffRequest(
            handoff_type="requirements_analysis",
            conversation_text="We need CRM integration.",
            deal_id="deal-123",
            tenant_id="tenant-abc",
            analysis_scope="full",
        )
        assert request.handoff_type == "requirements_analysis"
        assert request.deal_id == "deal-123"
        assert request.analysis_scope == "full"

        # Round-trip serialization
        request_dict = request.model_dump()
        request_restored = BAHandoffRequest.model_validate(request_dict)
        assert request_restored.conversation_text == request.conversation_text

        # BAHandoffResponse
        response = BAHandoffResponse(
            handoff_type="requirements_analysis",
            requirements=[],
            recommended_next_action="Proceed with gap analysis",
            confidence=0.85,
        )
        assert response.handoff_type == "requirements_analysis"
        assert response.confidence == 0.85

        # Round-trip serialization
        response_dict = response.model_dump()
        response_restored = BAHandoffResponse.model_validate(response_dict)
        assert response_restored.recommended_next_action == response.recommended_next_action


# -- Tests: Notion Block Renderers ----------------------------------------------


class TestBANotionRenderers:
    """Tests for module-level Notion block renderers."""

    def test_notion_block_renderers(self):
        """All 4 renderers return non-empty block lists with valid data."""
        # 1. Requirements renderer
        requirements = [
            ExtractedRequirement(
                requirement_id="REQ-001",
                description="Salesforce integration",
                category="functional",
                moscow_priority="must_have",
                stakeholder_domain="sales",
                priority_score="high",
                extraction_confidence=0.92,
            ),
            ExtractedRequirement(
                requirement_id="REQ-002",
                description="Low confidence item",
                category="constraint",
                moscow_priority="could_have",
                stakeholder_domain="ops",
                priority_score="low",
                extraction_confidence=0.3,
            ),
        ]
        req_blocks = render_requirements_to_notion_blocks(requirements)
        assert len(req_blocks) > 0
        # Should have heading and at least 2 bullet items
        assert any(b["type"] == "heading_2" for b in req_blocks)
        assert any(b["type"] == "bulleted_list_item" for b in req_blocks)

        # 2. Gap analysis renderer
        gap_result = GapAnalysisResult(
            requirements=[requirements[0]],
            gaps=[
                CapabilityGap(
                    requirement_id="REQ-001",
                    gap_description="No native Salesforce connector",
                    severity="major",
                    recommended_action="build_it",
                ),
            ],
            contradictions=[
                RequirementContradiction(
                    requirement_ids=["REQ-001", "REQ-002"],
                    conflict_description="Conflicting constraints",
                    resolution_suggestion="Prioritize one over the other",
                    severity="significant",
                ),
            ],
            coverage_percentage=75.0,
            recommended_next_action="Build connector",
        )
        gap_blocks = render_gap_analysis_to_notion_blocks(gap_result)
        assert len(gap_blocks) > 0
        assert any(b["type"] == "heading_2" for b in gap_blocks)

        # 3. User stories renderer
        stories = [
            UserStory(
                story_id="US-001",
                as_a="sales manager",
                i_want="automatic CRM sync",
                so_that="track deals without manual entry",
                acceptance_criteria=["Sync within 5 minutes"],
                story_points=8,
                priority="must_have",
                epic_theme="CRM Integration",
                stakeholder_domain="sales",
            ),
        ]
        story_blocks = render_user_stories_to_notion_blocks(stories)
        assert len(story_blocks) > 0
        assert any(b["type"] == "heading_2" for b in story_blocks)

        # 4. Process documentation renderer
        proc_doc = ProcessDocumentation(
            process_name="Lead Qualification",
            current_state="Manual review of emails",
            future_state="AI-powered lead scoring",
            delta="Eliminates manual review step",
            stakeholders=["Sales Director", "VP Engineering"],
            assumptions=["Historical data available"],
        )
        proc_blocks = render_process_doc_to_notion_blocks(proc_doc)
        assert len(proc_blocks) > 0
        assert any(b["type"] == "heading_2" for b in proc_blocks)
        # Should have stakeholder bullet items
        assert any(
            b["type"] == "bulleted_list_item"
            and "Sales Director" in b["bulleted_list_item"]["rich_text"][0]["text"]["content"]
            for b in proc_blocks
        )
