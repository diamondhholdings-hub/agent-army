"""Integration tests for the Technical Account Manager agent.

Tests cover all 7 capability handlers (health_scan, escalation_outreach,
release_notes, roadmap_preview, health_checkin, customer_success_review,
update_relationship_profile), HealthScorer edge cases (8 tests),
error handling (unknown type, fail-open on LLM error, partial notification
failure), schema auto-computation, registration correctness, handoff
payload construction, and GmailService.create_draft output structure.

All external dependencies (LLM service, Notion adapter, Gmail service,
Chat service, event bus, ticket client) are mocked -- no external services
are required to run these tests. HealthScorer is used as the REAL
implementation (pure Python, deterministic).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.agents.technical_account_manager import (
    TAMAgent,
    create_tam_registration,
)
from src.app.agents.technical_account_manager.schemas import (
    CoDevOpportunity,
    CommunicationRecord,
    EscalationNotificationResult,
    HealthScoreResult,
    IntegrationStatus,
    RelationshipProfile,
    StakeholderProfile,
    TAMHandoffRequest,
    TAMHandoffResponse,
    TAMResult,
    TAMTask,
    TicketSummary,
)
from src.app.agents.technical_account_manager.health_scorer import HealthScorer
from src.app.agents.base import BaseAgent


# -- Mock LLM response factories --------------------------------------------------


def _make_escalation_outreach_json() -> str:
    """Return JSON matching the escalation outreach schema."""
    return json.dumps(
        {
            "subject": "Proactive Support: Addressing Recent Technical Issues",
            "body_html": (
                "<p>Dear Acme team,</p>"
                "<p>We noticed some recent health changes and want to help.</p>"
                "<p>Let's schedule a call to discuss next steps.</p>"
            ),
            "tone": "empathetic",
            "key_issues": [
                "P1 ticket open for 5 days",
                "Health score dropped to 35",
            ],
        }
    )


def _make_release_notes_json() -> str:
    """Return JSON matching the release notes schema."""
    return json.dumps(
        {
            "subject": "Release v2.5: Features Relevant to Your Integration",
            "body_html": (
                "<p>Hi Acme team,</p>"
                "<p>Version 2.5 includes improvements to our REST API "
                "that affect your Salesforce integration.</p>"
            ),
            "highlighted_features": [
                "REST API v2 with batch support",
                "Webhook retry improvements",
            ],
            "relevance_notes": [
                "Your Salesforce integration will benefit from batch support",
                "Webhook retries reduce missed events",
            ],
        }
    )


def _make_roadmap_preview_json() -> str:
    """Return JSON matching the roadmap preview schema with co-dev opportunities."""
    return json.dumps(
        {
            "subject": "Q2 Roadmap Preview: Aligned with Your Needs",
            "body_html": (
                "<p>Hi Acme team,</p>"
                "<p>Here's a preview of upcoming features aligned with "
                "your technical roadmap.</p>"
            ),
            "aligned_items": [
                "GraphQL API (Q2)",
                "Advanced webhook filtering (Q3)",
            ],
            "co_dev_opportunities": [
                "Early access to GraphQL beta",
                "Joint webhook filtering design sessions",
            ],
        }
    )


def _make_health_checkin_json() -> str:
    """Return JSON matching the health check-in schema."""
    return json.dumps(
        {
            "subject": "Monthly Health Check-in: Acme Corp",
            "body_html": (
                "<p>Hi Acme team,</p>"
                "<p>Your account health is currently Green (score: 85). "
                "Everything is running smoothly.</p>"
            ),
            "health_summary": "Account health is stable at Green (85/100)",
            "recommendations": [
                "Consider adopting the new batch API for improved performance",
                "Schedule a quarterly architecture review",
            ],
        }
    )


def _make_customer_success_review_json() -> str:
    """Return JSON matching the customer success review schema."""
    return json.dumps(
        {
            "subject": "Customer Success Review: Acme Corp - Q1 2026",
            "body_html": (
                "<p>Technical Health & Relationship Review</p>"
                "<p>Score: 72 (Amber). 2 open tickets pending resolution.</p>"
            ),
            "health_overview": "Account at Amber (72) due to 2 aged P2 tickets",
            "integration_summary": "Salesforce and Slack integrations active",
            "open_items": [
                "P2 ticket #1234: API timeout during batch sync (5 days)",
                "P3 ticket #1235: Dashboard widget alignment (2 days)",
            ],
            "recommendations": [
                "Prioritize P2 ticket resolution to improve score",
                "Consider enabling webhook retry for batch sync reliability",
            ],
        }
    )


def _make_mock_llm(response_json: str) -> AsyncMock:
    """Create a mock LLM service that returns the given JSON string."""
    mock = AsyncMock()
    mock.completion = AsyncMock(return_value={"content": response_json})
    return mock


# -- Mock Gmail draft result -------------------------------------------------------


def _make_mock_gmail_service() -> AsyncMock:
    """Create a mock GmailService whose create_draft returns a DraftResult-like object."""
    mock = AsyncMock()
    draft_result = MagicMock()
    draft_result.draft_id = "draft-abc-123"
    draft_result.message_id = "msg-xyz-456"
    draft_result.thread_id = "thread-789"
    mock.create_draft = AsyncMock(return_value=draft_result)
    # Ensure send_email is present but NOT called -- TAM never sends email
    mock.send_email = AsyncMock()
    return mock


# -- Fixtures ------------------------------------------------------------------


@pytest.fixture
def tam_agent():
    """Create a TAM agent with mocked external services.

    Returns (agent, mock_llm, mock_notion_tam, mock_gmail, mock_chat,
             mock_event_bus, mock_ticket_client).
    """
    registration = create_tam_registration()
    mock_llm = AsyncMock()
    mock_notion_tam = AsyncMock()
    mock_gmail = _make_mock_gmail_service()
    mock_chat = AsyncMock()
    mock_event_bus = AsyncMock()
    mock_ticket_client = AsyncMock()
    health_scorer = HealthScorer()  # REAL scorer -- pure Python, deterministic

    agent = TAMAgent(
        registration=registration,
        llm_service=mock_llm,
        notion_tam=mock_notion_tam,
        gmail_service=mock_gmail,
        chat_service=mock_chat,
        event_bus=mock_event_bus,
        ticket_client=mock_ticket_client,
        health_scorer=health_scorer,
    )
    return (
        agent,
        mock_llm,
        mock_notion_tam,
        mock_gmail,
        mock_chat,
        mock_event_bus,
        mock_ticket_client,
    )


# -- Tests: Registration -------------------------------------------------------


class TestTAMRegistration:
    """Tests for TAM agent registration and class hierarchy."""

    def test_registration_correctness(self):
        """create_tam_registration returns agent_id='technical_account_manager', 5 capabilities."""
        reg = create_tam_registration()

        assert reg.agent_id == "technical_account_manager"
        assert reg.name == "Technical Account Manager"
        assert len(reg.capabilities) == 5

        cap_names = {c.name for c in reg.capabilities}
        assert cap_names == {
            "health_monitoring",
            "escalation_risk_scoring",
            "technical_communication",
            "relationship_profiling",
            "opportunity_surfacing",
        }

    def test_tam_is_base_agent_subclass(self):
        """TAMAgent inherits from BaseAgent."""
        assert issubclass(TAMAgent, BaseAgent)


# -- Tests: HealthScorer -------------------------------------------------------


class TestHealthScorer:
    """Tests for the pure Python HealthScorer -- all deterministic."""

    def test_health_scorer_perfect_health(self):
        """No issues -> score=100, rag='Green'."""
        scorer = HealthScorer()
        score, rag = scorer.compute_score(
            p1_p2_ticket_count=0,
            oldest_p1_p2_age_days=0,
            total_open_tickets=3,
            hours_since_heartbeat=24.0,
        )
        assert score == 100
        assert rag == "Green"

    def test_health_scorer_p1_p2_penalty(self):
        """2 aged P1/P2 tickets (age > 3 days) -> 100 - 2*20 = 60, rag='Amber'."""
        scorer = HealthScorer()
        score, rag = scorer.compute_score(
            p1_p2_ticket_count=2,
            oldest_p1_p2_age_days=5.0,
            total_open_tickets=2,
            hours_since_heartbeat=None,
        )
        assert score == 60
        assert rag == "Amber"

    def test_health_scorer_excess_ticket_penalty(self):
        """8 open tickets (3 excess over threshold 5) -> 100 - 3*5 = 85, rag='Green'."""
        scorer = HealthScorer()
        score, rag = scorer.compute_score(
            p1_p2_ticket_count=0,
            oldest_p1_p2_age_days=0,
            total_open_tickets=8,
            hours_since_heartbeat=None,
        )
        assert score == 85
        assert rag == "Green"

    def test_health_scorer_heartbeat_silence_penalty(self):
        """Silence > 2x threshold (144+ hours) -> 100 - 30 = 70. Add 1 excess ticket -> 65, rag='Amber'."""
        scorer = HealthScorer()
        # heartbeat penalty alone gives 70 which equals amber_threshold (Green boundary)
        # Adding 1 excess ticket (6 total, threshold 5) drops it to 65 -> Amber
        score, rag = scorer.compute_score(
            p1_p2_ticket_count=0,
            oldest_p1_p2_age_days=0,
            total_open_tickets=6,
            hours_since_heartbeat=150.0,
        )
        assert score == 65
        assert rag == "Amber"

    def test_health_scorer_none_heartbeat_no_penalty(self):
        """None heartbeat = not monitored -> score=100, no penalty."""
        scorer = HealthScorer()
        score, rag = scorer.compute_score(
            p1_p2_ticket_count=0,
            oldest_p1_p2_age_days=0,
            total_open_tickets=0,
            hours_since_heartbeat=None,
        )
        assert score == 100
        assert rag == "Green"

    def test_health_scorer_combined_penalties(self):
        """All 3 signals bad -> score floors at 0."""
        scorer = HealthScorer()
        score, rag = scorer.compute_score(
            p1_p2_ticket_count=3,   # 3 * 20 = 60 penalty (aged > threshold)
            oldest_p1_p2_age_days=10.0,
            total_open_tickets=15,  # 10 excess * 5 = 50 penalty
            hours_since_heartbeat=200.0,  # > 2x threshold = 30 penalty
        )
        # 100 - 60 - 50 - 30 = -40, floored to 0
        assert score == 0
        assert rag == "Red"

    def test_health_scorer_should_escalate(self):
        """Test all 3 escalation conditions."""
        scorer = HealthScorer()

        # Condition 1: score < 40
        assert scorer.should_escalate(35, "Red", None) is True
        assert scorer.should_escalate(35, "Red", "Green") is True

        # Condition 2: Green -> Red transition
        assert scorer.should_escalate(45, "Red", "Green") is True
        assert scorer.should_escalate(45, "Red", "Amber") is True

        # Condition 3: Green -> Amber transition
        assert scorer.should_escalate(65, "Amber", "Green") is True

        # No escalation: stable Green
        assert scorer.should_escalate(85, "Green", "Green") is False
        assert scorer.should_escalate(85, "Green", None) is False

        # No escalation: stable Amber
        assert scorer.should_escalate(55, "Amber", "Amber") is False

        # No escalation: Red -> Amber (improvement)
        assert scorer.should_escalate(55, "Amber", "Red") is False

    def test_health_scorer_custom_thresholds(self):
        """HealthScorer with custom thresholds works correctly."""
        scorer = HealthScorer(
            p1_p2_age_threshold_days=1,
            open_ticket_count_threshold=3,
            heartbeat_silence_hours=24,
            red_threshold=50,
            amber_threshold=80,
        )
        # 2 aged tickets (age > 1 day): 100 - 2*20 = 60
        score, rag = scorer.compute_score(
            p1_p2_ticket_count=2,
            oldest_p1_p2_age_days=2.0,
            total_open_tickets=3,
            hours_since_heartbeat=None,
        )
        assert score == 60
        # With custom amber_threshold=80: 60 < 80 -> Amber (but >= 50 -> not Red)
        assert rag == "Amber"


# -- Tests: Handler - Health Scan -----------------------------------------------


class TestTAMHealthScan:
    """Tests for health_scan handler."""

    @pytest.mark.asyncio
    async def test_health_scan_single_account(self, tam_agent):
        """Mock ticket_client returns tickets, health_scorer computes score."""
        agent, _llm, mock_notion, _gmail, _chat, _event_bus, mock_ticket = tam_agent

        # Mock notion_tam.get_account to return None so agent uses default dict
        mock_notion.get_account = AsyncMock(return_value=None)

        # Mock ticket responses
        mock_ticket.get_open_tickets = AsyncMock(return_value=[
            {"ticket_id": "T1", "age_days": 2.0},
            {"ticket_id": "T2", "age_days": 1.0},
        ])
        mock_ticket.get_p1_p2_tickets = AsyncMock(return_value=[
            {"ticket_id": "T1", "age_days": 2.0},
        ])

        result = await agent.execute(
            {
                "type": "health_scan",
                "account_id": "acct-001",
            },
            {"tenant_id": "test"},
        )

        assert result["task_type"] == "health_scan"
        assert "error" not in result or result.get("error") is None
        assert result["confidence"] == "high"
        # Should have health_score set (single account scan)
        assert result.get("health_score") is not None
        assert isinstance(result["health_score"]["score"], int)
        assert result["health_score"]["account_id"] == "acct-001"
        # Verify ticket_client was called
        mock_ticket.get_open_tickets.assert_called_once_with("acct-001")
        mock_ticket.get_p1_p2_tickets.assert_called_once_with("acct-001")


# -- Tests: Handler - Escalation Outreach ---------------------------------------


class TestTAMEscalationOutreach:
    """Tests for escalation_outreach handler."""

    @pytest.mark.asyncio
    async def test_escalation_outreach_handler(self, tam_agent):
        """Mock LLM returns escalation JSON. Assert create_draft called (NOT send_email)."""
        agent, mock_llm, _notion, mock_gmail, _chat, _event_bus, _ticket = tam_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_escalation_outreach_json()}
        )

        result = await agent.execute(
            {
                "type": "escalation_outreach",
                "account_id": "acct-001",
                "rep_email": "rep@example.com",
                "health_score": {"score": 35, "rag_status": "Red"},
            },
            {"tenant_id": "test"},
        )

        assert result["task_type"] == "escalation_outreach"
        assert result["communication_type"] == "escalation_outreach"
        assert result.get("communication_content") is not None
        assert len(result["communication_content"]) > 0
        # Draft was created
        assert result.get("draft_id") is not None
        # create_draft was called (at least once for the outreach + escalation channels)
        assert mock_gmail.create_draft.call_count >= 1
        # CRITICAL: send_email was NEVER called
        mock_gmail.send_email.assert_not_called()
        mock_llm.completion.assert_called_once()


# -- Tests: Handler - Release Notes ---------------------------------------------


class TestTAMReleaseNotes:
    """Tests for release_notes handler."""

    @pytest.mark.asyncio
    async def test_release_notes_handler(self, tam_agent):
        """Mock LLM returns release notes JSON. Assert create_draft called."""
        agent, mock_llm, _notion, mock_gmail, _chat, _event_bus, _ticket = tam_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_release_notes_json()}
        )

        result = await agent.execute(
            {
                "type": "release_notes",
                "account_id": "acct-001",
                "rep_email": "rep@example.com",
                "release_info": {"version": "2.5", "features": ["batch API"]},
            },
            {"tenant_id": "test"},
        )

        assert result["task_type"] == "release_notes"
        assert result["communication_type"] == "release_notes"
        assert result.get("communication_content") is not None
        assert result.get("draft_id") == "draft-abc-123"
        mock_gmail.create_draft.assert_called_once()
        mock_llm.completion.assert_called_once()


# -- Tests: Handler - Roadmap Preview -------------------------------------------


class TestTAMRoadmapPreview:
    """Tests for roadmap_preview handler."""

    @pytest.mark.asyncio
    async def test_roadmap_preview_handler(self, tam_agent):
        """Mock LLM returns roadmap JSON with co-dev opportunities. Assert event_bus.publish called."""
        agent, mock_llm, _notion, mock_gmail, _chat, mock_event_bus, _ticket = tam_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_roadmap_preview_json()}
        )

        result = await agent.execute(
            {
                "type": "roadmap_preview",
                "account_id": "acct-001",
                "rep_email": "rep@example.com",
                "roadmap_items": [
                    {"name": "GraphQL API", "timeline": "Q2"},
                    {"name": "Webhook filtering", "timeline": "Q3"},
                ],
            },
            {"tenant_id": "test"},
        )

        assert result["task_type"] == "roadmap_preview"
        assert result["communication_type"] == "roadmap_preview"
        assert result.get("communication_content") is not None
        assert result.get("draft_id") == "draft-abc-123"
        # Co-dev opportunities dispatched to event bus
        assert "co_dev_opportunities" in result
        assert len(result["co_dev_opportunities"]) > 0
        mock_event_bus.publish.assert_called_once()
        # Verify event was published to "opportunities" topic
        call_args = mock_event_bus.publish.call_args
        assert call_args[0][0] == "opportunities"


# -- Tests: Handler - Health Check-in -------------------------------------------


class TestTAMHealthCheckin:
    """Tests for health_checkin handler."""

    @pytest.mark.asyncio
    async def test_health_checkin_handler(self, tam_agent):
        """Mock LLM returns checkin JSON. Assert create_draft called."""
        agent, mock_llm, mock_notion, mock_gmail, _chat, _event_bus, _ticket = tam_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_health_checkin_json()}
        )
        # Mock relationship profile
        mock_notion.get_relationship_profile = AsyncMock(return_value={
            "communication_history": [],
        })

        result = await agent.execute(
            {
                "type": "health_checkin",
                "account_id": "acct-001",
                "rep_email": "rep@example.com",
                "health_score": {"score": 85, "rag_status": "Green"},
            },
            {"tenant_id": "test"},
        )

        assert result["task_type"] == "health_checkin"
        assert result["communication_type"] == "health_checkin"
        assert result.get("communication_content") is not None
        assert result.get("draft_id") == "draft-abc-123"
        mock_gmail.create_draft.assert_called_once()
        mock_llm.completion.assert_called_once()


# -- Tests: Handler - Customer Success Review -----------------------------------


class TestTAMCustomerSuccessReview:
    """Tests for customer_success_review handler."""

    @pytest.mark.asyncio
    async def test_customer_success_review_handler(self, tam_agent):
        """Mock LLM returns CSR JSON. Assert create_draft called."""
        agent, mock_llm, _notion, mock_gmail, _chat, _event_bus, _ticket = tam_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_customer_success_review_json()}
        )

        result = await agent.execute(
            {
                "type": "customer_success_review",
                "account_id": "acct-001",
                "rep_email": "rep@example.com",
                "health_score": {"score": 72, "rag_status": "Amber"},
            },
            {"tenant_id": "test"},
        )

        assert result["task_type"] == "customer_success_review"
        assert result["communication_type"] == "customer_success_review"
        assert result.get("communication_content") is not None
        assert result.get("draft_id") == "draft-abc-123"
        mock_gmail.create_draft.assert_called_once()
        mock_llm.completion.assert_called_once()


# -- Tests: Handler - Update Relationship Profile -------------------------------


class TestTAMUpdateRelationshipProfile:
    """Tests for update_relationship_profile handler."""

    @pytest.mark.asyncio
    async def test_update_relationship_profile_handler(self, tam_agent):
        """Mock notion_tam. Assert profile update writes to Notion."""
        agent, _llm, mock_notion, _gmail, _chat, _event_bus, _ticket = tam_agent

        mock_notion.get_relationship_profile = AsyncMock(return_value={
            "account_id": "acct-001",
            "account_name": "Acme Corp",
            "profile_page_id": "page-uuid-123",
        })
        mock_notion.update_relationship_profile = AsyncMock()

        result = await agent.execute(
            {
                "type": "update_relationship_profile",
                "account_id": "acct-001",
                "profile_updates": {
                    "account_name": "Acme Corporation",
                    "customer_environment": ["AWS", "Kubernetes"],
                },
            },
            {"tenant_id": "test"},
        )

        assert result["task_type"] == "update_relationship_profile"
        assert result["confidence"] == "high"
        assert "error" not in result or result.get("error") is None
        # Notion adapter called to update existing profile (has page_id)
        mock_notion.update_relationship_profile.assert_called_once()
        call_args = mock_notion.update_relationship_profile.call_args
        # First positional arg is the page_id
        assert call_args[0][0] == "page-uuid-123"


# -- Tests: Error Handling ------------------------------------------------------


class TestTAMErrorHandling:
    """Tests for error handling and fail-open behavior."""

    @pytest.mark.asyncio
    async def test_unknown_task_type_raises_value_error(self, tam_agent):
        """Unknown task type raises ValueError (TAM follows PM pattern)."""
        agent, _llm, _notion, _gmail, _chat, _event_bus, _ticket = tam_agent

        with pytest.raises(ValueError, match="Unknown task type"):
            await agent.execute(
                {"type": "nonexistent"},
                {"tenant_id": "test"},
            )

    @pytest.mark.asyncio
    async def test_llm_failure_fail_open(self, tam_agent):
        """LLM failure triggers fail-open response, not exception."""
        agent, mock_llm, _notion, _gmail, _chat, _event_bus, _ticket = tam_agent
        mock_llm.completion = AsyncMock(side_effect=Exception("LLM unavailable"))

        # escalation_outreach uses LLM -- should fail-open
        result = await agent.execute(
            {
                "type": "escalation_outreach",
                "account_id": "acct-001",
                "rep_email": "rep@example.com",
                "health_score": {"score": 30, "rag_status": "Red"},
            },
            {"tenant_id": "test"},
        )

        assert isinstance(result, dict)
        assert "error" in result
        assert result["confidence"] == "low"
        assert result["partial"] is True

    @pytest.mark.asyncio
    async def test_escalation_notification_partial_failure(self, tam_agent):
        """One channel (chat_service) raises -> other channels still fire."""
        agent, mock_llm, mock_notion, mock_gmail, mock_chat, mock_event_bus, _ticket = tam_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_escalation_outreach_json()}
        )
        # Make chat_service.send_message raise
        mock_chat.send_message = AsyncMock(side_effect=Exception("Chat API down"))
        # Ensure notion returns page for update
        mock_notion.get_relationship_profile = AsyncMock(return_value={})

        result = await agent.execute(
            {
                "type": "escalation_outreach",
                "account_id": "acct-001",
                "rep_email": "rep@example.com",
                "health_score": {"score": 30, "rag_status": "Red"},
            },
            {"tenant_id": "test", "chat_space": "spaces/test-space"},
        )

        # Should NOT have failed entirely -- still got escalation_outreach result
        assert result["task_type"] == "escalation_outreach"
        assert result.get("communication_content") is not None
        # The escalation result should show per-channel status
        esc_result = result.get("escalation_result")
        assert esc_result is not None
        channels = esc_result.get("channels", {})
        # Event bus should have succeeded
        assert channels.get("event_bus") is True
        # Email alert (create_draft) should have succeeded
        assert channels.get("email_alert") is True
        # Chat alert failed -- but didn't crash the whole operation
        assert channels.get("chat_alert") is False


# -- Tests: Schema Validation ---------------------------------------------------


class TestTAMSchemas:
    """Tests for schema auto-computation and serialization."""

    def test_health_score_result_auto_escalate(self):
        """HealthScoreResult with score=35 auto-sets should_escalate=True."""
        # Low score triggers escalation
        low_result = HealthScoreResult(
            account_id="acct-001",
            score=35,
            rag_status="Red",
        )
        assert low_result.should_escalate is True

        # High score does not trigger escalation
        high_result = HealthScoreResult(
            account_id="acct-002",
            score=85,
            rag_status="Green",
        )
        assert high_result.should_escalate is False

        # Green -> Amber transition triggers escalation
        amber_result = HealthScoreResult(
            account_id="acct-003",
            score=65,
            rag_status="Amber",
            previous_rag="Green",
        )
        assert amber_result.should_escalate is True

        # Non-Red -> Red transition triggers escalation
        red_result = HealthScoreResult(
            account_id="acct-004",
            score=42,
            rag_status="Red",
            previous_rag="Amber",
        )
        assert red_result.should_escalate is True

    def test_handoff_payload_construction(self):
        """TAMHandoffRequest and TAMHandoffResponse serialize/deserialize correctly."""
        request = TAMHandoffRequest(
            handoff_type="health_report",
            account_id="acct-001",
            tenant_id="tenant-abc",
            deal_id="deal-123",
            request_type="health_scan",
        )
        assert request.handoff_type == "health_report"
        assert request.account_id == "acct-001"
        assert request.request_type == "health_scan"

        # Round-trip serialization
        request_dict = request.model_dump()
        request_restored = TAMHandoffRequest.model_validate(request_dict)
        assert request_restored.account_id == request.account_id
        assert request_restored.tenant_id == request.tenant_id

        # TAMHandoffResponse
        health_score = HealthScoreResult(
            account_id="acct-001",
            score=75,
            rag_status="Green",
        )
        response = TAMHandoffResponse(
            handoff_type="health_report",
            health_score=health_score,
            recommended_next_action="Continue monitoring",
            confidence=0.85,
        )
        assert response.handoff_type == "health_report"
        assert response.confidence == 0.85

        # Round-trip serialization
        response_dict = response.model_dump()
        response_restored = TAMHandoffResponse.model_validate(response_dict)
        assert response_restored.recommended_next_action == response.recommended_next_action
        assert response_restored.health_score is not None
        assert response_restored.health_score.score == 75


# -- Tests: GmailService.create_draft Output Structure ---------------------------


class TestGmailCreateDraftOutput:
    """Tests for create_draft output structure used by TAM handlers."""

    @pytest.mark.asyncio
    async def test_create_draft_produces_correct_output_structure(self, tam_agent):
        """GmailService.create_draft returns object with draft_id, message_id, thread_id."""
        agent, mock_llm, _notion, mock_gmail, _chat, _event_bus, _ticket = tam_agent
        mock_llm.completion = AsyncMock(
            return_value={"content": _make_health_checkin_json()}
        )
        _notion.get_relationship_profile = AsyncMock(return_value={
            "communication_history": [],
        })

        result = await agent.execute(
            {
                "type": "health_checkin",
                "account_id": "acct-001",
                "rep_email": "rep@example.com",
            },
            {"tenant_id": "test"},
        )

        # Verify the draft was created and result has draft_id
        assert result["draft_id"] == "draft-abc-123"
        # Verify create_draft was called with an EmailMessage-like object
        mock_gmail.create_draft.assert_called_once()
        call_args = mock_gmail.create_draft.call_args
        email_arg = call_args[0][0]
        # EmailMessage should have to, subject, body_html
        assert hasattr(email_arg, "to") or "to" in dir(email_arg)
