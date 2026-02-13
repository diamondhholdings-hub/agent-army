"""Pydantic v2 schemas for the meeting capabilities domain.

Defines the data contracts for meetings, briefings, transcripts, minutes,
participants, action items, and decisions. All subsequent Phase 6 subsystems
(calendar monitor, bot manager, realtime pipeline, minutes generator) import
from this module.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class ParticipantRole(str, Enum):
    """Role of a meeting participant for speaker classification."""

    INTERNAL = "internal"
    EXTERNAL = "external"
    AGENT = "agent"


class MeetingStatus(str, Enum):
    """Lifecycle status of a meeting from detection through distribution."""

    SCHEDULED = "scheduled"
    BRIEFING_GENERATED = "briefing_generated"
    BOT_JOINING = "bot_joining"
    IN_PROGRESS = "in_progress"
    ENDED = "ended"
    MINUTES_GENERATED = "minutes_generated"
    DISTRIBUTED = "distributed"


# ── Participant & Supporting Models ──────────────────────────────────────────


class Participant(BaseModel):
    """A meeting attendee with role classification."""

    name: str
    email: str
    role: ParticipantRole = ParticipantRole.EXTERNAL
    title: str | None = None
    company: str | None = None


class ActionItem(BaseModel):
    """An action item extracted from meeting minutes."""

    owner: str = Field(description="Person responsible for this action")
    action: str = Field(description="What needs to be done")
    due_date: str | None = Field(None, description="When it's due, if mentioned")
    context: str = Field(description="Brief context from the meeting")


class Decision(BaseModel):
    """A decision or commitment made during a meeting."""

    decision: str = Field(description="What was decided")
    participants: list[str] = Field(description="Who agreed to this")
    context: str = Field(description="Discussion context leading to decision")


# ── Briefing Models ──────────────────────────────────────────────────────────


class BriefingContent(BaseModel):
    """Structured content of a pre-meeting briefing."""

    account_context: str = Field(description="Background on the account/company")
    attendee_profiles: list[dict] = Field(
        default_factory=list,
        description="Profile info for each attendee",
    )
    objectives: list[str] = Field(
        default_factory=list,
        description="Meeting objectives and goals",
    )
    talk_tracks: list[str] = Field(
        default_factory=list,
        description="Suggested talk tracks for the rep",
    )
    deal_context: str | None = Field(
        None,
        description="Current deal stage and qualification context",
    )


class Briefing(BaseModel):
    """Pre-meeting briefing document."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    meeting_id: uuid.UUID
    format: str = Field(
        default="structured",
        description="Briefing format: structured, bullet, or adaptive",
    )
    content: BriefingContent
    generated_at: datetime


# ── Transcript Models ────────────────────────────────────────────────────────


class TranscriptEntry(BaseModel):
    """A single entry in a meeting transcript."""

    speaker: str
    text: str
    timestamp_ms: int
    is_final: bool = True


class Transcript(BaseModel):
    """Full meeting transcript with individual entries."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    meeting_id: uuid.UUID
    entries: list[TranscriptEntry] = Field(default_factory=list)
    full_text: str = ""


# ── Minutes Models ───────────────────────────────────────────────────────────


class MeetingMinutes(BaseModel):
    """Structured post-meeting minutes."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    meeting_id: uuid.UUID
    executive_summary: str = Field(description="2-3 paragraph high-level summary")
    key_topics: list[str] = Field(
        default_factory=list,
        description="Main topics discussed",
    )
    action_items: list[ActionItem] = Field(
        default_factory=list,
        description="All action items with owners",
    )
    decisions: list[Decision] = Field(
        default_factory=list,
        description="Decisions and commitments made",
    )
    follow_up_date: str | None = Field(
        None,
        description="Next meeting date if mentioned",
    )
    generated_at: datetime


# ── Meeting Models ───────────────────────────────────────────────────────────


class Meeting(BaseModel):
    """Full meeting entity with all metadata."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: str
    title: str
    scheduled_start: datetime
    scheduled_end: datetime
    google_meet_url: str
    google_event_id: str
    status: MeetingStatus = MeetingStatus.SCHEDULED
    participants: list[Participant] = Field(default_factory=list)
    bot_id: str | None = None
    recording_url: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Request/Create Models ────────────────────────────────────────────────────


class MeetingCreate(BaseModel):
    """Request schema for creating a new meeting."""

    title: str
    scheduled_start: datetime
    scheduled_end: datetime
    google_meet_url: str
    google_event_id: str
    participants: list[Participant] = Field(default_factory=list)


class MeetingBriefingRequest(BaseModel):
    """Request schema for generating a meeting briefing."""

    meeting_id: uuid.UUID
    format: str = "structured"


class MinutesShareRequest(BaseModel):
    """Request schema for sharing meeting minutes externally."""

    meeting_id: uuid.UUID
    recipient_emails: list[str]
    include_transcript: bool = False
