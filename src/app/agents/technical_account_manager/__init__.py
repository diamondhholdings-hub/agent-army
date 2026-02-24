"""Technical Account Manager Agent for health monitoring and relationship management.

Exports:
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
    "CoDevOpportunity",
    "CommunicationRecord",
    "EscalationNotificationResult",
    "FeatureAdoption",
    "HealthScoreResult",
    "IntegrationStatus",
    "RelationshipProfile",
    "StakeholderProfile",
    "TAMHandoffRequest",
    "TAMHandoffResponse",
    "TAMResult",
    "TAMTask",
    "TicketSummary",
]
