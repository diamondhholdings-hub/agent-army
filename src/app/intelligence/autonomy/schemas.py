"""Autonomy engine, guardrails, and goal tracking schemas.

Defines the types for autonomous actions, guardrail checks,
approval workflows, revenue/activity goals, and performance
metrics. Used by the AutonomyEngine and GuardrailChecker to
gate agent actions by approval level.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ActionCategory(str, enum.Enum):
    """Classification of actions by approval requirement.

    autonomous: Agent can execute without human approval.
    approval_required: Agent must get human approval before executing.
    hard_stop: Action is never allowed autonomously.
    """

    autonomous = "autonomous"
    approval_required = "approval_required"
    hard_stop = "hard_stop"


class AutonomyAction(BaseModel):
    """A proposed autonomous action by the agent.

    Represents an action the agent wants to take (e.g., send
    follow-up email, schedule meeting). Each action is checked
    against guardrails before execution.
    """

    model_config = ConfigDict(from_attributes=True)

    action_id: str = Field(
        ...,
        description="Unique action identifier",
    )
    tenant_id: str = Field(
        ...,
        description="Tenant identifier",
    )
    action_type: str = Field(
        ...,
        description="Type of action: send_follow_up_email, schedule_meeting, etc.",
    )
    account_id: str = Field(
        ...,
        description="Target account for this action",
    )
    deal_stage: Optional[str] = Field(
        default=None,
        description="Current deal stage context (for stage-gated guardrails)",
    )
    rationale: str = Field(
        ...,
        description="Agent's reasoning for proposing this action",
    )
    proposed_at: datetime = Field(
        ...,
        description="When the action was proposed (UTC)",
    )
    executed_at: Optional[datetime] = Field(
        default=None,
        description="When the action was executed (None if pending/blocked)",
    )


class GuardrailResult(BaseModel):
    """Result of a guardrail check on a proposed action.

    Determines whether an action can proceed autonomously,
    needs human approval, or is blocked entirely.
    """

    model_config = ConfigDict(from_attributes=True)

    allowed: bool = Field(
        ...,
        description="Whether the action is allowed to proceed",
    )
    reason: str = Field(
        ...,
        description="Reason for the decision: autonomous, approval_required, hard_stop, stage_gate, unknown_action",
    )
    requires_human: bool = Field(
        default=False,
        description="Whether a human must approve this action",
    )
    action: AutonomyAction = Field(
        ...,
        description="The action that was checked",
    )


class ApprovalRequest(BaseModel):
    """A pending approval request for an action requiring human sign-off.

    Created when GuardrailChecker determines an action needs approval.
    Tracks the request lifecycle from creation through resolution.
    """

    model_config = ConfigDict(from_attributes=True)

    action_id: str = Field(
        ...,
        description="Associated action identifier",
    )
    tenant_id: str = Field(
        ...,
        description="Tenant identifier",
    )
    action: AutonomyAction = Field(
        ...,
        description="The action awaiting approval",
    )
    requested_at: datetime = Field(
        ...,
        description="When the approval was requested (UTC)",
    )
    resolved_at: Optional[datetime] = Field(
        default=None,
        description="When the approval was resolved",
    )
    approved: Optional[bool] = Field(
        default=None,
        description="Whether the action was approved (None if pending)",
    )
    resolved_by: Optional[str] = Field(
        default=None,
        description="User ID of the person who resolved the request",
    )


class GoalType(str, enum.Enum):
    """Categories of measurable sales goals."""

    pipeline = "pipeline"
    activity = "activity"
    quality = "quality"
    revenue = "revenue"


class Goal(BaseModel):
    """A revenue, pipeline, or activity target.

    Goals define measurable targets for the agent to pursue.
    They track progress from current_value toward target_value
    within a defined time period.
    """

    model_config = ConfigDict(from_attributes=True)

    goal_id: str = Field(
        ...,
        description="Unique goal identifier",
    )
    tenant_id: str = Field(
        ...,
        description="Tenant identifier",
    )
    clone_id: Optional[str] = Field(
        default=None,
        description="Clone identifier (None for tenant-wide goal)",
    )
    goal_type: GoalType = Field(
        ...,
        description="Category of goal",
    )
    target_value: float = Field(
        ...,
        gt=0,
        description="Target value to achieve (must be positive)",
    )
    current_value: float = Field(
        default=0.0,
        description="Current progress toward the target",
    )
    period_start: datetime = Field(
        ...,
        description="Start of the goal period (UTC)",
    )
    period_end: datetime = Field(
        ...,
        description="End of the goal period (UTC)",
    )
    status: str = Field(
        default="active",
        description="Goal status: active, completed, missed",
    )


class PerformanceMetrics(BaseModel):
    """Current performance snapshot for a clone or tenant.

    Aggregated metrics used for goal tracking, performance
    dashboards, and autonomous action prioritization.
    """

    model_config = ConfigDict(from_attributes=True)

    tenant_id: str = Field(
        ...,
        description="Tenant identifier",
    )
    clone_id: Optional[str] = Field(
        default=None,
        description="Clone identifier (None for tenant-wide metrics)",
    )
    pipeline_value: float = Field(
        default=0.0,
        description="Total value of deals in pipeline",
    )
    activity_count: int = Field(
        default=0,
        description="Number of activities (emails, meetings, etc.) in period",
    )
    quality_score: Optional[float] = Field(
        default=None,
        description="Qualification quality score (0.0-1.0, None if not enough data)",
    )
    revenue_closed: float = Field(
        default=0.0,
        description="Total revenue from closed-won deals in period",
    )
    as_of: datetime = Field(
        ...,
        description="Timestamp of this metrics snapshot (UTC)",
    )
