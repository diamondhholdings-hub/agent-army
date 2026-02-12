"""AnalyticsService for role-based performance analytics dashboards.

Provides three dashboard views matching CONTEXT.md locked decisions:
- Sales reps: Individual agent performance
- Managers: Team-level trends and coaching opportunities
- Executives: Strategic ROI and effectiveness metrics

Uses pre-computed aggregates where possible (cached in Redis with 5-min TTL
per RESEARCH.md Pitfall 4 recommendation).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.learning.models import FeedbackEntryModel, OutcomeRecordModel
from src.app.learning.schemas import OutcomeStatus

logger = structlog.get_logger(__name__)


class AnalyticsService:
    """Role-based analytics computation from outcome/feedback/calibration data.

    Provides three dashboard views matching CONTEXT.md locked decisions:
    - Sales reps: Individual agent performance
    - Managers: Team-level trends and coaching opportunities
    - Executives: Strategic ROI and effectiveness metrics

    Uses pre-computed aggregates where possible (cached in Redis with 5-min TTL
    per RESEARCH.md Pitfall 4 recommendation).
    """

    CACHE_TTL = 300  # 5 minutes

    def __init__(
        self,
        session_factory: Callable[..., AsyncGenerator[AsyncSession, None]],
        outcome_tracker,
        feedback_collector,
        calibration_engine,
        coaching_extractor,
        redis_client=None,
    ):
        """Accept all learning services for cross-component analytics.

        Args:
            session_factory: Async callable that yields AsyncSession instances.
            outcome_tracker: OutcomeTracker service instance.
            feedback_collector: FeedbackCollector service instance.
            calibration_engine: CalibrationEngine service instance.
            coaching_extractor: CoachingPatternExtractor service instance.
            redis_client: Optional Redis client for caching.
        """
        self._session_factory = session_factory
        self._outcome_tracker = outcome_tracker
        self._feedback_collector = feedback_collector
        self._calibration_engine = calibration_engine
        self._coaching_extractor = coaching_extractor
        self._redis = redis_client

    async def get_rep_dashboard(
        self, tenant_id: str, rep_id: str | None = None, days: int = 30
    ) -> dict:
        """Individual agent performance for a sales rep.

        Returns metrics including response rates, deal impact, feedback scores,
        and calibration summary for the specified period.

        Args:
            tenant_id: Tenant UUID string.
            rep_id: Optional rep ID filter (currently unused, reserved for
                    per-rep filtering when multi-rep support is added).
            days: Number of days to look back (default 30).

        Returns:
            Dict with role, period_days, response_rates, deal_impact,
            feedback_scores, calibration_summary, and generated_at.
        """
        cache_key = f"analytics:rep:{tenant_id}:{rep_id}:{days}"
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)

        # Compute outcome metrics
        outcome_data = await self._get_outcome_metrics(tenant_id, cutoff)

        # Compute feedback metrics
        feedback_summary = await self._feedback_collector.get_feedback_summary(
            tenant_id, days=days
        )

        # Compute calibration summary
        calibration_data = await self._get_calibration_summary(tenant_id)

        result = {
            "role": "rep",
            "period_days": days,
            "response_rates": outcome_data["response_rates"],
            "escalation_history": [],
            "deal_impact": outcome_data["deal_impact"],
            "feedback_scores": {
                "average_rating": feedback_summary.get("average_rating", 0.0),
                "total_feedbacks": feedback_summary.get("total_feedback_count", 0),
                "recent_trend": self._compute_trend(
                    feedback_summary.get("feedback_rate_trend", [])
                ),
            },
            "calibration_summary": calibration_data,
            "generated_at": now.isoformat(),
        }

        await self._set_cached(cache_key, result)
        return result

    async def get_manager_dashboard(
        self, tenant_id: str, days: int = 30
    ) -> dict:
        """Team-level performance for managers.

        Returns team trends, comparative performance by action type,
        coaching opportunities, aggregate calibration, escalation rate,
        and feedback health.

        Args:
            tenant_id: Tenant UUID string.
            days: Number of days to look back (default 30).

        Returns:
            Dict with role, period_days, team_trends, comparative_performance,
            coaching_opportunities, aggregate_calibration, escalation_rate,
            feedback_health, and generated_at.
        """
        cache_key = f"analytics:manager:{tenant_id}:{days}"
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)

        outcome_data = await self._get_outcome_metrics(tenant_id, cutoff)
        feedback_summary = await self._feedback_collector.get_feedback_summary(
            tenant_id, days=days
        )
        calibration_data = await self._get_calibration_summary(tenant_id)

        # Coaching opportunities
        coaching_patterns = await self._coaching_extractor.extract_patterns(
            tenant_id, days=days
        )
        coaching_opps = [
            {
                "pattern": p.description,
                "recommendation": p.recommendation,
                "confidence": p.confidence,
            }
            for p in coaching_patterns[:5]
        ]

        # Compute escalation rate
        total = outcome_data["response_rates"]["total_actions"]
        escalation_outcomes = outcome_data.get("escalation_count", 0)
        escalation_rate = escalation_outcomes / total if total > 0 else 0.0

        result = {
            "role": "manager",
            "period_days": days,
            "team_trends": {
                "total_outcomes": total,
                "success_rate": outcome_data["response_rates"]["success_rate"],
                "trend": self._compute_trend(
                    outcome_data.get("daily_activity", [])
                ),
                "daily_activity": outcome_data.get("daily_activity", []),
            },
            "comparative_performance": outcome_data.get(
                "by_action_type", []
            ),
            "coaching_opportunities": coaching_opps,
            "aggregate_calibration": calibration_data,
            "escalation_rate": round(escalation_rate, 4),
            "feedback_health": {
                "submission_rate": feedback_summary.get("average_rating", 0.0),
                "coverage_percent": min(
                    feedback_summary.get("total_feedback_count", 0)
                    / max(total, 1)
                    * 100,
                    100.0,
                ),
            },
            "generated_at": now.isoformat(),
        }

        await self._set_cached(cache_key, result)
        return result

    async def get_executive_summary(
        self, tenant_id: str, days: int = 30
    ) -> dict:
        """Strategic insights for executives.

        Returns ROI metrics, agent effectiveness, engagement trends,
        and strategic insights.

        Args:
            tenant_id: Tenant UUID string.
            days: Number of days to look back (default 30).

        Returns:
            Dict with role, period_days, roi_metrics, agent_effectiveness,
            engagement_trends, strategic_insights, and generated_at.
        """
        cache_key = f"analytics:executive:{tenant_id}:{days}"
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)

        outcome_data = await self._get_outcome_metrics(tenant_id, cutoff)
        total = outcome_data["response_rates"]["total_actions"]
        positive = outcome_data["response_rates"]["positive_outcomes"]

        # Coaching patterns for strategic insights
        patterns = await self._coaching_extractor.extract_patterns(
            tenant_id, days=days
        )
        strategic_insights = [p.description for p in patterns[:3]]

        # Estimated time saved: ~5 minutes per automated action
        est_time_saved = total * (5.0 / 60.0)  # hours

        result = {
            "role": "executive",
            "period_days": days,
            "roi_metrics": {
                "total_actions": total,
                "positive_outcomes": positive,
                "estimated_time_saved_hours": round(est_time_saved, 1),
                "cost_per_interaction": None,
            },
            "agent_effectiveness": {
                "overall_success_rate": outcome_data["response_rates"][
                    "success_rate"
                ],
                "qualification_completion_rate": 0.0,
                "escalation_rate": (
                    outcome_data.get("escalation_count", 0) / max(total, 1)
                ),
            },
            "engagement_trends": {
                "daily": outcome_data.get("daily_activity", []),
                "trend_direction": self._compute_trend(
                    outcome_data.get("daily_activity", [])
                ),
            },
            "strategic_insights": strategic_insights,
            "generated_at": now.isoformat(),
        }

        await self._set_cached(cache_key, result)
        return result

    # -- Internal helpers ---------------------------------------------------------

    async def _get_outcome_metrics(
        self, tenant_id: str, cutoff: datetime
    ) -> dict:
        """Compute outcome metrics from database for the period.

        Args:
            tenant_id: Tenant UUID string.
            cutoff: Datetime cutoff for period start.

        Returns:
            Dict with response_rates, deal_impact, by_action_type,
            daily_activity, escalation_count.
        """
        import uuid as uuid_mod

        async for session in self._session_factory():
            stmt = select(OutcomeRecordModel).where(
                OutcomeRecordModel.tenant_id == uuid_mod.UUID(tenant_id),
                OutcomeRecordModel.created_at >= cutoff,
            )
            result = await session.execute(stmt)
            outcomes = result.scalars().all()

            total = len(outcomes)
            positive = sum(
                1 for o in outcomes
                if o.outcome_status == OutcomeStatus.POSITIVE.value
            )
            negative = sum(
                1 for o in outcomes
                if o.outcome_status == OutcomeStatus.NEGATIVE.value
            )
            pending = sum(
                1 for o in outcomes
                if o.outcome_status == OutcomeStatus.PENDING.value
            )
            resolved_total = positive + negative
            success_rate = positive / resolved_total if resolved_total > 0 else 0.0

            # Deal impact
            deal_outcomes = [
                o for o in outcomes if o.outcome_type == "deal_progression"
            ]
            deals_progressed = sum(
                1 for o in deal_outcomes
                if o.outcome_status == OutcomeStatus.POSITIVE.value
            )
            deals_stalled = sum(
                1 for o in deal_outcomes
                if o.outcome_status == OutcomeStatus.NEGATIVE.value
            )

            # Escalation count
            escalation_count = sum(
                1 for o in outcomes if o.outcome_type == "escalation_result"
            )

            # By action type
            action_groups: dict[str, dict] = defaultdict(
                lambda: {"positive": 0, "total": 0}
            )
            for o in outcomes:
                if o.outcome_status != OutcomeStatus.PENDING.value:
                    action_groups[o.action_type]["total"] += 1
                    if o.outcome_status == OutcomeStatus.POSITIVE.value:
                        action_groups[o.action_type]["positive"] += 1

            by_action_type = [
                {
                    "action_type": at,
                    "success_rate": round(
                        stats["positive"] / stats["total"], 4
                    ) if stats["total"] > 0 else 0.0,
                    "volume": stats["total"],
                }
                for at, stats in action_groups.items()
            ]

            # Daily activity
            daily: dict[str, dict] = defaultdict(
                lambda: {"actions": 0, "positive": 0}
            )
            for o in outcomes:
                if o.created_at:
                    day_key = o.created_at.strftime("%Y-%m-%d")
                    daily[day_key]["actions"] += 1
                    if o.outcome_status == OutcomeStatus.POSITIVE.value:
                        daily[day_key]["positive"] += 1

            daily_activity = [
                {
                    "date": k,
                    "actions": v["actions"],
                    "positive": v.get("positive", 0),
                    "success_rate": round(
                        v["positive"] / v["actions"], 4
                    ) if v["actions"] > 0 else 0.0,
                }
                for k, v in sorted(daily.items())
            ]

            return {
                "response_rates": {
                    "total_actions": total,
                    "positive_outcomes": positive,
                    "negative_outcomes": negative,
                    "pending_outcomes": pending,
                    "success_rate": round(success_rate, 4),
                },
                "deal_impact": {
                    "deals_progressed": deals_progressed,
                    "deals_stalled": deals_stalled,
                    "deals_closed_won": 0,
                    "stage_advancement_rate": round(
                        deals_progressed / max(len(deal_outcomes), 1), 4
                    ),
                },
                "by_action_type": by_action_type,
                "daily_activity": daily_activity,
                "escalation_count": escalation_count,
            }

        # Fallback for empty session
        return {  # pragma: no cover
            "response_rates": {
                "total_actions": 0,
                "positive_outcomes": 0,
                "negative_outcomes": 0,
                "pending_outcomes": 0,
                "success_rate": 0.0,
            },
            "deal_impact": {
                "deals_progressed": 0,
                "deals_stalled": 0,
                "deals_closed_won": 0,
                "stage_advancement_rate": 0.0,
            },
            "by_action_type": [],
            "daily_activity": [],
            "escalation_count": 0,
        }

    async def _get_calibration_summary(self, tenant_id: str) -> dict:
        """Get calibration summary across all action types.

        Args:
            tenant_id: Tenant UUID string.

        Returns:
            Dict with action_types list and overall_brier.
        """
        try:
            action_types = await self._calibration_engine.get_all_action_types(
                tenant_id
            )
        except Exception:
            action_types = []

        action_type_data = []
        brier_scores = []

        for at in action_types:
            try:
                curve = await self._calibration_engine.get_calibration_curve(
                    tenant_id, at
                )
                is_calibrated = curve.brier_score < 0.15
                direction = "calibrated" if is_calibrated else "needs_adjustment"
                action_type_data.append({
                    "action_type": at,
                    "brier_score": curve.brier_score,
                    "is_calibrated": is_calibrated,
                    "direction": direction,
                })
                brier_scores.append(curve.brier_score)
            except Exception:
                logger.debug(
                    "analytics.calibration_curve_failed", action_type=at
                )

        overall_brier = (
            sum(brier_scores) / len(brier_scores) if brier_scores else 0.25
        )

        return {
            "action_types": action_type_data,
            "overall_brier": round(overall_brier, 6),
            "by_action_type": action_type_data,
        }

    @staticmethod
    def _compute_trend(daily_data: list[dict]) -> str:
        """Determine trend direction from daily activity data.

        Compares the second half average to the first half average.

        Args:
            daily_data: List of dicts with date and activity counts.

        Returns:
            "improving", "stable", or "declining".
        """
        if len(daily_data) < 2:
            return "stable"

        mid = len(daily_data) // 2
        first_half = daily_data[:mid]
        second_half = daily_data[mid:]

        def _avg_metric(data: list[dict]) -> float:
            if not data:
                return 0.0
            # Use 'positive' if available, else 'count'
            values = []
            for d in data:
                if "positive" in d:
                    values.append(d["positive"])
                elif "count" in d:
                    values.append(d["count"])
                elif "actions" in d:
                    values.append(d["actions"])
                else:
                    values.append(0)
            return sum(values) / len(values) if values else 0.0

        first_avg = _avg_metric(first_half)
        second_avg = _avg_metric(second_half)

        if first_avg == 0:
            return "stable" if second_avg == 0 else "improving"

        change = (second_avg - first_avg) / first_avg

        if change > 0.1:
            return "improving"
        elif change < -0.1:
            return "declining"
        return "stable"

    async def _get_cached(self, cache_key: str) -> dict | None:
        """Try Redis cache first. Returns None on miss or if Redis unavailable."""
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(cache_key)
            if raw is not None:
                return json.loads(raw)
        except Exception:
            logger.debug("analytics.cache_miss", key=cache_key)
        return None

    async def _set_cached(
        self, cache_key: str, data: dict, ttl: int | None = None
    ) -> None:
        """Cache result in Redis with TTL. Silently fails if Redis unavailable."""
        if self._redis is None:
            return
        try:
            await self._redis.set(
                cache_key, json.dumps(data, default=str), ex=ttl or self.CACHE_TTL
            )
        except Exception:
            logger.debug("analytics.cache_set_failed", key=cache_key)
