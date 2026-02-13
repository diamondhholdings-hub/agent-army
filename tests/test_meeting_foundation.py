"""Unit tests for Phase 6 meeting foundation: schemas, repository, and calendar service.

Tests Pydantic schema construction and validation, MeetingRepository CRUD
via InMemoryMeetingRepository test double, and GoogleCalendarService
static methods with mock event data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

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
    MeetingBriefingRequest,
    MinutesShareRequest,
)
from src.app.services.gsuite.calendar import GoogleCalendarService


# ── Fixtures ─────────────────────────────────────────────────────────────────


TENANT_ID = str(uuid.uuid4())
MEETING_ID = uuid.uuid4()
NOW = datetime.now(timezone.utc)


def _make_participant(**overrides) -> Participant:
    defaults = {
        "name": "Alice Johnson",
        "email": "alice@example.com",
        "role": ParticipantRole.EXTERNAL,
    }
    defaults.update(overrides)
    return Participant(**defaults)


def _make_meeting_create(**overrides) -> MeetingCreate:
    defaults = {
        "title": "Sales Discovery Call",
        "scheduled_start": NOW,
        "scheduled_end": NOW,
        "google_meet_url": "https://meet.google.com/abc-defg-hij",
        "google_event_id": "evt_12345",
        "participants": [_make_participant()],
    }
    defaults.update(overrides)
    return MeetingCreate(**defaults)


def _make_calendar_event(
    attendees: list[dict] | None = None,
    has_meet: bool = True,
    meet_url: str = "https://meet.google.com/abc-defg-hij",
) -> dict:
    """Create a mock Google Calendar event dict."""
    event: dict = {
        "id": "evt_12345",
        "summary": "Sales Discovery Call",
        "start": {"dateTime": NOW.isoformat()},
        "end": {"dateTime": NOW.isoformat()},
    }
    if attendees is not None:
        event["attendees"] = attendees
    if has_meet:
        event["conferenceData"] = {
            "entryPoints": [
                {
                    "entryPointType": "video",
                    "uri": meet_url,
                    "label": "meet.google.com/abc-defg-hij",
                },
            ],
        }
    return event


# ── InMemoryMeetingRepository ────────────────────────────────────────────────


class InMemoryMeetingRepository:
    """In-memory test double for MeetingRepository.

    Mirrors the MeetingRepository interface using dicts for storage.
    Used for fast unit testing without database dependency.
    """

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
        # Create new instance with updated status
        updated = m.model_copy(update={"status": status, "updated_at": datetime.now(timezone.utc)})
        self.meetings[meeting_id] = updated
        return updated

    async def update_meeting_bot_id(
        self, tenant_id: str, meeting_id: str, bot_id: str
    ) -> Meeting:
        m = self.meetings.get(meeting_id)
        if m is None or m.tenant_id != tenant_id:
            raise ValueError(f"Meeting not found: {meeting_id}")
        updated = m.model_copy(update={"bot_id": bot_id, "updated_at": datetime.now(timezone.utc)})
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
            full_text = f"{existing.full_text}\n{text_line}" if existing.full_text else text_line
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


# ── Schema Tests ─────────────────────────────────────────────────────────────


class TestPydanticSchemas:
    """Test Pydantic schema construction and validation."""

    def test_participant_constructs(self):
        p = Participant(name="Alice", email="alice@example.com")
        assert p.role == ParticipantRole.EXTERNAL  # default
        assert p.title is None
        assert p.company is None

    def test_participant_with_all_fields(self):
        p = Participant(
            name="Bob",
            email="bob@acme.com",
            role=ParticipantRole.INTERNAL,
            title="VP Sales",
            company="Acme Corp",
        )
        assert p.role == ParticipantRole.INTERNAL
        assert p.title == "VP Sales"

    def test_action_item_constructs(self):
        ai = ActionItem(
            owner="Alice",
            action="Send proposal",
            due_date="2026-03-01",
            context="Discussed during pricing section",
        )
        assert ai.owner == "Alice"
        assert ai.due_date == "2026-03-01"

    def test_decision_constructs(self):
        d = Decision(
            decision="Go with Enterprise plan",
            participants=["Alice", "Bob"],
            context="Agreed after evaluating pricing tiers",
        )
        assert len(d.participants) == 2

    def test_briefing_content_constructs(self):
        bc = BriefingContent(
            account_context="Large enterprise account",
            attendee_profiles=[{"name": "Alice", "title": "CTO"}],
            objectives=["Discuss pricing"],
            talk_tracks=["Lead with ROI"],
            deal_context="In discovery phase",
        )
        assert bc.account_context == "Large enterprise account"
        assert len(bc.attendee_profiles) == 1

    def test_meeting_status_enum(self):
        assert MeetingStatus.SCHEDULED.value == "scheduled"
        assert MeetingStatus.MINUTES_GENERATED.value == "minutes_generated"

    def test_meeting_create_constructs(self):
        mc = _make_meeting_create()
        assert mc.title == "Sales Discovery Call"
        assert len(mc.participants) == 1

    def test_transcript_entry_constructs(self):
        entry = TranscriptEntry(
            speaker="Alice",
            text="Hello everyone",
            timestamp_ms=1000,
            is_final=True,
        )
        assert entry.speaker == "Alice"
        assert entry.timestamp_ms == 1000

    def test_meeting_minutes_constructs(self):
        minutes = MeetingMinutes(
            meeting_id=MEETING_ID,
            executive_summary="Productive discovery call.",
            key_topics=["Pricing", "Timeline"],
            action_items=[
                ActionItem(
                    owner="Alice",
                    action="Send proposal",
                    context="Pricing discussion",
                ),
            ],
            decisions=[
                Decision(
                    decision="Move to evaluation",
                    participants=["Alice", "Bob"],
                    context="Both agreed",
                ),
            ],
            generated_at=NOW,
        )
        assert len(minutes.action_items) == 1
        assert len(minutes.decisions) == 1
        assert minutes.follow_up_date is None

    def test_meeting_briefing_request(self):
        req = MeetingBriefingRequest(meeting_id=MEETING_ID)
        assert req.format == "structured"

    def test_minutes_share_request(self):
        req = MinutesShareRequest(
            meeting_id=MEETING_ID,
            recipient_emails=["alice@example.com"],
        )
        assert req.include_transcript is False

    def test_participant_role_enum_values(self):
        assert ParticipantRole.INTERNAL.value == "internal"
        assert ParticipantRole.EXTERNAL.value == "external"
        assert ParticipantRole.AGENT.value == "agent"


# ── Repository Tests ─────────────────────────────────────────────────────────


class TestInMemoryMeetingRepository:
    """Test MeetingRepository CRUD via in-memory test double."""

    @pytest.fixture
    def repo(self) -> InMemoryMeetingRepository:
        return InMemoryMeetingRepository()

    async def test_create_and_get_meeting(self, repo: InMemoryMeetingRepository):
        data = _make_meeting_create()
        meeting = await repo.create_meeting(TENANT_ID, data)
        assert meeting.title == "Sales Discovery Call"
        assert meeting.status == MeetingStatus.SCHEDULED

        fetched = await repo.get_meeting(TENANT_ID, str(meeting.id))
        assert fetched is not None
        assert fetched.title == meeting.title

    async def test_get_meeting_by_event_id(self, repo: InMemoryMeetingRepository):
        data = _make_meeting_create(google_event_id="unique_evt_001")
        meeting = await repo.create_meeting(TENANT_ID, data)

        found = await repo.get_meeting_by_event_id(TENANT_ID, "unique_evt_001")
        assert found is not None
        assert found.id == meeting.id

        not_found = await repo.get_meeting_by_event_id(TENANT_ID, "nonexistent")
        assert not_found is None

    async def test_get_meeting_not_found(self, repo: InMemoryMeetingRepository):
        result = await repo.get_meeting(TENANT_ID, str(uuid.uuid4()))
        assert result is None

    async def test_update_meeting_status(self, repo: InMemoryMeetingRepository):
        data = _make_meeting_create()
        meeting = await repo.create_meeting(TENANT_ID, data)

        updated = await repo.update_meeting_status(
            TENANT_ID, str(meeting.id), MeetingStatus.IN_PROGRESS
        )
        assert updated.status == MeetingStatus.IN_PROGRESS

    async def test_update_meeting_bot_id(self, repo: InMemoryMeetingRepository):
        data = _make_meeting_create()
        meeting = await repo.create_meeting(TENANT_ID, data)

        updated = await repo.update_meeting_bot_id(
            TENANT_ID, str(meeting.id), "recall_bot_123"
        )
        assert updated.bot_id == "recall_bot_123"

    async def test_save_and_get_briefing(self, repo: InMemoryMeetingRepository):
        briefing = Briefing(
            meeting_id=MEETING_ID,
            format="structured",
            content=BriefingContent(
                account_context="Test account",
                objectives=["Discuss pricing"],
            ),
            generated_at=NOW,
        )
        saved = await repo.save_briefing(TENANT_ID, briefing)
        assert saved.format == "structured"

        fetched = await repo.get_briefing(TENANT_ID, str(MEETING_ID), "structured")
        assert fetched is not None
        assert fetched.content.account_context == "Test account"

    async def test_save_and_get_transcript(self, repo: InMemoryMeetingRepository):
        transcript = Transcript(
            meeting_id=MEETING_ID,
            entries=[
                TranscriptEntry(speaker="Alice", text="Hello", timestamp_ms=0),
                TranscriptEntry(speaker="Bob", text="Hi there", timestamp_ms=1500),
            ],
            full_text="Alice: Hello\nBob: Hi there",
        )
        saved = await repo.save_transcript(TENANT_ID, transcript)
        assert len(saved.entries) == 2

        fetched = await repo.get_transcript(TENANT_ID, str(MEETING_ID))
        assert fetched is not None
        assert "Hello" in fetched.full_text

    async def test_append_transcript_entry_creates_new(
        self, repo: InMemoryMeetingRepository
    ):
        mid = str(uuid.uuid4())
        entry = TranscriptEntry(speaker="Alice", text="Hello", timestamp_ms=0)
        await repo.append_transcript_entry(TENANT_ID, mid, entry)

        transcript = await repo.get_transcript(TENANT_ID, mid)
        assert transcript is not None
        assert len(transcript.entries) == 1

    async def test_append_transcript_entry_appends(
        self, repo: InMemoryMeetingRepository
    ):
        mid = str(uuid.uuid4())
        entry1 = TranscriptEntry(speaker="Alice", text="Hello", timestamp_ms=0)
        entry2 = TranscriptEntry(speaker="Bob", text="Hi", timestamp_ms=1000)
        await repo.append_transcript_entry(TENANT_ID, mid, entry1)
        await repo.append_transcript_entry(TENANT_ID, mid, entry2)

        transcript = await repo.get_transcript(TENANT_ID, mid)
        assert transcript is not None
        assert len(transcript.entries) == 2
        assert "Bob: Hi" in transcript.full_text

    async def test_save_and_get_minutes(self, repo: InMemoryMeetingRepository):
        minutes = MeetingMinutes(
            meeting_id=MEETING_ID,
            executive_summary="Good meeting.",
            key_topics=["Pricing"],
            action_items=[
                ActionItem(owner="Alice", action="Send doc", context="Pricing"),
            ],
            decisions=[],
            generated_at=NOW,
        )
        saved = await repo.save_minutes(TENANT_ID, minutes)
        assert saved.executive_summary == "Good meeting."

        fetched = await repo.get_minutes(TENANT_ID, str(MEETING_ID))
        assert fetched is not None
        assert len(fetched.action_items) == 1

    async def test_mark_minutes_shared(self, repo: InMemoryMeetingRepository):
        mid = str(MEETING_ID)
        await repo.mark_minutes_shared(TENANT_ID, mid)
        assert mid in repo.minutes_shared

    async def test_update_nonexistent_meeting_raises(
        self, repo: InMemoryMeetingRepository
    ):
        with pytest.raises(ValueError, match="Meeting not found"):
            await repo.update_meeting_status(
                TENANT_ID, str(uuid.uuid4()), MeetingStatus.ENDED
            )


# ── Calendar Service Tests ───────────────────────────────────────────────────


class TestGoogleCalendarService:
    """Test GoogleCalendarService static helper methods with mock event data."""

    def test_is_agent_invited_true(self):
        event = _make_calendar_event(
            attendees=[
                {"email": "agent@company.com", "displayName": "Sales Agent"},
                {"email": "customer@acme.com", "displayName": "Customer"},
            ]
        )
        assert GoogleCalendarService.is_agent_invited(event, "agent@company.com") is True

    def test_is_agent_invited_false(self):
        event = _make_calendar_event(
            attendees=[
                {"email": "customer@acme.com", "displayName": "Customer"},
            ]
        )
        assert GoogleCalendarService.is_agent_invited(event, "agent@company.com") is False

    def test_is_agent_invited_case_insensitive(self):
        event = _make_calendar_event(
            attendees=[
                {"email": "Agent@Company.com"},
            ]
        )
        assert GoogleCalendarService.is_agent_invited(event, "agent@company.com") is True

    def test_is_agent_invited_no_attendees(self):
        event = _make_calendar_event(attendees=None)
        assert GoogleCalendarService.is_agent_invited(event, "agent@company.com") is False

    def test_has_google_meet_link_true(self):
        event = _make_calendar_event(has_meet=True)
        assert GoogleCalendarService.has_google_meet_link(event) is True

    def test_has_google_meet_link_false(self):
        event = _make_calendar_event(has_meet=False)
        assert GoogleCalendarService.has_google_meet_link(event) is False

    def test_has_google_meet_link_no_conference_data(self):
        event = {"id": "evt_1", "summary": "No Meet"}
        assert GoogleCalendarService.has_google_meet_link(event) is False

    def test_get_meet_url_returns_url(self):
        url = "https://meet.google.com/abc-defg-hij"
        event = _make_calendar_event(has_meet=True, meet_url=url)
        assert GoogleCalendarService.get_meet_url(event) == url

    def test_get_meet_url_returns_none_no_meet(self):
        event = _make_calendar_event(has_meet=False)
        assert GoogleCalendarService.get_meet_url(event) is None

    def test_get_attendees_extracts_list(self):
        event = _make_calendar_event(
            attendees=[
                {"email": "alice@example.com", "displayName": "Alice"},
                {"email": "bob@example.com"},
            ]
        )
        attendees = GoogleCalendarService.get_attendees(event)
        assert len(attendees) == 2
        assert attendees[0]["name"] == "Alice"
        assert attendees[0]["email"] == "alice@example.com"
        # Bob has no displayName, should fall back to email
        assert attendees[1]["name"] == "bob@example.com"

    def test_get_attendees_empty(self):
        event = _make_calendar_event(attendees=None)
        attendees = GoogleCalendarService.get_attendees(event)
        assert attendees == []
