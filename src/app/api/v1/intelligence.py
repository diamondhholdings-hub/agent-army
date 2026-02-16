"""REST API endpoints for Intelligence & Autonomy system (Phase 7).

Provides endpoints for customer views, insights, goals, clones, personas,
and autonomy management. All endpoints require authentication and tenant
context, following the existing sales.py / learning.py auth + tenant
dependency pattern.

Services are accessed from ``request.app.state`` with 503 fallback when
not initialized (matching learning.py pattern).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

import structlog

from src.app.api.deps import get_current_user, get_tenant
from src.app.core.tenant import TenantContext
from src.app.models.tenant import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


# ── Service Accessor ─────────────────────────────────────────────────────────


def _get_intelligence_service(request: Request, service_name: str) -> Any:
    """Retrieve a Phase 7 intelligence service from app.state.

    Returns the service or raises HTTPException(503) if not initialized.

    Args:
        request: FastAPI request for app.state access.
        service_name: Attribute name on app.state.

    Returns:
        The requested service instance.

    Raises:
        HTTPException(503): If the service is None or not set.
    """
    service = getattr(request.app.state, service_name, None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Intelligence service '{service_name}' is not available. "
            "Phase 7 services may not have initialized.",
        )
    return service


# ── Request / Response Schemas ───────────────────────────────────────────────


class GoalCreateRequest(BaseModel):
    """Request body for creating a new goal."""

    goal_type: str = Field(
        ..., description="Category: pipeline, activity, quality, revenue"
    )
    target_value: float = Field(..., gt=0, description="Target value to achieve")
    period_start: datetime = Field(..., description="Start of the goal period")
    period_end: datetime = Field(..., description="End of the goal period")
    clone_id: Optional[str] = Field(
        default=None, description="Clone ID (None for tenant-wide)"
    )


class InsightFeedbackRequest(BaseModel):
    """Request body for submitting feedback on an insight."""

    feedback: str = Field(
        ..., description="Feedback type: 'useful' or 'false_alarm'"
    )
    comment: Optional[str] = Field(
        default=None, description="Optional comment with additional context"
    )


class ApprovalResolutionRequest(BaseModel):
    """Request body for approving or rejecting a pending action."""

    approved: bool = Field(..., description="True to approve, False to reject")
    resolved_by: str = Field(..., description="User ID of the person resolving")


class CloneCreateRequest(BaseModel):
    """Request body for creating a new agent clone."""

    clone_name: str = Field(..., description="Display name for the clone")
    owner_id: str = Field(..., description="Sales rep who owns this clone")
    dimensions: Optional[Dict[str, float]] = Field(
        default=None,
        description="Persona dimension values (0.0-1.0). Keys: formal_casual, "
        "concise_detailed, technical_business, proactive_reactive",
    )
    region: Optional[str] = Field(
        default=None, description="Geographic region: apac, emea, americas"
    )
    custom_instructions: Optional[str] = Field(
        default=None, description="Free-form persona customization text"
    )


class CloneUpdateRequest(BaseModel):
    """Request body for updating a clone's persona config."""

    clone_name: Optional[str] = Field(
        default=None, description="New display name"
    )
    dimensions: Optional[Dict[str, float]] = Field(
        default=None, description="Updated dimension values"
    )
    region: Optional[str] = Field(
        default=None, description="Updated geographic region"
    )
    custom_instructions: Optional[str] = Field(
        default=None, description="Updated customization text"
    )


class PersonaPreviewRequest(BaseModel):
    """Request body for generating a persona preview."""

    clone_name: str = Field(
        default="Preview Clone", description="Display name"
    )
    owner_id: str = Field(default="preview", description="Owner ID")
    dimensions: Optional[Dict[str, float]] = Field(
        default=None, description="Persona dimension values"
    )
    region: Optional[str] = Field(default=None, description="Geographic region")
    custom_instructions: Optional[str] = Field(
        default=None, description="Custom instructions"
    )


# ── Customer View Endpoints ──────────────────────────────────────────────────


