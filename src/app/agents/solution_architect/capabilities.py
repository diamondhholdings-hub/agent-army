"""Agent capability declarations for the Solution Architect agent.

Defines the 5 typed capabilities (map_requirements, generate_architecture,
scope_poc, respond_objection, technical_handoff) and the factory function
for creating a Solution Architect agent registration suitable for the
AgentRegistry.

Exports:
    SA_CAPABILITIES: List of 5 AgentCapability declarations.
    create_sa_registration: Factory for AgentRegistration.
"""

from __future__ import annotations

from src.app.agents.base import AgentCapability, AgentRegistration
from src.app.agents.solution_architect.schemas import (
    ArchitectureNarrative,
    ObjectionResponse,
    POCPlan,
    TechnicalAnswerPayload,
    TechnicalRequirementsDoc,
)


SA_CAPABILITIES: list[AgentCapability] = [
    AgentCapability(
        name="map_requirements",
        description=(
            "Extract structured technical requirements from sales call "
            "transcripts, classifying by category and priority"
        ),
        output_schema=TechnicalRequirementsDoc,
    ),
    AgentCapability(
        name="generate_architecture",
        description=(
            "Generate architecture narratives describing how our solution "
            "integrates with a prospect's technology stack"
        ),
        output_schema=ArchitectureNarrative,
    ),
    AgentCapability(
        name="scope_poc",
        description=(
            "Create POC plans with deliverables, timelines, resource "
            "estimates, and success criteria based on technical requirements"
        ),
        output_schema=POCPlan,
    ),
    AgentCapability(
        name="respond_objection",
        description=(
            "Craft evidence-grounded responses to technical objections "
            "and competitive challenges using knowledge base content"
        ),
        output_schema=ObjectionResponse,
    ),
    AgentCapability(
        name="technical_handoff",
        description=(
            "Answer technical questions from the Sales Agent with "
            "sales-ready language, supporting the SA-to-Sales handoff flow"
        ),
        output_schema=TechnicalAnswerPayload,
    ),
]


def create_sa_registration() -> AgentRegistration:
    """Create the Solution Architect agent registration for the AgentRegistry.

    Returns:
        AgentRegistration with 5 capabilities, suitable for passing
        to AgentRegistry.register().
    """
    return AgentRegistration(
        agent_id="solution_architect",
        name="Solution Architect",
        description=(
            "Technical pre-sales agent that extracts requirements, generates "
            "architecture narratives, scopes POCs, handles technical objections, "
            "and answers technical questions for the sales team"
        ),
        capabilities=SA_CAPABILITIES,
        backup_agent_id=None,
        tags=["technical", "architecture", "poc", "pre-sales"],
        max_concurrent_tasks=3,
    )
