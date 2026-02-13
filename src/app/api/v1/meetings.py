"""REST API and WebSocket endpoints for Meeting Capabilities.

Provides endpoints for listing meetings, viewing details, generating briefings,
managing bot lifecycle, retrieving transcripts, generating and sharing minutes,
handling Recall.ai webhooks, and WebSocket bridge for real-time pipeline
communication with the Output Media webapp.

All REST endpoints require authentication and tenant context, following the
patterns established in src/app/api/v1/sales.py and src/app/api/v1/deals.py.

Per CONTEXT.md: minutes sharing is manual only -- no automatic external
distribution.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field

import structlog

from src.app.api.deps import get_current_user, get_tenant
from src.app.core.tenant import TenantContext
from src.app.models.tenant import User
from src.app.meetings.schemas import (
    Briefing,
    Meeting,
    MeetingBriefingRequest,
    MeetingMinutes,
    MeetingStatus,
    MinutesShareRequest,
    Transcript,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/meetings", tags=["meetings"])


# ── Response Schemas ─────────────────────────────────────────────────────────


class MeetingResponse(BaseModel):
    """Response for meeting data, serializes datetimes to ISO strings."""

    id: str
    tenant_id: str
    title: str
    scheduled_start: str
    scheduled_end: str
    google_meet_url: str
    google_event_id: str
    status: str
    participants: list[dict] = Field(default_factory=list)
    bot_id: str | None = None
    recording_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class BriefingResponse(BaseModel):
    """Response for briefing data."""

    id: str
    meeting_id: str
    format: str
    content: dict
    generated_at: str


class TranscriptResponse(BaseModel):
    """Response for transcript data."""

    id: str
    meeting_id: str
    entries: list[dict] = Field(default_factory=list)
    full_text: str = ""


class MinutesResponse(BaseModel):
    """Response for meeting minutes data."""

    id: str
    meeting_id: str
    executive_summary: str
    key_topics: list[str] = Field(default_factory=list)
    action_items: list[dict] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)
    follow_up_date: str | None = None
    generated_at: str


class BotStatusResponse(BaseModel):
    """Response for bot status."""

    bot_id: str | None = None
    status: str


class ShareResponse(BaseModel):
    """Response for minutes sharing."""

    shared_to: list[str]
    shared_at: str


# ── Dependency Injection Helpers ─────────────────────────────────────────────


def _get_meeting_repository(request: Request) -> Any:
    """Retrieve MeetingRepository from app.state, 503 if not available."""
    repo = getattr(request.app.state, "meeting_repository", None)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meeting repository not initialized",
        )
    return repo


def _get_bot_manager(request: Request) -> Any:
    """Retrieve BotManager from app.state, 503 if not available."""
    mgr = getattr(request.app.state, "bot_manager", None)
    if mgr is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot manager not initialized (Recall.ai API key may not be configured)",
        )
    return mgr


def _get_briefing_generator(request: Request) -> Any:
    """Retrieve BriefingGenerator from app.state, 503 if not available."""
    gen = getattr(request.app.state, "briefing_generator", None)
    if gen is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Briefing generator not initialized",
        )
    return gen


def _get_minutes_generator(request: Request) -> Any:
    """Retrieve MinutesGenerator from app.state, 503 if not available."""
    gen = getattr(request.app.state, "minutes_generator", None)
    if gen is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Minutes generator not initialized",
        )
    return gen


def _get_minutes_distributor(request: Request) -> Any:
    """Retrieve MinutesDistributor from app.state, 503 if not available."""
    dist = getattr(request.app.state, "minutes_distributor", None)
    if dist is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Minutes distributor not initialized",
        )
    return dist


# ── Conversion Helpers ───────────────────────────────────────────────────────


def _meeting_to_response(m: Meeting) -> MeetingResponse:
    """Convert Meeting schema to MeetingResponse."""
    return MeetingResponse(
        id=str(m.id),
        tenant_id=m.tenant_id,
        title=m.title,
        scheduled_start=m.scheduled_start.isoformat(),
        scheduled_end=m.scheduled_end.isoformat(),
        google_meet_url=m.google_meet_url,
        google_event_id=m.google_event_id,
        status=m.status.value if hasattr(m.status, "value") else str(m.status),
        participants=[p.model_dump(mode="json") for p in m.participants],
        bot_id=m.bot_id,
        recording_url=m.recording_url,
        created_at=m.created_at.isoformat() if m.created_at else None,
        updated_at=m.updated_at.isoformat() if m.updated_at else None,
    )


def _briefing_to_response(b: Briefing) -> BriefingResponse:
    """Convert Briefing schema to BriefingResponse."""
    return BriefingResponse(
        id=str(b.id),
        meeting_id=str(b.meeting_id),
        format=b.format,
        content=b.content.model_dump(mode="json"),
        generated_at=b.generated_at.isoformat(),
    )


def _transcript_to_response(t: Transcript) -> TranscriptResponse:
    """Convert Transcript schema to TranscriptResponse."""
    return TranscriptResponse(
        id=str(t.id),
        meeting_id=str(t.meeting_id),
        entries=[e.model_dump(mode="json") for e in t.entries],
        full_text=t.full_text,
    )


def _minutes_to_response(m: MeetingMinutes) -> MinutesResponse:
    """Convert MeetingMinutes schema to MinutesResponse."""
    return MinutesResponse(
        id=str(m.id),
        meeting_id=str(m.meeting_id),
        executive_summary=m.executive_summary,
        key_topics=m.key_topics,
        action_items=[a.model_dump(mode="json") for a in m.action_items],
        decisions=[d.model_dump(mode="json") for d in m.decisions],
        follow_up_date=m.follow_up_date,
        generated_at=m.generated_at.isoformat(),
    )


# ── REST Endpoints ───────────────────────────────────────────────────────────


@router.get("/", response_model=list[MeetingResponse])
async def list_meetings(
    request: Request,
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter by meeting status",
    ),
    from_date: str | None = Query(
        default=None,
        description="Start of date range (ISO format)",
    ),
    to_date: str | None = Query(
        default=None,
        description="End of date range (ISO format)",
    ),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> list[MeetingResponse]:
    """List upcoming meetings for the tenant.

    Supports optional filters: status, from_date, to_date.
    """
    repo = _get_meeting_repository(request)

    # Default time window: now to +30 days
    now = datetime.now(timezone.utc)
    from_time = datetime.fromisoformat(from_date) if from_date else now
    to_time = (
        datetime.fromisoformat(to_date)
        if to_date
        else now.replace(year=now.year + 1)
    )

    meetings = await repo.get_upcoming_meetings(
        tenant_id=tenant.tenant_id,
        from_time=from_time,
        to_time=to_time,
    )

    # Apply status filter if provided
    if status_filter:
        meetings = [
            m for m in meetings
            if (m.status.value if hasattr(m.status, "value") else str(m.status)) == status_filter
        ]

    return [_meeting_to_response(m) for m in meetings]


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> MeetingResponse:
    """Get meeting details by ID."""
    repo = _get_meeting_repository(request)
    meeting = await repo.get_meeting(tenant.tenant_id, meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting not found: {meeting_id}",
        )
    return _meeting_to_response(meeting)


@router.post("/{meeting_id}/briefing", response_model=BriefingResponse)
async def generate_briefing(
    meeting_id: str,
    body: MeetingBriefingRequest,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> BriefingResponse:
    """Generate or retrieve a pre-meeting briefing.

    If a briefing already exists for the requested format, returns cached.
    Otherwise generates via BriefingGenerator.
    """
    repo = _get_meeting_repository(request)
    briefing_gen = _get_briefing_generator(request)

    # Check for cached briefing
    existing = await repo.get_briefing(
        tenant.tenant_id, meeting_id, body.format
    )
    if existing is not None:
        return _briefing_to_response(existing)

    # Get the meeting for context
    meeting = await repo.get_meeting(tenant.tenant_id, meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting not found: {meeting_id}",
        )

    # Generate briefing
    briefing = await briefing_gen.generate(
        meeting=meeting,
        format=body.format,
        tenant_id=tenant.tenant_id,
    )
    return _briefing_to_response(briefing)


@router.get(
    "/{meeting_id}/briefing/{briefing_format}",
    response_model=BriefingResponse,
)
async def get_briefing(
    meeting_id: str,
    briefing_format: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> BriefingResponse:
    """Get a specific format briefing for a meeting."""
    repo = _get_meeting_repository(request)
    briefing = await repo.get_briefing(
        tenant.tenant_id, meeting_id, briefing_format
    )
    if briefing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Briefing not found for meeting {meeting_id} format {briefing_format}",
        )
    return _briefing_to_response(briefing)


@router.post("/{meeting_id}/bot/start", response_model=BotStatusResponse)
async def start_bot(
    meeting_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> BotStatusResponse:
    """Manually trigger bot join for a meeting.

    Creates a Recall.ai bot via BotManager.
    """
    repo = _get_meeting_repository(request)
    bot_mgr = _get_bot_manager(request)

    meeting = await repo.get_meeting(tenant.tenant_id, meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting not found: {meeting_id}",
        )

    bot_id = await bot_mgr.create_meeting_bot(meeting, tenant.tenant_id)
    return BotStatusResponse(bot_id=bot_id, status="joining")


@router.get("/{meeting_id}/bot/status", response_model=BotStatusResponse)
async def get_bot_status(
    meeting_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> BotStatusResponse:
    """Get bot status for a meeting."""
    repo = _get_meeting_repository(request)
    bot_mgr = _get_bot_manager(request)

    meeting = await repo.get_meeting(tenant.tenant_id, meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting not found: {meeting_id}",
        )

    if not meeting.bot_id:
        return BotStatusResponse(bot_id=None, status="no_bot")

    bot_status = await bot_mgr.get_bot_status(meeting.bot_id)
    return BotStatusResponse(bot_id=meeting.bot_id, status=bot_status)


@router.get("/{meeting_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    meeting_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> TranscriptResponse:
    """Get meeting transcript."""
    repo = _get_meeting_repository(request)
    transcript = await repo.get_transcript(tenant.tenant_id, meeting_id)
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript not found for meeting {meeting_id}",
        )
    return _transcript_to_response(transcript)


@router.get("/{meeting_id}/minutes", response_model=MinutesResponse)
async def get_minutes(
    meeting_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> MinutesResponse:
    """Get meeting minutes."""
    repo = _get_meeting_repository(request)
    minutes = await repo.get_minutes(tenant.tenant_id, meeting_id)
    if minutes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Minutes not found for meeting {meeting_id}",
        )
    return _minutes_to_response(minutes)


@router.post(
    "/{meeting_id}/minutes/generate", response_model=MinutesResponse
)
async def generate_minutes(
    meeting_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> MinutesResponse:
    """Trigger minutes generation from meeting transcript.

    Loads transcript, generates structured minutes via MinutesGenerator.
    """
    repo = _get_meeting_repository(request)
    minutes_gen = _get_minutes_generator(request)

    meeting = await repo.get_meeting(tenant.tenant_id, meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting not found: {meeting_id}",
        )

    transcript = await repo.get_transcript(tenant.tenant_id, meeting_id)
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript not found for meeting {meeting_id}. Cannot generate minutes without transcript.",
        )

    minutes = await minutes_gen.generate(
        transcript=transcript,
        attendees=meeting.participants,
        meeting_metadata={
            "title": meeting.title,
            "date": meeting.scheduled_start.isoformat(),
        },
        tenant_id=tenant.tenant_id,
    )
    return _minutes_to_response(minutes)


@router.post("/{meeting_id}/minutes/share", response_model=ShareResponse)
async def share_minutes(
    meeting_id: str,
    body: MinutesShareRequest,
    request: Request,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> ShareResponse:
    """Manually share meeting minutes to selected recipients.

    Per CONTEXT.md: manual share only, no automatic distribution.
    Rep decides what to share externally.
    """
    distributor = _get_minutes_distributor(request)

    try:
        result = await distributor.share_externally(
            meeting_id=uuid.UUID(meeting_id),
            tenant_id=tenant.tenant_id,
            recipient_emails=body.recipient_emails,
            include_transcript=body.include_transcript,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    return ShareResponse(
        shared_to=result["sent_to"],
        shared_at=result["share_time"],
    )


@router.post("/webhook")
async def receive_webhook(
    request: Request,
) -> dict:
    """Recall.ai webhook receiver.

    Receives bot lifecycle events and transcript data. Routes events
    to BotManager.handle_bot_event.

    Returns 200 OK always per webhook best practice (avoid retries
    on processing errors).

    NOTE: Webhook endpoint does NOT require tenant auth -- Recall.ai
    sends events directly. Validation is done via webhook token.
    """
    try:
        payload = await request.json()
    except Exception:
        # Always return 200 per webhook best practice
        return {"status": "ok"}

    # Extract event details
    event_type = payload.get("event", payload.get("type", ""))
    bot_id = payload.get("data", {}).get("bot_id", payload.get("bot_id", ""))
    event_data = payload.get("data", payload)

    # Validate webhook token if configured
    webhook_token = getattr(
        getattr(request.app.state, "_settings", None),
        "RECALL_AI_WEBHOOK_TOKEN",
        None,
    )
    if webhook_token:
        request_token = request.headers.get("X-Recall-Token", "")
        if request_token != webhook_token:
            logger.warning(
                "webhook.invalid_token",
                bot_id=bot_id,
                event_type=event_type,
            )
            # Still return 200 to prevent retries
            return {"status": "ok"}

    # Route to BotManager if available
    bot_mgr = getattr(request.app.state, "bot_manager", None)
    if bot_mgr is not None and bot_id:
        try:
            await bot_mgr.handle_bot_event(
                bot_id=bot_id,
                event_type=event_type,
                event_data=event_data,
            )
        except Exception:
            logger.warning(
                "webhook.handler_error",
                bot_id=bot_id,
                event_type=event_type,
                exc_info=True,
            )

    return {"status": "ok"}


# ── WebSocket Endpoint ───────────────────────────────────────────────────────


@router.websocket("/ws/{meeting_id}")
async def meeting_websocket(
    websocket: WebSocket,
    meeting_id: str,
) -> None:
    """Real-time pipeline bridge for Output Media webapp.

    Accepts WebSocket connection from the Recall.ai Output Media webapp.
    Receives transcript data and routes to RealtimePipeline.
    Sends back speech commands and avatar reactions.

    Message formats:
    Receive: { "type": "transcript", "text": "...", "is_final": bool, "speaker_id": "..." }
    Send:    { "type": "speak", "text": "...", "confidence": float }
             { "type": "silence" }
             { "type": "reaction", "reaction": "nod|interested|thinking" }
    """
    await websocket.accept()
    logger.info(
        "websocket.connected",
        meeting_id=meeting_id,
    )

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "Invalid JSON"})
                continue

            msg_type = message.get("type", "")

            if msg_type == "transcript":
                text = message.get("text", "")
                is_final = message.get("is_final", False)
                speaker_id = message.get("speaker_id", "unknown")

                # Route to real-time pipeline if available
                pipeline = getattr(
                    getattr(websocket.app, "state", None),
                    f"pipeline_{meeting_id}",
                    None,
                )
                if pipeline is not None:
                    try:
                        await pipeline.handle_stt_transcript(
                            transcript=text,
                            is_final=is_final,
                            speaker_id=speaker_id,
                        )
                        # Pipeline spoke -- send speech response
                        if is_final and text.strip():
                            await websocket.send_json({
                                "type": "speak",
                                "text": "",
                                "confidence": 0.0,
                            })
                    except Exception:
                        logger.warning(
                            "websocket.pipeline_error",
                            meeting_id=meeting_id,
                            exc_info=True,
                        )
                else:
                    # No pipeline -- acknowledge receipt
                    if is_final:
                        await websocket.send_json({"type": "silence"})

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json({
                    "type": "error",
                    "detail": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        logger.info(
            "websocket.disconnected",
            meeting_id=meeting_id,
        )
    except Exception:
        logger.warning(
            "websocket.error",
            meeting_id=meeting_id,
            exc_info=True,
        )
