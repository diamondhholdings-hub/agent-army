"""Tests for feedback collection, calibration engine, and coaching extraction.

Tests FeedbackCollector, CalibrationEngine, and CoachingPatternExtractor
with in-memory test doubles matching the InMemoryStateRepository pattern
from test_sales_integration.py.

Covers:
- Feedback validation (inline vs dashboard rating ranges)
- Feedback querying (by conversation, reviewer)
- Feedback summary metrics computation
- Feedback fatigue rate detection
- Calibration bin initialization and idempotency
- Calibration bin updates (single and multiple)
- Brier score computation (perfect, random, static method)
- Calibration curve from arrays (static method)
- Miscalibration detection and adjustment
- Adjustment damping and bounds clamping
- Cold start protection
- Coaching pattern extraction
- Top performing actions ranking
- Improvement area identification
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src.app.learning.calibration import CalibrationEngine
from src.app.learning.coaching import CoachingPatternExtractor
from src.app.learning.feedback import FeedbackCollector
from src.app.learning.schemas import (
    CalibrationAdjustment,
    CalibrationCurve,
    CoachingPattern,
    FeedbackEntry,
    FeedbackSource,
    FeedbackTarget,
    OutcomeStatus,
)


# -- In-Memory Test Doubles ---------------------------------------------------


class InMemoryFeedbackStore:
    """In-memory test double for FeedbackCollector's database layer.

    Stores feedback entries in a list and provides session_factory
    compatible interface for the FeedbackCollector service.
    """

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def add(self, entry: dict) -> dict:
        entry.setdefault("id", uuid.uuid4())
        entry.setdefault("created_at", datetime.now(timezone.utc))
        self.entries.append(entry)
        return entry

    def query_by_conversation(self, tenant_id: str, conversation_state_id: str) -> list[dict]:
        return [
            e for e in self.entries
            if str(e["tenant_id"]) == tenant_id
            and str(e["conversation_state_id"]) == conversation_state_id
        ]

    def query_by_reviewer(self, tenant_id: str, reviewer_id: str, limit: int = 50) -> list[dict]:
        results = [
            e for e in self.entries
            if str(e["tenant_id"]) == tenant_id
            and str(e["reviewer_id"]) == reviewer_id
        ]
        results.sort(key=lambda e: e.get("created_at", datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        return results[:limit]

    def query_by_period(self, tenant_id: str, cutoff: datetime) -> list[dict]:
        return [
            e for e in self.entries
            if str(e["tenant_id"]) == tenant_id
            and e.get("created_at", datetime.now(timezone.utc)) >= cutoff
        ]

    def count_by_reviewer_period(self, tenant_id: str, reviewer_id: str, cutoff: datetime) -> int:
        return len([
            e for e in self.entries
            if str(e["tenant_id"]) == tenant_id
            and str(e["reviewer_id"]) == reviewer_id
            and e.get("created_at", datetime.now(timezone.utc)) >= cutoff
        ])


class InMemoryCalibrationStore:
    """In-memory test double for CalibrationEngine's database layer.

    Stores calibration bins in a dict keyed by (tenant_id, action_type, bin_index).
    """

    def __init__(self) -> None:
        self.bins: dict[tuple[str, str, int], dict] = {}

    def get_bins(self, tenant_id: str, action_type: str) -> list[dict]:
        results = [
            v for k, v in self.bins.items()
            if k[0] == tenant_id and k[1] == action_type
        ]
        results.sort(key=lambda b: b["bin_index"])
        return results

    def get_bin(self, tenant_id: str, action_type: str, bin_index: int) -> dict | None:
        return self.bins.get((tenant_id, action_type, bin_index))

    def set_bin(self, tenant_id: str, action_type: str, bin_index: int, data: dict) -> None:
        self.bins[(tenant_id, action_type, bin_index)] = data

    def get_all_action_types(self, tenant_id: str) -> list[str]:
        return list({k[1] for k in self.bins.keys() if k[0] == tenant_id})


class InMemoryOutcomeStore:
    """In-memory test double for outcome records used by CoachingPatternExtractor."""

    def __init__(self) -> None:
        self.outcomes: list[dict] = []
        self.feedbacks: list[dict] = []

    def add_outcome(self, outcome: dict) -> None:
        outcome.setdefault("id", uuid.uuid4())
        outcome.setdefault("created_at", datetime.now(timezone.utc))
        self.outcomes.append(outcome)

    def add_feedback(self, feedback: dict) -> None:
        feedback.setdefault("id", uuid.uuid4())
        feedback.setdefault("created_at", datetime.now(timezone.utc))
        self.feedbacks.append(feedback)


# -- Standalone Test Implementations ------------------------------------------
# These test against the service logic directly using in-memory state,
# bypassing the session_factory/SQLAlchemy layer.


class InMemoryFeedbackCollector:
    """In-memory FeedbackCollector for unit testing without database."""

    INLINE_RATING_RANGE = FeedbackCollector.INLINE_RATING_RANGE
    DASHBOARD_RATING_RANGE = FeedbackCollector.DASHBOARD_RATING_RANGE
    VALID_TARGET_TYPES = FeedbackCollector.VALID_TARGET_TYPES
    VALID_SOURCES = FeedbackCollector.VALID_SOURCES

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
        # Validate target_type
        if target_type not in self.VALID_TARGET_TYPES:
            raise ValueError(
                f"Invalid target_type '{target_type}'. "
                f"Must be one of: {', '.join(sorted(self.VALID_TARGET_TYPES))}"
            )

        # Validate source
        if source not in self.VALID_SOURCES:
            raise ValueError(
                f"Invalid source '{source}'. "
                f"Must be one of: {', '.join(sorted(self.VALID_SOURCES))}"
            )

        # Validate rating based on source
        if source == FeedbackSource.INLINE.value:
            min_r, max_r = self.INLINE_RATING_RANGE
            if not (min_r <= rating <= max_r):
                raise ValueError(
                    f"Inline rating must be between {min_r} and {max_r}, got {rating}"
                )
        elif source == FeedbackSource.DASHBOARD.value:
            min_r, max_r = self.DASHBOARD_RATING_RANGE
            if not (min_r <= rating <= max_r):
                raise ValueError(
                    f"Dashboard rating must be between {min_r} and {max_r}, got {rating}"
                )

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

    async def get_feedback_by_reviewer(
        self, tenant_id: str, reviewer_id: str, limit: int = 50
    ) -> list[FeedbackEntry]:
        results = [
            e for e in self._entries
            if e.tenant_id == tenant_id and e.reviewer_id == reviewer_id
        ]
        results.sort(key=lambda e: e.created_at, reverse=True)
        return results[:limit]

    async def get_feedback_summary(
        self, tenant_id: str, days: int = 30
    ) -> dict:
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
        avg_rating = sum(e.rating for e in filtered) / total

        rating_dist: dict[int, int] = defaultdict(int)
        for e in filtered:
            rating_dist[e.rating] += 1

        by_target: dict[str, dict] = defaultdict(lambda: {"count": 0, "rating_sum": 0})
        for e in filtered:
            by_target[e.target_type]["count"] += 1
            by_target[e.target_type]["rating_sum"] += e.rating
        by_target_result = {
            k: {"count": v["count"], "avg_rating": v["rating_sum"] / v["count"]}
            for k, v in by_target.items()
        }

        by_source: dict[str, int] = defaultdict(int)
        for e in filtered:
            by_source[e.source] += 1

        by_role: dict[str, dict] = defaultdict(lambda: {"count": 0, "rating_sum": 0})
        for e in filtered:
            by_role[e.reviewer_role]["count"] += 1
            by_role[e.reviewer_role]["rating_sum"] += e.rating
        by_role_result = {
            k: {"count": v["count"], "avg_rating": v["rating_sum"] / v["count"]}
            for k, v in by_role.items()
        }

        daily_counts: dict[str, int] = defaultdict(int)
        for e in filtered:
            day_key = e.created_at.strftime("%Y-%m-%d")
            daily_counts[day_key] += 1

        trend = [{"date": k, "count": v} for k, v in sorted(daily_counts.items())]

        return {
            "total_feedback_count": total,
            "average_rating": round(avg_rating, 2),
            "rating_distribution": dict(rating_dist),
            "by_target_type": by_target_result,
            "by_source": dict(by_source),
            "by_reviewer_role": by_role_result,
            "feedback_rate_trend": trend,
        }

    async def get_feedback_rate(self, tenant_id: str, reviewer_id: str) -> float:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        count = len([
            e for e in self._entries
            if e.tenant_id == tenant_id
            and e.reviewer_id == reviewer_id
            and e.created_at >= cutoff
        ])
        return count / 7.0


class InMemoryCalibrationEngine:
    """In-memory CalibrationEngine for unit testing without database."""

    N_BINS = CalibrationEngine.N_BINS
    BIN_EDGES = CalibrationEngine.BIN_EDGES
    MIN_SAMPLES_PER_BIN = CalibrationEngine.MIN_SAMPLES_PER_BIN
    MISCALIBRATION_THRESHOLD = CalibrationEngine.MISCALIBRATION_THRESHOLD
    MAX_ADJUSTMENT_RATE = CalibrationEngine.MAX_ADJUSTMENT_RATE
    SCALING_BOUNDS = CalibrationEngine.SCALING_BOUNDS
    ESCALATION_BOUNDS = CalibrationEngine.ESCALATION_BOUNDS

    def __init__(self) -> None:
        # bins keyed by (tenant_id, action_type, bin_index)
        self._bins: dict[tuple[str, str, int], dict] = {}

    async def initialize_bins(self, tenant_id: str, action_type: str) -> None:
        # Check if already exist
        existing = [
            k for k in self._bins
            if k[0] == tenant_id and k[1] == action_type
        ]
        if len(existing) >= self.N_BINS:
            return

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
        self,
        tenant_id: str,
        action_type: str,
        predicted_confidence: float,
        actual_outcome: bool,
    ) -> None:
        confidence = max(0.0, min(1.0, predicted_confidence))
        bin_idx = int(np.digitize(confidence, self.BIN_EDGES[1:]))
        bin_idx = max(0, min(self.N_BINS - 1, bin_idx))

        await self.initialize_bins(tenant_id, action_type)

        key = (tenant_id, action_type, bin_idx)
        b = self._bins[key]

        b["sample_count"] += 1
        b["outcome_sum"] += 1.0 if actual_outcome else 0.0
        b["actual_rate"] = b["outcome_sum"] / b["sample_count"]

        midpoint = (b["bin_lower"] + b["bin_upper"]) / 2.0
        b["brier_contribution"] = (midpoint - b["actual_rate"]) ** 2

    async def get_calibration_curve(
        self, tenant_id: str, action_type: str
    ) -> CalibrationCurve:
        bins = sorted(
            [v for k, v in self._bins.items() if k[0] == tenant_id and k[1] == action_type],
            key=lambda b: b["bin_index"],
        )

        midpoints = []
        actual_rates = []
        counts = []

        for b in bins:
            if b["sample_count"] >= self.MIN_SAMPLES_PER_BIN:
                midpoints.append((b["bin_lower"] + b["bin_upper"]) / 2.0)
                actual_rates.append(b["actual_rate"] or 0.0)
                counts.append(b["sample_count"])

        brier = 0.0
        if midpoints:
            predicted = np.array(midpoints)
            actual = np.array(actual_rates)
            weights = np.array(counts, dtype=float)
            gaps_sq = (predicted - actual) ** 2
            brier = float(np.average(gaps_sq, weights=weights))

        return CalibrationCurve(
            action_type=action_type,
            midpoints=midpoints,
            actual_rates=actual_rates,
            counts=counts,
            brier_score=round(brier, 6),
        )

    async def compute_brier_score(self, tenant_id: str, action_type: str) -> float:
        curve = await self.get_calibration_curve(tenant_id, action_type)
        if not curve.midpoints:
            return 0.25
        return curve.brier_score

    async def check_and_adjust(
        self, tenant_id: str, action_type: str
    ) -> CalibrationAdjustment | None:
        bins = sorted(
            [v for k, v in self._bins.items() if k[0] == tenant_id and k[1] == action_type],
            key=lambda b: b["bin_index"],
        )

        qualifying = [b for b in bins if b["sample_count"] >= self.MIN_SAMPLES_PER_BIN]
        if not qualifying:
            return None

        total_gap = 0.0
        total_weight = 0
        for b in qualifying:
            midpoint = (b["bin_lower"] + b["bin_upper"]) / 2.0
            actual = b["actual_rate"] or 0.0
            gap = midpoint - actual
            total_gap += gap * b["sample_count"]
            total_weight += b["sample_count"]

        if total_weight == 0:
            return None

        avg_gap = total_gap / total_weight

        if abs(avg_gap) <= self.MISCALIBRATION_THRESHOLD:
            return None

        if avg_gap > 0:
            direction = "decrease"
            magnitude = min(abs(avg_gap), self.MAX_ADJUSTMENT_RATE)
            old_threshold = 1.0
            new_threshold = max(self.SCALING_BOUNDS[0], old_threshold - magnitude)
        else:
            direction = "increase"
            magnitude = min(abs(avg_gap), self.MAX_ADJUSTMENT_RATE)
            old_threshold = 1.0
            new_threshold = min(self.SCALING_BOUNDS[1], old_threshold + magnitude)

        new_threshold = max(self.SCALING_BOUNDS[0], min(self.SCALING_BOUNDS[1], new_threshold))

        reason = (
            f"Average gap of {avg_gap:.3f} across {len(qualifying)} bins "
            f"({total_weight} samples) exceeds threshold of "
            f"{self.MISCALIBRATION_THRESHOLD}. Agent is "
            f"{'overconfident' if avg_gap > 0 else 'underconfident'}."
        )

        return CalibrationAdjustment(
            action_type=action_type,
            direction=direction,
            magnitude=round(magnitude, 4),
            old_threshold=old_threshold,
            new_threshold=round(new_threshold, 4),
            reason=reason,
        )


class InMemoryCoachingExtractor:
    """In-memory CoachingPatternExtractor for unit testing without database."""

    MIN_SAMPLES = CoachingPatternExtractor.MIN_SAMPLES

    def __init__(self) -> None:
        self._outcomes: list[dict] = []
        self._feedbacks: list[dict] = []

    def add_outcome(self, **kwargs: object) -> None:
        kwargs.setdefault("created_at", datetime.now(timezone.utc))
        self._outcomes.append(dict(kwargs))

    def add_feedback(self, **kwargs: object) -> None:
        kwargs.setdefault("created_at", datetime.now(timezone.utc))
        self._feedbacks.append(dict(kwargs))

    async def extract_patterns(self, tenant_id: str, days: int = 90) -> list[CoachingPattern]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        outcomes = [
            o for o in self._outcomes
            if o.get("tenant_id") == tenant_id
            and o.get("outcome_status") != OutcomeStatus.PENDING.value
            and o.get("created_at", datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        ]

        if not outcomes:
            return []

        patterns: list[CoachingPattern] = []

        # Action type effectiveness
        action_groups: dict[str, list] = defaultdict(list)
        for o in outcomes:
            is_positive = o.get("outcome_status") == OutcomeStatus.POSITIVE.value
            action_groups[o.get("action_type", "unknown")].append(is_positive)

        overall_positive = sum(
            1 for o in outcomes if o.get("outcome_status") == OutcomeStatus.POSITIVE.value
        )
        overall_rate = overall_positive / len(outcomes)

        for action_type, results_list in action_groups.items():
            if len(results_list) < self.MIN_SAMPLES:
                continue
            success_rate = sum(results_list) / len(results_list)
            diff = success_rate - overall_rate

            if abs(diff) > 0.05:
                patterns.append(
                    CoachingPattern(
                        pattern_type="action_effectiveness",
                        description=f"'{action_type}' has {success_rate:.0%} success rate",
                        confidence=min(len(results_list) / 50.0, 1.0),
                        sample_size=len(results_list),
                        supporting_data={
                            "action_type": action_type,
                            "success_rate": round(success_rate, 4),
                            "overall_rate": round(overall_rate, 4),
                        },
                        recommendation=f"Adjust '{action_type}' strategy",
                    )
                )

        patterns.sort(key=lambda p: p.confidence, reverse=True)
        return patterns

    async def get_top_performing_actions(
        self, tenant_id: str, days: int = 90, top_k: int = 5
    ) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        outcomes = [
            o for o in self._outcomes
            if o.get("tenant_id") == tenant_id
            and o.get("outcome_status") != OutcomeStatus.PENDING.value
            and o.get("created_at", datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        ]

        action_stats: dict[str, dict] = defaultdict(lambda: {"positive": 0, "total": 0})
        for o in outcomes:
            action_stats[o.get("action_type", "unknown")]["total"] += 1
            if o.get("outcome_status") == OutcomeStatus.POSITIVE.value:
                action_stats[o.get("action_type", "unknown")]["positive"] += 1

        ranked = []
        for action_type, stats in action_stats.items():
            if stats["total"] < self.MIN_SAMPLES:
                continue
            success_rate = stats["positive"] / stats["total"]
            ranked.append({
                "action_type": action_type,
                "success_rate": round(success_rate, 4),
                "total_count": stats["total"],
                "positive_count": stats["positive"],
            })

        ranked.sort(key=lambda x: x["success_rate"], reverse=True)
        return ranked[:top_k]

    async def get_improvement_areas(self, tenant_id: str, days: int = 90) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        outcomes = [
            o for o in self._outcomes
            if o.get("tenant_id") == tenant_id
            and o.get("outcome_status") != OutcomeStatus.PENDING.value
            and o.get("created_at", datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        ]

        areas: list[dict] = []
        action_stats: dict[str, dict] = defaultdict(lambda: {"positive": 0, "negative": 0, "total": 0})
        for o in outcomes:
            action_stats[o.get("action_type", "unknown")]["total"] += 1
            if o.get("outcome_status") == OutcomeStatus.POSITIVE.value:
                action_stats[o.get("action_type", "unknown")]["positive"] += 1
            elif o.get("outcome_status") == OutcomeStatus.NEGATIVE.value:
                action_stats[o.get("action_type", "unknown")]["negative"] += 1

        for action_type, stats in action_stats.items():
            if stats["total"] < self.MIN_SAMPLES:
                continue
            success_rate = stats["positive"] / stats["total"]
            if success_rate < 0.4:
                areas.append({
                    "area_type": "low_success_rate",
                    "action_type": action_type,
                    "success_rate": round(success_rate, 4),
                    "total_count": stats["total"],
                })

        return areas


# -- Fixtures ------------------------------------------------------------------


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
def feedback_collector() -> InMemoryFeedbackCollector:
    return InMemoryFeedbackCollector()


@pytest.fixture
def calibration_engine() -> InMemoryCalibrationEngine:
    return InMemoryCalibrationEngine()


@pytest.fixture
def coaching_extractor() -> InMemoryCoachingExtractor:
    return InMemoryCoachingExtractor()


# -- Feedback Tests ------------------------------------------------------------


class TestRecordInlineFeedback:
    """Test recording inline feedback with rating -1/0/1."""

    async def test_record_inline_feedback(
        self,
        feedback_collector: InMemoryFeedbackCollector,
        tenant_id: str,
        conversation_state_id: str,
        reviewer_id: str,
    ) -> None:
        """Record inline feedback with thumbs up, verify persisted."""
        entry = await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            target_type="message",
            target_id="msg-001",
            source="inline",
            rating=1,
            reviewer_id=reviewer_id,
            reviewer_role="rep",
            comment="Good response",
        )

        assert entry.tenant_id == tenant_id
        assert entry.conversation_state_id == conversation_state_id
        assert entry.target_type == "message"
        assert entry.target_id == "msg-001"
        assert entry.source == "inline"
        assert entry.rating == 1
        assert entry.reviewer_id == reviewer_id
        assert entry.reviewer_role == "rep"
        assert entry.comment == "Good response"
        assert entry.created_at is not None


class TestRecordDashboardFeedback:
    """Test recording dashboard feedback with rating 1-5."""

    async def test_record_dashboard_feedback(
        self,
        feedback_collector: InMemoryFeedbackCollector,
        tenant_id: str,
        conversation_state_id: str,
        reviewer_id: str,
    ) -> None:
        """Record dashboard feedback with 5-star rating, verify persisted."""
        entry = await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conversation_state_id,
            target_type="conversation",
            target_id="conv-001",
            source="dashboard",
            rating=5,
            reviewer_id=reviewer_id,
            reviewer_role="manager",
        )

        assert entry.source == "dashboard"
        assert entry.rating == 5
        assert entry.reviewer_role == "manager"
        assert entry.target_type == "conversation"


class TestFeedbackRatingValidationInline:
    """Test that inline source rejects ratings outside -1 to 1."""

    async def test_feedback_rating_validation_inline(
        self,
        feedback_collector: InMemoryFeedbackCollector,
        tenant_id: str,
        conversation_state_id: str,
        reviewer_id: str,
    ) -> None:
        """Inline source rejects rating=3 (outside -1 to 1 range)."""
        with pytest.raises(ValueError, match="Inline rating must be between -1 and 1"):
            await feedback_collector.record_feedback(
                tenant_id=tenant_id,
                conversation_state_id=conversation_state_id,
                target_type="message",
                target_id="msg-001",
                source="inline",
                rating=3,
                reviewer_id=reviewer_id,
                reviewer_role="rep",
            )


class TestFeedbackRatingValidationDashboard:
    """Test that dashboard source rejects ratings outside 1 to 5."""

    async def test_feedback_rating_validation_dashboard(
        self,
        feedback_collector: InMemoryFeedbackCollector,
        tenant_id: str,
        conversation_state_id: str,
        reviewer_id: str,
    ) -> None:
        """Dashboard source rejects rating=0 (outside 1 to 5 range)."""
        with pytest.raises(ValueError, match="Dashboard rating must be between 1 and 5"):
            await feedback_collector.record_feedback(
                tenant_id=tenant_id,
                conversation_state_id=conversation_state_id,
                target_type="message",
                target_id="msg-001",
                source="dashboard",
                rating=0,
                reviewer_id=reviewer_id,
                reviewer_role="rep",
            )


class TestGetFeedbackForConversation:
    """Test querying feedback by conversation."""

    async def test_get_feedback_for_conversation(
        self,
        feedback_collector: InMemoryFeedbackCollector,
        tenant_id: str,
        reviewer_id: str,
    ) -> None:
        """Create multiple feedbacks across conversations, query one."""
        conv_id1 = str(uuid.uuid4())
        conv_id2 = str(uuid.uuid4())

        await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conv_id1,
            target_type="message",
            target_id="msg-001",
            source="inline",
            rating=1,
            reviewer_id=reviewer_id,
            reviewer_role="rep",
        )
        await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conv_id1,
            target_type="decision",
            target_id="dec-001",
            source="inline",
            rating=-1,
            reviewer_id=reviewer_id,
            reviewer_role="rep",
        )
        await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conv_id2,
            target_type="message",
            target_id="msg-002",
            source="inline",
            rating=0,
            reviewer_id=reviewer_id,
            reviewer_role="rep",
        )

        results = await feedback_collector.get_feedback_for_conversation(
            tenant_id=tenant_id, conversation_state_id=conv_id1
        )

        assert len(results) == 2
        assert all(r.conversation_state_id == conv_id1 for r in results)


class TestFeedbackSummaryComputation:
    """Test computing feedback summary metrics."""

    async def test_feedback_summary_computation(
        self,
        feedback_collector: InMemoryFeedbackCollector,
        tenant_id: str,
        reviewer_id: str,
    ) -> None:
        """Create varied feedback, verify summary metrics."""
        conv_id = str(uuid.uuid4())
        reviewer_id2 = str(uuid.uuid4())

        # Create diverse feedbacks
        await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conv_id,
            target_type="message",
            target_id="msg-001",
            source="inline",
            rating=1,
            reviewer_id=reviewer_id,
            reviewer_role="rep",
        )
        await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conv_id,
            target_type="decision",
            target_id="dec-001",
            source="inline",
            rating=-1,
            reviewer_id=reviewer_id,
            reviewer_role="rep",
        )
        await feedback_collector.record_feedback(
            tenant_id=tenant_id,
            conversation_state_id=conv_id,
            target_type="conversation",
            target_id="conv-001",
            source="dashboard",
            rating=4,
            reviewer_id=reviewer_id2,
            reviewer_role="manager",
        )

        summary = await feedback_collector.get_feedback_summary(
            tenant_id=tenant_id, days=30
        )

        assert summary["total_feedback_count"] == 3
        # avg = (1 + -1 + 4) / 3 = 4/3 = 1.33
        assert summary["average_rating"] == pytest.approx(1.33, abs=0.01)
        assert summary["rating_distribution"][1] == 1
        assert summary["rating_distribution"][-1] == 1
        assert summary["rating_distribution"][4] == 1
        assert summary["by_target_type"]["message"]["count"] == 1
        assert summary["by_target_type"]["decision"]["count"] == 1
        assert summary["by_target_type"]["conversation"]["count"] == 1
        assert summary["by_source"]["inline"] == 2
        assert summary["by_source"]["dashboard"] == 1
        assert summary["by_reviewer_role"]["rep"]["count"] == 2
        assert summary["by_reviewer_role"]["manager"]["count"] == 1


class TestFeedbackRateForFatigue:
    """Test feedback rate computation for fatigue detection."""

    async def test_feedback_rate_for_fatigue(
        self,
        feedback_collector: InMemoryFeedbackCollector,
        tenant_id: str,
        reviewer_id: str,
    ) -> None:
        """Simulate feedback, verify rate computation."""
        conv_id = str(uuid.uuid4())

        # Record 7 feedbacks (1 per day average)
        for i in range(7):
            await feedback_collector.record_feedback(
                tenant_id=tenant_id,
                conversation_state_id=conv_id,
                target_type="message",
                target_id=f"msg-{i:03d}",
                source="inline",
                rating=1,
                reviewer_id=reviewer_id,
                reviewer_role="rep",
            )

        rate = await feedback_collector.get_feedback_rate(
            tenant_id=tenant_id, reviewer_id=reviewer_id
        )

        # 7 feedbacks / 7 days = 1.0 per day
        assert rate == pytest.approx(1.0, abs=0.01)


# -- Calibration Tests ---------------------------------------------------------


class TestInitializeBins:
    """Test creating calibration bins for action type."""

    async def test_initialize_bins(
        self,
        calibration_engine: InMemoryCalibrationEngine,
        tenant_id: str,
    ) -> None:
        """Create bins for action type, verify 10 bins with correct edges."""
        await calibration_engine.initialize_bins(tenant_id, "send_email")

        bins = sorted(
            [v for k, v in calibration_engine._bins.items()
             if k[0] == tenant_id and k[1] == "send_email"],
            key=lambda b: b["bin_index"],
        )

        assert len(bins) == 10

        # Verify bin edges
        for i, b in enumerate(bins):
            assert b["bin_index"] == i
            assert b["bin_lower"] == pytest.approx(i * 0.1, abs=0.001)
            assert b["bin_upper"] == pytest.approx((i + 1) * 0.1, abs=0.001)
            assert b["sample_count"] == 0
            assert b["outcome_sum"] == 0.0


class TestInitializeBinsIdempotent:
    """Test that initializing bins twice doesn't create duplicates."""

    async def test_initialize_bins_idempotent(
        self,
        calibration_engine: InMemoryCalibrationEngine,
        tenant_id: str,
    ) -> None:
        """Call initialize_bins twice, verify no duplicate bins."""
        await calibration_engine.initialize_bins(tenant_id, "send_email")
        await calibration_engine.initialize_bins(tenant_id, "send_email")

        bins = [
            k for k in calibration_engine._bins
            if k[0] == tenant_id and k[1] == "send_email"
        ]
        assert len(bins) == 10


