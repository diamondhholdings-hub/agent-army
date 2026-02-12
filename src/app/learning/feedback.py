"""FeedbackCollector service for recording and querying human feedback.

Collects inline reactions (thumbs up/down from Slack/Gmail) and detailed
dashboard reviews (1-5 scale from web dashboard). Links feedback to outcome
records for calibration integration. Provides summary metrics and fatigue
detection to maintain feedback quality over time.

Uses the session_factory callable pattern from ConversationStateRepository
for testable async database access with tenant isolation.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.learning.models import FeedbackEntryModel
from src.app.learning.schemas import FeedbackEntry, FeedbackSource, FeedbackTarget

logger = structlog.get_logger(__name__)


class FeedbackCollector:
    """Collects and manages human feedback on agent behavior.

    Supports both inline reactions (quick thumbs up/down) and detailed
    dashboard reviews. Links feedback to outcome records for calibration.
    """

    # Valid rating ranges by source
    INLINE_RATING_RANGE = (-1, 1)
    DASHBOARD_RATING_RANGE = (1, 5)

    # Valid target types and sources (from enums)
    VALID_TARGET_TYPES = {t.value for t in FeedbackTarget}
    VALID_SOURCES = {s.value for s in FeedbackSource}

    def __init__(
        self,
        session_factory: Callable[..., AsyncGenerator[AsyncSession, None]],
    ) -> None:
        """Accept session_factory callable (same pattern as ConversationStateRepository)."""
        self._session_factory = session_factory

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
        """Record feedback and optionally link to an outcome record.

        Validates:
        - rating range: -1 to 1 for inline source, 1 to 5 for dashboard source
        - target_type is one of MESSAGE, DECISION, CONVERSATION
        - source is one of INLINE, DASHBOARD

        Creates FeedbackEntryModel in database. If outcome_record_id is provided,
        also triggers calibration update via the outcome resolution (human_label signal).

        Args:
            tenant_id: Tenant UUID string.
            conversation_state_id: Conversation state UUID string.
            target_type: What the feedback is about ("message", "decision", "conversation").
            target_id: ID of the specific target.
            source: Where the feedback came from ("inline", "dashboard").
            rating: Rating value (-1/0/1 for inline, 1-5 for dashboard).
            reviewer_id: UUID string of the reviewer.
            reviewer_role: Role of the reviewer ("rep", "manager", "executive").
            outcome_record_id: Optional linked outcome record UUID string.
            comment: Optional text comment.
            metadata: Optional metadata dict.

        Returns:
            The created FeedbackEntry schema.

        Raises:
            ValueError: If validation fails for rating, target_type, or source.
        """
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

        feedback_id = uuid.uuid4()
        meta = metadata or {}

        async for session in self._session_factory():
            model = FeedbackEntryModel(
                id=feedback_id,
                tenant_id=uuid.UUID(tenant_id),
                conversation_state_id=uuid.UUID(conversation_state_id),
                outcome_record_id=uuid.UUID(outcome_record_id) if outcome_record_id else None,
                target_type=target_type,
                target_id=target_id,
                source=source,
                rating=rating,
                comment=comment,
                reviewer_id=uuid.UUID(reviewer_id),
                reviewer_role=reviewer_role,
                metadata_json=meta,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)

            logger.info(
                "feedback.recorded",
                feedback_id=str(feedback_id),
                tenant_id=tenant_id,
                target_type=target_type,
                source=source,
                rating=rating,
                reviewer_role=reviewer_role,
            )

            return FeedbackEntry(
                feedback_id=str(model.id),
                tenant_id=str(model.tenant_id),
                outcome_record_id=str(model.outcome_record_id) if model.outcome_record_id else None,
                conversation_state_id=str(model.conversation_state_id),
                target_type=model.target_type,
                target_id=model.target_id,
                source=model.source,
                rating=model.rating,
                comment=model.comment,
                reviewer_id=str(model.reviewer_id),
                reviewer_role=model.reviewer_role,
                metadata_json=model.metadata_json,
                created_at=model.created_at or datetime.now(timezone.utc),
            )

        raise RuntimeError("Session factory yielded no session")  # pragma: no cover

    async def get_feedback_for_conversation(
        self,
        tenant_id: str,
        conversation_state_id: str,
    ) -> list[FeedbackEntry]:
        """Get all feedback entries for a conversation.

        Args:
            tenant_id: Tenant UUID string.
            conversation_state_id: Conversation state UUID string.

        Returns:
            List of FeedbackEntry schemas for the conversation.
        """
        async for session in self._session_factory():
            stmt = select(FeedbackEntryModel).where(
                FeedbackEntryModel.tenant_id == uuid.UUID(tenant_id),
                FeedbackEntryModel.conversation_state_id == uuid.UUID(conversation_state_id),
            )
            result = await session.execute(stmt)
            models = result.scalars().all()

            return [
                FeedbackEntry(
                    feedback_id=str(m.id),
                    tenant_id=str(m.tenant_id),
                    outcome_record_id=str(m.outcome_record_id) if m.outcome_record_id else None,
                    conversation_state_id=str(m.conversation_state_id),
                    target_type=m.target_type,
                    target_id=m.target_id,
                    source=m.source,
                    rating=m.rating,
                    comment=m.comment,
                    reviewer_id=str(m.reviewer_id),
                    reviewer_role=m.reviewer_role,
                    metadata_json=m.metadata_json,
                    created_at=m.created_at or datetime.now(timezone.utc),
                )
                for m in models
            ]

        return []  # pragma: no cover

    async def get_feedback_by_reviewer(
        self,
        tenant_id: str,
        reviewer_id: str,
        limit: int = 50,
    ) -> list[FeedbackEntry]:
        """Get recent feedback from a specific reviewer.

        Args:
            tenant_id: Tenant UUID string.
            reviewer_id: Reviewer UUID string.
            limit: Maximum number of results (default 50).

        Returns:
            List of FeedbackEntry schemas from the reviewer, ordered by newest first.
        """
        async for session in self._session_factory():
            stmt = (
                select(FeedbackEntryModel)
                .where(
                    FeedbackEntryModel.tenant_id == uuid.UUID(tenant_id),
                    FeedbackEntryModel.reviewer_id == uuid.UUID(reviewer_id),
                )
                .order_by(FeedbackEntryModel.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            models = result.scalars().all()

            return [
                FeedbackEntry(
                    feedback_id=str(m.id),
                    tenant_id=str(m.tenant_id),
                    outcome_record_id=str(m.outcome_record_id) if m.outcome_record_id else None,
                    conversation_state_id=str(m.conversation_state_id),
                    target_type=m.target_type,
                    target_id=m.target_id,
                    source=m.source,
                    rating=m.rating,
                    comment=m.comment,
                    reviewer_id=str(m.reviewer_id),
                    reviewer_role=m.reviewer_role,
                    metadata_json=m.metadata_json,
                    created_at=m.created_at or datetime.now(timezone.utc),
                )
                for m in models
            ]

        return []  # pragma: no cover

    async def get_feedback_summary(
        self,
        tenant_id: str,
        days: int = 30,
    ) -> dict:
        """Compute feedback summary metrics for a tenant.

        Args:
            tenant_id: Tenant UUID string.
            days: Number of days to look back (default 30).

        Returns:
            Dict with:
            - total_feedback_count: int
            - average_rating: float
            - rating_distribution: dict[int, int] (rating -> count)
            - by_target_type: dict[str, dict] (target_type -> {count, avg_rating})
            - by_source: dict[str, int] (source -> count)
            - by_reviewer_role: dict[str, dict] (role -> {count, avg_rating})
            - feedback_rate_trend: list[dict] (daily feedback counts for trend)
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        async for session in self._session_factory():
            stmt = select(FeedbackEntryModel).where(
                FeedbackEntryModel.tenant_id == uuid.UUID(tenant_id),
                FeedbackEntryModel.created_at >= cutoff,
            )
            result = await session.execute(stmt)
            models = result.scalars().all()

            if not models:
                return {
                    "total_feedback_count": 0,
                    "average_rating": 0.0,
                    "rating_distribution": {},
                    "by_target_type": {},
                    "by_source": {},
                    "by_reviewer_role": {},
                    "feedback_rate_trend": [],
                }

            # Compute metrics
            total = len(models)
            rating_sum = sum(m.rating for m in models)
            avg_rating = rating_sum / total if total > 0 else 0.0

            # Rating distribution
            rating_dist: dict[int, int] = defaultdict(int)
            for m in models:
                rating_dist[m.rating] += 1

            # By target type
            by_target: dict[str, dict] = defaultdict(lambda: {"count": 0, "rating_sum": 0})
            for m in models:
                by_target[m.target_type]["count"] += 1
                by_target[m.target_type]["rating_sum"] += m.rating
            by_target_result = {
                k: {"count": v["count"], "avg_rating": v["rating_sum"] / v["count"]}
                for k, v in by_target.items()
            }

            # By source
            by_source: dict[str, int] = defaultdict(int)
            for m in models:
                by_source[m.source] += 1

            # By reviewer role
            by_role: dict[str, dict] = defaultdict(lambda: {"count": 0, "rating_sum": 0})
            for m in models:
                by_role[m.reviewer_role]["count"] += 1
                by_role[m.reviewer_role]["rating_sum"] += m.rating
            by_role_result = {
                k: {"count": v["count"], "avg_rating": v["rating_sum"] / v["count"]}
                for k, v in by_role.items()
            }

            # Daily trend
            daily_counts: dict[str, int] = defaultdict(int)
            for m in models:
                if m.created_at:
                    day_key = m.created_at.strftime("%Y-%m-%d")
                    daily_counts[day_key] += 1

            trend = [
                {"date": k, "count": v}
                for k, v in sorted(daily_counts.items())
            ]

            return {
                "total_feedback_count": total,
                "average_rating": round(avg_rating, 2),
                "rating_distribution": dict(rating_dist),
                "by_target_type": by_target_result,
                "by_source": dict(by_source),
                "by_reviewer_role": by_role_result,
                "feedback_rate_trend": trend,
            }

        return {  # pragma: no cover
            "total_feedback_count": 0,
            "average_rating": 0.0,
            "rating_distribution": {},
            "by_target_type": {},
            "by_source": {},
            "by_reviewer_role": {},
            "feedback_rate_trend": [],
        }

    async def get_feedback_rate(
        self,
        tenant_id: str,
        reviewer_id: str,
    ) -> float:
        """Get feedback submission rate for fatigue detection (Pitfall 3).

        Returns feedbacks per day over the last 7 days. Declining rates
        signal feedback fatigue.

        Args:
            tenant_id: Tenant UUID string.
            reviewer_id: Reviewer UUID string.

        Returns:
            Average feedbacks per day over the last 7 days.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        async for session in self._session_factory():
            stmt = select(func.count()).select_from(FeedbackEntryModel).where(
                FeedbackEntryModel.tenant_id == uuid.UUID(tenant_id),
                FeedbackEntryModel.reviewer_id == uuid.UUID(reviewer_id),
                FeedbackEntryModel.created_at >= cutoff,
            )
            result = await session.execute(stmt)
            count = result.scalar() or 0

            return count / 7.0

        return 0.0  # pragma: no cover
