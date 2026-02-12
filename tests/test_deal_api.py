"""Integration tests for deal management API endpoints.

Uses InMemoryDealRepository test double and httpx AsyncClient with app
override for deal_repository. Tests all CRUD endpoints for accounts,
opportunities, stakeholders, plans, and pipeline view.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.app.deals.schemas import (
    AccountCreate,
    AccountPlanData,
    AccountRead,
    OpportunityCreate,
    OpportunityFilter,
    OpportunityPlanData,
    OpportunityRead,
    OpportunityUpdate,
    ScoreSource,
    StakeholderCreate,
    StakeholderRead,
    StakeholderRole,
    StakeholderScores,
)


# ── In-Memory Test Double ────────────────────────────────────────────────────


class InMemoryDealRepository:
    """In-memory DealRepository for testing without database."""

    def __init__(self) -> None:
        self._accounts: dict[str, AccountRead] = {}
        self._opportunities: dict[str, OpportunityRead] = {}
        self._stakeholders: dict[str, StakeholderRead] = {}
        self._account_plans: dict[str, AccountPlanData] = {}
        self._opportunity_plans: dict[str, OpportunityPlanData] = {}

    async def create_account(self, tenant_id: str, data: AccountCreate) -> AccountRead:
        account_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        account = AccountRead(
            id=account_id,
            tenant_id=tenant_id,
            account_name=data.account_name,
            industry=data.industry,
            company_size=data.company_size,
            website=data.website,
            region=data.region,
            created_at=now,
            updated_at=now,
        )
        self._accounts[account_id] = account
        return account

    async def get_account(self, tenant_id: str, account_id: str) -> AccountRead | None:
        account = self._accounts.get(account_id)
        if account and account.tenant_id == tenant_id:
            return account
        return None

    async def get_account_by_name(self, tenant_id: str, account_name: str) -> AccountRead | None:
        for account in self._accounts.values():
            if account.tenant_id == tenant_id and account.account_name == account_name:
                return account
        return None

    async def list_accounts(self, tenant_id: str) -> list[AccountRead]:
        return [a for a in self._accounts.values() if a.tenant_id == tenant_id]

    async def create_opportunity(
        self, tenant_id: str, data: OpportunityCreate
    ) -> OpportunityRead:
        opp_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        opp = OpportunityRead(
            id=opp_id,
            tenant_id=tenant_id,
            account_id=data.account_id,
            name=data.name,
            product_line=data.product_line,
            deal_stage=data.deal_stage,
            estimated_value=data.estimated_value,
            detection_confidence=data.detection_confidence,
            source=data.source,
            qualification_snapshot=data.qualification_snapshot,
            created_at=now,
            updated_at=now,
        )
        self._opportunities[opp_id] = opp
        return opp

    async def get_opportunity(
        self, tenant_id: str, opportunity_id: str
    ) -> OpportunityRead | None:
        opp = self._opportunities.get(opportunity_id)
        if opp and opp.tenant_id == tenant_id:
            return opp
        return None

    async def find_matching_opportunity(
        self, tenant_id: str, account_id: str, product_line: str | None, timeline_months: int = 3
    ) -> OpportunityRead | None:
        for opp in self._opportunities.values():
            if (
                opp.tenant_id == tenant_id
                and opp.account_id == account_id
                and opp.deal_stage not in ("closed_won", "closed_lost")
            ):
                if product_line is None or opp.product_line == product_line:
                    return opp
        return None

    async def list_opportunities(
        self, tenant_id: str, filters: OpportunityFilter | None = None
    ) -> list[OpportunityRead]:
        result = [o for o in self._opportunities.values() if o.tenant_id == tenant_id]
        if filters:
            if filters.deal_stage:
                result = [o for o in result if o.deal_stage == filters.deal_stage]
            if filters.account_id:
                result = [o for o in result if o.account_id == filters.account_id]
            if filters.source:
                result = [o for o in result if o.source == filters.source]
        return result

    async def update_opportunity(
        self, tenant_id: str, opportunity_id: str, data: OpportunityUpdate
    ) -> OpportunityRead:
        opp = self._opportunities.get(opportunity_id)
        if opp is None or opp.tenant_id != tenant_id:
            raise ValueError(f"Opportunity not found: {opportunity_id}")
        update_data = data.model_dump(exclude_none=True)
        opp_dict = opp.model_dump()
        opp_dict.update(update_data)
        opp_dict["updated_at"] = datetime.now(timezone.utc)
        updated = OpportunityRead(**opp_dict)
        self._opportunities[opportunity_id] = updated
        return updated

    async def create_stakeholder(
        self, tenant_id: str, data: StakeholderCreate, account_id: str
    ) -> StakeholderRead:
        sh_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        stakeholder = StakeholderRead(
            id=sh_id,
            account_id=account_id,
            contact_name=data.contact_name,
            contact_email=data.contact_email,
            title=data.title,
            roles=data.roles,
            scores=data.scores,
            score_sources=data.score_sources,
            score_evidence=data.score_evidence,
            notes=data.notes,
            created_at=now,
            updated_at=now,
        )
        self._stakeholders[sh_id] = stakeholder
        return stakeholder

    async def get_stakeholder(
        self, tenant_id: str, stakeholder_id: str
    ) -> StakeholderRead | None:
        return self._stakeholders.get(stakeholder_id)

    async def list_stakeholders(
        self, tenant_id: str, account_id: str
    ) -> list[StakeholderRead]:
        return [
            s for s in self._stakeholders.values() if s.account_id == account_id
        ]

    async def update_stakeholder_scores(
        self,
        tenant_id: str,
        stakeholder_id: str,
        scores: StakeholderScores,
        sources: dict[str, str],
        evidence: dict[str, str],
    ) -> StakeholderRead:
        s = self._stakeholders.get(stakeholder_id)
        if s is None:
            raise ValueError(f"Stakeholder not found: {stakeholder_id}")
        s_dict = s.model_dump()
        s_dict["scores"] = scores
        # Merge sources and evidence
        existing_sources = dict(s.score_sources)
        for k, v in sources.items():
            try:
                existing_sources[k] = ScoreSource(v)
            except ValueError:
                pass
        s_dict["score_sources"] = existing_sources
        existing_evidence = dict(s.score_evidence)
        existing_evidence.update(evidence)
        s_dict["score_evidence"] = existing_evidence
        s_dict["updated_at"] = datetime.now(timezone.utc)
        updated = StakeholderRead(**s_dict)
        self._stakeholders[stakeholder_id] = updated
        return updated

    async def upsert_account_plan(
        self, tenant_id: str, account_id: str, plan_data: AccountPlanData
    ) -> int:
        key = f"{tenant_id}:{account_id}"
        self._account_plans[key] = plan_data
        return 1

    async def get_account_plan(
        self, tenant_id: str, account_id: str
    ) -> AccountPlanData | None:
        return self._account_plans.get(f"{tenant_id}:{account_id}")

    async def upsert_opportunity_plan(
        self, tenant_id: str, opportunity_id: str, plan_data: OpportunityPlanData
    ) -> int:
        key = f"{tenant_id}:{opportunity_id}"
        self._opportunity_plans[key] = plan_data
        return 1

    async def get_opportunity_plan(
        self, tenant_id: str, opportunity_id: str
    ) -> OpportunityPlanData | None:
        return self._opportunity_plans.get(f"{tenant_id}:{opportunity_id}")


# ── Test Fixtures ────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())


def _make_mock_app():
    """Create a minimal FastAPI app with mocked auth for testing deals API."""
    from fastapi import FastAPI

    from src.app.api.v1.deals import router

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    return app


def _mock_get_current_user():
    """Return a mock user for auth bypass."""
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.tenant_id = TENANT_ID
    mock_user.is_active = True
    mock_user.role = "admin"
    return mock_user


def _mock_get_tenant():
    """Return a mock tenant context."""
    mock_tenant = MagicMock()
    mock_tenant.tenant_id = TENANT_ID
    return mock_tenant


@pytest_asyncio.fixture
async def client_and_repo():
    """Create test client with InMemoryDealRepository and mocked auth."""
    from src.app.api.deps import get_current_user, get_tenant

    app = _make_mock_app()
    repo = InMemoryDealRepository()

    # Override dependencies
    app.dependency_overrides[get_current_user] = _mock_get_current_user
    app.dependency_overrides[get_tenant] = _mock_get_tenant

    # Set deal_repository on app.state
    app.state.deal_repository = repo

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, repo


# ── Account Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_account(client_and_repo):
    """POST /v1/deals/accounts -> 201 with account data."""
    client, repo = client_and_repo

    response = await client.post(
        "/v1/deals/accounts",
        json={"account_name": "Acme Corp", "industry": "Technology"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["account_name"] == "Acme Corp"
    assert data["industry"] == "Technology"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_accounts(client_and_repo):
    """GET /v1/deals/accounts -> 200 with list."""
    client, repo = client_and_repo

    # Create two accounts
    await client.post("/v1/deals/accounts", json={"account_name": "Acme Corp"})
    await client.post("/v1/deals/accounts", json={"account_name": "Beta Inc"})

    response = await client.get("/v1/deals/accounts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = {a["account_name"] for a in data}
    assert names == {"Acme Corp", "Beta Inc"}


@pytest.mark.asyncio
async def test_get_account_not_found(client_and_repo):
    """GET /v1/deals/accounts/{bad_id} -> 404."""
    client, repo = client_and_repo

    response = await client.get(f"/v1/deals/accounts/{uuid.uuid4()}")
    assert response.status_code == 404


# ── Opportunity Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_opportunity(client_and_repo):
    """POST /v1/deals/opportunities -> 201."""
    client, repo = client_and_repo

    # Create an account first
    acc_resp = await client.post("/v1/deals/accounts", json={"account_name": "Acme"})
    account_id = acc_resp.json()["id"]

    response = await client.post(
        "/v1/deals/opportunities",
        json={
            "account_id": account_id,
            "name": "Enterprise Deal",
            "product_line": "Platform",
            "estimated_value": 50000.0,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Enterprise Deal"
    assert data["estimated_value"] == 50000.0


@pytest.mark.asyncio
async def test_list_opportunities_filter_by_stage(client_and_repo):
    """GET /v1/deals/opportunities?stage=discovery -> filtered list."""
    client, repo = client_and_repo

    acc_resp = await client.post("/v1/deals/accounts", json={"account_name": "Acme"})
    account_id = acc_resp.json()["id"]

    # Create opps in different stages
    await client.post(
        "/v1/deals/opportunities",
        json={"account_id": account_id, "name": "Opp A", "deal_stage": "discovery"},
    )
    await client.post(
        "/v1/deals/opportunities",
        json={"account_id": account_id, "name": "Opp B", "deal_stage": "negotiation"},
    )

    response = await client.get("/v1/deals/opportunities?stage=discovery")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Opp A"


@pytest.mark.asyncio
async def test_get_opportunity_not_found(client_and_repo):
    """GET /v1/deals/opportunities/{bad_id} -> 404."""
    client, repo = client_and_repo

    response = await client.get(f"/v1/deals/opportunities/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_opportunity(client_and_repo):
    """PATCH /v1/deals/opportunities/{id} -> 200 with updated fields."""
    client, repo = client_and_repo

    acc_resp = await client.post("/v1/deals/accounts", json={"account_name": "Acme"})
    account_id = acc_resp.json()["id"]

    opp_resp = await client.post(
        "/v1/deals/opportunities",
        json={"account_id": account_id, "name": "Deal 1"},
    )
    opp_id = opp_resp.json()["id"]

    response = await client.patch(
        f"/v1/deals/opportunities/{opp_id}",
        json={"estimated_value": 75000.0, "deal_stage": "qualification"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["estimated_value"] == 75000.0
    assert data["deal_stage"] == "qualification"


# ── Stakeholder Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_stakeholder(client_and_repo):
    """POST /v1/deals/accounts/{id}/stakeholders -> 201."""
    client, repo = client_and_repo

    acc_resp = await client.post("/v1/deals/accounts", json={"account_name": "Acme"})
    account_id = acc_resp.json()["id"]

    response = await client.post(
        f"/v1/deals/accounts/{account_id}/stakeholders",
        json={
            "contact_name": "Jane Doe",
            "title": "VP Engineering",
            "roles": ["decision_maker"],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["contact_name"] == "Jane Doe"
    assert "decision_maker" in data["roles"]


@pytest.mark.asyncio
async def test_update_stakeholder_scores(client_and_repo):
    """PATCH /v1/deals/stakeholders/{id}/scores -> 200."""
    client, repo = client_and_repo

    acc_resp = await client.post("/v1/deals/accounts", json={"account_name": "Acme"})
    account_id = acc_resp.json()["id"]

    sh_resp = await client.post(
        f"/v1/deals/accounts/{account_id}/stakeholders",
        json={"contact_name": "John Smith", "title": "CTO"},
    )
    sh_id = sh_resp.json()["id"]

    response = await client.patch(
        f"/v1/deals/stakeholders/{sh_id}/scores",
        json={
            "decision_power": 9,
            "influence_level": 8,
            "relationship_strength": 7,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["scores"]["decision_power"] == 9
    assert data["scores"]["influence_level"] == 8
    assert data["scores"]["relationship_strength"] == 7


# ── Plan Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_account_plan_not_found(client_and_repo):
    """GET /v1/deals/accounts/{id}/plan -> 404 if no plan."""
    client, repo = client_and_repo

    acc_resp = await client.post("/v1/deals/accounts", json={"account_name": "Acme"})
    account_id = acc_resp.json()["id"]

    response = await client.get(f"/v1/deals/accounts/{account_id}/plan")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_account_plan_exists(client_and_repo):
    """GET /v1/deals/accounts/{id}/plan -> 200 when plan exists."""
    client, repo = client_and_repo

    acc_resp = await client.post("/v1/deals/accounts", json={"account_name": "Acme"})
    account_id = acc_resp.json()["id"]

    # Manually upsert a plan via the repo
    plan_data = AccountPlanData()
    plan_data.company_profile.industry = "Technology"
    await repo.upsert_account_plan(TENANT_ID, account_id, plan_data)

    response = await client.get(f"/v1/deals/accounts/{account_id}/plan")
    assert response.status_code == 200
    data = response.json()
    assert data["company_profile"]["industry"] == "Technology"


# ── Pipeline Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_view(client_and_repo):
    """GET /v1/deals/pipeline -> 200 with stage groups."""
    client, repo = client_and_repo

    acc_resp = await client.post("/v1/deals/accounts", json={"account_name": "Acme"})
    account_id = acc_resp.json()["id"]

    await client.post(
        "/v1/deals/opportunities",
        json={
            "account_id": account_id,
            "name": "Deal A",
            "deal_stage": "discovery",
            "estimated_value": 10000.0,
        },
    )
    await client.post(
        "/v1/deals/opportunities",
        json={
            "account_id": account_id,
            "name": "Deal B",
            "deal_stage": "discovery",
            "estimated_value": 20000.0,
        },
    )
    await client.post(
        "/v1/deals/opportunities",
        json={
            "account_id": account_id,
            "name": "Deal C",
            "deal_stage": "negotiation",
            "estimated_value": 50000.0,
        },
    )

    response = await client.get("/v1/deals/pipeline")
    assert response.status_code == 200
    data = response.json()
    assert data["stage_counts"]["discovery"] == 2
    assert data["stage_counts"]["negotiation"] == 1
    assert data["total_value"] == 80000.0


# ── 503 When Not Initialized ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deals_api_503_when_not_initialized():
    """app.state.deal_repository = None -> 503."""
    from src.app.api.deps import get_current_user, get_tenant

    app = _make_mock_app()
    app.dependency_overrides[get_current_user] = _mock_get_current_user
    app.dependency_overrides[get_tenant] = _mock_get_tenant
    # Explicitly set to None
    app.state.deal_repository = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/deals/accounts")
        assert response.status_code == 503
        assert "not initialized" in response.json()["detail"]
