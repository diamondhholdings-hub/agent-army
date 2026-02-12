"""Integration tests for QBS pipeline through SalesAgent.

Tests the full QBS flow: engine analysis -> prompt injection -> state
persistence -> expansion detection -> context summary enrichment.

All external services (LLM, Gmail, Chat, RAG, ConversationStore,
SessionManager) are mocked. QBS engine and expansion detector use
mock implementations returning predictable recommendations without
LLM calls. State repository uses InMemoryStateRepository for fast
test execution.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.agents.sales.agent import SalesAgent
from src.app.agents.sales.capabilities import create_sales_registration
from src.app.agents.sales.escalation import EscalationManager
from src.app.agents.sales.qbs.expansion import AccountExpansionDetector
from src.app.agents.sales.qbs.schemas import (
    EngagementSignal,
    ExpansionTrigger,
    PainDepthLevel,
    PainTopic,
    QBSQuestionRecommendation,
    QBSQuestionType,
)
from src.app.agents.sales.qualification import QualificationExtractor
from src.app.agents.sales.schemas import (
    Channel,
    ConversationState,
    DealStage,
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


# ── Mock QBS Components ───────────────────────────────────────────────────────


class MockQBSEngine:
    """Mock QBS engine returning predictable recommendations."""

    async def analyze_and_recommend(
        self,
        conversation_state,
        latest_message,
        conversation_history=None,
    ):
        return QBSQuestionRecommendation(
            question_type=QBSQuestionType.PAIN_FUNNEL,
            meddic_bant_target="need",
            voss_delivery="calibrated_question",
            suggested_question=(
                "What challenges are you facing with your current approach?"
            ),
            rationale="First interaction discovery",
            engagement_signal=EngagementSignal.FACTUAL,
            pain_depth=PainDepthLevel.SURFACE,
            should_probe_deeper=True,
        )


class MockExpansionDetector:
    """Mock expansion detector returning predictable triggers."""

    async def detect_expansion_triggers(
        self,
        conversation_text,
        existing_contacts,
        interaction_count=0,
    ):
        if "boss" in conversation_text.lower() or "team" in conversation_text.lower():
            return [
                ExpansionTrigger(
                    mentioned_name_or_role="their boss",
                    context_quote="My boss mentioned this last week",
                    relationship_to_contact="manager",
                    expansion_approach=(
                        "QBS value-based: understand their boss's priorities"
                    ),
                    urgency=(
                        "next_conversation" if interaction_count < 3 else "immediate"
                    ),
                )
            ]
        return []

    @staticmethod
    def save_expansion_state(state, triggers):
        AccountExpansionDetector.save_expansion_state(state, triggers)


# ── Test Fixtures ─────────────────────────────────────────────────────────────


def _make_state(**overrides) -> ConversationState:
    """Create a ConversationState with sensible defaults."""
    defaults = {
        "state_id": str(uuid.uuid4()),
        "tenant_id": "tenant-qbs-1",
        "account_id": "acct-qbs-1",
        "contact_id": "contact-qbs-1",
        "contact_email": "alice@example.com",
        "contact_name": "Alice Smith",
        "deal_stage": DealStage.DISCOVERY,
        "persona_type": PersonaType.MANAGER,
        "interaction_count": 0,
        "confidence_score": 0.8,
    }
    defaults.update(overrides)
    return ConversationState(**defaults)


def _make_qbs_agent(
    state_repo: InMemoryStateRepository | None = None,
    llm_response: str = "Subject: Test Follow-up\n\nHello Alice, great to connect.",
    with_qbs: bool = True,
    with_expansion: bool = True,
    qualification_result: QualificationState | None = None,
) -> tuple[SalesAgent, dict]:
    """Create a SalesAgent with mocked services and optional QBS components."""
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
            message_id="msg-qbs-1",
            thread_id="thread-qbs-1",
            label_ids=["SENT"],
        )
    )

    # Configure Chat mock
    mocks["chat_service"].send_message = AsyncMock(
        return_value=MagicMock(
            message_name="spaces/qbs/messages/1",
            create_time="2026-02-12T10:00:00Z",
        )
    )

    # Configure RAG mock
    mocks["rag_pipeline"].run = AsyncMock(
        return_value=MagicMock(
            answer="Product supports enterprise billing.", sources=[]
        )
    )

    # Configure conversation store mock
    mocks["conversation_store"].search_conversations = AsyncMock(return_value=[])

    # Qualification extractor
    qual_extractor = QualificationExtractor(llm_service=mocks["llm_service"])
    if qualification_result is not None:
        qual_extractor.extract_signals = AsyncMock(return_value=qualification_result)

    # Action engine and escalation manager
    from src.app.agents.sales.actions import NextActionEngine

    action_engine = NextActionEngine(llm_service=mocks["llm_service"])

    event_bus_mock = AsyncMock()
    event_bus_mock.publish = AsyncMock()
    escalation_mgr = EscalationManager(
        event_bus=event_bus_mock, llm_service=mocks["llm_service"]
    )

    # QBS components
    qbs_engine = MockQBSEngine() if with_qbs else None
    expansion_detector = MockExpansionDetector() if with_expansion else None

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
        qbs_engine=qbs_engine,
        expansion_detector=expansion_detector,
    )

    mocks["state_repo"] = state_repo
    mocks["qbs_engine"] = qbs_engine
    mocks["expansion_detector"] = expansion_detector

    return agent, mocks


# ── Integration Tests ─────────────────────────────────────────────────────────


class TestQBSGuidanceInjectedInPrompt:
    """Test 1: QBS guidance is injected into email/chat prompts."""

    @pytest.mark.asyncio
    async def test_qbs_guidance_injected_in_email_prompt(self):
        """QBS engine produces guidance -> injected into email prompt."""
        state_repo = InMemoryStateRepository()
        agent, mocks = _make_qbs_agent(state_repo=state_repo)

        # Compile sales context and get QBS guidance
        task = {
            "type": "send_email",
            "account_id": "acct-qbs-1",
            "contact_id": "contact-qbs-1",
            "contact_email": "alice@example.com",
            "contact_name": "Alice Smith",
            "persona_type": "manager",
            "deal_stage": "discovery",
            "description": "Initial outreach",
        }
        context = {"tenant_id": "tenant-qbs-1"}

        sales_ctx = await agent._compile_sales_context(task, context)
        guidance = await agent._get_qbs_guidance(sales_ctx)

        # Verify guidance contains expected QBS content
        assert guidance is not None
        assert "pain_funnel" in guidance
        assert "calibrated_question" in guidance
        assert "What challenges are you facing" in guidance


class TestQBSPainStatePersists:
    """Test 2: Pain state persists across interactions."""

    @pytest.mark.asyncio
    async def test_qbs_pain_state_persists_across_interactions(self):
        """Process reply twice -> pain state accumulates in metadata."""
        state_repo = InMemoryStateRepository()
        qualification = QualificationState()
        agent, mocks = _make_qbs_agent(
            state_repo=state_repo,
            qualification_result=qualification,
        )

        base_task = {
            "type": "process_reply",
            "account_id": "acct-qbs-1",
            "contact_id": "contact-qbs-1",
            "contact_email": "alice@example.com",
            "reply_text": "We are struggling with our billing accuracy",
            "channel": "email",
        }
        ctx = {"tenant_id": "tenant-qbs-1"}

        # First reply
        result1 = await agent.invoke(base_task, ctx)
        assert result1["status"] == "processed"

        # Load state and check pain state was created
        state = await state_repo.get_state(
            "tenant-qbs-1", "acct-qbs-1", "contact-qbs-1"
        )
        assert state is not None
        qbs_data = state.metadata.get("qbs", {})
        pain_data = qbs_data.get("pain_state", {})
        assert pain_data, "Pain state should be present after first reply"
        # Depth should have advanced (mock returns SURFACE)
        assert pain_data.get("depth_level") in ("surface", "business_impact", "emotional")

        # Second reply
        base_task["reply_text"] = "It costs us about 40 hours per month"
        result2 = await agent.invoke(base_task, ctx)
        assert result2["status"] == "processed"

        # Verify pain state accumulated (not reset)
        state2 = await state_repo.get_state(
            "tenant-qbs-1", "acct-qbs-1", "contact-qbs-1"
        )
        pain_data2 = state2.metadata.get("qbs", {}).get("pain_state", {})
        assert pain_data2, "Pain state should persist after second reply"
        # Interaction count should have advanced
        assert state2.interaction_count >= 2


class TestQBSExpansionDetected:
    """Test 3: Expansion triggers detected from reply text."""

    @pytest.mark.asyncio
    async def test_qbs_expansion_detected_from_reply(self):
        """Reply mentioning 'boss' -> expansion trigger saved in metadata."""
        state_repo = InMemoryStateRepository()
        qualification = QualificationState()
        agent, mocks = _make_qbs_agent(
            state_repo=state_repo,
            qualification_result=qualification,
        )

        task = {
            "type": "process_reply",
            "account_id": "acct-qbs-1",
            "contact_id": "contact-qbs-1",
            "contact_email": "alice@example.com",
            "reply_text": "My boss mentioned this last week and thinks we need to act fast",
            "channel": "email",
        }
        ctx = {"tenant_id": "tenant-qbs-1"}

        result = await agent.invoke(task, ctx)
        assert result["status"] == "processed"

        # Check expansion triggers in metadata
        state = await state_repo.get_state(
            "tenant-qbs-1", "acct-qbs-1", "contact-qbs-1"
        )
        expansion_data = state.metadata.get("qbs", {}).get("expansion", {})
        detected = expansion_data.get("detected_contacts", [])
        assert len(detected) >= 1
        assert detected[0]["mentioned_name_or_role"] == "their boss"
        assert detected[0]["relationship_to_contact"] == "manager"


class TestQBSNoExpansionWithoutMentions:
    """Test 4: No expansion triggers when no contacts mentioned."""

    @pytest.mark.asyncio
    async def test_qbs_no_expansion_without_mentions(self):
        """Reply without contact mentions -> no expansion data."""
        state_repo = InMemoryStateRepository()
        qualification = QualificationState()
        agent, mocks = _make_qbs_agent(
            state_repo=state_repo,
            qualification_result=qualification,
        )

        task = {
            "type": "process_reply",
            "account_id": "acct-qbs-1",
            "contact_id": "contact-qbs-1",
            "contact_email": "alice@example.com",
            "reply_text": "We need better billing accuracy for our invoices",
            "channel": "email",
        }
        ctx = {"tenant_id": "tenant-qbs-1"}

        result = await agent.invoke(task, ctx)
        assert result["status"] == "processed"

        state = await state_repo.get_state(
            "tenant-qbs-1", "acct-qbs-1", "contact-qbs-1"
        )
        expansion_data = state.metadata.get("qbs", {}).get("expansion", {})
        detected = expansion_data.get("detected_contacts", [])
        assert len(detected) == 0


class TestQBSFormatContextSummaryIncludesPain:
    """Test 5: Context summary includes QBS pain points."""

    def test_qbs_format_context_summary_includes_pain(self):
        """State with pain topics -> context summary has 'Identified Pain Points'."""
        state = _make_state(
            metadata={
                "qbs": {
                    "pain_state": {
                        "depth_level": "surface",
                        "pain_topics": [
                            {
                                "topic": "Billing accuracy",
                                "depth": "surface",
                                "evidence": "They mentioned billing errors",
                                "business_impact": "40 hours/month wasted",
                                "emotional_indicator": None,
                                "first_mentioned_at": 1,
                                "last_probed_at": 2,
                            }
                        ],
                        "emotional_recognition_detected": False,
                        "self_elaboration_count": 0,
                        "resistance_detected": False,
                        "revisit_later": [],
                        "last_probed_topic": None,
                        "probe_count_current_topic": 0,
                    }
                }
            }
        )

        sales_ctx = {
            "conversation_state": state,
            "rag_response": None,
            "conversation_history": [],
        }

        summary = SalesAgent._format_context_summary(sales_ctx)
        assert "Identified Pain Points" in summary
        assert "Billing accuracy" in summary
        assert "40 hours/month wasted" in summary


class TestQBSFormatContextSummaryIncludesExpansion:
    """Test 6: Context summary includes expansion opportunities."""

    def test_qbs_format_context_summary_includes_expansion(self):
        """State with expansion data -> context summary has 'Expansion Opportunities'."""
        state = _make_state(
            metadata={
                "qbs": {
                    "expansion": {
                        "detected_contacts": [
                            {
                                "mentioned_name_or_role": "VP of Engineering",
                                "context_quote": "Our VP wants to see a demo",
                                "relationship_to_contact": "executive sponsor",
                                "expansion_approach": "QBS value-based",
                                "urgency": "next_conversation",
                            }
                        ]
                    }
                }
            }
        )

        sales_ctx = {
            "conversation_state": state,
            "rag_response": None,
            "conversation_history": [],
        }

        summary = SalesAgent._format_context_summary(sales_ctx)
        assert "Expansion Opportunities" in summary
        assert "1 contact(s)" in summary


class TestQBSBackwardCompatibleWithoutEngine:
    """Test 7: SalesAgent works without QBS engine (backward compat)."""

    @pytest.mark.asyncio
    async def test_qbs_backward_compatible_without_engine(self):
        """SalesAgent with qbs_engine=None -> _get_qbs_guidance returns None."""
        state_repo = InMemoryStateRepository()
        agent, mocks = _make_qbs_agent(
            state_repo=state_repo,
            with_qbs=False,
            with_expansion=False,
        )

        task = {
            "type": "send_email",
            "account_id": "acct-qbs-1",
            "contact_id": "contact-qbs-1",
            "contact_email": "alice@example.com",
            "contact_name": "Alice Smith",
            "persona_type": "manager",
            "deal_stage": "discovery",
            "description": "Test backward compat",
        }
        ctx = {"tenant_id": "tenant-qbs-1"}

        sales_ctx = await agent._compile_sales_context(task, ctx)
        guidance = await agent._get_qbs_guidance(sales_ctx)
        assert guidance is None

        # Full email flow still works
        result = await agent.invoke(task, ctx)
        assert result["status"] == "sent"


class TestPromptIncludesQBSMethodology:
    """Test 8: System prompt always includes QBS methodology."""

    def test_prompt_includes_qbs_methodology(self):
        """build_system_prompt includes QBS keywords."""
        from src.app.agents.sales.prompts import build_system_prompt

        prompt = build_system_prompt(
            PersonaType.MANAGER, Channel.EMAIL, DealStage.DISCOVERY
        )

        # QBS methodology should be present
        assert "Question Based Selling" in prompt or "QBS" in prompt
        assert "Pain Funnel" in prompt or "pain funnel" in prompt.lower()
        assert "Impact Questions" in prompt or "impact" in prompt.lower()
        assert "Solution Questions" in prompt or "solution" in prompt.lower()
        assert "Confirmation Questions" in prompt or "confirmation" in prompt.lower()


class TestPromptIncludesDynamicQBSGuidance:
    """Test 9: System prompt includes dynamic QBS guidance when provided."""

    def test_prompt_includes_dynamic_qbs_guidance(self):
        """build_system_prompt with qbs_guidance -> guidance string in prompt."""
        from src.app.agents.sales.prompts import build_system_prompt

        guidance = "Focus on IMPACT questions targeting metrics"
        prompt = build_system_prompt(
            PersonaType.MANAGER,
            Channel.EMAIL,
            DealStage.DISCOVERY,
            qbs_guidance=guidance,
        )

        assert guidance in prompt
