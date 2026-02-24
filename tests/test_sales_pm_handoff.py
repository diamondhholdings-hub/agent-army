"""Round-trip integration tests for Sales Agent -> PM Agent handoff.

Proves the 11-05 inter-agent handoff requirement: the Sales Agent can
dispatch a project trigger event (deal_won, poc_scoped, complex_deal),
construct a PMTriggerEvent payload, dispatch a handoff task to the
Project Manager agent, and the PM agent processes the trigger to
initiate project planning.

All external dependencies (LLM, RAG, GSuite, stores) are mocked. The tests
exercise the actual execute() routing and handler logic for both agents.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.app.agents.sales.agent import SalesAgent
from src.app.agents.sales.capabilities import create_sales_registration
from src.app.agents.project_manager.agent import ProjectManagerAgent
from src.app.agents.project_manager.capabilities import create_pm_registration
from src.app.agents.project_manager.schemas import PMTriggerEvent


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_sales_agent() -> SalesAgent:
    """Create a SalesAgent with all dependencies mocked.

    The dispatch_project_trigger handler does NOT use any of the
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


# ── Test Cases ──────────────────────────────────────────────────────────────


class TestSalesAgentDispatchesProjectTrigger:
    """Tests for the Sales Agent's dispatch_project_trigger handler."""

    @pytest.mark.asyncio
    async def test_sales_agent_dispatches_deal_won_trigger(self):
        """Sales Agent constructs a valid handoff task for PM on deal_won."""
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_project_trigger",
                "trigger_type": "deal_won",
                "deal_id": "d-test-1",
                "deliverables": ["API integration"],
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "dispatched"
        assert result["target_agent_id"] == "project_manager"
        assert result["handoff_task"]["type"] == "process_trigger"
        assert result["handoff_task"]["trigger_type"] == "deal_won"
        assert result["handoff_task"]["deal_id"] == "d-test-1"
        assert "API integration" in result["handoff_task"]["deliverables"]

    @pytest.mark.asyncio
    async def test_sales_agent_dispatch_missing_fields_fails(self):
        """Empty trigger_type and deal_id returns failed status."""
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_project_trigger",
                "trigger_type": "",
                "deal_id": "",
            },
            context={},
        )

        assert result["status"] == "failed"
        assert "trigger_type" in result["error"]
        assert "deal_id" in result["error"]


class TestPMAgentReceivesTrigger:
    """Tests for the PM agent receiving a handoff task from Sales Agent."""

    @pytest.mark.asyncio
    async def test_pm_agent_receives_handoff_task(self):
        """PM agent processes a handoff_task dispatched by the Sales Agent."""
        pm_llm = AsyncMock()
        # First call: trigger analysis returning high priority
        # Second call: create_project_plan (chained internally by process_trigger)
        pm_llm.completion = AsyncMock(
            side_effect=[
                {
                    "content": json.dumps(
                        {
                            "project_name": "Test Project",
                            "recommended_phases": ["Discovery"],
                            "estimated_duration_weeks": 8,
                            "priority": "high",
                            "notes": "Deal won",
                        }
                    )
                },
                {
                    "content": json.dumps(
                        {
                            "plan_id": "p-1",
                            "deal_id": "d-1",
                            "project_name": "Test Project",
                            "phases": [
                                {
                                    "phase_id": "ph-1",
                                    "name": "Discovery",
                                    "resource_estimate_days": 10.0,
                                    "milestones": [
                                        {
                                            "milestone_id": "m-1",
                                            "name": "Kickoff",
                                            "target_date": "2026-03-01T00:00:00Z",
                                            "tasks": [
                                                {
                                                    "task_id": "t-1",
                                                    "name": "Schedule",
                                                    "owner": "PM",
                                                    "duration_days": 1.0,
                                                    "dependencies": [],
                                                    "status": "not_started",
                                                }
                                            ],
                                            "success_criteria": "Meeting held",
                                            "status": "not_started",
                                        }
                                    ],
                                }
                            ],
                            "created_at": "2026-02-23T00:00:00Z",
                            "updated_at": "2026-02-23T00:00:00Z",
                            "version": 1,
                            "trigger_source": "deal_won",
                            "total_budget_days": 10.0,
                        }
                    )
                },
            ]
        )
        pm_agent = _make_pm_agent(pm_llm)

        handoff_task = {
            "type": "process_trigger",
            "trigger_type": "deal_won",
            "deal_id": "d-1",
            "deliverables": ["API integration"],
            "timeline": "8 weeks",
            "stakeholders": [],
            "poc_plan": None,
        }
        result = await pm_agent.execute(task=handoff_task, context={"tenant_id": "t-1"})

        assert result.get("trigger_processed") is True
        assert result["trigger_type"] == "deal_won"
        # Plan was created because trigger analysis returned priority=high
        assert result.get("plan") is not None


