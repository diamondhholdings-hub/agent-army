"""Pydantic data models for the Collections Agent domain.

Defines all structured types used across the Collections agent: AR aging
reports, payment risk signals, escalation state tracking, collection message
generation, payment plan surfacing, inter-agent handoff payloads, and action
result models. These models are the foundational types that every Collections
capability handler, payment risk scorer, Notion adapter, and scheduler depends
on.

The collections_risk field is also added to CSMHealthSignals (in
src/app/agents/customer_success/schemas.py) to enable cross-agent health
integration: Collections risk feeds into CSM health scoring.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# -- AR Aging -----------------------------------------------------------------


class ARAgingBucket(BaseModel):
    """One aging period in an AR aging report.

    Attributes:
        bucket_label: The aging bucket this entry covers.
        invoice_count: Number of invoices in this bucket.
        total_amount_usd: Total dollar amount outstanding in this bucket.
        oldest_invoice_date: Date of the oldest invoice in this bucket.
        oldest_invoice_number: Invoice number of the oldest invoice in this
            bucket.
    """

    bucket_label: Literal["0-30", "31-60", "61-90", "90+"]
    invoice_count: int = Field(ge=0)
    total_amount_usd: float = Field(ge=0.0)
    oldest_invoice_date: date
    oldest_invoice_number: str


class ARAgingReport(BaseModel):
    """Full AR picture for a single account.

    Aggregates all aging buckets with a summary view of total outstanding
    balance, oldest outstanding invoice, and computed timestamp.

    Attributes:
        account_id: Account this AR aging report belongs to.
        account_name: Human-readable account name.
        total_outstanding_usd: Sum of all outstanding invoice amounts.
        buckets: Aging breakdown across all four standard buckets.
        oldest_invoice_number: Invoice number of the oldest unpaid invoice.
        oldest_invoice_amount_usd: Dollar amount of the oldest unpaid invoice.
        oldest_invoice_date: Due date of the oldest unpaid invoice.
        computed_at: UTC timestamp when this report was computed.
    """

    account_id: str
    account_name: str
    total_outstanding_usd: float = Field(ge=0.0)
    buckets: list[ARAgingBucket]
    oldest_invoice_number: str
    oldest_invoice_amount_usd: float = Field(ge=0.0)
    oldest_invoice_date: date
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# -- Payment Risk -------------------------------------------------------------


class PaymentRiskSignals(BaseModel):
    """Input signals for payment risk scoring across 4 primary dimensions.

    The four scoring dimensions carry different weights in the risk scorer.
    ``days_overdue`` is the primary signal with the strongest weight.
    ``arr_usd`` and ``tenure_years`` are tone modifiers only — they adjust
    message tone but do not factor into the numeric risk score.

    Attributes:
        account_id: Account being assessed.
        days_overdue: Days the oldest invoice is past due (primary signal,
            strongest weight).
        payment_history_streak: Consecutive payment behavior; positive =
            consecutive on-time payments, negative = consecutive late
            payments. Range: -12 to +12.
        total_outstanding_balance_usd: Total dollar amount currently overdue.
        days_to_renewal: Calendar days until contract renewal (0 = renewal
            today or past due).
        arr_usd: Annual recurring revenue in USD. Used for tone modifier
            only — not included in risk score.
        tenure_years: Customer tenure in years. Used for tone modifier
            only — not included in risk score.
    """

    account_id: str
    days_overdue: int = Field(ge=0)
    payment_history_streak: int
    total_outstanding_balance_usd: float = Field(ge=0.0)
    days_to_renewal: int = Field(ge=0)
    arr_usd: float = Field(ge=0.0, default=0.0)
    tenure_years: float = Field(ge=0.0, default=0.0)


class PaymentRiskResult(BaseModel):
    """Output of the payment risk scorer for a single account.

    Combines a numeric risk score (higher = more risk, inverted from CSM
    health scoring) with a RAG status, auto-computed escalation flag,
    per-dimension score breakdown, and an LLM-generated narrative.

    The ``should_escalate`` flag is auto-computed via model_validator:
    True when ``score >= 60.0``.

    Attributes:
        account_id: Account this risk assessment belongs to.
        score: Numeric payment risk score (0-100, higher = more risk).
        rag: Risk RAG status derived from score thresholds.
        should_escalate: Auto-computed flag -- True when score >= 60.
        score_breakdown: Per-dimension contribution to the overall score.
        narrative: Human-readable risk narrative filled by LLM handler;
            empty string from the scorer.
        computed_at: UTC timestamp when this result was computed.
    """

    account_id: str
    score: float = Field(ge=0.0, le=100.0)
    rag: Literal["GREEN", "AMBER", "RED", "CRITICAL"]
    should_escalate: bool = False
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    narrative: str = ""
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def _compute_escalate_flag(self) -> PaymentRiskResult:
        """Auto-set should_escalate when risk score reaches escalation threshold.

        Triggers:
        1. Score >= 60.0 (moderate-to-high payment risk requiring action)
        """
        self.should_escalate = self.score >= 60.0
        return self


# -- Escalation State ---------------------------------------------------------

# Type alias for escalation stage values (0=not started, 5=human handoff terminal).
EscalationStage = Literal[0, 1, 2, 3, 4, 5]


class EscalationState(BaseModel):
    """Per-account escalation persistence tracking collection stage progression.

    Tracks which escalation stage an account is currently in, when stages
    were entered, message counts, and the two reset signals (payment received,
    response received).

    Stage semantics:
        0: Not started (no collection action taken)
        1-4: Progressively escalating collection outreach stages
        5: Human handoff (terminal stage — rep takes over)

    Attributes:
        account_id: Account this escalation state belongs to.
        current_stage: Active escalation stage (0=not started, 5=terminal).
        stage_entered_at: UTC timestamp when the current stage was entered.
        last_message_sent_at: UTC timestamp of the most recent collection
            message sent.
        messages_unanswered: Count of consecutive unanswered messages in
            the current stage.
        stage5_notified: Whether the rep has been notified of stage 5
            (human handoff) status.
        payment_received_at: UTC timestamp when payment was received and
            recorded by the rep in Notion. Resets the escalation state.
        response_received_at: UTC timestamp when a customer response was
            recorded by the rep. Resets messages_unanswered.
    """

    account_id: str
    current_stage: int = Field(ge=0, le=5, default=0)
    stage_entered_at: Optional[datetime] = None
    last_message_sent_at: Optional[datetime] = None
    messages_unanswered: int = Field(ge=0, default=0)
    stage5_notified: bool = False
    payment_received_at: Optional[datetime] = None
    response_received_at: Optional[datetime] = None


# -- Collection Messages -------------------------------------------------------


class CollectionMessageStage(BaseModel):
    """Stage-specific collection message generated for an account.

    Produced by the collection message handler for a single escalation stage.
    The tone is modulated by the tone_modifier derived from account ARR and
    tenure. Gmail draft creation is optional and tracked via draft ID.

    Attributes:
        account_id: Account this message was generated for.
        stage: Escalation stage this message targets (1-5).
        subject: Email subject line for the collection message.
        body: Email body text for the collection message.
        tone_modifier: Computed tone modifier value (0.6-1.4); higher = firmer
            tone.
        references_invoice: Invoice number cited in this message.
        references_balance_usd: Outstanding balance amount cited in this
            message.
        gmail_draft_id: Gmail draft ID if the draft was created; None
            otherwise.
        generated_at: UTC timestamp when this message was generated.
    """

    account_id: str
    stage: int = Field(ge=1, le=5)
    subject: str
    body: str
    tone_modifier: float
    references_invoice: str
    references_balance_usd: float
    gmail_draft_id: Optional[str] = None
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# -- Payment Plans ------------------------------------------------------------


class PaymentPlanOption(BaseModel):
    """One structured payment plan option for negotiation with the customer.

    Attributes:
        option_type: Category of payment arrangement being offered.
        description: Human-readable description of the plan option.
        proposed_amounts: Ordered list of payment amounts for each
            installment.
        proposed_dates: Ordered list of proposed payment dates corresponding
            to proposed_amounts.
        total_usd: Total USD across all proposed payments.
    """

    option_type: Literal[
        "installment_schedule", "partial_payment", "pay_or_suspend"
    ]
    description: str
    proposed_amounts: list[float]
    proposed_dates: list[date]
    total_usd: float


class PaymentPlanOptions(BaseModel):
    """Full payment plan surface result containing multiple structured options.

    Produced by the payment plan handler and optionally written to a Notion
    page and/or a Gmail draft for rep review.

    Attributes:
        account_id: Account these payment plan options were generated for.
        total_outstanding_usd: Total outstanding balance at time of
            generation.
        options: List of payment plan options presented to the customer.
        llm_rationale: LLM-generated rationale explaining why these options
            were proposed.
        notion_page_id: Notion page ID if the plan was written to Notion;
            None otherwise.
        gmail_draft_id: Gmail draft ID if a draft was created; None
            otherwise.
        generated_at: UTC timestamp when these options were generated.
    """

    account_id: str
    total_outstanding_usd: float
    options: list[PaymentPlanOption]
    llm_rationale: str
    notion_page_id: Optional[str] = None
    gmail_draft_id: Optional[str] = None
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# -- Handoff Request ----------------------------------------------------------


class CollectionsHandoffRequest(BaseModel):
    """Inter-agent handoff request to the Collections agent.

    Sent when Sales Agent or other agents need Collections capabilities:
    AR aging reports, payment risk assessment, collection message generation,
    escalation checks, or payment plan surfacing.

    Attributes:
        request_type: Which Collections capability to invoke.
        account_id: Target account identifier.
        stage_override: Force a specific stage message (1-5) instead of using
            the account's current escalation stage. Optional.
        metadata: Additional context from the triggering event.
    """

    request_type: Literal[
        "ar_aging_report",
        "payment_risk_assessment",
        "generate_collection_message",
        "run_escalation_check",
        "surface_payment_plan",
    ]
    account_id: str
    stage_override: Optional[int] = Field(default=None, ge=1, le=5)
    metadata: dict[str, Any] = Field(default_factory=dict)


# -- Alert Result -------------------------------------------------------------


class CollectionsAlertResult(BaseModel):
    """Result of a completed Collections agent action.

    Tracks what action was taken, the escalation stage after the action,
    and whether downstream artifacts (Gmail drafts, Notion updates) were
    successfully created.

    Attributes:
        account_id: Account the action was taken on.
        action_taken: Human-readable description of the action performed.
        stage_after: Escalation stage the account is in after the action.
        draft_created: Whether a Gmail draft was created as part of this
            action.
        notion_updated: Whether a Notion record was updated as part of this
            action.
        error: Error message if the action failed; None on success.
        completed_at: UTC timestamp when this action completed.
    """

    account_id: str
    action_taken: str
    stage_after: int = Field(ge=0, le=5)
    draft_created: bool = False
    notion_updated: bool = False
    error: Optional[str] = None
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


__all__ = [
    "ARAgingBucket",
    "ARAgingReport",
    "PaymentRiskSignals",
    "PaymentRiskResult",
    "EscalationStage",
    "EscalationState",
    "CollectionMessageStage",
    "PaymentPlanOption",
    "PaymentPlanOptions",
    "CollectionsHandoffRequest",
    "CollectionsAlertResult",
]
