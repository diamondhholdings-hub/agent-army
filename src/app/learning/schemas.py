"""Pydantic schemas for the learning and feedback domain.

Defines all structured types for outcome tracking, feedback collection,
confidence calibration, and analytics presentation. These schemas are
the API contract for the learning module -- used by services, API
endpoints, and downstream consumers (calibration, analytics, coaching).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


# -- Enums -------------------------------------------------------------------


class OutcomeStatus(str, Enum):
    """Resolution status of an outcome record."""

    PENDING = "pending"
    POSITIVE = "positive"
    NEGATIVE = "negative"
    AMBIGUOUS = "ambiguous"
    EXPIRED = "expired"


class OutcomeType(str, Enum):
    """Type of outcome being tracked."""

    EMAIL_ENGAGEMENT = "email_engagement"
    DEAL_PROGRESSION = "deal_progression"
    MEETING_OUTCOME = "meeting_outcome"
    ESCALATION_RESULT = "escalation_result"


class FeedbackTarget(str, Enum):
    """What the feedback is about."""

    MESSAGE = "message"
    DECISION = "decision"
    CONVERSATION = "conversation"


class FeedbackSource(str, Enum):
    """Where the feedback came from."""

    INLINE = "inline"
    DASHBOARD = "dashboard"


# -- Core Schemas -------------------------------------------------------------


class OutcomeRecord(BaseModel):
    """Recorded outcome for a single agent action.

    Created with status=PENDING when an agent takes an action.
    Resolved to POSITIVE/NEGATIVE/AMBIGUOUS/EXPIRED by signal detection.
    """

    outcome_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    conversation_state_id: str
    action_type: str
    action_id: str | None = None
    predicted_confidence: float
    outcome_type: str
    outcome_status: str = OutcomeStatus.PENDING.value
    outcome_score: float | None = None
    signal_source: str | None = None
    window_expires_at: datetime | None = None
    resolved_at: datetime | None = None
    metadata_json: dict = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class FeedbackEntry(BaseModel):
    """Human feedback on agent behavior.

    Supports inline reactions (rating: -1/0/1) and dashboard reviews
    (rating: 1-5). Optional comment for detailed feedback.
    """

    feedback_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    outcome_record_id: str | None = None
    conversation_state_id: str
    target_type: str
    target_id: str
    source: str
    rating: int
    comment: str | None = None
    reviewer_id: str
    reviewer_role: str
    metadata_json: dict = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class CalibrationBin(BaseModel):
    """Single bin in a per-action-type calibration curve.

    Tracks predicted confidence range vs actual outcome rate for
    one of 10 bins ([0,.1), [.1,.2), ..., [.9,1.0]).
    """

    bin_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    action_type: str
    bin_index: int
    bin_lower: float
    bin_upper: float
    sample_count: int = 0
    outcome_sum: float = 0.0
    actual_rate: float | None = None
    brier_contribution: float | None = None
    last_updated: datetime | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# -- Outcome Window -----------------------------------------------------------


class OutcomeWindow(BaseModel):
    """Time window configuration for outcome signal detection.

    Different outcome types have different detection windows:
    - Immediate (24h): email reply detection
    - Engagement (7d): meeting follow-up, engagement patterns
    - Deal progression (30d): stage advancement, deal outcomes
    """

    action_type: str
    outcome_type: str
    window_hours: int

    @classmethod
    def immediate(cls, action_type: str = "send_email") -> OutcomeWindow:
        """24-hour window for immediate signals (email replies)."""
        return cls(
            action_type=action_type,
            outcome_type=OutcomeType.EMAIL_ENGAGEMENT.value,
            window_hours=24,
        )

    @classmethod
    def engagement(cls, action_type: str = "send_email") -> OutcomeWindow:
        """7-day window for engagement signals (meeting follow-up)."""
        return cls(
            action_type=action_type,
            outcome_type=OutcomeType.MEETING_OUTCOME.value,
            window_hours=168,
        )

    @classmethod
    def deal_progression(cls, action_type: str = "qualify") -> OutcomeWindow:
        """30-day window for deal progression signals."""
        return cls(
            action_type=action_type,
            outcome_type=OutcomeType.DEAL_PROGRESSION.value,
            window_hours=720,
        )


# -- Calibration Schemas ------------------------------------------------------


class CalibrationCurve(BaseModel):
    """Calibration curve data for a single action type.

    Plots predicted confidence (midpoints) vs actual success rate
    with sample counts per bin and overall Brier score.
    """

    action_type: str
    midpoints: list[float] = Field(default_factory=list)
    actual_rates: list[float] = Field(default_factory=list)
    counts: list[int] = Field(default_factory=list)
    brier_score: float = 0.0


class CalibrationAdjustment(BaseModel):
    """Recommended confidence adjustment based on calibration analysis.

    Generated when miscalibration exceeds threshold. Indicates whether
    the agent should increase or decrease confidence for an action type,
    by how much, and why.
    """

    action_type: str
    direction: str  # "increase" or "decrease"
    magnitude: float
    old_threshold: float
    new_threshold: float
    reason: str


# -- Coaching Schemas ---------------------------------------------------------


class CoachingPattern(BaseModel):
    """A coaching insight extracted from outcome/feedback data.

    Represents a statistical correlation between agent action attributes
    and outcomes, formatted as actionable sales training insights.
    """

    pattern_id: str = Field(default_factory=lambda: str(uuid4()))
    pattern_type: str  # "time_correlation", "persona_effectiveness", "escalation_pattern", "channel_preference", "stage_insight"
    description: str  # Human-readable insight
    confidence: float  # Statistical confidence 0.0-1.0
    sample_size: int
    supporting_data: dict = Field(default_factory=dict)  # Raw data backing the pattern
    recommendation: str  # Actionable advice for sales reps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# -- API Request/Response Schemas ---------------------------------------------


class SubmitFeedbackRequest(BaseModel):
    """Request body for submitting feedback on agent behavior."""

    conversation_state_id: str
    target_type: str
    target_id: str
    source: str
    rating: int = Field(ge=-1, le=5)
    comment: str | None = None


class SubmitFeedbackResponse(BaseModel):
    """Response after recording feedback."""

    feedback_id: str
    status: str = "recorded"


class OutcomeRecordResponse(BaseModel):
    """Serialized outcome record for API responses."""

    outcome_id: str
    tenant_id: str
    conversation_state_id: str
    action_type: str
    action_id: str | None = None
    predicted_confidence: float
    outcome_type: str
    outcome_status: str
    outcome_score: float | None = None
    signal_source: str | None = None
    window_expires_at: str | None = None
    resolved_at: str | None = None
    metadata_json: dict = Field(default_factory=dict)
    created_at: str


class AnalyticsDashboardResponse(BaseModel):
    """Analytics data for a dashboard view."""

    role: str
    metrics: dict = Field(default_factory=dict)
    period: str = "last_30_days"
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class CalibrationCurveResponse(BaseModel):
    """Calibration curve data for API response."""

    action_type: str
    curve: dict = Field(default_factory=dict)
    brier_score: float = 0.0
    sample_count: int = 0
    is_calibrated: bool = False
