"""Tests for CalendarMonitor and BriefingGenerator (Phase 6, Plan 02).

Tests the pre-meeting pipeline: calendar monitoring for agent meeting invites
and multi-format briefing generation. Uses InMemoryMeetingRepository from
test_meeting_foundation.py and mock calendar service doubles.

Minimum 10 tests required per plan specification.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.meetings.calendar.briefing import (
    BriefingExtraction,
    BriefingGenerator,
)
from src.app.meetings.calendar.monitor import (
    BRIEFING_LEAD_TIME_HOURS,
    EARLY_JOIN_MINUTES,
    CalendarMonitor,
    _parse_event_end,
    _parse_event_start,
)
from src.app.meetings.schemas import (
    Briefing,
    BriefingContent,
    Meeting,
    MeetingCreate,
    MeetingStatus,
    Participant,
    ParticipantRole,
)

# ── Test Doubles ─────────────────────────────────────────────────────────────


class InMemoryMeetingRepository:
    """Minimal in-memory repository double for CalendarMonitor/BriefingGenerator tests.

    Mirrors MeetingRepository interface for meeting and briefing operations.
    """

    def __init__(self) -> None:
        self.meetings: dict[str, Meeting] = {}
        self.briefings: dict[str, Briefing] = {}

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


TENANT_ID = str(uuid.uuid4())
AGENT_EMAIL = "agent@acme.com"


def _make_calendar_event(
    event_id: str = "evt-1",
    summary: str = "Sales Demo",
    start_offset_hours: float = 1.5,
    duration_hours: float = 1.0,
    attendees: list[dict] | None = None,
    has_meet: bool = True,
) -> dict:
    """Build a mock Google Calendar event dict."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=start_offset_hours)
    end = start + timedelta(hours=duration_hours)

    event: dict = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "attendees": attendees
        or [
            {"email": AGENT_EMAIL, "displayName": "Sales Agent"},
            {"email": "customer@external.com", "displayName": "Jane Customer"},
            {"email": "rep@acme.com", "displayName": "Bob Rep"},
        ],
    }

    if has_meet:
        event["conferenceData"] = {
            "entryPoints": [
                {"entryPointType": "video", "uri": "https://meet.google.com/abc-xyz"}
            ]
        }

    return event


def _make_mock_calendar_service(events: list[dict] | None = None):
    """Create a mock GoogleCalendarService that returns given events."""
    from src.app.services.gsuite.calendar import GoogleCalendarService

    mock = MagicMock(spec=GoogleCalendarService)
    mock.list_upcoming_events.return_value = events or []
    mock.has_google_meet_link = GoogleCalendarService.has_google_meet_link
    mock.get_meet_url = GoogleCalendarService.get_meet_url
    mock.get_attendees = GoogleCalendarService.get_attendees
    mock.is_agent_invited = GoogleCalendarService.is_agent_invited
    return mock


def _make_meeting(
    tenant_id: str = TENANT_ID,
    title: str = "Sales Demo",
    offset_hours: float = 1.5,
    status: MeetingStatus = MeetingStatus.SCHEDULED,
    participants: list[Participant] | None = None,
) -> Meeting:
    """Build a Meeting schema for testing."""
    now = datetime.now(timezone.utc)
    return Meeting(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        title=title,
        scheduled_start=now + timedelta(hours=offset_hours),
        scheduled_end=now + timedelta(hours=offset_hours + 1),
        google_meet_url="https://meet.google.com/abc-xyz",
        google_event_id=f"evt-{uuid.uuid4().hex[:8]}",
        status=status,
        participants=participants
        or [
            Participant(name="Sales Agent", email=AGENT_EMAIL, role=ParticipantRole.AGENT),
            Participant(
                name="Jane Customer",
                email="customer@external.com",
                role=ParticipantRole.EXTERNAL,
                title="VP Sales",
                company="ExternalCorp",
            ),
            Participant(
                name="Bob Rep",
                email="rep@acme.com",
                role=ParticipantRole.INTERNAL,
            ),
        ],
        created_at=now,
        updated_at=now,
    )


# ── CalendarMonitor Tests ────────────────────────────────────────────────────


