"""Meeting repository -- async CRUD for all meeting entities.

Provides MeetingRepository with session_factory callable pattern (matching
DealRepository from Phase 5 and ConversationStateRepository from Phase 4).
Handles serialization between Pydantic schemas and SQLAlchemy models for
meetings, briefings, transcripts, and minutes.

All methods take tenant_id as first argument for tenant-scoped queries.
JSON columns use Pydantic model_dump(mode="json") for save and
model_validate() for load (05-01 pattern).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.meetings.models import (
    BriefingModel,
    MeetingModel,
    MinutesModel,
    TranscriptModel,
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
    Transcript,
    TranscriptEntry,
)

logger = structlog.get_logger(__name__)


# ── Serialization Helpers ───────────────────────────────────────────────────


def _model_to_meeting(model: MeetingModel) -> Meeting:
    """Convert MeetingModel to Meeting schema."""
    participants = [
        Participant.model_validate(p) for p in (model.participants_data or [])
    ]
    return Meeting(
        id=model.id,
        tenant_id=str(model.tenant_id),
        title=model.title,
        scheduled_start=model.scheduled_start,
        scheduled_end=model.scheduled_end,
        google_meet_url=model.google_meet_url,
        google_event_id=model.google_event_id,
        status=MeetingStatus(model.status),
        participants=participants,
        bot_id=model.bot_id,
        recording_url=model.recording_url,
        created_at=model.created_at,
        updated_at=model.updated_at or model.created_at,
    )


def _model_to_briefing(model: BriefingModel) -> Briefing:
    """Convert BriefingModel to Briefing schema."""
    return Briefing(
        id=model.id,
        meeting_id=model.meeting_id,
        format=model.format,
        content=BriefingContent.model_validate(model.content_data or {}),
        generated_at=model.generated_at,
    )


def _model_to_transcript(model: TranscriptModel) -> Transcript:
    """Convert TranscriptModel to Transcript schema."""
    entries = [
        TranscriptEntry.model_validate(e) for e in (model.entries_data or [])
    ]
    return Transcript(
        id=model.id,
        meeting_id=model.meeting_id,
        entries=entries,
        full_text=model.full_text or "",
    )


def _model_to_minutes(model: MinutesModel) -> MeetingMinutes:
    """Convert MinutesModel to MeetingMinutes schema."""
    return MeetingMinutes(
        id=model.id,
        meeting_id=model.meeting_id,
        executive_summary=model.executive_summary or "",
        key_topics=model.key_topics_data or [],
        action_items=[
            ActionItem.model_validate(a) for a in (model.action_items_data or [])
        ],
        decisions=[
            Decision.model_validate(d) for d in (model.decisions_data or [])
        ],
        follow_up_date=model.follow_up_date,
        generated_at=model.generated_at,
    )


# ── Repository ──────────────────────────────────────────────────────────────


class MeetingRepository:
    """Async CRUD operations for all meeting entities.

    Uses session_factory callable pattern matching DealRepository (05-01)
    and ConversationStateRepository (04-05). All methods take tenant_id
    as first argument for tenant-scoped queries.

    Args:
        session_factory: Async callable that yields AsyncSession instances.
    """

    def __init__(
        self, session_factory: Callable[..., AsyncGenerator[AsyncSession, None]]
    ) -> None:
        self._session_factory = session_factory

    # ── Meetings ─────────────────────────────────────────────────────────

    async def create_meeting(
        self, tenant_id: str, data: MeetingCreate
    ) -> Meeting:
        """Create a new meeting from calendar event data.

        Args:
            tenant_id: Tenant UUID string.
            data: MeetingCreate with event details.

        Returns:
            Meeting with all persisted fields.
        """
        async for session in self._session_factory():
            model = MeetingModel(
                tenant_id=uuid.UUID(tenant_id),
                title=data.title,
                scheduled_start=data.scheduled_start,
                scheduled_end=data.scheduled_end,
                google_meet_url=data.google_meet_url,
                google_event_id=data.google_event_id,
                participants_data=[
                    p.model_dump(mode="json") for p in data.participants
                ],
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _model_to_meeting(model)

    async def get_meeting(
        self, tenant_id: str, meeting_id: str
    ) -> Meeting | None:
        """Get a meeting by ID.

        Args:
            tenant_id: Tenant UUID string.
            meeting_id: Meeting UUID string.

        Returns:
            Meeting if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(MeetingModel).where(
                MeetingModel.tenant_id == uuid.UUID(tenant_id),
                MeetingModel.id == uuid.UUID(meeting_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_meeting(model)

    async def get_meeting_by_event_id(
        self, tenant_id: str, google_event_id: str
    ) -> Meeting | None:
        """Get a meeting by Google Calendar event ID (for dedup).

        Args:
            tenant_id: Tenant UUID string.
            google_event_id: Google Calendar event ID.

        Returns:
            Meeting if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(MeetingModel).where(
                MeetingModel.tenant_id == uuid.UUID(tenant_id),
                MeetingModel.google_event_id == google_event_id,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_meeting(model)

    async def get_upcoming_meetings(
        self, tenant_id: str, from_time: datetime, to_time: datetime
    ) -> list[Meeting]:
        """Get meetings in a time window.

        Args:
            tenant_id: Tenant UUID string.
            from_time: Start of window (inclusive).
            to_time: End of window (inclusive).

        Returns:
            List of Meeting objects ordered by scheduled_start.
        """
        async for session in self._session_factory():
            stmt = (
                select(MeetingModel)
                .where(
                    MeetingModel.tenant_id == uuid.UUID(tenant_id),
                    MeetingModel.scheduled_start >= from_time,
                    MeetingModel.scheduled_start <= to_time,
                )
                .order_by(MeetingModel.scheduled_start)
            )
            result = await session.execute(stmt)
            models = result.scalars().all()
            return [_model_to_meeting(m) for m in models]

    async def update_meeting_status(
        self, tenant_id: str, meeting_id: str, status: MeetingStatus
    ) -> Meeting:
        """Update a meeting's lifecycle status.

        Args:
            tenant_id: Tenant UUID string.
            meeting_id: Meeting UUID string.
            status: New MeetingStatus.

        Returns:
            Updated Meeting.

        Raises:
            ValueError: If meeting not found.
        """
        async for session in self._session_factory():
            stmt = select(MeetingModel).where(
                MeetingModel.tenant_id == uuid.UUID(tenant_id),
                MeetingModel.id == uuid.UUID(meeting_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(
                    f"Meeting not found: tenant={tenant_id}, id={meeting_id}"
                )

            model.status = status.value
            model.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(model)
            return _model_to_meeting(model)

    async def update_meeting_bot_id(
        self, tenant_id: str, meeting_id: str, bot_id: str
    ) -> Meeting:
        """Set the Recall.ai bot ID for a meeting.

        Args:
            tenant_id: Tenant UUID string.
            meeting_id: Meeting UUID string.
            bot_id: Recall.ai bot ID.

        Returns:
            Updated Meeting.

        Raises:
            ValueError: If meeting not found.
        """
        async for session in self._session_factory():
            stmt = select(MeetingModel).where(
                MeetingModel.tenant_id == uuid.UUID(tenant_id),
                MeetingModel.id == uuid.UUID(meeting_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(
                    f"Meeting not found: tenant={tenant_id}, id={meeting_id}"
                )

            model.bot_id = bot_id
            model.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(model)
            return _model_to_meeting(model)

    # ── Briefings ────────────────────────────────────────────────────────

    async def save_briefing(
        self, tenant_id: str, briefing: Briefing
    ) -> Briefing:
        """Save a briefing for a meeting.

        Args:
            tenant_id: Tenant UUID string.
            briefing: Briefing schema to persist.

        Returns:
            Persisted Briefing.
        """
        async for session in self._session_factory():
            model = BriefingModel(
                id=briefing.id,
                tenant_id=uuid.UUID(tenant_id),
                meeting_id=briefing.meeting_id,
                format=briefing.format,
                content_data=briefing.content.model_dump(mode="json"),
                generated_at=briefing.generated_at,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _model_to_briefing(model)

    async def get_briefing(
        self, tenant_id: str, meeting_id: str, format: str = "structured"
    ) -> Briefing | None:
        """Get a briefing for a meeting by format.

        Args:
            tenant_id: Tenant UUID string.
            meeting_id: Meeting UUID string.
            format: Briefing format to retrieve.

        Returns:
            Briefing if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(BriefingModel).where(
                BriefingModel.tenant_id == uuid.UUID(tenant_id),
                BriefingModel.meeting_id == uuid.UUID(meeting_id),
                BriefingModel.format == format,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_briefing(model)

    # ── Transcripts ──────────────────────────────────────────────────────

    async def save_transcript(
        self, tenant_id: str, transcript: Transcript
    ) -> Transcript:
        """Save a complete transcript for a meeting.

        Args:
            tenant_id: Tenant UUID string.
            transcript: Transcript schema to persist.

        Returns:
            Persisted Transcript.
        """
        async for session in self._session_factory():
            model = TranscriptModel(
                id=transcript.id,
                tenant_id=uuid.UUID(tenant_id),
                meeting_id=transcript.meeting_id,
                entries_data=[
                    e.model_dump(mode="json") for e in transcript.entries
                ],
                full_text=transcript.full_text,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _model_to_transcript(model)

    async def get_transcript(
        self, tenant_id: str, meeting_id: str
    ) -> Transcript | None:
        """Get the transcript for a meeting.

        Args:
            tenant_id: Tenant UUID string.
            meeting_id: Meeting UUID string.

        Returns:
            Transcript if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(TranscriptModel).where(
                TranscriptModel.tenant_id == uuid.UUID(tenant_id),
                TranscriptModel.meeting_id == uuid.UUID(meeting_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_transcript(model)

    async def append_transcript_entry(
        self, tenant_id: str, meeting_id: str, entry: TranscriptEntry
    ) -> None:
        """Append a transcript entry during real-time streaming.

        Creates the transcript if it doesn't exist, otherwise appends
        the entry to the existing entries_data JSON array and updates
        full_text.

        Args:
            tenant_id: Tenant UUID string.
            meeting_id: Meeting UUID string.
            entry: TranscriptEntry to append.
        """
        async for session in self._session_factory():
            stmt = select(TranscriptModel).where(
                TranscriptModel.tenant_id == uuid.UUID(tenant_id),
                TranscriptModel.meeting_id == uuid.UUID(meeting_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            entry_dict = entry.model_dump(mode="json")

            if model is None:
                # Create new transcript with first entry
                text_line = f"{entry.speaker}: {entry.text}"
                model = TranscriptModel(
                    tenant_id=uuid.UUID(tenant_id),
                    meeting_id=uuid.UUID(meeting_id),
                    entries_data=[entry_dict],
                    full_text=text_line,
                )
                session.add(model)
            else:
                # Append to existing transcript
                entries = list(model.entries_data or [])
                entries.append(entry_dict)
                model.entries_data = entries
                text_line = f"{entry.speaker}: {entry.text}"
                model.full_text = (
                    f"{model.full_text}\n{text_line}" if model.full_text else text_line
                )

            await session.commit()

    # ── Minutes ──────────────────────────────────────────────────────────

    async def save_minutes(
        self, tenant_id: str, minutes: MeetingMinutes
    ) -> MeetingMinutes:
        """Save structured minutes for a meeting.

        Args:
            tenant_id: Tenant UUID string.
            minutes: MeetingMinutes schema to persist.

        Returns:
            Persisted MeetingMinutes.
        """
        async for session in self._session_factory():
            model = MinutesModel(
                id=minutes.id,
                tenant_id=uuid.UUID(tenant_id),
                meeting_id=minutes.meeting_id,
                executive_summary=minutes.executive_summary,
                key_topics_data=minutes.key_topics,
                action_items_data=[
                    a.model_dump(mode="json") for a in minutes.action_items
                ],
                decisions_data=[
                    d.model_dump(mode="json") for d in minutes.decisions
                ],
                follow_up_date=minutes.follow_up_date,
                generated_at=minutes.generated_at,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _model_to_minutes(model)

    async def get_minutes(
        self, tenant_id: str, meeting_id: str
    ) -> MeetingMinutes | None:
        """Get minutes for a meeting.

        Args:
            tenant_id: Tenant UUID string.
            meeting_id: Meeting UUID string.

        Returns:
            MeetingMinutes if found, None otherwise.
        """
        async for session in self._session_factory():
            stmt = select(MinutesModel).where(
                MinutesModel.tenant_id == uuid.UUID(tenant_id),
                MinutesModel.meeting_id == uuid.UUID(meeting_id),
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_minutes(model)

    async def mark_minutes_shared(
        self, tenant_id: str, meeting_id: str
    ) -> None:
        """Mark meeting minutes as shared externally.

        Args:
            tenant_id: Tenant UUID string.
            meeting_id: Meeting UUID string.
        """
        async for session in self._session_factory():
            stmt = (
                update(MinutesModel)
                .where(
                    MinutesModel.tenant_id == uuid.UUID(tenant_id),
                    MinutesModel.meeting_id == uuid.UUID(meeting_id),
                )
                .values(shared_externally=True)
            )
            await session.execute(stmt)
            await session.commit()
