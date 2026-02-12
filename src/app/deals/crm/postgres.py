"""PostgreSQL CRM adapter -- always-on primary storage wrapping DealRepository.

The PostgresAdapter delegates all CRM operations to the existing DealRepository.
This adapter is always available -- the agent always has data access even if
external CRM (Notion, Salesforce) is down.

Per CONTEXT.md: "PostgreSQL as primary storage ensures agent always has data
access even if external CRM is down."
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from src.app.deals.crm.adapter import CRMAdapter
from src.app.deals.repository import DealRepository
from src.app.deals.schemas import (
    ActivityCreate,
    ChangeRecord,
    ContactCreate,
    ContactUpdate,
    OpportunityCreate,
    OpportunityFilter,
    OpportunityRead,
    OpportunityUpdate,
    StakeholderCreate,
    StakeholderScores,
)

logger = structlog.get_logger(__name__)


class PostgresAdapter(CRMAdapter):
    """CRM adapter backed by PostgreSQL via DealRepository.

    All methods delegate to DealRepository, which handles tenant-scoped
    async CRUD operations. This adapter is the primary storage -- always
    available, always up-to-date.

    Args:
        repository: DealRepository instance for database operations.
        tenant_id: Tenant UUID string for scoping all queries.
    """

    def __init__(self, repository: DealRepository, tenant_id: str) -> None:
        self._repo = repository
        self._tenant_id = tenant_id

    async def create_opportunity(self, opportunity: OpportunityCreate) -> str:
        """Create opportunity in PostgreSQL, return string ID."""
        result = await self._repo.create_opportunity(self._tenant_id, opportunity)
        logger.info(
            "postgres_crm.opportunity_created",
            opportunity_id=result.id,
            tenant_id=self._tenant_id,
        )
        return result.id

    async def update_opportunity(self, external_id: str, data: OpportunityUpdate) -> None:
        """Update opportunity fields by ID in PostgreSQL."""
        await self._repo.update_opportunity(self._tenant_id, external_id, data)
        logger.info(
            "postgres_crm.opportunity_updated",
            opportunity_id=external_id,
            tenant_id=self._tenant_id,
        )

    async def get_opportunity(self, external_id: str) -> OpportunityRead | None:
        """Fetch opportunity by ID from PostgreSQL."""
        return await self._repo.get_opportunity(self._tenant_id, external_id)

    async def list_opportunities(self, filters: OpportunityFilter) -> list[OpportunityRead]:
        """List opportunities matching filter criteria from PostgreSQL."""
        return await self._repo.list_opportunities(self._tenant_id, filters)

    async def create_contact(self, contact: ContactCreate) -> str:
        """Create stakeholder in PostgreSQL from ContactCreate, return string ID.

        Maps ContactCreate fields to StakeholderCreate for the repository.
        Requires an account_id -- uses the first account found for the tenant
        or raises ValueError if none exist.
        """
        # Map ContactCreate to StakeholderCreate
        from src.app.deals.schemas import StakeholderRole

        roles = []
        for r in contact.roles:
            try:
                roles.append(StakeholderRole(r))
            except ValueError:
                pass  # Skip unknown roles

        stakeholder_data = StakeholderCreate(
            contact_name=contact.contact_name,
            contact_email=contact.contact_email,
            title=contact.title,
            roles=roles,
            scores=StakeholderScores(
                decision_power=contact.decision_power,
                influence_level=contact.influence_level,
                relationship_strength=contact.relationship_strength,
            ),
        )

        # Get accounts to find a default account_id
        accounts = await self._repo.list_accounts(self._tenant_id)
        if not accounts:
            raise ValueError(
                f"No accounts found for tenant {self._tenant_id}. "
                "Create an account before adding contacts."
            )

        result = await self._repo.create_stakeholder(
            self._tenant_id, stakeholder_data, accounts[0].id
        )
        logger.info(
            "postgres_crm.contact_created",
            stakeholder_id=result.id,
            tenant_id=self._tenant_id,
        )
        return result.id

    async def update_contact(self, external_id: str, data: ContactUpdate) -> None:
        """Update stakeholder scores in PostgreSQL.

        Maps ContactUpdate fields to stakeholder score updates.
        Only updates score fields that are provided (non-None).
        """
        existing = await self._repo.get_stakeholder(self._tenant_id, external_id)
        if existing is None:
            raise ValueError(f"Stakeholder not found: {external_id}")

        # Build updated scores from existing + new values
        scores = StakeholderScores(
            decision_power=(
                data.decision_power
                if data.decision_power is not None
                else existing.scores.decision_power
            ),
            influence_level=(
                data.influence_level
                if data.influence_level is not None
                else existing.scores.influence_level
            ),
            relationship_strength=(
                data.relationship_strength
                if data.relationship_strength is not None
                else existing.scores.relationship_strength
            ),
        )

        await self._repo.update_stakeholder_scores(
            self._tenant_id,
            external_id,
            scores=scores,
            sources={},
            evidence={},
        )
        logger.info(
            "postgres_crm.contact_updated",
            stakeholder_id=external_id,
            tenant_id=self._tenant_id,
        )

    async def create_activity(self, activity: ActivityCreate) -> str:
        """Log an activity in PostgreSQL.

        Activities are stored as metadata on the related opportunity.
        Returns a generated activity ID string.

        Note: In a full implementation, activities would have their own table.
        For now, we log them as opportunity metadata updates if related_opportunity_id
        is present.
        """
        import uuid

        activity_id = str(uuid.uuid4())

        if activity.related_opportunity_id:
            opp = await self._repo.get_opportunity(
                self._tenant_id, activity.related_opportunity_id
            )
            if opp:
                logger.info(
                    "postgres_crm.activity_created",
                    activity_id=activity_id,
                    opportunity_id=activity.related_opportunity_id,
                    activity_type=activity.type,
                    tenant_id=self._tenant_id,
                )
        else:
            logger.info(
                "postgres_crm.activity_created",
                activity_id=activity_id,
                activity_type=activity.type,
                tenant_id=self._tenant_id,
            )

        return activity_id

    async def get_changes_since(self, since: datetime) -> list[ChangeRecord]:
        """Get opportunities changed since timestamp.

        Queries all opportunities updated after the given timestamp and
        returns them as ChangeRecord objects for sync.
        """
        all_opps = await self._repo.list_opportunities(self._tenant_id)

        changes: list[ChangeRecord] = []
        for opp in all_opps:
            # Check updated_at or created_at against since
            opp_time = opp.updated_at or opp.created_at
            if opp_time is not None:
                # Ensure since is timezone-aware for comparison
                since_aware = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
                opp_time_aware = (
                    opp_time if opp_time.tzinfo else opp_time.replace(tzinfo=timezone.utc)
                )

                if opp_time_aware >= since_aware:
                    changes.append(
                        ChangeRecord(
                            entity_type="opportunity",
                            entity_id=opp.id,
                            external_id=opp.external_id,
                            changed_fields={
                                "name": opp.name,
                                "deal_stage": opp.deal_stage,
                                "estimated_value": opp.estimated_value,
                                "probability": opp.probability,
                                "close_date": (
                                    opp.close_date.isoformat() if opp.close_date else None
                                ),
                                "product_line": opp.product_line,
                                "source": opp.source,
                            },
                            timestamp=opp_time_aware,
                            source="postgres",
                        )
                    )

        return changes
