"""Sales Agent for text-based sales interactions.

Provides the SalesAgent (BaseAgent subclass) that conducts sales conversations
via Gmail and Google Chat, adapting to customer personas, executing BANT/MEDDIC
qualification, tracking conversation state, and escalating to humans when needed.

Exports:
    SalesAgent: Core sales agent class composing all sub-components.
    NextActionEngine: Hybrid rule-based + LLM next-action recommender.
    EscalationManager: Escalation trigger evaluator and report generator.
    QualificationExtractor: LLM-powered qualification signal extraction.
    create_sales_registration: Factory for AgentRegistration.
    SALES_AGENT_CAPABILITIES: List of 5 typed capabilities.
    ConversationState, DealStage, PersonaType, Channel: Core schema types.
    BANTSignals, MEDDICSignals, QualificationState: Qualification schemas.
    EscalationReport, NextAction: Report and recommendation schemas.
"""

from src.app.agents.sales.actions import NextActionEngine
from src.app.agents.sales.agent import SalesAgent
from src.app.agents.sales.capabilities import (
    SALES_AGENT_CAPABILITIES,
    create_sales_registration,
)
from src.app.agents.sales.escalation import EscalationManager
from src.app.agents.sales.qualification import QualificationExtractor
from src.app.agents.sales.schemas import (
    BANTSignals,
    Channel,
    ConversationState,
    DealStage,
    EscalationReport,
    MEDDICSignals,
    NextAction,
    PersonaType,
    QualificationState,
)

__all__ = [
    "BANTSignals",
    "Channel",
    "ConversationState",
    "DealStage",
    "EscalationManager",
    "EscalationReport",
    "MEDDICSignals",
    "NextAction",
    "NextActionEngine",
    "PersonaType",
    "QualificationExtractor",
    "QualificationState",
    "SALES_AGENT_CAPABILITIES",
    "SalesAgent",
    "create_sales_registration",
]