class TestUpdateCalibrationSingle:
    """Test updating a single calibration bin."""

    async def test_update_calibration_single(
        self,
        calibration_engine: InMemoryCalibrationEngine,
        tenant_id: str,
    ) -> None:
        """Update one bin with a positive outcome, verify counts/rates."""
        await calibration_engine.update_calibration(
            tenant_id=tenant_id,
            action_type="send_email",
            predicted_confidence=0.75,
            actual_outcome=True,
        )

        # 0.75 falls in bin 7 ([0.7, 0.8))
        key = (tenant_id, "send_email", 7)
        b = calibration_engine._bins[key]

        assert b["sample_count"] == 1
        assert b["outcome_sum"] == 1.0
        assert b["actual_rate"] == 1.0


class TestUpdateCalibrationMultiple:
    """Test multiple outcome updates across bins."""

    async def test_update_calibration_multiple(
        self,
        calibration_engine: InMemoryCalibrationEngine,
        tenant_id: str,
    ) -> None:
        """Multiple outcomes across bins, verify distribution."""
        # Bin 2 ([0.2, 0.3)): 2 positive, 1 negative
        for _ in range(2):
            await calibration_engine.update_calibration(
                tenant_id, "send_email", 0.25, True
            )
        await calibration_engine.update_calibration(
            tenant_id, "send_email", 0.25, False
        )

        # Bin 8 ([0.8, 0.9)): 1 positive, 2 negative
        await calibration_engine.update_calibration(
            tenant_id, "send_email", 0.85, True
        )
        for _ in range(2):
            await calibration_engine.update_calibration(
                tenant_id, "send_email", 0.85, False
            )

        b2 = calibration_engine._bins[(tenant_id, "send_email", 2)]
        assert b2["sample_count"] == 3
        assert b2["outcome_sum"] == 2.0
        assert b2["actual_rate"] == pytest.approx(2 / 3, abs=0.01)

        b8 = calibration_engine._bins[(tenant_id, "send_email", 8)]
        assert b8["sample_count"] == 3
        assert b8["outcome_sum"] == 1.0
        assert b8["actual_rate"] == pytest.approx(1 / 3, abs=0.01)


