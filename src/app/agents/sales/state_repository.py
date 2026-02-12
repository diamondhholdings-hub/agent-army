"""Conversation state repository for async CRUD and qualification merging.

Provides ConversationStateRepository for persisting and retrieving sales
conversation state from PostgreSQL. Handles serialization between Pydantic
models (ConversationState, QualificationState) and the SQLAlchemy
ConversationStateModel JSON columns.

Deal stage transitions are validated against VALID_TRANSITIONS to prevent
illegal jumps (e.g., PROSPECTING cannot skip to NEGOTIATION).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agents.sales.schemas import (
    Channel,
    ConversationState,
    DealStage,
    NextAction,
    PersonaType,
    QualificationState,
)
from src.app.models.sales import ConversationStateModel

logger = structlog.get_logger(__name__)

# ── Deal Stage Transition Rules ───────────────────────────────────────────────

# Maps each stage to the set of stages it can transition TO.
# STALLED can be reached from any active stage, and can resume to any active stage.
VALID_TRANSITIONS: dict[DealStage, set[DealStage]] = {
    DealStage.PROSPECTING: {DealStage.DISCOVERY, DealStage.STALLED},
    DealStage.DISCOVERY: {DealStage.QUALIFICATION, DealStage.STALLED},
    DealStage.QUALIFICATION: {DealStage.EVALUATION, DealStage.STALLED},
    DealStage.EVALUATION: {DealStage.NEGOTIATION, DealStage.STALLED},
    DealStage.NEGOTIATION: {
        DealStage.CLOSED_WON,
        DealStage.CLOSED_LOST,
        DealStage.STALLED,
    },
    DealStage.CLOSED_WON: set(),  # Terminal stage
    DealStage.CLOSED_LOST: set(),  # Terminal stage
    DealStage.STALLED: {
        # Can resume to any active (non-terminal) stage
        DealStage.PROSPECTING,
        DealStage.DISCOVERY,
        DealStage.QUALIFICATION,
        DealStage.EVALUATION,
        DealStage.NEGOTIATION,
    },
}


class InvalidStageTransitionError(ValueError):
    """Raised when a deal stage transition violates the transition rules."""

    def __init__(self, from_stage: DealStage, to_stage: DealStage) -> None:
        self.from_stage = from_stage
        self.to_stage = to_stage
        super().__init__(
            f"Invalid stage transition: {from_stage.value} -> {to_stage.value}. "
            f"Allowed transitions from {from_stage.value}: "
            f"{', '.join(s.value for s in VALID_TRANSITIONS.get(from_stage, set()))}"
        )


def validate_stage_transition(from_stage: DealStage, to_stage: DealStage) -> None:
    """Validate that a deal stage transition is allowed.

    Args:
        from_stage: Current deal stage.
        to_stage: Target deal stage.

    Raises:
        InvalidStageTransitionError: If transition is not allowed.
    """
    if from_stage == to_stage:
        return  # Same stage is always valid (no-op)

    allowed = VALID_TRANSITIONS.get(from_stage, set())
    if to_stage not in allowed:
        raise InvalidStageTransitionError(from_stage, to_stage)


# ── Repository ────────────────────────────────────────────────────────────────


class ConversationStateRepository:
    """Async CRUD operations for conversation state persistence.

    Converts between Pydantic ConversationState models and SQLAlchemy
    ConversationStateModel rows, handling JSON serialization of
    QualificationState and NextAction lists.

    Args:
        session_factory: Async callable that yields AsyncSession instances.
    """

    def __init__(
        self, session_factory: Callable[..., AsyncGenerator[AsyncSession, None]]
    ) -> None:
        self._session_factory = session_factory

    async def get_state(
        self,
        tenant_id: str,
        account_id: str,
        contact_id: str,
    ) -> ConversationState | None:
        """Load conversation state by tenant + account + contact.

        Args:
            tenant_id: Tenant UUID string.
            account_id: Account identifier.
            contact_id: Contact identifier.

        Returns:
            ConversationState if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(ConversationStateModel).where(
                ConversationStateModel.tenant_id == uuid.UUID(tenant_id),
                ConversationStateModel.account_id == account_id,
                ConversationStateModel.contact_id == contact_id,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_state(model)

    async def save_state(self, state: ConversationState) -> ConversationState:
        """Upsert conversation state (insert or update).

        Uses SQLAlchemy merge() for upsert semantics. Validates deal stage
        transitions when updating an existing record.

        Args:
            state: ConversationState to persist.

        Returns:
            The persisted ConversationState (with any server-generated fields).
        """
        async for session in self._session_factory():
            # Check for existing record to validate stage transition
            stmt = select(ConversationStateModel).where(
                ConversationStateModel.tenant_id == uuid.UUID(state.tenant_id),
                ConversationStateModel.account_id == state.account_id,
                ConversationStateModel.contact_id == state.contact_id,
            )
            result = await session.execute(stmt)
            existing_model = result.scalar_one_or_none()

            if existing_model is not None:
                existing_stage = DealStage(existing_model.deal_stage)
                new_stage = state.deal_stage
                validate_stage_transition(existing_stage, new_stage)

                # Update existing model fields
                model_dict = _state_to_model(state)
                for key, value in model_dict.items():
                    if key != "id":
                        setattr(existing_model, key, value)
                await session.commit()
                await session.refresh(existing_model)
                return _model_to_state(existing_model)
            else:
                # Insert new record
                model_dict = _state_to_model(state)
                new_model = ConversationStateModel(**model_dict)
                session.add(new_model)
                await session.commit()
                await session.refresh(new_model)
                return _model_to_state(new_model)

    async def list_states_by_tenant(
        self,
        tenant_id: str,
        deal_stage: str | None = None,
    ) -> list[ConversationState]:
        """List all conversation states for a tenant.

        Args:
            tenant_id: Tenant UUID string.
            deal_stage: Optional filter by deal stage value.

        Returns:
            List of ConversationState objects.
        """
        async for session in self._session_factory():
            stmt = select(ConversationStateModel).where(
                ConversationStateModel.tenant_id == uuid.UUID(tenant_id),
            )
            if deal_stage is not None:
                stmt = stmt.where(
                    ConversationStateModel.deal_stage == deal_stage,
                )
            result = await session.execute(stmt)
            models = result.scalars().all()
            return [_model_to_state(m) for m in models]

    async def update_qualification(
        self,
        tenant_id: str,
        account_id: str,
        contact_id: str,
        new_signals: QualificationState,
    ) -> ConversationState:
        """Merge new qualification signals into existing state.

        Loads existing state, merges via merge_qualification_signals(),
        and saves the result. Prevents Pitfall 3 (overwriting existing
        qualification data).

        Args:
            tenant_id: Tenant UUID string.
            account_id: Account identifier.
            contact_id: Contact identifier.
            new_signals: New QualificationState to merge.

        Returns:
            Updated ConversationState with merged qualification.

        Raises:
            ValueError: If no existing state found for the given keys.
        """
        # Import here to avoid circular dependency
        from src.app.agents.sales.qualification import merge_qualification_signals

        existing = await self.get_state(tenant_id, account_id, contact_id)
        if existing is None:
            raise ValueError(
                f"No conversation state found for tenant={tenant_id}, "
                f"account={account_id}, contact={contact_id}"
            )

        merged = merge_qualification_signals(existing.qualification, new_signals)
        existing.qualification = merged
        return await self.save_state(existing)


# ── Serialization Helpers ─────────────────────────────────────────────────────


def _model_to_state(model: ConversationStateModel) -> ConversationState:
    """Convert a SQLAlchemy ConversationStateModel to a Pydantic ConversationState.

    Deserializes qualification_data JSON into QualificationState and
    next_actions JSON into list[NextAction].
    """
    # Deserialize qualification_data JSON
    qual_data = model.qualification_data or {}
    qualification = QualificationState(**qual_data) if qual_data else QualificationState()

    # Deserialize next_actions JSON
    actions_data = model.next_actions or []
    next_actions = [a if isinstance(a, str) else a.get("description", str(a)) for a in actions_data]

    return ConversationState(
        state_id=str(model.id),
        tenant_id=str(model.tenant_id),
        account_id=model.account_id,
        contact_id=model.contact_id,
        contact_email=model.contact_email,
        contact_name=model.contact_name or "",
        deal_stage=DealStage(model.deal_stage),
        persona_type=PersonaType(model.persona_type),
        qualification=qualification,
        interaction_count=model.interaction_count or 0,
        last_interaction=model.last_interaction,
        last_channel=Channel(model.last_channel) if model.last_channel else None,
        escalated=model.escalated or False,
        escalation_reason=model.escalation_reason,
        confidence_score=model.confidence_score or 0.5,
        next_actions=next_actions,
        follow_up_scheduled=model.follow_up_scheduled,
        created_at=model.created_at or datetime.now(timezone.utc),
        metadata=model.metadata_json or {},
    )


def _state_to_model(state: ConversationState) -> dict:
    """Convert a Pydantic ConversationState to a dict suitable for ConversationStateModel.

    Serializes QualificationState to JSON for the qualification_data column
    and next_actions list to JSON.
    """
    return {
        "id": uuid.UUID(state.state_id) if state.state_id else uuid.uuid4(),
        "tenant_id": uuid.UUID(state.tenant_id),
        "account_id": state.account_id,
        "contact_id": state.contact_id,
        "contact_email": state.contact_email,
        "contact_name": state.contact_name or None,
        "deal_stage": state.deal_stage.value,
        "persona_type": state.persona_type.value,
        "qualification_data": state.qualification.model_dump(
            mode="json", exclude_none=False
        ),
        "interaction_count": state.interaction_count,
        "last_interaction": state.last_interaction,
        "last_channel": state.last_channel.value if state.last_channel else None,
        "escalated": state.escalated,
        "escalation_reason": state.escalation_reason,
        "confidence_score": state.confidence_score,
        "next_actions": state.next_actions,
        "follow_up_scheduled": state.follow_up_scheduled,
        "metadata_json": state.metadata,
        "created_at": state.created_at,
    }
