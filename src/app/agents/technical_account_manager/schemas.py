"""Pydantic data models for the Technical Account Manager agent domain.

Defines all structured types used across the TAM agent: health scoring,
relationship profiling, ticket summaries, communication records,
co-development opportunities, escalation notifications, and inter-agent
handoff payloads. These models are the foundational types that every TAM
capability handler, prompt builder, Notion adapter, and health scorer
depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# ── Ticket Data ──────────────────────────────────────────────────────────


class TicketSummary(BaseModel):
    """Normalized ticket data from any support system (Kayako/Jira).

    Provides a unified representation of support tickets regardless of
    the source system, with priority classification and age tracking
    for health score computation.

    Attributes:
        ticket_id: Unique identifier from the source ticket system.
        account_id: Account this ticket belongs to.
        priority: Severity classification (P1 highest, P4 lowest).
        status: Current lifecycle status of the ticket.
        created_at: UTC timestamp when the ticket was created.
        age_days: Number of days since ticket creation (>= 0).
        subject: Brief description of the ticket issue.
    """

    ticket_id: str
    account_id: str
    priority: Literal["P1", "P2", "P3", "P4"]
    status: Literal["open", "pending", "resolved", "closed"]
    created_at: datetime
    age_days: float = Field(ge=0.0)
    subject: str


# ── Health Scoring ───────────────────────────────────────────────────────


class HealthScoreResult(BaseModel):
    """Account health score with RAG status and escalation trigger logic.

    Combines a numeric score (0-100, higher = healthier) with a derived
    RAG status (Red/Amber/Green) for at-a-glance scanning. The
    ``should_escalate`` flag is auto-computed via model_validator based
    on score thresholds and RAG status transitions.

    Escalation triggers:
    - Score below 40 (Red threshold)
    - RAG status worsened to Red from any non-Red state
    - RAG status dropped from Green to Amber (early warning)

    Attributes:
        account_id: Account this health score belongs to.
        score: Numeric health score (0-100, higher = healthier).
        rag_status: Red/Amber/Green status derived from score.
        previous_score: Score from the prior scan, if available.
        previous_rag: RAG status from the prior scan, if available.
        p1_p2_ticket_count: Number of open P1/P2 tickets at scan time.
        oldest_p1_p2_age_days: Age in days of the oldest P1/P2 ticket.
        total_open_tickets: Total number of open tickets at scan time.
        hours_since_heartbeat: Hours since last integration heartbeat.
            None means heartbeat is not monitored (no penalty).
        should_escalate: Auto-computed flag indicating whether this
            score change should trigger escalation notifications.
        scan_timestamp: UTC timestamp when this score was computed.
    """

    account_id: str
    score: int = Field(ge=0, le=100)
    rag_status: Literal["Green", "Amber", "Red"]
    previous_score: int | None = None
    previous_rag: str | None = None
    p1_p2_ticket_count: int = 0
    oldest_p1_p2_age_days: float = 0.0
    total_open_tickets: int = 0
    hours_since_heartbeat: float | None = None
    should_escalate: bool = False
    scan_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def _compute_escalation_flag(self) -> HealthScoreResult:
        """Auto-set should_escalate based on score and RAG transitions.

        Triggers:
        1. Score < 40 (Red threshold)
        2. Previous RAG was not Red and current RAG is Red (worsened to Red)
        3. Previous RAG was Green and current RAG is Amber (early warning)
        """
        self.should_escalate = (
            self.score < 40
            or (
                self.previous_rag is not None
                and self.previous_rag != "Red"
                and self.rag_status == "Red"
            )
            or (self.previous_rag == "Green" and self.rag_status == "Amber")
        )
        return self


# ── Relationship Profile Components ──────────────────────────────────────


class StakeholderProfile(BaseModel):
    """A stakeholder within an account's technical relationship.

    Captures the stakeholder's role and technical maturity level for
    communication personalization. Maturity can be set initially by the
    rep and refined over time by the TAM agent.

    Attributes:
        name: Stakeholder's full name.
        role: Job title or functional role.
        technical_maturity: Assessed technical sophistication level.
        notes: Free-text notes about this stakeholder.
    """

    name: str
    role: str
    technical_maturity: Literal["low", "medium", "high"]
    notes: str = ""


class IntegrationStatus(BaseModel):
    """Status of a product integration for an account.

    Tracks which integrations are active and when they were established,
    used for feature adoption analysis and communication personalization.

    Attributes:
        integration_name: Name of the product integration.
        is_active: Whether the integration is currently active.
        since: Date string or "unknown" for when the integration started.
    """

    integration_name: str
    is_active: bool = True
    since: str = ""


class FeatureAdoption(BaseModel):
    """Feature adoption status for an account.

    Tracks which product features are in use and how that information
    was determined (heartbeat telemetry, ticket mentions, or manual entry).

    Attributes:
        feature_name: Name of the product feature.
        adopted: Whether the account is actively using this feature.
        source: How adoption status was determined.
    """

    feature_name: str
    adopted: bool = False
    source: Literal["heartbeat", "ticket", "manual"] = "manual"


class CommunicationRecord(BaseModel):
    """Record of a TAM communication sent to an account.

    Maintains the communication history for continuity in future
    outreach and relationship tracking.

    Attributes:
        date: Date of the communication (ISO format string).
        communication_type: Which TAM communication capability generated this.
        subject: Subject line or title of the communication.
        outcome: Rep-noted outcome after the communication was reviewed/sent.
    """

    date: str
    communication_type: Literal[
        "escalation_outreach",
        "release_notes",
        "roadmap_preview",
        "health_checkin",
        "customer_success_review",
    ]
    subject: str
    outcome: str = ""


class CoDevOpportunity(BaseModel):
    """A co-development or integration opportunity identified for an account.

    Surfaced by the TAM agent and dispatched to the Sales Agent for
    active deal follow-up when appropriate.

    Attributes:
        opportunity_name: Short name for the opportunity.
        description: Detailed description of the opportunity.
        status: Lifecycle status of the opportunity.
        dispatched_to_sales: Whether this has been sent to the Sales Agent.
    """

    opportunity_name: str
    description: str
    status: Literal["surfaced", "discussed", "in_progress", "closed"] = "surfaced"
    dispatched_to_sales: bool = False


# ── Relationship Profile ─────────────────────────────────────────────────


class RelationshipProfile(BaseModel):
    """Complete technical relationship profile for an account.

    Aggregates all relationship dimensions: stakeholders, integrations,
    feature adoption, customer environment, communication history,
    co-development opportunities, and current health status. Stored as
    a Notion sub-page under the account page.

    Attributes:
        account_id: Account this profile belongs to.
        account_name: Human-readable account name.
        stakeholders: Known stakeholder profiles with maturity assessments.
        integrations: Active product integrations.
        feature_adoption: Feature adoption status from heartbeat/tickets/manual.
        customer_environment: Known applications and systems in the customer's
            tech stack (e.g., "Salesforce", "AWS", "Kubernetes").
        communication_history: Past TAM communications with this account.
        co_dev_opportunities: Identified co-development opportunities.
        health_score: Latest numeric health score (0-100), if computed.
        health_rag: Latest RAG status, if computed.
        last_health_scan: UTC timestamp of the last health scan.
        profile_page_id: Notion sub-page ID for this relationship profile.
    """

    account_id: str
    account_name: str = ""
    stakeholders: list[StakeholderProfile] = Field(default_factory=list)
    integrations: list[IntegrationStatus] = Field(default_factory=list)
    feature_adoption: list[FeatureAdoption] = Field(default_factory=list)
    customer_environment: list[str] = Field(default_factory=list)
    communication_history: list[CommunicationRecord] = Field(default_factory=list)
    co_dev_opportunities: list[CoDevOpportunity] = Field(default_factory=list)
    health_score: int | None = None
    health_rag: str | None = None
    last_health_scan: datetime | None = None
    profile_page_id: str | None = None


# ── Escalation Notification ──────────────────────────────────────────────


class EscalationNotificationResult(BaseModel):
    """Result of dispatching escalation notifications across channels.

    Tracks which of the four notification channels (Notion, event bus,
    email alert, chat alert) succeeded or failed during escalation.

    Attributes:
        account_id: Account the escalation was triggered for.
        channels: Per-channel success status (e.g., {"notion": True, "email": False}).
        draft_id: Gmail draft ID for the escalation outreach communication.
        alerts_sent: Total number of channels that successfully dispatched.
    """

    account_id: str
    channels: dict[str, bool] = Field(default_factory=dict)
    draft_id: str | None = None
    alerts_sent: int = 0


# ── Task / Result Envelopes ──────────────────────────────────────────────


class TAMTask(BaseModel):
    """Task envelope dispatched to the TAM agent for processing.

    Specifies which TAM capability to invoke, the target account,
    and optional context data for enrichment.

    Attributes:
        task_type: Which TAM capability to execute.
        account_id: Target account identifier, if applicable.
        tenant_id: Tenant context for multi-tenant isolation.
        deal_id: Associated CRM deal identifier, if applicable.
        release_info: Release data for release_notes task type.
        profile_updates: Partial profile updates for update_relationship_profile.
        metadata: Additional context from the triggering event.
    """

    task_type: Literal[
        "health_scan",
        "escalation_outreach",
        "release_notes",
        "roadmap_preview",
        "health_checkin",
        "customer_success_review",
        "update_relationship_profile",
    ]
    account_id: str | None = None
    tenant_id: str
    deal_id: str | None = None
    release_info: dict[str, Any] = Field(default_factory=dict)
    profile_updates: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TAMResult(BaseModel):
    """Result envelope returned by the TAM agent after processing.

    Contains outputs from whichever capability was invoked, with error
    handling and confidence metadata. Uses the fail-open pattern: on
    error, returns partial=True with the error field populated.

    Attributes:
        task_type: Which TAM capability produced this result.
        health_scores: List of health scores (populated for batch health_scan).
        health_score: Single health score (populated for single-account scan).
        escalation_result: Escalation notification dispatch result.
        communication_content: Generated communication HTML content.
        communication_type: Which communication type was generated.
        draft_id: Gmail draft ID if a draft was created.
        relationship_profile: Updated relationship profile data.
        error: Error message if processing failed, None on success.
        confidence: Overall confidence in the result.
        partial: True if the result is incomplete due to error or timeout.
    """

    task_type: str
    health_scores: list[HealthScoreResult] = Field(default_factory=list)
    health_score: HealthScoreResult | None = None
    escalation_result: EscalationNotificationResult | None = None
    communication_content: str | None = None
    communication_type: str | None = None
    draft_id: str | None = None
    relationship_profile: RelationshipProfile | None = None
    error: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    partial: bool = False


# ── Inter-Agent Handoff Payloads ─────────────────────────────────────────


class TAMHandoffRequest(BaseModel):
    """Handoff request to the TAM agent from Sales Agent or other agents.

    Sent when another agent needs TAM capabilities: health reports,
    escalation alerts, or specific communication generation.

    Attributes:
        handoff_type: Classification for validation strictness routing.
        account_id: Target account identifier.
        tenant_id: Tenant context for multi-tenant isolation.
        deal_id: Associated CRM deal identifier, if applicable.
        request_type: Which TAM capability to invoke.
    """

    handoff_type: Literal["health_report", "escalation_alert"] = "health_report"
    account_id: str
    tenant_id: str
    deal_id: str | None = None
    request_type: Literal[
        "health_scan",
        "escalation_outreach",
        "release_notes",
        "roadmap_preview",
        "health_checkin",
        "customer_success_review",
    ] = "health_scan"


class TAMHandoffResponse(BaseModel):
    """Handoff response from TAM agent back to requesting agent.

    Returns the structured health, escalation, or communication results
    for the requesting agent to incorporate into its workflow.

    Attributes:
        handoff_type: Classification matching the request.
        health_score: Health score result, if applicable.
        escalation_result: Escalation notification result, if applicable.
        communication_content: Generated communication HTML content.
        recommended_next_action: Summary action for the requesting agent.
        confidence: Overall confidence in the response (0.0 to 1.0).
    """

    handoff_type: Literal["health_report", "escalation_alert"] = "health_report"
    health_score: HealthScoreResult | None = None
    escalation_result: EscalationNotificationResult | None = None
    communication_content: str | None = None
    recommended_next_action: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


__all__ = [
    "TicketSummary",
    "HealthScoreResult",
    "StakeholderProfile",
    "IntegrationStatus",
    "FeatureAdoption",
    "CommunicationRecord",
    "CoDevOpportunity",
    "RelationshipProfile",
    "EscalationNotificationResult",
    "TAMTask",
    "TAMResult",
    "TAMHandoffRequest",
    "TAMHandoffResponse",
]
