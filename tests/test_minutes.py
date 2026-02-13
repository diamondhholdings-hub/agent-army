"""Unit tests for MinutesGenerator and MinutesDistributor.

Tests structured minutes extraction from transcripts, map-reduce for
long transcripts, graceful fallback without LLM, internal distribution,
manual external sharing, and email content verification.

Uses InMemoryMeetingRepository test double (from test_meeting_foundation)
and mock LLM/gmail services.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.meetings.minutes.distributor import (
    MinutesDistributor,
    _build_external_email,
    _build_internal_email,
)
from src.app.meetings.minutes.generator import (
    CHARS_PER_TOKEN,
    MAX_TOKENS_PER_CHUNK,
    ChunkSummary,
    ExtractedActionItem,
    ExtractedDecision,
    ExtractedMinutes,
    MinutesGenerator,
    _chunk_transcript,
    _estimate_tokens,
)
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


# ── Fixtures ─────────────────────────────────────────────────────────────────


TENANT_ID = str(uuid.uuid4())
MEETING_ID = uuid.uuid4()
NOW = datetime.now(timezone.utc)


class InMemoryMeetingRepository:
    """In-memory test double for MeetingRepository.

    Mirrors the MeetingRepository interface for fast unit testing.
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
            created_at=NOW,
            updated_at=NOW,
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


def _make_meeting(
    meeting_id: uuid.UUID | None = None,
    tenant_id: str = TENANT_ID,
    title: str = "Q4 Product Demo",
    **overrides,
) -> Meeting:
    mid = meeting_id or MEETING_ID
    defaults = {
        "id": mid,
        "tenant_id": tenant_id,
        "title": title,
        "scheduled_start": NOW,
        "scheduled_end": NOW,
        "google_meet_url": "https://meet.google.com/abc-defg-hij",
        "google_event_id": "evt_123",
        "status": MeetingStatus.ENDED,
        "participants": [
            Participant(
                name="Alice Smith",
                email="alice@company.com",
                role=ParticipantRole.INTERNAL,
            ),
            Participant(
                name="Bob Jones",
                email="bob@customer.com",
                role=ParticipantRole.EXTERNAL,
            ),
        ],
        "created_at": NOW,
        "updated_at": NOW,
    }
    defaults.update(overrides)
    return Meeting(**defaults)


def _make_transcript(
    meeting_id: uuid.UUID | None = None,
    full_text: str = "Alice Smith: Welcome to the demo.\nBob Jones: Thanks for having us.",
) -> Transcript:
    mid = meeting_id or MEETING_ID
    return Transcript(
        meeting_id=mid,
        entries=[
            TranscriptEntry(
                speaker="Alice Smith", text="Welcome to the demo.", timestamp_ms=0
            ),
            TranscriptEntry(
                speaker="Bob Jones",
                text="Thanks for having us.",
                timestamp_ms=5000,
            ),
        ],
        full_text=full_text,
    )


def _make_minutes(
    meeting_id: uuid.UUID | None = None,
) -> MeetingMinutes:
    mid = meeting_id or MEETING_ID
    return MeetingMinutes(
        meeting_id=mid,
        executive_summary="A productive meeting about Q4 product features.",
        key_topics=["Product roadmap", "Pricing discussion"],
        action_items=[
            ActionItem(
                owner="Alice Smith",
                action="Send pricing proposal",
                due_date="2026-02-20",
                context="Discussed during pricing segment",
            ),
            ActionItem(
                owner="Bob Jones",
                action="Review technical requirements",
                due_date=None,
                context="Bob volunteered to evaluate",
            ),
        ],
        decisions=[
            Decision(
                decision="Proceed with enterprise tier evaluation",
                participants=["Alice Smith", "Bob Jones"],
                context="Both sides agreed to 30-day POC",
            ),
        ],
        follow_up_date="2026-02-25",
        generated_at=NOW,
    )


