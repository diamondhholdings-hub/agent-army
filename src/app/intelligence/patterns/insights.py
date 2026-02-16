"""Insight generation -- converts detected patterns into actionable insights.

InsightGenerator creates persisted insights from detected patterns, sends
real-time alerts for critical/high severity patterns, generates daily
digests for lower-priority patterns, and tracks feedback for threshold tuning.

Real-time alerts are published to an event bus for SSE delivery. Daily
digests aggregate insights by account for a 24-hour summary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

from src.app.intelligence.patterns.schemas import (
    Alert,
    DailyDigest,
    Insight,
    PatternMatch,
)

logger = structlog.get_logger(__name__)


class InsightGenerator:
    """Creates insights from detected patterns and manages alert delivery.

    Handles the full lifecycle from pattern detection to actionable insight:
    persistence via repository, real-time alerts for critical patterns,
    daily digests for lower-priority patterns, and feedback tracking.

    Args:
        repository: IntelligenceRepository (or compatible) for persistence.
            Must have ``create_insight``, ``list_insights``,
            ``record_feedback``, and ``get_feedback_stats`` methods.
        event_bus: Optional event bus for real-time alert delivery via SSE.
            Must have a ``publish`` method. If None, alerts are created
            but not delivered in real-time.
    """

    def __init__(
        self,
        repository: Any,
        event_bus: Optional[Any] = None,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus

    async def create_insight(
        self, tenant_id: str, pattern: PatternMatch
    ) -> Insight:
        """Persist a detected pattern as an insight.

        Args:
            tenant_id: Tenant identifier.
            pattern: Detected pattern to persist.

        Returns:
            Created Insight with unique ID and pending status.
        """
        insight_data = await self._repository.create_insight(
            tenant_id=tenant_id,
            account_id=pattern.account_id,
            pattern_type=pattern.pattern_type.value,
            pattern_data=pattern.model_dump(mode="json"),
            confidence=pattern.confidence,
            severity=pattern.severity,
        )

        insight = Insight(
            id=insight_data["id"],
            tenant_id=tenant_id,
            pattern=pattern,
            status="pending",
            created_at=insight_data["created_at"],
        )

        logger.info(
            "insights.created",
            insight_id=insight.id,
            tenant_id=tenant_id,
            pattern_type=pattern.pattern_type.value,
            confidence=pattern.confidence,
        )

        return insight

    async def create_insights_batch(
        self, tenant_id: str, patterns: List[PatternMatch]
    ) -> List[Insight]:
        """Create insights from a batch of patterns with deduplication.

        Deduplicates by (account_id, pattern_type): if an identical
        pending insight exists for the same account and pattern type
        created in the last 24 hours, it is skipped to prevent alert
        flooding.

        Args:
            tenant_id: Tenant identifier.
            patterns: List of detected patterns to persist.

        Returns:
            List of created Insight objects (excluding duplicates).
        """
        # Fetch existing pending insights for dedup check
        existing_insights = await self._repository.list_insights(
            tenant_id=tenant_id,
            status="pending",
        )

        created: List[Insight] = []
        for pattern in patterns:
            if self._is_duplicate(existing_insights, pattern):
                logger.debug(
                    "insights.duplicate_skipped",
                    tenant_id=tenant_id,
                    account_id=pattern.account_id,
                    pattern_type=pattern.pattern_type.value,
                )
                continue

            insight = await self.create_insight(tenant_id, pattern)
            created.append(insight)

            # Add to existing list so subsequent patterns in the batch
            # can also be checked for dedup
            existing_insights.append(
                {
                    "account_id": pattern.account_id,
                    "pattern_type": pattern.pattern_type.value,
                    "status": "pending",
                    "created_at": insight.created_at,
                }
            )

        logger.info(
            "insights.batch_created",
            tenant_id=tenant_id,
            total_patterns=len(patterns),
            created=len(created),
            deduplicated=len(patterns) - len(created),
        )

        return created

    async def send_alert(self, insight: Insight) -> Alert:
        """Send a real-time alert for a critical/high severity insight.

        Publishes the alert to the event bus for SSE delivery. If the
        event bus is not configured, creates the Alert record with
        delivered_at=None and logs a warning.

        Args:
            insight: Insight to alert on.

        Returns:
            Alert record with delivery status.
        """
        now = datetime.now(timezone.utc)

        if self._event_bus is not None:
            try:
                await self._event_bus.publish(
                    event_type="insight_alert",
                    data={
                        "insight_id": insight.id,
                        "tenant_id": insight.tenant_id,
                        "pattern_type": insight.pattern.pattern_type.value,
                        "severity": insight.pattern.severity,
                        "confidence": insight.pattern.confidence,
                        "account_id": insight.pattern.account_id,
                        "evidence": insight.pattern.evidence,
                    },
                )
                alert = Alert(
                    insight_id=insight.id,
                    tenant_id=insight.tenant_id,
                    delivered_at=now,
                    channel="sse",
                )
                logger.info(
                    "insights.alert_sent",
                    insight_id=insight.id,
                    channel="sse",
                )
            except Exception:
                logger.warning(
                    "insights.alert_delivery_failed",
                    insight_id=insight.id,
                    exc_info=True,
                )
                alert = Alert(
                    insight_id=insight.id,
                    tenant_id=insight.tenant_id,
                    delivered_at=None,
                    channel="sse",
                )
        else:
            logger.warning(
                "insights.no_event_bus",
                insight_id=insight.id,
                message="Event bus not configured; alert not delivered",
            )
            alert = Alert(
                insight_id=insight.id,
                tenant_id=insight.tenant_id,
                delivered_at=None,
                channel="sse",
            )

        return alert

    async def generate_daily_digest(
        self,
        tenant_id: str,
        clone_id: Optional[str] = None,
    ) -> DailyDigest:
        """Generate a daily digest of pending insights from the last 24 hours.

        Aggregates all pending insights, groups by account, and sorts
        by severity within each group.

        Args:
            tenant_id: Tenant identifier.
            clone_id: Optional clone filter (None for tenant-wide digest).

        Returns:
            DailyDigest with insights grouped by account.
        """
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(hours=24)

        # Fetch all pending insights
        all_insights = await self._repository.list_insights(
            tenant_id=tenant_id,
            status="pending",
        )

        # Filter to last 24 hours
        recent_insights = [
            i
            for i in all_insights
            if i.get("created_at") and i["created_at"] >= period_start
        ]

        # Convert repo dicts to Insight schemas
        insight_objects: List[Insight] = []
        for data in recent_insights:
            try:
                pattern = PatternMatch(
                    pattern_type=data["pattern_data"].get(
                        "pattern_type", data["pattern_type"]
                    ),
                    confidence=data["confidence"],
                    severity=data["severity"],
                    evidence=data["pattern_data"].get("evidence", []),
                    detected_at=data["pattern_data"].get(
                        "detected_at", data["created_at"]
                    ),
                    account_id=data["account_id"],
                )
                insight = Insight(
                    id=data["id"],
                    tenant_id=tenant_id,
                    pattern=pattern,
                    status=data["status"],
                    created_at=data["created_at"],
                )
                insight_objects.append(insight)
            except Exception:
                logger.warning(
                    "insights.digest_parse_error",
                    insight_id=data.get("id"),
                    exc_info=True,
                )
                continue

        # Group by account
        grouped: Dict[str, List[Insight]] = {}
        for insight in insight_objects:
            account = insight.pattern.account_id
            if account not in grouped:
                grouped[account] = []
            grouped[account].append(insight)

        digest = DailyDigest(
            tenant_id=tenant_id,
            clone_id=clone_id,
            period_start=period_start,
            period_end=now,
            insights=insight_objects,
            grouped_by_account=grouped,
        )

        logger.info(
            "insights.daily_digest_generated",
            tenant_id=tenant_id,
            clone_id=clone_id,
            total_insights=len(insight_objects),
            accounts=len(grouped),
        )

        return digest

    async def process_feedback(
        self,
        tenant_id: str,
        insight_id: str,
        feedback: str,
        comment: Optional[str] = None,
    ) -> bool:
        """Record feedback on an insight's usefulness.

        Args:
            tenant_id: Tenant identifier.
            insight_id: Insight to provide feedback on.
            feedback: "useful" or "false_alarm".
            comment: Optional comment with additional context.

        Returns:
            True on success, False if recording failed.
        """
        try:
            await self._repository.record_feedback(
                tenant_id=tenant_id,
                insight_id=insight_id,
                feedback=feedback,
                submitted_by="system",
                comment=comment,
            )
            logger.info(
                "insights.feedback_recorded",
                insight_id=insight_id,
                feedback=feedback,
            )
            return True
        except Exception:
            logger.warning(
                "insights.feedback_recording_failed",
                insight_id=insight_id,
                exc_info=True,
            )
            return False

    async def get_feedback_summary(self, tenant_id: str) -> Dict[str, Any]:
        """Get feedback statistics for threshold tuning.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Dict with useful_count, false_alarm_count, and accuracy_rate.
        """
        stats = await self._repository.get_feedback_stats(tenant_id)

        total = stats.get("total", 0)
        useful = stats.get("useful", 0)
        false_alarm = stats.get("false_alarm", 0)

        accuracy_rate = useful / total if total > 0 else 0.0

        return {
            "useful_count": useful,
            "false_alarm_count": false_alarm,
            "total": total,
            "accuracy_rate": round(accuracy_rate, 3),
        }

    @staticmethod
    def _should_alert_realtime(pattern: PatternMatch) -> bool:
        """Determine if a pattern warrants a real-time alert.

        Real-time alerts are sent for critical and high severity patterns.
        Lower severity patterns are included in the daily digest only.

        Args:
            pattern: Pattern to evaluate.

        Returns:
            True if severity is 'critical' or 'high'.
        """
        return pattern.severity in ("critical", "high")

    @staticmethod
    def _is_duplicate(
        existing_insights: List[Dict[str, Any]],
        pattern: PatternMatch,
    ) -> bool:
        """Check if a pattern already has a pending insight within 24 hours.

        Deduplicates by (account_id, pattern_type) within a 24-hour window.

        Args:
            existing_insights: List of existing insight dicts.
            pattern: New pattern to check against.

        Returns:
            True if a duplicate pending insight exists within 24 hours.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)

        for existing in existing_insights:
            if (
                existing.get("account_id") == pattern.account_id
                and existing.get("pattern_type") == pattern.pattern_type.value
                and existing.get("status") == "pending"
                and existing.get("created_at") is not None
                and existing["created_at"] >= cutoff
            ):
                return True

        return False
