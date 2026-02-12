"""OutcomeTracker service for recording and resolving agent action outcomes.

Records pending outcomes when agents take actions, resolves them via
time-windowed signal detection (email reply, deal progression, expiry),
and handles race conditions with SELECT FOR UPDATE SKIP LOCKED.

Uses the session_factory callable pattern from ConversationStateRepository
for testable async database access with tenant isolation.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.learning.models import OutcomeRecordModel
from src.app.learning.schemas import OutcomeRecord, OutcomeStatus

logger = structlog.get_logger(__name__)


class OutcomeTracker:
    """Records and resolves agent action outcomes with time-windowed signal detection.

    Window configurations (from CONTEXT.md locked decisions):
    - email_engagement: 24h for immediate signals (reply detection)
    - deal_progression: 720h (30 days) for stage advancement
    - meeting_outcome: 168h (7 days) for meeting follow-up
    - escalation_result: 168h (7 days) for escalation resolution
    """

    WINDOW_CONFIG: dict[str, int] = {
        "email_engagement": 24,
        "deal_progression": 720,
        "meeting_outcome": 168,
        "escalation_result": 168,
    }

    def __init__(
        self,
        session_factory: Callable[..., AsyncGenerator[AsyncSession, None]],
    ) -> None:
        """Initialize with a session factory callable.

        Args:
            session_factory: Async callable that yields AsyncSession instances.
                Same pattern as ConversationStateRepository.
        """
        self._session_factory = session_factory

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
        """Record a new pending outcome for an agent action.

        Calculates window_expires_at from WINDOW_CONFIG based on outcome_type.
        Creates OutcomeRecordModel in database with status=pending.

        Args:
            tenant_id: Tenant UUID string.
            conversation_state_id: Conversation state UUID string.
            action_type: Type of action (send_email, send_chat, etc.).
            predicted_confidence: Agent's confidence at time of action (0.0-1.0).
            outcome_type: Type of outcome to track (email_engagement, etc.).
            action_id: Optional reference to specific message/decision ID.
            metadata: Optional metadata dict to store with the outcome.

        Returns:
            The created OutcomeRecord schema.
        """
        now = datetime.now(timezone.utc)
        window_hours = self.WINDOW_CONFIG.get(outcome_type, 168)
        window_expires_at = now + timedelta(hours=window_hours)

        outcome_id = uuid.uuid4()
        meta = metadata or {}

        async for session in self._session_factory():
            model = OutcomeRecordModel(
                id=outcome_id,
                tenant_id=uuid.UUID(tenant_id),
                conversation_state_id=uuid.UUID(conversation_state_id),
                action_type=action_type,
                action_id=action_id,
                predicted_confidence=predicted_confidence,
                outcome_type=outcome_type,
                outcome_status=OutcomeStatus.PENDING.value,
                window_expires_at=window_expires_at,
                metadata_json=meta,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)

            logger.info(
                "outcome.recorded",
                outcome_id=str(outcome_id),
                tenant_id=tenant_id,
                action_type=action_type,
                outcome_type=outcome_type,
                predicted_confidence=predicted_confidence,
                window_expires_at=window_expires_at.isoformat(),
            )

            return OutcomeRecord(
                outcome_id=str(model.id),
                tenant_id=str(model.tenant_id),
                conversation_state_id=str(model.conversation_state_id),
                action_type=model.action_type,
                action_id=model.action_id,
                predicted_confidence=model.predicted_confidence,
                outcome_type=model.outcome_type,
                outcome_status=model.outcome_status,
                outcome_score=model.outcome_score,
                signal_source=model.signal_source,
                window_expires_at=model.window_expires_at,
                resolved_at=model.resolved_at,
                metadata_json=model.metadata_json,
                created_at=model.created_at or now,
            )

        # Should not reach here, but satisfy type checker
        raise RuntimeError("Session factory yielded no session")  # pragma: no cover

    async def resolve_outcome(
        self,
        outcome_id: str,
        tenant_id: str,
        outcome_status: str,
        outcome_score: float | None = None,
        signal_source: str = "automatic",
    ) -> OutcomeRecord:
        """Resolve a pending outcome with a final status and optional score.

        Uses SELECT ... FOR UPDATE SKIP LOCKED to prevent race conditions
        (Pitfall 1 from RESEARCH.md). Validates that outcome is currently
        pending to prevent double-resolution.

        Args:
            outcome_id: UUID string of the outcome to resolve.
            tenant_id: Tenant UUID string.
            outcome_status: Final status (positive, negative, ambiguous).
            outcome_score: Optional numeric score (scale depends on type).
            signal_source: How the outcome was detected ("automatic" or "human_label").

        Returns:
            The resolved OutcomeRecord.

        Raises:
            ValueError: If outcome not found or already resolved.
        """
        now = datetime.now(timezone.utc)

        async for session in self._session_factory():
            # SELECT FOR UPDATE SKIP LOCKED to prevent concurrent resolution
            stmt = (
                select(OutcomeRecordModel)
                .where(
                    OutcomeRecordModel.id == uuid.UUID(outcome_id),
                    OutcomeRecordModel.tenant_id == uuid.UUID(tenant_id),
                )
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(
                    f"Outcome {outcome_id} not found or locked by another process"
                )

            if model.outcome_status != OutcomeStatus.PENDING.value:
                raise ValueError(
                    f"Outcome {outcome_id} already resolved with status "
                    f"'{model.outcome_status}', cannot re-resolve"
                )

            model.outcome_status = outcome_status
            model.outcome_score = outcome_score
            model.signal_source = signal_source
            model.resolved_at = now

            await session.commit()
            await session.refresh(model)

            logger.info(
                "outcome.resolved",
                outcome_id=outcome_id,
                tenant_id=tenant_id,
                outcome_status=outcome_status,
                outcome_score=outcome_score,
                signal_source=signal_source,
            )

            return OutcomeRecord(
                outcome_id=str(model.id),
                tenant_id=str(model.tenant_id),
                conversation_state_id=str(model.conversation_state_id),
                action_type=model.action_type,
                action_id=model.action_id,
                predicted_confidence=model.predicted_confidence,
                outcome_type=model.outcome_type,
                outcome_status=model.outcome_status,
                outcome_score=model.outcome_score,
                signal_source=model.signal_source,
                window_expires_at=model.window_expires_at,
                resolved_at=model.resolved_at,
                metadata_json=model.metadata_json,
                created_at=model.created_at,
            )

        raise RuntimeError("Session factory yielded no session")  # pragma: no cover

    async def get_pending_outcomes(
        self,
        tenant_id: str | None = None,
        outcome_type: str | None = None,
        expired_only: bool = False,
    ) -> list[OutcomeRecord]:
        """Query pending outcomes, optionally filtered by type or expired window.

        Args:
            tenant_id: Optional tenant filter.
            outcome_type: Optional outcome type filter.
            expired_only: If True, only returns outcomes past their window.

        Returns:
            List of matching OutcomeRecord schemas.
        """
        async for session in self._session_factory():
            stmt = select(OutcomeRecordModel).where(
                OutcomeRecordModel.outcome_status == OutcomeStatus.PENDING.value,
            )

            if tenant_id is not None:
                stmt = stmt.where(
                    OutcomeRecordModel.tenant_id == uuid.UUID(tenant_id)
                )

            if outcome_type is not None:
                stmt = stmt.where(
                    OutcomeRecordModel.outcome_type == outcome_type
                )

            if expired_only:
                now = datetime.now(timezone.utc)
                stmt = stmt.where(
                    OutcomeRecordModel.window_expires_at < now
                )

            result = await session.execute(stmt)
            models = result.scalars().all()

            return [
                OutcomeRecord(
                    outcome_id=str(m.id),
                    tenant_id=str(m.tenant_id),
                    conversation_state_id=str(m.conversation_state_id),
                    action_type=m.action_type,
                    action_id=m.action_id,
                    predicted_confidence=m.predicted_confidence,
                    outcome_type=m.outcome_type,
                    outcome_status=m.outcome_status,
                    outcome_score=m.outcome_score,
                    signal_source=m.signal_source,
                    window_expires_at=m.window_expires_at,
                    resolved_at=m.resolved_at,
                    metadata_json=m.metadata_json,
                    created_at=m.created_at,
                )
                for m in models
            ]

        return []  # pragma: no cover

    async def get_outcomes_for_conversation(
        self,
        tenant_id: str,
        conversation_state_id: str,
    ) -> list[OutcomeRecord]:
        """Get all outcomes (any status) for a specific conversation.

        Args:
            tenant_id: Tenant UUID string.
            conversation_state_id: Conversation state UUID string.

        Returns:
            List of OutcomeRecord schemas for the conversation.
        """
        async for session in self._session_factory():
            stmt = select(OutcomeRecordModel).where(
                OutcomeRecordModel.tenant_id == uuid.UUID(tenant_id),
                OutcomeRecordModel.conversation_state_id == uuid.UUID(
                    conversation_state_id
                ),
            )
            result = await session.execute(stmt)
            models = result.scalars().all()

            return [
                OutcomeRecord(
                    outcome_id=str(m.id),
                    tenant_id=str(m.tenant_id),
                    conversation_state_id=str(m.conversation_state_id),
                    action_type=m.action_type,
                    action_id=m.action_id,
                    predicted_confidence=m.predicted_confidence,
                    outcome_type=m.outcome_type,
                    outcome_status=m.outcome_status,
                    outcome_score=m.outcome_score,
                    signal_source=m.signal_source,
                    window_expires_at=m.window_expires_at,
                    resolved_at=m.resolved_at,
                    metadata_json=m.metadata_json,
                    created_at=m.created_at,
                )
                for m in models
            ]

        return []  # pragma: no cover

    async def check_immediate_signals(self, tenant_id: str | None = None) -> int:
        """Check for immediate signals (email reply detection).

        Queries pending email_engagement outcomes within their 24h window.
        For each, checks if the conversation_state has had new interactions
        since the outcome was recorded (reply detected = positive).

        Detection logic:
        - Load conversation state for each pending outcome
        - If state.interaction_count increased since outcome.created_at: POSITIVE
        - If window expired: EXPIRED
        - Otherwise: still PENDING (leave for next check)

        Args:
            tenant_id: Optional tenant filter.

        Returns:
            Count of outcomes resolved.
        """
        from src.app.models.sales import ConversationStateModel

        resolved_count = 0
        now = datetime.now(timezone.utc)

        async for session in self._session_factory():
            stmt = select(OutcomeRecordModel).where(
                OutcomeRecordModel.outcome_status == OutcomeStatus.PENDING.value,
                OutcomeRecordModel.outcome_type == "email_engagement",
            )
            if tenant_id is not None:
                stmt = stmt.where(
                    OutcomeRecordModel.tenant_id == uuid.UUID(tenant_id)
                )

            result = await session.execute(stmt)
            outcomes = result.scalars().all()

            for outcome in outcomes:
                # Check window expiry first
                if outcome.window_expires_at and outcome.window_expires_at < now:
                    outcome.outcome_status = OutcomeStatus.EXPIRED.value
                    outcome.resolved_at = now
                    resolved_count += 1
                    continue

                # Check for reply signal via conversation state
                conv_stmt = select(ConversationStateModel).where(
                    ConversationStateModel.id == outcome.conversation_state_id,
                    ConversationStateModel.tenant_id == outcome.tenant_id,
                )
                conv_result = await session.execute(conv_stmt)
                conv = conv_result.scalar_one_or_none()

                if conv is None:
                    continue

                # If interaction count increased since outcome creation, reply detected
                initial_count = outcome.metadata_json.get("interaction_count_at_creation", 0)
                if conv.interaction_count > initial_count:
                    outcome.outcome_status = OutcomeStatus.POSITIVE.value
                    outcome.outcome_score = 1.0
                    outcome.signal_source = "automatic"
                    outcome.resolved_at = now
                    resolved_count += 1

            if resolved_count > 0:
                await session.commit()

            logger.info(
                "outcome.immediate_signals_checked",
                resolved_count=resolved_count,
                tenant_id=tenant_id,
            )

            return resolved_count

        return 0  # pragma: no cover

    async def check_deal_progression_signals(
        self, tenant_id: str | None = None
    ) -> int:
        """Check for deal progression signals.

        Queries pending deal_progression outcomes. For each, checks if the
        deal stage has advanced from the stage at outcome creation.

        Detection logic:
        - Load conversation state
        - Compare current deal_stage vs stage in metadata_json["deal_stage_at_creation"]
        - Stage advanced forward: POSITIVE (score based on stages advanced)
        - Stage moved to CLOSED_LOST or STALLED: NEGATIVE
        - No change but window expired: EXPIRED

        Args:
            tenant_id: Optional tenant filter.

        Returns:
            Count of outcomes resolved.
        """
        from src.app.models.sales import ConversationStateModel

        # Ordered stages for progression calculation
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

        async for session in self._session_factory():
            stmt = select(OutcomeRecordModel).where(
                OutcomeRecordModel.outcome_status == OutcomeStatus.PENDING.value,
                OutcomeRecordModel.outcome_type == "deal_progression",
            )
            if tenant_id is not None:
                stmt = stmt.where(
                    OutcomeRecordModel.tenant_id == uuid.UUID(tenant_id)
                )

            result = await session.execute(stmt)
            outcomes = result.scalars().all()

            for outcome in outcomes:
                conv_stmt = select(ConversationStateModel).where(
                    ConversationStateModel.id == outcome.conversation_state_id,
                    ConversationStateModel.tenant_id == outcome.tenant_id,
                )
                conv_result = await session.execute(conv_stmt)
                conv = conv_result.scalar_one_or_none()

                if conv is None:
                    # Window check even without conv state
                    if outcome.window_expires_at and outcome.window_expires_at < now:
                        outcome.outcome_status = OutcomeStatus.EXPIRED.value
                        outcome.resolved_at = now
                        resolved_count += 1
                    continue

                original_stage = outcome.metadata_json.get(
                    "deal_stage_at_creation", "prospecting"
                )
                current_stage = conv.deal_stage

                # Check for negative outcomes
                if current_stage in ("closed_lost", "stalled"):
                    outcome.outcome_status = OutcomeStatus.NEGATIVE.value
                    outcome.outcome_score = 0.0
                    outcome.signal_source = "automatic"
                    outcome.resolved_at = now
                    resolved_count += 1
                    continue

                # Check for positive progression
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
                    # Score: 0.2 per stage advanced, max 1.0
                    score = min(stages_advanced * 0.2, 1.0)
                    outcome.outcome_status = OutcomeStatus.POSITIVE.value
                    outcome.outcome_score = score
                    outcome.signal_source = "automatic"
                    outcome.resolved_at = now
                    resolved_count += 1
                    continue

                # No change -- check window
                if outcome.window_expires_at and outcome.window_expires_at < now:
                    outcome.outcome_status = OutcomeStatus.EXPIRED.value
                    outcome.resolved_at = now
                    resolved_count += 1

            if resolved_count > 0:
                await session.commit()

            logger.info(
                "outcome.deal_progression_signals_checked",
                resolved_count=resolved_count,
                tenant_id=tenant_id,
            )

            return resolved_count

        return 0  # pragma: no cover

    async def expire_overdue_outcomes(self, tenant_id: str | None = None) -> int:
        """Bulk-expire outcomes past their window with no signal detected.

        Efficiently updates all pending outcomes where window_expires_at < now()
        to status=EXPIRED. Uses a single UPDATE statement for performance.

        Args:
            tenant_id: Optional tenant filter.

        Returns:
            Count of expired outcomes.
        """
        now = datetime.now(timezone.utc)

        async for session in self._session_factory():
            stmt = (
                update(OutcomeRecordModel)
                .where(
                    OutcomeRecordModel.outcome_status == OutcomeStatus.PENDING.value,
                    OutcomeRecordModel.window_expires_at < now,
                )
                .values(
                    outcome_status=OutcomeStatus.EXPIRED.value,
                    resolved_at=now,
                )
            )

            if tenant_id is not None:
                stmt = stmt.where(
                    OutcomeRecordModel.tenant_id == uuid.UUID(tenant_id)
                )

            result = await session.execute(stmt)
            await session.commit()

            expired_count = result.rowcount  # type: ignore[union-attr]

            logger.info(
                "outcome.overdue_expired",
                expired_count=expired_count,
                tenant_id=tenant_id,
            )

            return expired_count

        return 0  # pragma: no cover
