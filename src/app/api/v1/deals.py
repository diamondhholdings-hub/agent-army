"""REST API endpoints for Deal Management operations.

Provides CRUD endpoints for accounts, opportunities, stakeholders, plans,
and a pipeline view. All endpoints require authentication and tenant context,
following the exact patterns established in src/app/api/v1/sales.py.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from src.app.api.deps import get_current_user, get_tenant
from src.app.core.tenant import TenantContext
from src.app.models.tenant import User

router = APIRouter(prefix="/deals", tags=["deals"])


# ── Response Schemas ─────────────────────────────────────────────────────────


class AccountResponse(BaseModel):
    """Response for account data."""

    id: str
    tenant_id: str
    account_name: str
    industry: str | None = None
    company_size: str | None = None
    website: str | None = None
    region: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class OpportunityResponse(BaseModel):
    """Response for opportunity data, serializes datetimes to ISO strings."""

    id: str
    tenant_id: str
    account_id: str
    external_id: str | None = None
    name: str
    product_line: str | None = None
    deal_stage: str = "prospecting"
    estimated_value: float | None = None
    probability: float = 0.1
    close_date: str | None = None
    detection_confidence: float = 0.0
    source: str = "agent_detected"
    qualification_snapshot: dict[str, Any] = Field(default_factory=dict)
    synced_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class StakeholderResponse(BaseModel):
    """Response for stakeholder data."""

    id: str
    account_id: str
    contact_name: str
    contact_email: str | None = None
    title: str | None = None
    roles: list[str] = Field(default_factory=list)
    scores: dict[str, int] = Field(default_factory=dict)
    score_sources: dict[str, str] = Field(default_factory=dict)
    score_evidence: dict[str, str] = Field(default_factory=dict)
    interaction_count: int = 0
    last_interaction: str | None = None
    notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class PipelineResponse(BaseModel):
    """Pipeline view grouping opportunities by stage."""

    stages: dict[str, list[OpportunityResponse]] = Field(default_factory=dict)
    stage_counts: dict[str, int] = Field(default_factory=dict)
    total_value: float = 0.0


# ── Request Schemas ──────────────────────────────────────────────────────────


class CreateAccountRequest(BaseModel):
    """Request body for creating an account."""

    account_name: str
    industry: str | None = None
    company_size: str | None = None
    website: str | None = None
    region: str | None = None


class CreateOpportunityRequest(BaseModel):
    """Request body for creating an opportunity."""

    account_id: str
    name: str
    product_line: str | None = None
    deal_stage: str = "prospecting"
    estimated_value: float | None = None
    close_date: str | None = None
    detection_confidence: float = 0.0
    source: str = "agent_detected"
    qualification_snapshot: dict[str, Any] = Field(default_factory=dict)


class UpdateOpportunityRequest(BaseModel):
    """Request body for updating an opportunity (all fields optional)."""

    name: str | None = None
    product_line: str | None = None
    deal_stage: str | None = None
    estimated_value: float | None = None
    close_date: str | None = None
    detection_confidence: float | None = None
    probability: float | None = None
    source: str | None = None
    qualification_snapshot: dict[str, Any] | None = None
    external_id: str | None = None


class CreateStakeholderRequest(BaseModel):
    """Request body for creating a stakeholder."""

    contact_name: str
    contact_email: str | None = None
    title: str | None = None
    roles: list[str] = Field(default_factory=list)
    scores: dict[str, int] = Field(default_factory=lambda: {
        "decision_power": 5,
        "influence_level": 5,
        "relationship_strength": 3,
    })
    notes: str | None = None


class UpdateStakeholderScoresRequest(BaseModel):
    """Request body for updating stakeholder scores."""

    decision_power: int = Field(ge=0, le=10)
    influence_level: int = Field(ge=0, le=10)
    relationship_strength: int = Field(ge=0, le=10)
    sources: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)


# ── Dependency Injection Helper ──────────────────────────────────────────────


def _get_deal_repository(request: Request) -> Any:
    """Retrieve DealRepository from app.state, 503 if not available."""
    repo = getattr(request.app.state, "deal_repository", None)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Deal management not initialized",
        )
    return repo


# ── Conversion Helpers ───────────────────────────────────────────────────────


def _account_to_response(account: Any) -> AccountResponse:
    """Convert AccountRead to AccountResponse."""
    return AccountResponse(
        id=account.id,
        tenant_id=account.tenant_id,
        account_name=account.account_name,
        industry=account.industry,
        company_size=account.company_size,
        website=account.website,
        region=account.region,
        created_at=account.created_at.isoformat() if account.created_at else None,
        updated_at=account.updated_at.isoformat() if account.updated_at else None,
    )


def _opportunity_to_response(opp: Any) -> OpportunityResponse:
    """Convert OpportunityRead to OpportunityResponse."""
    return OpportunityResponse(
        id=opp.id,
        tenant_id=opp.tenant_id,
        account_id=opp.account_id,
        external_id=opp.external_id,
        name=opp.name,
        product_line=opp.product_line,
        deal_stage=opp.deal_stage,
        estimated_value=opp.estimated_value,
        probability=opp.probability,
        close_date=opp.close_date.isoformat() if opp.close_date else None,
        detection_confidence=opp.detection_confidence,
        source=opp.source,
        qualification_snapshot=opp.qualification_snapshot,
        synced_at=opp.synced_at.isoformat() if opp.synced_at else None,
        created_at=opp.created_at.isoformat() if opp.created_at else None,
        updated_at=opp.updated_at.isoformat() if opp.updated_at else None,
    )


def _stakeholder_to_response(s: Any) -> StakeholderResponse:
    """Convert StakeholderRead to StakeholderResponse."""
    return StakeholderResponse(
        id=s.id,
        account_id=s.account_id,
        contact_name=s.contact_name,
        contact_email=s.contact_email,
        title=s.title,
        roles=[r.value if hasattr(r, "value") else str(r) for r in s.roles],
        scores=s.scores.model_dump() if hasattr(s.scores, "model_dump") else dict(s.scores),
        score_sources={
            k: v.value if hasattr(v, "value") else str(v)
            for k, v in s.score_sources.items()
        },
        score_evidence=s.score_evidence,
        interaction_count=s.interaction_count,
        last_interaction=(
            s.last_interaction.isoformat() if s.last_interaction else None
        ),
        notes=s.notes,
        created_at=s.created_at.isoformat() if s.created_at else None,
        updated_at=s.updated_at.isoformat() if s.updated_at else None,
    )


# ── Account Endpoints ────────────────────────────────────────────────────────


@router.post("/accounts", response_model=AccountResponse, status_code=201)
async def create_account(
    body: CreateAccountRequest,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> AccountResponse:
    """Create a new account."""
    repo = _get_deal_repository(request)

    from src.app.deals.schemas import AccountCreate

    data = AccountCreate(
        account_name=body.account_name,
        industry=body.industry,
        company_size=body.company_size,
        website=body.website,
        region=body.region,
    )
    account = await repo.create_account(tenant.tenant_id, data)
    return _account_to_response(account)


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> list[AccountResponse]:
    """List all accounts for the tenant."""
    repo = _get_deal_repository(request)
    accounts = await repo.list_accounts(tenant.tenant_id)
    return [_account_to_response(a) for a in accounts]


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> AccountResponse:
    """Get a single account by ID."""
    repo = _get_deal_repository(request)
    account = await repo.get_account(tenant.tenant_id, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account not found: {account_id}",
        )
    return _account_to_response(account)


# ── Opportunity Endpoints ────────────────────────────────────────────────────


@router.post("/opportunities", response_model=OpportunityResponse, status_code=201)
async def create_opportunity(
    body: CreateOpportunityRequest,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> OpportunityResponse:
    """Create a new opportunity."""
    repo = _get_deal_repository(request)

    from src.app.deals.schemas import OpportunityCreate

    data = OpportunityCreate(
        account_id=body.account_id,
        name=body.name,
        product_line=body.product_line,
        deal_stage=body.deal_stage,
        estimated_value=body.estimated_value,
        detection_confidence=body.detection_confidence,
        source=body.source,
        qualification_snapshot=body.qualification_snapshot,
    )
    opp = await repo.create_opportunity(tenant.tenant_id, data)
    return _opportunity_to_response(opp)


@router.get("/opportunities", response_model=list[OpportunityResponse])
async def list_opportunities(
    request: Request,
    stage: str | None = Query(default=None, description="Filter by deal stage"),
    account_id: str | None = Query(default=None, description="Filter by account ID"),
    source: str | None = Query(default=None, description="Filter by source"),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> list[OpportunityResponse]:
    """List opportunities with optional filters."""
    repo = _get_deal_repository(request)

    from src.app.deals.schemas import OpportunityFilter

    filters = None
    if stage or account_id or source:
        filters = OpportunityFilter(
            tenant_id=tenant.tenant_id,
            deal_stage=stage,
            account_id=account_id,
            source=source,
        )

    opps = await repo.list_opportunities(tenant.tenant_id, filters)
    return [_opportunity_to_response(o) for o in opps]


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def get_opportunity(
    opportunity_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> OpportunityResponse:
    """Get a single opportunity by ID."""
    repo = _get_deal_repository(request)
    opp = await repo.get_opportunity(tenant.tenant_id, opportunity_id)
    if opp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Opportunity not found: {opportunity_id}",
        )
    return _opportunity_to_response(opp)


@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def update_opportunity(
    opportunity_id: str,
    body: UpdateOpportunityRequest,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> OpportunityResponse:
    """Update an opportunity."""
    repo = _get_deal_repository(request)

    from src.app.deals.schemas import OpportunityUpdate

    data = OpportunityUpdate(**body.model_dump(exclude_none=True))
    try:
        opp = await repo.update_opportunity(tenant.tenant_id, opportunity_id, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    return _opportunity_to_response(opp)


# ── Stakeholder Endpoints ────────────────────────────────────────────────────


@router.get(
    "/accounts/{account_id}/stakeholders",
    response_model=list[StakeholderResponse],
)
async def list_stakeholders(
    account_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> list[StakeholderResponse]:
    """List stakeholders for an account."""
    repo = _get_deal_repository(request)
    stakeholders = await repo.list_stakeholders(tenant.tenant_id, account_id)
    return [_stakeholder_to_response(s) for s in stakeholders]


@router.post(
    "/accounts/{account_id}/stakeholders",
    response_model=StakeholderResponse,
    status_code=201,
)
async def create_stakeholder(
    account_id: str,
    body: CreateStakeholderRequest,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> StakeholderResponse:
    """Create a stakeholder for an account."""
    repo = _get_deal_repository(request)

    from src.app.deals.schemas import (
        ScoreSource,
        StakeholderCreate,
        StakeholderRole,
        StakeholderScores,
    )

    # Parse roles
    roles = []
    for r in body.roles:
        try:
            roles.append(StakeholderRole(r))
        except ValueError:
            pass

    scores = StakeholderScores(
        decision_power=body.scores.get("decision_power", 5),
        influence_level=body.scores.get("influence_level", 5),
        relationship_strength=body.scores.get("relationship_strength", 3),
    )

    data = StakeholderCreate(
        contact_name=body.contact_name,
        contact_email=body.contact_email,
        title=body.title,
        roles=roles,
        scores=scores,
        notes=body.notes,
    )
    stakeholder = await repo.create_stakeholder(tenant.tenant_id, data, account_id)
    return _stakeholder_to_response(stakeholder)


@router.patch(
    "/stakeholders/{stakeholder_id}/scores",
    response_model=StakeholderResponse,
)
async def update_stakeholder_scores(
    stakeholder_id: str,
    body: UpdateStakeholderScoresRequest,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> StakeholderResponse:
    """Update stakeholder political mapping scores."""
    repo = _get_deal_repository(request)

    from src.app.deals.schemas import StakeholderScores

    scores = StakeholderScores(
        decision_power=body.decision_power,
        influence_level=body.influence_level,
        relationship_strength=body.relationship_strength,
    )
    try:
        stakeholder = await repo.update_stakeholder_scores(
            tenant_id=tenant.tenant_id,
            stakeholder_id=stakeholder_id,
            scores=scores,
            sources=body.sources,
            evidence=body.evidence,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    return _stakeholder_to_response(stakeholder)


# ── Plan Endpoints ───────────────────────────────────────────────────────────


@router.get("/accounts/{account_id}/plan")
async def get_account_plan(
    account_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> dict:
    """Get the account plan for an account."""
    repo = _get_deal_repository(request)
    plan = await repo.get_account_plan(tenant.tenant_id, account_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No account plan found for account: {account_id}",
        )
    return plan.model_dump(mode="json")


@router.get("/opportunities/{opportunity_id}/plan")
async def get_opportunity_plan(
    opportunity_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> dict:
    """Get the opportunity plan for an opportunity."""
    repo = _get_deal_repository(request)
    plan = await repo.get_opportunity_plan(tenant.tenant_id, opportunity_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No opportunity plan found for opportunity: {opportunity_id}",
        )
    return plan.model_dump(mode="json")


# ── Pipeline Endpoint ────────────────────────────────────────────────────────


@router.get("/pipeline", response_model=PipelineResponse)
async def get_pipeline(
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> PipelineResponse:
    """Pipeline view: all opportunities grouped by stage with counts and totals."""
    repo = _get_deal_repository(request)
    opps = await repo.list_opportunities(tenant.tenant_id)

    # Group by stage
    stages: dict[str, list[OpportunityResponse]] = {}
    total_value = 0.0

    for opp in opps:
        response = _opportunity_to_response(opp)
        stage = opp.deal_stage
        if stage not in stages:
            stages[stage] = []
        stages[stage].append(response)
        if opp.estimated_value is not None:
            total_value += opp.estimated_value

    stage_counts = {stage: len(items) for stage, items in stages.items()}

    return PipelineResponse(
        stages=stages,
        stage_counts=stage_counts,
        total_value=total_value,
    )