class TestCalendarMonitorCheckUpcoming:
    """Test CalendarMonitor.check_upcoming_meetings."""

    @pytest.mark.asyncio
    async def test_discovers_new_meeting_from_calendar(self):
        """Events with agent invite and Meet link create meeting records."""
        event = _make_calendar_event()
        calendar_service = _make_mock_calendar_service([event])
        repo = InMemoryMeetingRepository()
        briefing_gen = MagicMock()

        monitor = CalendarMonitor(
            calendar_service=calendar_service,
            repository=repo,
            briefing_generator=briefing_gen,
        )

        meetings = await monitor.check_upcoming_meetings(AGENT_EMAIL, TENANT_ID)

        assert len(meetings) == 1
        assert meetings[0].title == "Sales Demo"
        assert meetings[0].google_event_id == "evt-1"
        assert len(repo.meetings) == 1

    @pytest.mark.asyncio
    async def test_skips_events_without_meet_link(self):
        """Events without Google Meet link are filtered out."""
        event = _make_calendar_event(has_meet=False)
        calendar_service = _make_mock_calendar_service([event])
        repo = InMemoryMeetingRepository()
        briefing_gen = MagicMock()

        monitor = CalendarMonitor(
            calendar_service=calendar_service,
            repository=repo,
            briefing_generator=briefing_gen,
        )

        meetings = await monitor.check_upcoming_meetings(AGENT_EMAIL, TENANT_ID)

        assert len(meetings) == 0
        assert len(repo.meetings) == 0

    @pytest.mark.asyncio
    async def test_skips_already_tracked_meetings(self):
        """Already-tracked meetings are returned but not re-created."""
        event = _make_calendar_event()
        calendar_service = _make_mock_calendar_service([event])
        repo = InMemoryMeetingRepository()
        briefing_gen = MagicMock()

        monitor = CalendarMonitor(
            calendar_service=calendar_service,
            repository=repo,
            briefing_generator=briefing_gen,
        )

        # First call creates the meeting
        first_result = await monitor.check_upcoming_meetings(AGENT_EMAIL, TENANT_ID)
        assert len(first_result) == 1
        assert len(repo.meetings) == 1

        # Second call returns it but doesn't duplicate
        second_result = await monitor.check_upcoming_meetings(AGENT_EMAIL, TENANT_ID)
        assert len(second_result) == 1
        assert len(repo.meetings) == 1  # Still only 1

    @pytest.mark.asyncio
    async def test_handles_empty_calendar(self):
        """Empty calendar returns empty list."""
        calendar_service = _make_mock_calendar_service([])
        repo = InMemoryMeetingRepository()
        briefing_gen = MagicMock()

        monitor = CalendarMonitor(
            calendar_service=calendar_service,
            repository=repo,
            briefing_generator=briefing_gen,
        )

        meetings = await monitor.check_upcoming_meetings(AGENT_EMAIL, TENANT_ID)
        assert meetings == []


class TestCalendarMonitorClassifyAttendees:
    """Test CalendarMonitor._classify_attendees."""

    def test_classifies_internal_external_agent(self):
        """Attendees are classified by email domain and agent email."""
        attendees = [
            {"email": AGENT_EMAIL, "name": "Agent"},
            {"email": "rep@acme.com", "name": "Rep"},
            {"email": "customer@external.com", "name": "Customer"},
        ]

        participants = CalendarMonitor._classify_attendees(
            attendees, "acme.com", AGENT_EMAIL
        )

        assert len(participants) == 3

        roles = {p.email: p.role for p in participants}
        assert roles[AGENT_EMAIL] == ParticipantRole.AGENT
        assert roles["rep@acme.com"] == ParticipantRole.INTERNAL
        assert roles["customer@external.com"] == ParticipantRole.EXTERNAL

    def test_all_external_when_no_domain(self):
        """Without internal domain, non-agent attendees are all EXTERNAL."""
        attendees = [
            {"email": "user@company.com", "name": "User"},
        ]

        participants = CalendarMonitor._classify_attendees(
            attendees, "", "agent@other.com"
        )

        assert len(participants) == 1
        assert participants[0].role == ParticipantRole.EXTERNAL


