"""Deal management repository -- async CRUD for all deal entities.

Provides DealRepository with session_factory callable pattern (matching
ConversationStateRepository from Phase 4). Handles serialization between
Pydantic schemas and SQLAlchemy models for accounts, opportunities,
stakeholders, account plans, and opportunity plans.

All methods take tenant_id as first argument for tenant-scoped queries.
Plan data is serialized via Pydantic model_dump(mode="json") and
deserialized via model_validate().
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deals.models import (
    AccountModel,
    AccountPlanModel,
    OpportunityModel,
    OpportunityPlanModel,
    StakeholderModel,
)
from src.app.deals.schemas import (
    AccountCreate,
    AccountPlanData,
    AccountRead,
    OpportunityCreate,
    OpportunityFilter,
    OpportunityPlanData,
    OpportunityRead,
    OpportunityUpdate,
    StakeholderCreate,
    StakeholderRead,
    StakeholderScores,
)

logger = structlog.get_logger(__name__)


# ── Serialization Helpers ───────────────────────────────────────────────────


def _model_to_account(model: AccountModel) -> AccountRead:
    """Convert AccountModel to AccountRead schema."""
    return AccountRead(
        id=str(model.id),
        tenant_id=str(model.tenant_id),
        account_name=model.account_name,
        industry=model.industry,
        company_size=model.company_size,
        website=model.website,
        region=model.region,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _model_to_opportunity(model: OpportunityModel) -> OpportunityRead:
    """Convert OpportunityModel to OpportunityRead schema."""
    return OpportunityRead(
        id=str(model.id),
        tenant_id=str(model.tenant_id),
        account_id=str(model.account_id),
        external_id=model.external_id,
        name=model.name,
        product_line=model.product_line,
        deal_stage=model.deal_stage,
        estimated_value=model.estimated_value,
        probability=model.probability,
        close_date=model.close_date,
        detection_confidence=model.detection_confidence,
        source=model.source,
        qualification_snapshot=model.qualification_snapshot or {},
        synced_at=model.synced_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _model_to_stakeholder(model: StakeholderModel) -> StakeholderRead:
    """Convert StakeholderModel to StakeholderRead schema."""
    from src.app.deals.schemas import ScoreSource, StakeholderRole

    # Deserialize roles from JSON list of strings
    roles = []
    for r in (model.roles or []):
        try:
            roles.append(StakeholderRole(r))
        except ValueError:
            pass  # Skip unknown roles gracefully

    # Deserialize score_sources from JSON dict
    score_sources = {}
    for key, val in (model.score_sources or {}).items():
        try:
            score_sources[key] = ScoreSource(val)
        except ValueError:
            pass

    return StakeholderRead(
        id=str(model.id),
        account_id=str(model.account_id),
        contact_name=model.contact_name,
        contact_email=model.contact_email,
        title=model.title,
        roles=roles,
        scores=StakeholderScores(
            decision_power=model.decision_power or 5,
            influence_level=model.influence_level or 5,
            relationship_strength=model.relationship_strength or 3,
        ),
        score_sources=score_sources,
        score_evidence=model.score_evidence or {},
        interaction_count=model.interaction_count or 0,
        last_interaction=model.last_interaction,
        notes=model.notes,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# ── Repository ──────────────────────────────────────────────────────────────


class DealRepository:
    """Async CRUD operations for all deal management entities.

    Uses session_factory callable pattern matching ConversationStateRepository.
    All methods take tenant_id as first argument for tenant-scoped queries.

    Args:
        session_factory: Async callable that yields AsyncSession instances.
    """

    def __init__(
        self, session_factory: Callable[..., AsyncGenerator[AsyncSession, None]]
    ) -> None:
        self._session_factory = session_factory

    # ── Accounts ────────────────────────────────────────────────────────────

    async def create_account(
        self, tenant_id: str, data: AccountCreate
    ) -> AccountRead:
        """Create a new account.

        Args:
            tenant_id: Tenant UUID string.
            data: AccountCreate schema with account details.

        Returns:
            AccountRead with all persisted fields.
        """
        async for session in self._session_factory():
            model = AccountModel(
                tenant_id=uuid.UUID(tenant_id),
                account_name=data.account_name,
                industry=data.industry,
                company_size=data.company_size,
                website=data.website,
                region=data.region,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _model_to_account(model)

    async def get_account(
        self, tenant_id: str, account_id: str
    ) -> AccountRead | None:
        """Get an account by ID.

        Args:
            tenant_id: Tenant UUID string.
            account_id: Account UUID string.

        Returns:
            AccountRead if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(AccountModel).where(
                AccountModel.tenant_id == uuid.UUID(tenant_id),
                AccountModel.id == uuid.UUID(account_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_account(model)

    async def get_account_by_name(
        self, tenant_id: str, account_name: str
    ) -> AccountRead | None:
        """Get an account by name (case-sensitive).

        Args:
            tenant_id: Tenant UUID string.
            account_name: Account name to look up.

        Returns:
            AccountRead if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(AccountModel).where(
                AccountModel.tenant_id == uuid.UUID(tenant_id),
                AccountModel.account_name == account_name,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_account(model)

    async def list_accounts(self, tenant_id: str) -> list[AccountRead]:
        """List all accounts for a tenant.

        Args:
            tenant_id: Tenant UUID string.

        Returns:
            List of AccountRead objects.
        """
        async for session in self._session_factory():
            stmt = select(AccountModel).where(
                AccountModel.tenant_id == uuid.UUID(tenant_id),
            )
            result = await session.execute(stmt)
            models = result.scalars().all()
            return [_model_to_account(m) for m in models]

    # ── Opportunities ───────────────────────────────────────────────────────

    async def create_opportunity(
        self, tenant_id: str, data: OpportunityCreate
    ) -> OpportunityRead:
        """Create a new opportunity.

        Args:
            tenant_id: Tenant UUID string.
            data: OpportunityCreate schema with opportunity details.

        Returns:
            OpportunityRead with all persisted fields.
        """
        async for session in self._session_factory():
            model = OpportunityModel(
                tenant_id=uuid.UUID(tenant_id),
                account_id=uuid.UUID(data.account_id),
                name=data.name,
                product_line=data.product_line,
                deal_stage=data.deal_stage,
                estimated_value=data.estimated_value,
                close_date=data.close_date,
                detection_confidence=data.detection_confidence,
                source=data.source,
                qualification_snapshot=data.qualification_snapshot,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _model_to_opportunity(model)

    async def get_opportunity(
        self, tenant_id: str, opportunity_id: str
    ) -> OpportunityRead | None:
        """Get an opportunity by ID.

        Args:
            tenant_id: Tenant UUID string.
            opportunity_id: Opportunity UUID string.

        Returns:
            OpportunityRead if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(OpportunityModel).where(
                OpportunityModel.tenant_id == uuid.UUID(tenant_id),
                OpportunityModel.id == uuid.UUID(opportunity_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_opportunity(model)

    async def find_matching_opportunity(
        self,
        tenant_id: str,
        account_id: str,
        product_line: str | None,
        timeline_months: int = 3,
    ) -> OpportunityRead | None:
        """Find an existing opportunity that matches the given criteria.

        Used for deduplication (RESEARCH.md Pitfall 3): if discussing the
        same product line within the timeline window, update existing
        opportunity instead of creating a new one.

        Args:
            tenant_id: Tenant UUID string.
            account_id: Account UUID string.
            product_line: Product line to match (None matches any).
            timeline_months: Maximum months apart for close dates to match.

        Returns:
            OpportunityRead if a match is found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(OpportunityModel).where(
                OpportunityModel.tenant_id == uuid.UUID(tenant_id),
                OpportunityModel.account_id == uuid.UUID(account_id),
                OpportunityModel.deal_stage.notin_(["closed_won", "closed_lost"]),
            )

            if product_line is not None:
                stmt = stmt.where(
                    OpportunityModel.product_line == product_line,
                )

            result = await session.execute(stmt)
            candidates = result.scalars().all()

            if not candidates:
                return None

            # Return the most recently created matching opportunity
            # Timeline-based filtering would need close_date comparison,
            # but for simplicity we match on product_line + open status
            best = max(candidates, key=lambda m: m.created_at or datetime.min)
            return _model_to_opportunity(best)

    async def list_opportunities(
        self, tenant_id: str, filters: OpportunityFilter | None = None
    ) -> list[OpportunityRead]:
        """List opportunities for a tenant with optional filters.

        Args:
            tenant_id: Tenant UUID string.
            filters: Optional OpportunityFilter for narrowing results.

        Returns:
            List of OpportunityRead objects.
        """
        async for session in self._session_factory():
            stmt = select(OpportunityModel).where(
                OpportunityModel.tenant_id == uuid.UUID(tenant_id),
            )

            if filters is not None:
                if filters.account_id is not None:
                    stmt = stmt.where(
                        OpportunityModel.account_id == uuid.UUID(filters.account_id),
                    )
                if filters.deal_stage is not None:
                    stmt = stmt.where(
                        OpportunityModel.deal_stage == filters.deal_stage,
                    )
                if filters.source is not None:
                    stmt = stmt.where(
                        OpportunityModel.source == filters.source,
                    )

            result = await session.execute(stmt)
            models = result.scalars().all()
            return [_model_to_opportunity(m) for m in models]

    async def update_opportunity(
        self, tenant_id: str, opportunity_id: str, data: OpportunityUpdate
    ) -> OpportunityRead:
        """Update an existing opportunity.

        Args:
            tenant_id: Tenant UUID string.
            opportunity_id: Opportunity UUID string.
            data: OpportunityUpdate with fields to update.

        Returns:
            Updated OpportunityRead.

        Raises:
            ValueError: If opportunity not found.
        """
        async for session in self._session_factory():
            stmt = select(OpportunityModel).where(
                OpportunityModel.tenant_id == uuid.UUID(tenant_id),
                OpportunityModel.id == uuid.UUID(opportunity_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(
                    f"Opportunity not found: tenant={tenant_id}, id={opportunity_id}"
                )

            # Update only non-None fields
            update_data = data.model_dump(exclude_none=True)
            for key, value in update_data.items():
                if key == "account_id" and isinstance(value, str):
                    value = uuid.UUID(value)
                setattr(model, key, value)

            model.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(model)
            return _model_to_opportunity(model)

    # ── Stakeholders ────────────────────────────────────────────────────────

    async def create_stakeholder(
        self, tenant_id: str, data: StakeholderCreate, account_id: str
    ) -> StakeholderRead:
        """Create a new stakeholder.

        Args:
            tenant_id: Tenant UUID string.
            data: StakeholderCreate schema with stakeholder details.
            account_id: Account UUID string this stakeholder belongs to.

        Returns:
            StakeholderRead with all persisted fields.
        """
        async for session in self._session_factory():
            model = StakeholderModel(
                tenant_id=uuid.UUID(tenant_id),
                account_id=uuid.UUID(account_id),
                contact_name=data.contact_name,
                contact_email=data.contact_email,
                title=data.title,
                roles=[r.value for r in data.roles],
                decision_power=data.scores.decision_power,
                influence_level=data.scores.influence_level,
                relationship_strength=data.scores.relationship_strength,
                score_sources={k: v.value for k, v in data.score_sources.items()},
                score_evidence=data.score_evidence,
                notes=data.notes,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _model_to_stakeholder(model)

    async def get_stakeholder(
        self, tenant_id: str, stakeholder_id: str
    ) -> StakeholderRead | None:
        """Get a stakeholder by ID.

        Args:
            tenant_id: Tenant UUID string.
            stakeholder_id: Stakeholder UUID string.

        Returns:
            StakeholderRead if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(StakeholderModel).where(
                StakeholderModel.tenant_id == uuid.UUID(tenant_id),
                StakeholderModel.id == uuid.UUID(stakeholder_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_stakeholder(model)

    async def list_stakeholders(
        self, tenant_id: str, account_id: str
    ) -> list[StakeholderRead]:
        """List all stakeholders for an account.

        Args:
            tenant_id: Tenant UUID string.
            account_id: Account UUID string.

        Returns:
            List of StakeholderRead objects.
        """
        async for session in self._session_factory():
            stmt = select(StakeholderModel).where(
                StakeholderModel.tenant_id == uuid.UUID(tenant_id),
                StakeholderModel.account_id == uuid.UUID(account_id),
            )
            result = await session.execute(stmt)
            models = result.scalars().all()
            return [_model_to_stakeholder(m) for m in models]

    async def update_stakeholder_scores(
        self,
        tenant_id: str,
        stakeholder_id: str,
        scores: StakeholderScores,
        sources: dict[str, str],
        evidence: dict[str, str],
    ) -> StakeholderRead:
        """Update stakeholder political mapping scores.

        Args:
            tenant_id: Tenant UUID string.
            stakeholder_id: Stakeholder UUID string.
            scores: New StakeholderScores.
            sources: Dict mapping score field to ScoreSource value.
            evidence: Dict mapping score field to evidence string.

        Returns:
            Updated StakeholderRead.

        Raises:
            ValueError: If stakeholder not found.
        """
        async for session in self._session_factory():
            stmt = select(StakeholderModel).where(
                StakeholderModel.tenant_id == uuid.UUID(tenant_id),
                StakeholderModel.id == uuid.UUID(stakeholder_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(
                    f"Stakeholder not found: tenant={tenant_id}, id={stakeholder_id}"
                )

            model.decision_power = scores.decision_power
            model.influence_level = scores.influence_level
            model.relationship_strength = scores.relationship_strength

            # Merge sources and evidence (preserve existing, update new)
            existing_sources = model.score_sources or {}
            existing_sources.update(sources)
            model.score_sources = existing_sources

            existing_evidence = model.score_evidence or {}
            existing_evidence.update(evidence)
            model.score_evidence = existing_evidence

            model.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(model)
            return _model_to_stakeholder(model)

    # ── Account Plans ───────────────────────────────────────────────────────

    async def upsert_account_plan(
        self, tenant_id: str, account_id: str, plan_data: AccountPlanData
    ) -> int:
        """Create or update an account plan.

        Inserts a new plan or increments version and updates existing.
        Plan data is serialized to JSON via Pydantic model_dump(mode="json").

        Args:
            tenant_id: Tenant UUID string.
            account_id: Account UUID string.
            plan_data: AccountPlanData to persist.

        Returns:
            New version number (int).
        """
        async for session in self._session_factory():
            stmt = select(AccountPlanModel).where(
                AccountPlanModel.tenant_id == uuid.UUID(tenant_id),
                AccountPlanModel.account_id == uuid.UUID(account_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            serialized = plan_data.model_dump(mode="json")

            if model is not None:
                model.plan_data = serialized
                model.version = (model.version or 0) + 1
                model.updated_at = datetime.now(timezone.utc)
                await session.commit()
                return model.version
            else:
                new_model = AccountPlanModel(
                    tenant_id=uuid.UUID(tenant_id),
                    account_id=uuid.UUID(account_id),
                    plan_data=serialized,
                    version=1,
                )
                session.add(new_model)
                await session.commit()
                return 1

    async def get_account_plan(
        self, tenant_id: str, account_id: str
    ) -> AccountPlanData | None:
        """Get an account plan.

        Deserializes plan_data JSON back into AccountPlanData via
        model_validate().

        Args:
            tenant_id: Tenant UUID string.
            account_id: Account UUID string.

        Returns:
            AccountPlanData if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(AccountPlanModel).where(
                AccountPlanModel.tenant_id == uuid.UUID(tenant_id),
                AccountPlanModel.account_id == uuid.UUID(account_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if model is None:
                return None

            return AccountPlanData.model_validate(model.plan_data or {})

    # ── Opportunity Plans ───────────────────────────────────────────────────

    async def upsert_opportunity_plan(
        self, tenant_id: str, opportunity_id: str, plan_data: OpportunityPlanData
    ) -> int:
        """Create or update an opportunity plan.

        Inserts a new plan or increments version and updates existing.
        Plan data is serialized to JSON via Pydantic model_dump(mode="json").

        Args:
            tenant_id: Tenant UUID string.
            opportunity_id: Opportunity UUID string.
            plan_data: OpportunityPlanData to persist.

        Returns:
            New version number (int).
        """
        async for session in self._session_factory():
            stmt = select(OpportunityPlanModel).where(
                OpportunityPlanModel.tenant_id == uuid.UUID(tenant_id),
                OpportunityPlanModel.opportunity_id == uuid.UUID(opportunity_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            serialized = plan_data.model_dump(mode="json")

            if model is not None:
                model.plan_data = serialized
                model.version = (model.version or 0) + 1
                model.updated_at = datetime.now(timezone.utc)
                await session.commit()
                return model.version
            else:
                new_model = OpportunityPlanModel(
                    tenant_id=uuid.UUID(tenant_id),
                    opportunity_id=uuid.UUID(opportunity_id),
                    plan_data=serialized,
                    version=1,
                )
                session.add(new_model)
                await session.commit()
                return 1

    async def get_opportunity_plan(
        self, tenant_id: str, opportunity_id: str
    ) -> OpportunityPlanData | None:
        """Get an opportunity plan.

        Deserializes plan_data JSON back into OpportunityPlanData via
        model_validate().

        Args:
            tenant_id: Tenant UUID string.
            opportunity_id: Opportunity UUID string.

        Returns:
            OpportunityPlanData if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(OpportunityPlanModel).where(
                OpportunityPlanModel.tenant_id == uuid.UUID(tenant_id),
                OpportunityPlanModel.opportunity_id == uuid.UUID(opportunity_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if model is None:
                return None

            return OpportunityPlanData.model_validate(model.plan_data or {})
