"""Round-trip integration tests for Sales Agent -> BA Agent and PM Agent -> BA Agent handoff.

Proves the 12-05 inter-agent handoff requirement: the Sales Agent can detect
BA trigger conditions, construct a BAHandoffRequest, dispatch a handoff task
to the Business Analyst agent, and the BA agent processes the request and
returns structured analysis results. Similarly, the PM Agent can dispatch
scope change impact analysis to the BA agent.

All external dependencies (LLM, RAG, GSuite, stores) are mocked. The tests
exercise the actual execute() routing and handler logic for all three agents.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.app.agents.sales.agent import SCOPE_TO_TASK_TYPE, SalesAgent
from src.app.agents.sales.capabilities import create_sales_registration
from src.app.agents.project_manager.agent import ProjectManagerAgent
from src.app.agents.project_manager.capabilities import create_pm_registration
from src.app.agents.business_analyst.agent import BusinessAnalystAgent
from src.app.agents.business_analyst.capabilities import create_ba_registration
from src.app.agents.business_analyst.schemas import BAHandoffRequest


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_sales_agent() -> SalesAgent:
    """Create a SalesAgent with all dependencies mocked.

    The dispatch_requirements_analysis handler does NOT use any of the
    external services (gmail, chat, rag, etc.), so simple stubs suffice.
    """
    registration = create_sales_registration()
    return SalesAgent(
        registration=registration,
        llm_service=AsyncMock(),
        gmail_service=AsyncMock(),
        chat_service=AsyncMock(),
        rag_pipeline=AsyncMock(),
        conversation_store=AsyncMock(),
        session_manager=AsyncMock(),
        state_repository=AsyncMock(),
        qualification_extractor=AsyncMock(),
        action_engine=AsyncMock(),
        escalation_manager=AsyncMock(),
    )


def _make_pm_agent(llm_mock: AsyncMock | None = None) -> ProjectManagerAgent:
    """Create a ProjectManagerAgent with mocked dependencies."""
    registration = create_pm_registration()
    return ProjectManagerAgent(
        registration=registration,
        llm_service=llm_mock or AsyncMock(),
        rag_pipeline=AsyncMock(),
        notion_pm=AsyncMock(),
    )


def _make_ba_agent(llm_mock: AsyncMock | None = None) -> BusinessAnalystAgent:
    """Create a BusinessAnalystAgent with mocked dependencies."""
    registration = create_ba_registration()
    return BusinessAnalystAgent(
        registration=registration,
        llm_service=llm_mock or AsyncMock(),
        rag_pipeline=None,
    )


# ── BA Trigger Heuristic Tests ──────────────────────────────────────────────


class TestSalesAgentBATriggerKeyword:
    """Tests for _is_ba_trigger keyword detection."""

    def test_two_keyword_matches_triggers(self):
        """Two or more BA keyword matches return True."""
        text = "We need API access and our process requires SSO integration"
        assert SalesAgent._is_ba_trigger(text, "prospecting") is True

    def test_no_keywords_does_not_trigger(self):
        """Non-matching text returns False."""
        text = "Hello, nice weather today"
        assert SalesAgent._is_ba_trigger(text, "prospecting") is False

    def test_single_keyword_does_not_trigger(self):
        """A single keyword match is not enough."""
        text = "We have a requirement for your product"
        assert SalesAgent._is_ba_trigger(text, "prospecting") is False

    def test_three_keywords_triggers(self):
        """More than two matches also triggers."""
        text = "We need to discuss the use case and our current process has a pain point"
        assert SalesAgent._is_ba_trigger(text, "prospecting") is True


class TestSalesAgentBATriggerStage:
    """Tests for _is_ba_trigger stage detection."""

    def test_technical_evaluation_stage_triggers(self):
        """technical_evaluation stage returns True regardless of text."""
        assert SalesAgent._is_ba_trigger("no keywords", "technical_evaluation") is True

    def test_technical_evaluation_case_insensitive(self):
        """Stage matching is case-insensitive with space normalization."""
        assert SalesAgent._is_ba_trigger("no keywords", "Technical Evaluation") is True

    def test_evaluation_stage_triggers(self):
        """evaluation stage returns True."""
        assert SalesAgent._is_ba_trigger("no keywords", "evaluation") is True

    def test_discovery_stage_triggers(self):
        """discovery stage returns True."""
        assert SalesAgent._is_ba_trigger("no keywords", "discovery") is True

    def test_prospecting_stage_does_not_trigger(self):
        """prospecting stage does NOT trigger without keywords."""
        assert SalesAgent._is_ba_trigger("no keywords", "prospecting") is False


# ── Sales Agent Dispatch Tests ──────────────────────────────────────────────


class TestSalesAgentDispatchRequirementsAnalysis:
    """Tests for the Sales Agent's dispatch_requirements_analysis handler."""

    @pytest.mark.asyncio
    async def test_sales_agent_dispatch_requirements_analysis(self):
        """Sales Agent constructs a valid handoff task for BA agent."""
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_requirements_analysis",
                "conversation_text": "We need SSO and our process requires API access",
                "deal_id": "d-ba-1",
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "dispatched"
        assert result["target_agent_id"] == "business_analyst"
        assert result["handoff_task"]["type"] == "requirements_extraction"
        assert result["handoff_task"]["deal_id"] == "d-ba-1"
        assert "SSO" in result["handoff_task"]["conversation_text"]

    @pytest.mark.asyncio
    async def test_sales_agent_dispatch_missing_fields(self):
        """Missing conversation_text returns failed status."""
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_requirements_analysis",
                "conversation_text": "",
                "deal_id": "d-ba-2",
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "failed"
        assert "conversation_text" in result["error"]

    @pytest.mark.asyncio
    async def test_sales_agent_dispatch_missing_deal_id(self):
        """Missing deal_id returns failed status."""
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_requirements_analysis",
                "conversation_text": "Some conversation",
                "deal_id": "",
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "failed"
        assert "deal_id" in result["error"]


