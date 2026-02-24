"""Project Manager agent for project lifecycle management.

Provides the ProjectManagerAgent (BaseAgent subclass) that handles PMBOK-
compliant project planning, risk detection with auto-adjustment, scope
change management, status reporting with earned value metrics, CRM
integration via Notion, and trigger event processing.

Exports:
    ProjectManagerAgent: Core project manager agent class.
    PM_CAPABILITIES: List of 6 typed capabilities.
    create_pm_registration: Factory for AgentRegistration.
    PMScheduler: Weekly status report scheduler.
    WBSTask, WBSMilestone, WBSPhase: Work breakdown structure models.
    RiskThresholds, RiskSignal, RiskLogEntry: Risk management models.
    ProjectPlan: Complete project plan model.
    MilestoneProgress, ActionItem, EarnedValueMetrics: Reporting models.
    InternalStatusReport, ExternalStatusReport: Status report models.
    MilestoneSummary: Customer-facing milestone summary.
    PlanDelta, ScopeChangeDelta, ChangeRequest: Scope change models.
    PMTriggerEvent: Trigger event model.
    ProjectPlanHandoffPayload, StatusReportHandoffPayload,
        RiskAlertHandoffPayload: Inter-agent handoff payloads.
    calculate_earned_value, compute_milestone_progress: EV computation.
    NotionPMAdapter, render_wbs_to_notion_blocks: Notion CRM adapter.
"""

from src.app.agents.project_manager.agent import ProjectManagerAgent
from src.app.agents.project_manager.capabilities import (
    PM_CAPABILITIES,
    create_pm_registration,
)
from src.app.agents.project_manager.earned_value import (
    calculate_earned_value,
    compute_milestone_progress,
)
from src.app.agents.project_manager.notion_pm import (
    NotionPMAdapter,
    render_report_to_notion_blocks,
    render_wbs_to_notion_blocks,
)
from src.app.agents.project_manager.scheduler import PMScheduler
from src.app.agents.project_manager.schemas import (
    ActionItem,
    ChangeRequest,
    EarnedValueMetrics,
    ExternalStatusReport,
    InternalStatusReport,
    MilestoneProgress,
    MilestoneSummary,
    PlanDelta,
    PMTriggerEvent,
    ProjectPlan,
    ProjectPlanHandoffPayload,
    RiskAlertHandoffPayload,
    RiskLogEntry,
    RiskSignal,
    RiskThresholds,
    ScopeChangeDelta,
    StatusReportHandoffPayload,
    WBSMilestone,
    WBSPhase,
    WBSTask,
)

__all__ = [
    "ActionItem",
    "ChangeRequest",
    "EarnedValueMetrics",
    "ExternalStatusReport",
    "InternalStatusReport",
    "MilestoneProgress",
    "MilestoneSummary",
    "NotionPMAdapter",
    "PM_CAPABILITIES",
    "PMScheduler",
    "PMTriggerEvent",
    "PlanDelta",
    "ProjectManagerAgent",
    "ProjectPlan",
    "ProjectPlanHandoffPayload",
    "RiskAlertHandoffPayload",
    "RiskLogEntry",
    "RiskSignal",
    "RiskThresholds",
    "ScopeChangeDelta",
    "StatusReportHandoffPayload",
    "WBSMilestone",
    "WBSPhase",
    "WBSTask",
    "calculate_earned_value",
    "compute_milestone_progress",
    "create_pm_registration",
    "render_report_to_notion_blocks",
    "render_wbs_to_notion_blocks",
]
