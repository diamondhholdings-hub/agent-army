"""Tests for QBS schema validation and prompt template generation.

Tests QBS Pydantic model construction, enum values, default states,
prompt template content, and builder function output formatting.
"""

from __future__ import annotations

import pytest

from src.app.agents.sales.qbs.schemas import (
    EngagementSignal,
    ExpansionRecommendation,
    ExpansionTrigger,
    PainDepthLevel,
    PainFunnelState,
    PainTopic,
    QBSQuestionRecommendation,
    QBSQuestionType,
)
from src.app.agents.sales.qbs.prompts import (
    EXPANSION_DETECTION_PROMPT,
    QBS_ANALYSIS_SYSTEM_PROMPT,
    QBS_METHODOLOGY_PROMPT,
    build_expansion_detection_prompt,
    build_qbs_analysis_prompt,
    build_qbs_prompt_section,
)


# ── Enum Tests ─────────────────────────────────────────────────────────────


class TestQBSQuestionType:
    def test_enum_values(self) -> None:
        assert QBSQuestionType.PAIN_FUNNEL == "pain_funnel"
        assert QBSQuestionType.IMPACT == "impact"
        assert QBSQuestionType.SOLUTION == "solution"
        assert QBSQuestionType.CONFIRMATION == "confirmation"

    def test_enum_count(self) -> None:
        assert len(QBSQuestionType) == 4


class TestPainDepthLevel:
    def test_enum_values(self) -> None:
        assert PainDepthLevel.NOT_EXPLORED == "not_explored"
        assert PainDepthLevel.SURFACE == "surface"
        assert PainDepthLevel.BUSINESS_IMPACT == "business_impact"
        assert PainDepthLevel.EMOTIONAL == "emotional"

    def test_enum_count(self) -> None:
        assert len(PainDepthLevel) == 4


class TestEngagementSignal:
    def test_enum_values(self) -> None:
        assert EngagementSignal.HIGH_ENERGY == "high_energy"
        assert EngagementSignal.FACTUAL == "factual"
        assert EngagementSignal.RESISTANT == "resistant"
        assert EngagementSignal.TOPIC_SHIFT == "topic_shift"
        assert EngagementSignal.EMOTIONAL_LANGUAGE == "emotional_language"

    def test_enum_count(self) -> None:
        assert len(EngagementSignal) == 5


# ── QBSQuestionRecommendation Tests ───────────────────────────────────────


class TestQBSQuestionRecommendation:
    def test_full_construction(self) -> None:
        rec = QBSQuestionRecommendation(
            question_type=QBSQuestionType.PAIN_FUNNEL,
            meddic_bant_target="need",
            voss_delivery="calibrated_question",
            suggested_question="What challenges are you facing?",
            rationale="First interaction, need to discover pain",
            information_gaps=["budget", "timeline"],
            engagement_signal=EngagementSignal.FACTUAL,
            pain_depth=PainDepthLevel.NOT_EXPLORED,
            should_probe_deeper=False,
            natural_stopping_signals=["customer gave short answer"],
        )
        assert rec.question_type == QBSQuestionType.PAIN_FUNNEL
        assert rec.meddic_bant_target == "need"
        assert rec.voss_delivery == "calibrated_question"
        assert rec.suggested_question == "What challenges are you facing?"
        assert rec.rationale == "First interaction, need to discover pain"
        assert rec.information_gaps == ["budget", "timeline"]
        assert rec.engagement_signal == EngagementSignal.FACTUAL
        assert rec.pain_depth == PainDepthLevel.NOT_EXPLORED
        assert rec.should_probe_deeper is False
        assert rec.natural_stopping_signals == ["customer gave short answer"]

    def test_blended_triple_fields(self) -> None:
        """Verify the blended triple: question_type + meddic_bant_target + voss_delivery."""
        rec = QBSQuestionRecommendation(
            question_type=QBSQuestionType.IMPACT,
            meddic_bant_target="metrics",
            voss_delivery="mirror",
            suggested_question="...struggling with your billing system?",
            rationale="Customer mentioned billing pain, mirror to explore impact",
            engagement_signal=EngagementSignal.HIGH_ENERGY,
            pain_depth=PainDepthLevel.SURFACE,
            should_probe_deeper=True,
        )
        assert rec.question_type == QBSQuestionType.IMPACT
        assert rec.meddic_bant_target == "metrics"
        assert rec.voss_delivery == "mirror"

    def test_empty_optional_lists(self) -> None:
        rec = QBSQuestionRecommendation(
            question_type=QBSQuestionType.CONFIRMATION,
            meddic_bant_target="champion",
            voss_delivery="label",
            suggested_question="So the core issue is accuracy?",
            rationale="Confirming understanding",
            engagement_signal=EngagementSignal.HIGH_ENERGY,
            pain_depth=PainDepthLevel.BUSINESS_IMPACT,
            should_probe_deeper=False,
        )
        assert rec.information_gaps == []
        assert rec.natural_stopping_signals == []

    def test_all_question_types_accepted(self) -> None:
        for qt in QBSQuestionType:
            rec = QBSQuestionRecommendation(
                question_type=qt,
                meddic_bant_target="need",
                voss_delivery="calibrated_question",
                suggested_question="Test question",
                rationale="Test",
                engagement_signal=EngagementSignal.FACTUAL,
                pain_depth=PainDepthLevel.NOT_EXPLORED,
                should_probe_deeper=False,
            )
            assert rec.question_type == qt