class TestSalesAgentScopeToTaskTypeMapping:
    """CRITICAL: Verify all 4 scope values map correctly to BA task router keys."""

    @pytest.mark.asyncio
    async def test_full_scope_maps_to_requirements_extraction(self):
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_requirements_analysis",
                "conversation_text": "We need features",
                "deal_id": "d-scope-1",
                "analysis_scope": "full",
            },
            context={"tenant_id": "t-1"},
        )
        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "requirements_extraction"

    @pytest.mark.asyncio
    async def test_gap_only_scope_maps_to_gap_analysis(self):
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_requirements_analysis",
                "conversation_text": "We have gaps",
                "deal_id": "d-scope-2",
                "analysis_scope": "gap_only",
            },
            context={"tenant_id": "t-1"},
        )
        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "gap_analysis"

    @pytest.mark.asyncio
    async def test_stories_only_scope_maps_to_user_story_generation(self):
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_requirements_analysis",
                "conversation_text": "Generate stories",
                "deal_id": "d-scope-3",
                "analysis_scope": "stories_only",
            },
            context={"tenant_id": "t-1"},
        )
        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "user_story_generation"

    @pytest.mark.asyncio
    async def test_process_only_scope_maps_to_process_documentation(self):
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_requirements_analysis",
                "conversation_text": "Document our process",
                "deal_id": "d-scope-4",
                "analysis_scope": "process_only",
            },
            context={"tenant_id": "t-1"},
        )
        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "process_documentation"

    def test_scope_to_task_type_dict_completeness(self):
        """Verify SCOPE_TO_TASK_TYPE covers all BAHandoffRequest.analysis_scope values."""
        expected_scopes = {"full", "gap_only", "stories_only", "process_only"}
        assert set(SCOPE_TO_TASK_TYPE.keys()) == expected_scopes

        # Verify all values are valid BA agent task types
        valid_ba_task_types = {
            "requirements_extraction",
            "gap_analysis",
            "user_story_generation",
            "process_documentation",
        }
        for scope, task_type in SCOPE_TO_TASK_TYPE.items():
            assert task_type in valid_ba_task_types, (
                f"SCOPE_TO_TASK_TYPE[{scope!r}] = {task_type!r} is not a valid BA task type"
            )


# ── PM Agent Dispatch Tests ─────────────────────────────────────────────────


class TestPMAgentDispatchScopeChangeAnalysis:
    """Tests for the PM Agent's dispatch_scope_change_analysis handler."""

    @pytest.mark.asyncio
    async def test_pm_agent_dispatch_scope_change_analysis(self):
        """PM Agent constructs a valid handoff task for BA agent."""
        agent = _make_pm_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_scope_change_analysis",
                "conversation_text": "Client wants to add reporting module",
                "deal_id": "d-pm-1",
                "existing_requirements": [{"requirement_id": "REQ-001"}],
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "dispatched"
        assert result["target_agent_id"] == "business_analyst"
        assert result["handoff_task"]["type"] == "gap_analysis"
        assert result["handoff_task"]["deal_id"] == "d-pm-1"
        assert len(result["handoff_task"]["existing_requirements"]) == 1

    @pytest.mark.asyncio
    async def test_pm_agent_dispatch_missing_fields(self):
        """Missing required fields returns failed status."""
        agent = _make_pm_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_scope_change_analysis",
                "conversation_text": "",
                "deal_id": "",
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "failed"
        assert "conversation_text" in result["error"]
        assert "deal_id" in result["error"]

    @pytest.mark.asyncio
    async def test_pm_dispatch_payload_round_trips(self):
        """Payload serializes as valid BAHandoffRequest."""
        agent = _make_pm_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_scope_change_analysis",
                "conversation_text": "Scope change: add analytics",
                "deal_id": "d-pm-2",
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "dispatched"
        payload = BAHandoffRequest.model_validate_json(result["payload"])
        assert payload.analysis_scope == "gap_only"
        assert payload.deal_id == "d-pm-2"
        assert payload.tenant_id == "t-1"


# ── Round-Trip Tests ────────────────────────────────────────────────────────


