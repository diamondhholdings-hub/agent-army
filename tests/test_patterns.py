"""Unit tests for pattern recognition: detectors, engine, and insight generator.

Tests all 3 pattern detectors (BuyingSignalDetector, RiskIndicatorDetector,
EngagementChangeDetector), the PatternRecognitionEngine orchestration and
filtering, and the InsightGenerator for insight creation, deduplication,
alerting, digests, and feedback.

Uses in-memory test doubles -- no database dependency.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from src.app.intelligence.consolidation.schemas import (
    ChannelInteraction,
    UnifiedCustomerView,
)
from src.app.intelligence.patterns.detectors import (
    BuyingSignalDetector,
    EngagementChangeDetector,
    RiskIndicatorDetector,
)
from src.app.intelligence.patterns.engine import (
    PatternRecognitionEngine,
    create_default_engine,
)
from src.app.intelligence.patterns.insights import InsightGenerator
from src.app.intelligence.patterns.schemas import (
    DailyDigest,
    Insight,
    PatternMatch,
    PatternType,
)


# ── Constants ────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
ACCOUNT_ID = str(uuid.uuid4())
NOW = datetime.now(timezone.utc)


# ── In-Memory Repository Test Double ─────────────────────────────────────────


class InMemoryInsightRepository:
    """Minimal in-memory repository double for InsightGenerator tests.

    Implements only the methods used by InsightGenerator: create_insight,
    list_insights, record_feedback, get_feedback_stats.
    """

    def __init__(self) -> None:
        self.insights: Dict[str, Dict[str, Any]] = {}
        self.feedback: Dict[str, Dict[str, Any]] = {}

    async def create_insight(
        self,
        tenant_id: str,
        account_id: str,
        pattern_type: str,
        pattern_data: Dict[str, Any],
        confidence: float,
        severity: str = "medium",
    ) -> Dict[str, Any]:
        insight_id = str(uuid.uuid4())
        insight = {
            "id": insight_id,
            "tenant_id": tenant_id,
            "account_id": account_id,
            "pattern_type": pattern_type,
            "pattern_data": pattern_data,
            "confidence": confidence,
            "severity": severity,
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "acted_at": None,
        }
        self.insights[insight_id] = insight
        return insight

    async def list_insights(
        self,
        tenant_id: str,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        results = []
        for i in self.insights.values():
            if i["tenant_id"] != tenant_id:
                continue
            if account_id is not None and i["account_id"] != account_id:
                continue
            if status is not None and i["status"] != status:
                continue
            results.append(i)
        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results[:limit]

    async def record_feedback(
        self,
        tenant_id: str,
        insight_id: str,
        feedback: str,
        submitted_by: str,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        feedback_id = str(uuid.uuid4())
        fb = {
            "id": feedback_id,
            "tenant_id": tenant_id,
            "insight_id": insight_id,
            "feedback": feedback,
            "submitted_by": submitted_by,
            "comment": comment,
            "submitted_at": datetime.now(timezone.utc),
        }
        self.feedback[feedback_id] = fb
        return fb

    async def get_feedback_stats(self, tenant_id: str) -> Dict[str, int]:
        stats: Dict[str, int] = {"useful": 0, "false_alarm": 0, "total": 0}
        for fb in self.feedback.values():
            if fb["tenant_id"] == tenant_id:
                stats[fb["feedback"]] = stats.get(fb["feedback"], 0) + 1
                stats["total"] += 1
        return stats


# ── Mock Event Bus ───────────────────────────────────────────────────────────


class MockEventBus:
    """Test double for event bus to capture published alerts."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    async def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        self.events.append({"event_type": event_type, "data": data})


# ── Helper: Build Timeline ───────────────────────────────────────────────────


def _make_interaction(
    channel: str = "email",
    content: str = "General discussion",
    days_ago: int = 0,
    participants: Optional[List[str]] = None,
    key_points: Optional[List[str]] = None,
) -> ChannelInteraction:
    """Helper to create a ChannelInteraction for tests."""
    return ChannelInteraction(
        channel=channel,
        timestamp=NOW - timedelta(days=days_ago),
        participants=participants or [],
        content_summary=content,
        key_points=key_points or [],
    )


