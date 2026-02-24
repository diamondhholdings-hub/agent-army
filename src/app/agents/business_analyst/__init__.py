"""Business Analyst Agent for requirements gathering and analysis.

Exports:
    BusinessAnalystAgent: Core business analyst agent class.
    BA_CAPABILITIES: List of 4 typed capabilities.
    create_ba_registration: Factory for AgentRegistration.
    BAHandoffRequest, BAHandoffResponse: Inter-agent handoff payloads.
    BAResult, BATask: Task/result envelopes.
    ExtractedRequirement, CapabilityGap, RequirementContradiction: Analysis models.
    GapAnalysisResult: Complete gap analysis output.
    UserStory: Agile user story model.
    ProcessDocumentation: Current/future state process documentation.
"""

from src.app.agents.business_analyst.agent import BusinessAnalystAgent
from src.app.agents.business_analyst.capabilities import (
    BA_CAPABILITIES,
    create_ba_registration,
)
from src.app.agents.business_analyst.schemas import (
    BAHandoffRequest,
    BAHandoffResponse,
    BAResult,
    BATask,
    CapabilityGap,
    ExtractedRequirement,
    GapAnalysisResult,
    ProcessDocumentation,
    RequirementContradiction,
    UserStory,
)

__all__ = [
    "BA_CAPABILITIES",
    "BAHandoffRequest",
    "BAHandoffResponse",
    "BAResult",
    "BATask",
    "BusinessAnalystAgent",
    "CapabilityGap",
    "ExtractedRequirement",
    "GapAnalysisResult",
    "ProcessDocumentation",
    "RequirementContradiction",
    "UserStory",
    "create_ba_registration",
]
