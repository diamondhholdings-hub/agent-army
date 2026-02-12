"""Sales Agent persistence models -- conversation state in tenant schema.

Stores conversation state for each sales interaction, including deal stage,
qualification progress (BANT/MEDDIC as JSON), persona type, interaction history,
and escalation status. Uses TenantBase for schema_translate_map isolation.

The qualification_data JSON column stores serialized QualificationState
(BANT + MEDDIC signals) to allow flexible schema evolution without migrations.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.database import TenantBase


class ConversationStateModel(TenantBase):
    """Persistent conversation state for a sales deal/contact.

    Keyed by (tenant_id, account_id, contact_id) to ensure one state
    per contact per account per tenant. The qualification_data JSON
    column stores the full QualificationState (BANT + MEDDIC) for
    flexible evolution.
    """

    __tablename__ = "conversation_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "account_id",
            "contact_id",
            name="uq_conversation_state_tenant_account_contact",
        ),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deal_stage: Mapped[str] = mapped_column(
        String(50), default="prospecting", server_default=text("'prospecting'")
    )
    persona_type: Mapped[str] = mapped_column(
        String(20), default="manager", server_default=text("'manager'")
    )
    qualification_data: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    interaction_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    last_interaction: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    escalated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    escalation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence_score: Mapped[float] = mapped_column(
        Float, default=0.5, server_default=text("0.5")
    )
    next_actions: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'::json")
    )
    follow_up_scheduled: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )
