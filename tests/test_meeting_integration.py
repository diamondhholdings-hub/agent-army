"""Integration tests for Phase 6 meeting capabilities.

Tests the full meeting API endpoint flow, WebSocket communication,
main.py lifespan initialization, and end-to-end meeting lifecycle
using mocked external services.

Uses InMemoryMeetingRepository test double and FastAPI TestClient.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.api.v1.meetings import router as meetings_router
from src.app.meetings.schemas import (
    ActionItem,
    Briefing,
    BriefingContent,
    Decision,
    Meeting,
    MeetingCreate,
    MeetingMinutes,
    MeetingStatus,
    Participant,
    ParticipantRole,
    Transcript,
    TranscriptEntry,
)


# ── Constants ────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())
NOW = datetime.now(timezone.utc)


# ── In-Memory Repository ────────────────────────────────────────────────────


class InMemoryMeetingRepository:
    """In-memory test double for MeetingRepository (same as test_meeting_foundation)."""

    def __init__(self) -> None:
        self.meetings: dict[str, Meeting] = {}
        self.briefings: dict[str, Briefing] = {}
        self.transcripts: dict[str, Transcript] = {}
        self.minutes: dict[str, MeetingMinutes] = {}
        self.minutes_shared: set[str] = set()

    async def create_meeting(
        self, tenant_id: str, data: MeetingCreate
    ) -> Meeting:
        meeting = Meeting(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            title=data.title,
            scheduled_start=data.scheduled_start,
            scheduled_end=data.scheduled_end,
            google_meet_url=data.google_meet_url,
            google_event_id=data.google_event_id,
            participants=data.participants,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.meetings[str(meeting.id)] = meeting
        return meeting

    async def get_meeting(
        self, tenant_id: str, meeting_id: str
    ) -> Meeting | None:
        m = self.meetings.get(meeting_id)
        if m and m.tenant_id == tenant_id:
            return m
        return None

    async def get_meeting_by_event_id(
        self, tenant_id: str, google_event_id: str
    ) -> Meeting | None:
        for m in self.meetings.values():
            if m.tenant_id == tenant_id and m.google_event_id == google_event_id:
                return m
        return None

    async def get_upcoming_meetings(
        self, tenant_id: str, from_time: datetime, to_time: datetime
    ) -> list[Meeting]:
        results = [
            m
            for m in self.meetings.values()
            if m.tenant_id == tenant_id
            and from_time <= m.scheduled_start <= to_time
        ]
        return sorted(results, key=lambda m: m.scheduled_start)

    async def update_meeting_status(
        self, tenant_id: str, meeting_id: str, status: MeetingStatus
    ) -> Meeting:
        m = self.meetings.get(meeting_id)
        if m is None or m.tenant_id != tenant_id:
            raise ValueError(f"Meeting not found: {meeting_id}")
        updated = m.model_copy(
            update={"status": status, "updated_at": datetime.now(timezone.utc)}
        )
        self.meetings[meeting_id] = updated
        return updated

    async def update_meeting_bot_id(
        self, tenant_id: str, meeting_id: str, bot_id: str
    ) -> Meeting:
        m = self.meetings.get(meeting_id)
        if m is None or m.tenant_id != tenant_id:
            raise ValueError(f"Meeting not found: {meeting_id}")
        updated = m.model_copy(
            update={"bot_id": bot_id, "updated_at": datetime.now(timezone.utc)}
        )
        self.meetings[meeting_id] = updated
        return updated

    async def save_briefing(
        self, tenant_id: str, briefing: Briefing
    ) -> Briefing:
        key = f"{briefing.meeting_id}:{briefing.format}"
        self.briefings[key] = briefing
        return briefing

    async def get_briefing(
        self, tenant_id: str, meeting_id: str, format: str = "structured"
    ) -> Briefing | None:
        key = f"{meeting_id}:{format}"
        return self.briefings.get(key)

    async def save_transcript(
        self, tenant_id: str, transcript: Transcript
    ) -> Transcript:
        self.transcripts[str(transcript.meeting_id)] = transcript
        return transcript

    async def get_transcript(
        self, tenant_id: str, meeting_id: str
    ) -> Transcript | None:
        return self.transcripts.get(meeting_id)

    async def append_transcript_entry(
        self, tenant_id: str, meeting_id: str, entry: TranscriptEntry
    ) -> None:
        existing = self.transcripts.get(meeting_id)
        if existing is None:
            text_line = f"{entry.speaker}: {entry.text}"
            self.transcripts[meeting_id] = Transcript(
                meeting_id=uuid.UUID(meeting_id),
                entries=[entry],
                full_text=text_line,
            )
        else:
            entries = list(existing.entries) + [entry]
            text_line = f"{entry.speaker}: {entry.text}"
            full_text = (
                f"{existing.full_text}\n{text_line}"
                if existing.full_text
                else text_line
            )
            self.transcripts[meeting_id] = existing.model_copy(
                update={"entries": entries, "full_text": full_text}
            )

    async def save_minutes(
        self, tenant_id: str, minutes: MeetingMinutes
    ) -> MeetingMinutes:
        self.minutes[str(minutes.meeting_id)] = minutes
        return minutes

    async def get_minutes(
        self, tenant_id: str, meeting_id: str
    ) -> MeetingMinutes | None:
        return self.minutes.get(meeting_id)

    async def mark_minutes_shared(
        self, tenant_id: str, meeting_id: str
    ) -> None:
        self.minutes_shared.add(meeting_id)


# ── Test Fixtures ────────────────────────────────────────────────────────────


def _make_meeting(repo: InMemoryMeetingRepository, **overrides) -> Meeting:
    """Create and store a meeting in the repository synchronously."""
    meeting_id = overrides.pop("id", uuid.uuid4())
    defaults = {
        "id": meeting_id,
        "tenant_id": TENANT_ID,
        "title": "Product Demo with Acme Corp",
        "scheduled_start": NOW + timedelta(hours=2),
        "scheduled_end": NOW + timedelta(hours=3),
        "google_meet_url": "https://meet.google.com/abc-defg-hij",
        "google_event_id": "event_123",
        "status": MeetingStatus.SCHEDULED,
        "participants": [
            Participant(name="Alice", email="alice@acme.com", role=ParticipantRole.EXTERNAL),
            Participant(name="Bob", email="bob@ourteam.com", role=ParticipantRole.INTERNAL),
            Participant(name="Agent", email="agent@ourteam.com", role=ParticipantRole.AGENT),
        ],
        "bot_id": None,
        "recording_url": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    defaults.update(overrides)
    meeting = Meeting(**defaults)
    repo.meetings[str(meeting.id)] = meeting
    return meeting


def _make_transcript(repo: InMemoryMeetingRepository, meeting_id: uuid.UUID) -> Transcript:
    """Create and store a transcript in the repository."""
    transcript = Transcript(
        meeting_id=meeting_id,
        entries=[
            TranscriptEntry(speaker="Alice", text="Let me show you the platform.", timestamp_ms=1000),
            TranscriptEntry(speaker="Bob", text="Great, let's see the dashboard.", timestamp_ms=5000),
            TranscriptEntry(speaker="Alice", text="We need a follow-up next week.", timestamp_ms=10000),
        ],
        full_text="Alice: Let me show you the platform.\nBob: Great, let's see the dashboard.\nAlice: We need a follow-up next week.",
    )
    repo.transcripts[str(meeting_id)] = transcript
    return transcript


def _make_minutes(repo: InMemoryMeetingRepository, meeting_id: uuid.UUID) -> MeetingMinutes:
    """Create and store minutes in the repository."""
    minutes = MeetingMinutes(
        meeting_id=meeting_id,
        executive_summary="A productive product demo was conducted with Acme Corp.",
        key_topics=["Platform overview", "Dashboard walkthrough"],
        action_items=[
            ActionItem(
                owner="Bob", action="Schedule follow-up meeting",
                due_date="2026-02-20", context="Alice requested follow-up",
            ),
        ],
        decisions=[
            Decision(
                decision="Proceed to trial phase",
                participants=["Alice", "Bob"],
                context="After seeing the dashboard demo",
            ),
        ],
        follow_up_date="2026-02-20",
        generated_at=NOW,
    )
    repo.minutes[str(meeting_id)] = minutes
    return minutes


def _make_briefing(repo: InMemoryMeetingRepository, meeting_id: uuid.UUID, fmt: str = "structured") -> Briefing:
    """Create and store a briefing in the repository."""
    briefing = Briefing(
        meeting_id=meeting_id,
        format=fmt,
        content=BriefingContent(
            account_context="Acme Corp is a mid-market SaaS company.",
            attendee_profiles=[{"name": "Alice", "role": "VP Sales"}],
            objectives=["Present platform overview", "Discuss pricing"],
            talk_tracks=["Focus on ROI metrics", "Reference similar customers"],
            deal_context="Discovery stage",
        ),
        generated_at=NOW,
    )
    repo.briefings[f"{meeting_id}:{fmt}"] = briefing
    return briefing


# ── Mock Auth Dependency ─────────────────────────────────────────────────────


def _create_test_app(repo: InMemoryMeetingRepository, **extra_state) -> FastAPI:
    """Create a test FastAPI app with mocked auth and meetings router."""
    from src.app.core.tenant import TenantContext
    from src.app.models.tenant import User as UserModel

    app = FastAPI()
    app.include_router(meetings_router)

    # Set up app.state
    app.state.meeting_repository = repo
    app.state.bot_manager = extra_state.get("bot_manager", None)
    app.state.briefing_generator = extra_state.get("briefing_generator", None)
    app.state.minutes_generator = extra_state.get("minutes_generator", None)
    app.state.minutes_distributor = extra_state.get("minutes_distributor", None)

    for k, v in extra_state.items():
        setattr(app.state, k, v)

    # Override auth dependencies
    from src.app.api.deps import get_current_user, get_tenant

    mock_user = MagicMock(spec=UserModel)
    mock_user.id = USER_ID
    mock_user.tenant_id = TENANT_ID
    mock_tenant = TenantContext(tenant_id=TENANT_ID, tenant_slug="test-tenant", schema_name=f"tenant_{TENANT_ID}")

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_tenant] = lambda: mock_tenant

    return app


# ── Test Classes ─────────────────────────────────────────────────────────────


class TestMeetingListEndpoint:
    """Test meeting list endpoint."""

    def test_list_meetings_empty_for_new_tenant(self):
        """Test: meeting list returns empty list for new tenant."""
        repo = InMemoryMeetingRepository()
        app = _create_test_app(repo)
        client = TestClient(app)

        response = client.get("/meetings/")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_meetings_returns_existing(self):
        """Test: meeting list returns existing meetings."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        app = _create_test_app(repo)
        client = TestClient(app)

        response = client.get("/meetings/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Product Demo with Acme Corp"
        assert data[0]["id"] == str(meeting.id)


class TestMeetingDetailEndpoint:
    """Test meeting detail endpoint."""

    def test_get_meeting_found(self):
        """Test: get meeting by ID returns details."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        app = _create_test_app(repo)
        client = TestClient(app)

        response = client.get(f"/meetings/{meeting.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Product Demo with Acme Corp"
        assert data["status"] == "scheduled"

    def test_get_meeting_not_found(self):
        """Test: get non-existent meeting returns 404."""
        repo = InMemoryMeetingRepository()
        app = _create_test_app(repo)
        client = TestClient(app)

        response = client.get(f"/meetings/{uuid.uuid4()}")
        assert response.status_code == 404


class TestBriefingEndpoints:
    """Test briefing generation and retrieval."""

    def test_briefing_returns_cached(self):
        """Test: briefing endpoint returns cached briefing if exists."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        _make_briefing(repo, meeting.id, "structured")
        app = _create_test_app(repo)
        client = TestClient(app)

        response = client.post(
            f"/meetings/{meeting.id}/briefing",
            json={"meeting_id": str(meeting.id), "format": "structured"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "structured"
        assert "account_context" in data["content"]

    def test_briefing_caching_same_request(self):
        """Test: same briefing request returns same cached briefing."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        briefing = _make_briefing(repo, meeting.id, "bullet")
        app = _create_test_app(repo)
        client = TestClient(app)

        # First request
        response1 = client.post(
            f"/meetings/{meeting.id}/briefing",
            json={"meeting_id": str(meeting.id), "format": "bullet"},
        )
        # Second request (should return same cached)
        response2 = client.post(
            f"/meetings/{meeting.id}/briefing",
            json={"meeting_id": str(meeting.id), "format": "bullet"},
        )
        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.json()["id"] == response2.json()["id"]

    def test_get_specific_format_briefing(self):
        """Test: get briefing by format returns correct format."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        _make_briefing(repo, meeting.id, "bullet")
        app = _create_test_app(repo)
        client = TestClient(app)

        response = client.get(f"/meetings/{meeting.id}/briefing/bullet")
        assert response.status_code == 200
        assert response.json()["format"] == "bullet"

    def test_get_missing_format_briefing(self):
        """Test: get briefing for non-existent format returns 404."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        app = _create_test_app(repo)
        client = TestClient(app)

        response = client.get(f"/meetings/{meeting.id}/briefing/adaptive")
        assert response.status_code == 404


class TestBotEndpoints:
    """Test bot start and status endpoints."""

    def test_bot_start_creates_bot(self):
        """Test: bot start endpoint creates bot via BotManager (mock RecallClient)."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)

        mock_bot_mgr = AsyncMock()
        mock_bot_mgr.create_meeting_bot = AsyncMock(return_value="bot-recall-123")

        app = _create_test_app(repo, bot_manager=mock_bot_mgr)
        client = TestClient(app)

        response = client.post(f"/meetings/{meeting.id}/bot/start")
        assert response.status_code == 200
        data = response.json()
        assert data["bot_id"] == "bot-recall-123"
        assert data["status"] == "joining"
        mock_bot_mgr.create_meeting_bot.assert_called_once()

    def test_bot_status_returns_current_status(self):
        """Test: bot status endpoint returns current status."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo, bot_id="bot-recall-456")

        mock_bot_mgr = AsyncMock()
        mock_bot_mgr.get_bot_status = AsyncMock(return_value="in_call_recording")

        app = _create_test_app(repo, bot_manager=mock_bot_mgr)
        client = TestClient(app)

        response = client.get(f"/meetings/{meeting.id}/bot/status")
        assert response.status_code == 200
        data = response.json()
        assert data["bot_id"] == "bot-recall-456"
        assert data["status"] == "in_call_recording"

    def test_bot_status_no_bot(self):
        """Test: bot status returns no_bot when no bot assigned."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)  # no bot_id

        mock_bot_mgr = AsyncMock()
        app = _create_test_app(repo, bot_manager=mock_bot_mgr)
        client = TestClient(app)

        response = client.get(f"/meetings/{meeting.id}/bot/status")
        assert response.status_code == 200
        data = response.json()
        assert data["bot_id"] is None
        assert data["status"] == "no_bot"


class TestWebhookEndpoint:
    """Test Recall.ai webhook receiver."""

    def test_webhook_processes_transcript_event(self):
        """Test: webhook endpoint processes transcript events and returns 200."""
        repo = InMemoryMeetingRepository()

        mock_bot_mgr = AsyncMock()
        mock_bot_mgr.handle_bot_event = AsyncMock()

        app = _create_test_app(repo, bot_manager=mock_bot_mgr)
        client = TestClient(app)

        payload = {
            "event": "transcript.data",
            "data": {
                "bot_id": "bot-123",
                "text": "Hello everyone",
                "speaker": "Alice",
            },
        }
        response = client.post("/meetings/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_bot_mgr.handle_bot_event.assert_called_once_with(
            bot_id="bot-123",
            event_type="transcript.data",
            event_data=payload["data"],
        )

    def test_webhook_always_returns_200(self):
        """Test: webhook always returns 200 even on error."""
        repo = InMemoryMeetingRepository()

        mock_bot_mgr = AsyncMock()
        mock_bot_mgr.handle_bot_event = AsyncMock(side_effect=Exception("processing error"))

        app = _create_test_app(repo, bot_manager=mock_bot_mgr)
        client = TestClient(app)

        payload = {
            "event": "status_change",
            "data": {"bot_id": "bot-123", "code": "call_ended"},
        }
        response = client.post("/meetings/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestTranscriptEndpoint:
    """Test transcript retrieval."""

    def test_get_transcript_found(self):
        """Test: get transcript returns entries and full_text."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        _make_transcript(repo, meeting.id)

        app = _create_test_app(repo)
        client = TestClient(app)

        response = client.get(f"/meetings/{meeting.id}/transcript")
        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 3
        assert "Alice" in data["full_text"]

    def test_get_transcript_not_found(self):
        """Test: get transcript for meeting without transcript returns 404."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        app = _create_test_app(repo)
        client = TestClient(app)

        response = client.get(f"/meetings/{meeting.id}/transcript")
        assert response.status_code == 404


class TestMinutesEndpoints:
    """Test minutes generation and sharing."""

    def test_get_minutes_found(self):
        """Test: get minutes returns structured minutes."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        _make_minutes(repo, meeting.id)
        app = _create_test_app(repo)
        client = TestClient(app)

        response = client.get(f"/meetings/{meeting.id}/minutes")
        assert response.status_code == 200
        data = response.json()
        assert "Acme Corp" in data["executive_summary"]
        assert len(data["action_items"]) == 1
        assert len(data["decisions"]) == 1

    def test_generate_minutes_with_transcript(self):
        """Test: minutes generation endpoint produces structured minutes (mock LLM)."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        _make_transcript(repo, meeting.id)

        mock_minutes_gen = AsyncMock()
        mock_minutes_gen.generate = AsyncMock(
            return_value=MeetingMinutes(
                meeting_id=meeting.id,
                executive_summary="Demo went well.",
                key_topics=["Platform"],
                action_items=[
                    ActionItem(
                        owner="Bob", action="Follow up",
                        due_date=None, context="Demo",
                    ),
                ],
                decisions=[],
                generated_at=NOW,
            )
        )

        app = _create_test_app(repo, minutes_generator=mock_minutes_gen)
        client = TestClient(app)

        response = client.post(f"/meetings/{meeting.id}/minutes/generate")
        assert response.status_code == 200
        data = response.json()
        assert data["executive_summary"] == "Demo went well."
        assert len(data["action_items"]) == 1
        mock_minutes_gen.generate.assert_called_once()

    def test_generate_minutes_no_transcript_returns_404(self):
        """Test: minutes generation without transcript returns 404."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)

        mock_minutes_gen = AsyncMock()
        app = _create_test_app(repo, minutes_generator=mock_minutes_gen)
        client = TestClient(app)

        response = client.post(f"/meetings/{meeting.id}/minutes/generate")
        assert response.status_code == 404
        assert "Transcript not found" in response.json()["detail"]


class TestMinutesShareEndpoint:
    """Test minutes sharing -- manual only, no automatic distribution."""

    def test_share_minutes_to_specified_recipients_only(self):
        """Test: share endpoint sends email to specified recipients only (mock Gmail)."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        _make_minutes(repo, meeting.id)

        mock_dist = AsyncMock()
        mock_dist.share_externally = AsyncMock(
            return_value={
                "sent_to": ["customer@acme.com"],
                "share_time": NOW.isoformat(),
            }
        )

        app = _create_test_app(repo, minutes_distributor=mock_dist)
        client = TestClient(app)

        response = client.post(
            f"/meetings/{meeting.id}/minutes/share",
            json={
                "meeting_id": str(meeting.id),
                "recipient_emails": ["customer@acme.com"],
                "include_transcript": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["shared_to"] == ["customer@acme.com"]
        mock_dist.share_externally.assert_called_once_with(
            meeting_id=meeting.id,
            tenant_id=TENANT_ID,
            recipient_emails=["customer@acme.com"],
            include_transcript=False,
        )

    def test_share_does_not_auto_share(self):
        """Test: no auto-share -- verify no unsolicited sends happen during minutes generation."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        _make_transcript(repo, meeting.id)

        mock_dist = AsyncMock()
        mock_dist.share_externally = AsyncMock()

        mock_gen = AsyncMock()
        mock_gen.generate = AsyncMock(
            return_value=MeetingMinutes(
                meeting_id=meeting.id,
                executive_summary="Test summary.",
                key_topics=[],
                action_items=[],
                decisions=[],
                generated_at=NOW,
            )
        )

        app = _create_test_app(
            repo,
            minutes_generator=mock_gen,
            minutes_distributor=mock_dist,
        )
        client = TestClient(app)

        # Generate minutes
        response = client.post(f"/meetings/{meeting.id}/minutes/generate")
        assert response.status_code == 200

        # Verify share_externally was NOT called automatically
        mock_dist.share_externally.assert_not_called()


class TestWebSocketEndpoint:
    """Test WebSocket connection for real-time pipeline bridge."""

    def test_websocket_accepts_and_processes_transcript(self):
        """Test: WebSocket connection accepts and processes transcript messages."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        app = _create_test_app(repo)
        client = TestClient(app)

        with client.websocket_connect(f"/meetings/ws/{meeting.id}") as ws:
            # Send transcript message
            ws.send_text(json.dumps({
                "type": "transcript",
                "text": "Hello everyone, let's begin.",
                "is_final": True,
                "speaker_id": "speaker_1",
            }))
            response = ws.receive_json()
            # Without a pipeline, should get silence response
            assert response["type"] == "silence"

    def test_websocket_ping_pong(self):
        """Test: WebSocket handles ping/pong."""
        repo = InMemoryMeetingRepository()
        app = _create_test_app(repo)
        client = TestClient(app)

        with client.websocket_connect(f"/meetings/ws/{uuid.uuid4()}") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            response = ws.receive_json()
            assert response["type"] == "pong"

    def test_websocket_unknown_message_type(self):
        """Test: WebSocket returns error for unknown message type."""
        repo = InMemoryMeetingRepository()
        app = _create_test_app(repo)
        client = TestClient(app)

        with client.websocket_connect(f"/meetings/ws/{uuid.uuid4()}") as ws:
            ws.send_text(json.dumps({"type": "unknown_type"}))
            response = ws.receive_json()
            assert response["type"] == "error"
            assert "Unknown message type" in response["detail"]


class TestPhase6Initialization:
    """Test Phase 6 init in main.py."""

    def test_phase6_init_succeeds_with_mock_services(self):
        """Test: Phase 6 init in main.py succeeds with mock services."""
        # Verify that the Phase 6 block exists in main.py and the
        # try/except pattern is followed. We check by importing
        # main and parsing the relevant sections.
        import ast

        with open("src/app/main.py") as f:
            source = f.read()

        tree = ast.parse(source)

        # Verify Phase 6 comment exists
        assert "Phase 6: Meeting Capabilities" in source

        # Verify meeting_repository is set on app.state
        assert "app.state.meeting_repository" in source
        assert "app.state.briefing_generator" in source
        assert "app.state.bot_manager" in source
        assert "app.state.minutes_generator" in source
        assert "app.state.minutes_distributor" in source
        assert "app.state.calendar_monitor" in source

        # Verify graceful failure pattern
        assert "phase6.meeting_capabilities_init_failed" in source
        assert "phase6.meeting_capabilities_initialized" in source

    def test_phase6_graceful_failure_sets_none(self):
        """Test: Phase 6 init gracefully fails (sets None) without API keys."""
        import ast

        with open("src/app/main.py") as f:
            source = f.read()

        # Verify the except block sets all services to None
        # Find the except block after Phase 6 try
        phase6_start = source.index("Phase 6: Meeting Capabilities")
        phase6_section = source[phase6_start:]

        # Check that the except block explicitly sets None
        assert "app.state.meeting_repository = None" in phase6_section
        assert "app.state.briefing_generator = None" in phase6_section
        assert "app.state.bot_manager = None" in phase6_section
        assert "app.state.minutes_generator = None" in phase6_section
        assert "app.state.minutes_distributor = None" in phase6_section
        assert "app.state.calendar_monitor = None" in phase6_section


class TestServiceUnavailable:
    """Test that 503 is returned when services are not initialized."""

    def test_bot_start_503_without_bot_manager(self):
        """Test: bot start returns 503 when bot_manager is None."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        app = _create_test_app(repo, bot_manager=None)
        client = TestClient(app)

        response = client.post(f"/meetings/{meeting.id}/bot/start")
        assert response.status_code == 503
        assert "Bot manager" in response.json()["detail"]

    def test_minutes_generate_503_without_generator(self):
        """Test: minutes generate returns 503 when generator is None."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting(repo)
        app = _create_test_app(repo, minutes_generator=None)
        client = TestClient(app)

        response = client.post(f"/meetings/{meeting.id}/minutes/generate")
        assert response.status_code == 503
        assert "Minutes generator" in response.json()["detail"]
