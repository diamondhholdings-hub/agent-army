"""Add meeting capability tables for meetings, briefings, transcripts, and minutes.

Revision ID: 007_meeting_tables
Revises: 006_deal_management
Create Date: 2026-02-13

Creates four tables in the tenant schema for meeting lifecycle:
- meetings: Meeting events detected from Google Calendar
- briefings: Pre-meeting briefing documents (JSON content)
- transcripts: Full meeting transcripts with entries
- meeting_minutes: Structured post-meeting minutes

All tables include RLS policies for tenant isolation and indexes
for common query patterns. No foreign key constraints (application-level
referential integrity via repository, consistent with Phase 5 pattern).
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "007_meeting_tables"
down_revision: Union[str, None] = "006_deal_management"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Get the actual schema name from -x args
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    # ── meetings table ───────────────────────────────────────────────────

    op.create_table(
        "meetings",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("google_meet_url", sa.String(500), nullable=False),
        sa.Column("google_event_id", sa.String(300), nullable=False),
        sa.Column(
            "status",
            sa.String(50),
            server_default=sa.text("'scheduled'"),
            nullable=False,
        ),
        sa.Column(
            "participants_data",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("bot_id", sa.String(200), nullable=True),
        sa.Column("recording_url", sa.String(1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "google_event_id", name="uq_meeting_tenant_event"
        ),
        schema="tenant",
    )

    op.execute(f'ALTER TABLE "{schema}".meetings ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{schema}".meetings FORCE ROW LEVEL SECURITY')
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".meetings
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    # Calendar dedup: find meeting by tenant + event ID
    op.execute(
        f'CREATE INDEX idx_meetings_tenant_event '
        f'ON "{schema}".meetings(tenant_id, google_event_id)'
    )
    # Active meeting queries by status
    op.execute(
        f'CREATE INDEX idx_meetings_tenant_status '
        f'ON "{schema}".meetings(tenant_id, status)'
    )
    # Upcoming meeting queries by scheduled_start
    op.execute(
        f'CREATE INDEX idx_meetings_tenant_start '
        f'ON "{schema}".meetings(tenant_id, scheduled_start)'
    )

    # ── briefings table ──────────────────────────────────────────────────

    op.create_table(
        "briefings",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "format",
            sa.String(50),
            server_default=sa.text("'structured'"),
            nullable=False,
        ),
        sa.Column(
            "content_data",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="tenant",
    )

    op.execute(f'ALTER TABLE "{schema}".briefings ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{schema}".briefings FORCE ROW LEVEL SECURITY')
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".briefings
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_briefings_tenant_meeting '
        f'ON "{schema}".briefings(tenant_id, meeting_id)'
    )

    # ── transcripts table ────────────────────────────────────────────────

    op.create_table(
        "transcripts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "entries_data",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "full_text",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="tenant",
    )

    op.execute(f'ALTER TABLE "{schema}".transcripts ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{schema}".transcripts FORCE ROW LEVEL SECURITY')
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".transcripts
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_transcripts_tenant_meeting '
        f'ON "{schema}".transcripts(tenant_id, meeting_id)'
    )

    # ── meeting_minutes table ────────────────────────────────────────────

    op.create_table(
        "meeting_minutes",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "executive_summary",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "key_topics_data",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "action_items_data",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "decisions_data",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("follow_up_date", sa.String(50), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "shared_externally",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="tenant",
    )

    op.execute(
        f'ALTER TABLE "{schema}".meeting_minutes ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".meeting_minutes FORCE ROW LEVEL SECURITY'
    )
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".meeting_minutes
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_minutes_tenant_meeting '
        f'ON "{schema}".meeting_minutes(tenant_id, meeting_id)'
    )


def downgrade() -> None:
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    # Drop policies then tables in reverse order

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".meeting_minutes'
    )
    op.drop_table("meeting_minutes", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".transcripts'
    )
    op.drop_table("transcripts", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".briefings'
    )
    op.drop_table("briefings", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".meetings'
    )
    op.drop_table("meetings", schema="tenant")
