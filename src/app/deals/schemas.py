"""Pydantic schemas for deal management -- plans, political mapping, CRM, signals.

Defines all structured types for the deal lifecycle:
- Enums: StakeholderRole, ScoreSource, OpportunitySource, FieldOwnership
- Political mapping: StakeholderScores, StakeholderCreate/Read
- Account plans: CompanyProfile, RelationshipHistory, StrategicPositioning, AccountPlanData
- Opportunity plans: CoreDealInfo, QualificationTracking, StakeholderSummary, ActionItem, OpportunityPlanData
- CRM payloads: OpportunityCreate/Update/Read/Filter, ContactCreate/Update, ActivityCreate,
  ChangeRecord, SyncResult, FieldOwnershipConfig
- Opportunity detection: OpportunitySignals

DealStage is imported from agents.sales.schemas (not duplicated).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.app.agents.sales.schemas import DealStage  # noqa: F401 -- re-export


# ── Enums ───────────────────────────────────────────────────────────────────


class StakeholderRole(str, Enum):
    """Roles a stakeholder can play in a deal (multiple allowed per person)."""

    DECISION_MAKER = "decision_maker"
    INFLUENCER = "influencer"
    CHAMPION = "champion"
    BLOCKER = "blocker"
    USER = "user"
    GATEKEEPER = "gatekeeper"


class ScoreSource(str, Enum):
    """Origin of a stakeholder score for audit transparency."""

    HEURISTIC = "heuristic"
    CONVERSATION_SIGNAL = "conversation_signal"
    HUMAN_OVERRIDE = "human_override"


class OpportunitySource(str, Enum):
    """How an opportunity was created."""

    AGENT_DETECTED = "agent_detected"
    MANUAL = "manual"
    IMPORTED = "imported"


class FieldOwnership(str, Enum):
    """Who owns a CRM field for conflict resolution during sync."""

    AGENT_OWNED = "agent_owned"
    HUMAN_OWNED = "human_owned"
    SHARED = "shared"


# ── Stakeholder Schemas ─────────────────────────────────────────────────────


class StakeholderScores(BaseModel):
    """Quantitative political mapping scores (0-10 scale)."""

    decision_power: int = Field(default=5, ge=0, le=10)
    influence_level: int = Field(default=5, ge=0, le=10)
    relationship_strength: int = Field(default=3, ge=0, le=10)


class StakeholderCreate(BaseModel):
    """Schema for creating a new stakeholder."""

    contact_name: str
    contact_email: str | None = None
    title: str | None = None
    roles: list[StakeholderRole] = Field(default_factory=list)
    scores: StakeholderScores = Field(default_factory=StakeholderScores)
    score_sources: dict[str, ScoreSource] = Field(default_factory=dict)
    score_evidence: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None


class StakeholderRead(BaseModel):
    """Schema for reading a stakeholder (includes all persisted fields)."""

    id: str
    account_id: str
    contact_name: str
    contact_email: str | None = None
    title: str | None = None
    roles: list[StakeholderRole] = Field(default_factory=list)
    scores: StakeholderScores = Field(default_factory=StakeholderScores)
    score_sources: dict[str, ScoreSource] = Field(default_factory=dict)
    score_evidence: dict[str, str] = Field(default_factory=dict)
    interaction_count: int = 0
    last_interaction: datetime | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Account Plan Data (CONTEXT.md locked sections) ──────────────────────────


class CompanyProfile(BaseModel):
    """Company profile section of the account plan."""

    industry: str | None = None
    company_size: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    business_model: str | None = None
    strategic_initiatives: list[str] = Field(default_factory=list)


class InteractionSummary(BaseModel):
    """Summary of a single interaction for relationship history."""

    date: datetime
    channel: str
    summary: str
    sentiment: str = "neutral"


class RelationshipHistory(BaseModel):
    """Relationship history section of the account plan."""

    key_events: list[str] = Field(default_factory=list, max_length=50)
    interaction_summaries: list[InteractionSummary] = Field(
        default_factory=list, max_length=20
    )
    overall_sentiment: str = "neutral"
    wins: list[str] = Field(default_factory=list)
    losses: list[str] = Field(default_factory=list)


class StrategicPositioning(BaseModel):
    """Strategic positioning section of the account plan."""

    competitive_landscape: str = ""
    whitespace_opportunities: list[str] = Field(default_factory=list)
    strategic_fit: str = ""


class AccountPlanData(BaseModel):
    """Full account plan document (stored as JSON in AccountPlanModel.plan_data).

    Sections per CONTEXT.md locked decisions:
    - Company profile: industry, size, tech stack, business model, initiatives
    - Relationship history: events, interactions, sentiment, wins/losses
    - Strategic positioning: competitive landscape, whitespace, fit
    - Active opportunities: list of opportunity IDs
    """

    company_profile: CompanyProfile = Field(default_factory=CompanyProfile)
    relationship_history: RelationshipHistory = Field(
        default_factory=RelationshipHistory
    )
    strategic_positioning: StrategicPositioning = Field(
        default_factory=StrategicPositioning
    )
    active_opportunity_ids: list[str] = Field(default_factory=list)


# ── Opportunity Plan Data (CONTEXT.md locked sections) ──────────────────────


class CoreDealInfo(BaseModel):
    """Core deal information section of the opportunity plan."""

    product_line: str | None = None
    estimated_value: float | None = None
    close_date: datetime | None = None
    probability: float = Field(default=0.1, ge=0.0, le=1.0)
    stage: str = "prospecting"
    source: str = "agent_detected"


class QualificationTracking(BaseModel):
    """BANT/MEDDIC qualification tracking section of the opportunity plan."""

    bant_snapshot: dict[str, Any] = Field(default_factory=dict)
    meddic_snapshot: dict[str, Any] = Field(default_factory=dict)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    last_assessed: datetime | None = None


class StakeholderSummary(BaseModel):
    """Lightweight stakeholder reference within an opportunity plan."""

    stakeholder_id: str
    name: str
    roles: list[str] = Field(default_factory=list)
    decision_power: int = Field(default=5, ge=0, le=10)
    influence_level: int = Field(default=5, ge=0, le=10)
    key_insight: str = ""


class ActionItem(BaseModel):
    """Action item / next step within an opportunity plan."""

    description: str
    owner: str
    due_date: datetime | None = None
    status: str = "open"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class OpportunityPlanData(BaseModel):
    """Full opportunity plan document (stored as JSON in OpportunityPlanModel.plan_data).

    Sections per CONTEXT.md locked decisions:
    - Core deal info: product, value, timeline, stage, probability
    - Qualification tracking: BANT/MEDDIC snapshots with confidence
    - Stakeholder map: lightweight references to key contacts
    - Action items: next steps with ownership and status
    """

    core_deal: CoreDealInfo = Field(default_factory=CoreDealInfo)
    qualification_tracking: QualificationTracking = Field(
        default_factory=QualificationTracking
    )
    stakeholder_map: list[StakeholderSummary] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list, max_length=30)


# ── Account CRUD Schemas ────────────────────────────────────────────────────


class AccountCreate(BaseModel):
    """Schema for creating a new account."""

    account_name: str
    industry: str | None = None
    company_size: str | None = None
    website: str | None = None
    region: str | None = None


class AccountRead(BaseModel):
    """Schema for reading an account (includes all persisted fields)."""

    id: str
    tenant_id: str
    account_name: str
    industry: str | None = None
    company_size: str | None = None
    website: str | None = None
    region: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Opportunity CRUD Schemas ────────────────────────────────────────────────


class OpportunityCreate(BaseModel):
    """Schema for creating a new opportunity."""

    account_id: str
    name: str
    product_line: str | None = None
    deal_stage: str = "prospecting"
    estimated_value: float | None = None
    close_date: datetime | None = None
    detection_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = "agent_detected"
    qualification_snapshot: dict[str, Any] = Field(default_factory=dict)


class OpportunityUpdate(BaseModel):
    """Schema for updating an opportunity (all fields optional)."""

    name: str | None = None
    product_line: str | None = None
    deal_stage: str | None = None
    estimated_value: float | None = None
    close_date: datetime | None = None
    detection_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    probability: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str | None = None
    qualification_snapshot: dict[str, Any] | None = None
    external_id: str | None = None


class OpportunityRead(BaseModel):
    """Schema for reading an opportunity (includes all persisted fields)."""

    id: str
    tenant_id: str
    account_id: str
    external_id: str | None = None
    name: str
    product_line: str | None = None
    deal_stage: str = "prospecting"
    estimated_value: float | None = None
    probability: float = 0.1
    close_date: datetime | None = None
    detection_confidence: float = 0.0
    source: str = "agent_detected"
    qualification_snapshot: dict[str, Any] = Field(default_factory=dict)
    synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OpportunityFilter(BaseModel):
    """Filter criteria for listing opportunities."""

    tenant_id: str
    account_id: str | None = None
    deal_stage: str | None = None
    source: str | None = None


# ── CRM Sync Schemas ───────────────────────────────────────────────────────


class ContactCreate(BaseModel):
    """CRM-facing contact creation payload (maps to StakeholderCreate)."""

    contact_name: str
    contact_email: str | None = None
    title: str | None = None
    roles: list[str] = Field(default_factory=list)
    decision_power: int = Field(default=5, ge=0, le=10)
    influence_level: int = Field(default=5, ge=0, le=10)
    relationship_strength: int = Field(default=3, ge=0, le=10)


class ContactUpdate(BaseModel):
    """CRM-facing contact update payload (all fields optional)."""

    contact_name: str | None = None
    contact_email: str | None = None
    title: str | None = None
    roles: list[str] | None = None
    decision_power: int | None = Field(default=None, ge=0, le=10)
    influence_level: int | None = Field(default=None, ge=0, le=10)
    relationship_strength: int | None = Field(default=None, ge=0, le=10)


class ActivityCreate(BaseModel):
    """CRM activity log entry."""

    type: str
    subject: str
    description: str
    related_opportunity_id: str | None = None
    related_contact_id: str | None = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ChangeRecord(BaseModel):
    """Record of a change for CRM sync audit trail."""

    entity_type: str
    entity_id: str
    external_id: str | None = None
    changed_fields: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: str = "agent"


class SyncResult(BaseModel):
    """Summary of a CRM sync operation."""

    pushed: int = 0
    pulled: int = 0
    conflicts: int = 0
    errors: list[str] = Field(default_factory=list)


class FieldOwnershipConfig(BaseModel):
    """Configuration for field ownership in CRM sync conflict resolution."""

    agent_owned_fields: list[str] = Field(default_factory=list)
    human_owned_fields: list[str] = Field(default_factory=list)
    shared_fields: list[str] = Field(default_factory=list)


# ── Opportunity Detection Schemas ───────────────────────────────────────────


class OpportunitySignals(BaseModel):
    """Signals extracted from a conversation indicating deal potential.

    Used by the OpportunityDetector to analyze conversations and decide
    whether to create/update an opportunity. The deal_potential_confidence
    threshold is >0.8 per CONTEXT.md (bias toward precision).
    """

    deal_potential_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    product_line: str | None = None
    estimated_value: float | None = None
    estimated_timeline: str | None = None
    pain_points: list[str] = Field(default_factory=list)
    budget_signals: list[str] = Field(default_factory=list)
    is_new_opportunity: bool = True
    matching_opportunity_id: str | None = None
    reasoning: str = ""