# ── PainTopic Tests ────────────────────────────────────────────────────────


class TestPainTopic:
    def test_basic_construction(self) -> None:
        topic = PainTopic(
            topic="Manual billing process",
            depth=PainDepthLevel.SURFACE,
            evidence="They mentioned spending 40 hours a week on manual billing",
            first_mentioned_at=1,
            last_probed_at=1,
        )
        assert topic.topic == "Manual billing process"
        assert topic.depth == PainDepthLevel.SURFACE
        assert topic.business_impact is None
        assert topic.emotional_indicator is None

    def test_with_business_impact_and_emotion(self) -> None:
        topic = PainTopic(
            topic="Revenue leakage",
            depth=PainDepthLevel.EMOTIONAL,
            evidence="We're losing about 5% of revenue to billing errors",
            business_impact="5% revenue loss, approximately $2M annually",
            emotional_indicator="It's keeping me up at night",
            first_mentioned_at=2,
            last_probed_at=5,
        )
        assert topic.business_impact == "5% revenue loss, approximately $2M annually"
        assert topic.emotional_indicator == "It's keeping me up at night"
        assert topic.depth == PainDepthLevel.EMOTIONAL


# ── PainFunnelState Tests ──────────────────────────────────────────────────


class TestPainFunnelState:
    def test_default_state(self) -> None:
        state = PainFunnelState()
        assert state.depth_level == PainDepthLevel.NOT_EXPLORED
        assert state.pain_topics == []
        assert state.emotional_recognition_detected is False
        assert state.self_elaboration_count == 0
        assert state.resistance_detected is False
        assert state.revisit_later == []
        assert state.last_probed_topic is None
        assert state.probe_count_current_topic == 0

    def test_with_pain_topics(self) -> None:
        topics = [
            PainTopic(
                topic=f"Pain {i}",
                depth=PainDepthLevel.SURFACE,
                evidence=f"Evidence {i}",
                first_mentioned_at=i,
                last_probed_at=i,
            )
            for i in range(3)
        ]
        state = PainFunnelState(
            depth_level=PainDepthLevel.SURFACE,
            pain_topics=topics,
            last_probed_topic="Pain 2",
            probe_count_current_topic=2,
        )
        assert len(state.pain_topics) == 3
        assert state.last_probed_topic == "Pain 2"
        assert state.probe_count_current_topic == 2

    def test_max_10_pain_topics(self) -> None:
        """PainFunnelState can hold up to 10 topics (boundary per RESEARCH.md Pitfall 6)."""
        topics = [
            PainTopic(
                topic=f"Pain {i}",
                depth=PainDepthLevel.SURFACE,
                evidence=f"Evidence {i}",
                first_mentioned_at=i,
                last_probed_at=i,
            )
            for i in range(10)
        ]
        state = PainFunnelState(pain_topics=topics)
        assert len(state.pain_topics) == 10

    def test_resistance_and_revisit(self) -> None:
        state = PainFunnelState(
            resistance_detected=True,
            revisit_later=["budget concerns", "team structure"],
        )
        assert state.resistance_detected is True
        assert len(state.revisit_later) == 2

    def test_serialization_roundtrip(self) -> None:
        state = PainFunnelState(
            depth_level=PainDepthLevel.BUSINESS_IMPACT,
            emotional_recognition_detected=True,
            self_elaboration_count=3,
        )
        data = state.model_dump()
        restored = PainFunnelState(**data)
        assert restored.depth_level == PainDepthLevel.BUSINESS_IMPACT
        assert restored.emotional_recognition_detected is True
        assert restored.self_elaboration_count == 3


