"""Meeting persistence models -- tenant-scoped tables for meeting lifecycle.

Four SQLAlchemy models using TenantBase for schema_translate_map isolation:
- MeetingModel: Meeting events detected from Google Calendar
- BriefingModel: Pre-meeting briefing documents (JSON content)
- TranscriptModel: Full meeting transcripts with entries (JSON)
- MinutesModel: Structured post-meeting minutes (JSON fields)

All models use the "tenant" placeholder schema, remapped at runtime to the
actual tenant schema (e.g., "tenant_skyvera") via schema_translate_map.

No foreign key constraints (application-level referential integrity via
repository, consistent with Phase 5 pattern).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.database import TenantBase


class MeetingModel(TenantBase):
    """Meeting event detected from Google Calendar.

    Represents a scheduled or completed meeting where the agent was
    explicitly invited. Tracks lifecycle from SCHEDULED through DISTRIBUTED.
    Participants and metadata stored as JSON for schema flexibility.
    """

    __tablename__ = "meetings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "google_event_id",
            name="uq_meeting_tenant_event",
        ),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scheduled_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    google_meet_url: Mapped[str] = mapped_column(String(500), nullable=False)
    google_event_id: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default="scheduled",
        server_default=text("'scheduled'"),
    )
    participants_data: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'::json")
    )
    bot_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recording_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )


class BriefingModel(TenantBase):
    """Pre-meeting briefing document stored as JSON content.

    One or more briefings per meeting (different formats: structured,
    bullet, adaptive). Content stored as JSON for Pydantic round-tripping
    via model_dump()/model_validate().
    """

    __tablename__ = "briefings"
    __table_args__ = (
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    meeting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    format: Mapped[str] = mapped_column(
        String(50),
        default="structured",
        server_default=text("'structured'"),
    )
    content_data: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class TranscriptModel(TenantBase):
    """Full meeting transcript with per-entry JSON data.

    Entries stored as JSON array for real-time append during meeting.
    Full text stored separately as searchable Text column for
    minutes generation and vector embedding.
    """

    __tablename__ = "transcripts"
    __table_args__ = (
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    meeting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entries_data: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'::json")
    )
    full_text: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class MinutesModel(TenantBase):
    """Structured post-meeting minutes with JSON-stored fields.

    Stores executive summary as searchable Text, and structured data
    (key_topics, action_items, decisions) as JSON for Pydantic
    round-tripping. Internal-only by default; shared_externally tracks
    distribution status.
    """

    __tablename__ = "meeting_minutes"
    __table_args__ = (
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    meeting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    key_topics_data: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'::json")
    )
    action_items_data: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'::json")
    )
    decisions_data: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'::json")
    )
    follow_up_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    shared_externally: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
    )
