"""Pydantic data models for the Customer Success Manager agent domain.

Defines all structured types used across the CSM agent: health signals,
health scoring, churn risk assessment, expansion opportunities, QBR content
generation, feature adoption reporting, inter-agent handoff payloads, and
alert dispatch results. These models are the foundational types that every
CSM capability handler, prompt builder, Notion adapter, and health scorer
depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# -- Health Signals -----------------------------------------------------------


class CSMHealthSignals(BaseModel):
    """Raw health signal inputs for CSM health score computation.

    Captures all 13 signal dimensions used by the health scorer to compute
    a composite health score. Signals come from usage telemetry, CRM data,
    support systems, and TAM health assessments.

    Attributes:
        feature_adoption_rate: Fraction of available features actively used
            (0.0 to 1.0).
        usage_trend: Direction of overall product usage over the trailing
            period.
        login_frequency_days: Average days between logins, if tracked.
        days_since_last_interaction: Calendar days since last meaningful
            customer interaction (meeting, email, support ticket).
        stakeholder_engagement: Assessed engagement level of key
            stakeholders.
        nps_score: Net Promoter Score response (0-10), if collected.
        invoice_payment_status: Current invoice payment standing.
        days_to_renewal: Calendar days until contract renewal date.
        seats_utilization_rate: Ratio of active seats to purchased seats
            (0.0 to 2.0; values above 1.0 indicate over-utilization).
        open_ticket_count: Number of currently open support tickets.
        avg_ticket_sentiment: Aggregated sentiment across open tickets.
        escalation_count_90_days: Number of escalations in the trailing
            90-day window.
        tam_health_rag: TAM agent's latest RAG assessment, if available.
        collections_risk: Collections agent's latest payment risk RAG status,
            if available. Enables cross-agent health integration where
            Collections payment risk feeds into CSM health scoring.
    """

    feature_adoption_rate: float = Field(ge=0.0, le=1.0)
    usage_trend: Literal["growing", "stable", "declining", "inactive"]
    login_frequency_days: Optional[int] = None
    days_since_last_interaction: Optional[int] = None
    stakeholder_engagement: Literal["high", "medium", "low"]
    nps_score: Optional[int] = Field(default=None, ge=0, le=10)
    invoice_payment_status: Literal[
        "current", "overdue_30", "overdue_60", "overdue_90_plus"
    ]
    days_to_renewal: Optional[int] = None
    seats_utilization_rate: float = Field(ge=0.0, le=2.0)
    open_ticket_count: int = Field(ge=0, default=0)
    avg_ticket_sentiment: Literal[
        "positive", "neutral", "negative", "critical"
    ] = "neutral"
    escalation_count_90_days: int = Field(ge=0, default=0)
    tam_health_rag: Optional[Literal["GREEN", "AMBER", "RED"]] = None
    collections_risk: Optional[Literal["GREEN", "AMBER", "RED", "CRITICAL"]] = None


# -- Health Score -------------------------------------------------------------


class CSMHealthScore(BaseModel):
    """Computed health score with RAG status and alert trigger logic.

    Combines a numeric score (0-100, higher = healthier) with a derived
    RAG status and churn risk level. The ``should_alert`` flag is
    auto-computed via model_validator: True when RAG is RED or churn risk
    is high/critical.

    Attributes:
        account_id: Account this health score belongs to.
        score: Numeric health score (0-100, higher = healthier).
        rag: Red/Amber/Green status derived from score thresholds.
        should_alert: Auto-computed flag -- True when rag is RED or
            churn_risk_level is high/critical.
        churn_risk_level: Assessed churn risk severity.
        churn_triggered_by: What triggered the churn risk assessment.
        signal_breakdown: Per-signal contribution to the overall score.
        computed_at: UTC timestamp when this score was computed.
    """

    account_id: str
    score: float = Field(ge=0.0, le=100.0)
    rag: Literal["GREEN", "AMBER", "RED"]
    should_alert: bool = False
    churn_risk_level: Literal["low", "medium", "high", "critical"]
    churn_triggered_by: Optional[
        Literal["contract_proximity", "behavioral", "both"]
    ] = None
    signal_breakdown: dict[str, float] = Field(default_factory=dict)
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def _compute_alert_flag(self) -> CSMHealthScore:
        """Auto-set should_alert based on RAG status and churn risk level.

        Triggers:
        1. RAG status is RED (immediate concern)
        2. Churn risk level is high or critical (elevated churn probability)
        """
        self.should_alert = (
            self.rag == "RED"
            or self.churn_risk_level in ("high", "critical")
        )
        return self


# -- Churn Risk ---------------------------------------------------------------


class ChurnRiskResult(BaseModel):
    """Churn risk assessment result for an account.

    Produced by the churn narrative handler, combining quantitative risk
    level with a human-readable narrative explaining the assessment.

    Attributes:
        account_id: Account this churn assessment belongs to.
        churn_risk_level: Assessed churn risk severity.
        churn_triggered_by: What triggered the churn risk assessment.
        churn_narrative: Human-readable explanation of the churn risk
            factors and recommended actions.
        days_to_renewal: Calendar days until contract renewal, if known.
        health_rag: Current RAG status at time of assessment.
        created_at: UTC timestamp when this assessment was produced.
    """

    account_id: str
    churn_risk_level: Literal["low", "medium", "high", "critical"]
    churn_triggered_by: Optional[
        Literal["contract_proximity", "behavioral", "both"]
    ] = None
    churn_narrative: str = ""
    days_to_renewal: Optional[int] = None
    health_rag: Literal["GREEN", "AMBER", "RED"]
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# -- Expansion Opportunity ----------------------------------------------------


class ExpansionOpportunity(BaseModel):
    """An expansion opportunity identified for an account.

    Surfaced by the CSM agent when usage patterns, seat utilization, or
    feature adoption signals indicate upsell or cross-sell potential.

    Attributes:
        account_id: Account this opportunity belongs to.
        opportunity_type: Category of expansion opportunity.
        evidence: Description of the signals that surfaced this opportunity.
        estimated_arr_impact: Estimated annual recurring revenue impact in
            dollars, if calculable.
        recommended_talk_track: Suggested conversation approach for the
            account rep.
        confidence: Confidence level in this opportunity assessment.
        created_at: UTC timestamp when this opportunity was identified.
    """

    account_id: str
    opportunity_type: Literal["seats", "module", "integration"]
    evidence: str
    estimated_arr_impact: Optional[float] = None
    recommended_talk_track: str
    confidence: Literal["low", "medium", "high"] = "medium"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# -- QBR Content --------------------------------------------------------------


class QBRContent(BaseModel):
    """Quarterly Business Review content generated for an account.

    Structured QBR material covering health summary, ROI metrics, feature
    adoption scorecard, and expansion next steps. Triggered quarterly or
    by contract proximity.

    Attributes:
        account_id: Account this QBR was generated for.
        period: Review period label (e.g., "Q1 2026", "2026-01 to 2026-03").
        health_summary: Narrative summary of account health over the period.
        roi_metrics: Key ROI metrics with values (e.g., {"time_saved_hours": 120}).
        feature_adoption_scorecard: Per-feature adoption data
            (e.g., {"feature_x": {"adopted": True, "usage_pct": 0.85}}).
        expansion_next_steps: Ordered list of recommended expansion actions.
        generated_at: UTC timestamp when this QBR was generated.
        trigger: What triggered this QBR generation.
    """

    account_id: str
    period: str
    health_summary: str
    roi_metrics: dict[str, Any] = Field(default_factory=dict)
    feature_adoption_scorecard: dict[str, Any] = Field(default_factory=dict)
    expansion_next_steps: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    trigger: Literal["quarterly", "contract_proximity"]


# -- Feature Adoption Report --------------------------------------------------


class FeatureAdoptionReport(BaseModel):
    """Feature adoption analysis report for an account.

    Details which features are in use, which are underutilized, and
    provides recommendations for improving adoption. Optionally includes
    benchmark comparisons against similar accounts.

    Attributes:
        account_id: Account this report was generated for.
        features_used: List of actively used feature names.
        adoption_rate: Overall feature adoption rate (0.0 to 1.0).
        underutilized_features: Features available but not fully adopted.
        recommendations: Ordered list of adoption improvement recommendations.
        benchmark_comparison: Optional per-feature benchmark data
            (e.g., {"feature_x": 0.75} meaning 75th percentile).
        generated_at: UTC timestamp when this report was generated.
    """

    account_id: str
    features_used: list[str] = Field(default_factory=list)
    adoption_rate: float = Field(ge=0.0, le=1.0)
    underutilized_features: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    benchmark_comparison: Optional[dict[str, float]] = None
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# -- Handoff Request ----------------------------------------------------------


class CSMHandoffRequest(BaseModel):
    """Handoff request to the CSM agent from Sales Agent or other agents.

    Sent when another agent needs CSM capabilities: health scanning,
    QBR generation, expansion checking, or feature adoption tracking.

    Attributes:
        task_type: Which CSM capability to invoke.
        account_id: Target account identifier.
        tenant_id: Tenant context for multi-tenant isolation.
        context: Additional context from the triggering event.
        priority: Execution priority for queue ordering.
    """

    task_type: Literal[
        "health_scan",
        "generate_qbr",
        "check_expansion",
        "track_feature_adoption",
    ]
    account_id: str
    tenant_id: str
    context: dict = Field(default_factory=dict)
    priority: Literal["normal", "high", "urgent"] = "normal"


# -- Alert Result -------------------------------------------------------------


class CSMAlertResult(BaseModel):
    """Result of dispatching CSM alerts across notification channels.

    Tracks which notification channels (Notion, event bus, email, chat)
    succeeded or failed during alert dispatch.

    Attributes:
        account_id: Account the alert was triggered for.
        channels: Per-channel success status
            (e.g., {"notion": True, "email": False}).
        draft_id: Gmail draft ID for the alert communication, if created.
        alerts_sent: Total number of channels that successfully dispatched.
    """

    account_id: str
    channels: dict[str, bool] = Field(default_factory=dict)
    draft_id: Optional[str] = None
    alerts_sent: int = 0


__all__ = [
    "CSMHealthSignals",
    "CSMHealthScore",
    "ChurnRiskResult",
    "ExpansionOpportunity",
    "QBRContent",
    "FeatureAdoptionReport",
    "CSMHandoffRequest",
    "CSMAlertResult",
]
