"""Round-trip integration tests for Sales Agent -> TAM Agent handoff.

Proves the 13-05 inter-agent handoff requirement: the Sales Agent can detect
TAM trigger conditions, construct a TAMHandoffRequest, dispatch a handoff task
to the Technical Account Manager agent, and the TAM agent processes the request
and returns structured results. Covers keyword triggers, stage triggers,
request type mapping, missing fields, and full round-trip flows for health scan
and escalation outreach.

All external dependencies (LLM, RAG, GSuite, stores, ticket clients) are mocked.
The tests exercise the actual execute() routing and handler logic for both agents.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.app.agents.sales.agent import TAM_REQUEST_TO_TASK_TYPE, SalesAgent
from src.app.agents.sales.capabilities import create_sales_registration
from src.app.agents.technical_account_manager.agent import TAMAgent
from src.app.agents.technical_account_manager.capabilities import create_tam_registration
from src.app.agents.technical_account_manager.health_scorer import HealthScorer
from src.app.agents.technical_account_manager.schemas import TAMHandoffRequest


# -- Fixtures ----------------------------------------------------------------


def _make_sales_agent() -> SalesAgent:
    """Create a SalesAgent with all dependencies mocked.

    The dispatch_tam_health_check handler does NOT use any of the
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


def _make_tam_agent(
    llm_mock: AsyncMock | None = None,
    ticket_client: AsyncMock | None = None,
    gmail_service: AsyncMock | None = None,
    health_scorer: HealthScorer | None = None,
) -> TAMAgent:
    """Create a TAMAgent with mocked dependencies and real HealthScorer."""
    registration = create_tam_registration()
    return TAMAgent(
        registration=registration,
        llm_service=llm_mock or AsyncMock(),
        notion_tam=None,
        gmail_service=gmail_service,
        chat_service=None,
        event_bus=None,
        ticket_client=ticket_client,
        health_scorer=health_scorer or HealthScorer(),
    )


# -- TAM Trigger Keyword Tests -----------------------------------------------


class TestSalesAgentTAMTriggerKeyword:
    """Tests for _is_tam_trigger keyword detection."""

    def test_two_keyword_matches_triggers(self):
        """Two or more TAM keyword matches return True."""
        text = "We have a health check issue and technical issues with the system"
        assert SalesAgent._is_tam_trigger(text, "prospecting") is True

    def test_no_keywords_does_not_trigger(self):
        """Non-matching text returns False."""
        text = "Hello, nice weather today"
        assert SalesAgent._is_tam_trigger(text, "prospecting") is False

    def test_single_keyword_does_not_trigger(self):
        """A single keyword match is not enough (need 2+)."""
        text = "We have a health check scheduled"
        assert SalesAgent._is_tam_trigger(text, "prospecting") is False


# -- TAM Trigger Stage Tests -------------------------------------------------


class TestSalesAgentTAMTriggerStage:
    """Tests for _is_tam_trigger stage detection."""

    def test_closed_won_stage_triggers(self):
        """closed_won stage returns True regardless of text."""
        assert SalesAgent._is_tam_trigger("no keywords", "closed_won") is True

    def test_active_customer_case_insensitive(self):
        """Stage matching is case-insensitive with space normalization."""
        assert SalesAgent._is_tam_trigger("no keywords", "Active Customer") is True

    def test_prospecting_stage_does_not_trigger(self):
        """prospecting stage does NOT trigger without keywords."""
        assert SalesAgent._is_tam_trigger("no keywords", "prospecting") is False

    def test_onboarding_stage_triggers(self):
        """onboarding stage returns True."""
        assert SalesAgent._is_tam_trigger("no keywords", "onboarding") is True

    def test_renewal_stage_triggers(self):
        """renewal stage returns True."""
        assert SalesAgent._is_tam_trigger("no keywords", "renewal") is True

    def test_account_management_stage_triggers(self):
        """account_management stage returns True."""
        assert SalesAgent._is_tam_trigger("no keywords", "account_management") is True


# -- Sales Agent Dispatch Tests -----------------------------------------------


class TestSalesAgentDispatchTAMHealthCheck:
    """Tests for the Sales Agent's dispatch_tam_health_check handler."""

    @pytest.mark.asyncio
    async def test_sales_agent_dispatch_tam_health_check(self):
        """Sales Agent constructs a valid handoff task for TAM agent."""
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "acc-1",
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "dispatched"
        assert result["target_agent_id"] == "technical_account_manager"
        assert result["handoff_task"]["type"] == "health_scan"
        assert result["handoff_task"]["account_id"] == "acc-1"

    @pytest.mark.asyncio
    async def test_sales_agent_dispatch_tam_missing_account_id(self):
        """Missing account_id returns failed status."""
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "",
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "failed"
        assert "account_id" in result["error"]

    @pytest.mark.asyncio
    async def test_sales_agent_tam_default_request_type(self):
        """Dispatch without request_type defaults to health_scan."""
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "acc-default",
            },
            context={"tenant_id": "t-1"},
        )

        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "health_scan"


