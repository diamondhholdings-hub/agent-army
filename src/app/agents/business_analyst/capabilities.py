"""Agent capability declarations for the Business Analyst agent.

Defines the 4 typed capabilities (extract_requirements, analyze_gaps,
generate_user_stories, document_process) and the factory function for
creating a Business Analyst agent registration suitable for the
AgentRegistry.

Exports:
    BA_CAPABILITIES: List of 4 AgentCapability declarations.
    create_ba_registration: Factory for AgentRegistration.
"""

from __future__ import annotations

from src.app.agents.base import AgentCapability, AgentRegistration
from src.app.agents.business_analyst.schemas import (
    BAResult,
    GapAnalysisResult,
    ProcessDocumentation,
)


BA_CAPABILITIES: list[AgentCapability] = [
    AgentCapability(
        name="extract_requirements",
        description=(
            "Extract structured requirements from conversations, categorizing "
            "by type (functional/non-functional/constraint), MoSCoW priority, "
            "and stakeholder domain"
        ),
        output_schema=BAResult,
    ),
    AgentCapability(
        name="analyze_gaps",
        description=(
            "Compare stated requirements against product capabilities, identify "
            "coverage gaps with recommended actions, and detect requirement "
            "contradictions"
        ),
        output_schema=GapAnalysisResult,
    ),
    AgentCapability(
        name="generate_user_stories",
        description=(
            "Convert business requirements into agile user stories with "
            "acceptance criteria, story points, and dual-grouping by epic "
            "and stakeholder domain"
        ),
        output_schema=BAResult,
    ),
    AgentCapability(
        name="document_process",
        description=(
            "Produce process documentation from workflow conversations showing "
            "current state, future state, and delta"
        ),
        output_schema=ProcessDocumentation,
    ),
]


def create_ba_registration() -> AgentRegistration:
    """Create the Business Analyst agent registration for the AgentRegistry.

    Returns:
        AgentRegistration with 4 capabilities, suitable for passing
        to AgentRegistry.register().
    """
    return AgentRegistration(
        agent_id="business_analyst",
        name="Business Analyst",
        description=(
            "Requirements engineering agent that extracts requirements, "
            "performs gap analysis, generates user stories, and produces "
            "process documentation from sales conversations"
        ),
        capabilities=BA_CAPABILITIES,
        backup_agent_id=None,
        tags=[
            "requirements",
            "analysis",
            "user-stories",
            "process-docs",
            "gap-analysis",
        ],
        max_concurrent_tasks=3,
    )
