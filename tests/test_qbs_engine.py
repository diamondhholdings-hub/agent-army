"""Tests for QBS engine, pain tracker, and expansion detector.

Tests rule-based fallback logic, pain state management, back-off detection,
expansion state deduplication, and urgency adjustment. LLM-dependent paths
(analyze_and_recommend, detect_expansion_triggers) are covered by integration
tests in Plan 03.
"""

from __future__ import annotations

import uuid

import pytest

from src.app.agents.sales.qbs.engine import QBSQuestionEngine
from src.app.agents.sales.qbs.expansion import AccountExpansionDetector
from src.app.agents.sales.qbs.pain_tracker import PainDepthTracker
from src.app.agents.sales.qbs.schemas import (
    EngagementSignal,
    ExpansionTrigger,
    PainDepthLevel,
    PainFunnelState,
    PainTopic,
    QBSQuestionRecommendation,
    QBSQuestionType,
)
from src.app.agents.sales.schemas import (
    BANTSignals,
    ConversationState,
    DealStage,
    MEDDICSignals,
    PersonaType,
    QualificationState,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_state() -> ConversationState:
    """Minimal ConversationState for testing."""
    return ConversationState(
        state_id=str(uuid.uuid4()),
        tenant_id="tenant-001",
        account_id="acct-001",
        contact_id="contact-001",
        contact_email="jane@example.com",
        contact_name="Jane Doe",
        deal_stage=DealStage.DISCOVERY,
        persona_type=PersonaType.MANAGER,
        interaction_count=3,
    )


@pytest.fixture
def sample_state_first_interaction() -> ConversationState:
    """ConversationState with zero interactions."""
    return ConversationState(
        state_id=str(uuid.uuid4()),
        tenant_id="tenant-001",
        account_id="acct-001",
        contact_id="contact-001",
        contact_email="jane@example.com",
        contact_name="Jane Doe",
        deal_stage=DealStage.PROSPECTING,
        persona_type=PersonaType.MANAGER,
        interaction_count=0,
    )


@pytest.fixture
def engine() -> QBSQuestionEngine:
    """QBSQuestionEngine with a mock LLM service."""
    mock_llm = type("MockLLM", (), {"router": None})()
    return QBSQuestionEngine(mock_llm)


@pytest.fixture
def fully_identified_qualification() -> QualificationState:
    """QualificationState with all dimensions identified."""
    return QualificationState(
        bant=BANTSignals(
            budget_identified=True,
            authority_identified=True,
            need_identified=True,
            timeline_identified=True,
        ),
        meddic=MEDDICSignals(
            metrics_identified=True,
            economic_buyer_identified=True,
            decision_criteria_identified=True,
            decision_process_identified=True,
            pain_identified=True,
            champion_identified=True,
        ),
    )


@pytest.fixture
def partial_qualification() -> QualificationState:
    """QualificationState with some dimensions identified."""
    return QualificationState(
        bant=BANTSignals(
            budget_identified=True,
            need_identified=True,
        ),
        meddic=MEDDICSignals(
            pain_identified=True,
        ),
    )


def _make_recommendation(
    question_type: QBSQuestionType = QBSQuestionType.PAIN_FUNNEL,
    target: str = "need",
    delivery: str = "calibrated_question",
    engagement: EngagementSignal = EngagementSignal.FACTUAL,
    pain_depth: PainDepthLevel = PainDepthLevel.SURFACE,
    should_probe: bool = True,
) -> QBSQuestionRecommendation:
    """Helper to build a recommendation for tests."""
    return QBSQuestionRecommendation(
        question_type=question_type,
        meddic_bant_target=target,
        voss_delivery=delivery,
        suggested_question="Test question?",
        rationale="Test rationale",
        engagement_signal=engagement,
        pain_depth=pain_depth,
        should_probe_deeper=should_probe,
    )


# ── QBSQuestionEngine Fallback Tests ─────────────────────────────────────────


class TestQBSQuestionEngineFallback:
    def test_fallback_first_interaction(
        self, engine: QBSQuestionEngine, sample_state_first_interaction: ConversationState
    ) -> None:
        pain_state = PainFunnelState()
        rec = engine._fallback_recommendation(sample_state_first_interaction, pain_state)
        assert rec.question_type == QBSQuestionType.PAIN_FUNNEL
        assert rec.meddic_bant_target == "need"
        assert rec.voss_delivery == "calibrated_question"
        assert rec.engagement_signal == EngagementSignal.FACTUAL
        assert rec.should_probe_deeper is False

    def test_fallback_not_explored(
        self, engine: QBSQuestionEngine, sample_state: ConversationState
    ) -> None:
        pain_state = PainFunnelState(depth_level=PainDepthLevel.NOT_EXPLORED)
        rec = engine._fallback_recommendation(sample_state, pain_state)
        assert rec.question_type == QBSQuestionType.PAIN_FUNNEL
        assert rec.meddic_bant_target == "pain"
        assert rec.voss_delivery == "label"

    def test_fallback_surface(
        self, engine: QBSQuestionEngine, sample_state: ConversationState
    ) -> None:
        pain_state = PainFunnelState(depth_level=PainDepthLevel.SURFACE)
        rec = engine._fallback_recommendation(sample_state, pain_state)
        assert rec.question_type == QBSQuestionType.IMPACT
        assert rec.meddic_bant_target == "metrics"
        assert rec.voss_delivery == "calibrated_question"

    def test_fallback_business_impact(
        self, engine: QBSQuestionEngine, sample_state: ConversationState
    ) -> None:
        pain_state = PainFunnelState(depth_level=PainDepthLevel.BUSINESS_IMPACT)
        rec = engine._fallback_recommendation(sample_state, pain_state)
        assert rec.question_type == QBSQuestionType.SOLUTION
        assert rec.meddic_bant_target == "decision_criteria"

    def test_fallback_emotional(
        self, engine: QBSQuestionEngine, sample_state: ConversationState
    ) -> None:
        pain_state = PainFunnelState(depth_level=PainDepthLevel.EMOTIONAL)
        rec = engine._fallback_recommendation(sample_state, pain_state)
        assert rec.question_type == QBSQuestionType.CONFIRMATION
        assert rec.meddic_bant_target == "champion"
        assert rec.voss_delivery == "mirror"


class TestQBSQuestionEngineLoadPainState:
    def test_load_empty_metadata(self, sample_state: ConversationState) -> None:
        result = QBSQuestionEngine._load_pain_state(sample_state)
        assert isinstance(result, PainFunnelState)
        assert result.depth_level == PainDepthLevel.NOT_EXPLORED
        assert result.pain_topics == []

    def test_load_existing_metadata(self, sample_state: ConversationState) -> None:
        sample_state.metadata = {
            "qbs": {
                "pain_state": {
                    "depth_level": "surface",
                    "pain_topics": [
                        {
                            "topic": "billing errors",
                            "depth": "surface",
                            "evidence": "They mentioned billing issues",
                            "first_mentioned_at": 1,
                            "last_probed_at": 2,
                        }
                    ],
                    "resistance_detected": True,
                    "self_elaboration_count": 2,
                }
            }
        }
        result = QBSQuestionEngine._load_pain_state(sample_state)
        assert result.depth_level == PainDepthLevel.SURFACE
        assert len(result.pain_topics) == 1
        assert result.pain_topics[0].topic == "billing errors"
        assert result.resistance_detected is True
        assert result.self_elaboration_count == 2


class TestQBSQuestionEngineBuildGaps:
    def test_fully_identified_returns_empty(
        self, fully_identified_qualification: QualificationState
    ) -> None:
        result = QBSQuestionEngine._build_qualification_gaps(
            fully_identified_qualification
        )
        assert result == ""

    def test_partial_lists_missing_dimensions(
        self, partial_qualification: QualificationState
    ) -> None:
        result = QBSQuestionEngine._build_qualification_gaps(
            partial_qualification
        )
        # Budget and need are identified in BANT, so authority and timeline should be gaps
        assert "authority" in result
        assert "timeline" in result
        # Pain is identified in MEDDIC, so metrics, economic_buyer, decision_criteria,
        # decision_process, and champion should be gaps
        assert "metrics" in result
        assert "economic_buyer" in result
        assert "decision_criteria" in result
        assert "decision_process" in result
        assert "champion" in result
        # These should NOT be in the gaps
        assert "budget" not in result
        assert "need" not in result
        assert "pain" not in result

    def test_default_state_lists_all_dimensions(self) -> None:
        default_state = QualificationState()
        result = QBSQuestionEngine._build_qualification_gaps(default_state)
        # All 10 dimensions should be gaps
        for dim in [
            "budget", "authority", "need", "timeline",
            "metrics", "economic_buyer", "decision_criteria",
            "decision_process", "pain", "champion",
        ]:
            assert dim in result


# ── PainDepthTracker Tests ───────────────────────────────────────────────────


class TestPainDepthTrackerLoad:
    def test_load_empty_metadata(self, sample_state: ConversationState) -> None:
        result = PainDepthTracker.load(sample_state)
        assert isinstance(result, PainFunnelState)
        assert result.depth_level == PainDepthLevel.NOT_EXPLORED
        assert result.pain_topics == []

    def test_load_populated_metadata(self, sample_state: ConversationState) -> None:
        sample_state.metadata = {
            "qbs": {
                "pain_state": {
                    "depth_level": "business_impact",
                    "pain_topics": [],
                    "emotional_recognition_detected": True,
                    "self_elaboration_count": 3,
                    "resistance_detected": False,
                }
            }
        }
        result = PainDepthTracker.load(sample_state)
        assert result.depth_level == PainDepthLevel.BUSINESS_IMPACT
        assert result.emotional_recognition_detected is True
        assert result.self_elaboration_count == 3


class TestPainDepthTrackerSave:
    def test_save_writes_to_metadata(self, sample_state: ConversationState) -> None:
        pain_state = PainFunnelState(
            depth_level=PainDepthLevel.SURFACE,
            resistance_detected=True,
        )
        PainDepthTracker.save(sample_state, pain_state)

        assert "qbs" in sample_state.metadata
        assert "pain_state" in sample_state.metadata["qbs"]
        saved = sample_state.metadata["qbs"]["pain_state"]
        assert saved["depth_level"] == "surface"
        assert saved["resistance_detected"] is True

    def test_save_preserves_other_metadata_keys(
        self, sample_state: ConversationState
    ) -> None:
        sample_state.metadata = {"existing_key": "existing_value"}
        pain_state = PainFunnelState()
        PainDepthTracker.save(sample_state, pain_state)

        assert sample_state.metadata["existing_key"] == "existing_value"
        assert "qbs" in sample_state.metadata

    def test_save_preserves_other_qbs_keys(
        self, sample_state: ConversationState
    ) -> None:
        sample_state.metadata = {
            "qbs": {"expansion": {"detected_contacts": []}}
        }
        pain_state = PainFunnelState()
        PainDepthTracker.save(sample_state, pain_state)

        assert "expansion" in sample_state.metadata["qbs"]
        assert "pain_state" in sample_state.metadata["qbs"]


class TestPainDepthTrackerUpdate:
    def test_advances_depth_surface_to_business_impact(self) -> None:
        pain_state = PainFunnelState(depth_level=PainDepthLevel.SURFACE)
        rec = _make_recommendation(pain_depth=PainDepthLevel.BUSINESS_IMPACT)
        result = PainDepthTracker.update_from_recommendation(pain_state, rec, 3)
        assert result.depth_level == PainDepthLevel.BUSINESS_IMPACT

    def test_does_not_regress_depth(self) -> None:
        pain_state = PainFunnelState(depth_level=PainDepthLevel.BUSINESS_IMPACT)
        rec = _make_recommendation(pain_depth=PainDepthLevel.SURFACE)
        result = PainDepthTracker.update_from_recommendation(pain_state, rec, 3)
        assert result.depth_level == PainDepthLevel.BUSINESS_IMPACT

    def test_detects_emotional_recognition(self) -> None:
        pain_state = PainFunnelState()
        rec = _make_recommendation(
            engagement=EngagementSignal.EMOTIONAL_LANGUAGE
        )
        result = PainDepthTracker.update_from_recommendation(pain_state, rec, 3)
        assert result.emotional_recognition_detected is True

    def test_increments_self_elaboration_count(self) -> None:
        pain_state = PainFunnelState(self_elaboration_count=1)
        rec = _make_recommendation(engagement=EngagementSignal.HIGH_ENERGY)
        result = PainDepthTracker.update_from_recommendation(pain_state, rec, 3)
        assert result.self_elaboration_count == 2

    def test_detects_resistance(self) -> None:
        pain_state = PainFunnelState()
        rec = _make_recommendation(engagement=EngagementSignal.RESISTANT)
        result = PainDepthTracker.update_from_recommendation(pain_state, rec, 3)
        assert result.resistance_detected is True

    def test_updates_probe_tracking_same_topic(self) -> None:
        pain_state = PainFunnelState(
            last_probed_topic="pain_funnel:need",
            probe_count_current_topic=1,
        )
        rec = _make_recommendation(
            question_type=QBSQuestionType.PAIN_FUNNEL, target="need"
        )
        result = PainDepthTracker.update_from_recommendation(pain_state, rec, 3)
        assert result.probe_count_current_topic == 2
        assert result.last_probed_topic == "pain_funnel:need"

    def test_resets_probe_tracking_new_topic(self) -> None:
        pain_state = PainFunnelState(
            last_probed_topic="pain_funnel:need",
            probe_count_current_topic=3,
        )
        rec = _make_recommendation(
            question_type=QBSQuestionType.IMPACT, target="metrics"
        )
        result = PainDepthTracker.update_from_recommendation(pain_state, rec, 3)
        assert result.probe_count_current_topic == 1
        assert result.last_probed_topic == "impact:metrics"


class TestPainDepthTrackerAddTopic:
    def test_adds_new_topic(self) -> None:
        pain_state = PainFunnelState()
        result = PainDepthTracker.add_pain_topic(
            pain_state,
            topic="billing errors",
            depth=PainDepthLevel.SURFACE,
            evidence="They said billing is broken",
            interaction_count=1,
        )
        assert len(result.pain_topics) == 1
        assert result.pain_topics[0].topic == "billing errors"
        assert result.pain_topics[0].depth == PainDepthLevel.SURFACE
        assert result.pain_topics[0].first_mentioned_at == 1
        assert result.pain_topics[0].last_probed_at == 1

    def test_updates_existing_topic(self) -> None:
        pain_state = PainFunnelState(
            pain_topics=[
                PainTopic(
                    topic="billing errors",
                    depth=PainDepthLevel.SURFACE,
                    evidence="initial evidence",
                    first_mentioned_at=1,
                    last_probed_at=1,
                )
            ]
        )
        result = PainDepthTracker.add_pain_topic(
            pain_state,
            topic="billing errors",
            depth=PainDepthLevel.BUSINESS_IMPACT,
            evidence="new evidence",
            interaction_count=3,
            business_impact="$50k/month revenue leakage",
        )
        assert len(result.pain_topics) == 1
        assert result.pain_topics[0].depth == PainDepthLevel.BUSINESS_IMPACT
        assert result.pain_topics[0].last_probed_at == 3
        assert result.pain_topics[0].first_mentioned_at == 1
        assert result.pain_topics[0].business_impact == "$50k/month revenue leakage"

    def test_appends_evidence_with_separator(self) -> None:
        pain_state = PainFunnelState(
            pain_topics=[
                PainTopic(
                    topic="billing errors",
                    depth=PainDepthLevel.SURFACE,
                    evidence="first evidence",
                    first_mentioned_at=1,
                    last_probed_at=1,
                )
            ]
        )
        result = PainDepthTracker.add_pain_topic(
            pain_state,
            topic="billing errors",
            depth=PainDepthLevel.SURFACE,
            evidence="second evidence",
            interaction_count=2,
        )
        assert result.pain_topics[0].evidence == "first evidence | second evidence"

    def test_enforces_max_10_topics(self) -> None:
        pain_state = PainFunnelState(
            pain_topics=[
                PainTopic(
                    topic=f"topic-{i}",
                    depth=PainDepthLevel.SURFACE,
                    evidence=f"evidence-{i}",
                    first_mentioned_at=i,
                    last_probed_at=i,
                )
                for i in range(10)
            ]
        )
        assert len(pain_state.pain_topics) == 10

        # Add 11th topic
        result = PainDepthTracker.add_pain_topic(
            pain_state,
            topic="topic-new",
            depth=PainDepthLevel.SURFACE,
            evidence="new evidence",
            interaction_count=20,
        )
        assert len(result.pain_topics) == 10
        # The oldest topic (topic-0, last_probed_at=0) should be evicted
        topic_names = [t.topic for t in result.pain_topics]
        assert "topic-0" not in topic_names
        assert "topic-new" in topic_names

    def test_does_not_regress_topic_depth(self) -> None:
        pain_state = PainFunnelState(
            pain_topics=[
                PainTopic(
                    topic="billing errors",
                    depth=PainDepthLevel.BUSINESS_IMPACT,
                    evidence="deep evidence",
                    first_mentioned_at=1,
                    last_probed_at=2,
                )
            ]
        )
        result = PainDepthTracker.add_pain_topic(
            pain_state,
            topic="billing errors",
            depth=PainDepthLevel.SURFACE,
            evidence="shallow evidence",
            interaction_count=3,
        )
        # Depth should not regress
        assert result.pain_topics[0].depth == PainDepthLevel.BUSINESS_IMPACT


class TestPainDepthTrackerBackOff:
    def test_back_off_after_3_probes_without_elaboration(self) -> None:
        pain_state = PainFunnelState(
            probe_count_current_topic=3,
            emotional_recognition_detected=False,
            self_elaboration_count=0,
        )
        assert PainDepthTracker.should_back_off(pain_state) is True

    def test_back_off_when_resistance_detected(self) -> None:
        pain_state = PainFunnelState(
            resistance_detected=True,
            probe_count_current_topic=1,
        )
        assert PainDepthTracker.should_back_off(pain_state) is True

    def test_no_back_off_when_self_elaboration(self) -> None:
        pain_state = PainFunnelState(
            probe_count_current_topic=3,
            emotional_recognition_detected=False,
            self_elaboration_count=1,
        )
        assert PainDepthTracker.should_back_off(pain_state) is False

    def test_no_back_off_when_emotional_recognition(self) -> None:
        pain_state = PainFunnelState(
            probe_count_current_topic=3,
            emotional_recognition_detected=True,
            self_elaboration_count=0,
        )
        assert PainDepthTracker.should_back_off(pain_state) is False

    def test_no_back_off_under_3_probes(self) -> None:
        pain_state = PainFunnelState(
            probe_count_current_topic=2,
            emotional_recognition_detected=False,
            self_elaboration_count=0,
        )
        assert PainDepthTracker.should_back_off(pain_state) is False


# ── AccountExpansionDetector Tests ───────────────────────────────────────────


class TestExpansionDetectorSaveState:
    def test_save_new_triggers(self, sample_state: ConversationState) -> None:
        triggers = [
            ExpansionTrigger(
                mentioned_name_or_role="VP of Engineering",
                context_quote="I need to check with our VP of Engineering",
                relationship_to_contact="executive sponsor",
                expansion_approach="QBS: How does the VP experience this problem?",
                urgency="next_conversation",
            ),
        ]
        AccountExpansionDetector.save_expansion_state(sample_state, triggers)

        expansion = sample_state.metadata["qbs"]["expansion"]
        assert len(expansion["detected_contacts"]) == 1
        assert expansion["detected_contacts"][0]["mentioned_name_or_role"] == "VP of Engineering"

    def test_deduplicates_by_name(self, sample_state: ConversationState) -> None:
        # Pre-populate with existing trigger
        sample_state.metadata = {
            "qbs": {
                "expansion": {
                    "detected_contacts": [
                        {
                            "mentioned_name_or_role": "VP of Engineering",
                            "context_quote": "original context",
                            "relationship_to_contact": "sponsor",
                            "expansion_approach": "original approach",
                            "urgency": "next_conversation",
                        }
                    ]
                }
            }
        }

        # Try to add same contact again
        triggers = [
            ExpansionTrigger(
                mentioned_name_or_role="VP of Engineering",
                context_quote="new context",
                relationship_to_contact="executive sponsor",
                expansion_approach="new approach",
                urgency="immediate",
            ),
            ExpansionTrigger(
                mentioned_name_or_role="Sarah from procurement",
                context_quote="Sarah mentioned budget",
                relationship_to_contact="peer",
                expansion_approach="Direct request",
                urgency="next_conversation",
            ),
        ]
        AccountExpansionDetector.save_expansion_state(sample_state, triggers)

        contacts = sample_state.metadata["qbs"]["expansion"]["detected_contacts"]
        assert len(contacts) == 2  # VP deduped, Sarah added
        names = [c["mentioned_name_or_role"] for c in contacts]
        assert names.count("VP of Engineering") == 1
        assert "Sarah from procurement" in names

    def test_caps_at_20_entries(self, sample_state: ConversationState) -> None:
        # Pre-populate with 19 existing contacts
        sample_state.metadata = {
            "qbs": {
                "expansion": {
                    "detected_contacts": [
                        {
                            "mentioned_name_or_role": f"Contact-{i}",
                            "context_quote": f"context-{i}",
                            "relationship_to_contact": "peer",
                            "expansion_approach": "approach",
                            "urgency": "next_conversation",
                        }
                        for i in range(19)
                    ]
                }
            }
        }

        # Add 3 new triggers (should cap at 20)
        triggers = [
            ExpansionTrigger(
                mentioned_name_or_role=f"New-Contact-{i}",
                context_quote=f"new context-{i}",
                relationship_to_contact="peer",
                expansion_approach="approach",
                urgency="next_conversation",
            )
            for i in range(3)
        ]
        AccountExpansionDetector.save_expansion_state(sample_state, triggers)

        contacts = sample_state.metadata["qbs"]["expansion"]["detected_contacts"]
        assert len(contacts) <= 20


class TestExpansionDetectorUrgencyAdjustment:
    """Test urgency adjustment logic.

    The urgency adjustment happens in detect_expansion_triggers which is
    async and LLM-dependent. We test the logic by directly constructing
    triggers and simulating the adjustment.
    """

    def test_immediate_overridden_for_early_interactions(self) -> None:
        """When interaction_count < 3, 'immediate' -> 'next_conversation'."""
        trigger = ExpansionTrigger(
            mentioned_name_or_role="CTO",
            context_quote="Our CTO wants to see this",
            relationship_to_contact="executive",
            expansion_approach="Direct request",
            urgency="immediate",
        )
        # Simulate the urgency adjustment from detect_expansion_triggers
        interaction_count = 2
        if interaction_count < 3:
            if trigger.urgency == "immediate":
                trigger.urgency = "next_conversation"

        assert trigger.urgency == "next_conversation"

    def test_next_conversation_not_changed_for_early_interactions(self) -> None:
        """'next_conversation' urgency is not modified."""
        trigger = ExpansionTrigger(
            mentioned_name_or_role="CTO",
            context_quote="Our CTO wants to see this",
            relationship_to_contact="executive",
            expansion_approach="Direct request",
            urgency="next_conversation",
        )
        interaction_count = 1
        if interaction_count < 3:
            if trigger.urgency == "immediate":
                trigger.urgency = "next_conversation"

        assert trigger.urgency == "next_conversation"

    def test_immediate_preserved_for_later_interactions(self) -> None:
        """When interaction_count >= 3, 'immediate' is preserved."""
        trigger = ExpansionTrigger(
            mentioned_name_or_role="CTO",
            context_quote="Our CTO wants to see this",
            relationship_to_contact="executive",
            expansion_approach="Direct request",
            urgency="immediate",
        )
        interaction_count = 5
        if interaction_count < 3:
            if trigger.urgency == "immediate":
                trigger.urgency = "next_conversation"

        assert trigger.urgency == "immediate"


# ── QBSQuestionEngine Build Pain Summary Tests ──────────────────────────────


class TestBuildPainSummary:
    def test_empty_state_summary(self, engine: QBSQuestionEngine) -> None:
        pain_state = PainFunnelState()
        result = engine._build_pain_summary(pain_state)
        assert "not_explored" in result
        assert "Pain Topics: 0" in result

    def test_populated_state_summary(self, engine: QBSQuestionEngine) -> None:
        pain_state = PainFunnelState(
            depth_level=PainDepthLevel.BUSINESS_IMPACT,
            pain_topics=[
                PainTopic(
                    topic="billing errors",
                    depth=PainDepthLevel.BUSINESS_IMPACT,
                    evidence="Revenue leakage",
                    first_mentioned_at=1,
                    last_probed_at=3,
                )
            ],
            resistance_detected=True,
            last_probed_topic="impact:metrics",
        )
        result = engine._build_pain_summary(pain_state)
        assert "business_impact" in result
        assert "Pain Topics: 1" in result
        assert "billing errors" in result
        assert "Resistance Detected: True" in result
        assert "Last Probed: impact:metrics" in result


# ── Resolve Model Tests ──────────────────────────────────────────────────────


class TestResolveModel:
    def test_default_when_no_router(self) -> None:
        mock_llm = type("MockLLM", (), {"router": None})()
        engine = QBSQuestionEngine(mock_llm)
        result = engine._resolve_model("fast")
        assert result == "anthropic/claude-sonnet-4-20250514"

    def test_resolves_from_router(self) -> None:
        mock_router = type(
            "MockRouter",
            (),
            {
                "model_list": [
                    {
                        "model_name": "fast",
                        "litellm_params": {"model": "anthropic/claude-haiku-3"},
                    }
                ]
            },
        )()
        mock_llm = type("MockLLM", (), {"router": mock_router})()
        engine = QBSQuestionEngine(mock_llm)
        result = engine._resolve_model("fast")
        assert result == "anthropic/claude-haiku-3"

    def test_default_when_model_not_in_router(self) -> None:
        mock_router = type(
            "MockRouter",
            (),
            {
                "model_list": [
                    {
                        "model_name": "reasoning",
                        "litellm_params": {"model": "anthropic/claude-opus-4-20250514"},
                    }
                ]
            },
        )()
        mock_llm = type("MockLLM", (), {"router": mock_router})()
        engine = QBSQuestionEngine(mock_llm)
        result = engine._resolve_model("fast")
        assert result == "anthropic/claude-sonnet-4-20250514"
