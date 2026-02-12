"""Agent capability declarations for the Sales Agent.

Defines the 5 typed capabilities (email_outreach, chat_messaging,
qualification, next_action, escalation) and the factory function for
creating a Sales Agent registration suitable for the AgentRegistry.

Exports:
    SALES_AGENT_CAPABILITIES: List of 5 AgentCapability declarations.
    create_sales_registration: Factory for AgentRegistration.
"""

from __future__ import annotations

from src.app.agents.base import AgentCapability, AgentRegistration


SALES_AGENT_CAPABILITIES: list[AgentCapability] = [
    AgentCapability(
        name="email_outreach",
        description=(
            "Send contextual sales emails via Gmail, adapted to customer "
            "persona and deal stage"
        ),
    ),
    AgentCapability(
        name="chat_messaging",
        description=(
            "Send sales messages via Google Chat, adapted to customer "
            "persona and deal stage"
        ),
    ),
    AgentCapability(
        name="qualification",
        description=(
            "Execute BANT and MEDDIC qualification by extracting signals "
            "from conversations"
        ),
    ),
    AgentCapability(
        name="next_action",
        description=(
            "Recommend next sales actions based on deal state and "
            "engagement signals"
        ),
    ),
    AgentCapability(
        name="escalation",
        description=(
            "Evaluate when to escalate to human sales rep and generate "
            "structured handoff reports"
        ),
    ),
]


def create_sales_registration() -> AgentRegistration:
    """Create the Sales Agent registration for the AgentRegistry.

    Returns:
        AgentRegistration with 5 capabilities, suitable for passing
        to AgentRegistry.register().
    """
    return AgentRegistration(
        agent_id="sales_agent",
        name="Sales Agent",
        description=(
            "Enterprise sales agent that conducts text-based interactions "
            "via email and chat, executes BANT/MEDDIC qualification, and "
            "manages deal progression"
        ),
        capabilities=SALES_AGENT_CAPABILITIES,
        backup_agent_id=None,  # No backup for v1
        tags=["sales", "email", "chat", "qualification", "bant", "meddic"],
        max_concurrent_tasks=3,
    )
