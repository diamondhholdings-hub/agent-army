"""Technical Account Manager Agent for health monitoring and escalation prediction.

Exports:
    TAMAgent: Core TAM agent class.
    TAM_CAPABILITIES: List of 5 typed capabilities.
    create_tam_registration: Factory for AgentRegistration.
    TAMTask, TAMResult: Task/result envelopes.
    HealthScoreResult: Account health score with RAG status.
    TicketSummary: Normalized support ticket data.
    StakeholderProfile: Stakeholder with technical maturity assessment.
    IntegrationStatus: Product integration status for an account.
    FeatureAdoption: Feature adoption tracking.
    CommunicationRecord: TAM communication history record.
    CoDevOpportunity: Co-development opportunity.
    RelationshipProfile: Complete account relationship profile.
    EscalationNotificationResult: Multi-channel escalation dispatch result.
    TAMHandoffRequest, TAMHandoffResponse: Inter-agent handoff payloads.
"""

from src.app.agents.technical_account_manager.agent import TAMAgent
from src.app.agents.technical_account_manager.capabilities import (
    TAM_CAPABILITIES,
    create_tam_registration,
)
from src.app.agents.technical_account_manager.schemas import (
    CoDevOpportunity,
    CommunicationRecord,
    EscalationNotificationResult,
    FeatureAdoption,
    HealthScoreResult,
    IntegrationStatus,
    RelationshipProfile,
    StakeholderProfile,
    TAMHandoffRequest,
    TAMHandoffResponse,
    TAMResult,
    TAMTask,
    TicketSummary,
)

__all__ = [
    "TAM_CAPABILITIES",
    "TAMAgent",
    "TAMHandoffRequest",
    "TAMHandoffResponse",
    "TAMResult",
    "TAMTask",
    "TicketSummary",
    "HealthScoreResult",
    "StakeholderProfile",
    "IntegrationStatus",
    "FeatureAdoption",
    "RelationshipProfile",
    "CommunicationRecord",
    "CoDevOpportunity",
    "EscalationNotificationResult",
    "create_tam_registration",
]