# ── ExpansionTrigger Tests ─────────────────────────────────────────────────


class TestExpansionTrigger:
    def test_immediate_urgency(self) -> None:
        trigger = ExpansionTrigger(
            mentioned_name_or_role="Sarah from procurement",
            context_quote="Sarah from procurement handles all vendor approvals",
            relationship_to_contact="peer in another department",
            expansion_approach="Value-based: understand procurement requirements",
            urgency="immediate",
        )
        assert trigger.urgency == "immediate"
        assert trigger.mentioned_name_or_role == "Sarah from procurement"

    def test_next_conversation_urgency(self) -> None:
        trigger = ExpansionTrigger(
            mentioned_name_or_role="my boss",
            context_quote="I'd need to check with my boss on that",
            relationship_to_contact="direct manager",
            expansion_approach="QBS-style: How does your boss experience this problem?",
            urgency="next_conversation",
        )
        assert trigger.urgency == "next_conversation"

    def test_after_trust_builds_urgency(self) -> None:
        trigger = ExpansionTrigger(
            mentioned_name_or_role="the CTO",
            context_quote="The CTO is looking at this space broadly",
            relationship_to_contact="executive sponsor",
            expansion_approach="Direct request after building champion relationship",
            urgency="after_trust_builds",
        )
        assert trigger.urgency == "after_trust_builds"


# ── ExpansionRecommendation Tests ──────────────────────────────────────────


class TestExpansionRecommendation:
    def test_default_empty(self) -> None:
        rec = ExpansionRecommendation()
        assert rec.triggers == []
        assert rec.primary_recommendation == ""
        assert rec.resistance_assessment == ""
        assert rec.political_context == ""

    def test_with_multiple_triggers(self) -> None:
        triggers = [
            ExpansionTrigger(
                mentioned_name_or_role="VP of Engineering",
                context_quote="The VP of Engineering is driving this initiative",
                relationship_to_contact="executive sponsor",
                expansion_approach="QBS: How does the VP experience this problem?",
                urgency="next_conversation",
            ),
            ExpansionTrigger(
                mentioned_name_or_role="finance team",
                context_quote="Finance needs to sign off on anything over 50k",
                relationship_to_contact="budget gatekeeper",
                expansion_approach="Value-based: understand finance requirements",
                urgency="after_trust_builds",
            ),
        ]
        rec = ExpansionRecommendation(
            triggers=triggers,
            primary_recommendation="Build champion first, then request VP introduction",
            resistance_assessment="Low resistance expected -- customer volunteered info",
            political_context="VP drives initiative, finance has budget authority",
        )
        assert len(rec.triggers) == 2
        assert "champion" in rec.primary_recommendation


# ── Prompt Template Content Tests ──────────────────────────────────────────


class TestQBSMethodologyPrompt:
    def test_contains_question_types(self) -> None:
        assert "pain funnel" in QBS_METHODOLOGY_PROMPT.lower()
        assert "impact" in QBS_METHODOLOGY_PROMPT.lower()
        assert "solution" in QBS_METHODOLOGY_PROMPT.lower()
        assert "confirmation" in QBS_METHODOLOGY_PROMPT.lower()

    def test_contains_anti_interrogation_rule(self) -> None:
        assert "never ask more than one" in QBS_METHODOLOGY_PROMPT.lower()

    def test_contains_give_value_first(self) -> None:
        assert "give value first" in QBS_METHODOLOGY_PROMPT.lower()

    def test_contains_elite_principles(self) -> None:
        prompt_lower = QBS_METHODOLOGY_PROMPT.lower()
        assert "listen actively" in prompt_lower
        assert "follow the energy" in prompt_lower
        assert "gap sensing" in prompt_lower
        assert "context over checklist" in prompt_lower

    def test_contains_pain_pacing(self) -> None:
        assert "respect the customer's pace" in QBS_METHODOLOGY_PROMPT.lower()

    def test_contains_methodology_blending(self) -> None:
        prompt_lower = QBS_METHODOLOGY_PROMPT.lower()
        assert "meddic" in prompt_lower or "bant" in prompt_lower
        assert "voss" in prompt_lower