class TestFullRoundTrip:
    """End-to-end round-trip test: Sales Agent -> PM Agent."""

    @pytest.mark.asyncio
    async def test_full_round_trip_sales_to_pm(self):
        """Full round-trip: Sales dispatches trigger, PM processes and creates plan."""
        # Step 1: Sales Agent dispatches trigger
        sales_agent = _make_sales_agent()
        dispatch_result = await sales_agent.execute(
            task={
                "type": "dispatch_project_trigger",
                "trigger_type": "deal_won",
                "deal_id": "d-1",
                "deliverables": ["CRM integration", "Reporting"],
            },
            context={"tenant_id": "t-1"},
        )
        assert dispatch_result["status"] == "dispatched"

        # Step 2: PM agent processes the handoff task
        handoff_task = dispatch_result["handoff_task"]
        pm_llm = AsyncMock()
        pm_llm.completion = AsyncMock(
            return_value={
                "content": json.dumps(
                    {
                        "project_name": "CRM Integration Project",
                        "recommended_phases": [
                            "Discovery",
                            "Build",
                            "Deploy",
                        ],
                        "estimated_duration_weeks": 12,
                        "priority": "high",
                        "notes": "Standard integration project",
                    }
                )
            }
        )
        pm_agent = _make_pm_agent(pm_llm)
        pm_result = await pm_agent.execute(
            task=handoff_task, context={"tenant_id": "t-1"}
        )

        # PM should have processed the trigger successfully
        assert pm_result.get("trigger_processed") is True
        assert pm_result["trigger_type"] == "deal_won"


class TestIsProjectTrigger:
    """Tests for the _is_project_trigger heuristic helper."""

    def test_is_project_trigger_deal_won(self):
        """closed_won stage returns deal_won trigger type."""
        result = SalesAgent._is_project_trigger("closed_won", {})
        assert result == "deal_won"

    def test_is_project_trigger_won(self):
        """'won' stage (alternative spelling) returns deal_won."""
        result = SalesAgent._is_project_trigger("won", {})
        assert result == "deal_won"

    def test_is_project_trigger_case_insensitive(self):
        """Stage matching is case-insensitive."""
        result = SalesAgent._is_project_trigger("Closed Won", {})
        assert result == "deal_won"

    def test_is_project_trigger_poc_scoped(self):
        """poc_scoped context flag returns poc_scoped trigger type."""
        result = SalesAgent._is_project_trigger("evaluation", {"poc_scoped": True})
        assert result == "poc_scoped"

    def test_is_project_trigger_complex_deal(self):
        """complex_deal context flag returns complex_deal trigger type."""
        result = SalesAgent._is_project_trigger(
            "discovery", {"complex_deal": True}
        )
        assert result == "complex_deal"

    def test_is_project_trigger_no_trigger(self):
        """No matching conditions returns None."""
        result = SalesAgent._is_project_trigger("qualification", {})
        assert result is None


class TestTriggerPayloadValidation:
    """Tests that dispatch creates valid PMTriggerEvent payloads."""

    @pytest.mark.asyncio
    async def test_dispatch_creates_valid_pm_trigger_event(self):
        """Payload round-trips as valid PMTriggerEvent via model_validate_json."""
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_project_trigger",
                "trigger_type": "poc_scoped",
                "deal_id": "d-2",
                "deliverables": ["POC deployment"],
                "timeline": "6 weeks",
                "stakeholders": ["tech@customer.com"],
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "dispatched"

        # Verify payload round-trips as valid PMTriggerEvent
        payload = PMTriggerEvent.model_validate_json(result["payload"])
        assert payload.trigger_type == "poc_scoped"
        assert payload.deal_id == "d-2"
        assert "POC deployment" in payload.deliverables
        assert payload.timeline == "6 weeks"
        assert "tech@customer.com" in payload.stakeholders
        assert payload.tenant_id == "t-1"
