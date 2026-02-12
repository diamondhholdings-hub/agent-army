"""Tests for learning module: outcome tracking models, schemas, and service.

Tests OutcomeTracker service with InMemoryOutcomeTracker test double,
model instantiation for all three SQLAlchemy models, schema serialization
roundtrips, and enum/window configuration validation.

Follows the test pattern from tests/test_sales_state.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from collections.abc import AsyncGenerator

import pytest

from src.app.learning.models import (
    CalibrationBinModel,
    FeedbackEntryModel,
    OutcomeRecordModel,
)
from src.app.learning.schemas import (
    CalibrationBin,
    CalibrationCurve,
    CalibrationAdjustment,
    FeedbackEntry,
    FeedbackSource,
    FeedbackTarget,
    OutcomeRecord,
    OutcomeStatus,
    OutcomeType,
    OutcomeWindow,
    SubmitFeedbackRequest,
    SubmitFeedbackResponse,
    OutcomeRecordResponse,
    AnalyticsDashboardResponse,
    CalibrationCurveResponse,
)
from src.app.learning.outcomes import OutcomeTracker


# -- InMemory Test Double ------------------------------------------------------


class InMemoryOutcomeTracker:
    """In-memory test double for OutcomeTracker.

    Stores outcomes in a dict for fast unit testing without database.
    Mirrors OutcomeTracker's interface for recording and resolving outcomes.
    """

    WINDOW_CONFIG = OutcomeTracker.WINDOW_CONFIG

    def __init__(self) -> None:
        self._outcomes: dict[str, OutcomeRecord] = {}
        self._conversation_interaction_counts: dict[str, int] = {}
        self._conversation_deal_stages: dict[str, str] = {}

    async def record_outcome(
        self,
        tenant_id: str,
        conversation_state_id: str,
        action_type: str,
        predicted_confidence: float,
        outcome_type: str,
        action_id: str | None = None,
        metadata: dict | None = None,
    ) -> OutcomeRecord:
        now = datetime.now(timezone.utc)
        window_hours = self.WINDOW_CONFIG.get(outcome_type, 168)
        window_expires_at = now + timedelta(hours=window_hours)

        outcome = OutcomeRecord(
            outcome_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type=action_type,
            action_id=action_id,
            predicted_confidence=predicted_confidence,
            outcome_type=outcome_type,
            outcome_status=OutcomeStatus.PENDING.value,
            window_expires_at=window_expires_at,
            metadata_json=metadata or {},
            created_at=now,
        )
        self._outcomes[outcome.outcome_id] = outcome
        return outcome

    async def resolve_outcome(
        self,
        outcome_id: str,
        tenant_id: str,
        outcome_status: str,
        outcome_score: float | None = None,
        signal_source: str = "automatic",
    ) -> OutcomeRecord:
        outcome = self._outcomes.get(outcome_id)
        if outcome is None:
            raise ValueError(f"Outcome {outcome_id} not found")
        if outcome.outcome_status != OutcomeStatus.PENDING.value:
            raise ValueError(
                f"Outcome {outcome_id} already resolved with status "
                f"'{outcome.outcome_status}', cannot re-resolve"
            )
        outcome.outcome_status = outcome_status
        outcome.outcome_score = outcome_score
        outcome.signal_source = signal_source
        outcome.resolved_at = datetime.now(timezone.utc)
        return outcome

    async def get_pending_outcomes(
        self,
        tenant_id: str | None = None,
        outcome_type: str | None = None,
        expired_only: bool = False,
    ) -> list[OutcomeRecord]:
        results = []
        now = datetime.now(timezone.utc)
        for o in self._outcomes.values():
            if o.outcome_status != OutcomeStatus.PENDING.value:
                continue
            if tenant_id is not None and o.tenant_id != tenant_id:
                continue
            if outcome_type is not None and o.outcome_type != outcome_type:
                continue
            if expired_only and o.window_expires_at and o.window_expires_at >= now:
                continue
            results.append(o)
        return results

    async def get_outcomes_for_conversation(
        self,
        tenant_id: str,
        conversation_state_id: str,
    ) -> list[OutcomeRecord]:
        return [
            o
            for o in self._outcomes.values()
            if o.tenant_id == tenant_id
            and o.conversation_state_id == conversation_state_id
        ]

    async def check_immediate_signals(self, tenant_id: str | None = None) -> int:
        """Simulate immediate signal detection using in-memory state."""
        resolved_count = 0
        now = datetime.now(timezone.utc)

        for outcome in list(self._outcomes.values()):
            if outcome.outcome_status != OutcomeStatus.PENDING.value:
                continue
            if outcome.outcome_type != "email_engagement":
                continue
            if tenant_id is not None and outcome.tenant_id != tenant_id:
                continue

            # Check window expiry
            if outcome.window_expires_at and outcome.window_expires_at < now:
                outcome.outcome_status = OutcomeStatus.EXPIRED.value
                outcome.resolved_at = now
                resolved_count += 1
                continue

            # Check interaction count increase
            initial_count = outcome.metadata_json.get(
                "interaction_count_at_creation", 0
            )
            current_count = self._conversation_interaction_counts.get(
                outcome.conversation_state_id, 0
            )
            if current_count > initial_count:
                outcome.outcome_status = OutcomeStatus.POSITIVE.value
                outcome.outcome_score = 1.0
                outcome.signal_source = "automatic"
                outcome.resolved_at = now
                resolved_count += 1

        return resolved_count

    async def check_deal_progression_signals(
        self, tenant_id: str | None = None
    ) -> int:
        """Simulate deal progression signal detection."""
        stage_order = [
            "prospecting",
            "discovery",
            "qualification",
            "evaluation",
            "negotiation",
            "closed_won",
        ]
        resolved_count = 0
        now = datetime.now(timezone.utc)

        for outcome in list(self._outcomes.values()):
            if outcome.outcome_status != OutcomeStatus.PENDING.value:
                continue
            if outcome.outcome_type != "deal_progression":
                continue
            if tenant_id is not None and outcome.tenant_id != tenant_id:
                continue

            original_stage = outcome.metadata_json.get(
                "deal_stage_at_creation", "prospecting"
            )
            current_stage = self._conversation_deal_stages.get(
                outcome.conversation_state_id, original_stage
            )

            if current_stage in ("closed_lost", "stalled"):
                outcome.outcome_status = OutcomeStatus.NEGATIVE.value
                outcome.outcome_score = 0.0
                outcome.signal_source = "automatic"
                outcome.resolved_at = now
                resolved_count += 1
                continue

            orig_idx = (
                stage_order.index(original_stage)
                if original_stage in stage_order
                else 0
            )
            curr_idx = (
                stage_order.index(current_stage)
                if current_stage in stage_order
                else 0
            )

            if curr_idx > orig_idx:
                stages_advanced = curr_idx - orig_idx
                score = min(stages_advanced * 0.2, 1.0)
                outcome.outcome_status = OutcomeStatus.POSITIVE.value
                outcome.outcome_score = score
                outcome.signal_source = "automatic"
                outcome.resolved_at = now
                resolved_count += 1
                continue

            if outcome.window_expires_at and outcome.window_expires_at < now:
                outcome.outcome_status = OutcomeStatus.EXPIRED.value
                outcome.resolved_at = now
                resolved_count += 1

        return resolved_count

    async def expire_overdue_outcomes(self, tenant_id: str | None = None) -> int:
        """Expire all overdue pending outcomes."""
        expired_count = 0
        now = datetime.now(timezone.utc)

        for outcome in self._outcomes.values():
            if outcome.outcome_status != OutcomeStatus.PENDING.value:
                continue
            if tenant_id is not None and outcome.tenant_id != tenant_id:
                continue
            if outcome.window_expires_at and outcome.window_expires_at < now:
                outcome.outcome_status = OutcomeStatus.EXPIRED.value
                outcome.resolved_at = now
                expired_count += 1

        return expired_count


# -- Fixtures ------------------------------------------------------------------


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def conversation_state_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def tracker() -> InMemoryOutcomeTracker:
    return InMemoryOutcomeTracker()


# -- Test: Outcome Record Creation ---------------------------------------------


class TestOutcomeRecordCreation:
    """Test recording outcomes with correct field initialization."""

    async def test_outcome_record_creation(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Record an outcome and verify all fields set correctly."""
        outcome = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
            action_id="msg-001",
            metadata={"subject": "Follow up"},
        )

        assert outcome.tenant_id == tenant_id
        assert outcome.conversation_state_id == conversation_state_id
        assert outcome.action_type == "send_email"
        assert outcome.predicted_confidence == 0.8
        assert outcome.outcome_type == "email_engagement"
        assert outcome.outcome_status == OutcomeStatus.PENDING.value
        assert outcome.action_id == "msg-001"
        assert outcome.outcome_score is None
        assert outcome.resolved_at is None
        assert outcome.window_expires_at is not None
        assert outcome.metadata_json == {"subject": "Follow up"}
        assert outcome.created_at is not None

    async def test_window_expires_at_calculated(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Verify window_expires_at is calculated from WINDOW_CONFIG."""
        now = datetime.now(timezone.utc)

        outcome = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.7,
            outcome_type="email_engagement",
        )

        # 24 hour window for email_engagement
        expected_window = now + timedelta(hours=24)
        # Allow 2 second tolerance for test execution time
        assert abs((outcome.window_expires_at - expected_window).total_seconds()) < 2


# -- Test: Outcome Resolution --------------------------------------------------


class TestOutcomeResolution:
    """Test resolving pending outcomes."""

    async def test_outcome_resolution(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Record then resolve an outcome, verify status changed."""
        outcome = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
        )

        resolved = await tracker.resolve_outcome(
            outcome_id=outcome.outcome_id,
            tenant_id=tenant_id,
            outcome_status=OutcomeStatus.POSITIVE.value,
            outcome_score=1.0,
            signal_source="automatic",
        )

        assert resolved.outcome_status == OutcomeStatus.POSITIVE.value
        assert resolved.outcome_score == 1.0
        assert resolved.signal_source == "automatic"
        assert resolved.resolved_at is not None

    async def test_double_resolution_prevented(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Resolve same outcome twice -- should raise ValueError."""
        outcome = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
        )

        await tracker.resolve_outcome(
            outcome_id=outcome.outcome_id,
            tenant_id=tenant_id,
            outcome_status=OutcomeStatus.POSITIVE.value,
        )

        with pytest.raises(ValueError, match="already resolved"):
            await tracker.resolve_outcome(
                outcome_id=outcome.outcome_id,
                tenant_id=tenant_id,
                outcome_status=OutcomeStatus.NEGATIVE.value,
            )


# -- Test: Window Expiry Calculation -------------------------------------------


class TestWindowExpiryCalculation:
    """Test that each outcome_type gets the correct window duration."""

    async def test_window_expiry_calculation(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Verify each outcome_type gets correct window hours."""
        cases = [
            ("email_engagement", 24),
            ("deal_progression", 720),
            ("meeting_outcome", 168),
            ("escalation_result", 168),
        ]

        for outcome_type, expected_hours in cases:
            now = datetime.now(timezone.utc)
            outcome = await tracker.record_outcome(
                tenant_id=tenant_id,
                conversation_state_id=conversation_state_id,
                action_type="send_email",
                predicted_confidence=0.5,
                outcome_type=outcome_type,
            )

            expected_window = now + timedelta(hours=expected_hours)
            delta = abs(
                (outcome.window_expires_at - expected_window).total_seconds()
            )
            assert delta < 2, (
                f"Window for {outcome_type}: expected ~{expected_hours}h, "
                f"got delta of {delta}s"
            )


# -- Test: Pending Outcomes Filtering ------------------------------------------


class TestGetPendingOutcomesFiltered:
    """Test querying pending outcomes with filters."""

    async def test_get_pending_outcomes_filtered(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Create outcomes with different types/statuses, verify filtering."""
        # Create 3 outcomes: 2 email, 1 deal
        o1 = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.7,
            outcome_type="email_engagement",
        )
        o2 = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
        )
        o3 = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="qualify",
            predicted_confidence=0.6,
            outcome_type="deal_progression",
        )

        # Resolve one email outcome
        await tracker.resolve_outcome(
            outcome_id=o1.outcome_id,
            tenant_id=tenant_id,
            outcome_status=OutcomeStatus.POSITIVE.value,
        )

        # Filter: all pending
        pending = await tracker.get_pending_outcomes(tenant_id=tenant_id)
        assert len(pending) == 2

        # Filter: pending email only
        email_pending = await tracker.get_pending_outcomes(
            tenant_id=tenant_id, outcome_type="email_engagement"
        )
        assert len(email_pending) == 1
        assert email_pending[0].outcome_id == o2.outcome_id

        # Filter: pending deal only
        deal_pending = await tracker.get_pending_outcomes(
            tenant_id=tenant_id, outcome_type="deal_progression"
        )
        assert len(deal_pending) == 1
        assert deal_pending[0].outcome_id == o3.outcome_id

    async def test_get_outcomes_for_conversation(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str
    ) -> None:
        """Get all outcomes for a specific conversation."""
        conv_id1 = str(uuid.uuid4())
        conv_id2 = str(uuid.uuid4())

        await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conv_id1,
            action_type="send_email",
            predicted_confidence=0.7,
            outcome_type="email_engagement",
        )
        await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conv_id1,
            action_type="qualify",
            predicted_confidence=0.6,
            outcome_type="deal_progression",
        )
        await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conv_id2,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
        )

        results = await tracker.get_outcomes_for_conversation(
            tenant_id=tenant_id, conversation_state_id=conv_id1
        )
        assert len(results) == 2
        assert all(r.conversation_state_id == conv_id1 for r in results)


# -- Test: Expire Overdue Outcomes ---------------------------------------------


class TestExpireOverdueOutcomes:
    """Test bulk expiry of overdue pending outcomes."""

    async def test_expire_overdue_outcomes(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Create outcomes with past window, call expire, verify status=EXPIRED."""
        o1 = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.7,
            outcome_type="email_engagement",
        )
        # Manually set window to the past
        o1.window_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        o2 = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="qualify",
            predicted_confidence=0.6,
            outcome_type="deal_progression",
        )
        # This one is still within window (don't expire)

        expired_count = await tracker.expire_overdue_outcomes(tenant_id=tenant_id)

        assert expired_count == 1
        assert o1.outcome_status == OutcomeStatus.EXPIRED.value
        assert o1.resolved_at is not None
        assert o2.outcome_status == OutcomeStatus.PENDING.value