def _make_customer_view(
    timeline: Optional[List[ChannelInteraction]] = None,
    signals: Optional[Dict[str, Any]] = None,
) -> UnifiedCustomerView:
    """Helper to create a UnifiedCustomerView for tests."""
    return UnifiedCustomerView(
        tenant_id=TENANT_ID,
        account_id=ACCOUNT_ID,
        timeline=timeline or [],
        signals=signals or {},
        last_updated=NOW,
    )


# ── BuyingSignalDetector Tests ───────────────────────────────────────────────


class TestBuyingSignalDetector:
    """Test buying signal detection: budget, timeline, competitive, stakeholder."""

    @pytest.mark.asyncio
    async def test_detect_budget_mention(self):
        """Budget-related content should produce a buying signal."""
        detector = BuyingSignalDetector()
        timeline = [
            _make_interaction(
                content="We have approved $500K budget for this initiative",
                key_points=["Budget approved at $500K"],
            ),
        ]
        results = await detector.detect(timeline, {})

        assert len(results) >= 1
        budget_signals = [
            r for r in results if "budget" in r.evidence[0].lower() or "$" in r.evidence[0]
        ]
        assert len(budget_signals) >= 1
        assert budget_signals[0].pattern_type == PatternType.buying_signal
        assert budget_signals[0].confidence == 0.8

    @pytest.mark.asyncio
    async def test_detect_timeline_urgency(self):
        """Timeline urgency content should produce a buying signal."""
        detector = BuyingSignalDetector()
        timeline = [
            _make_interaction(content="We need this by end of Q2, deadline is firm"),
        ]
        results = await detector.detect(timeline, {})

        assert len(results) >= 1
        timeline_signals = [
            r for r in results if r.confidence == 0.75
        ]
        assert len(timeline_signals) >= 1
        assert timeline_signals[0].pattern_type == PatternType.buying_signal

    @pytest.mark.asyncio
    async def test_detect_competitive_evaluation(self):
        """Competitive evaluation content should produce a buying signal."""
        detector = BuyingSignalDetector()
        timeline = [
            _make_interaction(
                content="We are comparing your solution with other vendors on our shortlist"
            ),
        ]
        results = await detector.detect(timeline, {})

        assert len(results) >= 1
        comp_signals = [r for r in results if r.confidence == 0.7]
        assert len(comp_signals) >= 1

    @pytest.mark.asyncio
    async def test_detect_no_signals(self):
        """Neutral conversation should produce no buying signals."""
        detector = BuyingSignalDetector()
        timeline = [
            _make_interaction(content="Thanks for the meeting, talk to you later"),
            _make_interaction(content="Sounds good, have a great weekend"),
        ]
        results = await detector.detect(timeline, {})
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_detect_empty_timeline(self):
        """Empty timeline should produce no signals."""
        detector = BuyingSignalDetector()
        results = await detector.detect([], {})
        assert results == []

    @pytest.mark.asyncio
    async def test_detect_stakeholder_expansion(self):
        """More participants in later interactions should detect expansion."""
        detector = BuyingSignalDetector()
        timeline = [
            _make_interaction(
                content="Initial call",
                days_ago=20,
                participants=["alice@acme.com"],
            ),
            _make_interaction(
                content="Follow up call",
                days_ago=15,
                participants=["alice@acme.com"],
            ),
            _make_interaction(
                content="Team review",
                days_ago=5,
                participants=["alice@acme.com", "bob@acme.com", "carol@acme.com"],
            ),
            _make_interaction(
                content="Executive meeting",
                days_ago=1,
                participants=["alice@acme.com", "bob@acme.com", "carol@acme.com", "dave@acme.com"],
            ),
        ]
        results = await detector.detect(timeline, {})

        stakeholder_signals = [
            r for r in results if "stakeholder" in r.evidence[0].lower()
        ]
        assert len(stakeholder_signals) >= 1
        assert stakeholder_signals[0].confidence == 0.65


# ── RiskIndicatorDetector Tests ──────────────────────────────────────────────


