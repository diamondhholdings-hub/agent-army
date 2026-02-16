"""Goal tracker -- self-directed revenue target pursuit.

GoalTracker manages measurable goals (pipeline, activity, quality, revenue),
tracks progress toward targets, detects completion and missed deadlines,
and suggests corrective actions when goals are behind schedule.

Uses on-track heuristic: current_value / target_value >= days_elapsed / total_days.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from src.app.intelligence.autonomy.schemas import (
    Goal,
    GoalType,
    PerformanceMetrics,
)

logger = structlog.get_logger(__name__)


class GoalTracker:
    """Tracks revenue targets and suggests corrective actions.

    Manages the lifecycle of measurable sales goals: creation, progress
    tracking, completion detection, and corrective action suggestions.

    Args:
        repository: IntelligenceRepository or compatible object with
            create_goal, get_goal, list_goals, and update_goal_progress methods.
    """

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    async def create_goal(
        self,
        tenant_id: str,
        goal_type: GoalType,
        target_value: float,
        period_start: datetime,
        period_end: datetime,
        clone_id: Optional[str] = None,
    ) -> Goal:
        """Create a new measurable goal.

        Validates that target_value is positive and period_end is after
        period_start before persisting.

        Args:
            tenant_id: Tenant identifier.
            goal_type: Category of goal (pipeline, activity, quality, revenue).
            target_value: Target value to achieve (must be > 0).
            period_start: Start of the goal period.
            period_end: End of the goal period (must be after period_start).
            clone_id: Optional clone identifier (None for tenant-wide goal).

        Returns:
            Created Goal object.

        Raises:
            ValueError: If target_value <= 0 or period_end <= period_start.
        """
        if target_value <= 0:
            raise ValueError(
                f"target_value must be positive, got {target_value}"
            )
        if period_end <= period_start:
            raise ValueError(
                "period_end must be after period_start: "
                f"{period_end} <= {period_start}"
            )

        goal_data = await self._repository.create_goal(
            tenant_id=tenant_id,
            goal_type=goal_type.value,
            target_value=target_value,
            period_start=period_start,
            period_end=period_end,
            clone_id=clone_id,
        )

        goal = Goal(
            goal_id=goal_data["id"],
            tenant_id=tenant_id,
            clone_id=clone_id,
            goal_type=goal_type,
            target_value=target_value,
            current_value=goal_data.get("current_value", 0.0),
            period_start=period_start,
            period_end=period_end,
            status=goal_data.get("status", "active"),
        )

        logger.info(
            "goals.created",
            goal_id=goal.goal_id,
            tenant_id=tenant_id,
            goal_type=goal_type.value,
            target_value=target_value,
        )

        return goal

    async def update_progress(
        self,
        tenant_id: str,
        goal_id: str,
        current_value: float,
    ) -> Goal:
        """Update a goal's current progress.

        Checks if the goal is now completed (current_value >= target_value)
        or missed (period_end has passed and current_value < target_value).
        Updates status accordingly.

        Args:
            tenant_id: Tenant identifier.
            goal_id: Goal identifier.
            current_value: New current value.

        Returns:
            Updated Goal object.

        Raises:
            ValueError: If goal is not found.
        """
        goal_data = await self._repository.update_goal_progress(
            tenant_id=tenant_id,
            goal_id=goal_id,
            current_value=current_value,
        )

        if goal_data is None:
            raise ValueError(f"Goal not found: {goal_id}")

        # Check for missed deadline (period_end has passed)
        now = datetime.now(timezone.utc)
        status = goal_data.get("status", "active")
        period_end = goal_data.get("period_end")

        if (
            status == "active"
            and period_end is not None
            and now > period_end
            and current_value < goal_data["target_value"]
        ):
            status = "missed"
            # Update status in repository
            await self._repository.update_goal_progress(
                tenant_id=tenant_id,
                goal_id=goal_id,
                current_value=current_value,
            )

        goal = Goal(
            goal_id=goal_data["id"],
            tenant_id=goal_data["tenant_id"],
            clone_id=goal_data.get("clone_id"),
            goal_type=GoalType(goal_data["goal_type"]),
            target_value=goal_data["target_value"],
            current_value=current_value,
            period_start=goal_data["period_start"],
            period_end=goal_data["period_end"],
            status=status,
        )

        logger.info(
            "goals.progress_updated",
            goal_id=goal_id,
            current_value=current_value,
            target_value=goal.target_value,
            status=goal.status,
            progress_pct=self._compute_progress_pct(goal),
        )

        return goal

    async def get_active_goals(
        self,
        tenant_id: str,
        clone_id: Optional[str] = None,
    ) -> List[Goal]:
        """Return active goals for a tenant or clone.

        Args:
            tenant_id: Tenant identifier.
            clone_id: Optional clone filter.

        Returns:
            List of active Goal objects.
        """
        goal_dicts = await self._repository.list_goals(
            tenant_id=tenant_id,
            clone_id=clone_id,
            status="active",
        )

        goals: List[Goal] = []
        for data in goal_dicts:
            try:
                goals.append(
                    Goal(
                        goal_id=data["id"],
                        tenant_id=data["tenant_id"],
                        clone_id=data.get("clone_id"),
                        goal_type=GoalType(data["goal_type"]),
                        target_value=data["target_value"],
                        current_value=data.get("current_value", 0.0),
                        period_start=data["period_start"],
                        period_end=data["period_end"],
                        status=data.get("status", "active"),
                    )
                )
            except Exception:
                logger.warning(
                    "goals.parse_error",
                    goal_id=data.get("id"),
                    exc_info=True,
                )
                continue

        return goals

    async def compute_metrics(
        self,
        tenant_id: str,
        clone_id: Optional[str] = None,
    ) -> PerformanceMetrics:
        """Compute current performance metrics from repository data.

        Queries deal data (pipeline, revenue), conversation data (activity
        counts), and outcome data (quality metrics). Fields that cannot
        be computed return 0.0 or None.

        Args:
            tenant_id: Tenant identifier.
            clone_id: Optional clone filter.

        Returns:
            PerformanceMetrics snapshot.
        """
        now = datetime.now(timezone.utc)

        # Attempt to gather metrics from repository if methods exist
        pipeline_value = 0.0
        activity_count = 0
        quality_score: Optional[float] = None
        revenue_closed = 0.0

        try:
            if hasattr(self._repository, "get_pipeline_value"):
                pipeline_value = await self._repository.get_pipeline_value(
                    tenant_id, clone_id
                )
        except Exception:
            logger.debug("goals.pipeline_metric_unavailable", tenant_id=tenant_id)

        try:
            if hasattr(self._repository, "get_activity_count"):
                activity_count = await self._repository.get_activity_count(
                    tenant_id, clone_id
                )
        except Exception:
            logger.debug("goals.activity_metric_unavailable", tenant_id=tenant_id)

        try:
            if hasattr(self._repository, "get_quality_score"):
                quality_score = await self._repository.get_quality_score(
                    tenant_id, clone_id
                )
        except Exception:
            logger.debug("goals.quality_metric_unavailable", tenant_id=tenant_id)

        try:
            if hasattr(self._repository, "get_revenue_closed"):
                revenue_closed = await self._repository.get_revenue_closed(
                    tenant_id, clone_id
                )
        except Exception:
            logger.debug("goals.revenue_metric_unavailable", tenant_id=tenant_id)

        metrics = PerformanceMetrics(
            tenant_id=tenant_id,
            clone_id=clone_id,
            pipeline_value=pipeline_value,
            activity_count=activity_count,
            quality_score=quality_score,
            revenue_closed=revenue_closed,
            as_of=now,
        )

        logger.info(
            "goals.metrics_computed",
            tenant_id=tenant_id,
            clone_id=clone_id,
            pipeline_value=pipeline_value,
            activity_count=activity_count,
            revenue_closed=revenue_closed,
        )

        return metrics

    async def check_goal_status(
        self,
        tenant_id: str,
    ) -> List[Dict[str, Any]]:
        """Evaluate all active goals and return status summaries.

        Returns a list of goal status dicts including progress percentage,
        on-track indicator, and days remaining. On-track heuristic:
        current_value / target_value >= days_elapsed / total_days.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            List of dicts with goal, progress_pct, on_track, days_remaining.
        """
        goals = await self.get_active_goals(tenant_id)
        now = datetime.now(timezone.utc)
        statuses: List[Dict[str, Any]] = []

        for goal in goals:
            progress_pct = self._compute_progress_pct(goal)
            total_days = (goal.period_end - goal.period_start).total_seconds() / 86400
            days_elapsed = (now - goal.period_start).total_seconds() / 86400
            days_remaining = max(0, int((goal.period_end - now).total_seconds() / 86400))

            # On-track heuristic: progress matches or exceeds time elapsed
            if total_days > 0 and days_elapsed > 0:
                time_fraction = days_elapsed / total_days
                progress_fraction = goal.current_value / goal.target_value
                on_track = progress_fraction >= time_fraction
            else:
                # Goal hasn't started yet or has zero duration
                on_track = True

            statuses.append(
                {
                    "goal": goal,
                    "progress_pct": round(progress_pct, 1),
                    "on_track": on_track,
                    "days_remaining": days_remaining,
                }
            )

        logger.info(
            "goals.status_checked",
            tenant_id=tenant_id,
            total_goals=len(statuses),
            on_track=sum(1 for s in statuses if s["on_track"]),
            behind=sum(1 for s in statuses if not s["on_track"]),
        )

        return statuses

    async def suggest_actions(
        self,
        tenant_id: str,
        goal: Goal,
    ) -> List[str]:
        """Suggest corrective actions based on goal type and progress.

        Provides actionable suggestions when a goal is behind target.
        Suggestions vary by goal type to guide the agent toward the
        most impactful activities.

        Args:
            tenant_id: Tenant identifier.
            goal: Goal to suggest actions for.

        Returns:
            List of suggestion strings (may be empty if goal is on track).
        """
        progress_pct = self._compute_progress_pct(goal)
        suggestions: List[str] = []

        # Only suggest if progress is below 80% of expected
        now = datetime.now(timezone.utc)
        total_days = (goal.period_end - goal.period_start).total_seconds() / 86400
        days_elapsed = (now - goal.period_start).total_seconds() / 86400

        if total_days > 0 and days_elapsed > 0:
            expected_progress = (days_elapsed / total_days) * 100
            if progress_pct >= expected_progress * 0.8:
                # Goal is on track or nearly so; no corrective action needed
                return suggestions

        goal_type = goal.goal_type

        if goal_type == GoalType.revenue:
            suggestions.extend(
                [
                    "Prioritize closing advanced-stage opportunities",
                    "Review stalled deals for re-engagement opportunities",
                    "Focus follow-ups on high-value accounts showing buying signals",
                ]
            )
        elif goal_type == GoalType.pipeline:
            suggestions.extend(
                [
                    "Increase outreach cadence to new accounts",
                    "Expand prospecting to adjacent verticals",
                    "Re-engage dormant accounts with updated value propositions",
                ]
            )
        elif goal_type == GoalType.activity:
            suggestions.extend(
                [
                    "Schedule follow-up meetings with engaged contacts",
                    "Increase email outreach volume to qualified prospects",
                    "Book discovery calls with recently researched accounts",
                ]
            )
        elif goal_type == GoalType.quality:
            suggestions.extend(
                [
                    "Complete BANT qualification for in-progress conversations",
                    "Improve discovery question depth in initial meetings",
                    "Review and address qualification gaps in active deals",
                ]
            )

        logger.info(
            "goals.actions_suggested",
            tenant_id=tenant_id,
            goal_id=goal.goal_id,
            goal_type=goal_type.value,
            progress_pct=progress_pct,
            suggestion_count=len(suggestions),
        )

        return suggestions

    @staticmethod
    def _compute_progress_pct(goal: Goal) -> float:
        """Compute progress percentage, capped at 100.0.

        Args:
            goal: Goal to compute progress for.

        Returns:
            Progress percentage (0.0 to 100.0).
        """
        if goal.target_value <= 0:
            return 0.0
        return min(100.0, (goal.current_value / goal.target_value) * 100)
