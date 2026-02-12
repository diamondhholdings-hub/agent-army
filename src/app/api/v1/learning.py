"""REST API + SSE endpoints for learning, feedback, analytics, and coaching.

Provides endpoints for submitting feedback, querying outcomes, retrieving
calibration curves, accessing role-based analytics dashboards, viewing
coaching patterns, and streaming real-time analytics updates via SSE.

All endpoints require authentication and tenant context, following the
exact patterns established in src/app/api/v1/sales.py.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from src.app.api.deps import get_current_user, get_tenant
from src.app.core.tenant import TenantContext
from src.app.models.tenant import User
from src.app.learning.schemas import (
    AnalyticsDashboardResponse,
    CalibrationCurveResponse,
    SubmitFeedbackRequest,
    SubmitFeedbackResponse,
)

# SSE support -- graceful fallback if sse-starlette not installed
try:
    from sse_starlette.sse import EventSourceResponse

    SSE_AVAILABLE = True
except ImportError:
    SSE_AVAILABLE = False

router = APIRouter(prefix="/learning", tags=["learning"])


# ── Dependency Injection Helpers ─────────────────────────────────────────────


def _get_outcome_tracker(request: Request) -> Any:
    """Retrieve OutcomeTracker from app.state, 503 if not available."""
    tracker = getattr(request.app.state, "outcome_tracker", None)
    if tracker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OutcomeTracker is not available. Learning system may not have initialized.",
        )
    return tracker


def _get_feedback_collector(request: Request) -> Any:
    """Retrieve FeedbackCollector from app.state, 503 if not available."""
    collector = getattr(request.app.state, "feedback_collector", None)
    if collector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FeedbackCollector is not available. Learning system may not have initialized.",
        )
    return collector


def _get_calibration_engine(request: Request) -> Any:
    """Retrieve CalibrationEngine from app.state, 503 if not available."""
    engine = getattr(request.app.state, "calibration_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CalibrationEngine is not available. Learning system may not have initialized.",
        )
    return engine


def _get_analytics_service(request: Request) -> Any:
    """Retrieve AnalyticsService from app.state, 503 if not available."""
    service = getattr(request.app.state, "analytics_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AnalyticsService is not available. Learning system may not have initialized.",
        )
    return service


def _get_coaching_extractor(request: Request) -> Any:
    """Retrieve CoachingPatternExtractor from app.state, 503 if not available."""
    extractor = getattr(request.app.state, "coaching_extractor", None)
    if extractor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CoachingPatternExtractor is not available. Learning system may not have initialized.",
        )
    return extractor


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/feedback", response_model=SubmitFeedbackResponse)
async def submit_feedback(
    body: SubmitFeedbackRequest,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> SubmitFeedbackResponse:
    """Submit feedback on agent behavior.

    Accepts inline reactions (-1/0/1) or dashboard reviews (1-5).
    """
    collector = _get_feedback_collector(request)

    try:
        entry = await collector.record_feedback(
            tenant_id=tenant.tenant_id,
            conversation_state_id=body.conversation_state_id,
            target_type=body.target_type,
            target_id=body.target_id,
            source=body.source,
            rating=body.rating,
            reviewer_id=str(user.id),
            reviewer_role=getattr(user, "role", "rep"),
            comment=body.comment,
        )
        return SubmitFeedbackResponse(
            feedback_id=entry.feedback_id, status="recorded"
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@router.get("/feedback/{conversation_state_id}")
async def get_feedback_for_conversation(
    conversation_state_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> list[dict]:
    """Get all feedback entries for a conversation."""
    collector = _get_feedback_collector(request)

    entries = await collector.get_feedback_for_conversation(
        tenant_id=tenant.tenant_id,
        conversation_state_id=conversation_state_id,
    )
    return [e.model_dump(mode="json") for e in entries]


@router.get("/outcomes/{conversation_state_id}")
async def get_outcomes_for_conversation(
    conversation_state_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> list[dict]:
    """Get all outcomes for a conversation."""
    tracker = _get_outcome_tracker(request)

    outcomes = await tracker.get_outcomes_for_conversation(
        tenant_id=tenant.tenant_id,
        conversation_state_id=conversation_state_id,
    )
    return [o.model_dump(mode="json") for o in outcomes]


@router.get("/calibration/{action_type}", response_model=CalibrationCurveResponse)
async def get_calibration_curve(
    action_type: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> CalibrationCurveResponse:
    """Get calibration curve for an action type."""
    engine = _get_calibration_engine(request)

    curve = await engine.get_calibration_curve(
        tenant_id=tenant.tenant_id, action_type=action_type
    )
    total_samples = sum(curve.counts) if curve.counts else 0

    return CalibrationCurveResponse(
        action_type=action_type,
        curve={
            "midpoints": curve.midpoints,
            "actual_rates": curve.actual_rates,
            "counts": curve.counts,
        },
        brier_score=curve.brier_score,
        sample_count=total_samples,
        is_calibrated=curve.brier_score < 0.15 if total_samples > 0 else False,
    )


@router.get("/analytics/rep", response_model=AnalyticsDashboardResponse)
async def get_rep_dashboard(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> AnalyticsDashboardResponse:
    """Rep dashboard -- individual agent performance."""
    service = _get_analytics_service(request)

    data = await service.get_rep_dashboard(
        tenant_id=tenant.tenant_id, days=days
    )
    return AnalyticsDashboardResponse(
        role="rep",
        metrics=data,
        period=f"last_{days}_days",
        generated_at=data.get("generated_at", ""),
    )


@router.get("/analytics/manager", response_model=AnalyticsDashboardResponse)
async def get_manager_dashboard(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> AnalyticsDashboardResponse:
    """Manager dashboard -- team-level trends."""
    service = _get_analytics_service(request)

    data = await service.get_manager_dashboard(
        tenant_id=tenant.tenant_id, days=days
    )
    return AnalyticsDashboardResponse(
        role="manager",
        metrics=data,
        period=f"last_{days}_days",
        generated_at=data.get("generated_at", ""),
    )


@router.get("/analytics/executive", response_model=AnalyticsDashboardResponse)
async def get_executive_summary(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> AnalyticsDashboardResponse:
    """Executive dashboard -- strategic ROI and effectiveness."""
    service = _get_analytics_service(request)

    data = await service.get_executive_summary(
        tenant_id=tenant.tenant_id, days=days
    )
    return AnalyticsDashboardResponse(
        role="executive",
        metrics=data,
        period=f"last_{days}_days",
        generated_at=data.get("generated_at", ""),
    )


@router.get("/coaching/patterns")
async def get_coaching_patterns(
    request: Request,
    days: int = Query(default=90, ge=1, le=365),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> list[dict]:
    """Get coaching patterns extracted from outcome data."""
    extractor = _get_coaching_extractor(request)

    patterns = await extractor.extract_patterns(
        tenant_id=tenant.tenant_id, days=days
    )
    return [p.model_dump(mode="json") for p in patterns]


@router.get("/analytics/stream")
async def analytics_stream(
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
):
    """SSE real-time analytics stream.

    Subscribes to Redis pub/sub channel t:{tenant_id}:analytics and
    yields metric_update events as JSON. Falls back to periodic polling
    if Redis pub/sub unavailable. Returns 501 if sse-starlette not installed.
    """
    if not SSE_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="SSE streaming not available. Install sse-starlette.",
        )

    analytics = _get_analytics_service(request)
    tenant_id = tenant.tenant_id

    async def event_generator():
        """Yield analytics events. Falls back to polling if no Redis pub/sub."""
        redis_client = getattr(request.app.state, "redis_client", None)
        channel_name = f"t:{tenant_id}:analytics"

        if redis_client is not None:
            try:
                pubsub = redis_client.pubsub()
                await pubsub.subscribe(channel_name)

                while True:
                    if await request.is_disconnected():
                        break
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if message and message["type"] == "message":
                        yield {
                            "event": "metric_update",
                            "data": message["data"],
                        }
                    await asyncio.sleep(0.1)

                await pubsub.unsubscribe(channel_name)
                await pubsub.close()
                return
            except Exception:
                # Fall through to polling
                pass

        # Polling fallback: emit dashboard snapshot every 30 seconds
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await analytics.get_rep_dashboard(
                    tenant_id=tenant_id, days=1
                )
                yield {
                    "event": "metric_update",
                    "data": json.dumps(data, default=str),
                }
            except Exception:
                yield {
                    "event": "error",
                    "data": json.dumps({"error": "Failed to compute metrics"}),
                }
            await asyncio.sleep(30)

    return EventSourceResponse(event_generator())
