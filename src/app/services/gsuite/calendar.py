"""Google Calendar service for meeting detection via domain-wide delegation.

Extends the GSuiteAuthManager pattern from auth.py to provide Calendar API v3
access. Detects meetings where the sales agent is explicitly invited and
extracts Google Meet URLs, attendee lists, and event metadata.

Used by the CalendarMonitor (future 06-02) to poll for upcoming meetings
and trigger briefing generation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from googleapiclient.discovery import build

from src.app.services.gsuite.auth import GSuiteAuthManager

logger = structlog.get_logger(__name__)

# Calendar API scopes for read-only access to events
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
]


class GoogleCalendarService:
    """Google Calendar API v3 service for meeting detection.

    Uses GSuiteAuthManager for credential management with domain-wide
    delegation. Caches Calendar API service instances per user email
    (same pattern as get_gmail_service in auth.py).

    Args:
        auth_manager: GSuiteAuthManager instance (shared with Gmail/Chat).
    """

    def __init__(self, auth_manager: GSuiteAuthManager) -> None:
        self._auth_manager = auth_manager
        self._service_cache: dict[str, Any] = {}

    def get_calendar_service(self, user_email: str) -> Any:
        """Get a cached Calendar API v3 service for the delegated user.

        Args:
            user_email: Email to impersonate via domain-wide delegation.

        Returns:
            Calendar API Resource object.
        """
        cache_key = f"calendar:{user_email}"

        if cache_key not in self._service_cache:
            logger.info(
                "building_calendar_service",
                user_email=user_email,
            )
            credentials = self._auth_manager._build_credentials(
                user_email, CALENDAR_SCOPES
            )
            service = build("calendar", "v3", credentials=credentials)
            self._service_cache[cache_key] = service

        return self._service_cache[cache_key]

    def list_upcoming_events(
        self,
        agent_email: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[dict]:
        """Fetch upcoming events where the agent email is an attendee.

        Queries the agent's calendar for events in the given time window,
        then filters to events where the agent is explicitly invited.

        Args:
            agent_email: The agent's email address to check.
            time_min: Start of time window.
            time_max: End of time window.

        Returns:
            List of Google Calendar event dicts where agent is an attendee.
        """
        service = self.get_calendar_service(agent_email)

        events_result = (
            service.events()
            .list(
                calendarId=agent_email,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        all_events = events_result.get("items", [])

        return [
            event
            for event in all_events
            if self.is_agent_invited(event, agent_email)
        ]

    def get_event(self, agent_email: str, event_id: str) -> dict:
        """Fetch a single calendar event by ID.

        Args:
            agent_email: Email for authentication delegation.
            event_id: Google Calendar event ID.

        Returns:
            Google Calendar event dict.
        """
        service = self.get_calendar_service(agent_email)

        return (
            service.events()
            .get(calendarId=agent_email, eventId=event_id)
            .execute()
        )

    @staticmethod
    def is_agent_invited(event: dict, agent_email: str) -> bool:
        """Check if the agent email is in the event attendee list.

        Only returns True for explicit invites -- the agent must appear
        in the attendees list. Being the calendar owner or organizer
        alone is not sufficient (per CONTEXT.md: explicit invite required).

        Args:
            event: Google Calendar event dict.
            agent_email: The agent's email address.

        Returns:
            True if agent is explicitly listed as an attendee.
        """
        attendees = event.get("attendees", [])
        return any(
            a.get("email", "").lower() == agent_email.lower()
            for a in attendees
        )

    @staticmethod
    def has_google_meet_link(event: dict) -> bool:
        """Check if the event has a Google Meet video conference link.

        Looks in conferenceData.entryPoints for an entry with type "video".

        Args:
            event: Google Calendar event dict.

        Returns:
            True if event has a Google Meet link.
        """
        conference = event.get("conferenceData", {})
        entry_points = conference.get("entryPoints", [])
        return any(ep.get("entryPointType") == "video" for ep in entry_points)

    @staticmethod
    def get_meet_url(event: dict) -> str | None:
        """Extract the Google Meet URL from an event.

        Args:
            event: Google Calendar event dict.

        Returns:
            Google Meet URL string, or None if not found.
        """
        conference = event.get("conferenceData", {})
        entry_points = conference.get("entryPoints", [])
        for ep in entry_points:
            if ep.get("entryPointType") == "video":
                return ep.get("uri")
        return None

    @staticmethod
    def get_attendees(event: dict) -> list[dict]:
        """Extract attendee list from an event.

        Returns simplified attendee dicts with name and email.

        Args:
            event: Google Calendar event dict.

        Returns:
            List of dicts with 'email' and 'name' keys.
        """
        attendees = event.get("attendees", [])
        return [
            {
                "email": a.get("email", ""),
                "name": a.get("displayName", a.get("email", "")),
            }
            for a in attendees
        ]
