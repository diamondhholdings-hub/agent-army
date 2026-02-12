"""Learning module persistence models -- outcome records, feedback, and calibration.

Three tenant-scoped tables for the agent learning system:
- outcome_records: Tracks predicted vs actual outcomes for agent actions
- feedback_entries: Human feedback on agent behavior (inline + dashboard)
- calibration_bins: Per-action-type confidence calibration data (10 bins)

All models use TenantBase for schema_translate_map isolation, following
the exact pattern from src/app/models/sales.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.database import TenantBase


class OutcomeRecordModel(TenantBase):
    """Persistent outcome record for a single agent action.

    Tracks the agent's predicted confidence at action time and the actual
    outcome once resolved. Time-windowed signal detection resolves pending
    outcomes to positive, negative, ambiguous, or expired.

    Keyed by (tenant_id, conversation_state_id, action_type) for querying
    all outcomes related to a conversation or action type.
    """

    __tablename__ = "outcome_records"
    __table_args__ = (
        Index(
            "idx_outcome_records_tenant_action_created",
            "tenant_id",
            "action_type",
            "created_at",
        ),
        Index(
            "idx_outcome_records_tenant_status_created",
            "tenant_id",
            "outcome_status",
            "created_at",
        ),
        Index(
            "idx_outcome_records_tenant_type_status",
            "tenant_id",
            "outcome_type",
            "outcome_status",
        ),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    predicted_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    outcome_type: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default=text("'pending'")
    )
    outcome_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    window_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class FeedbackEntryModel(TenantBase):
    """Human feedback on agent behavior -- inline reactions or dashboard reviews.

    Supports dual interface: quick inline reactions (thumbs up/down from
    Slack/Gmail) and detailed reviews (1-5 scale from web dashboard).
    Each feedback targets a specific message, decision, or conversation.
    """

    __tablename__ = "feedback_entries"
    __table_args__ = (
        Index(
            "idx_feedback_entries_tenant_conversation",
            "tenant_id",
            "conversation_state_id",
        ),
        Index(
            "idx_feedback_entries_tenant_reviewer_created",
            "tenant_id",
            "reviewer_id",
            "created_at",
        ),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    outcome_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    conversation_state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(20), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class CalibrationBinModel(TenantBase):
    """Per-action-type confidence calibration bin.

    Maintains 10 bins (0-9) per action type, each tracking the predicted
    confidence range and actual outcome rate. Used to compute calibration
    curves and Brier scores for detecting miscalibration.

    Unique constraint on (tenant_id, action_type, bin_index) ensures
    exactly one bin per position per action type per tenant.
    """

    __tablename__ = "calibration_bins"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "action_type",
            "bin_index",
            name="uq_calibration_bin_tenant_action_bin",
        ),
        Index(
            "idx_calibration_bins_tenant_action",
            "tenant_id",
            "action_type",
        ),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    bin_index: Mapped[int] = mapped_column(Integer, nullable=False)
    bin_lower: Mapped[float] = mapped_column(Float, nullable=False)
    bin_upper: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    outcome_sum: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0.0")
    )
    actual_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    brier_contribution: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_updated: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
