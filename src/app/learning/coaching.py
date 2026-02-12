"""CoachingPatternExtractor for identifying training insights from outcomes.

Extracts statistical correlations between agent action attributes and
outcomes to provide actionable sales training insights. Starts with
statistical patterns (RESEARCH.md recommendation), not LLM-based analysis.

Success Criterion 5: "turning AI insights into human coaching."

Correlations include:
- Action type effectiveness (which actions yield best outcomes)
- Escalation patterns (which triggers led to best results)
- Improvement areas (low-performing actions needing attention)

Uses the session_factory callable pattern from ConversationStateRepository
for testable async database access with tenant isolation.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.learning.models import FeedbackEntryModel, OutcomeRecordModel
from src.app.learning.schemas import CoachingPattern, OutcomeStatus

logger = structlog.get_logger(__name__)


class CoachingPatternExtractor:
    """Identifies coaching patterns from outcome and feedback data.

    Extracts statistical correlations between agent action attributes
    and outcomes to provide actionable sales training insights.

    Starts with statistical patterns (RESEARCH.md recommendation),
    not LLM-based analysis.
    """

    MIN_SAMPLES = 5  # Minimum samples for a pattern to be considered

    def __init__(
        self,
        session_factory: Callable[..., AsyncGenerator[AsyncSession, None]],
    ) -> None:
        """Accept session_factory callable."""
        self._session_factory = session_factory

    async def extract_patterns(
        self, tenant_id: str, days: int = 90
    ) -> list[CoachingPattern]:
        """Extract coaching patterns from recent outcome data.

        Queries resolved outcomes and feedback, computes correlations,
        and returns ranked patterns by statistical significance.

        Pattern extraction pipeline:
        1. Load resolved outcomes for the period
        2. Group by dimensions (action_type, outcome_type)
        3. Compute success rates per group
        4. Compare groups to identify significant differences
        5. Format as CoachingPattern objects with human-readable insights

        Args:
            tenant_id: Tenant UUID string.
            days: Number of days to look back (default 90).

        Returns:
            List of CoachingPattern sorted by confidence descending.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        async for session in self._session_factory():
            # Load resolved outcomes
            stmt = select(OutcomeRecordModel).where(
                OutcomeRecordModel.tenant_id == uuid.UUID(tenant_id),
                OutcomeRecordModel.outcome_status != OutcomeStatus.PENDING.value,
                OutcomeRecordModel.created_at >= cutoff,
            )
            result = await session.execute(stmt)
            outcomes = result.scalars().all()

            if not outcomes:
                return []

            patterns: list[CoachingPattern] = []

            # Pattern 1: Action type effectiveness
            action_groups: dict[str, list] = defaultdict(list)
            for o in outcomes:
                is_positive = o.outcome_status == OutcomeStatus.POSITIVE.value
                action_groups[o.action_type].append(is_positive)

            overall_positive = sum(
                1 for o in outcomes if o.outcome_status == OutcomeStatus.POSITIVE.value
            )
            overall_rate = overall_positive / len(outcomes) if outcomes else 0.0

            for action_type, results_list in action_groups.items():
                if len(results_list) < self.MIN_SAMPLES:
                    continue

                success_rate = sum(results_list) / len(results_list)
                diff = success_rate - overall_rate

                if abs(diff) > 0.05:  # >5% difference from average
                    if diff > 0:
                        desc = (
                            f"'{action_type}' actions have a {success_rate:.0%} success rate, "
                            f"which is {diff:.0%} above the average of {overall_rate:.0%}."
                        )
                        recommendation = (
                            f"Consider using '{action_type}' more frequently in similar contexts."
                        )
                    else:
                        desc = (
                            f"'{action_type}' actions have a {success_rate:.0%} success rate, "
                            f"which is {abs(diff):.0%} below the average of {overall_rate:.0%}."
                        )
                        recommendation = (
                            f"Review '{action_type}' approach -- consider alternative strategies "
                            f"or additional preparation before these actions."
                        )

                    patterns.append(
                        CoachingPattern(
                            pattern_type="action_effectiveness",
                            description=desc,
                            confidence=min(len(results_list) / 50.0, 1.0),
                            sample_size=len(results_list),
                            supporting_data={
                                "action_type": action_type,
                                "success_rate": round(success_rate, 4),
                                "overall_rate": round(overall_rate, 4),
                                "difference": round(diff, 4),
                            },
                            recommendation=recommendation,
                        )
                    )

            # Pattern 2: Outcome type analysis
            outcome_type_groups: dict[str, list] = defaultdict(list)
            for o in outcomes:
                is_positive = o.outcome_status == OutcomeStatus.POSITIVE.value
                outcome_type_groups[o.outcome_type].append(is_positive)

            for outcome_type, results_list in outcome_type_groups.items():
                if len(results_list) < self.MIN_SAMPLES:
                    continue

                success_rate = sum(results_list) / len(results_list)

                if success_rate < 0.3:
                    patterns.append(
                        CoachingPattern(
                            pattern_type="stage_insight",
                            description=(
                                f"Low success rate ({success_rate:.0%}) for "
                                f"'{outcome_type}' outcomes. This area needs attention."
                            ),
                            confidence=min(len(results_list) / 50.0, 1.0),
                            sample_size=len(results_list),
                            supporting_data={
                                "outcome_type": outcome_type,
                                "success_rate": round(success_rate, 4),
                                "total": len(results_list),
                                "positive": sum(results_list),
                            },
                            recommendation=(
                                f"Focus on improving '{outcome_type}' outcomes through "
                                f"better preparation and follow-up strategies."
                            ),
                        )
                    )

            # Sort by confidence descending
            patterns.sort(key=lambda p: p.confidence, reverse=True)

            return patterns

        return []  # pragma: no cover

    async def get_escalation_patterns(
        self, tenant_id: str, days: int = 90
    ) -> list[CoachingPattern]:
        """Identify patterns in escalation outcomes.

        Analyzes: which escalation triggers led to best outcomes?
        Which deal stages have highest escalation-to-resolution success?

        Args:
            tenant_id: Tenant UUID string.
            days: Number of days to look back (default 90).

        Returns:
            List of CoachingPattern for escalation insights.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        async for session in self._session_factory():
            stmt = select(OutcomeRecordModel).where(
                OutcomeRecordModel.tenant_id == uuid.UUID(tenant_id),
                OutcomeRecordModel.outcome_type == "escalation_result",
                OutcomeRecordModel.outcome_status != OutcomeStatus.PENDING.value,
                OutcomeRecordModel.created_at >= cutoff,
            )
            result = await session.execute(stmt)
            outcomes = result.scalars().all()

            if len(outcomes) < self.MIN_SAMPLES:
                return []

            patterns: list[CoachingPattern] = []

            # Group by escalation trigger from metadata
            trigger_groups: dict[str, list] = defaultdict(list)
            for o in outcomes:
                trigger = o.metadata_json.get("escalation_trigger", "unknown")
                is_positive = o.outcome_status == OutcomeStatus.POSITIVE.value
                trigger_groups[trigger].append(is_positive)

            for trigger, results_list in trigger_groups.items():
                if len(results_list) < self.MIN_SAMPLES:
                    continue

                success_rate = sum(results_list) / len(results_list)

                patterns.append(
                    CoachingPattern(
                        pattern_type="escalation_pattern",
                        description=(
                            f"Escalations triggered by '{trigger}' have a "
                            f"{success_rate:.0%} resolution rate "
                            f"({sum(results_list)}/{len(results_list)})."
                        ),
                        confidence=min(len(results_list) / 30.0, 1.0),
                        sample_size=len(results_list),
                        supporting_data={
                            "trigger": trigger,
                            "success_rate": round(success_rate, 4),
                            "total": len(results_list),
                            "positive": sum(results_list),
                        },
                        recommendation=(
                            f"{'Prioritize' if success_rate > 0.5 else 'Reconsider'} "
                            f"escalations triggered by '{trigger}' -- "
                            f"{'they resolve well' if success_rate > 0.5 else 'success rate is low'}."
                        ),
                    )
                )

            patterns.sort(key=lambda p: p.confidence, reverse=True)
            return patterns

        return []  # pragma: no cover

    async def get_top_performing_actions(
        self, tenant_id: str, days: int = 90, top_k: int = 5
    ) -> list[dict]:
        """Identify the most effective action types by success rate.

        Returns top_k action types with highest positive outcome ratio,
        filtered to those with MIN_SAMPLES threshold.

        Args:
            tenant_id: Tenant UUID string.
            days: Number of days to look back (default 90).
            top_k: Number of top actions to return (default 5).

        Returns:
            List of dicts with action_type, success_rate, total_count, positive_count.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        async for session in self._session_factory():
            stmt = select(OutcomeRecordModel).where(
                OutcomeRecordModel.tenant_id == uuid.UUID(tenant_id),
                OutcomeRecordModel.outcome_status != OutcomeStatus.PENDING.value,
                OutcomeRecordModel.created_at >= cutoff,
            )
            result = await session.execute(stmt)
            outcomes = result.scalars().all()

            # Group by action type
            action_stats: dict[str, dict] = defaultdict(
                lambda: {"positive": 0, "total": 0}
            )
            for o in outcomes:
                action_stats[o.action_type]["total"] += 1
                if o.outcome_status == OutcomeStatus.POSITIVE.value:
                    action_stats[o.action_type]["positive"] += 1

            # Filter and compute success rates
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

            # Sort by success rate descending
            ranked.sort(key=lambda x: x["success_rate"], reverse=True)
            return ranked[:top_k]

        return []  # pragma: no cover

    async def get_improvement_areas(
        self, tenant_id: str, days: int = 90
    ) -> list[dict]:
        """Identify areas where the agent underperforms.

        Finds action types or scenarios with low success rates,
        high escalation rates, or poor human feedback scores.
        Used for targeted training recommendations.

        Args:
            tenant_id: Tenant UUID string.
            days: Number of days to look back (default 90).

        Returns:
            List of dicts with area_type, description, success_rate, recommendation.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        areas: list[dict] = []

        async for session in self._session_factory():
            # Find low-performing action types from outcomes
            stmt = select(OutcomeRecordModel).where(
                OutcomeRecordModel.tenant_id == uuid.UUID(tenant_id),
                OutcomeRecordModel.outcome_status != OutcomeStatus.PENDING.value,
                OutcomeRecordModel.created_at >= cutoff,
            )
            result = await session.execute(stmt)
            outcomes = result.scalars().all()

            action_stats: dict[str, dict] = defaultdict(
                lambda: {"positive": 0, "negative": 0, "total": 0}
            )
            for o in outcomes:
                action_stats[o.action_type]["total"] += 1
                if o.outcome_status == OutcomeStatus.POSITIVE.value:
                    action_stats[o.action_type]["positive"] += 1
                elif o.outcome_status == OutcomeStatus.NEGATIVE.value:
                    action_stats[o.action_type]["negative"] += 1

            for action_type, stats in action_stats.items():
                if stats["total"] < self.MIN_SAMPLES:
                    continue
                success_rate = stats["positive"] / stats["total"]
                if success_rate < 0.4:  # Below 40% success rate
                    areas.append({
                        "area_type": "low_success_rate",
                        "action_type": action_type,
                        "description": (
                            f"'{action_type}' has only {success_rate:.0%} success rate "
                            f"({stats['positive']}/{stats['total']})"
                        ),
                        "success_rate": round(success_rate, 4),
                        "total_count": stats["total"],
                        "recommendation": (
                            f"Improve '{action_type}' strategy: review failed cases, "
                            f"adjust timing or approach."
                        ),
                    })

            # Find areas with poor feedback scores
            fb_stmt = select(FeedbackEntryModel).where(
                FeedbackEntryModel.tenant_id == uuid.UUID(tenant_id),
                FeedbackEntryModel.created_at >= cutoff,
            )
            fb_result = await session.execute(fb_stmt)
            feedbacks = fb_result.scalars().all()

            target_ratings: dict[str, list] = defaultdict(list)
            for fb in feedbacks:
                target_ratings[fb.target_type].append(fb.rating)

            for target_type, ratings in target_ratings.items():
                if len(ratings) < self.MIN_SAMPLES:
                    continue
                avg_rating = sum(ratings) / len(ratings)
                if avg_rating < 0.0:  # Negative average for inline (-1/0/1)
                    areas.append({
                        "area_type": "poor_feedback",
                        "target_type": target_type,
                        "description": (
                            f"'{target_type}' feedback averages {avg_rating:.2f} "
                            f"(negative sentiment, {len(ratings)} reviews)"
                        ),
                        "avg_rating": round(avg_rating, 4),
                        "total_reviews": len(ratings),
                        "recommendation": (
                            f"Review agent '{target_type}' quality -- human reviewers "
                            f"are consistently giving negative feedback."
                        ),
                    })

            return areas

        return []  # pragma: no cover