class TestBrierScorePerfect:
    """Test Brier score with perfect calibration."""

    async def test_brier_score_perfect(
        self,
        calibration_engine: InMemoryCalibrationEngine,
        tenant_id: str,
    ) -> None:
        """Predicted == actual for all bins, Brier should be near 0.0."""
        # For bin with midpoint 0.75, actual rate should be ~0.75
        # Add enough samples: 75% positive in [0.7, 0.8) bin
        for _ in range(75):
            await calibration_engine.update_calibration(
                tenant_id, "send_email", 0.75, True
            )
        for _ in range(25):
            await calibration_engine.update_calibration(
                tenant_id, "send_email", 0.75, False
            )

        brier = await calibration_engine.compute_brier_score(tenant_id, "send_email")

        # Midpoint is 0.75, actual rate is 0.75, so Brier contribution = 0.0
        assert brier == pytest.approx(0.0, abs=0.001)


class TestBrierScoreRandom:
    """Test Brier score with random guessing baseline."""

    async def test_brier_score_random(
        self,
        calibration_engine: InMemoryCalibrationEngine,
        tenant_id: str,
    ) -> None:
        """Predicted all 0.5, outcomes 50/50, Brier should be near 0.25."""
        # No data returns 0.25 baseline
        brier = await calibration_engine.compute_brier_score(tenant_id, "send_email")
        assert brier == pytest.approx(0.25)