@router.get("/customer-view/{account_id}")
async def get_customer_view(
    request: Request,
    account_id: str,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Get unified customer view for an account.

    Returns the cross-channel consolidated view including timeline,
    summaries, and extracted signals.
    """
    service = _get_intelligence_service(request, "customer_view_service")
    view = await service.get_unified_view(tenant.tenant_id, account_id)
    return view


@router.get("/customer-view/{account_id}/recent")
async def get_customer_view_recent(
    request: Request,
    account_id: str,
    days: int = Query(default=7, ge=1, le=90, description="Number of days"),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Get recent activity for an account.

    Returns interactions from the last N days (default 7).
    """
    service = _get_intelligence_service(request, "customer_view_service")
    view = await service.get_unified_view(tenant.tenant_id, account_id)
    # Filter timeline to recent days
    if hasattr(view, "timeline"):
        from datetime import timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent = [
            i for i in view.timeline if hasattr(i, "timestamp") and i.timestamp >= cutoff
        ]
        return {"account_id": account_id, "days": days, "interactions": recent}
    return {"account_id": account_id, "days": days, "interactions": []}


# ── Insights Endpoints ───────────────────────────────────────────────────────


@router.get("/insights")
async def list_insights(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Filter by account"),
    insight_status: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by status: pending, acted, dismissed",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Max results"),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """List insights for the tenant with optional filters."""
    service = _get_intelligence_service(request, "intelligence_repository")
    insights = await service.list_insights(
        tenant_id=tenant.tenant_id,
        account_id=account_id,
        status=insight_status,
        limit=limit,
    )
    return insights


@router.post("/insights/{insight_id}/feedback")
async def submit_insight_feedback(
    request: Request,
    insight_id: str,
    body: InsightFeedbackRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Submit feedback on an insight (useful or false_alarm)."""
    service = _get_intelligence_service(request, "insight_generator")
    success = await service.process_feedback(
        tenant_id=tenant.tenant_id,
        insight_id=insight_id,
        feedback=body.feedback,
        comment=body.comment,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to record feedback.",
        )
    return {"status": "ok", "insight_id": insight_id, "feedback": body.feedback}


@router.get("/insights/digest")
async def get_daily_digest(
    request: Request,
    clone_id: Optional[str] = Query(default=None, description="Filter by clone"),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Get daily digest of insights for the tenant."""
    service = _get_intelligence_service(request, "insight_generator")
    digest = await service.generate_daily_digest(
        tenant_id=tenant.tenant_id,
        clone_id=clone_id,
    )
    return digest


@router.get("/insights/feedback-stats")
async def get_feedback_stats(
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Get feedback statistics for threshold tuning."""
    service = _get_intelligence_service(request, "insight_generator")
    stats = await service.get_feedback_summary(tenant_id=tenant.tenant_id)
    return stats


# ── Goals Endpoints ──────────────────────────────────────────────────────────


@router.post("/goals", status_code=status.HTTP_201_CREATED)
async def create_goal(
    request: Request,
    body: GoalCreateRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Create a new measurable goal."""
    service = _get_intelligence_service(request, "goal_tracker")
    from src.app.intelligence.autonomy.schemas import GoalType

    try:
        goal_type = GoalType(body.goal_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid goal_type: {body.goal_type}. "
            f"Valid types: {[t.value for t in GoalType]}",
        )

    goal = await service.create_goal(
        tenant_id=tenant.tenant_id,
        goal_type=goal_type,
        target_value=body.target_value,
        period_start=body.period_start,
        period_end=body.period_end,
        clone_id=body.clone_id,
    )
    return goal


@router.get("/goals")
async def list_goals(
    request: Request,
    clone_id: Optional[str] = Query(default=None, description="Filter by clone"),
    goal_status: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by status: active, completed, missed",
    ),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """List goals for the tenant."""
    service = _get_intelligence_service(request, "goal_tracker")
    goals = await service.get_active_goals(
        tenant_id=tenant.tenant_id,
        clone_id=clone_id,
    )
    return goals


@router.get("/goals/{goal_id}/status")
async def get_goal_status(
    request: Request,
    goal_id: str,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Get goal status with progress percentage and on-track indicator."""
    service = _get_intelligence_service(request, "goal_tracker")
    status_data = await service.get_goal_status(
        tenant_id=tenant.tenant_id,
        goal_id=goal_id,
    )
    if status_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal not found: {goal_id}",
        )
    return status_data


@router.get("/metrics")
async def get_performance_metrics(
    request: Request,
    clone_id: Optional[str] = Query(default=None, description="Filter by clone"),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Get current performance metrics for a clone or tenant."""
    service = _get_intelligence_service(request, "goal_tracker")
    metrics = await service.compute_metrics(
        tenant_id=tenant.tenant_id,
        clone_id=clone_id,
    )
    return metrics


# ── Clone / Persona Endpoints ────────────────────────────────────────────────


@router.post("/clones", status_code=status.HTTP_201_CREATED)
async def create_clone(
    request: Request,
    body: CloneCreateRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Create a new agent clone with persona configuration."""
    clone_manager = _get_intelligence_service(request, "clone_manager")
    persona_builder = _get_intelligence_service(request, "persona_builder")

    # Build persona config from request
    from src.app.intelligence.persona.schemas import PersonaDimension

    dimensions = None
    if body.dimensions:
        dimensions = {}
        for key, val in body.dimensions.items():
            try:
                dim = PersonaDimension(key)
                dimensions[dim] = val
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid dimension: {key}. "
                    f"Valid: {[d.value for d in PersonaDimension]}",
                )

    persona_config = persona_builder.build_persona(
        clone_name=body.clone_name,
        owner_id=body.owner_id,
        dimensions=dimensions,
        region=body.region,
        custom_instructions=body.custom_instructions,
    )
    persona_config.tenant_id = tenant.tenant_id

    clone = await clone_manager.create_clone(
        tenant_id=tenant.tenant_id,
        clone_name=body.clone_name,
        owner_id=body.owner_id,
        persona_config=persona_config,
    )
    return clone


@router.get("/clones")
async def list_clones(
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """List all active clones for the tenant."""
    service = _get_intelligence_service(request, "clone_manager")
    clones = await service.list_clones(tenant_id=tenant.tenant_id)
    return clones


@router.get("/clones/{clone_id}")
async def get_clone(
    request: Request,
    clone_id: str,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Get clone details by ID."""
    service = _get_intelligence_service(request, "clone_manager")
    clone = await service.get_clone(
        tenant_id=tenant.tenant_id, clone_id=clone_id
    )
    if clone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clone not found: {clone_id}",
        )
    return clone


@router.put("/clones/{clone_id}")
async def update_clone(
    request: Request,
    clone_id: str,
    body: CloneUpdateRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Update a clone's persona configuration."""
    service = _get_intelligence_service(request, "clone_manager")

    updates: Dict[str, Any] = {}
    if body.clone_name is not None:
        updates["clone_name"] = body.clone_name

    if body.dimensions is not None:
        from src.app.intelligence.persona.schemas import PersonaConfig, PersonaDimension

        dimensions = {}
        for key, val in body.dimensions.items():
            try:
                dim = PersonaDimension(key)
                dimensions[dim] = val
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid dimension: {key}",
                )
        updates["persona_config"] = PersonaConfig(
            clone_id=clone_id,
            tenant_id=tenant.tenant_id,
            owner_id="",
            dimensions=dimensions,
            region=body.region,
            custom_instructions=body.custom_instructions,
        )

    clone = await service.update_clone(
        tenant_id=tenant.tenant_id,
        clone_id=clone_id,
        **updates,
    )
    if clone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clone not found: {clone_id}",
        )
    return clone


@router.delete("/clones/{clone_id}")
async def deactivate_clone(
    request: Request,
    clone_id: str,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Soft-deactivate a clone."""
    service = _get_intelligence_service(request, "clone_manager")
    success = await service.deactivate_clone(
        tenant_id=tenant.tenant_id, clone_id=clone_id
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clone not found: {clone_id}",
        )
    return {"status": "deactivated", "clone_id": clone_id}


@router.post("/clones/preview")
async def generate_persona_preview(
    request: Request,
    body: PersonaPreviewRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Generate a persona preview with sample email and chat messages."""
    persona_builder = _get_intelligence_service(request, "persona_builder")

    from src.app.intelligence.persona.schemas import PersonaDimension

    dimensions = None
    if body.dimensions:
        dimensions = {}
        for key, val in body.dimensions.items():
            try:
                dim = PersonaDimension(key)
                dimensions[dim] = val
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid dimension: {key}",
                )

    persona_config = persona_builder.build_persona(
        clone_name=body.clone_name,
        owner_id=body.owner_id,
        dimensions=dimensions,
        region=body.region,
        custom_instructions=body.custom_instructions,
    )
    persona_config.tenant_id = tenant.tenant_id

    preview = await persona_builder.generate_preview(persona_config)
    return preview


@router.get("/persona/dimensions")
async def get_dimension_options(
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Get dimension options for guided persona builder UI."""
    persona_builder = _get_intelligence_service(request, "persona_builder")
    options = persona_builder.get_dimension_options()
    return options


# ── Autonomy Endpoints ───────────────────────────────────────────────────────


@router.get("/autonomy/pending")
async def list_pending_approvals(
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """List pending approval requests for autonomous actions."""
    service = _get_intelligence_service(request, "autonomy_engine")
    pending = await service.get_pending_approvals(tenant_id=tenant.tenant_id)
    return pending


@router.post("/autonomy/{action_id}/approve")
async def resolve_approval(
    request: Request,
    action_id: str,
    body: ApprovalResolutionRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Approve or reject a pending autonomous action."""
    service = _get_intelligence_service(request, "autonomy_engine")
    success = await service.resolve_approval(
        tenant_id=tenant.tenant_id,
        action_id=action_id,
        approved=body.approved,
        resolved_by=body.resolved_by,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action not found or could not be resolved: {action_id}",
        )
    return {
        "status": "approved" if body.approved else "rejected",
        "action_id": action_id,
    }


@router.post("/autonomy/scan/{account_id}")
async def trigger_pattern_scan(
    request: Request,
    account_id: str,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> Any:
    """Trigger an on-demand pattern scan for an account."""
    pattern_engine = _get_intelligence_service(request, "pattern_engine")
    customer_view_service = _get_intelligence_service(
        request, "customer_view_service"
    )

    patterns = await pattern_engine.scan_account(
        tenant_id=tenant.tenant_id,
        account_id=account_id,
        customer_view_service=customer_view_service,
    )
    return {
        "account_id": account_id,
        "patterns_detected": len(patterns),
        "patterns": patterns,
    }
