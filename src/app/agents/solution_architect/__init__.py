"""Solution Architect Agent for technical pre-sales interactions.

Provides the SolutionArchitectAgent (BaseAgent subclass) that handles
requirements extraction, architecture narrative generation, POC scoping,
technical objection response, and inter-agent technical handoff.

Exports:
    SolutionArchitectAgent: Core solution architect agent class.
    SA_CAPABILITIES: List of 5 typed capabilities.
    create_sa_registration: Factory for AgentRegistration.
    TechRequirement, TechnicalRequirementsDoc: Requirements extraction schemas.
    IntegrationPoint, ArchitectureNarrative: Architecture narrative schemas.
    POCDeliverable, ResourceEstimate, POCPlan: POC scoping schemas.
    Evidence, ObjectionResponse: Objection handling schemas.
    TechnicalQuestionPayload, TechnicalAnswerPayload: Handoff payload schemas.
"""

from src.app.agents.solution_architect.agent import SolutionArchitectAgent
from src.app.agents.solution_architect.capabilities import (
    SA_CAPABILITIES,
    create_sa_registration,
)
from src.app.agents.solution_architect.schemas import (
    ArchitectureNarrative,
    Evidence,
    IntegrationPoint,
    ObjectionResponse,
    POCDeliverable,
    POCPlan,
    ResourceEstimate,
    TechRequirement,
    TechnicalAnswerPayload,
    TechnicalQuestionPayload,
    TechnicalRequirementsDoc,
)

__all__ = [
    "ArchitectureNarrative",
    "Evidence",
    "IntegrationPoint",
    "ObjectionResponse",
    "POCDeliverable",
    "POCPlan",
    "ResourceEstimate",
    "SA_CAPABILITIES",
    "SolutionArchitectAgent",
    "TechRequirement",
    "TechnicalAnswerPayload",
    "TechnicalQuestionPayload",
    "TechnicalRequirementsDoc",
    "create_sa_registration",
]