class TestQBSAnalysisSystemPrompt:
    def test_contains_sensing_modes(self) -> None:
        prompt_lower = QBS_ANALYSIS_SYSTEM_PROMPT.lower()
        assert "information gap" in prompt_lower
        assert "engagement signal" in prompt_lower
        assert "natural conversation flow" in prompt_lower

    def test_contains_question_selection_guidance(self) -> None:
        assert "not fixed sequence" in QBS_ANALYSIS_SYSTEM_PROMPT.lower()

    def test_contains_pain_depth_levels(self) -> None:
        prompt_lower = QBS_ANALYSIS_SYSTEM_PROMPT.lower()
        assert "not_explored" in prompt_lower
        assert "surface" in prompt_lower
        assert "business_impact" in prompt_lower
        assert "emotional" in prompt_lower


class TestExpansionDetectionPrompt:
    def test_contains_detection_rules(self) -> None:
        prompt_lower = EXPANSION_DETECTION_PROMPT.lower()
        assert "mention" in prompt_lower
        assert "context_quote" in prompt_lower
        assert "urgency" in prompt_lower

    def test_contains_urgency_levels(self) -> None:
        prompt_lower = EXPANSION_DETECTION_PROMPT.lower()
        assert "immediate" in prompt_lower
        assert "next_conversation" in prompt_lower
        assert "after_trust_builds" in prompt_lower


# ── Builder Function Tests ─────────────────────────────────────────────────


class TestBuildQBSAnalysisPrompt:
    def test_returns_two_messages(self) -> None:
        messages = build_qbs_analysis_prompt(
            conversation_state_summary="Deal stage: DISCOVERY, Persona: MANAGER",
            latest_message="We're struggling with manual billing",
            conversation_history_summary="First interaction, no prior context",
            pain_state_summary="No pain explored yet",
            qualification_gaps="Missing: budget, timeline, authority",
        )
        assert len(messages) == 2

    def test_system_role_first(self) -> None:
        messages = build_qbs_analysis_prompt(
            conversation_state_summary="test",
            latest_message="test",
            conversation_history_summary="test",
            pain_state_summary="test",
            qualification_gaps="test",
        )
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_message_structure(self) -> None:
        messages = build_qbs_analysis_prompt(
            conversation_state_summary="DISCOVERY stage",
            latest_message="Our billing takes 40 hours per week",
            conversation_history_summary="Initial outreach was well-received",
            pain_state_summary="Surface-level pain identified",
            qualification_gaps="Budget and timeline unknown",
        )
        for msg in messages:
            assert "role" in msg
            assert "content" in msg
            assert isinstance(msg["role"], str)
            assert isinstance(msg["content"], str)

    def test_user_message_contains_context(self) -> None:
        messages = build_qbs_analysis_prompt(
            conversation_state_summary="DISCOVERY",
            latest_message="Manual billing is painful",
            conversation_history_summary="Prior interactions positive",
            pain_state_summary="Surface depth",
            qualification_gaps="Missing budget",
        )
        user_content = messages[1]["content"]
        assert "DISCOVERY" in user_content
        assert "Manual billing is painful" in user_content
        assert "Missing budget" in user_content


