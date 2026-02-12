"""Integration tests for the learning system end-to-end pipeline.

Tests the full learning pipeline: outcome recording, feedback submission,
calibration updates, analytics dashboards, coaching patterns, scheduler
task definitions, and API endpoint wiring.

Uses in-memory test doubles for all services, matching the pattern from
tests/test_sales_integration.py and tests/test_learning_outcomes.py.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.app.learning.schemas import (
    CalibrationAdjustment,
    CalibrationCurve,
    CoachingPattern,
    FeedbackEntry,
    FeedbackSource,
    FeedbackTarget,
    OutcomeRecord,
    OutcomeStatus,
)


# ── In-Memory Test Doubles ───────────────────────────────────────────────────


class InMemoryOutcomeTracker:
    """In-memory OutcomeTracker for integration testing."""

    WINDOW_CONFIG = {
        "email_engagement": 24,
        "deal_progression": 720,
        "meeting_outcome": 168,
        "escalation_result": 168,
    }

    def __init__(self) -> None:
        self._outcomes: dict[str, OutcomeRecord] = {}

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
        outcome = OutcomeRecord(
            outcome_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type=action_type,
            action_id=action_id,
            predicted_confidence=predicted_confidence,
            outcome_type=outcome_type,
            outcome_status=OutcomeStatus.PENDING.value,
            window_expires_at=now + timedelta(hours=window_hours),
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
            raise ValueError(f"Outcome {outcome_id} already resolved")
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
        now = datetime.now(timezone.utc)
        return [
            o for o in self._outcomes.values()
            if o.outcome_status == OutcomeStatus.PENDING.value
            and (tenant_id is None or o.tenant_id == tenant_id)
            and (outcome_type is None or o.outcome_type == outcome_type)
            and (not expired_only or (o.window_expires_at and o.window_expires_at < now))
        ]

    async def get_outcomes_for_conversation(
        self, tenant_id: str, conversation_state_id: str
    ) -> list[OutcomeRecord]:
        return [
            o for o in self._outcomes.values()
            if o.tenant_id == tenant_id
            and o.conversation_state_id == conversation_state_id
        ]

    async def check_immediate_signals(self, tenant_id: str | None = None) -> int:
        return 0

    async def check_deal_progression_signals(self, tenant_id: str | None = None) -> int:
        return 0

    async def expire_overdue_outcomes(self, tenant_id: str | None = None) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for o in self._outcomes.values():
            if (o.outcome_status == OutcomeStatus.PENDING.value
                    and o.window_expires_at and o.window_expires_at < now):
                o.outcome_status = OutcomeStatus.EXPIRED.value
                o.resolved_at = now
                count += 1
        return count


class InMemoryFeedbackCollector:
    """In-memory FeedbackCollector for integration testing."""

    INLINE_RATING_RANGE = (-1, 1)
    DASHBOARD_RATING_RANGE = (1, 5)
    VALID_TARGET_TYPES = {t.value for t in FeedbackTarget}
    VALID_SOURCES = {s.value for s in FeedbackSource}

    def __init__(self) -> None:
        self._entries: list[FeedbackEntry] = []

    async def record_feedback(
        self,
        tenant_id: str,
        conversation_state_id: str,
        target_type: str,
        target_id: str,
        source: str,
        rating: int,
        reviewer_id: str,
        reviewer_role: str,
        outcome_record_id: str | None = None,
        comment: str | None = None,
        metadata: dict | None = None,
    ) -> FeedbackEntry:
        if target_type not in self.VALID_TARGET_TYPES:
            raise ValueError(f"Invalid target_type '{target_type}'")
        if source not in self.VALID_SOURCES:
            raise ValueError(f"Invalid source '{source}'")
        if source == FeedbackSource.INLINE.value:
            if not (self.INLINE_RATING_RANGE[0] <= rating <= self.INLINE_RATING_RANGE[1]):
                raise ValueError(f"Inline rating must be between -1 and 1, got {rating}")
        elif source == FeedbackSource.DASHBOARD.value:
            if not (self.DASHBOARD_RATING_RANGE[0] <= rating <= self.DASHBOARD_RATING_RANGE[1]):
                raise ValueError(f"Dashboard rating must be between 1 and 5, got {rating}")

        entry = FeedbackEntry(
            feedback_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            outcome_record_id=outcome_record_id,
            target_type=target_type,
            target_id=target_id,
            source=source,
            rating=rating,
            comment=comment,
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
            metadata_json=metadata or {},
        )
        self._entries.append(entry)
        return entry

    async def get_feedback_for_conversation(
        self, tenant_id: str, conversation_state_id: str
    ) -> list[FeedbackEntry]:
        return [
            e for e in self._entries
            if e.tenant_id == tenant_id
            and e.conversation_state_id == conversation_state_id
        ]

    async def get_feedback_summary(self, tenant_id: str, days: int = 30) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        filtered = [
            e for e in self._entries
            if e.tenant_id == tenant_id and e.created_at >= cutoff
        ]
        if not filtered:
            return {
                "total_feedback_count": 0,
                "average_rating": 0.0,
                "rating_distribution": {},
                "by_target_type": {},
                "by_source": {},
                "by_reviewer_role": {},
                "feedback_rate_trend": [],
            }
        total = len(filtered)
        avg = sum(e.rating for e in filtered) / total
        return {
            "total_feedback_count": total,
            "average_rating": round(avg, 2),
            "rating_distribution": {},
            "by_target_type": {},
            "by_source": {},
            "by_reviewer_role": {},
            "feedback_rate_trend": [],
        }


class InMemoryCalibrationEngine:
    """In-memory CalibrationEngine for integration testing."""

    N_BINS = 10
    BIN_EDGES = np.linspace(0.0, 1.0, 11)
    MIN_SAMPLES_PER_BIN = 10
    MISCALIBRATION_THRESHOLD = 0.15

    def __init__(self) -> None:
        self._bins: dict[tuple[str, str, int], dict] = {}

    async def initialize_bins(self, tenant_id: str, action_type: str) -> None:
        for i in range(self.N_BINS):
            key = (tenant_id, action_type, i)
            if key not in self._bins:
                self._bins[key] = {
                    "bin_index": i,
                    "bin_lower": float(self.BIN_EDGES[i]),
                    "bin_upper": float(self.BIN_EDGES[i + 1]),
                    "sample_count": 0,
                    "outcome_sum": 0.0,
                    "actual_rate": None,
                    "brier_contribution": None,
                }

    async def update_calibration(
        self, tenant_id: str, action_type: str,
        predicted_confidence: float, actual_outcome: bool,
    ) -> None:
        await self.initialize_bins(tenant_id, action_type)
        confidence = max(0.0, min(1.0, predicted_confidence))
        bin_idx = int(np.digitize(confidence, self.BIN_EDGES[1:]))
        bin_idx = max(0, min(self.N_BINS - 1, bin_idx))
        key = (tenant_id, action_type, bin_idx)
        b = self._bins[key]
        b["sample_count"] += 1
        b["outcome_sum"] += 1.0 if actual_outcome else 0.0
        b["actual_rate"] = b["outcome_sum"] / b["sample_count"]
        mid = (b["bin_lower"] + b["bin_upper"]) / 2.0
        b["brier_contribution"] = (mid - b["actual_rate"]) ** 2

    async def get_calibration_curve(
        self, tenant_id: str, action_type: str
    ) -> CalibrationCurve:
        midpoints, actual_rates, counts = [], [], []
        for i in range(self.N_BINS):
            key = (tenant_id, action_type, i)
            b = self._bins.get(key)
            if b and b["sample_count"] >= self.MIN_SAMPLES_PER_BIN:
                mid = (b["bin_lower"] + b["bin_upper"]) / 2.0
                midpoints.append(mid)
                actual_rates.append(b["actual_rate"] or 0.0)
                counts.append(b["sample_count"])

        brier = 0.0
        if midpoints:
            predicted = np.array(midpoints)
            actual = np.array(actual_rates)
            weights = np.array(counts, dtype=float)
            brier = float(np.average((predicted - actual) ** 2, weights=weights))

        return CalibrationCurve(
            action_type=action_type,
            midpoints=midpoints,
            actual_rates=actual_rates,
            counts=counts,
            brier_score=round(brier, 6),
        )

    async def check_and_adjust(
        self, tenant_id: str, action_type: str
    ) -> CalibrationAdjustment | None:
        qualifying = []
        for i in range(self.N_BINS):
            key = (tenant_id, action_type, i)
            b = self._bins.get(key)
            if b and b["sample_count"] >= self.MIN_SAMPLES_PER_BIN:
                qualifying.append(b)
        if not qualifying:
            return None

        total_gap = 0.0
        total_weight = 0
        for b in qualifying:
            mid = (b["bin_lower"] + b["bin_upper"]) / 2.0
            actual = b["actual_rate"] or 0.0
            total_gap += (mid - actual) * b["sample_count"]
            total_weight += b["sample_count"]
        if total_weight == 0:
            return None
        avg_gap = total_gap / total_weight
        if abs(avg_gap) <= self.MISCALIBRATION_THRESHOLD:
            return None

        direction = "decrease" if avg_gap > 0 else "increase"
        magnitude = min(abs(avg_gap), 0.10)
        return CalibrationAdjustment(
            action_type=action_type,
            direction=direction,
            magnitude=round(magnitude, 4),
            old_threshold=1.0,
            new_threshold=round(1.0 - magnitude if avg_gap > 0 else 1.0 + magnitude, 4),
            reason=f"Avg gap {avg_gap:.3f} exceeds threshold",
        )

    async def get_all_action_types(self, tenant_id: str) -> list[str]:
        return list({k[1] for k in self._bins.keys() if k[0] == tenant_id})

    async def compute_brier_score(self, tenant_id: str, action_type: str) -> float:
        curve = await self.get_calibration_curve(tenant_id, action_type)
        return curve.brier_score if curve.midpoints else 0.25


class InMemoryCoachingExtractor:
    """In-memory CoachingPatternExtractor for integration testing."""

    def __init__(self) -> None:
        self._patterns: list[CoachingPattern] = []

    def seed_patterns(self, patterns: list[CoachingPattern]) -> None:
        self._patterns = patterns

    async def extract_patterns(
        self, tenant_id: str, days: int = 90
    ) -> list[CoachingPattern]:
        return self._patterns

    async def get_escalation_patterns(
        self, tenant_id: str, days: int = 90
    ) -> list[CoachingPattern]:
        return [p for p in self._patterns if p.pattern_type == "escalation_pattern"]


class InMemoryAnalyticsService:
    """In-memory AnalyticsService delegating to in-memory sub-services."""

    def __init__(
        self,
        outcome_tracker: InMemoryOutcomeTracker,
        feedback_collector: InMemoryFeedbackCollector,
        calibration_engine: InMemoryCalibrationEngine,
        coaching_extractor: InMemoryCoachingExtractor,
    ) -> None:
        self._outcomes = outcome_tracker
        self._feedback = feedback_collector
        self._calibration = calibration_engine
        self._coaching = coaching_extractor

    async def get_rep_dashboard(
        self, tenant_id: str, rep_id: str | None = None, days: int = 30
    ) -> dict:
        outcomes = list(self._outcomes._outcomes.values())
        total = len([o for o in outcomes if o.tenant_id == tenant_id])
        positive = len([
            o for o in outcomes
            if o.tenant_id == tenant_id
            and o.outcome_status == OutcomeStatus.POSITIVE.value
        ])
        negative = len([
            o for o in outcomes
            if o.tenant_id == tenant_id
            and o.outcome_status == OutcomeStatus.NEGATIVE.value
        ])
        pending = len([
            o for o in outcomes
            if o.tenant_id == tenant_id
            and o.outcome_status == OutcomeStatus.PENDING.value
        ])
        resolved = positive + negative
        success_rate = positive / resolved if resolved > 0 else 0.0

        feedback_summary = await self._feedback.get_feedback_summary(tenant_id, days=days)

        return {
            "role": "rep",
            "period_days": days,
            "response_rates": {
                "total_actions": total,
                "positive_outcomes": positive,
                "negative_outcomes": negative,
                "pending_outcomes": pending,
                "success_rate": round(success_rate, 4),
            },
            "escalation_history": [],
            "deal_impact": {
                "deals_progressed": 0,
                "deals_stalled": 0,
                "deals_closed_won": 0,
                "stage_advancement_rate": 0.0,
            },
            "feedback_scores": {
                "average_rating": feedback_summary.get("average_rating", 0.0),
                "total_feedbacks": feedback_summary.get("total_feedback_count", 0),
                "recent_trend": "stable",
            },
            "calibration_summary": {"action_types": [], "overall_brier": 0.25},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_manager_dashboard(self, tenant_id: str, days: int = 30) -> dict:
        rep_data = await self.get_rep_dashboard(tenant_id, days=days)
        coaching = await self._coaching.extract_patterns(tenant_id, days=days)
        return {
            "role": "manager",
            "period_days": days,
            "team_trends": {
                "total_outcomes": rep_data["response_rates"]["total_actions"],
                "success_rate": rep_data["response_rates"]["success_rate"],
                "trend": "stable",
                "daily_activity": [],
            },
            "comparative_performance": [],
            "coaching_opportunities": [
                {"pattern": p.description, "recommendation": p.recommendation, "confidence": p.confidence}
                for p in coaching[:5]
            ],
            "aggregate_calibration": {"overall_brier": 0.25, "by_action_type": []},
            "escalation_rate": 0.0,
            "feedback_health": {"submission_rate": 0.0, "coverage_percent": 0.0},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_executive_summary(self, tenant_id: str, days: int = 30) -> dict:
        rep_data = await self.get_rep_dashboard(tenant_id, days=days)
        total = rep_data["response_rates"]["total_actions"]
        return {
            "role": "executive",
            "period_days": days,
            "roi_metrics": {
                "total_actions": total,
                "positive_outcomes": rep_data["response_rates"]["positive_outcomes"],
                "estimated_time_saved_hours": round(total * 5.0 / 60.0, 1),
                "cost_per_interaction": None,
            },
            "agent_effectiveness": {
                "overall_success_rate": rep_data["response_rates"]["success_rate"],
                "qualification_completion_rate": 0.0,
                "escalation_rate": 0.0,
            },
            "engagement_trends": {"daily": [], "trend_direction": "stable"},
            "strategic_insights": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def conversation_state_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def reviewer_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def outcome_tracker() -> InMemoryOutcomeTracker:
    return InMemoryOutcomeTracker()


@pytest.fixture
def feedback_collector() -> InMemoryFeedbackCollector:
    return InMemoryFeedbackCollector()


@pytest.fixture
def calibration_engine() -> InMemoryCalibrationEngine:
    return InMemoryCalibrationEngine()


@pytest.fixture
def coaching_extractor() -> InMemoryCoachingExtractor:
    return InMemoryCoachingExtractor()


@pytest.fixture
def analytics_service(
    outcome_tracker, feedback_collector, calibration_engine, coaching_extractor
) -> InMemoryAnalyticsService:
    return InMemoryAnalyticsService(
        outcome_tracker=outcome_tracker,
        feedback_collector=feedback_collector,
        calibration_engine=calibration_engine,
        coaching_extractor=coaching_extractor,
    )


# ── Test 1: Record and Resolve Outcome ───────────────────────────────────────


class TestRecordAndResolveOutcome:
    """Test 1: Record outcome, verify pending. Resolve it, verify status changed."""

    @pytest.mark.asyncio
    async def test_record_and_resolve_outcome(
        self, outcome_tracker, tenant_id, conversation_state_id
    ):
        outcome = await outcome_tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
        )
        assert outcome.outcome_status == OutcomeStatus.PENDING.value
        assert outcome.resolved_at is None

        resolved = await outcome_tracker.resolve_outcome(
            outcome_id=outcome.outcome_id,
            tenant_id=tenant_id,
            outcome_status=OutcomeStatus.POSITIVE.value,
            outcome_score=1.0,
        )
        assert resolved.outcome_status == OutcomeStatus.POSITIVE.value
        assert resolved.outcome_score == 1.0
        assert resolved.resolved_at is not None


# ── Test 2: Outcome Expiry Lifecycle ─────────────────────────────────────────


class TestOutcomeExpiryLifecycle:
    """Test 2: Record outcome with short window, expire it, verify EXPIRED status."""

    @pytest.mark.asyncio
    async def test_outcome_expiry_lifecycle(
        self, outcome_tracker, tenant_id, conversation_state_id
    ):
        outcome = await outcome_tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.7,
            outcome_type="email_engagement",
        )
        # Force window to past
        outcome.window_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        expired_count = await outcome_tracker.expire_overdue_outcomes(tenant_id=tenant_id)
        assert expired_count == 1
        assert outcome.outcome_status == OutcomeStatus.EXPIRED.value
        assert outcome.resolved_at is not None


# ── Test 3: Feedback Submission Inline ───────────────────────────────────────


class TestFeedbackSubmissionInline:
    """Test 3: Submit inline feedback (-1/0/1), verify recorded."""

    @pytest.mark.asyncio
    async def test_feedback_submission_inline(
        self, feedback_collector, tenant_id, conversation_state_id, reviewer_id
    ):
        entry = await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            target_type="message",
            target_id="msg-001",
            source="inline",
            rating=1,
            reviewer_id=reviewer_id,
            reviewer_role="rep",
        )
        assert entry.rating == 1
        assert entry.source == "inline"
        assert entry.target_type == "message"
        assert entry.feedback_id is not None


# ── Test 4: Feedback Submission Dashboard ────────────────────────────────────


class TestFeedbackSubmissionDashboard:
    """Test 4: Submit dashboard feedback (1-5), verify recorded."""

    @pytest.mark.asyncio
    async def test_feedback_submission_dashboard(
        self, feedback_collector, tenant_id, conversation_state_id, reviewer_id
    ):
        entry = await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            target_type="decision",
            target_id="dec-001",
            source="dashboard",
            rating=4,
            reviewer_id=reviewer_id,
            reviewer_role="manager",
            comment="Good qualification decision",
        )
        assert entry.rating == 4
        assert entry.source == "dashboard"
        assert entry.comment == "Good qualification decision"


# ── Test 5: Feedback Linked to Outcome ───────────────────────────────────────


class TestFeedbackLinkedToOutcome:
    """Test 5: Submit feedback with outcome_record_id, verify link."""

    @pytest.mark.asyncio
    async def test_feedback_linked_to_outcome(
        self, outcome_tracker, feedback_collector, tenant_id,
        conversation_state_id, reviewer_id,
    ):
        outcome = await outcome_tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
        )

        entry = await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            target_type="message",
            target_id="msg-002",
            source="inline",
            rating=1,
            reviewer_id=reviewer_id,
            reviewer_role="rep",
            outcome_record_id=outcome.outcome_id,
        )
        assert entry.outcome_record_id == outcome.outcome_id


# ── Test 6: Calibration Update and Curve ─────────────────────────────────────


class TestCalibrationUpdateAndCurve:
    """Test 6: Update calibration with multiple outcomes, get curve, verify shape."""

    @pytest.mark.asyncio
    async def test_calibration_update_and_curve(
        self, calibration_engine, tenant_id
    ):
        # Feed 15 outcomes at confidence 0.75 (bin 7: [0.7, 0.8))
        for i in range(15):
            await calibration_engine.update_calibration(
                tenant_id=tenant_id,
                action_type="send_email",
                predicted_confidence=0.75,
                actual_outcome=(i % 2 == 0),  # ~50% success rate
            )

        curve = await calibration_engine.get_calibration_curve(
            tenant_id, "send_email"
        )
        assert len(curve.midpoints) >= 1
        assert len(curve.actual_rates) >= 1
        assert len(curve.counts) >= 1
        assert curve.counts[0] >= 10


# ── Test 7: Calibration Brier Score ──────────────────────────────────────────


class TestCalibrationBrierScore:
    """Test 7: Feed known predictions and outcomes, verify Brier score."""

    @pytest.mark.asyncio
    async def test_calibration_brier_score(
        self, calibration_engine, tenant_id
    ):
        # Feed 20 outcomes at 0.85 confidence, all positive -> nearly perfect
        for _ in range(20):
            await calibration_engine.update_calibration(
                tenant_id=tenant_id,
                action_type="qualify",
                predicted_confidence=0.85,
                actual_outcome=True,
            )

        brier = await calibration_engine.compute_brier_score(tenant_id, "qualify")
        # Predicted midpoint is 0.85, actual is 1.0 -> (0.85-1.0)^2 = 0.0225
        assert brier < 0.10  # Should be well calibrated for all-positive


# ── Test 8: Miscalibration Auto-Adjust ───────────────────────────────────────


class TestMiscalibrationAutoAdjust:
    """Test 8: Create overconfident calibration, run check_and_adjust."""

    @pytest.mark.asyncio
    async def test_miscalibration_auto_adjust(
        self, calibration_engine, tenant_id
    ):
        # Feed outcomes at high confidence 0.85 but mostly negative
        for i in range(20):
            await calibration_engine.update_calibration(
                tenant_id=tenant_id,
                action_type="send_email",
                predicted_confidence=0.85,
                actual_outcome=(i < 3),  # Only 3/20 positive = 15%
            )

        adj = await calibration_engine.check_and_adjust(tenant_id, "send_email")
        assert adj is not None
        assert adj.direction == "decrease"
        assert adj.magnitude > 0


# ── Test 9: Analytics Rep Dashboard ──────────────────────────────────────────


class TestAnalyticsRepDashboard:
    """Test 9: Call get_rep_dashboard, verify structure and required fields."""

    @pytest.mark.asyncio
    async def test_analytics_rep_dashboard(
        self, analytics_service, outcome_tracker, tenant_id, conversation_state_id
    ):
        # Record some outcomes
        o1 = await outcome_tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
        )
        await outcome_tracker.resolve_outcome(
            outcome_id=o1.outcome_id,
            tenant_id=tenant_id,
            outcome_status=OutcomeStatus.POSITIVE.value,
        )

        dashboard = await analytics_service.get_rep_dashboard(tenant_id, days=30)

        assert dashboard["role"] == "rep"
        assert dashboard["period_days"] == 30
        assert "response_rates" in dashboard
        assert "total_actions" in dashboard["response_rates"]
        assert "success_rate" in dashboard["response_rates"]
        assert "deal_impact" in dashboard
        assert "feedback_scores" in dashboard
        assert "calibration_summary" in dashboard
        assert "generated_at" in dashboard


# ── Test 10: Analytics Manager Dashboard ─────────────────────────────────────


class TestAnalyticsManagerDashboard:
    """Test 10: Call get_manager_dashboard, verify structure."""

    @pytest.mark.asyncio
    async def test_analytics_manager_dashboard(
        self, analytics_service, tenant_id
    ):
        dashboard = await analytics_service.get_manager_dashboard(tenant_id, days=30)

        assert dashboard["role"] == "manager"
        assert "team_trends" in dashboard
        assert "comparative_performance" in dashboard
        assert "coaching_opportunities" in dashboard
        assert "aggregate_calibration" in dashboard
        assert "escalation_rate" in dashboard
        assert "feedback_health" in dashboard
        assert "generated_at" in dashboard


# ── Test 11: Analytics Executive Summary ─────────────────────────────────────


class TestAnalyticsExecutiveSummary:
    """Test 11: Call get_executive_summary, verify structure."""

    @pytest.mark.asyncio
    async def test_analytics_executive_summary(
        self, analytics_service, tenant_id
    ):
        summary = await analytics_service.get_executive_summary(tenant_id, days=30)

        assert summary["role"] == "executive"
        assert "roi_metrics" in summary
        assert "total_actions" in summary["roi_metrics"]
        assert "estimated_time_saved_hours" in summary["roi_metrics"]
        assert "agent_effectiveness" in summary
        assert "engagement_trends" in summary
        assert "strategic_insights" in summary
        assert "generated_at" in summary


# ── Test 12: Coaching Patterns Extraction ────────────────────────────────────


class TestCoachingPatternsExtraction:
    """Test 12: Create outcomes with patterns, extract, verify non-empty."""

    @pytest.mark.asyncio
    async def test_coaching_patterns_extraction(
        self, coaching_extractor, tenant_id
    ):
        coaching_extractor.seed_patterns([
            CoachingPattern(
                pattern_type="action_effectiveness",
                description="'send_email' has 80% success rate",
                confidence=0.9,
                sample_size=50,
                recommendation="Use email outreach more frequently",
            ),
            CoachingPattern(
                pattern_type="stage_insight",
                description="Low success in qualification stage",
                confidence=0.7,
                sample_size=30,
                recommendation="Focus on qualification prep",
            ),
        ])

        patterns = await coaching_extractor.extract_patterns(tenant_id, days=90)
        assert len(patterns) == 2
        assert patterns[0].pattern_type == "action_effectiveness"
        assert patterns[0].confidence == 0.9
        assert patterns[1].recommendation == "Focus on qualification prep"


# ── Test 13: Full Learning Pipeline ──────────────────────────────────────────


class TestFullLearningPipeline:
    """Test 13: End-to-end: record -> feedback -> calibration -> analytics."""

    @pytest.mark.asyncio
    async def test_full_learning_pipeline(
        self, outcome_tracker, feedback_collector, calibration_engine,
        analytics_service, tenant_id, conversation_state_id, reviewer_id,
    ):
        # Step 1: Record outcome
        outcome = await outcome_tracker.record_outcome(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            action_type="send_email",
            predicted_confidence=0.8,
            outcome_type="email_engagement",
        )
        assert outcome.outcome_status == OutcomeStatus.PENDING.value

        # Step 2: Resolve outcome
        resolved = await outcome_tracker.resolve_outcome(
            outcome_id=outcome.outcome_id,
            tenant_id=tenant_id,
            outcome_status=OutcomeStatus.POSITIVE.value,
            outcome_score=1.0,
        )
        assert resolved.outcome_status == OutcomeStatus.POSITIVE.value

        # Step 3: Submit feedback
        entry = await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            target_type="message",
            target_id="msg-pipeline",
            source="inline",
            rating=1,
            reviewer_id=reviewer_id,
            reviewer_role="rep",
            outcome_record_id=outcome.outcome_id,
        )
        assert entry.outcome_record_id == outcome.outcome_id

        # Step 4: Update calibration
        await calibration_engine.update_calibration(
            tenant_id=tenant_id,
            action_type="send_email",
            predicted_confidence=0.8,
            actual_outcome=True,
        )

        # Step 5: Get analytics (verify pipeline works end-to-end)
        dashboard = await analytics_service.get_rep_dashboard(tenant_id, days=30)
        assert dashboard["response_rates"]["total_actions"] >= 1
        assert dashboard["response_rates"]["positive_outcomes"] >= 1


# ── Test 14: Scheduler Tasks Defined ─────────────────────────────────────────


class TestSchedulerTasksDefined:
    """Test 14: Call setup_learning_scheduler, verify all 5 task functions."""

    @pytest.mark.asyncio
    async def test_scheduler_tasks_defined(
        self, outcome_tracker, calibration_engine, analytics_service
    ):
        from src.app.learning.scheduler import setup_learning_scheduler

        tasks = await setup_learning_scheduler(
            outcome_tracker=outcome_tracker,
            calibration_engine=calibration_engine,
            analytics_service=analytics_service,
        )

        assert len(tasks) == 5
        assert "check_immediate_signals" in tasks
        assert "check_engagement_signals" in tasks
        assert "check_deal_progression" in tasks
        assert "expire_overdue_outcomes" in tasks
        assert "calibration_check" in tasks

        # Verify each is callable
        for name, fn in tasks.items():
            assert callable(fn), f"{name} is not callable"


# ── Test 15: Learning API Feedback Endpoint (mock) ───────────────────────────


class TestLearningAPIFeedbackEndpoint:
    """Test 15: Test POST /learning/feedback returns 200 with valid data."""

    @pytest.mark.asyncio
    async def test_learning_api_feedback_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.app.api.v1.learning import router
        from src.app.learning.schemas import SubmitFeedbackRequest

        app = FastAPI()
        app.include_router(router)

        # Mock services on app.state
        mock_collector = InMemoryFeedbackCollector()
        app.state.feedback_collector = mock_collector
        app.state.outcome_tracker = InMemoryOutcomeTracker()
        app.state.calibration_engine = InMemoryCalibrationEngine()
        app.state.analytics_service = None
        app.state.coaching_extractor = None

        # Mock auth dependencies
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.role = "rep"
        mock_tenant = MagicMock()
        mock_tenant.tenant_id = str(uuid.uuid4())

        app.dependency_overrides[
            __import__("src.app.api.deps", fromlist=["get_current_user"]).get_current_user
        ] = lambda: mock_user
        app.dependency_overrides[
            __import__("src.app.api.deps", fromlist=["get_tenant"]).get_tenant
        ] = lambda: mock_tenant

        client = TestClient(app)
        response = client.post(
            "/learning/feedback",
            json={
                "conversation_state_id": str(uuid.uuid4()),
                "target_type": "message",
                "target_id": "msg-test",
                "source": "inline",
                "rating": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "recorded"
        assert "feedback_id" in data


# ── Test 16: Learning API Analytics Endpoint (mock) ──────────────────────────


class TestLearningAPIAnalyticsEndpoint:
    """Test 16: Test GET /learning/analytics/rep returns 200."""

    @pytest.mark.asyncio
    async def test_learning_api_analytics_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.app.api.v1.learning import router

        app = FastAPI()
        app.include_router(router)

        # Mock analytics service
        mock_analytics = AsyncMock()
        mock_analytics.get_rep_dashboard = AsyncMock(return_value={
            "role": "rep",
            "period_days": 30,
            "response_rates": {"total_actions": 10, "success_rate": 0.7},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        app.state.analytics_service = mock_analytics
        app.state.outcome_tracker = InMemoryOutcomeTracker()
        app.state.feedback_collector = InMemoryFeedbackCollector()
        app.state.calibration_engine = InMemoryCalibrationEngine()
        app.state.coaching_extractor = InMemoryCoachingExtractor()

        # Mock auth
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_tenant = MagicMock()
        mock_tenant.tenant_id = str(uuid.uuid4())

        app.dependency_overrides[
            __import__("src.app.api.deps", fromlist=["get_current_user"]).get_current_user
        ] = lambda: mock_user
        app.dependency_overrides[
            __import__("src.app.api.deps", fromlist=["get_tenant"]).get_tenant
        ] = lambda: mock_tenant

        client = TestClient(app)
        response = client.get("/learning/analytics/rep")
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "rep"