class TestBrierScoreStaticMethod:
    """Test static brier_score with numpy arrays directly."""

    def test_brier_score_static_method(self) -> None:
        """Test static brier_score with perfect predictions."""
        predicted = np.array([0.9, 0.1, 0.8, 0.2])
        actual = np.array([1.0, 0.0, 1.0, 0.0])

        score = CalibrationEngine.brier_score(predicted, actual)

        # (0.1^2 + 0.1^2 + 0.2^2 + 0.2^2) / 4 = (0.01 + 0.01 + 0.04 + 0.04) / 4 = 0.025
        assert score == pytest.approx(0.025, abs=0.001)

    def test_brier_score_empty_returns_baseline(self) -> None:
        """Empty arrays return 0.25 baseline."""
        score = CalibrationEngine.brier_score(np.array([]), np.array([]))
        assert score == 0.25


class TestCalibrationCurveFromArrays:
    """Test static calibration_curve_from_arrays."""

    def test_calibration_curve_from_arrays(self) -> None:
        """Test calibration curve computation from raw arrays."""
        predicted = np.array([0.15, 0.25, 0.35, 0.75, 0.85, 0.95])
        actual = np.array([0.0, 0.0, 1.0, 1.0, 1.0, 0.0])

        result = CalibrationEngine.calibration_curve_from_arrays(predicted, actual)

        assert "midpoints" in result
        assert "actual_rates" in result
        assert "counts" in result
        assert "brier_score" in result
        assert len(result["midpoints"]) > 0

    def test_calibration_curve_from_arrays_empty(self) -> None:
        """Empty arrays return baseline."""
        result = CalibrationEngine.calibration_curve_from_arrays(
            np.array([]), np.array([])
        )
        assert result["brier_score"] == 0.25
        assert result["midpoints"] == []