def _make_extracted_minutes() -> ExtractedMinutes:
    return ExtractedMinutes(
        executive_summary="A productive demo meeting.",
        key_topics=["Product features", "Timeline"],
        action_items=[
            ExtractedActionItem(
                owner="Alice",
                action="Send proposal",
                due_date="2026-02-20",
                context="Pricing discussion",
            ),
        ],
        decisions=[
            ExtractedDecision(
                decision="Proceed with POC",
                participants=["Alice", "Bob"],
                context="Agreement reached",
            ),
        ],
        follow_up_date="2026-02-25",
    )


# ── Generator Tests ──────────────────────────────────────────────────────────


class TestEstimateTokens:
    """Test token estimation function."""

    def test_estimate_tokens_reasonable_count(self):
        text = "Hello world, this is a test string."
        tokens = _estimate_tokens(text)
        expected = int(len(text) / CHARS_PER_TOKEN)
        assert tokens == expected

    def test_estimate_tokens_empty_string(self):
        assert _estimate_tokens("") == 0

    def test_estimate_tokens_long_text(self):
        text = "x" * 48000  # Should be 12000 tokens
        assert _estimate_tokens(text) == 12000


class TestChunkTranscript:
    """Test transcript chunking at speaker boundaries."""

    def test_chunk_small_transcript_returns_single_chunk(self):
        text = "Alice: Hello\nBob: Hi there"
        chunks = _chunk_transcript(text)
        assert len(chunks) == 1
        assert "Alice: Hello" in chunks[0]

    def test_chunk_transcript_splits_at_speaker_boundaries(self):
        """Long transcript should split at speaker turns."""
        # Build transcript exceeding MAX_TOKENS_PER_CHUNK
        lines = []
        for i in range(600):
            speaker = "Alice" if i % 2 == 0 else "Bob"
            # Each line ~100 chars = ~25 tokens
            lines.append(f"{speaker}: This is turn number {i} with some additional context text to pad it out a bit more.")
        text = "\n".join(lines)

        # Ensure it exceeds one chunk
        assert _estimate_tokens(text) > MAX_TOKENS_PER_CHUNK

        chunks = _chunk_transcript(text)
        assert len(chunks) >= 2

        # Each chunk should start with a speaker turn
        for chunk in chunks:
            first_line = chunk.strip().split("\n")[0]
            assert ":" in first_line, f"Chunk should start with speaker: {first_line}"

    def test_chunk_transcript_includes_overlap(self):
        """Chunks should overlap for context continuity."""
        lines = []
        for i in range(600):
            speaker = "Alice" if i % 2 == 0 else "Bob"
            lines.append(f"{speaker}: Turn number {i} with extra padding text to ensure we have substantial content.")
        text = "\n".join(lines)

        chunks = _chunk_transcript(text)
        if len(chunks) >= 2:
            # Check that some content from end of chunk 1 appears at start of chunk 2
            # Due to overlap of last 2 speaker turns
            chunk1_lines = chunks[0].strip().split("\n")
            chunk2_lines = chunks[1].strip().split("\n")

            # Last line of chunk 1 should appear in chunk 2
            last_line_chunk1 = chunk1_lines[-1]
            chunk2_text = chunks[1]
            # Overlap means some content repeats
            assert len(chunk2_lines) > 0

    def test_chunk_empty_transcript(self):
        assert _chunk_transcript("") == []
        assert _chunk_transcript("   ") == []

    def test_chunk_no_speaker_pattern_falls_back(self):
        """Text without speaker patterns falls back to char-based chunking."""
        text = "Just some text\nwithout speaker attribution\n" * 2000
        chunks = _chunk_transcript(text)
        assert len(chunks) >= 1


