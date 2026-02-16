"""Intelligence repository -- async CRUD for all intelligence entities.

Provides IntelligenceRepository with session_factory callable pattern
(matching DealRepository from Phase 5). Handles serialization between
Pydantic schemas and SQLAlchemy models for clones, insights, goals,
autonomous actions, and alert feedback.

All methods take tenant_id as first argument for tenant-scoped queries.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import func as sa_func
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.intelligence.models import (
    AgentCloneModel,
    AlertFeedbackModel,
    AutonomousActionModel,
    GoalModel,
    InsightModel,
)

logger = structlog.get_logger(__name__)


class IntelligenceRepository:
    """Async CRUD operations for all intelligence entities.

    Uses session_factory callable pattern matching DealRepository.
    All methods take tenant_id as first argument for tenant-scoped queries.

    Args:
        session_factory: Async callable that yields AsyncSession instances.
    """

    def __init__(
        self, session_factory: Callable[..., AsyncGenerator[AsyncSession, None]]
    ) -> None:
        self._session_factory = session_factory

    # ── Clone CRUD ──────────────────────────────────────────────────────────

    async def create_clone(
        self,
        tenant_id: str,
        clone_name: str,
        owner_id: str,
        persona_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new agent clone.

        Args:
            tenant_id: Tenant UUID string.
            clone_name: Display name for the clone.
            owner_id: Sales rep who owns this clone.
            persona_config: Persona configuration dict (stored as JSON).

        Returns:
            Dict with clone data including id, clone_name, owner_id, etc.
        """
        async for session in self._session_factory():
            model = AgentCloneModel(
                tenant_id=uuid.UUID(tenant_id),
                clone_name=clone_name,
                owner_id=owner_id,
                persona_config=persona_config or {},
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            logger.info(
                "intelligence.clone_created",
                clone_id=str(model.id),
                tenant_id=tenant_id,
                clone_name=clone_name,
            )
            return _clone_to_dict(model)

    async def get_clone(
        self, tenant_id: str, clone_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a clone by ID.

        Args:
            tenant_id: Tenant UUID string.
            clone_id: Clone UUID string.

        Returns:
            Dict with clone data if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(AgentCloneModel).where(
                AgentCloneModel.tenant_id == uuid.UUID(tenant_id),
                AgentCloneModel.id == uuid.UUID(clone_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _clone_to_dict(model)

    async def list_clones(
        self, tenant_id: str, active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """List clones for a tenant.

        Args:
            tenant_id: Tenant UUID string.
            active_only: If True, only return active clones.

        Returns:
            List of clone dicts.
        """
        async for session in self._session_factory():
            stmt = select(AgentCloneModel).where(
                AgentCloneModel.tenant_id == uuid.UUID(tenant_id),
            )
            if active_only:
                stmt = stmt.where(AgentCloneModel.active == True)  # noqa: E712
            result = await session.execute(stmt)
            models = result.scalars().all()
            return [_clone_to_dict(m) for m in models]

    async def update_clone(
        self, tenant_id: str, clone_id: str, **updates: Any
    ) -> Optional[Dict[str, Any]]:
        """Update a clone's fields.

        Args:
            tenant_id: Tenant UUID string.
            clone_id: Clone UUID string.
            **updates: Fields to update (clone_name, persona_config, etc.).

        Returns:
            Updated clone dict if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(AgentCloneModel).where(
                AgentCloneModel.tenant_id == uuid.UUID(tenant_id),
                AgentCloneModel.id == uuid.UUID(clone_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None

            for key, value in updates.items():
                if hasattr(model, key):
                    setattr(model, key, value)

            model.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(model)
            logger.info(
                "intelligence.clone_updated",
                clone_id=clone_id,
                updated_fields=list(updates.keys()),
            )
            return _clone_to_dict(model)

    async def deactivate_clone(
        self, tenant_id: str, clone_id: str
    ) -> Optional[Dict[str, Any]]:
        """Soft-delete a clone by setting active=False.

        Args:
            tenant_id: Tenant UUID string.
            clone_id: Clone UUID string.

        Returns:
            Deactivated clone dict if found, None otherwise.
        """
        return await self.update_clone(tenant_id, clone_id, active=False)

    # ── Insight CRUD ────────────────────────────────────────────────────────

    async def create_insight(
        self,
        tenant_id: str,
        account_id: str,
        pattern_type: str,
        pattern_data: Dict[str, Any],
        confidence: float,
        severity: str = "medium",
    ) -> Dict[str, Any]:
        """Create a new insight from a detected pattern.

        Args:
            tenant_id: Tenant UUID string.
            account_id: Account identifier.
            pattern_type: Category of pattern detected.
            pattern_data: Full pattern data as dict (stored as JSON).
            confidence: Detection confidence (0.0-1.0).
            severity: Severity level (low/medium/high/critical).

        Returns:
            Dict with insight data.
        """
        async for session in self._session_factory():
            model = InsightModel(
                tenant_id=uuid.UUID(tenant_id),
                account_id=account_id,
                pattern_type=pattern_type,
                pattern_data=pattern_data,
                confidence=confidence,
                severity=severity,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            logger.info(
                "intelligence.insight_created",
                insight_id=str(model.id),
                tenant_id=tenant_id,
                pattern_type=pattern_type,
                confidence=confidence,
            )
            return _insight_to_dict(model)

    async def get_insight(
        self, tenant_id: str, insight_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get an insight by ID.

        Args:
            tenant_id: Tenant UUID string.
            insight_id: Insight UUID string.

        Returns:
            Dict with insight data if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(InsightModel).where(
                InsightModel.tenant_id == uuid.UUID(tenant_id),
                InsightModel.id == uuid.UUID(insight_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _insight_to_dict(model)

    async def list_insights(
        self,
        tenant_id: str,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List insights for a tenant with optional filters.

        Args:
            tenant_id: Tenant UUID string.
            account_id: Optional account filter.
            status: Optional status filter (pending/acted/dismissed).
            limit: Maximum number of results.

        Returns:
            List of insight dicts ordered by created_at descending.
        """
        async for session in self._session_factory():
            stmt = select(InsightModel).where(
                InsightModel.tenant_id == uuid.UUID(tenant_id),
            )
            if account_id is not None:
                stmt = stmt.where(InsightModel.account_id == account_id)
            if status is not None:
                stmt = stmt.where(InsightModel.status == status)
            stmt = stmt.order_by(InsightModel.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            models = result.scalars().all()
            return [_insight_to_dict(m) for m in models]

    async def update_insight_status(
        self, tenant_id: str, insight_id: str, status: str
    ) -> Optional[Dict[str, Any]]:
        """Update an insight's lifecycle status.

        Args:
            tenant_id: Tenant UUID string.
            insight_id: Insight UUID string.
            status: New status (pending/acted/dismissed).

        Returns:
            Updated insight dict if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(InsightModel).where(
                InsightModel.tenant_id == uuid.UUID(tenant_id),
                InsightModel.id == uuid.UUID(insight_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None

            model.status = status
            if status in ("acted", "dismissed"):
                model.acted_at = datetime.now(timezone.utc)

            await session.commit()
            await session.refresh(model)
            logger.info(
                "intelligence.insight_status_updated",
                insight_id=insight_id,
                new_status=status,
            )
            return _insight_to_dict(model)

    # ── Goal CRUD ───────────────────────────────────────────────────────────

    async def create_goal(
        self,
        tenant_id: str,
        goal_type: str,
        target_value: float,
        period_start: datetime,
        period_end: datetime,
        clone_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new goal.

        Args:
            tenant_id: Tenant UUID string.
            goal_type: Category of goal (pipeline/activity/quality/revenue).
            target_value: Target value to achieve.
            period_start: Start of goal period.
            period_end: End of goal period.
            clone_id: Optional clone UUID (None for tenant-wide goal).

        Returns:
            Dict with goal data.
        """
        async for session in self._session_factory():
            model = GoalModel(
                tenant_id=uuid.UUID(tenant_id),
                clone_id=uuid.UUID(clone_id) if clone_id else None,
                goal_type=goal_type,
                target_value=target_value,
                period_start=period_start,
                period_end=period_end,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            logger.info(
                "intelligence.goal_created",
                goal_id=str(model.id),
                tenant_id=tenant_id,
                goal_type=goal_type,
                target_value=target_value,
            )
            return _goal_to_dict(model)

    async def get_goal(
        self, tenant_id: str, goal_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a goal by ID.

        Args:
            tenant_id: Tenant UUID string.
            goal_id: Goal UUID string.

        Returns:
            Dict with goal data if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(GoalModel).where(
                GoalModel.tenant_id == uuid.UUID(tenant_id),
                GoalModel.id == uuid.UUID(goal_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _goal_to_dict(model)

    async def list_goals(
        self,
        tenant_id: str,
        clone_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List goals for a tenant with optional filters.

        Args:
            tenant_id: Tenant UUID string.
            clone_id: Optional clone filter.
            status: Optional status filter (active/completed/missed).

        Returns:
            List of goal dicts.
        """
        async for session in self._session_factory():
            stmt = select(GoalModel).where(
                GoalModel.tenant_id == uuid.UUID(tenant_id),
            )
            if clone_id is not None:
                stmt = stmt.where(GoalModel.clone_id == uuid.UUID(clone_id))
            if status is not None:
                stmt = stmt.where(GoalModel.status == status)
            result = await session.execute(stmt)
            models = result.scalars().all()
            return [_goal_to_dict(m) for m in models]

    async def update_goal_progress(
        self, tenant_id: str, goal_id: str, current_value: float
    ) -> Optional[Dict[str, Any]]:
        """Update a goal's current progress.

        Args:
            tenant_id: Tenant UUID string.
            goal_id: Goal UUID string.
            current_value: New current value.

        Returns:
            Updated goal dict if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(GoalModel).where(
                GoalModel.tenant_id == uuid.UUID(tenant_id),
                GoalModel.id == uuid.UUID(goal_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None

            model.current_value = current_value
            # Auto-complete if target reached
            if current_value >= model.target_value and model.status == "active":
                model.status = "completed"

            await session.commit()
            await session.refresh(model)
            logger.info(
                "intelligence.goal_progress_updated",
                goal_id=goal_id,
                current_value=current_value,
                target_value=model.target_value,
                status=model.status,
            )
            return _goal_to_dict(model)

    # ── Action Logging ──────────────────────────────────────────────────────

    async def log_autonomous_action(
        self,
        tenant_id: str,
        action_type: str,
        account_id: str,
        action_data: Optional[Dict[str, Any]] = None,
        approval_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Log an autonomous action for audit trail.

        Args:
            tenant_id: Tenant UUID string.
            action_type: Type of action (send_follow_up_email, etc.).
            account_id: Target account identifier.
            action_data: Full action context as dict.
            approval_status: Initial approval status (None/pending/approved/rejected).

        Returns:
            Dict with action data.
        """
        async for session in self._session_factory():
            model = AutonomousActionModel(
                tenant_id=uuid.UUID(tenant_id),
                action_type=action_type,
                account_id=account_id,
                action_data=action_data or {},
                approval_status=approval_status,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            logger.info(
                "intelligence.action_logged",
                action_id=str(model.id),
                tenant_id=tenant_id,
                action_type=action_type,
                approval_status=approval_status,
            )
            return _action_to_dict(model)

    async def get_action(
        self, tenant_id: str, action_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get an autonomous action by ID.

        Args:
            tenant_id: Tenant UUID string.
            action_id: Action UUID string.

        Returns:
            Dict with action data if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(AutonomousActionModel).where(
                AutonomousActionModel.tenant_id == uuid.UUID(tenant_id),
                AutonomousActionModel.id == uuid.UUID(action_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _action_to_dict(model)

    async def update_action_result(
        self,
        tenant_id: str,
        action_id: str,
        execution_result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Update an action's execution result.

        Args:
            tenant_id: Tenant UUID string.
            action_id: Action UUID string.
            execution_result: Result data from action execution.

        Returns:
            Updated action dict if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(AutonomousActionModel).where(
                AutonomousActionModel.tenant_id == uuid.UUID(tenant_id),
                AutonomousActionModel.id == uuid.UUID(action_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None

            model.execution_result = execution_result
            model.executed_at = datetime.now(timezone.utc)

            await session.commit()
            await session.refresh(model)
            logger.info(
                "intelligence.action_result_updated",
                action_id=action_id,
                executed=True,
            )
            return _action_to_dict(model)

    # ── Feedback ────────────────────────────────────────────────────────────

    async def record_feedback(
        self,
        tenant_id: str,
        insight_id: str,
        feedback: str,
        submitted_by: str,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record feedback on an insight's usefulness.

        Args:
            tenant_id: Tenant UUID string.
            insight_id: Insight UUID string.
            feedback: Feedback type (useful/false_alarm).
            submitted_by: User ID of the person submitting feedback.
            comment: Optional comment with additional context.

        Returns:
            Dict with feedback data.
        """
        async for session in self._session_factory():
            model = AlertFeedbackModel(
                tenant_id=uuid.UUID(tenant_id),
                insight_id=uuid.UUID(insight_id),
                feedback=feedback,
                submitted_by=submitted_by,
                comment=comment,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            logger.info(
                "intelligence.feedback_recorded",
                insight_id=insight_id,
                feedback=feedback,
            )
            return _feedback_to_dict(model)

    async def get_feedback_stats(
        self, tenant_id: str
    ) -> Dict[str, int]:
        """Get aggregated feedback statistics for a tenant.

        Args:
            tenant_id: Tenant UUID string.

        Returns:
            Dict with feedback counts: {"useful": N, "false_alarm": N, "total": N}.
        """
        async for session in self._session_factory():
            stmt = (
                select(
                    AlertFeedbackModel.feedback,
                    sa_func.count(AlertFeedbackModel.id).label("count"),
                )
                .where(AlertFeedbackModel.tenant_id == uuid.UUID(tenant_id))
                .group_by(AlertFeedbackModel.feedback)
            )
            result = await session.execute(stmt)
            rows = result.all()

            stats: Dict[str, int] = {"useful": 0, "false_alarm": 0, "total": 0}
            for feedback_type, count in rows:
                stats[feedback_type] = count
                stats["total"] += count

            return stats


# ── Serialization Helpers ──────────────────────────────────────────────────


def _clone_to_dict(model: AgentCloneModel) -> Dict[str, Any]:
    """Convert AgentCloneModel to dict."""
    return {
        "id": str(model.id),
        "tenant_id": str(model.tenant_id),
        "clone_name": model.clone_name,
        "owner_id": model.owner_id,
        "persona_config": model.persona_config or {},
        "active": model.active,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


def _insight_to_dict(model: InsightModel) -> Dict[str, Any]:
    """Convert InsightModel to dict."""
    return {
        "id": str(model.id),
        "tenant_id": str(model.tenant_id),
        "account_id": model.account_id,
        "pattern_type": model.pattern_type,
        "pattern_data": model.pattern_data or {},
        "confidence": model.confidence,
        "severity": model.severity,
        "status": model.status,
        "created_at": model.created_at,
        "acted_at": model.acted_at,
    }


def _goal_to_dict(model: GoalModel) -> Dict[str, Any]:
    """Convert GoalModel to dict."""
    return {
        "id": str(model.id),
        "tenant_id": str(model.tenant_id),
        "clone_id": str(model.clone_id) if model.clone_id else None,
        "goal_type": model.goal_type,
        "target_value": model.target_value,
        "current_value": model.current_value,
        "period_start": model.period_start,
        "period_end": model.period_end,
        "status": model.status,
        "created_at": model.created_at,
    }


def _action_to_dict(model: AutonomousActionModel) -> Dict[str, Any]:
    """Convert AutonomousActionModel to dict."""
    return {
        "id": str(model.id),
        "tenant_id": str(model.tenant_id),
        "action_type": model.action_type,
        "account_id": model.account_id,
        "action_data": model.action_data or {},
        "proposed_at": model.proposed_at,
        "executed_at": model.executed_at,
        "execution_result": model.execution_result,
        "approval_status": model.approval_status,
        "approved_by": model.approved_by,
        "approved_at": model.approved_at,
    }


def _feedback_to_dict(model: AlertFeedbackModel) -> Dict[str, Any]:
    """Convert AlertFeedbackModel to dict."""
    return {
        "id": str(model.id),
        "tenant_id": str(model.tenant_id),
        "insight_id": str(model.insight_id),
        "feedback": model.feedback,
        "comment": model.comment,
        "submitted_at": model.submitted_at,
        "submitted_by": model.submitted_by,
    }
