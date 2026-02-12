"""Tests for SalesAgent, NextActionEngine, EscalationManager, and capabilities.

All external dependencies (GmailService, ChatService, RAG pipeline,
ConversationStore, SessionManager, ConversationStateRepository,
QualificationExtractor, NextActionEngine, EscalationManager, LLMService)
are mocked to test the SalesAgent in isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.sales.actions import NextActionEngine
from src.app.agents.sales.agent import SalesAgent
from src.app.agents.sales.capabilities import (
    SALES_AGENT_CAPABILITIES,
    create_sales_registration,
)
from src.app.agents.sales.escalation import EscalationManager
from src.app.agents.sales.schemas import (
    BANTSignals,
    Channel,
    ConversationState,
    DealStage,
    EscalationReport,
    MEDDICSignals,
    NextAction,
    PersonaType,
    QualificationState,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_state(**overrides) -> ConversationState:
    """Create a ConversationState with sensible defaults."""
    defaults = {
        "state_id": str(uuid.uuid4()),
        "tenant_id": "tenant-1",
        "account_id": "acct-1",
        "contact_id": "contact-1",
        "contact_email": "john@example.com",
        "contact_name": "John Doe",
        "deal_stage": DealStage.DISCOVERY,
        "persona_type": PersonaType.MANAGER,
        "interaction_count": 3,
        "last_interaction": datetime.now(timezone.utc) - timedelta(days=1),
        "last_channel": Channel.EMAIL,
        "confidence_score": 0.8,
    }
    defaults.update(overrides)
    return ConversationState(**defaults)


def _make_sales_agent() -> tuple[SalesAgent, dict[str, AsyncMock | MagicMock]]:
    """Create a SalesAgent with all mocked dependencies, returning both."""
    registration = create_sales_registration()

    mocks = {
        "llm_service": AsyncMock(),
        "gmail_service": AsyncMock(),
        "chat_service": AsyncMock(),
        "rag_pipeline": AsyncMock(),
        "conversation_store": AsyncMock(),
        "session_manager": AsyncMock(),
        "state_repository": AsyncMock(),
        "qualification_extractor": AsyncMock(),
        "action_engine": AsyncMock(),
        "escalation_manager": AsyncMock(),
    }

    # Default return values
    mocks["llm_service"].completion = AsyncMock(
        return_value={"content": "Subject: Test\n\nHello, this is a test email."}
    )
    mocks["gmail_service"].send_email = AsyncMock(
        return_value=MagicMock(message_id="msg-1", thread_id="thread-1")
    )
    mocks["chat_service"].send_message = AsyncMock(
        return_value=MagicMock(message_name="spaces/123/messages/456", create_time="2026-01-01T00:00:00Z")
    )
    mocks["rag_pipeline"].run = AsyncMock(
        return_value=MagicMock(answer="Product info here", sources=[])
    )
    mocks["conversation_store"].search_conversations = AsyncMock(
        return_value=[]
    )
    mocks["state_repository"].get_state = AsyncMock(
        return_value=_make_state()
    )
    mocks["state_repository"].save_state = AsyncMock(
        side_effect=lambda s: s
    )
    mocks["qualification_extractor"].extract_signals = AsyncMock(
        return_value=QualificationState()
    )
    mocks["action_engine"].recommend_actions = AsyncMock(
        return_value=[NextAction(action_type="follow_up", description="Follow up")]
    )
    mocks["escalation_manager"].evaluate_escalation = AsyncMock(
        return_value=None
    )
    mocks["escalation_manager"].publish_escalation = AsyncMock()

    agent = SalesAgent(
        registration=registration,
        llm_service=mocks["llm_service"],
        gmail_service=mocks["gmail_service"],
        chat_service=mocks["chat_service"],
        rag_pipeline=mocks["rag_pipeline"],
        conversation_store=mocks["conversation_store"],
        session_manager=mocks["session_manager"],
        state_repository=mocks["state_repository"],
        qualification_extractor=mocks["qualification_extractor"],
        action_engine=mocks["action_engine"],
        escalation_manager=mocks["escalation_manager"],
    )
    return agent, mocks


# ── Capability Registration Tests ───────────────────────────────────────────


class TestCapabilities:
    """Tests for agent capability declarations and registration."""

    def test_sales_agent_capabilities_count(self):
        """SALES_AGENT_CAPABILITIES has exactly 5 capabilities."""
        assert len(SALES_AGENT_CAPABILITIES) == 5

    def test_sales_agent_capabilities_names(self):
        """All 5 expected capabilities are present."""
        names = {c.name for c in SALES_AGENT_CAPABILITIES}
        assert names == {
            "email_outreach",
            "chat_messaging",
            "qualification",
            "next_action",
            "escalation",
        }

    def test_create_sales_registration_returns_valid(self):
        """create_sales_registration returns AgentRegistration with 5 capabilities."""
        reg = create_sales_registration()
        assert reg.agent_id == "sales_agent"
        assert reg.name == "Sales Agent"
        assert len(reg.capabilities) == 5
        assert reg.backup_agent_id is None
        assert "sales" in reg.tags
        assert "meddic" in reg.tags
        assert reg.max_concurrent_tasks == 3


# ── SalesAgent Task Routing Tests ───────────────────────────────────────────


class TestSalesAgentRouting:
    """Tests for execute() task routing."""

    @pytest.mark.asyncio
    async def test_execute_routes_send_email(self):
        """execute() routes 'send_email' to _handle_send_email."""
        agent, mocks = _make_sales_agent()
        task = {
            "type": "send_email",
            "account_id": "acct-1",
            "contact_id": "contact-1",
            "description": "Send outreach email",
        }
        result = await agent.execute(task, {"tenant_id": "tenant-1"})
        assert result["status"] == "sent"
        assert "message_id" in result

    @pytest.mark.asyncio
    async def test_execute_routes_send_chat(self):
        """execute() routes 'send_chat' to _handle_send_chat."""
        agent, mocks = _make_sales_agent()
        task = {
            "type": "send_chat",
            "account_id": "acct-1",
            "contact_id": "contact-1",
            "space_name": "spaces/test",
            "description": "Send chat message",
        }
        result = await agent.execute(task, {"tenant_id": "tenant-1"})
        assert result["status"] == "sent"
        assert "message_name" in result

    @pytest.mark.asyncio
    async def test_execute_routes_process_reply(self):
        """execute() routes 'process_reply' to _handle_process_reply."""
        agent, mocks = _make_sales_agent()
        task = {
            "type": "process_reply",
            "account_id": "acct-1",
            "contact_id": "contact-1",
            "reply_text": "We have a budget of $50k",
        }
        result = await agent.execute(task, {"tenant_id": "tenant-1"})
        assert result["status"] == "processed"
        assert "qualification_update" in result
        assert "next_actions" in result

    @pytest.mark.asyncio
    async def test_execute_routes_recommend_action(self):
        """execute() routes 'recommend_action' to _handle_recommend_action."""
        agent, mocks = _make_sales_agent()
        task = {
            "type": "recommend_action",
            "account_id": "acct-1",
            "contact_id": "contact-1",
        }
        result = await agent.execute(task, {"tenant_id": "tenant-1"})
        assert "next_actions" in result

    @pytest.mark.asyncio
    async def test_execute_raises_for_unknown_type(self):
        """execute() raises ValueError for unknown task type."""
        agent, _ = _make_sales_agent()
        with pytest.raises(ValueError, match="Unknown task type"):
            await agent.execute(
                {"type": "unknown_task"},
                {"tenant_id": "tenant-1"},
            )


# ── SalesAgent Handler Tests ───────────────────────────────────────────────


class TestSalesAgentHandlers:
    """Tests for individual handler behavior."""

    @pytest.mark.asyncio
    async def test_send_email_calls_gmail_service(self):
        """_handle_send_email calls gmail_service.send_email with EmailMessage."""
        agent, mocks = _make_sales_agent()
        task = {
            "type": "send_email",
            "account_id": "acct-1",
            "contact_id": "contact-1",
            "description": "Outreach",
        }
        await agent.execute(task, {"tenant_id": "tenant-1"})
        mocks["gmail_service"].send_email.assert_called_once()
        call_args = mocks["gmail_service"].send_email.call_args
        email_msg = call_args[0][0]
        assert hasattr(email_msg, "to")
        assert hasattr(email_msg, "subject")

    @pytest.mark.asyncio
    async def test_send_email_updates_state(self):
        """_handle_send_email increments interaction_count and sets last_channel."""
        agent, mocks = _make_sales_agent()
        task = {
            "type": "send_email",
            "account_id": "acct-1",
            "contact_id": "contact-1",
            "description": "Outreach",
        }
        await agent.execute(task, {"tenant_id": "tenant-1"})
        # save_state should have been called with updated state
        mocks["state_repository"].save_state.assert_called_once()
        saved_state = mocks["state_repository"].save_state.call_args[0][0]
        assert saved_state.interaction_count == 4  # was 3, incremented to 4
        assert saved_state.last_channel == Channel.EMAIL
        assert saved_state.last_interaction is not None

    @pytest.mark.asyncio
    async def test_process_reply_extracts_qualification(self):
        """_handle_process_reply calls qualification_extractor.extract_signals."""
        agent, mocks = _make_sales_agent()
        task = {
            "type": "process_reply",
            "account_id": "acct-1",
            "contact_id": "contact-1",
            "reply_text": "Our budget is around $100k and we need this by Q2",
        }
        await agent.execute(task, {"tenant_id": "tenant-1"})
        mocks["qualification_extractor"].extract_signals.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_reply_gets_next_actions(self):
        """_handle_process_reply calls action_engine.recommend_actions."""
        agent, mocks = _make_sales_agent()
        task = {
            "type": "process_reply",
            "account_id": "acct-1",
            "contact_id": "contact-1",
            "reply_text": "Let's discuss pricing",
        }
        await agent.execute(task, {"tenant_id": "tenant-1"})
        mocks["action_engine"].recommend_actions.assert_called_once()

    @pytest.mark.asyncio
    async def test_escalation_checked_after_send_email(self):
        """Escalation is evaluated after send_email."""
        agent, mocks = _make_sales_agent()
        task = {
            "type": "send_email",
            "account_id": "acct-1",
            "contact_id": "contact-1",
            "description": "Send email",
        }
        await agent.execute(task, {"tenant_id": "tenant-1"})
        mocks["escalation_manager"].evaluate_escalation.assert_called_once()

    @pytest.mark.asyncio
    async def test_escalation_checked_after_process_reply(self):
        """Escalation is evaluated after process_reply."""
        agent, mocks = _make_sales_agent()
        task = {
            "type": "process_reply",
            "account_id": "acct-1",
            "contact_id": "contact-1",
            "reply_text": "I need to speak to a real person",
        }
        await agent.execute(task, {"tenant_id": "tenant-1"})
        mocks["escalation_manager"].evaluate_escalation.assert_called_once()

    @pytest.mark.asyncio
    async def test_escalation_published_when_triggered(self):
        """When escalation triggers, publish_escalation is called."""
        agent, mocks = _make_sales_agent()
        escalation_report = EscalationReport(
            escalation_id="esc-1",
            tenant_id="tenant-1",
            account_id="acct-1",
            contact_id="contact-1",
            contact_name="John",
            deal_stage=DealStage.NEGOTIATION,
            escalation_trigger="customer_request",
            confidence_score=0.5,
            account_context="context",
            what_agent_tried="tried email",
            why_escalating="customer asked",
            recommended_next_action="call them",
        )
        mocks["escalation_manager"].evaluate_escalation = AsyncMock(
            return_value=escalation_report
        )
        task = {
            "type": "send_email",
            "account_id": "acct-1",
            "contact_id": "contact-1",
            "description": "Send email",
        }
        result = await agent.execute(task, {"tenant_id": "tenant-1"})
        mocks["escalation_manager"].publish_escalation.assert_called_once()
        assert result["escalation"] is not None


# ── NextActionEngine Tests ──────────────────────────────────────────────────


class TestNextActionEngine:
    """Tests for rule-based and fallback action recommendation."""

    @pytest.mark.asyncio
    async def test_escalated_state_returns_escalate_action(self):
        """Escalated state returns urgent escalate action."""
        engine = NextActionEngine(llm_service=AsyncMock())
        state = _make_state(escalated=True)
        actions = await engine.recommend_actions(state)
        assert len(actions) == 1
        assert actions[0].action_type == "escalate"
        assert actions[0].priority == "urgent"

    @pytest.mark.asyncio
    async def test_closed_won_returns_wait_action(self):
        """CLOSED_WON state returns wait action."""
        engine = NextActionEngine(llm_service=AsyncMock())
        state = _make_state(deal_stage=DealStage.CLOSED_WON)
        actions = await engine.recommend_actions(state)
        assert len(actions) == 1
        assert actions[0].action_type == "wait"

    @pytest.mark.asyncio
    async def test_no_interactions_returns_initial_outreach(self):
        """Zero interactions returns send_email for initial outreach."""
        engine = NextActionEngine(llm_service=AsyncMock())
        state = _make_state(interaction_count=0)
        actions = await engine.recommend_actions(state)
        assert len(actions) == 1
        assert actions[0].action_type == "send_email"
        assert actions[0].priority == "high"

    @pytest.mark.asyncio
    async def test_stale_deal_returns_follow_up(self):
        """Deal with 10+ days inactivity returns follow_up action."""
        engine = NextActionEngine(llm_service=AsyncMock())
        state = _make_state(
            last_interaction=datetime.now(timezone.utc) - timedelta(days=10),
            deal_stage=DealStage.QUALIFICATION,
        )
        actions = await engine.recommend_actions(state)
        assert len(actions) == 1
        assert actions[0].action_type == "follow_up"
        assert actions[0].priority == "high"

    @pytest.mark.asyncio
    async def test_low_qualification_returns_discovery_email(self):
        """Low qualification completion returns discovery email."""
        engine = NextActionEngine(llm_service=AsyncMock())
        state = _make_state(
            deal_stage=DealStage.DISCOVERY,
            qualification=QualificationState(),  # 0% completion
        )
        actions = await engine.recommend_actions(state)
        assert len(actions) == 1
        assert actions[0].action_type == "send_email"
        assert "not yet identified" in actions[0].description


# ── EscalationManager Tests ─────────────────────────────────────────────────


class TestEscalationManager:
    """Tests for escalation trigger evaluation."""

    @pytest.mark.asyncio
    async def test_no_triggers_returns_none(self):
        """No triggers returns None."""
        manager = EscalationManager(
            event_bus=AsyncMock(), llm_service=AsyncMock()
        )
        state = _make_state(confidence_score=0.9)
        result = await manager.evaluate_escalation(state, "Hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_low_confidence_triggers(self):
        """Confidence below 0.7 triggers escalation."""
        llm_mock = AsyncMock()
        llm_mock.completion = AsyncMock(return_value={"content": "Call them."})
        manager = EscalationManager(
            event_bus=AsyncMock(), llm_service=llm_mock
        )
        state = _make_state(confidence_score=0.5)
        result = await manager.evaluate_escalation(state, "Normal message")
        assert result is not None
        assert result.escalation_trigger == "confidence_low"

    @pytest.mark.asyncio
    async def test_customer_request_triggers(self):
        """Customer requesting human triggers escalation."""
        llm_mock = AsyncMock()
        llm_mock.completion = AsyncMock(return_value={"content": "Call them."})
        manager = EscalationManager(
            event_bus=AsyncMock(), llm_service=llm_mock
        )
        state = _make_state(confidence_score=0.9)
        result = await manager.evaluate_escalation(
            state, "I would like to speak to someone about this"
        )
        assert result is not None
        assert result.escalation_trigger == "customer_request"

    @pytest.mark.asyncio
    async def test_high_stakes_triggers_in_negotiation(self):
        """High-stakes keywords in NEGOTIATION stage trigger escalation."""
        llm_mock = AsyncMock()
        llm_mock.completion = AsyncMock(return_value={"content": "Call them."})
        manager = EscalationManager(
            event_bus=AsyncMock(), llm_service=llm_mock
        )
        state = _make_state(
            deal_stage=DealStage.NEGOTIATION,
            confidence_score=0.9,
        )
        result = await manager.evaluate_escalation(
            state, "Let's discuss pricing and contract terms"
        )
        assert result is not None
        assert result.escalation_trigger == "high_stakes"

    @pytest.mark.asyncio
    async def test_high_stakes_does_not_trigger_in_discovery(self):
        """High-stakes keywords in DISCOVERY stage do NOT trigger."""
        manager = EscalationManager(
            event_bus=AsyncMock(), llm_service=AsyncMock()
        )
        state = _make_state(
            deal_stage=DealStage.DISCOVERY,
            confidence_score=0.9,
        )
        result = await manager.evaluate_escalation(
            state, "Let's discuss pricing"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_complexity_triggers(self):
        """Complex deal with 3+ criteria and multiple stakeholders triggers."""
        llm_mock = AsyncMock()
        llm_mock.completion = AsyncMock(return_value={"content": "Call them."})
        manager = EscalationManager(
            event_bus=AsyncMock(), llm_service=llm_mock
        )
        qualification = QualificationState(
            bant=BANTSignals(authority_identified=True),
            meddic=MEDDICSignals(
                decision_criteria=["security", "scalability", "pricing"],
                decision_criteria_identified=True,
                economic_buyer_identified=True,
                champion_identified=True,
            ),
        )
        state = _make_state(
            confidence_score=0.9,
            qualification=qualification,
        )
        result = await manager.evaluate_escalation(state, "Let me check")
        assert result is not None
        assert result.escalation_trigger == "complexity"