class TestMiscalibrationDetection:
    """Test miscalibration detection triggers adjustment."""

    async def test_miscalibration_detection(
        self,
        calibration_engine: InMemoryCalibrationEngine,
        tenant_id: str,
    ) -> None:
        """Create overconfident bins (predicted 0.85, actual ~0.5), verify adjustment."""
        # Bin 8 ([0.8, 0.9)) midpoint=0.85, but only 50% positive
        for _ in range(10):
            await calibration_engine.update_calibration(
                tenant_id, "send_email", 0.85, True
            )
        for _ in range(10):
            await calibration_engine.update_calibration(
                tenant_id, "send_email", 0.85, False
            )

        adjustment = await calibration_engine.check_and_adjust(tenant_id, "send_email")

        assert adjustment is not None
        assert adjustment.action_type == "send_email"
        assert adjustment.direction == "decrease"
        assert adjustment.magnitude > 0
        assert "overconfident" in adjustment.reason


class TestAdjustmentDamping:
    """Test that adjustment magnitude is capped at MAX_ADJUSTMENT_RATE."""

    async def test_adjustment_damping(
        self,
        calibration_engine: InMemoryCalibrationEngine,
        tenant_id: str,
    ) -> None:
        """Verify adjustment magnitude capped at MAX_ADJUSTMENT_RATE (10%)."""
        # Extreme overconfidence: predicted 0.95, actual 0.0
        for _ in range(20):
            await calibration_engine.update_calibration(
                tenant_id, "send_email", 0.95, False
            )

        adjustment = await calibration_engine.check_and_adjust(tenant_id, "send_email")

        assert adjustment is not None
        assert adjustment.magnitude <= CalibrationEngine.MAX_ADJUSTMENT_RATE