# -- Test: Immediate Signal Detection ------------------------------------------


class TestImmediateSignalDetection:
    """Test email reply detection via interaction count increase."""

    async def test_immediate_signal_detection_reply(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Simulate reply detection (interaction count increased) resolves to POSITIVE."""
        outcome = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
            metadata={"interaction_count_at_creation": 3},
        )

        # Simulate reply: increase interaction count
        tracker._conversation_interaction_counts[conversation_state_id] = 5

        resolved_count = await tracker.check_immediate_signals(
            tenant_id=tenant_id
        )

        assert resolved_count == 1
        assert outcome.outcome_status == OutcomeStatus.POSITIVE.value
        assert outcome.outcome_score == 1.0
        assert outcome.signal_source == "automatic"


# -- Test: Deal Progression Signal Detection -----------------------------------


class TestDealProgressionSignalDetection:
    """Test deal stage advancement detection."""

    async def test_deal_progression_signal_detection(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Simulate stage advance resolves to POSITIVE."""
        outcome = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="qualify",
            predicted_confidence=0.7,
            outcome_type="deal_progression",
            metadata={"deal_stage_at_creation": "discovery"},
        )

        # Simulate stage advancement
        tracker._conversation_deal_stages[conversation_state_id] = "qualification"

        resolved_count = await tracker.check_deal_progression_signals(
            tenant_id=tenant_id
        )

        assert resolved_count == 1
        assert outcome.outcome_status == OutcomeStatus.POSITIVE.value
        assert outcome.outcome_score == 0.2  # 1 stage * 0.2
        assert outcome.signal_source == "automatic"

    async def test_deal_progression_negative_closed_lost(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Stage moving to closed_lost resolves to NEGATIVE."""
        outcome = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="qualify",
            predicted_confidence=0.7,
            outcome_type="deal_progression",
            metadata={"deal_stage_at_creation": "evaluation"},
        )

        tracker._conversation_deal_stages[conversation_state_id] = "closed_lost"

        resolved_count = await tracker.check_deal_progression_signals(
            tenant_id=tenant_id
        )

        assert resolved_count == 1
        assert outcome.outcome_status == OutcomeStatus.NEGATIVE.value
        assert outcome.outcome_score == 0.0

    async def test_deal_progression_multi_stage_advance(
        self, tracker: InMemoryOutcomeTracker, tenant_id: str, conversation_state_id: str
    ) -> None:
        """Multiple stage advancement gives higher score."""
        outcome = await tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="qualify",
            predicted_confidence=0.6,
            outcome_type="deal_progression",
            metadata={"deal_stage_at_creation": "prospecting"},
        )

        # Jump from prospecting to evaluation (3 stages)
        tracker._conversation_deal_stages[conversation_state_id] = "evaluation"

        resolved_count = await tracker.check_deal_progression_signals(
            tenant_id=tenant_id
        )

        assert resolved_count == 1
        assert outcome.outcome_status == OutcomeStatus.POSITIVE.value
        assert outcome.outcome_score == pytest.approx(0.6)  # 3 stages * 0.2


# -- Test: Model Instantiation ------------------------------------------------


class TestModelInstantiation:
    """Verify all three SQLAlchemy models can be instantiated."""

    def test_model_instantiation(self) -> None:
        """Verify all three SQLAlchemy models can be instantiated."""
        tid = uuid.uuid4()
        cid = uuid.uuid4()

        # OutcomeRecordModel
        outcome_model = OutcomeRecordModel(
            id=uuid.uuid4(),
            tenant_id=tid,
            conversation_state_id=cid,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
            outcome_status="pending",
            metadata_json={},
        )
        assert outcome_model.action_type == "send_email"
        assert outcome_model.predicted_confidence == 0.8
        assert outcome_model.outcome_status == "pending"

        # FeedbackEntryModel
        feedback_model = FeedbackEntryModel(
            id=uuid.uuid4(),
            tenant_id=tid,
            conversation_state_id=cid,
            target_type="message",
            target_id="msg-001",
            source="inline",
            rating=1,
            reviewer_id=uuid.uuid4(),
            reviewer_role="rep",
            metadata_json={},
        )
        assert feedback_model.target_type == "message"
        assert feedback_model.rating == 1
        assert feedback_model.reviewer_role == "rep"

        # CalibrationBinModel
        calibration_model = CalibrationBinModel(
            id=uuid.uuid4(),
            tenant_id=tid,
            action_type="send_email",
            bin_index=3,
            bin_lower=0.3,
            bin_upper=0.4,
            sample_count=50,
            outcome_sum=18.0,
            actual_rate=0.36,
        )
        assert calibration_model.bin_index == 3
        assert calibration_model.bin_lower == 0.3
        assert calibration_model.sample_count == 50
        assert calibration_model.actual_rate == 0.36


# -- Test: Schema Serialization Roundtrip --------------------------------------


class TestSchemaSerializationRoundtrip:
    """Verify schemas serialize/deserialize correctly."""

    def test_outcome_record_roundtrip(self, tenant_id: str) -> None:
        """OutcomeRecord serialize/deserialize roundtrip."""
        record = OutcomeRecord(
            tenant_id=tenant_id,
            conversation_state_id=str(uuid.uuid4()),
            action_type="send_email",
            predicted_confidence=0.85,
            outcome_type="email_engagement",
            metadata_json={"key": "value"},
        )

        data = record.model_dump(mode="json")
        restored = OutcomeRecord(**data)

        assert restored.tenant_id == record.tenant_id
        assert restored.action_type == record.action_type
        assert restored.predicted_confidence == record.predicted_confidence
        assert restored.outcome_status == OutcomeStatus.PENDING.value
        assert restored.metadata_json == {"key": "value"}

    def test_feedback_entry_roundtrip(self, tenant_id: str) -> None:
        """FeedbackEntry serialize/deserialize roundtrip."""
        entry = FeedbackEntry(
            tenant_id=tenant_id,
            conversation_state_id=str(uuid.uuid4()),
            target_type=FeedbackTarget.MESSAGE.value,
            target_id="msg-001",
            source=FeedbackSource.INLINE.value,
            rating=1,
            comment="Good response",
            reviewer_id=str(uuid.uuid4()),
            reviewer_role="rep",
        )

        data = entry.model_dump(mode="json")
        restored = FeedbackEntry(**data)

        assert restored.tenant_id == entry.tenant_id
        assert restored.target_type == "message"
        assert restored.rating == 1
        assert restored.comment == "Good response"

    def test_calibration_bin_roundtrip(self, tenant_id: str) -> None:
        """CalibrationBin serialize/deserialize roundtrip."""
        bin_data = CalibrationBin(
            tenant_id=tenant_id,
            action_type="send_email",
            bin_index=5,
            bin_lower=0.5,
            bin_upper=0.6,
            sample_count=100,
            outcome_sum=55.0,
            actual_rate=0.55,
            brier_contribution=0.02,
        )

        data = bin_data.model_dump(mode="json")
        restored = CalibrationBin(**data)

        assert restored.bin_index == 5
        assert restored.sample_count == 100
        assert restored.actual_rate == 0.55
        assert restored.brier_contribution == 0.02


# -- Test: OutcomeWindow Classmethods ------------------------------------------


class TestOutcomeWindowClassmethods:
    """Verify OutcomeWindow factory methods return correct hours."""

    def test_outcome_window_immediate(self) -> None:
        window = OutcomeWindow.immediate()
        assert window.window_hours == 24
        assert window.outcome_type == "email_engagement"

    def test_outcome_window_engagement(self) -> None:
        window = OutcomeWindow.engagement()
        assert window.window_hours == 168
        assert window.outcome_type == "meeting_outcome"

    def test_outcome_window_deal_progression(self) -> None:
        window = OutcomeWindow.deal_progression()
        assert window.window_hours == 720
        assert window.outcome_type == "deal_progression"

    def test_outcome_window_custom_action_type(self) -> None:
        window = OutcomeWindow.immediate(action_type="send_chat")
        assert window.action_type == "send_chat"
        assert window.window_hours == 24


# -- Test: Enum Values ---------------------------------------------------------


class TestOutcomeStatusEnumValues:
    """Verify all OutcomeStatus enum values match expected strings."""

    def test_outcome_status_enum_values(self) -> None:
        assert OutcomeStatus.PENDING.value == "pending"
        assert OutcomeStatus.POSITIVE.value == "positive"
        assert OutcomeStatus.NEGATIVE.value == "negative"
        assert OutcomeStatus.AMBIGUOUS.value == "ambiguous"
        assert OutcomeStatus.EXPIRED.value == "expired"

    def test_outcome_type_enum_values(self) -> None:
        assert OutcomeType.EMAIL_ENGAGEMENT.value == "email_engagement"
        assert OutcomeType.DEAL_PROGRESSION.value == "deal_progression"
        assert OutcomeType.MEETING_OUTCOME.value == "meeting_outcome"
        assert OutcomeType.ESCALATION_RESULT.value == "escalation_result"

    def test_feedback_target_enum_values(self) -> None:
        assert FeedbackTarget.MESSAGE.value == "message"
        assert FeedbackTarget.DECISION.value == "decision"
        assert FeedbackTarget.CONVERSATION.value == "conversation"

    def test_feedback_source_enum_values(self) -> None:
        assert FeedbackSource.INLINE.value == "inline"
        assert FeedbackSource.DASHBOARD.value == "dashboard"


# -- Test: API Request/Response Schemas ----------------------------------------


class TestAPISchemas:
    """Verify API request/response schemas work correctly."""

    def test_submit_feedback_request_validation(self) -> None:
        """SubmitFeedbackRequest validates rating bounds."""
        req = SubmitFeedbackRequest(
            conversation_state_id=str(uuid.uuid4()),
            target_type="message",
            target_id="msg-001",
            source="inline",
            rating=1,
        )
        assert req.rating == 1
        assert req.comment is None

    def test_submit_feedback_request_rating_bounds(self) -> None:
        """Rating must be between -1 and 5."""
        with pytest.raises(Exception):
            SubmitFeedbackRequest(
                conversation_state_id=str(uuid.uuid4()),
                target_type="message",
                target_id="msg-001",
                source="inline",
                rating=10,  # Too high
            )

    def test_submit_feedback_response(self) -> None:
        resp = SubmitFeedbackResponse(feedback_id="fb-001")
        assert resp.status == "recorded"

    def test_calibration_curve_response(self) -> None:
        resp = CalibrationCurveResponse(
            action_type="send_email",
            brier_score=0.12,
            sample_count=500,
            is_calibrated=True,
        )
        assert resp.is_calibrated is True
        assert resp.brier_score == 0.12

    def test_analytics_dashboard_response(self) -> None:
        resp = AnalyticsDashboardResponse(
            role="manager",
            metrics={"response_rate": 0.65},
        )
        assert resp.role == "manager"
        assert resp.period == "last_30_days"