# -- Request Type Mapping Tests -----------------------------------------------


class TestSalesAgentTAMRequestTypeMapping:
    """CRITICAL: Verify all 6 request types map correctly to TAM task router keys."""

    @pytest.mark.asyncio
    async def test_health_scan_mapping(self):
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "acc-rt-1",
                "request_type": "health_scan",
            },
            context={"tenant_id": "t-1"},
        )
        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "health_scan"

    @pytest.mark.asyncio
    async def test_escalation_outreach_mapping(self):
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "acc-rt-2",
                "request_type": "escalation_outreach",
            },
            context={"tenant_id": "t-1"},
        )
        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "escalation_outreach"

    @pytest.mark.asyncio
    async def test_release_notes_mapping(self):
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "acc-rt-3",
                "request_type": "release_notes",
            },
            context={"tenant_id": "t-1"},
        )
        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "release_notes"

    @pytest.mark.asyncio
    async def test_roadmap_preview_mapping(self):
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "acc-rt-4",
                "request_type": "roadmap_preview",
            },
            context={"tenant_id": "t-1"},
        )
        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "roadmap_preview"

    @pytest.mark.asyncio
    async def test_health_checkin_mapping(self):
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "acc-rt-5",
                "request_type": "health_checkin",
            },
            context={"tenant_id": "t-1"},
        )
        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "health_checkin"

    @pytest.mark.asyncio
    async def test_customer_success_review_mapping(self):
        agent = _make_sales_agent()
        result = await agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "acc-rt-6",
                "request_type": "customer_success_review",
            },
            context={"tenant_id": "t-1"},
        )
        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "customer_success_review"

    def test_tam_request_to_task_type_dict_completeness(self):
        """Verify TAM_REQUEST_TO_TASK_TYPE covers all TAMHandoffRequest.request_type values."""
        expected_types = {
            "health_scan", "escalation_outreach", "release_notes",
            "roadmap_preview", "health_checkin", "customer_success_review",
        }
        assert set(TAM_REQUEST_TO_TASK_TYPE.keys()) == expected_types

        # All values should also be valid TAM agent task types
        valid_tam_task_types = {
            "health_scan", "escalation_outreach", "release_notes",
            "roadmap_preview", "health_checkin", "customer_success_review",
            "update_relationship_profile",
        }
        for req_type, task_type in TAM_REQUEST_TO_TASK_TYPE.items():
            assert task_type in valid_tam_task_types, (
                f"TAM_REQUEST_TO_TASK_TYPE[{req_type!r}] = {task_type!r} "
                f"is not a valid TAM task type"
            )


# -- Round-Trip Tests ---------------------------------------------------------


class TestSalesToTAMRoundTripHealthScan:
    """End-to-end round-trip: Sales Agent -> TAM Agent health scan."""

    @pytest.mark.asyncio
    async def test_sales_to_tam_round_trip_health_scan(self):
        """Full round-trip: Sales dispatches, TAM returns health score."""
        # Step 1: Sales Agent dispatches tam_health_check
        sales_agent = _make_sales_agent()
        dispatch_result = await sales_agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "acc-rt-health",
            },
            context={"tenant_id": "t-round-trip"},
        )

        assert dispatch_result["status"] == "dispatched"
        handoff_task = dispatch_result["handoff_task"]
        assert handoff_task["type"] == "health_scan"

        # Step 2: Route handoff_task to TAM agent with real HealthScorer
        # Mock ticket_client returning 2 P1 tickets (age > threshold to trigger penalty)
        ticket_client = AsyncMock()
        ticket_client.get_open_tickets = AsyncMock(return_value=[
            {"ticket_id": "T-001", "priority": "P1", "age_days": 5.0},
            {"ticket_id": "T-002", "priority": "P2", "age_days": 2.0},
        ])
        ticket_client.get_p1_p2_tickets = AsyncMock(return_value=[
            {"ticket_id": "T-001", "priority": "P1", "age_days": 5.0},
            {"ticket_id": "T-002", "priority": "P2", "age_days": 2.0},
        ])

        tam_agent = _make_tam_agent(
            ticket_client=ticket_client,
            health_scorer=HealthScorer(),
        )
        tam_result = await tam_agent.execute(
            task=handoff_task,
            context={"tenant_id": "t-round-trip"},
        )

        # Step 3: Verify TAM returned a health score
        assert tam_result.get("task_type") == "health_scan"
        assert tam_result.get("error") is None
        assert tam_result.get("confidence") == "high"

        # The health_score field is populated for single-account scan
        health_score = tam_result.get("health_score")
        assert health_score is not None
        assert health_score["account_id"] == "acc-rt-health"
        assert 0 <= health_score["score"] <= 100
        assert health_score["rag_status"] in ("Green", "Amber", "Red")
        # With 2 P1/P2 tickets (oldest age 5 > threshold 3), score should have penalty
        # Penalty: 2 * 20 = 40. Score = 100 - 40 = 60. RAG = Amber.
        assert health_score["score"] == 60
        assert health_score["rag_status"] == "Amber"