class TestSalestoBAARoundTrip:
    """End-to-end round-trip: Sales Agent -> BA Agent -> validated response."""

    @pytest.mark.asyncio
    async def test_sales_to_ba_round_trip(self):
        """Full round-trip: Sales dispatches, BA processes requirements extraction."""
        # Step 1: Sales Agent dispatches requirements analysis
        sales_agent = _make_sales_agent()
        dispatch_result = await sales_agent.execute(
            task={
                "type": "dispatch_requirements_analysis",
                "conversation_text": (
                    "We need SSO integration with SAML 2.0. "
                    "Our process requires automated user provisioning."
                ),
                "deal_id": "d-rt-1",
                "analysis_scope": "full",
            },
            context={"tenant_id": "t-round-trip"},
        )

        assert dispatch_result["status"] == "dispatched"
        handoff_task = dispatch_result["handoff_task"]
        assert handoff_task["type"] == "requirements_extraction"

        # Step 2: Route handoff_task to BA agent (simulating Supervisor routing)
        ba_llm = AsyncMock()
        ba_llm.completion = AsyncMock(
            return_value={
                "content": json.dumps([
                    {
                        "requirement_id": "REQ-001",
                        "description": "SSO integration with SAML 2.0",
                        "category": "functional",
                        "moscow_priority": "must_have",
                        "stakeholder_domain": "tech",
                        "priority_score": "high",
                        "extraction_confidence": 0.9,
                        "source_quote": "We need SSO integration with SAML 2.0",
                    },
                    {
                        "requirement_id": "REQ-002",
                        "description": "Automated user provisioning",
                        "category": "functional",
                        "moscow_priority": "should_have",
                        "stakeholder_domain": "ops",
                        "priority_score": "med",
                        "extraction_confidence": 0.85,
                        "source_quote": "Our process requires automated user provisioning",
                    },
                ])
            }
        )
        ba_agent = _make_ba_agent(ba_llm)
        ba_result = await ba_agent.execute(
            task=handoff_task,
            context={"tenant_id": "t-round-trip"},
        )

        # Step 3: Verify BA returned structured requirements
        assert ba_result.get("task_type") == "requirements_extraction"
        assert ba_result.get("error") is None
        assert len(ba_result["requirements"]) == 2
        assert ba_result["requirements"][0]["requirement_id"] == "REQ-001"
        assert ba_result["confidence"] in ("high", "medium", "low")


class TestPMtoBAARoundTrip:
    """End-to-end round-trip: PM Agent -> BA Agent -> gap analysis."""

    @pytest.mark.asyncio
    async def test_pm_to_ba_round_trip(self):
        """Full round-trip: PM dispatches scope change, BA returns gap analysis."""
        # Step 1: PM Agent dispatches scope change analysis
        pm_agent = _make_pm_agent()
        dispatch_result = await pm_agent.execute(
            task={
                "type": "dispatch_scope_change_analysis",
                "conversation_text": "Client wants to add a reporting dashboard module",
                "deal_id": "d-rt-2",
                "existing_requirements": [
                    {
                        "requirement_id": "REQ-001",
                        "description": "Core API integration",
                        "category": "functional",
                        "moscow_priority": "must_have",
                        "stakeholder_domain": "tech",
                        "priority_score": "high",
                        "extraction_confidence": 0.9,
                    }
                ],
            },
            context={"tenant_id": "t-round-trip"},
        )

        assert dispatch_result["status"] == "dispatched"
        handoff_task = dispatch_result["handoff_task"]
        assert handoff_task["type"] == "gap_analysis"

        # Step 2: Route handoff_task to BA agent
        ba_llm = AsyncMock()
        ba_llm.completion = AsyncMock(
            return_value={
                "content": json.dumps({
                    "requirements": [
                        {
                            "requirement_id": "REQ-001",
                            "description": "Core API integration",
                            "category": "functional",
                            "moscow_priority": "must_have",
                            "stakeholder_domain": "tech",
                            "priority_score": "high",
                            "extraction_confidence": 0.9,
                        }
                    ],
                    "gaps": [
                        {
                            "requirement_id": "REQ-001",
                            "gap_description": "Reporting dashboard not in current scope",
                            "severity": "major",
                            "recommended_action": "build_it",
                            "workaround": None,
                            "requires_sa_escalation": False,
                        }
                    ],
                    "contradictions": [],
                    "coverage_percentage": 60.0,
                    "recommended_next_action": "Scope reporting dashboard as new deliverable",
                    "requires_sa_escalation": False,
                })
            }
        )
        ba_agent = _make_ba_agent(ba_llm)
        ba_result = await ba_agent.execute(
            task=handoff_task,
            context={"tenant_id": "t-round-trip"},
        )

        # Step 3: Verify BA returned gap analysis results
        assert ba_result.get("task_type") == "gap_analysis"
        assert ba_result.get("error") is None
        assert ba_result["gap_analysis"] is not None
        assert ba_result["gap_analysis"]["coverage_percentage"] == 60.0
        assert len(ba_result["gap_analysis"]["gaps"]) == 1
        assert ba_result["gap_analysis"]["gaps"][0]["severity"] == "major"
