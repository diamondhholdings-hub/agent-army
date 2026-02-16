"""Intelligence & Autonomy persistence models -- tenant-scoped tables.

Five SQLAlchemy models using TenantBase for schema_translate_map isolation:
- AgentCloneModel: Persona configuration per agent clone
- InsightModel: Detected patterns and alerts for human review
- GoalModel: Revenue targets and activity metrics
- AutonomousActionModel: Audit trail of autonomous decisions
- AlertFeedbackModel: Feedback on alert usefulness for threshold tuning

All models use the "tenant" placeholder schema, remapped at runtime to the
actual tenant schema (e.g., "tenant_skyvera") via schema_translate_map.

No foreign key constraints (application-level referential integrity via
repository, consistent with Phase 5/6 pattern).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.database import TenantBase


class AgentCloneModel(TenantBase):
    """Agent clone with persona configuration.

    Represents a personalized sales agent instance. Each clone has
    a unique persona configuration (stored as JSON) that affects
    communication style. All clones within a tenant share product
    knowledge, sales methodologies, and pattern insights.
    """

    __tablename__ = "agent_clones"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "clone_name",
            name="uq_clone_tenant_name",
        ),
        Index("idx_agent_clones_tenant_active", "tenant_id", "active"),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    clone_name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False)
    persona_config: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
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


class InsightModel(TenantBase):
    """Detected pattern persisted for human review.

    Stores pattern detection results with confidence scoring,
    severity classification, and lifecycle status tracking.
    Pattern data stored as JSON for schema flexibility.
    """

    __tablename__ = "insights"
    __table_args__ = (
        Index("idx_insights_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("idx_insights_tenant_account", "tenant_id", "account_id"),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[str] = mapped_column(String(100), nullable=False)
    pattern_type: Mapped[str] = mapped_column(String(50), nullable=False)
    pattern_data: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), default="medium", server_default=text("'medium'")
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default=text("'pending'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    acted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class GoalModel(TenantBase):
    """Revenue, pipeline, or activity target.

    Tracks measurable goals for agents or clones. Goals have a
    defined time period and progress from current_value toward
    target_value. Status transitions: active -> completed/missed.
    """

    __tablename__ = "goals"
    __table_args__ = (
        Index("idx_goals_tenant_status", "tenant_id", "status"),
        Index("idx_goals_tenant_clone", "tenant_id", "clone_id"),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    clone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    goal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    current_value: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0.0")
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class AutonomousActionModel(TenantBase):
    """Audit trail for autonomous agent decisions.

    Every action proposed by the agent is logged here, regardless
    of whether it was executed, blocked, or pending approval. Stores
    the full action context and guardrail check result.
    """

    __tablename__ = "autonomous_actions"
    __table_args__ = (
        Index(
            "idx_actions_tenant_approval_proposed",
            "tenant_id",
            "approval_status",
            "proposed_at",
        ),
        Index("idx_actions_tenant_account", "tenant_id", "account_id"),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    account_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action_data: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    execution_result: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    approval_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AlertFeedbackModel(TenantBase):
    """Human feedback on alert usefulness.

    Captures "useful" or "false_alarm" feedback on insights to tune
    pattern detection confidence thresholds over time. Linked to
    insights via insight_id (application-level referential integrity).
    """

    __tablename__ = "alert_feedback"
    __table_args__ = (
        Index("idx_feedback_tenant_feedback", "tenant_id", "feedback"),
        Index("idx_feedback_tenant_insight", "tenant_id", "insight_id"),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    insight_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    feedback: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    submitted_by: Mapped[str] = mapped_column(String(100), nullable=False)
