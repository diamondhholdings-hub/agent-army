"""Tests for sales conversation state persistence and deal stage transitions.

Tests ConversationStateModel instantiation, _model_to_state/_state_to_model
serialization roundtrip, deal stage transition validation, and repository
list filtering logic.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.sales.schemas import (
    BANTSignals,
    Channel,
    ConversationState,
    DealStage,
    MEDDICSignals,
    NextAction,
    PersonaType,
    QualificationState,
)
from src.app.agents.sales.state_repository import (
    VALID_TRANSITIONS,
    InvalidStageTransitionError,
    _model_to_state,
    _state_to_model,
    validate_stage_transition,
)
from src.app.models.sales import ConversationStateModel


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_state(sample_tenant_id: str) -> ConversationState:
    return ConversationState(
        state_id=str(uuid.uuid4()),
        tenant_id=sample_tenant_id,
        account_id="acct-001",
        contact_id="contact-001",
        contact_email="john@example.com",
        contact_name="John Doe",
        deal_stage=DealStage.DISCOVERY,
        persona_type=PersonaType.MANAGER,
        qualification=QualificationState(
            bant=BANTSignals(
                budget_identified=True,
                budget_range="100k-200k",
                budget_evidence="Mentioned budget of 100-200k in Q2 planning",
                budget_confidence=0.8,
                need_identified=True,
                need_description="Reduce billing errors by 50%",
                need_evidence="Said 'we lose $50k/month to billing mistakes'",
                need_confidence=0.9,
            ),
            meddic=MEDDICSignals(
                pain_identified=True,
                pain_description="Billing errors causing revenue leakage",
                pain_evidence="'We lose $50k/month to billing mistakes'",
                pain_confidence=0.9,
                decision_criteria=["accuracy", "integration speed"],
                decision_criteria_identified=True,
                decision_criteria_confidence=0.7,
            ),
            overall_confidence=0.75,
            key_insights=["Budget confirmed in 100-200k range", "Pain point validated"],
            recommended_next_questions=[
                "How does your team currently handle billing reconciliation?",
                "What does the ideal timeline look like for implementing a solution?",
            ],
        ),
        interaction_count=3,
        last_interaction=datetime(2026, 2, 10, 14, 30, tzinfo=timezone.utc),
        last_channel=Channel.EMAIL,
        escalated=False,
        confidence_score=0.75,
        next_actions=["Send follow-up email with case study"],
        metadata={"source": "inbound_lead"},
    )


@pytest.fixture
def sample_qualification() -> QualificationState:
    return QualificationState(
        bant=BANTSignals(
            budget_identified=True,
            budget_range="100k-200k",
            budget_confidence=0.8,
        ),
        meddic=MEDDICSignals(
            pain_identified=True,
            pain_description="Billing errors",
            pain_confidence=0.9,
        ),
        overall_confidence=0.7,
        key_insights=["Budget confirmed"],
    )


# ── Model Instantiation Tests ────────────────────────────────────────────────


class TestConversationStateModel:
    """Test that ConversationStateModel can be instantiated with all fields."""

    def test_model_instantiation_with_all_fields(self, sample_tenant_id: str) -> None:
        model = ConversationStateModel(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(sample_tenant_id),
            account_id="acct-001",
            contact_id="contact-001",
            contact_email="john@example.com",
            contact_name="John Doe",
            deal_stage="discovery",
            persona_type="manager",
            qualification_data={"bant": {}, "meddic": {}},
            interaction_count=5,
            last_interaction=datetime.now(timezone.utc),
            last_channel="email",
            escalated=False,
            escalation_reason=None,
            confidence_score=0.8,
            next_actions=[],
            follow_up_scheduled=None,
            metadata_json={"source": "web"},
        )

        assert model.account_id == "acct-001"
        assert model.contact_email == "john@example.com"
        assert model.deal_stage == "discovery"
        assert model.persona_type == "manager"
        assert model.interaction_count == 5
        assert model.escalated is False
        assert model.confidence_score == 0.8

    def test_model_instantiation_with_defaults(self, sample_tenant_id: str) -> None:
        model = ConversationStateModel(
            tenant_id=uuid.UUID(sample_tenant_id),
            account_id="acct-002",
            contact_id="contact-002",
            contact_email="jane@example.com",
        )

        assert model.account_id == "acct-002"
        assert model.contact_email == "jane@example.com"

    def test_model_table_config(self) -> None:
        assert ConversationStateModel.__tablename__ == "conversation_states"
        # Verify schema is set to "tenant" for schema_translate_map
        table_args = ConversationStateModel.__table_args__
        schema_dict = next(a for a in table_args if isinstance(a, dict))
        assert schema_dict["schema"] == "tenant"


# ── Serialization Tests ──────────────────────────────────────────────────────


class TestModelToState:
    """Test _model_to_state correctly deserializes qualification_data JSON."""

    def test_deserializes_qualification_data(self, sample_tenant_id: str) -> None:
        model = ConversationStateModel(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(sample_tenant_id),
            account_id="acct-001",
            contact_id="contact-001",
            contact_email="john@example.com",
            contact_name="John Doe",
            deal_stage="qualification",
            persona_type="c_suite",
            qualification_data={
                "bant": {
                    "budget_identified": True,
                    "budget_range": "500k",
                    "budget_confidence": 0.9,
                },
                "meddic": {
                    "champion_identified": True,
                    "champion_contact": "Sarah VP",
                    "champion_confidence": 0.85,
                },
                "overall_confidence": 0.8,
                "key_insights": ["Large budget confirmed"],
                "recommended_next_questions": ["What is the decision process?"],
            },
            interaction_count=7,
            last_interaction=datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc),
            last_channel="email",
            escalated=False,
            confidence_score=0.8,
            next_actions=[{"description": "Follow up on proposal"}],
            metadata_json={"source": "referral"},
            created_at=datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
        )

        state = _model_to_state(model)

        assert state.deal_stage == DealStage.QUALIFICATION
        assert state.persona_type == PersonaType.C_SUITE
        assert state.qualification.bant.budget_identified is True
        assert state.qualification.bant.budget_range == "500k"
        assert state.qualification.bant.budget_confidence == 0.9
        assert state.qualification.meddic.champion_identified is True
        assert state.qualification.meddic.champion_contact == "Sarah VP"
        assert state.qualification.overall_confidence == 0.8
        assert state.qualification.key_insights == ["Large budget confirmed"]
        assert state.interaction_count == 7
        assert state.last_channel == Channel.EMAIL
        assert state.metadata == {"source": "referral"}

    def test_deserializes_empty_qualification(self, sample_tenant_id: str) -> None:
        model = ConversationStateModel(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(sample_tenant_id),
            account_id="acct-002",
            contact_id="contact-002",
            contact_email="jane@example.com",
            deal_stage="prospecting",
            persona_type="manager",
            qualification_data={},
            interaction_count=0,
            escalated=False,
            confidence_score=0.5,
            next_actions=[],
            metadata_json={},
            created_at=datetime.now(timezone.utc),
        )

        state = _model_to_state(model)

        assert state.qualification.bant.budget_identified is False
        assert state.qualification.meddic.pain_identified is False
        assert state.qualification.overall_confidence == 0.5

    def test_handles_none_optional_fields(self, sample_tenant_id: str) -> None:
        model = ConversationStateModel(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(sample_tenant_id),
            account_id="acct-003",
            contact_id="contact-003",
            contact_email="bob@example.com",
            deal_stage="prospecting",
            persona_type="ic",
            qualification_data=None,
            interaction_count=0,
            last_interaction=None,
            last_channel=None,
            escalated=False,
            confidence_score=0.5,
            next_actions=None,
            metadata_json=None,
            created_at=datetime.now(timezone.utc),
        )

        state = _model_to_state(model)

        assert state.last_interaction is None
        assert state.last_channel is None
        assert state.qualification.bant.budget_identified is False
        assert state.next_actions == []


class TestStateToModel:
    """Test _state_to_model correctly serializes QualificationState to JSON."""

    def test_serializes_qualification_to_json(self, sample_state: ConversationState) -> None:
        model_dict = _state_to_model(sample_state)

        assert model_dict["account_id"] == "acct-001"
        assert model_dict["contact_email"] == "john@example.com"
        assert model_dict["deal_stage"] == "discovery"
        assert model_dict["persona_type"] == "manager"
        assert model_dict["last_channel"] == "email"
        assert model_dict["escalated"] is False
        assert model_dict["metadata_json"] == {"source": "inbound_lead"}

        # Check qualification_data is a dict (JSON-serializable)
        qual = model_dict["qualification_data"]
        assert isinstance(qual, dict)
        assert qual["bant"]["budget_identified"] is True
        assert qual["bant"]["budget_range"] == "100k-200k"
        assert qual["bant"]["budget_confidence"] == 0.8
        assert qual["meddic"]["pain_identified"] is True
        assert qual["meddic"]["pain_confidence"] == 0.9
        assert qual["overall_confidence"] == 0.75
        assert "Budget confirmed in 100-200k range" in qual["key_insights"]

    def test_roundtrip_serialization(self, sample_state: ConversationState, sample_tenant_id: str) -> None:
        """Serialize state to model dict, create model, deserialize back -- should match."""
        model_dict = _state_to_model(sample_state)
        model = ConversationStateModel(**model_dict)
        restored = _model_to_state(model)

        assert restored.tenant_id == sample_state.tenant_id
        assert restored.account_id == sample_state.account_id
        assert restored.contact_id == sample_state.contact_id
        assert restored.deal_stage == sample_state.deal_stage
        assert restored.persona_type == sample_state.persona_type
        assert restored.qualification.bant.budget_identified == sample_state.qualification.bant.budget_identified
        assert restored.qualification.bant.budget_range == sample_state.qualification.bant.budget_range
        assert restored.qualification.meddic.pain_identified == sample_state.qualification.meddic.pain_identified
        assert restored.interaction_count == sample_state.interaction_count
        assert restored.escalated == sample_state.escalated
        assert restored.confidence_score == sample_state.confidence_score


# ── Deal Stage Transition Tests ──────────────────────────────────────────────


class TestDealStageTransitions:
    """Test that deal stage transitions follow the defined rules."""

    def test_valid_forward_transitions(self) -> None:
        """Test all valid forward transitions work."""
        valid_chains = [
            (DealStage.PROSPECTING, DealStage.DISCOVERY),
            (DealStage.DISCOVERY, DealStage.QUALIFICATION),
            (DealStage.QUALIFICATION, DealStage.EVALUATION),
            (DealStage.EVALUATION, DealStage.NEGOTIATION),
            (DealStage.NEGOTIATION, DealStage.CLOSED_WON),
            (DealStage.NEGOTIATION, DealStage.CLOSED_LOST),
        ]
        for from_stage, to_stage in valid_chains:
            validate_stage_transition(from_stage, to_stage)  # Should not raise

    def test_same_stage_transition_is_valid(self) -> None:
        """Same stage is a no-op, always valid."""
        for stage in DealStage:
            validate_stage_transition(stage, stage)  # Should not raise

    def test_any_active_stage_can_go_to_stalled(self) -> None:
        """Any non-terminal stage can transition to STALLED."""
        active_stages = [
            DealStage.PROSPECTING,
            DealStage.DISCOVERY,
            DealStage.QUALIFICATION,
            DealStage.EVALUATION,
            DealStage.NEGOTIATION,
        ]
        for stage in active_stages:
            validate_stage_transition(stage, DealStage.STALLED)

    def test_stalled_can_resume_to_active_stages(self) -> None:
        """STALLED can resume to any non-terminal stage."""
        active_stages = [
            DealStage.PROSPECTING,
            DealStage.DISCOVERY,
            DealStage.QUALIFICATION,
            DealStage.EVALUATION,
            DealStage.NEGOTIATION,
        ]
        for stage in active_stages:
            validate_stage_transition(DealStage.STALLED, stage)

    def test_cannot_skip_stages(self) -> None:
        """PROSPECTING cannot jump directly to NEGOTIATION or beyond."""
        with pytest.raises(InvalidStageTransitionError):
            validate_stage_transition(DealStage.PROSPECTING, DealStage.NEGOTIATION)

        with pytest.raises(InvalidStageTransitionError):
            validate_stage_transition(DealStage.PROSPECTING, DealStage.QUALIFICATION)

        with pytest.raises(InvalidStageTransitionError):
            validate_stage_transition(DealStage.DISCOVERY, DealStage.NEGOTIATION)

    def test_terminal_stages_cannot_transition(self) -> None:
        """CLOSED_WON and CLOSED_LOST are terminal -- no transitions out."""
        for terminal in [DealStage.CLOSED_WON, DealStage.CLOSED_LOST]:
            for stage in DealStage:
                if stage == terminal:
                    continue  # Same-stage is always valid
                with pytest.raises(InvalidStageTransitionError):
                    validate_stage_transition(terminal, stage)

    def test_invalid_transition_error_message(self) -> None:
        """Error message includes from/to stages and allowed transitions."""
        with pytest.raises(InvalidStageTransitionError) as exc_info:
            validate_stage_transition(DealStage.PROSPECTING, DealStage.NEGOTIATION)

        error = exc_info.value
        assert error.from_stage == DealStage.PROSPECTING
        assert error.to_stage == DealStage.NEGOTIATION
        assert "prospecting" in str(error).lower()
        assert "negotiation" in str(error).lower()


# ── VALID_TRANSITIONS Coverage ───────────────────────────────────────────────


class TestValidTransitionsCompleteness:
    """Ensure VALID_TRANSITIONS covers all DealStage values."""

    def test_all_stages_have_transition_entry(self) -> None:
        for stage in DealStage:
            assert stage in VALID_TRANSITIONS, f"Missing VALID_TRANSITIONS entry for {stage}"

    def test_terminal_stages_have_empty_transitions(self) -> None:
        assert VALID_TRANSITIONS[DealStage.CLOSED_WON] == set()
        assert VALID_TRANSITIONS[DealStage.CLOSED_LOST] == set()