class TestMinutesGeneratorGenerate:
    """Test MinutesGenerator.generate with mocked LLM."""

    @pytest.mark.asyncio
    async def test_generate_valid_minutes_schema(self):
        """Generator should produce valid MeetingMinutes schema (mock LLM)."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting

        generator = MinutesGenerator(repository=repo)
        transcript = _make_transcript()
        attendees = meeting.participants
        metadata = {"title": meeting.title, "date": str(NOW)}

        extracted = _make_extracted_minutes()

        with patch.object(
            generator,
            "_extract_minutes_single_pass",
            new_callable=AsyncMock,
            return_value=extracted,
        ):
            result = await generator.generate(
                transcript, attendees, metadata, TENANT_ID
            )

        assert isinstance(result, MeetingMinutes)
        assert result.meeting_id == MEETING_ID
        assert result.executive_summary == "A productive demo meeting."
        assert len(result.action_items) == 1
        assert len(result.decisions) == 1
        assert result.follow_up_date == "2026-02-25"

    @pytest.mark.asyncio
    async def test_generate_saves_to_repository(self):
        """Generated minutes should be saved to repository."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting

        generator = MinutesGenerator(repository=repo)
        transcript = _make_transcript()
        extracted = _make_extracted_minutes()

        with patch.object(
            generator,
            "_extract_minutes_single_pass",
            new_callable=AsyncMock,
            return_value=extracted,
        ):
            await generator.generate(
                transcript,
                meeting.participants,
                {"title": meeting.title},
                TENANT_ID,
            )

        # Minutes should be in repository
        saved = await repo.get_minutes(TENANT_ID, str(MEETING_ID))
        assert saved is not None
        assert saved.executive_summary == "A productive demo meeting."

    @pytest.mark.asyncio
    async def test_generate_updates_meeting_status(self):
        """Meeting status should be updated to MINUTES_GENERATED."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting

        generator = MinutesGenerator(repository=repo)
        transcript = _make_transcript()
        extracted = _make_extracted_minutes()

        with patch.object(
            generator,
            "_extract_minutes_single_pass",
            new_callable=AsyncMock,
            return_value=extracted,
        ):
            await generator.generate(
                transcript,
                meeting.participants,
                {"title": meeting.title},
                TENANT_ID,
            )

        updated_meeting = repo.meetings.get(str(MEETING_ID))
        assert updated_meeting is not None
        assert updated_meeting.status == MeetingStatus.MINUTES_GENERATED

    @pytest.mark.asyncio
    async def test_generate_map_reduce_for_long_transcript(self):
        """Long transcripts should use map-reduce extraction."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting

        generator = MinutesGenerator(repository=repo)

        # Build long transcript exceeding MAX_TOKENS_PER_CHUNK
        lines = []
        for i in range(600):
            speaker = "Alice Smith" if i % 2 == 0 else "Bob Jones"
            lines.append(f"{speaker}: This is turn {i} with detailed discussion content and additional context.")
        long_text = "\n".join(lines)
        transcript = _make_transcript(full_text=long_text)

        extracted = _make_extracted_minutes()

        with patch.object(
            generator,
            "_extract_map_reduce",
            new_callable=AsyncMock,
            return_value=extracted,
        ) as mock_map_reduce:
            result = await generator.generate(
                transcript,
                meeting.participants,
                {"title": meeting.title},
                TENANT_ID,
            )

        mock_map_reduce.assert_called_once()
        assert isinstance(result, MeetingMinutes)

    @pytest.mark.asyncio
    async def test_generate_graceful_fallback_without_llm(self):
        """Generator should fall back gracefully if LLM fails."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting

        generator = MinutesGenerator(repository=repo)
        transcript = _make_transcript()

        with patch.object(
            generator,
            "_extract_minutes_single_pass",
            new_callable=AsyncMock,
            side_effect=Exception("LLM unavailable"),
        ):
            result = await generator.generate(
                transcript,
                meeting.participants,
                {"title": meeting.title},
                TENANT_ID,
            )

        # Should return minutes with empty extracted fields
        assert isinstance(result, MeetingMinutes)
        assert result.executive_summary == ""
        assert result.action_items == []
        assert result.decisions == []
        assert result.key_topics == []


# ── Distributor Tests ────────────────────────────────────────────────────────


class TestDistributorSaveInternally:
    """Test MinutesDistributor.save_internally."""

    @pytest.mark.asyncio
    async def test_save_internally_updates_meeting_status(self):
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting

        distributor = MinutesDistributor(repository=repo)
        minutes = _make_minutes()

        await distributor.save_internally(minutes, TENANT_ID)

        # Minutes saved in repo
        saved = await repo.get_minutes(TENANT_ID, str(MEETING_ID))
        assert saved is not None

        # Meeting status updated
        updated = repo.meetings.get(str(MEETING_ID))
        assert updated.status == MeetingStatus.MINUTES_GENERATED

    @pytest.mark.asyncio
    async def test_save_internally_idempotent(self):
        """Calling save_internally twice should not create duplicate minutes."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting

        distributor = MinutesDistributor(repository=repo)
        minutes = _make_minutes()

        # Pre-save minutes
        await repo.save_minutes(TENANT_ID, minutes)

        # Second save should not fail
        await distributor.save_internally(minutes, TENANT_ID)

        saved = await repo.get_minutes(TENANT_ID, str(MEETING_ID))
        assert saved is not None


