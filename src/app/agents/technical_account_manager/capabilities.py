"""Agent capability declarations for the Technical Account Manager agent.

Defines the 5 typed capabilities (health_monitoring, escalation_risk_scoring,
technical_communication, relationship_profiling, opportunity_surfacing) and the
factory function for creating a TAM agent registration suitable for the
AgentRegistry.

Exports:
    TAM_CAPABILITIES: List of 5 AgentCapability declarations.
    create_tam_registration: Factory for AgentRegistration.
"""

from __future__ import annotations

from src.app.agents.base import AgentCapability, AgentRegistration
from src.app.agents.technical_account_manager.schemas import (
    CoDevOpportunity,
    EscalationNotificationResult,
    HealthScoreResult,
    RelationshipProfile,
    TAMResult,
)


TAM_CAPABILITIES: list[AgentCapability] = [
    AgentCapability(
        name="health_monitoring",
        description=(
            "Monitor technical health per account from tickets, CRM, and "
            "heartbeat signals. Computes 0-100 health score with Red/Amber/"
            "Green status."
        ),
        output_schema=HealthScoreResult,
    ),
    AgentCapability(
        name="escalation_risk_scoring",
        description=(
            "Predict escalation risk and trigger proactive outreach across "
            "4 channels (Notion, event bus, email, chat) when health "
            "deteriorates."
        ),
        output_schema=EscalationNotificationResult,
    ),
    AgentCapability(
        name="technical_communication",
        description=(
            "Generate account-tailored technical communications: escalation "
            "outreach, release notes, roadmap previews, health check-ins, and "
            "Customer Success Reviews. All created as Gmail drafts for rep "
            "review."
        ),
        output_schema=TAMResult,
    ),
    AgentCapability(
        name="relationship_profiling",
        description=(
            "Track technical relationship status per account: stakeholder "
            "maturity, integration depth, feature adoption, communication "
            "history, and customer environment."
        ),
        output_schema=RelationshipProfile,
    ),
    AgentCapability(
        name="opportunity_surfacing",
        description=(
            "Identify co-development and integration opportunities by "
            "aligning customer technical roadmap with product roadmap. "
            "Dispatches to Sales Agent via event bus."
        ),
        output_schema=CoDevOpportunity,
    ),
]


def create_tam_registration() -> AgentRegistration:
    """Create the Technical Account Manager agent registration.

    Returns:
        AgentRegistration with 5 capabilities, suitable for passing
        to AgentRegistry.register().
    """
    return AgentRegistration(
        agent_id="technical_account_manager",
        name="Technical Account Manager",
        description=(
            "Technical account management agent that monitors health metrics, "
            "predicts escalation risk, generates technical advocacy "
            "communications, tracks technical relationships, and surfaces "
            "co-dev opportunities"
        ),
        capabilities=TAM_CAPABILITIES,
        backup_agent_id=None,
        tags=[
            "tam",
            "health",
            "escalation",
            "technical",
            "account_management",
        ],
        max_concurrent_tasks=3,
    )