class TestRiskIndicatorDetector:
    """Test risk indicator detection: silence, freeze, departure, competitor."""

    @pytest.mark.asyncio
    async def test_detect_radio_silence(self):
        """No interactions in 14+ days should detect radio silence."""
        detector = RiskIndicatorDetector()
        timeline = [
            _make_interaction(content="Last contact", days_ago=20),
        ]
        results = await detector.detect(timeline, {})

        silence_signals = [
            r for r in results if "no interactions" in r.evidence[0].lower()
        ]
        assert len(silence_signals) >= 1
        assert silence_signals[0].confidence == 0.8
        assert silence_signals[0].severity == "high"

    @pytest.mark.asyncio
    async def test_detect_budget_freeze(self):
        """Budget freeze language should detect risk."""
        detector = RiskIndicatorDetector()
        timeline = [
            _make_interaction(
                content="Unfortunately we have a budget freeze across the company"
            ),
        ]
        results = await detector.detect(timeline, {})

        freeze_signals = [
            r for r in results if "budget freeze" in r.evidence[0].lower()
        ]
        assert len(freeze_signals) >= 1
        assert freeze_signals[0].confidence == 0.75
        assert freeze_signals[0].severity == "high"

    @pytest.mark.asyncio
    async def test_detect_champion_departure(self):
        """Champion departure language should detect critical risk."""
        detector = RiskIndicatorDetector()
        timeline = [
            _make_interaction(
                content="Just wanted to let you know Sarah is leaving the company next month"
            ),
        ]
        results = await detector.detect(timeline, {})

        departure_signals = [
            r for r in results if "departure" in r.evidence[0].lower()
        ]
        assert len(departure_signals) >= 1
        assert departure_signals[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_detect_competitor_preference(self):
        """Competitor preference language should detect risk."""
        detector = RiskIndicatorDetector()
        timeline = [
            _make_interaction(
                content="Honestly, we are leaning toward the other vendor as a better fit"
            ),
        ]
        results = await detector.detect(timeline, {})

        pref_signals = [
            r for r in results if "competitor preference" in r.evidence[0].lower()
        ]
        assert len(pref_signals) >= 1
        assert pref_signals[0].confidence == 0.75

    @pytest.mark.asyncio
    async def test_detect_no_risks(self):
        """Healthy engagement should produce no risk signals."""
        detector = RiskIndicatorDetector()
        timeline = [
            _make_interaction(content="Great meeting today!", days_ago=1),
            _make_interaction(content="Looking forward to next steps", days_ago=0),
        ]
        results = await detector.detect(timeline, {})
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_detect_empty_timeline(self):
        """Empty timeline should produce no risk signals."""
        detector = RiskIndicatorDetector()
        results = await detector.detect([], {})
        assert results == []


# ── EngagementChangeDetector Tests ───────────────────────────────────────────


class TestEngagementChangeDetector:
    """Test engagement change detection: rate, attendance, depth."""

    @pytest.mark.asyncio
    async def test_detect_increasing_engagement(self):
        """Higher recent activity rate should detect positive change."""
        detector = EngagementChangeDetector()

        # Baseline: ~1 interaction over the baseline window (days 8-30)
        # Recent: 5 interactions in last 7 days
        timeline = [
            _make_interaction(content="Baseline contact", days_ago=20),
        ]
        # Add 5 recent interactions
        for i in range(5):
            timeline.append(
                _make_interaction(
                    content=f"Active discussion point {i}",
                    days_ago=i,
                )
            )

        results = await detector.detect(timeline, {})

        increasing = [
            r
            for r in results
            if r.pattern_type == PatternType.engagement_change
            and "increased" in r.evidence[0].lower()
        ]
        assert len(increasing) >= 1

    @pytest.mark.asyncio
    async def test_detect_decreasing_engagement(self):
        """Lower recent activity rate should detect negative change."""
        detector = EngagementChangeDetector()

        # Baseline: many interactions in days 8-30
        timeline = []
        for i in range(10):
            timeline.append(
                _make_interaction(
                    content=f"Regular contact {i}",
                    days_ago=8 + i * 2,
                )
            )

        # Recent: zero interactions in last 7 days
        # (no items with days_ago < 7)

        results = await detector.detect(timeline, {})

        decreasing = [
            r
            for r in results
            if r.pattern_type == PatternType.engagement_change
            and "decreased" in r.evidence[0].lower()
        ]
        assert len(decreasing) >= 1

    @pytest.mark.asyncio
    async def test_stable_engagement(self):
        """Consistent engagement rate should produce no change signals."""
        detector = EngagementChangeDetector()

        # Roughly equal distribution across baseline and recent periods
        timeline = []
        # 3 interactions in baseline (days 8-30, so ~23-day window)
        for i in range(3):
            timeline.append(
                _make_interaction(
                    content=f"Baseline interaction {i}",
                    days_ago=10 + i * 5,
                )
            )
        # 1 interaction in recent (last 7 days)
        # Baseline rate: 3/23 = 0.13/day, Recent rate: 1/7 = 0.14/day
        # Difference is <30%, so should be stable
        timeline.append(
            _make_interaction(content="Recent interaction", days_ago=3)
        )

        results = await detector.detect(timeline, {})

        # Should not detect any engagement changes since rates are similar
        engagement_changes = [
            r for r in results if r.pattern_type == PatternType.engagement_change
        ]
        assert len(engagement_changes) == 0

    @pytest.mark.asyncio
    async def test_detect_empty_timeline(self):
        """Empty timeline produces no engagement change signals."""
        detector = EngagementChangeDetector()
        results = await detector.detect([], {})
        assert results == []

    @pytest.mark.asyncio
    async def test_no_baseline_returns_empty(self):
        """If no baseline interactions exist, return empty."""
        detector = EngagementChangeDetector()
        # Only recent interactions, nothing in baseline window
        timeline = [
            _make_interaction(content="Recent only", days_ago=1),
        ]
        results = await detector.detect(timeline, {})
        assert results == []


# ── PatternRecognitionEngine Tests ───────────────────────────────────────────


class _MockDetector:
    """Test double detector that returns predetermined patterns."""

    def __init__(self, patterns: List[PatternMatch]) -> None:
        self._patterns = patterns

    async def detect(
        self,
        timeline: List[ChannelInteraction],
        signals: Dict[str, Any],
    ) -> List[PatternMatch]:
        return self._patterns


class _FailingDetector:
    """Test double detector that raises an exception."""

    async def detect(
        self,
        timeline: List[ChannelInteraction],
        signals: Dict[str, Any],
    ) -> List[PatternMatch]:
        raise RuntimeError("Detector failure")


class TestPatternRecognitionEngine:
    """Test engine orchestration, filtering, and sorting."""

    @pytest.mark.asyncio
    async def test_detect_patterns_filters_by_confidence(self):
        """Patterns below confidence threshold should be filtered out."""
        low_conf = PatternMatch(
            pattern_type=PatternType.buying_signal,
            confidence=0.5,  # Below 0.7 threshold
            severity="medium",
            evidence=["Evidence A", "Evidence B"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )
        high_conf = PatternMatch(
            pattern_type=PatternType.buying_signal,
            confidence=0.85,
            severity="high",
            evidence=["Evidence C", "Evidence D"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )

        engine = PatternRecognitionEngine(
            detectors=[_MockDetector([low_conf, high_conf])],
            confidence_threshold=0.7,
        )
        view = _make_customer_view()
        results = await engine.detect_patterns(view)

        assert len(results) == 1
        assert results[0].confidence == 0.85

    @pytest.mark.asyncio
    async def test_detect_patterns_filters_by_evidence(self):
        """Patterns with fewer than min_evidence_count should be filtered."""
        one_evidence = PatternMatch(
            pattern_type=PatternType.risk_indicator,
            confidence=0.9,
            severity="high",
            evidence=["Only one piece"],  # Only 1 evidence
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )
        two_evidence = PatternMatch(
            pattern_type=PatternType.risk_indicator,
            confidence=0.85,
            severity="high",
            evidence=["Evidence A", "Evidence B"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )

        engine = PatternRecognitionEngine(
            detectors=[_MockDetector([one_evidence, two_evidence])],
            min_evidence_count=2,
        )
        view = _make_customer_view()
        results = await engine.detect_patterns(view)

        assert len(results) == 1
        assert len(results[0].evidence) == 2

    @pytest.mark.asyncio
    async def test_update_confidence_threshold(self):
        """Threshold should be clamped to [0.3, 0.95]."""
        engine = PatternRecognitionEngine(detectors=[])

        engine.update_confidence_threshold(0.1)
        assert engine.confidence_threshold == 0.3  # Clamped up

        engine.update_confidence_threshold(0.99)
        assert engine.confidence_threshold == 0.95  # Clamped down

        engine.update_confidence_threshold(0.6)
        assert engine.confidence_threshold == 0.6  # Within range

    @pytest.mark.asyncio
    async def test_detect_patterns_sorted_by_severity(self):
        """Results should be sorted: critical > high > medium > low."""
        patterns = [
            PatternMatch(
                pattern_type=PatternType.risk_indicator,
                confidence=0.8,
                severity="low",
                evidence=["A", "B"],
                detected_at=NOW,
                account_id=ACCOUNT_ID,
            ),
            PatternMatch(
                pattern_type=PatternType.risk_indicator,
                confidence=0.85,
                severity="critical",
                evidence=["C", "D"],
                detected_at=NOW,
                account_id=ACCOUNT_ID,
            ),
            PatternMatch(
                pattern_type=PatternType.buying_signal,
                confidence=0.75,
                severity="high",
                evidence=["E", "F"],
                detected_at=NOW,
                account_id=ACCOUNT_ID,
            ),
            PatternMatch(
                pattern_type=PatternType.engagement_change,
                confidence=0.7,
                severity="medium",
                evidence=["G", "H"],
                detected_at=NOW,
                account_id=ACCOUNT_ID,
            ),
        ]

        engine = PatternRecognitionEngine(
            detectors=[_MockDetector(patterns)],
            confidence_threshold=0.7,
        )
        view = _make_customer_view()
        results = await engine.detect_patterns(view)

        assert len(results) == 4
        assert results[0].severity == "critical"
        assert results[1].severity == "high"
        assert results[2].severity == "medium"
        assert results[3].severity == "low"

    @pytest.mark.asyncio
    async def test_failing_detector_is_skipped(self):
        """A failing detector should not prevent others from running."""
        good_pattern = PatternMatch(
            pattern_type=PatternType.buying_signal,
            confidence=0.9,
            severity="high",
            evidence=["Evidence X", "Evidence Y"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )

        engine = PatternRecognitionEngine(
            detectors=[
                _FailingDetector(),
                _MockDetector([good_pattern]),
            ],
        )
        view = _make_customer_view()
        results = await engine.detect_patterns(view)

        assert len(results) == 1
        assert results[0].confidence == 0.9

    @pytest.mark.asyncio
    async def test_create_default_engine(self):
        """Factory function should create engine with 3 detectors."""
        engine = create_default_engine()
        assert len(engine._detectors) == 3
        assert engine.confidence_threshold == 0.7

    @pytest.mark.asyncio
    async def test_engine_stamps_account_id(self):
        """Engine should fill in blank account_id from customer view."""
        pattern = PatternMatch(
            pattern_type=PatternType.buying_signal,
            confidence=0.9,
            severity="high",
            evidence=["A", "B"],
            detected_at=NOW,
            account_id="",  # Empty -- engine should fill in
        )

        engine = PatternRecognitionEngine(
            detectors=[_MockDetector([pattern])],
        )
        view = _make_customer_view()
        results = await engine.detect_patterns(view)

        assert len(results) == 1
        assert results[0].account_id == ACCOUNT_ID


# ── InsightGenerator Tests ───────────────────────────────────────────────────


class TestInsightGenerator:
    """Test insight creation, deduplication, alerts, digests, and feedback."""

    @pytest.fixture
    def repo(self) -> InMemoryInsightRepository:
        return InMemoryInsightRepository()

    @pytest.fixture
    def event_bus(self) -> MockEventBus:
        return MockEventBus()

    @pytest.fixture
    def generator(
        self, repo: InMemoryInsightRepository, event_bus: MockEventBus
    ) -> InsightGenerator:
        return InsightGenerator(repository=repo, event_bus=event_bus)

    def _make_pattern(
        self,
        pattern_type: PatternType = PatternType.buying_signal,
        confidence: float = 0.85,
        severity: str = "high",
    ) -> PatternMatch:
        return PatternMatch(
            pattern_type=pattern_type,
            confidence=confidence,
            severity=severity,
            evidence=["Evidence A", "Evidence B"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )

    @pytest.mark.asyncio
    async def test_create_insight(self, generator: InsightGenerator):
        """Creating an insight should persist it via repository."""
        pattern = self._make_pattern()
        insight = await generator.create_insight(TENANT_ID, pattern)

        assert isinstance(insight, Insight)
        assert insight.tenant_id == TENANT_ID
        assert insight.pattern.pattern_type == PatternType.buying_signal
        assert insight.status == "pending"
        assert insight.id is not None

    @pytest.mark.asyncio
    async def test_batch_deduplication(self, generator: InsightGenerator):
        """Duplicate pattern+account within batch should be skipped."""
        pattern1 = self._make_pattern(
            pattern_type=PatternType.buying_signal, confidence=0.8
        )
        pattern2 = self._make_pattern(
            pattern_type=PatternType.buying_signal, confidence=0.9
        )
        pattern3 = self._make_pattern(
            pattern_type=PatternType.risk_indicator, confidence=0.75
        )

        results = await generator.create_insights_batch(
            TENANT_ID, [pattern1, pattern2, pattern3]
        )

        # pattern1 and pattern2 are same (account_id, buying_signal) -- dedup
        # pattern3 is different (risk_indicator) -- kept
        assert len(results) == 2
        types = {r.pattern.pattern_type for r in results}
        assert PatternType.buying_signal in types
        assert PatternType.risk_indicator in types

    @pytest.mark.asyncio
    async def test_send_alert_with_event_bus(
        self,
        generator: InsightGenerator,
        event_bus: MockEventBus,
    ):
        """Alert should be published to event bus and have delivered_at."""
        pattern = self._make_pattern(severity="critical")
        insight = await generator.create_insight(TENANT_ID, pattern)
        alert = await generator.send_alert(insight)

        assert alert.delivered_at is not None
        assert alert.channel == "sse"
        assert len(event_bus.events) == 1
        assert event_bus.events[0]["event_type"] == "insight_alert"

    @pytest.mark.asyncio
    async def test_send_alert_without_event_bus(
        self, repo: InMemoryInsightRepository
    ):
        """Alert without event bus should have delivered_at=None."""
        generator = InsightGenerator(repository=repo, event_bus=None)
        pattern = self._make_pattern(severity="critical")
        insight = await generator.create_insight(TENANT_ID, pattern)
        alert = await generator.send_alert(insight)

        assert alert.delivered_at is None
        assert alert.channel == "sse"

    @pytest.mark.asyncio
    async def test_should_alert_realtime_critical(self):
        """Critical severity should trigger real-time alert."""
        pattern = PatternMatch(
            pattern_type=PatternType.risk_indicator,
            confidence=0.9,
            severity="critical",
            evidence=["A", "B"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )
        assert InsightGenerator._should_alert_realtime(pattern) is True

    @pytest.mark.asyncio
    async def test_should_alert_realtime_high(self):
        """High severity should trigger real-time alert."""
        pattern = PatternMatch(
            pattern_type=PatternType.buying_signal,
            confidence=0.85,
            severity="high",
            evidence=["A", "B"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )
        assert InsightGenerator._should_alert_realtime(pattern) is True

    @pytest.mark.asyncio
    async def test_should_alert_realtime_low(self):
        """Low severity should NOT trigger real-time alert."""
        pattern = PatternMatch(
            pattern_type=PatternType.engagement_change,
            confidence=0.7,
            severity="low",
            evidence=["A", "B"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )
        assert InsightGenerator._should_alert_realtime(pattern) is False

    @pytest.mark.asyncio
    async def test_should_alert_realtime_medium(self):
        """Medium severity should NOT trigger real-time alert."""
        pattern = PatternMatch(
            pattern_type=PatternType.engagement_change,
            confidence=0.75,
            severity="medium",
            evidence=["A", "B"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )
        assert InsightGenerator._should_alert_realtime(pattern) is False

    @pytest.mark.asyncio
    async def test_generate_daily_digest(self, generator: InsightGenerator):
        """Daily digest should aggregate recent pending insights."""
        # Create a few insights
        for ptype in [PatternType.buying_signal, PatternType.risk_indicator]:
            pattern = self._make_pattern(pattern_type=ptype)
            await generator.create_insight(TENANT_ID, pattern)

        digest = await generator.generate_daily_digest(TENANT_ID)

        assert isinstance(digest, DailyDigest)
        assert digest.tenant_id == TENANT_ID
        assert len(digest.insights) == 2
        assert ACCOUNT_ID in digest.grouped_by_account
        assert len(digest.grouped_by_account[ACCOUNT_ID]) == 2

    @pytest.mark.asyncio
    async def test_process_feedback(self, generator: InsightGenerator):
        """Feedback should be recorded successfully."""
        pattern = self._make_pattern()
        insight = await generator.create_insight(TENANT_ID, pattern)

        result = await generator.process_feedback(
            TENANT_ID, insight.id, "useful", "Very helpful alert"
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_get_feedback_summary(
        self,
        generator: InsightGenerator,
        repo: InMemoryInsightRepository,
    ):
        """Feedback summary should compute accuracy rate."""
        # Create insights and record feedback
        for _ in range(3):
            pattern = self._make_pattern()
            insight = await generator.create_insight(TENANT_ID, pattern)
            await generator.process_feedback(TENANT_ID, insight.id, "useful")

        pattern = self._make_pattern(pattern_type=PatternType.risk_indicator)
        insight = await generator.create_insight(TENANT_ID, pattern)
        await generator.process_feedback(TENANT_ID, insight.id, "false_alarm")

        summary = await generator.get_feedback_summary(TENANT_ID)

        assert summary["useful_count"] == 3
        assert summary["false_alarm_count"] == 1
        assert summary["total"] == 4
        assert summary["accuracy_rate"] == 0.75

    @pytest.mark.asyncio
    async def test_is_duplicate_within_24h(self):
        """Duplicate check should match within 24-hour window."""
        existing = [
            {
                "account_id": ACCOUNT_ID,
                "pattern_type": "buying_signal",
                "status": "pending",
                "created_at": NOW - timedelta(hours=12),
            }
        ]
        pattern = PatternMatch(
            pattern_type=PatternType.buying_signal,
            confidence=0.85,
            severity="high",
            evidence=["A", "B"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )

        assert InsightGenerator._is_duplicate(existing, pattern) is True

    @pytest.mark.asyncio
    async def test_is_not_duplicate_different_type(self):
        """Different pattern type should not be a duplicate."""
        existing = [
            {
                "account_id": ACCOUNT_ID,
                "pattern_type": "buying_signal",
                "status": "pending",
                "created_at": NOW - timedelta(hours=12),
            }
        ]
        pattern = PatternMatch(
            pattern_type=PatternType.risk_indicator,
            confidence=0.85,
            severity="high",
            evidence=["A", "B"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )

        assert InsightGenerator._is_duplicate(existing, pattern) is False

    @pytest.mark.asyncio
    async def test_is_not_duplicate_after_24h(self):
        """Insight older than 24 hours should not count as duplicate."""
        existing = [
            {
                "account_id": ACCOUNT_ID,
                "pattern_type": "buying_signal",
                "status": "pending",
                "created_at": NOW - timedelta(hours=48),
            }
        ]
        pattern = PatternMatch(
            pattern_type=PatternType.buying_signal,
            confidence=0.85,
            severity="high",
            evidence=["A", "B"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )

        assert InsightGenerator._is_duplicate(existing, pattern) is False