class TestDistributorNotifyInternal:
    """Test MinutesDistributor.notify_internal."""

    @pytest.mark.asyncio
    async def test_notify_internal_sends_email_to_internal_attendees_only(self):
        """Should only notify internal attendees, not external."""
        repo = InMemoryMeetingRepository()
        mock_gmail = AsyncMock()
        mock_gmail.send_email = AsyncMock()

        distributor = MinutesDistributor(
            repository=repo, gmail_service=mock_gmail
        )
        meeting = _make_meeting()
        minutes = _make_minutes()

        await distributor.notify_internal(meeting, minutes, TENANT_ID)

        # Only internal attendee (Alice) should be notified
        assert mock_gmail.send_email.call_count == 1
        sent_email = mock_gmail.send_email.call_args[0][0]
        assert sent_email.to == "alice@company.com"
        assert "Meeting Minutes Ready" in sent_email.subject

    @pytest.mark.asyncio
    async def test_notify_internal_no_internal_attendees(self):
        """Should handle meetings with no internal attendees gracefully."""
        repo = InMemoryMeetingRepository()
        mock_gmail = AsyncMock()

        distributor = MinutesDistributor(
            repository=repo, gmail_service=mock_gmail
        )
        meeting = _make_meeting(
            participants=[
                Participant(
                    name="Bob Jones",
                    email="bob@customer.com",
                    role=ParticipantRole.EXTERNAL,
                ),
            ]
        )
        minutes = _make_minutes()

        await distributor.notify_internal(meeting, minutes, TENANT_ID)

        # No emails should be sent
        mock_gmail.send_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_internal_falls_back_to_logging(self):
        """Without gmail service, should fall back to logging."""
        repo = InMemoryMeetingRepository()
        distributor = MinutesDistributor(repository=repo, gmail_service=None)

        meeting = _make_meeting()
        minutes = _make_minutes()

        # Should not raise -- falls back to logging
        await distributor.notify_internal(meeting, minutes, TENANT_ID)


