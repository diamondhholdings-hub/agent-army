"""Pattern recognition and insight schemas.

Defines the types for detected patterns, persisted insights,
real-time alerts, and daily digest aggregation. Used by the
PatternRecognitionEngine to communicate findings to downstream
services and the alert/notification system.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PatternType(str, enum.Enum):
    """Categories of detectable patterns across customer interactions."""

    buying_signal = "buying_signal"
    risk_indicator = "risk_indicator"
    engagement_change = "engagement_change"
    cross_account_pattern = "cross_account_pattern"


class PatternMatch(BaseModel):
    """A detected pattern from LLM-based analysis.

    Represents a single pattern detection result with confidence
    scoring, severity classification, and supporting evidence.
    Confidence must be between 0.0 and 1.0.
    """

    model_config = ConfigDict(from_attributes=True)

    pattern_type: PatternType = Field(
        ...,
        description="Category of the detected pattern",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Detection confidence score (0.0 to 1.0)",
    )
    severity: str = Field(
        default="medium",
        description="Severity level: low, medium, high, critical",
    )
    evidence: List[str] = Field(
        default_factory=list,
        description="Supporting evidence from source data (quotes, references)",
    )
    detected_at: datetime = Field(
        ...,
        description="When the pattern was detected (UTC)",
    )
    account_id: str = Field(
        ...,
        description="Account this pattern was detected in",
    )


class Insight(BaseModel):
    """A persisted pattern for human review and action.

    Represents a detected pattern that has been saved for tracking.
    Insights go through a lifecycle: pending -> acted/dismissed.
    Human feedback on insights tunes detection thresholds over time.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(
        ...,
        description="Unique insight identifier",
    )
    tenant_id: str = Field(
        ...,
        description="Tenant identifier",
    )
    pattern: PatternMatch = Field(
        ...,
        description="The detected pattern data",
    )
    status: str = Field(
        default="pending",
        description="Lifecycle status: pending, acted, dismissed",
    )
    created_at: datetime = Field(
        ...,
        description="When the insight was created (UTC)",
    )
    acted_at: Optional[datetime] = Field(
        default=None,
        description="When the insight was acted upon or dismissed",
    )


class Alert(BaseModel):
    """A real-time alert for a critical insight.

    Alerts are triggered when a high-confidence or high-severity
    pattern is detected. Delivered via SSE, email, or Slack
    depending on tenant configuration.
    """

    model_config = ConfigDict(from_attributes=True)

    insight_id: str = Field(
        ...,
        description="Associated insight identifier",
    )
    tenant_id: str = Field(
        ...,
        description="Tenant identifier",
    )
    delivered_at: Optional[datetime] = Field(
        default=None,
        description="When the alert was delivered (None if pending delivery)",
    )
    channel: str = Field(
        default="sse",
        description="Delivery channel: sse, email, slack",
    )


class DailyDigest(BaseModel):
    """Aggregated insights for a 24-hour period.

    Groups insights by account for a daily summary delivered
    to sales reps. Used for lower-priority patterns that do
    not warrant real-time alerts.
    """

    model_config = ConfigDict(from_attributes=True)

    tenant_id: str = Field(
        ...,
        description="Tenant identifier",
    )
    clone_id: Optional[str] = Field(
        default=None,
        description="Clone identifier (None for tenant-wide digest)",
    )
    period_start: datetime = Field(
        ...,
        description="Start of the digest period (UTC)",
    )
    period_end: datetime = Field(
        ...,
        description="End of the digest period (UTC)",
    )
    insights: List[Insight] = Field(
        default_factory=list,
        description="All insights in this period",
    )
    grouped_by_account: Dict[str, List[Insight]] = Field(
        default_factory=dict,
        description="Insights grouped by account_id for easy scanning",
    )
