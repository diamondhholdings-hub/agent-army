"""Plan management for account and opportunity plan lifecycle.

Generates and updates strategic account plans and tactical opportunity plans
from accumulated conversation data. Uses structured data assembly (not LLM)
per RESEARCH.md Open Question 4.

All list fields are capped to prevent unbounded growth (Pitfall 4):
- MAX_KEY_EVENTS = 50 for relationship history events
- MAX_INTERACTIONS = 20 for interaction summaries
- MAX_ACTION_ITEMS = 30 for opportunity plan action items

Plans are persisted via DealRepository using JSON columns with Pydantic
model_dump/model_validate round-trip (05-01 pattern).

Exports:
    PlanManager: Account and opportunity plan lifecycle management.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from src.app.agents.sales.schemas import ConversationState
from src.app.deals.repository import DealRepository
from src.app.deals.schemas import (
    AccountPlanData,
    ActionItem,
    CompanyProfile,
    CoreDealInfo,
    InteractionSummary,
    OpportunityPlanData,
    OpportunityRead,
    QualificationTracking,
    RelationshipHistory,
    StakeholderRead,
    StakeholderSummary,
)

logger = structlog.get_logger(__name__)


class PlanManager:
    """Manage account and opportunity plan lifecycle.

    Creates and updates strategic account plans and tactical opportunity plans
    from conversation data. Uses structured data assembly (not LLM generation)
    for plan content.

    Growth caps (RESEARCH.md Pitfall 4):
    - MAX_KEY_EVENTS: Maximum key events in relationship history
    - MAX_INTERACTIONS: Maximum interaction summaries
    - MAX_ACTION_ITEMS: Maximum action items in opportunity plan

    Args:
        repository: DealRepository instance for plan persistence.
    """

    MAX_KEY_EVENTS = 50  # Pitfall 4: prevent unbounded growth
    MAX_INTERACTIONS = 20  # Pitfall 4
    MAX_ACTION_ITEMS = 30  # Pitfall 4

    def __init__(self, repository: DealRepository) -> None:
        self._repo = repository

    async def create_or_update_account_plan(
        self,
        tenant_id: str,
        account_id: str,
        conversation_state: ConversationState,
        stakeholders: list[StakeholderRead],
    ) -> AccountPlanData:
        """Create or update an account plan from conversation data.

        Gets existing plan from repository (or creates new). Updates:
        - company_profile from conversation signals (structured assembly, not LLM)
        - relationship_history.interaction_summaries (capped at MAX_INTERACTIONS)
        - active_opportunity_ids from repository query

        Args:
            tenant_id: Tenant UUID string.
            account_id: Account UUID string.
            conversation_state: Current conversation state.
            stakeholders: List of stakeholders for this account.

        Returns:
            Updated AccountPlanData.
        """
        # Get existing plan or start fresh
        existing = await self._repo.get_account_plan(tenant_id, account_id)
        plan = existing if existing is not None else AccountPlanData()

        # Update company profile from conversation metadata
        plan.company_profile = self._update_company_profile(
            plan.company_profile, conversation_state
        )

        # Add interaction summary to relationship history
        interaction = self._build_interaction_summary(conversation_state)
        plan.relationship_history.interaction_summaries.append(interaction)
        plan.relationship_history.interaction_summaries = self._trim_list(
            plan.relationship_history.interaction_summaries, self.MAX_INTERACTIONS
        )

        # Cap key events
        plan.relationship_history.key_events = self._trim_list(
            plan.relationship_history.key_events, self.MAX_KEY_EVENTS
        )

        # Update active opportunity IDs from repository
        opportunities = await self._repo.list_opportunities(tenant_id)
        account_opps = [
            opp for opp in opportunities if opp.account_id == account_id
        ]
        plan.active_opportunity_ids = [
            opp.id
            for opp in account_opps
            if opp.deal_stage not in ("closed_won", "closed_lost")
        ]

        # Persist
        version = await self._repo.upsert_account_plan(tenant_id, account_id, plan)
        logger.info(
            "account_plan_updated",
            tenant_id=tenant_id,
            account_id=account_id,
            version=version,
            active_opportunities=len(plan.active_opportunity_ids),
            interactions=len(plan.relationship_history.interaction_summaries),
        )

        return plan

    async def create_or_update_opportunity_plan(
        self,
        tenant_id: str,
        opportunity_id: str,
        opportunity: OpportunityRead,
        conversation_state: ConversationState,
        stakeholders: list[StakeholderRead],
    ) -> OpportunityPlanData:
        """Create or update an opportunity plan from deal data.

        Gets existing plan from repository (or creates new). Updates:
        - core_deal from opportunity data (product_line, value, stage, probability, close_date)
        - qualification_tracking from conversation_state.qualification (BANT/MEDDIC snapshot)
        - stakeholder_map from stakeholders list
        - action_items (cap at MAX_ACTION_ITEMS, prune completed)

        Args:
            tenant_id: Tenant UUID string.
            opportunity_id: Opportunity UUID string.
            opportunity: Current opportunity data.
            conversation_state: Current conversation state.
            stakeholders: List of stakeholders for this deal.

        Returns:
            Updated OpportunityPlanData.
        """
        # Get existing plan or start fresh
        existing = await self._repo.get_opportunity_plan(tenant_id, opportunity_id)
        plan = existing if existing is not None else OpportunityPlanData()

        # Update core deal info from opportunity data
        plan.core_deal = CoreDealInfo(
            product_line=opportunity.product_line,
            estimated_value=opportunity.estimated_value,
            close_date=opportunity.close_date,
            probability=opportunity.probability,
            stage=opportunity.deal_stage,
            source=opportunity.source,
        )

        # Update qualification tracking from conversation state
        qual = conversation_state.qualification
        plan.qualification_tracking = QualificationTracking(
            bant_snapshot=qual.bant.model_dump(mode="json"),
            meddic_snapshot=qual.meddic.model_dump(mode="json"),
            overall_confidence=qual.overall_confidence,
            last_assessed=qual.last_updated,
        )

        # Update stakeholder map from stakeholders list
        plan.stakeholder_map = [
            StakeholderSummary(
                stakeholder_id=s.id,
                name=s.contact_name,
                roles=[r.value for r in s.roles],
                decision_power=s.scores.decision_power,
                influence_level=s.scores.influence_level,
                key_insight=s.notes or "",
            )
            for s in stakeholders
        ]

        # Prune completed action items and cap
        plan.action_items = [
            item for item in plan.action_items if item.status != "completed"
        ]
        plan.action_items = self._trim_list(plan.action_items, self.MAX_ACTION_ITEMS)

        # Persist
        version = await self._repo.upsert_opportunity_plan(
            tenant_id, opportunity_id, plan
        )
        logger.info(
            "opportunity_plan_updated",
            tenant_id=tenant_id,
            opportunity_id=opportunity_id,
            version=version,
            stage=plan.core_deal.stage,
            stakeholders=len(plan.stakeholder_map),
            action_items=len(plan.action_items),
        )

        return plan

    def _build_interaction_summary(
        self, conversation_state: ConversationState
    ) -> InteractionSummary:
        """Create a summary entry for relationship history from conversation state.

        Args:
            conversation_state: Current conversation state.

        Returns:
            InteractionSummary capturing the interaction details.
        """
        channel = (
            conversation_state.last_channel.value
            if conversation_state.last_channel
            else "unknown"
        )

        # Build summary from available state data
        stage = conversation_state.deal_stage.value
        qual_completion = conversation_state.qualification.combined_completion
        summary = (
            f"Interaction #{conversation_state.interaction_count} via {channel}. "
            f"Stage: {stage}. "
            f"Qualification: {qual_completion:.0%} complete. "
            f"Confidence: {conversation_state.confidence_score:.2f}."
        )

        return InteractionSummary(
            date=conversation_state.last_interaction or datetime.now(timezone.utc),
            channel=channel,
            summary=summary,
            sentiment="neutral",  # Could be refined with LLM in future
        )

    def _update_company_profile(
        self,
        profile: CompanyProfile,
        conversation_state: ConversationState,
    ) -> CompanyProfile:
        """Update company profile from conversation metadata.

        Structured data assembly from conversation state metadata,
        not LLM generation (per RESEARCH.md Open Question 4).

        Args:
            profile: Existing company profile.
            conversation_state: Current conversation state.

        Returns:
            Updated CompanyProfile.
        """
        metadata = conversation_state.metadata or {}

        # Update fields from metadata if present (non-destructive)
        if metadata.get("industry") and not profile.industry:
            profile.industry = metadata["industry"]
        if metadata.get("company_size") and not profile.company_size:
            profile.company_size = metadata["company_size"]
        if metadata.get("business_model") and not profile.business_model:
            profile.business_model = metadata["business_model"]

        # Extend tech stack with unique items
        new_tech = metadata.get("tech_stack", [])
        if isinstance(new_tech, list):
            existing = set(profile.tech_stack)
            for tech in new_tech:
                if tech not in existing:
                    profile.tech_stack.append(tech)
                    existing.add(tech)

        # Extend strategic initiatives with unique items
        new_initiatives = metadata.get("strategic_initiatives", [])
        if isinstance(new_initiatives, list):
            existing_init = set(profile.strategic_initiatives)
            for init in new_initiatives:
                if init not in existing_init:
                    profile.strategic_initiatives.append(init)
                    existing_init.add(init)

        return profile

    @staticmethod
    def _trim_list(items: list, max_size: int) -> list:
        """Trim list to max_size, keeping most recent items (Pitfall 4).

        Args:
            items: List to trim.
            max_size: Maximum allowed size.

        Returns:
            Trimmed list (last max_size items).
        """
        if len(items) <= max_size:
            return items
        return items[-max_size:]