class TestCalendarMonitorProcessMeetings:
    """Test CalendarMonitor.process_upcoming_meetings and last-minute handling."""

    @pytest.mark.asyncio
    async def test_triggers_briefing_for_meeting_within_lead_time(self):
        """Meeting starting within 2 hours triggers briefing generation."""
        event = _make_calendar_event(start_offset_hours=1.0)
        calendar_service = _make_mock_calendar_service([event])
        repo = InMemoryMeetingRepository()

        briefing_gen = MagicMock()
        briefing_gen.generate_all_formats = AsyncMock(return_value=[])

        monitor = CalendarMonitor(
            calendar_service=calendar_service,
            repository=repo,
            briefing_generator=briefing_gen,
        )

        await monitor.process_upcoming_meetings(AGENT_EMAIL, TENANT_ID)

        # Briefing generator should have been called
        briefing_gen.generate_all_formats.assert_called_once()

    @pytest.mark.asyncio
    async def test_last_minute_meeting_gets_immediate_briefing(self):
        """Meeting added less than 2 hours before start gets immediate briefing."""
        # Meeting starting in 30 minutes (well within lead time)
        event = _make_calendar_event(start_offset_hours=0.5)
        calendar_service = _make_mock_calendar_service([event])
        repo = InMemoryMeetingRepository()

        briefing_gen = MagicMock()
        briefing_gen.generate_all_formats = AsyncMock(return_value=[])

        monitor = CalendarMonitor(
            calendar_service=calendar_service,
            repository=repo,
            briefing_generator=briefing_gen,
        )

        await monitor.process_upcoming_meetings(AGENT_EMAIL, TENANT_ID)

        # Should generate briefing immediately for last-minute meeting
        briefing_gen.generate_all_formats.assert_called_once()

    @pytest.mark.asyncio
    async def test_graceful_error_handling_per_meeting(self):
        """Errors on one meeting don't prevent processing others."""
        event1 = _make_calendar_event(event_id="evt-fail", start_offset_hours=1.0)
        event2 = _make_calendar_event(event_id="evt-ok", start_offset_hours=1.5)
        calendar_service = _make_mock_calendar_service([event1, event2])
        repo = InMemoryMeetingRepository()

        call_count = 0

        async def generate_with_error(meeting, tenant_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated failure")
            return []

        briefing_gen = MagicMock()
        briefing_gen.generate_all_formats = AsyncMock(side_effect=generate_with_error)

        monitor = CalendarMonitor(
            calendar_service=calendar_service,
            repository=repo,
            briefing_generator=briefing_gen,
        )

        # Should not raise -- errors are caught per-meeting
        await monitor.process_upcoming_meetings(AGENT_EMAIL, TENANT_ID)

        # Both meetings should have been attempted
        assert call_count == 2


# ── BriefingGenerator Tests ──────────────────────────────────────────────────


class TestBriefingGeneratorGenerate:
    """Test BriefingGenerator.generate_briefing."""

    @pytest.mark.asyncio
    async def test_generates_valid_briefing_schema(self):
        """generate_briefing produces a valid Briefing schema."""
        repo = InMemoryMeetingRepository()
        generator = BriefingGenerator(repository=repo)
        meeting = _make_meeting()

        briefing = await generator.generate_briefing(meeting, TENANT_ID, format="structured")

        assert isinstance(briefing, Briefing)
        assert briefing.meeting_id == meeting.id
        assert briefing.format == "structured"
        assert isinstance(briefing.content, BriefingContent)
        assert briefing.generated_at is not None

    @pytest.mark.asyncio
    async def test_briefing_includes_account_context(self):
        """Briefing content includes account context from participants."""
        repo = InMemoryMeetingRepository()
        generator = BriefingGenerator(repository=repo)
        meeting = _make_meeting()

        briefing = await generator.generate_briefing(meeting, TENANT_ID)

        # Account context should mention external company
        assert "ExternalCorp" in briefing.content.account_context

    @pytest.mark.asyncio
    async def test_briefing_includes_attendee_profiles(self):
        """Briefing includes attendee profiles (excluding agent)."""
        repo = InMemoryMeetingRepository()
        generator = BriefingGenerator(repository=repo)
        meeting = _make_meeting()

        briefing = await generator.generate_briefing(meeting, TENANT_ID)

        profiles = briefing.content.attendee_profiles
        # Agent should be excluded, customer and rep included
        emails = [p["email"] for p in profiles]
        assert AGENT_EMAIL not in emails
        assert "customer@external.com" in emails
        assert "rep@acme.com" in emails

    @pytest.mark.asyncio
    async def test_briefing_has_objectives_and_talk_tracks(self):
        """Briefing includes objectives and talk tracks (rule-based fallback)."""
        repo = InMemoryMeetingRepository()
        generator = BriefingGenerator(repository=repo)  # No LLM service
        meeting = _make_meeting()

        briefing = await generator.generate_briefing(meeting, TENANT_ID)

        assert len(briefing.content.objectives) >= 3
        assert len(briefing.content.talk_tracks) >= 3

    @pytest.mark.asyncio
    async def test_saves_briefing_to_repository(self):
        """Generated briefing is persisted in repository."""
        repo = InMemoryMeetingRepository()
        generator = BriefingGenerator(repository=repo)
        meeting = _make_meeting()

        briefing = await generator.generate_briefing(meeting, TENANT_ID)

        saved = await repo.get_briefing(TENANT_ID, str(meeting.id), format="structured")
        assert saved is not None
        assert saved.meeting_id == meeting.id


class TestBriefingGeneratorFormats:
    """Test BriefingGenerator format renderers."""

    def test_structured_briefing_renders_all_sections(self):
        """Structured format includes all expected Markdown sections."""
        content = BriefingContent(
            account_context="Meeting with ExternalCorp.",
            attendee_profiles=[
                {"name": "Jane", "title": "VP", "company": "ExternalCorp", "role": "external"}
            ],
            objectives=["Explore pain points", "Map decision makers"],
            talk_tracks=["Industry trends", "Pain funnel approach"],
            deal_context="Discovery stage, initial engagement",
        )

        result = BriefingGenerator._build_structured_briefing(content)

        assert "## Account Context" in result
        assert "## Attendee Profiles" in result
        assert "## Deal Status" in result
        assert "## Objectives" in result
        assert "## Suggested Talk Tracks" in result
        assert "ExternalCorp" in result
        assert "Jane" in result

    def test_bullet_briefing_is_concise(self):
        """Bullet format produces concise output."""
        content = BriefingContent(
            account_context="Meeting with ExternalCorp.",
            attendee_profiles=[
                {"name": "Jane", "title": "VP", "company": "ExternalCorp", "role": "external"}
            ],
            objectives=["Explore pain points"],
            talk_tracks=["Industry trends"],
        )

        result = BriefingGenerator._build_bullet_briefing(content)

        assert "Account:" in result
        assert "Attendees:" in result
        assert "Key objectives:" in result
        assert "Talk tracks:" in result
        # Bullet format should be shorter than structured
        structured = BriefingGenerator._build_structured_briefing(content)
        assert len(result) <= len(structured)

    def test_adaptive_briefing_detailed_for_first_meeting(self):
        """Adaptive format is detailed when is_first_meeting=True."""
        content = BriefingContent(
            account_context="Meeting with ExternalCorp.",
            attendee_profiles=[
                {"name": "Jane", "title": "VP", "company": "ExternalCorp", "role": "external"}
            ],
            objectives=["Explore pain points"],
            talk_tracks=["Industry trends"],
            deal_context="Discovery stage",
        )

        result = BriefingGenerator._build_adaptive_briefing(content, is_first_meeting=True)

        assert "# First Meeting Briefing" in result
        assert "## Who You're Meeting" in result
        assert "## Account Background" in result
        assert "### Jane" in result

    def test_adaptive_briefing_brief_for_ongoing(self):
        """Adaptive format is brief when is_first_meeting=False."""
        content = BriefingContent(
            account_context="Meeting with ExternalCorp.",
            attendee_profiles=[
                {"name": "Jane", "title": "VP", "company": "ExternalCorp", "role": "external"}
            ],
            objectives=["Obj 1", "Obj 2", "Obj 3", "Obj 4", "Obj 5"],
            talk_tracks=["Track 1", "Track 2", "Track 3", "Track 4", "Track 5"],
        )

        result = BriefingGenerator._build_adaptive_briefing(content, is_first_meeting=False)

        assert "# Follow-up Meeting Brief" in result
        # Brief format limits to top 3
        assert "Obj 4" not in result
        assert "Track 4" not in result


class TestBriefingGeneratorAllFormats:
    """Test BriefingGenerator.generate_all_formats."""

    @pytest.mark.asyncio
    async def test_generates_all_three_formats(self):
        """generate_all_formats produces exactly 3 briefings."""
        repo = InMemoryMeetingRepository()
        generator = BriefingGenerator(repository=repo)
        meeting = _make_meeting()

        briefings = await generator.generate_all_formats(meeting, TENANT_ID)

        assert len(briefings) == 3
        formats = {b.format for b in briefings}
        assert formats == {"structured", "bullet", "adaptive"}

    @pytest.mark.asyncio
    async def test_all_formats_saved_to_repository(self):
        """All 3 format variants are persisted in repository."""
        repo = InMemoryMeetingRepository()
        generator = BriefingGenerator(repository=repo)
        meeting = _make_meeting()

        await generator.generate_all_formats(meeting, TENANT_ID)

        for fmt in ("structured", "bullet", "adaptive"):
            saved = await repo.get_briefing(TENANT_ID, str(meeting.id), format=fmt)
            assert saved is not None, f"Missing briefing format: {fmt}"


class TestBriefingGeneratorFallback:
    """Test BriefingGenerator rule-based fallback."""

    @pytest.mark.asyncio
    async def test_fallback_when_llm_unavailable(self):
        """Rule-based objectives work when no LLM service configured."""
        repo = InMemoryMeetingRepository()
        generator = BriefingGenerator(repository=repo, llm_service=None)
        meeting = _make_meeting()

        briefing = await generator.generate_briefing(meeting, TENANT_ID)

        # Should still have objectives and talk tracks from rule-based engine
        assert len(briefing.content.objectives) >= 3
        assert len(briefing.content.talk_tracks) >= 3

    @pytest.mark.asyncio
    async def test_fallback_when_llm_fails(self):
        """Falls back to rule-based when LLM raises exception."""
        repo = InMemoryMeetingRepository()
        # Provide an LLM service that fails
        mock_llm = MagicMock()
        generator = BriefingGenerator(repository=repo, llm_service=mock_llm)

        # Patch the LLM method to fail
        async def fail(*args, **kwargs):
            raise RuntimeError("LLM unavailable")

        generator._llm_generate_objectives = fail

        meeting = _make_meeting()
        briefing = await generator.generate_briefing(meeting, TENANT_ID)

        # Should still produce valid content via fallback
        assert len(briefing.content.objectives) >= 3
        assert len(briefing.content.talk_tracks) >= 3

    def test_rule_based_objectives_include_meeting_title(self):
        """Rule-based fallback includes meeting title in objectives."""
        objectives, talk_tracks = BriefingGenerator._rule_based_objectives(
            "discovery", "Q1 Pipeline Review"
        )

        assert any("Q1 Pipeline Review" in obj for obj in objectives)
        assert len(talk_tracks) >= 3


class TestBriefingExtraction:
    """Test BriefingExtraction Pydantic model."""

    def test_extraction_model_constructs(self):
        """BriefingExtraction model validates correctly."""
        extraction = BriefingExtraction(
            objectives=["Explore pain", "Map stakeholders"],
            talk_tracks=["Industry trends", "Competitive landscape"],
            account_summary="Tech company in growth stage",
        )

        assert len(extraction.objectives) == 2
        assert len(extraction.talk_tracks) == 2
        assert extraction.account_summary == "Tech company in growth stage"

    def test_extraction_model_defaults(self):
        """BriefingExtraction has sensible defaults."""
        extraction = BriefingExtraction(
            objectives=["obj1"],
            talk_tracks=["track1"],
        )
        assert extraction.account_summary == ""


class TestHelperFunctions:
    """Test helper functions for event parsing."""

    def test_parse_event_start_datetime(self):
        """Parses dateTime format from event start."""
        event = {"start": {"dateTime": "2026-02-15T10:00:00+00:00"}}
        result = _parse_event_start(event)
        assert result is not None
        assert result.year == 2026

    def test_parse_event_start_date_only(self):
        """Parses date-only format from all-day events."""
        event = {"start": {"date": "2026-02-15"}}
        result = _parse_event_start(event)
        assert result is not None
        assert result.year == 2026

    def test_parse_event_start_missing(self):
        """Returns None for missing start time."""
        event = {"start": {}}
        result = _parse_event_start(event)
        assert result is None

    def test_parse_event_end(self):
        """Parses end time from event."""
        event = {"end": {"dateTime": "2026-02-15T11:00:00+00:00"}}
        result = _parse_event_end(event)
        assert result is not None


class TestCalendarMonitorIsFirstMeeting:
    """Test BriefingGenerator._is_first_meeting_with_attendees."""

    @pytest.mark.asyncio
    async def test_first_meeting_with_new_attendees(self):
        """Returns True when no prior meetings with overlapping attendees."""
        repo = InMemoryMeetingRepository()
        generator = BriefingGenerator(repository=repo)
        meeting = _make_meeting()

        result = await generator._is_first_meeting_with_attendees(meeting, TENANT_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_not_first_meeting_with_same_attendees(self):
        """Returns False when prior meetings exist with same external attendees."""
        repo = InMemoryMeetingRepository()
        generator = BriefingGenerator(repository=repo)

        # Create a prior meeting with overlapping external attendee
        prior_meeting = _make_meeting(offset_hours=-24)  # Yesterday
        repo.meetings[str(prior_meeting.id)] = prior_meeting

        # Current meeting with same external attendee
        meeting = _make_meeting(offset_hours=1.5)

        result = await generator._is_first_meeting_with_attendees(meeting, TENANT_ID)
        assert result is False