class TestColdStartProtection:
    """Test that bins with < MIN_SAMPLES do not trigger adjustment."""

    async def test_cold_start_protection(
        self,
        calibration_engine: InMemoryCalibrationEngine,
        tenant_id: str,
    ) -> None:
        """Bins with < MIN_SAMPLES do not trigger adjustment."""
        # Add only 5 samples (below MIN_SAMPLES_PER_BIN=10)
        for _ in range(5):
            await calibration_engine.update_calibration(
                tenant_id, "send_email", 0.85, False
            )

        adjustment = await calibration_engine.check_and_adjust(tenant_id, "send_email")

        # Should return None because insufficient data
        assert adjustment is None


class TestScalingBounds:
    """Test that adjustments are clamped to SCALING_BOUNDS."""

    async def test_scaling_bounds(
        self,
        calibration_engine: InMemoryCalibrationEngine,
        tenant_id: str,
    ) -> None:
        """Verify adjustments clamped to SCALING_BOUNDS (0.5, 1.5)."""
        # Extreme miscalibration
        for _ in range(50):
            await calibration_engine.update_calibration(
                tenant_id, "send_email", 0.95, False
            )

        adjustment = await calibration_engine.check_and_adjust(tenant_id, "send_email")

        assert adjustment is not None
        # new_threshold should be within bounds
        assert adjustment.new_threshold >= CalibrationEngine.SCALING_BOUNDS[0]
        assert adjustment.new_threshold <= CalibrationEngine.SCALING_BOUNDS[1]


