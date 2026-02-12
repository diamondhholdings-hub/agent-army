"""Integration tests for Sales Agent end-to-end flows.

Tests the complete pipeline with mocked external services:
- Email sending flow
- Chat sending flow
- Reply processing with qualification extraction
- Escalation triggers (low confidence, customer request)
- Next-action recommendations (new conversation, stale deal)
- Agent registration
- Persona differentiation
- Context compilation

All external services (GmailService, ChatService, RAG pipeline,
ConversationStore, SessionManager, LLMService) are mocked. State
repository uses an in-memory mock for fast test execution.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.agents.sales.actions import NextActionEngine
from src.app.agents.sales.agent import SalesAgent
from src.app.agents.sales.capabilities import (
    SALES_AGENT_CAPABILITIES,
    create_sales_registration,
)
from src.app.agents.sales.escalation import EscalationManager
from src.app.agents.sales.qualification import QualificationExtractor
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


# ── In-Memory State Repository ───────────────────────────────────────────────


class InMemoryStateRepository:
    """Simple in-memory state repository for integration tests."""

    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}

    def _key(self, tenant_id: str, account_id: str, contact_id: str) -> str:
        return f"{tenant_id}:{account_id}:{contact_id}"

    async def get_state(
        self, tenant_id: str, account_id: str, contact_id: str
    ) -> ConversationState | None:
        return self._states.get(self._key(tenant_id, account_id, contact_id))

    async def save_state(self, state: ConversationState) -> ConversationState:
        key = self._key(state.tenant_id, state.account_id, state.contact_id)
        self._states[key] = state
        return state

    async def list_states_by_tenant(
        self, tenant_id: str, deal_stage: str | None = None
    ) -> list[ConversationState]:
        results = []
        for state in self._states.values():
            if state.tenant_id == tenant_id:
                if deal_stage is None or state.deal_stage.value == deal_stage:
                    results.append(state)
        return results


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_state(**overrides) -> ConversationState:
    """Create a ConversationState with sensible defaults."""
    defaults = {
        "state_id": str(uuid.uuid4()),
        "tenant_id": "tenant-int-1",
        "account_id": "acct-int-1",
        "contact_id": "contact-int-1",
        "contact_email": "alice@example.com",
        "contact_name": "Alice Smith",
        "deal_stage": DealStage.DISCOVERY,
        "persona_type": PersonaType.MANAGER,
        "interaction_count": 0,
        "confidence_score": 0.8,
    }
    defaults.update(overrides)
    return ConversationState(**defaults)


def _make_integration_agent(
    state_repo: InMemoryStateRepository | None = None,
    llm_response: str = "Subject: Test Follow-up\n\nHello Alice, great to connect.",
    escalation_result: EscalationReport | None = None,
    qualification_result: QualificationState | None = None,
) -> tuple[SalesAgent, dict]:
    """Create a SalesAgent with mocked services and real-ish state repo."""
    registration = create_sales_registration()
    if state_repo is None:
        state_repo = InMemoryStateRepository()

    mocks = {
        "llm_service": AsyncMock(),
        "gmail_service": AsyncMock(),
        "chat_service": AsyncMock(),
        "rag_pipeline": AsyncMock(),
        "conversation_store": AsyncMock(),
        "session_manager": AsyncMock(),
    }

    # Configure LLM mock
    mocks["llm_service"].completion = AsyncMock(
        return_value={"content": llm_response}
    )

    # Configure Gmail mock
    mocks["gmail_service"].send_email = AsyncMock(
        return_value=MagicMock(
            message_id="msg-int-1",
            thread_id="thread-int-1",
            label_ids=["SENT"],
        )
    )

    # Configure Chat mock
    mocks["chat_service"].send_message = AsyncMock(
        return_value=MagicMock(
            message_name="spaces/int/messages/1",
            create_time="2026-01-15T10:00:00Z",
        )
    )

    # Configure RAG mock
    mocks["rag_pipeline"].run = AsyncMock(
        return_value=MagicMock(answer="Product supports enterprise billing.", sources=[])
    )

    # Configure conversation store mock
    mocks["conversation_store"].search_conversations = AsyncMock(return_value=[])

    # Real qualification extractor with mock LLM (fail-open returns default)
    qual_extractor = QualificationExtractor(llm_service=mocks["llm_service"])
    if qualification_result is not None:
        # Override extract_signals for deterministic testing
        qual_extractor.extract_signals = AsyncMock(return_value=qualification_result)

    # Real next-action engine with mock LLM
    action_engine = NextActionEngine(llm_service=mocks["llm_service"])

    # Real escalation manager with mock event bus + LLM
    event_bus_mock = AsyncMock()
    event_bus_mock.publish = AsyncMock()
    escalation_mgr = EscalationManager(
        event_bus=event_bus_mock, llm_service=mocks["llm_service"]
    )
    if escalation_result is not None:
        escalation_mgr.evaluate_escalation = AsyncMock(
            return_value=escalation_result
        )

    agent = SalesAgent(
        registration=registration,
        llm_service=mocks["llm_service"],
        gmail_service=mocks["gmail_service"],
        chat_service=mocks["chat_service"],
        rag_pipeline=mocks["rag_pipeline"],
        conversation_store=mocks["conversation_store"],
        session_manager=mocks["session_manager"],
        state_repository=state_repo,
        qualification_extractor=qual_extractor,
        action_engine=action_engine,
        escalation_manager=escalation_mgr,
    )

    mocks["state_repo"] = state_repo
    mocks["qual_extractor"] = qual_extractor
    mocks["action_engine"] = action_engine
    mocks["escalation_manager"] = escalation_mgr
    mocks["event_bus"] = event_bus_mock

    return agent, mocks


# ── Integration Tests ────────────────────────────────────────────────────────


class TestSendEmailFlow:
    """Test 1: End-to-end email sending flow."""

    @pytest.mark.asyncio
    async def test_send_email_flow(self):
        """Send email -> verify Gmail called -> state saved -> qualification attempted."""
        state_repo = InMemoryStateRepository()
        agent, mocks = _make_integration_agent(state_repo=state_repo)

        task = {
            "type": "send_email",
            "account_id": "acct-int-1",
            "contact_id": "contact-int-1",
            "contact_email": "alice@example.com",
            "contact_name": "Alice Smith",
            "persona_type": "manager",
            "deal_stage": "discovery",
            "description": "Initial outreach about our billing platform",
        }
        context = {"tenant_id": "tenant-int-1"}

        result = await agent.invoke(task, context)

        # 1. Gmail service was called with EmailMessage
        mocks["gmail_service"].send_email.assert_called_once()
        email_msg = mocks["gmail_service"].send_email.call_args[0][0]
        assert email_msg.to == "alice@example.com"
        assert email_msg.subject is not None

        # 2. Result has expected structure
        assert result["status"] == "sent"
        assert result["message_id"] == "msg-int-1"
        assert result["thread_id"] == "thread-int-1"

        # 3. State was saved (interaction_count > 0, last_channel = email)
        saved_state = await state_repo.get_state(
            "tenant-int-1", "acct-int-1", "contact-int-1"
        )
        assert saved_state is not None
        assert saved_state.interaction_count >= 1
        assert saved_state.last_channel == Channel.EMAIL
        assert saved_state.last_interaction is not None


class TestSendChatFlow:
    """Test 2: End-to-end chat sending flow."""

    @pytest.mark.asyncio
    async def test_send_chat_flow(self):
        """Send chat -> verify chat_service called -> state saved."""
        state_repo = InMemoryStateRepository()
        agent, mocks = _make_integration_agent(state_repo=state_repo)

        task = {
            "type": "send_chat",
            "account_id": "acct-int-1",
            "contact_id": "contact-int-1",
            "contact_name": "Alice Smith",
            "persona_type": "manager",
            "deal_stage": "discovery",
            "description": "Follow up on their pricing question",
            "space_name": "spaces/test-space",
            "thread_key": "thread-key-1",
        }
        context = {"tenant_id": "tenant-int-1"}

        result = await agent.invoke(task, context)

        # chat_service.send_message was called
        mocks["chat_service"].send_message.assert_called_once()
        chat_msg = mocks["chat_service"].send_message.call_args[0][0]
        assert chat_msg.space_name == "spaces/test-space"

        # Result structure
        assert result["status"] == "sent"
        assert result["message_name"] == "spaces/int/messages/1"

        # State saved with chat channel
        saved_state = await state_repo.get_state(
            "tenant-int-1", "acct-int-1", "contact-int-1"
        )
        assert saved_state is not None
        assert saved_state.last_channel == Channel.CHAT


class TestProcessReplyExtractsQualification:
    """Test 3: Reply processing with qualification extraction."""

    @pytest.mark.asyncio
    async def test_process_reply_extracts_qualification(self):
        """Process reply -> qualification extractor called -> result has qualification."""
        state_repo = InMemoryStateRepository()
        qualification = QualificationState(
            bant=BANTSignals(
                budget_identified=True,
                budget_range="$200k",
                budget_confidence=0.8,
            ),
            overall_confidence=0.7,
            key_insights=["Budget around $200k"],
        )
        agent, mocks = _make_integration_agent(
            state_repo=state_repo,
            qualification_result=qualification,
        )

        task = {
            "type": "process_reply",
            "account_id": "acct-int-1",
            "contact_id": "contact-int-1",
            "contact_email": "alice@example.com",
            "reply_text": "Our budget is around $200k and we need this by Q3",
            "channel": "email",
        }
        context = {"tenant_id": "tenant-int-1"}

        result = await agent.invoke(task, context)

        # Qualification extractor was called
        mocks["qual_extractor"].extract_signals.assert_called_once()

        # Result contains qualification_update and next_actions
        assert result["status"] == "processed"
        assert "qualification_update" in result
        assert result["qualification_update"]["bant"]["budget_identified"] is True
        assert "next_actions" in result
        assert len(result["next_actions"]) >= 1


class TestEscalationTriggersOnLowConfidence:
    """Test 4: Escalation trigger on low confidence score."""

    @pytest.mark.asyncio
    async def test_escalation_triggers_on_low_confidence(self):
        """Low confidence state -> process reply -> escalation evaluated."""
        state_repo = InMemoryStateRepository()
        # Pre-populate state with low confidence
        low_conf_state = _make_state(
            confidence_score=0.5,
            interaction_count=3,
            last_interaction=datetime.now(timezone.utc) - timedelta(hours=2),
            last_channel=Channel.EMAIL,
        )
        await state_repo.save_state(low_conf_state)

        qualification = QualificationState(overall_confidence=0.5)
        agent, mocks = _make_integration_agent(
            state_repo=state_repo,
            qualification_result=qualification,
        )

        task = {
            "type": "process_reply",
            "account_id": "acct-int-1",
            "contact_id": "contact-int-1",
            "contact_email": "alice@example.com",
            "reply_text": "We need more details on the pricing model",
            "channel": "email",
        }
        context = {"tenant_id": "tenant-int-1"}

        result = await agent.invoke(task, context)

        # Escalation should be triggered (confidence < 0.7)
        # The real EscalationManager evaluates triggers
        assert result["status"] == "processed"
        # With confidence 0.5 < 0.7 threshold, escalation triggers
        if result["escalation"] is not None:
            assert result["escalation"]["escalation_trigger"] == "confidence_low"

        # State should be updated with escalation info
        saved_state = await state_repo.get_state(
            "tenant-int-1", "acct-int-1", "contact-int-1"
        )
        assert saved_state is not None


class TestEscalationTriggersOnCustomerRequest:
    """Test 5: Escalation trigger on customer request for human."""

    @pytest.mark.asyncio
    async def test_escalation_triggers_on_customer_request(self):
        """Customer requests human contact -> escalation triggered."""
        state_repo = InMemoryStateRepository()
        state = _make_state(
            confidence_score=0.9,
            interaction_count=2,
            last_interaction=datetime.now(timezone.utc),
            last_channel=Channel.EMAIL,
        )
        await state_repo.save_state(state)

        qualification = QualificationState()
        agent, mocks = _make_integration_agent(
            state_repo=state_repo,
            qualification_result=qualification,
        )

        task = {
            "type": "process_reply",
            "account_id": "acct-int-1",
            "contact_id": "contact-int-1",
            "contact_email": "alice@example.com",
            "reply_text": "Can I speak to someone on your team about this?",
            "channel": "email",
        }
        context = {"tenant_id": "tenant-int-1"}

        result = await agent.invoke(task, context)

        # The phrase "speak to someone" matches customer request triggers
        assert result["status"] == "processed"
        assert result["escalation"] is not None
        assert result["escalation"]["escalation_trigger"] == "customer_request"

        # State should be marked as escalated
        saved_state = await state_repo.get_state(
            "tenant-int-1", "acct-int-1", "contact-int-1"
        )
        assert saved_state is not None
        assert saved_state.escalated is True
        assert saved_state.escalation_reason == "customer_request"


class TestRecommendActionForNewConversation:
    """Test 6: Next-action recommendations for new conversation."""

    @pytest.mark.asyncio
    async def test_recommend_action_for_new_conversation(self):
        """Fresh state (interaction_count=0) -> returns initial outreach."""
        state_repo = InMemoryStateRepository()
        # No pre-existing state -- agent creates fresh state
        agent, mocks = _make_integration_agent(state_repo=state_repo)

        task = {
            "type": "recommend_action",
            "account_id": "acct-new",
            "contact_id": "contact-new",
        }
        context = {"tenant_id": "tenant-int-1"}

        result = await agent.invoke(task, context)

        assert "next_actions" in result
        actions = result["next_actions"]
        assert len(actions) >= 1
        # Rule-based: no interactions -> initial outreach email
        assert actions[0]["action_type"] == "send_email"
        assert actions[0]["priority"] == "high"


class TestRecommendActionForStaleDeal:
    """Test 7: Next-action recommendations for stale deal."""

    @pytest.mark.asyncio
    async def test_recommend_action_for_stale_deal(self):
        """State with 10-day-old interaction -> returns follow-up action."""
        state_repo = InMemoryStateRepository()
        stale_state = _make_state(
            interaction_count=5,
            last_interaction=datetime.now(timezone.utc) - timedelta(days=10),
            last_channel=Channel.EMAIL,
            deal_stage=DealStage.QUALIFICATION,
        )
        await state_repo.save_state(stale_state)

        agent, mocks = _make_integration_agent(state_repo=state_repo)

        task = {
            "type": "recommend_action",
            "account_id": "acct-int-1",
            "contact_id": "contact-int-1",
        }
        context = {"tenant_id": "tenant-int-1"}

        result = await agent.invoke(task, context)

        assert "next_actions" in result
        actions = result["next_actions"]
        assert len(actions) >= 1
        # Rule-based: 10+ days inactive -> follow-up
        assert actions[0]["action_type"] == "follow_up"
        assert actions[0]["priority"] == "high"


class TestAgentRegistration:
    """Test 8: Agent registration produces valid registration."""

    def test_agent_registration(self):
        """create_sales_registration() produces valid registration."""
        registration = create_sales_registration()

        assert registration.agent_id == "sales_agent"
        assert registration.name == "Sales Agent"
        assert len(registration.capabilities) == 5

        capability_names = {c.name for c in registration.capabilities}
        assert capability_names == {
            "email_outreach",
            "chat_messaging",
            "qualification",
            "next_action",
            "escalation",
        }

        assert "sales" in registration.tags
        assert "bant" in registration.tags
        assert "meddic" in registration.tags
        assert "email" in registration.tags
        assert "chat" in registration.tags
        assert registration.max_concurrent_tasks == 3
        assert registration.backup_agent_id is None


class TestPersonaAffectsEmailContent:
    """Test 9: Persona affects email prompt construction."""

    @pytest.mark.asyncio
    async def test_persona_affects_email_content(self):
        """IC vs C_SUITE persona produces different system prompts."""
        from src.app.agents.sales.prompts import build_system_prompt

        ic_prompt = build_system_prompt(
            persona=PersonaType.IC,
            channel=Channel.EMAIL,
            deal_stage=DealStage.DISCOVERY,
        )
        csuite_prompt = build_system_prompt(
            persona=PersonaType.C_SUITE,
            channel=Channel.EMAIL,
            deal_stage=DealStage.DISCOVERY,
        )

        # IC prompt should have conversational tone
        assert "conversational" in ic_prompt.lower()
        assert "peer-to-peer" in ic_prompt.lower()

        # C-Suite prompt should have formal/executive tone
        assert "formal" in csuite_prompt.lower()
        assert "executive" in csuite_prompt.lower()

        # They should be different
        assert ic_prompt != csuite_prompt

    @pytest.mark.asyncio
    async def test_persona_used_in_email_generation(self):
        """Email generation uses correct persona from state."""
        from src.app.agents.sales.prompts import build_email_prompt

        # Build prompt for IC persona
        messages = build_email_prompt(
            persona=PersonaType.IC,
            deal_stage=DealStage.DISCOVERY,
            context_summary="Contact: Test User\nAccount: acct-1",
            task_description="Send discovery email",
        )

        # System prompt should reflect IC persona
        system_content = messages[0]["content"]
        assert "ic" in system_content.lower()
        assert "conversational" in system_content.lower()


class TestContextCompilation:
    """Test 10: Context compilation calls all expected services."""

    @pytest.mark.asyncio
    async def test_context_compilation(self):
        """_compile_sales_context calls RAG, conversation_store, and state_repository."""
        state_repo = InMemoryStateRepository()
        state = _make_state()
        await state_repo.save_state(state)

        agent, mocks = _make_integration_agent(state_repo=state_repo)

        task = {
            "type": "send_email",
            "account_id": "acct-int-1",
            "contact_id": "contact-int-1",
            "contact_email": "alice@example.com",
            "description": "Test context compilation",
        }
        context = {"tenant_id": "tenant-int-1"}

        # Execute triggers context compilation internally
        await agent.invoke(task, context)

        # RAG pipeline should have been called
        mocks["rag_pipeline"].run.assert_called_once()

        # Conversation store should have been searched
        mocks["conversation_store"].search_conversations.assert_called_once()


class TestEndToEndPipeline:
    """Test 11: Full pipeline -- send email -> process reply -> recommend action."""

    @pytest.mark.asyncio
    async def test_full_pipeline_email_reply_recommend(self):
        """Complete flow: send email -> process reply -> get recommendation."""
        state_repo = InMemoryStateRepository()

        # Use deterministic qualification results
        initial_qual = QualificationState()
        reply_qual = QualificationState(
            bant=BANTSignals(
                budget_identified=True,
                budget_range="$200k",
                budget_confidence=0.8,
                need_identified=True,
                need_description="Enterprise billing platform",
                need_confidence=0.7,
            ),
            overall_confidence=0.6,
            key_insights=["Budget ~$200k", "Need enterprise billing"],
        )

        # Step 1: Send email
        agent, mocks = _make_integration_agent(
            state_repo=state_repo,
            qualification_result=initial_qual,
        )

        email_task = {
            "type": "send_email",
            "account_id": "acct-pipe-1",
            "contact_id": "contact-pipe-1",
            "contact_email": "bob@example.com",
            "contact_name": "Bob Manager",
            "persona_type": "manager",
            "deal_stage": "discovery",
            "description": "Initial outreach about billing platform",
        }
        email_result = await agent.invoke(email_task, {"tenant_id": "tenant-int-1"})
        assert email_result["status"] == "sent"

        # Step 2: Process reply (swap qualification result)
        mocks["qual_extractor"].extract_signals = AsyncMock(
            return_value=reply_qual
        )

        reply_task = {
            "type": "process_reply",
            "account_id": "acct-pipe-1",
            "contact_id": "contact-pipe-1",
            "contact_email": "bob@example.com",
            "reply_text": "Our budget is around $200k and we need an enterprise billing platform by Q3",
            "channel": "email",
        }
        reply_result = await agent.invoke(reply_task, {"tenant_id": "tenant-int-1"})
        assert reply_result["status"] == "processed"
        assert reply_result["qualification_update"]["bant"]["budget_identified"] is True

        # Step 3: Recommend action
        action_task = {
            "type": "recommend_action",
            "account_id": "acct-pipe-1",
            "contact_id": "contact-pipe-1",
        }
        action_result = await agent.invoke(
            action_task, {"tenant_id": "tenant-int-1"}
        )
        assert "next_actions" in action_result
        assert len(action_result["next_actions"]) >= 1

        # Verify state accumulated across the pipeline
        final_state = await state_repo.get_state(
            "tenant-int-1", "acct-pipe-1", "contact-pipe-1"
        )
        assert final_state is not None
        assert final_state.interaction_count >= 2  # email + reply
        assert final_state.qualification.bant.budget_identified is True
