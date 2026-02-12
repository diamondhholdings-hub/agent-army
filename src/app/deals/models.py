"""Deal management persistence models -- tenant-scoped tables for the deal lifecycle.

Five SQLAlchemy models using TenantBase for schema_translate_map isolation:
- AccountModel: Company accounts being pursued
- OpportunityModel: Individual deals/opportunities within accounts
- StakeholderModel: Contacts with political mapping scores
- AccountPlanModel: Strategic account plans (JSON document)
- OpportunityPlanModel: Tactical opportunity plans (JSON document)

All models use the "tenant" placeholder schema, remapped at runtime to the
actual tenant schema (e.g., "tenant_skyvera") via schema_translate_map.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.database import TenantBase


class AccountModel(TenantBase):
    """Company account being pursued by the sales agent.

    Represents a target organization. One account per name per tenant,
    enforced by unique constraint. Serves as the parent entity for
    opportunities and stakeholders.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "account_name",
            name="uq_account_tenant_name",
        ),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_name: Mapped[str] = mapped_column(String(300), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
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


class OpportunityModel(TenantBase):
    """Individual deal/opportunity within an account.

    Tracks deal stage, estimated value, probability, detection confidence,
    and qualification snapshot. Linked to an account via account_id
    (application-level referential integrity, no FK constraint due to
    tenant-schema RLS architecture).
    """

    __tablename__ = "opportunities"
    __table_args__ = (
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    product_line: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deal_stage: Mapped[str] = mapped_column(
        String(50), default="prospecting", server_default=text("'prospecting'")
    )
    estimated_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability: Mapped[float] = mapped_column(
        Float, default=0.1, server_default=text("0.1")
    )
    close_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    detection_confidence: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0.0")
    )
    source: Mapped[str] = mapped_column(
        String(50), default="agent_detected", server_default=text("'agent_detected'")
    )
    qualification_snapshot: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
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
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StakeholderModel(TenantBase):
    """Contact/stakeholder with political mapping scores.

    Supports multiple roles per person and three quantitative 0-10 scores:
    decision_power, influence_level, relationship_strength. Score origin
    and evidence are tracked for transparency.
    """

    __tablename__ = "stakeholders"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "account_id",
            "contact_email",
            name="uq_stakeholder_tenant_account_email",
        ),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    roles: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'::json")
    )
    decision_power: Mapped[int] = mapped_column(
        Integer, default=5, server_default=text("5")
    )
    influence_level: Mapped[int] = mapped_column(
        Integer, default=5, server_default=text("5")
    )
    relationship_strength: Mapped[int] = mapped_column(
        Integer, default=3, server_default=text("3")
    )
    score_sources: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    score_evidence: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    interaction_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    last_interaction: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class AccountPlanModel(TenantBase):
    """Strategic account plan stored as a JSON document.

    One plan per account per tenant. The plan_data column stores the full
    AccountPlanData Pydantic model as JSON. Version increments on each
    update to support optimistic concurrency and audit trail.
    """

    __tablename__ = "account_plans"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "account_id",
            name="uq_account_plan_tenant_account",
        ),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plan_data: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1")
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


class OpportunityPlanModel(TenantBase):
    """Tactical opportunity plan stored as a JSON document.

    One plan per opportunity per tenant. The plan_data column stores the
    full OpportunityPlanData Pydantic model as JSON. Version increments
    on each update.
    """

    __tablename__ = "opportunity_plans"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "opportunity_id",
            name="uq_opportunity_plan_tenant_opportunity",
        ),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plan_data: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1")
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