class TestBuildQBSPromptSection:
    @pytest.fixture
    def sample_recommendation(self) -> QBSQuestionRecommendation:
        return QBSQuestionRecommendation(
            question_type=QBSQuestionType.PAIN_FUNNEL,
            meddic_bant_target="need",
            voss_delivery="calibrated_question",
            suggested_question="What challenges are you facing with your current approach?",
            rationale="First interaction, starting with pain discovery",
            information_gaps=["budget", "timeline"],
            engagement_signal=EngagementSignal.FACTUAL,
            pain_depth=PainDepthLevel.NOT_EXPLORED,
            should_probe_deeper=False,
        )

    @pytest.fixture
    def sample_pain_state(self) -> PainFunnelState:
        return PainFunnelState()

    def test_returns_string(
        self,
        sample_recommendation: QBSQuestionRecommendation,
        sample_pain_state: PainFunnelState,
    ) -> None:
        result = build_qbs_prompt_section(
            sample_recommendation, sample_pain_state, []
        )
        assert isinstance(result, str)

    def test_contains_question_type(
        self,
        sample_recommendation: QBSQuestionRecommendation,
        sample_pain_state: PainFunnelState,
    ) -> None:
        result = build_qbs_prompt_section(
            sample_recommendation, sample_pain_state, []
        )
        assert "pain_funnel" in result

    def test_contains_suggested_question(
        self,
        sample_recommendation: QBSQuestionRecommendation,
        sample_pain_state: PainFunnelState,
    ) -> None:
        result = build_qbs_prompt_section(
            sample_recommendation, sample_pain_state, []
        )
        assert "What challenges are you facing" in result

    def test_contains_information_gaps(
        self,
        sample_recommendation: QBSQuestionRecommendation,
        sample_pain_state: PainFunnelState,
    ) -> None:
        result = build_qbs_prompt_section(
            sample_recommendation, sample_pain_state, []
        )
        assert "budget" in result
        assert "timeline" in result

    def test_no_expansion_section_when_empty(
        self,
        sample_recommendation: QBSQuestionRecommendation,
        sample_pain_state: PainFunnelState,
    ) -> None:
        result = build_qbs_prompt_section(
            sample_recommendation, sample_pain_state, []
        )
        assert "Account Expansion" not in result

    def test_expansion_section_when_triggers_present(
        self,
        sample_recommendation: QBSQuestionRecommendation,
        sample_pain_state: PainFunnelState,
    ) -> None:
        triggers = [
            ExpansionTrigger(
                mentioned_name_or_role="VP of Engineering",
                context_quote="Our VP of Engineering wants this done by Q3",
                relationship_to_contact="executive sponsor",
                expansion_approach="QBS: How does the VP experience this?",
                urgency="next_conversation",
            ),
        ]
        result = build_qbs_prompt_section(
            sample_recommendation, sample_pain_state, triggers
        )
        assert "Account Expansion" in result
        assert "VP of Engineering" in result

    def test_not_explored_pain_state(
        self,
        sample_recommendation: QBSQuestionRecommendation,
    ) -> None:
        """Early conversation: NOT_EXPLORED pain state renders correctly."""
        state = PainFunnelState()
        result = build_qbs_prompt_section(
            sample_recommendation, state, []
        )
        assert "not_explored" in result

    def test_resistance_detected_in_pain_state(
        self,
        sample_recommendation: QBSQuestionRecommendation,
    ) -> None:
        state = PainFunnelState(resistance_detected=True)
        result = build_qbs_prompt_section(
            sample_recommendation, state, []
        )
        assert "RESISTANCE DETECTED" in result

    def test_pain_topics_shown(self) -> None:
        rec = QBSQuestionRecommendation(
            question_type=QBSQuestionType.IMPACT,
            meddic_bant_target="metrics",
            voss_delivery="mirror",
            suggested_question="...the billing system?",
            rationale="Probe impact of billing pain",
            engagement_signal=EngagementSignal.HIGH_ENERGY,
            pain_depth=PainDepthLevel.SURFACE,
            should_probe_deeper=True,
        )
        state = PainFunnelState(
            depth_level=PainDepthLevel.SURFACE,
            pain_topics=[
                PainTopic(
                    topic="Manual billing",
                    depth=PainDepthLevel.SURFACE,
                    evidence="40 hours per week",
                    business_impact="$2M annual cost",
                    first_mentioned_at=1,
                    last_probed_at=2,
                ),
            ],
        )
        result = build_qbs_prompt_section(rec, state, [])
        assert "Manual billing" in result
        assert "$2M annual cost" in result


class TestBuildExpansionDetectionPrompt:
    def test_returns_two_messages(self) -> None:
        messages = build_expansion_detection_prompt(
            conversation_text="My boss Sarah wants to see a demo",
            existing_contacts=["John Doe"],
        )
        assert len(messages) == 2

    def test_system_role_first(self) -> None:
        messages = build_expansion_detection_prompt(
            conversation_text="test",
            existing_contacts=[],
        )
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_existing_contacts_in_system_message(self) -> None:
        messages = build_expansion_detection_prompt(
            conversation_text="My boss wants this",
            existing_contacts=["John Doe", "Jane Smith"],
        )
        system_content = messages[0]["content"]
        assert "John Doe" in system_content
        assert "Jane Smith" in system_content

    def test_empty_contacts_handled(self) -> None:
        messages = build_expansion_detection_prompt(
            conversation_text="My boss wants this",
            existing_contacts=[],
        )
        system_content = messages[0]["content"]
        assert "None" in system_content or "none" in system_content.lower()

    def test_conversation_text_in_user_message(self) -> None:
        text = "Sarah from procurement handles all vendor approvals"
        messages = build_expansion_detection_prompt(
            conversation_text=text,
            existing_contacts=[],
        )
        assert messages[1]["content"] == text
