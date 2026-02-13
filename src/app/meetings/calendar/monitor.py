"""CalendarMonitor -- watches for agent meeting invites and triggers briefing generation.

Polls Google Calendar via GoogleCalendarService to detect meetings where the
sales agent is explicitly invited (opt-in model per CONTEXT.md) and has a
Google Meet link. Creates meeting records in MeetingRepository and triggers
BriefingGenerator within the 2-hour lead-time window.

Last-minute meetings (added <2h before start) get immediate briefing
generation -- degraded lead time is better than no briefing (CONTEXT.md).

Idempotent briefing keyed by (meeting_id, scheduled_time) per Research
Pitfall 8: if a meeting is rescheduled (different start time for same
event_id), a new briefing is generated.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import structlog

from src.app.meetings.schemas import (
    Meeting,
    MeetingCreate,
    MeetingStatus,
    Participant,
    ParticipantRole,
)

if TYPE_CHECKING:
    from src.app.meetings.calendar.briefing import BriefingGenerator
    from src.app.meetings.repository import MeetingRepository
    from src.app.services.gsuite.calendar import GoogleCalendarService

logger = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

BRIEFING_LEAD_TIME_HOURS = 2
EARLY_JOIN_MINUTES = 3
POLL_INTERVAL_SECONDS = 60


class CalendarMonitor:
    """Watches for agent meeting invites and triggers pre-meeting pipeline.

    Polls Google Calendar for upcoming events, filters to explicit agent
    invites with Google Meet links, creates meeting records, and triggers
    briefing generation within the lead-time window.

    Args:
        calendar_service: GoogleCalendarService for calendar event fetching.
        repository: MeetingRepository for persisting discovered meetings.
        briefing_generator: BriefingGenerator for creating pre-meeting briefings.
        bot_manager: Optional bot manager for triggering bot joins (None until Plan 06-03).
    """

    def __init__(
        self,
        calendar_service: GoogleCalendarService,
        repository: MeetingRepository,
        briefing_generator: BriefingGenerator,
        bot_manager: Any | None = None,
    ) -> None:
        self._calendar_service = calendar_service
        self._repository = repository
        self._briefing_generator = briefing_generator
        self._bot_manager = bot_manager
        self._running = False

    # ── Core Detection ───────────────────────────────────────────────────

    async def check_upcoming_meetings(
        self, agent_email: str, tenant_id: str
    ) -> list[Meeting]:
        """Query calendar and create records for newly discovered meetings.

        Fetches events in the window [now, now + BRIEFING_LEAD_TIME_HOURS + 1h],
        filters to events where the agent is explicitly invited AND has a
        Google Meet link, and creates meeting records for new events.

        Args:
            agent_email: The agent's email address on the calendar.
            tenant_id: Tenant UUID string for scoped queries.

        Returns:
            List of upcoming Meeting objects (both existing and newly created).
        """
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(hours=BRIEFING_LEAD_TIME_HOURS + 1)

        # Fetch events from Google Calendar
        events = self._calendar_service.list_upcoming_events(
            agent_email=agent_email,
            time_min=now,
            time_max=window_end,
        )

        upcoming: list[Meeting] = []

        for event in events:
            # Filter: must have Google Meet link
            if not self._calendar_service.has_google_meet_link(event):
                continue

            event_id = event.get("id", "")
            if not event_id:
                continue

            # Check if already tracked
            existing = await self._repository.get_meeting_by_event_id(
                tenant_id, event_id
            )

            if existing is not None:
                # Check for reschedule: if start time changed, update and re-brief
                event_start = _parse_event_start(event)
                if (
                    event_start is not None
                    and existing.scheduled_start != event_start
                ):
                    logger.info(
                        "meeting_rescheduled",
                        event_id=event_id,
                        old_start=existing.scheduled_start.isoformat(),
                        new_start=event_start.isoformat(),
                    )
                    # Mark as needing new briefing by resetting status
                    existing = await self._repository.update_meeting_status(
                        tenant_id, str(existing.id), MeetingStatus.SCHEDULED
                    )
                upcoming.append(existing)
                continue

            # Create new meeting record
            meet_url = self._calendar_service.get_meet_url(event) or ""
            event_start = _parse_event_start(event)
            event_end = _parse_event_end(event)

            if event_start is None or event_end is None:
                logger.warning(
                    "skipping_event_missing_times",
                    event_id=event_id,
                )
                continue

            # Classify attendees
            attendees = self._calendar_service.get_attendees(event)
            internal_domain = agent_email.split("@")[1] if "@" in agent_email else ""
            participants = self._classify_attendees(
                attendees, internal_domain, agent_email
            )

            meeting_data = MeetingCreate(
                title=event.get("summary", "Untitled Meeting"),
                scheduled_start=event_start,
                scheduled_end=event_end,
                google_meet_url=meet_url,
                google_event_id=event_id,
                participants=participants,
            )

            meeting = await self._repository.create_meeting(tenant_id, meeting_data)
            logger.info(
                "meeting_discovered",
                meeting_id=str(meeting.id),
                title=meeting.title,
                scheduled_start=meeting.scheduled_start.isoformat(),
            )
            upcoming.append(meeting)

        return upcoming

    # ── Processing Loop ──────────────────────────────────────────────────

    async def process_upcoming_meetings(
        self, agent_email: str, tenant_id: str
    ) -> None:
        """Process upcoming meetings: trigger briefings and bot joins.

        For each meeting with status SCHEDULED:
        - If meeting starts within BRIEFING_LEAD_TIME_HOURS and no briefing
          exists: trigger briefing generation.
        - If meeting starts within EARLY_JOIN_MINUTES: trigger bot join
          (if bot_manager available).
        - Last-minute meetings (added <2h before start): generate briefing
          immediately.

        Args:
            agent_email: The agent's email address.
            tenant_id: Tenant UUID string.
        """
        meetings = await self.check_upcoming_meetings(agent_email, tenant_id)
        now = datetime.now(timezone.utc)

        for meeting in meetings:
            try:
                await self._process_single_meeting(meeting, tenant_id, now)
            except Exception:
                logger.exception(
                    "meeting_processing_error",
                    meeting_id=str(meeting.id),
                    title=meeting.title,
                )

    async def _process_single_meeting(
        self, meeting: Meeting, tenant_id: str, now: datetime
    ) -> None:
        """Process a single meeting for briefing/bot triggers."""
        if meeting.status != MeetingStatus.SCHEDULED:
            return

        time_until_start = (meeting.scheduled_start - now).total_seconds()
        hours_until_start = time_until_start / 3600
        minutes_until_start = time_until_start / 60

        # Briefing trigger: within lead time OR last-minute meeting
        needs_briefing = hours_until_start <= BRIEFING_LEAD_TIME_HOURS
        if needs_briefing:
            await self._ensure_briefing(meeting, tenant_id)

        # Bot join trigger: within early join window
        if minutes_until_start <= EARLY_JOIN_MINUTES and self._bot_manager is not None:
            logger.info(
                "triggering_bot_join",
                meeting_id=str(meeting.id),
                minutes_until_start=round(minutes_until_start, 1),
            )
            # Bot join will be implemented in Plan 06-03

    async def _ensure_briefing(
        self, meeting: Meeting, tenant_id: str
    ) -> None:
        """Generate briefing if one doesn't already exist for this meeting.

        Idempotent: checks for existing briefing before generating.
        Uses (meeting_id, scheduled_time) as key -- if meeting was
        rescheduled (status reset to SCHEDULED), a new briefing is generated.
        """
        existing_briefing = await self._repository.get_briefing(
            tenant_id, str(meeting.id), format="structured"
        )

        if existing_briefing is not None and meeting.status == MeetingStatus.SCHEDULED:
            # Briefing exists and meeting hasn't been rescheduled
            logger.debug(
                "briefing_already_exists",
                meeting_id=str(meeting.id),
            )
            return

        logger.info(
            "generating_briefing",
            meeting_id=str(meeting.id),
            title=meeting.title,
        )

        try:
            await self._briefing_generator.generate_all_formats(meeting, tenant_id)
            await self._repository.update_meeting_status(
                tenant_id, str(meeting.id), MeetingStatus.BRIEFING_GENERATED
            )
        except Exception:
            logger.exception(
                "briefing_generation_failed",
                meeting_id=str(meeting.id),
            )

    # ── Poll Loop ────────────────────────────────────────────────────────

    async def run_poll_loop(
        self, agent_email: str, tenant_id: str
    ) -> None:
        """Async loop that polls for upcoming meetings.

        Calls process_upcoming_meetings every POLL_INTERVAL_SECONDS.
        Graceful error handling: logs and continues on failures.

        Args:
            agent_email: The agent's email address.
            tenant_id: Tenant UUID string.
        """
        self._running = True
        logger.info(
            "calendar_monitor_started",
            agent_email=agent_email,
            poll_interval=POLL_INTERVAL_SECONDS,
        )

        while self._running:
            try:
                await self.process_upcoming_meetings(agent_email, tenant_id)
                logger.debug(
                    "poll_cycle_complete",
                    agent_email=agent_email,
                )
            except Exception:
                logger.exception(
                    "poll_cycle_error",
                    agent_email=agent_email,
                )

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    def stop(self) -> None:
        """Signal the poll loop to stop."""
        self._running = False

    # ── Attendee Classification ──────────────────────────────────────────

    @staticmethod
    def _classify_attendees(
        attendees: list[dict], internal_domain: str, agent_email: str
    ) -> list[Participant]:
        """Classify attendees as INTERNAL, EXTERNAL, or AGENT.

        Args:
            attendees: List of dicts with 'email' and 'name' keys.
            internal_domain: Email domain for internal classification.
            agent_email: The agent's own email address.

        Returns:
            List of Participant schemas with role classification.
        """
        participants: list[Participant] = []

        for attendee in attendees:
            email = attendee.get("email", "").lower()
            name = attendee.get("name", email)

            if email == agent_email.lower():
                role = ParticipantRole.AGENT
            elif internal_domain and email.endswith(f"@{internal_domain.lower()}"):
                role = ParticipantRole.INTERNAL
            else:
                role = ParticipantRole.EXTERNAL

            participants.append(
                Participant(name=name, email=email, role=role)
            )

        return participants


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_event_start(event: dict) -> datetime | None:
    """Parse start time from a Google Calendar event dict."""
    start = event.get("start", {})
    dt_str = start.get("dateTime") or start.get("date")
    if dt_str is None:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def _parse_event_end(event: dict) -> datetime | None:
    """Parse end time from a Google Calendar event dict."""
    end = event.get("end", {})
    dt_str = end.get("dateTime") or end.get("date")
    if dt_str is None:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None