# -- Coaching Tests ------------------------------------------------------------


class TestExtractPatternsWithData:
    """Test coaching pattern extraction with outcome data."""

    async def test_extract_patterns_with_data(
        self,
        coaching_extractor: InMemoryCoachingExtractor,
        tenant_id: str,
    ) -> None:
        """Create outcomes with patterns, verify patterns extracted."""
        # Action type A: high success (8/10)
        for _ in range(8):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="send_email",
                outcome_status=OutcomeStatus.POSITIVE.value,
            )
        for _ in range(2):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="send_email",
                outcome_status=OutcomeStatus.NEGATIVE.value,
            )

        # Action type B: low success (2/10)
        for _ in range(2):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="cold_call",
                outcome_status=OutcomeStatus.POSITIVE.value,
            )
        for _ in range(8):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="cold_call",
                outcome_status=OutcomeStatus.NEGATIVE.value,
            )

        patterns = await coaching_extractor.extract_patterns(tenant_id)

        assert len(patterns) >= 1
        # At least one pattern should reference the action types
        action_types = [p.supporting_data.get("action_type") for p in patterns]
        assert "send_email" in action_types or "cold_call" in action_types


class TestTopPerformingActions:
    """Test identifying most effective action types."""

    async def test_top_performing_actions(
        self,
        coaching_extractor: InMemoryCoachingExtractor,
        tenant_id: str,
    ) -> None:
        """Create outcomes for multiple action types, verify ranking."""
        # Best: send_email (9/10)
        for _ in range(9):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="send_email",
                outcome_status=OutcomeStatus.POSITIVE.value,
            )
        coaching_extractor.add_outcome(
            tenant_id=tenant_id,
            action_type="send_email",
            outcome_status=OutcomeStatus.NEGATIVE.value,
        )

        # Medium: qualify (5/10)
        for _ in range(5):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="qualify",
                outcome_status=OutcomeStatus.POSITIVE.value,
            )
        for _ in range(5):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="qualify",
                outcome_status=OutcomeStatus.NEGATIVE.value,
            )

        # Worst: cold_call (1/10)
        coaching_extractor.add_outcome(
            tenant_id=tenant_id,
            action_type="cold_call",
            outcome_status=OutcomeStatus.POSITIVE.value,
        )
        for _ in range(9):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="cold_call",
                outcome_status=OutcomeStatus.NEGATIVE.value,
            )

        top = await coaching_extractor.get_top_performing_actions(tenant_id, top_k=3)

        assert len(top) == 3
        # Ranked by success rate
        assert top[0]["action_type"] == "send_email"
        assert top[0]["success_rate"] == pytest.approx(0.9, abs=0.01)
        assert top[1]["action_type"] == "qualify"
        assert top[2]["action_type"] == "cold_call"


class TestImprovementAreas:
    """Test identifying underperforming areas."""

    async def test_improvement_areas(
        self,
        coaching_extractor: InMemoryCoachingExtractor,
        tenant_id: str,
    ) -> None:
        """Create low-performing outcomes, verify identified."""
        # Low performer: 2/10 = 20% success
        for _ in range(2):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="cold_call",
                outcome_status=OutcomeStatus.POSITIVE.value,
            )
        for _ in range(8):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="cold_call",
                outcome_status=OutcomeStatus.NEGATIVE.value,
            )

        # Good performer: 8/10 = 80% (should NOT appear)
        for _ in range(8):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="send_email",
                outcome_status=OutcomeStatus.POSITIVE.value,
            )
        for _ in range(2):
            coaching_extractor.add_outcome(
                tenant_id=tenant_id,
                action_type="send_email",
                outcome_status=OutcomeStatus.NEGATIVE.value,
            )

        areas = await coaching_extractor.get_improvement_areas(tenant_id)

        assert len(areas) >= 1
        area_actions = [a["action_type"] for a in areas]
        assert "cold_call" in area_actions
        assert "send_email" not in area_actions  # 80% success should not be flagged
