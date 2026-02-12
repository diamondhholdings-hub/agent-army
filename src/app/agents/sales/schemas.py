"""Pydantic data models for the Sales Agent domain.

Defines all structured types used across the Sales Agent: qualification signals
(BANT, MEDDIC), conversation state, deal stages, persona types, escalation
reports, and next-action recommendations. These models are the foundational
types that every Sales Agent component depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


# ── Enums ───────────────────────────────────────────────────────────────────


class PersonaType(str, Enum):
    """Customer persona seniority level for communication style adaptation."""

    IC = "ic"
    MANAGER = "manager"
    C_SUITE = "c_suite"


class DealStage(str, Enum):
    """Sales pipeline stage for a deal/opportunity."""

    PROSPECTING = "prospecting"
    DISCOVERY = "discovery"
    QUALIFICATION = "qualification"
    EVALUATION = "evaluation"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"
    STALLED = "stalled"


class Channel(str, Enum):
    """Communication channel for sales interactions."""

    EMAIL = "email"
    CHAT = "chat"


# ── BANT Qualification Signals ──────────────────────────────────────────────


class BANTSignals(BaseModel):
    """Budget, Authority, Need, Timeline qualification signals with evidence.

    Each BANT dimension tracks whether the signal has been identified, its
    value, the evidence quote from the conversation, and a confidence score.
    """

    # Budget
    budget_identified: bool = False
    budget_range: str | None = None
    budget_evidence: str | None = None
    budget_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Authority
    authority_identified: bool = False
    authority_contact: str | None = None
    authority_role: str | None = None
    authority_evidence: str | None = None
    authority_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Need
    need_identified: bool = False
    need_description: str | None = None
    need_evidence: str | None = None
    need_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Timeline
    timeline_identified: bool = False
    timeline_description: str | None = None
    timeline_evidence: str | None = None
    timeline_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def completion_score(self) -> float:
        """Fraction of BANT dimensions identified (0.0 to 1.0)."""
        identified = sum([
            self.budget_identified,
            self.authority_identified,
            self.need_identified,
            self.timeline_identified,
        ])
        return identified / 4


# ── MEDDIC Qualification Signals ────────────────────────────────────────────


class MEDDICSignals(BaseModel):
    """Metrics, Economic Buyer, Decision Criteria/Process, Identify Pain,
    Champion qualification signals with evidence.

    Each MEDDIC dimension tracks identification status, details, evidence,
    and confidence -- enabling progressive qualification over multiple
    interactions without losing signal history.
    """

    # Metrics
    metrics_identified: bool = False
    metrics_description: str | None = None
    metrics_evidence: str | None = None
    metrics_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Economic Buyer
    economic_buyer_identified: bool = False
    economic_buyer_contact: str | None = None
    economic_buyer_evidence: str | None = None
    economic_buyer_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Decision Criteria
    decision_criteria_identified: bool = False
    decision_criteria: list[str] = Field(default_factory=list)
    decision_criteria_evidence: str | None = None
    decision_criteria_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Decision Process
    decision_process_identified: bool = False
    decision_process_description: str | None = None
    decision_process_evidence: str | None = None
    decision_process_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Identify Pain
    pain_identified: bool = False
    pain_description: str | None = None
    pain_evidence: str | None = None
    pain_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Champion
    champion_identified: bool = False
    champion_contact: str | None = None
    champion_evidence: str | None = None
    champion_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def completion_score(self) -> float:
        """Fraction of MEDDIC dimensions identified (0.0 to 1.0)."""
        identified = sum([
            self.metrics_identified,
            self.economic_buyer_identified,
            self.decision_criteria_identified,
            self.decision_process_identified,
            self.pain_identified,
            self.champion_identified,
        ])
        return identified / 6


# ── Combined Qualification State ────────────────────────────────────────────


class QualificationState(BaseModel):
    """Combined BANT + MEDDIC qualification tracking.

    Aggregates both frameworks into a single state object with overall
    confidence, key insights, and recommended next questions for filling
    qualification gaps.
    """

    bant: BANTSignals = Field(default_factory=BANTSignals)
    meddic: MEDDICSignals = Field(default_factory=MEDDICSignals)
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    key_insights: list[str] = Field(default_factory=list)
    recommended_next_questions: list[str] = Field(default_factory=list)
    last_updated: datetime | None = None

    @property
    def combined_completion(self) -> float:
        """Average completion across BANT and MEDDIC (0.0 to 1.0)."""
        return (self.bant.completion_score + self.meddic.completion_score) / 2


# ── Conversation State ──────────────────────────────────────────────────────


class ConversationState(BaseModel):
    """Full state for a sales conversation/deal.

    Tracks everything needed to continue a conversation across interactions:
    deal stage, persona, qualification progress, interaction history,
    escalation status, and recommended next actions. This is the primary
    state object persisted between agent invocations.
    """

    state_id: str
    tenant_id: str
    account_id: str
    contact_id: str
    contact_email: str
    contact_name: str = ""
    deal_stage: DealStage = DealStage.PROSPECTING
    persona_type: PersonaType = PersonaType.MANAGER
    qualification: QualificationState = Field(default_factory=QualificationState)
    interaction_count: int = 0
    last_interaction: datetime | None = None
    last_channel: Channel | None = None
    escalated: bool = False
    escalation_reason: str | None = None
    confidence_score: float = 0.5
    next_actions: list[str] = Field(default_factory=list)
    follow_up_scheduled: datetime | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict = Field(default_factory=dict)


# ── Escalation Report ──────────────────────────────────────────────────────


class EscalationReport(BaseModel):
    """Structured handoff report for human escalation.

    Follows the locked decision format from CONTEXT.md: account context,
    deal stage, what the agent tried, why it is escalating, recommended
    next action, relevant conversation excerpts, and notification routing
    to sales rep + manager.
    """

    escalation_id: str
    tenant_id: str
    account_id: str
    contact_id: str
    contact_name: str
    deal_stage: DealStage
    escalation_trigger: str  # "confidence_low", "high_stakes", "customer_request", "complexity"
    confidence_score: float
    account_context: str
    what_agent_tried: str
    why_escalating: str
    recommended_next_action: str
    relevant_conversation_excerpts: list[str] = Field(default_factory=list)
    notification_targets: list[str] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── Next Action ─────────────────────────────────────────────────────────────


class NextAction(BaseModel):
    """A recommended next action for a sales conversation.

    Generated by the next-action recommender based on conversation state,
    qualification progress, and engagement signals.
    """

    action_type: str  # "send_email", "send_chat", "schedule_call", "escalate", "wait", "follow_up"
    description: str
    priority: str = "medium"  # "low", "medium", "high", "urgent"
    suggested_timing: str | None = None  # "within 24 hours", "next business day"
    context: str = ""  # Why this action is recommended