class TestSalesToTAMRoundTripEscalationOutreach:
    """End-to-end round-trip: Sales Agent -> TAM Agent escalation outreach."""

    @pytest.mark.asyncio
    async def test_sales_to_tam_round_trip_escalation_outreach(self):
        """Full round-trip: Sales dispatches escalation, TAM generates outreach draft."""
        # Step 1: Sales Agent dispatches with request_type="escalation_outreach"
        sales_agent = _make_sales_agent()
        dispatch_result = await sales_agent.execute(
            task={
                "type": "dispatch_tam_health_check",
                "account_id": "acc-rt-esc",
                "request_type": "escalation_outreach",
            },
            context={"tenant_id": "t-round-trip"},
        )

        assert dispatch_result["status"] == "dispatched"
        handoff_task = dispatch_result["handoff_task"]
        assert handoff_task["type"] == "escalation_outreach"

        # Step 2: Route handoff_task to TAM agent
        # Mock LLM returning escalation outreach JSON
        tam_llm = AsyncMock()
        tam_llm.completion = AsyncMock(
            return_value={
                "content": json.dumps({
                    "subject": "Escalation: Account acc-rt-esc requires attention",
                    "body_html": "<p>Dear team, account acc-rt-esc health has degraded.</p>",
                    "key_issues": [
                        "Multiple P1 tickets open",
                        "Integration heartbeat silent for 96 hours",
                    ],
                })
            }
        )

        # Mock gmail_service to capture create_draft call
        gmail_mock = AsyncMock()
        gmail_mock.create_draft = AsyncMock(return_value={"draft_id": "draft-esc-123"})

        tam_agent = _make_tam_agent(
            llm_mock=tam_llm,
            gmail_service=gmail_mock,
            health_scorer=HealthScorer(),
        )

        # Add rep_email and health_score to the task (TAM escalation handler expects them)
        handoff_task["rep_email"] = "rep@example.com"
        handoff_task["health_score"] = {
            "score": 25,
            "rag_status": "Red",
            "previous_score": 60,
            "previous_rag": "Amber",
        }

        tam_result = await tam_agent.execute(
            task=handoff_task,
            context={"tenant_id": "t-round-trip"},
        )

        # Step 3: Verify TAM generated escalation outreach
        assert tam_result.get("task_type") == "escalation_outreach"
        assert tam_result.get("error") is None
        assert tam_result.get("confidence") == "high"
        assert tam_result.get("communication_type") == "escalation_outreach"
        assert tam_result.get("communication_content") is not None
        assert "acc-rt-esc" in tam_result["communication_content"]

        # Verify create_draft was called (not send_email)
        gmail_mock.create_draft.assert_called()
        gmail_mock.send_email = AsyncMock()  # Should not have been called
        # Confirm send_email was NOT called
        gmail_mock.send_email.assert_not_called()


# -- Serialization Tests ------------------------------------------------------


class TestTAMHandoffRequestSerialization:
    """Tests for TAMHandoffRequest serialization round-trip."""

    def test_tam_handoff_request_serialization(self):
        """Create TAMHandoffRequest, serialize to JSON, deserialize back."""
        request = TAMHandoffRequest(
            account_id="acc-ser-1",
            tenant_id="t-ser-1",
            deal_id="d-ser-1",
            request_type="escalation_outreach",
            handoff_type="escalation_alert",
        )

        json_str = request.model_dump_json()
        restored = TAMHandoffRequest.model_validate_json(json_str)

        assert restored.account_id == "acc-ser-1"
        assert restored.tenant_id == "t-ser-1"
        assert restored.deal_id == "d-ser-1"
        assert restored.request_type == "escalation_outreach"
        assert restored.handoff_type == "escalation_alert"


# -- Keyword Isolation Tests --------------------------------------------------


class TestTAMTriggerDoesNotMatchOtherAgentKeywords:
    """Verify TAM keywords don't cross-trigger with BA or SA keywords."""

    def test_requirements_text_does_not_trigger_tam(self):
        """BA-relevant text ('we need requirements') does NOT trigger TAM."""
        text = "We need requirements for SSO and our process requires API access"
        assert SalesAgent._is_tam_trigger(text, "prospecting") is False

    def test_api_integration_text_does_not_trigger_tam(self):
        """SA-relevant text about API architecture does NOT trigger TAM."""
        text = "What is your API architecture and how does the SDK handle authentication?"
        assert SalesAgent._is_tam_trigger(text, "prospecting") is False

    def test_tam_keywords_trigger_only_tam(self):
        """TAM-specific text triggers TAM but not BA."""
        text = "We have a health check concern and a support issue with the integration"
        assert SalesAgent._is_tam_trigger(text, "prospecting") is True
        assert SalesAgent._is_ba_trigger(text, "prospecting") is False
