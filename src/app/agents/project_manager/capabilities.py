"""Agent capability declarations for the Project Manager agent.

Defines the 6 typed capabilities (create_project_plan, detect_risks,
adjust_plan, generate_status_report, write_crm_records, process_trigger)
and the factory function for creating a Project Manager agent registration
suitable for the AgentRegistry.

Exports:
    PM_CAPABILITIES: List of 6 AgentCapability declarations.
    create_pm_registration: Factory for AgentRegistration.
"""

from __future__ import annotations

from src.app.agents.base import AgentCapability, AgentRegistration
from src.app.agents.project_manager.schemas import (
    InternalStatusReport,
    ProjectPlan,
    ScopeChangeDelta,
)


PM_CAPABILITIES: list[AgentCapability] = [
    AgentCapability(
        name="create_project_plan",
        description=(
            "Generate a PMBOK-compliant 3-level WBS project plan from deal "
            "deliverables and SA artifacts"
        ),
        output_schema=ProjectPlan,
    ),
    AgentCapability(
        name="detect_risks",
        description=(
            "Analyze milestone progress against plan and flag predicted "
            "schedule delays"
        ),
    ),
    AgentCapability(
        name="adjust_plan",
        description=(
            "Produce a scope change delta report showing adjusted plan when "
            "scope changes are introduced"
        ),
        output_schema=ScopeChangeDelta,
    ),
    AgentCapability(
        name="generate_status_report",
        description=(
            "Generate internal and customer-facing status reports with RAG, "
            "risks, and earned value metrics"
        ),
        output_schema=InternalStatusReport,
    ),
    AgentCapability(
        name="write_crm_records",
        description=(
            "Write project plan, milestones, risk log, and status reports "
            "to Notion CRM"
        ),
    ),
    AgentCapability(
        name="process_trigger",
        description=(
            "Process trigger events (deal won, POC scoped, complex deal, "
            "manual) to initiate project planning"
        ),
    ),
]


def create_pm_registration() -> AgentRegistration:
    """Create the Project Manager agent registration for the AgentRegistry.

    Returns:
        AgentRegistration with 6 capabilities, suitable for passing
        to AgentRegistry.register().
    """
    return AgentRegistration(
        agent_id="project_manager",
        name="Project Manager",
        description=(
            "Project lifecycle management agent that creates PMBOK-compliant "
            "project plans, detects schedule risks, auto-adjusts plans on "
            "scope changes, generates status reports with earned value metrics, "
            "and integrates with CRM"
        ),
        capabilities=PM_CAPABILITIES,
        backup_agent_id=None,
        tags=["project_management", "planning", "risk", "reporting", "crm"],
        max_concurrent_tasks=3,
    )