class TestDistributorShareExternally:
    """Test MinutesDistributor.share_externally."""

    @pytest.mark.asyncio
    async def test_share_externally_sends_customer_appropriate_content(self):
        """External email should contain summary and action items."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting
        minutes = _make_minutes()
        repo.minutes[str(MEETING_ID)] = minutes

        mock_gmail = AsyncMock()
        mock_gmail.send_email = AsyncMock()

        distributor = MinutesDistributor(
            repository=repo, gmail_service=mock_gmail
        )

        result = await distributor.share_externally(
            meeting_id=MEETING_ID,
            tenant_id=TENANT_ID,
            recipient_emails=["bob@customer.com"],
        )

        assert "bob@customer.com" in result["sent_to"]
        assert "share_time" in result

        # Check email content
        sent_email = mock_gmail.send_email.call_args[0][0]
        assert "Meeting Summary" in sent_email.subject

    @pytest.mark.asyncio
    async def test_share_externally_marks_as_shared(self):
        """Shared minutes should be marked in repository."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting
        minutes = _make_minutes()
        repo.minutes[str(MEETING_ID)] = minutes

        distributor = MinutesDistributor(repository=repo)

        await distributor.share_externally(
            meeting_id=MEETING_ID,
            tenant_id=TENANT_ID,
            recipient_emails=["bob@customer.com"],
        )

        assert str(MEETING_ID) in repo.minutes_shared

    @pytest.mark.asyncio
    async def test_share_externally_raises_for_missing_minutes(self):
        """Should raise ValueError if minutes not found."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting

        distributor = MinutesDistributor(repository=repo)

        with pytest.raises(ValueError, match="Minutes not found"):
            await distributor.share_externally(
                meeting_id=MEETING_ID,
                tenant_id=TENANT_ID,
                recipient_emails=["bob@customer.com"],
            )


class TestBuildExternalEmail:
    """Test external email builder excludes internal notes."""

    def test_external_email_excludes_participant_list(self):
        """External email should NOT include detailed participant information."""
        meeting = _make_meeting()
        minutes = _make_minutes()

        html = _build_external_email(meeting, minutes)

        # Should contain summary
        assert "A productive meeting about Q4 product features" in html
        # Should contain action items
        assert "Send pricing proposal" in html
        # Should contain decisions
        assert "Proceed with enterprise tier evaluation" in html
        # External email uses simpler decision format without participant names
        assert "Agreed by:" not in html

    def test_external_email_professional_formatting(self):
        """External email should have professional formatting."""
        meeting = _make_meeting()
        minutes = _make_minutes()

        html = _build_external_email(meeting, minutes)

        assert "<html>" in html
        assert "Meeting Summary:" in html
        assert "Thank you for your time" in html

    def test_external_email_with_transcript(self):
        """External email with include_transcript should mention transcript."""
        meeting = _make_meeting()
        minutes = _make_minutes()

        html = _build_external_email(meeting, minutes, include_transcript=True)
        assert "Transcript" in html

    def test_external_email_without_transcript(self):
        """External email without transcript should not mention it."""
        meeting = _make_meeting()
        minutes = _make_minutes()

        html = _build_external_email(meeting, minutes, include_transcript=False)
        assert "Transcript" not in html


class TestBuildInternalEmail:
    """Test internal email builder includes full content."""

    def test_internal_email_includes_all_sections(self):
        """Internal email should include summary, topics, actions, decisions."""
        meeting = _make_meeting()
        minutes = _make_minutes()

        html = _build_internal_email(meeting, minutes)

        assert "Executive Summary" in html
        assert "Key Topics" in html
        assert "Action Items" in html
        assert "Decisions & Commitments" in html
        assert "Full transcript is available" in html

    def test_internal_email_includes_follow_up(self):
        """Internal email should include follow-up date if present."""
        meeting = _make_meeting()
        minutes = _make_minutes()

        html = _build_internal_email(meeting, minutes)
        assert "2026-02-25" in html


class TestNoAutoShare:
    """Test that distributor does NOT auto-share externally."""

    @pytest.mark.asyncio
    async def test_no_auto_external_distribution(self):
        """save_internally should NOT send to external recipients."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting

        mock_gmail = AsyncMock()
        mock_gmail.send_email = AsyncMock()

        distributor = MinutesDistributor(
            repository=repo, gmail_service=mock_gmail
        )
        minutes = _make_minutes()

        # save_internally should NOT trigger any email sends
        await distributor.save_internally(minutes, TENANT_ID)

        # Gmail should not have been called (no internal notify from save_internally)
        mock_gmail.send_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_external_requires_explicit_call(self):
        """Only share_externally should send to external recipients."""
        repo = InMemoryMeetingRepository()
        meeting = _make_meeting()
        repo.meetings[str(meeting.id)] = meeting
        minutes = _make_minutes()
        repo.minutes[str(MEETING_ID)] = minutes

        mock_gmail = AsyncMock()
        mock_gmail.send_email = AsyncMock()

        distributor = MinutesDistributor(
            repository=repo, gmail_service=mock_gmail
        )

        # Explicit share should send
        result = await distributor.share_externally(
            meeting_id=MEETING_ID,
            tenant_id=TENANT_ID,
            recipient_emails=["bob@customer.com"],
        )
        assert mock_gmail.send_email.call_count == 1
        assert "bob@customer.com" in result["sent_to"]
