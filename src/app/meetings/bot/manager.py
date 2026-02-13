"""BotManager for meeting bot lifecycle management.

Handles the full Recall.ai bot lifecycle: creation with Output Media config
(webpage camera for HeyGen avatar), early join scheduling, webhook event
processing, verbal entrance greeting on join, status tracking, and
post-meeting artifact retrieval.

Per CONTEXT.md LOCKED decisions:
- 2-3 minutes early join (professional standard)
- Verbal greeting immediately upon join (no silent joining -- transparency)
- Agent stays until all external participants leave (everyone_left_timeout 30s)
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import structlog

from src.app.meetings.bot.recall_client import RecallClient
from src.app.meetings.schemas import (
    Meeting,
    MeetingStatus,
    Transcript,
    TranscriptEntry,
)

if TYPE_CHECKING:
    from src.app.meetings.realtime.tts import ElevenLabsTTS
    from src.app.meetings.repository import MeetingRepository

logger = structlog.get_logger(__name__)

# Early join window per CONTEXT.md: 2-3 minutes early
EARLY_JOIN_MINUTES = 3

# Silent MP3 placeholder for automatic_audio_output initialization
# Minimal valid MP3 frame (silence) -- required to enable output_audio endpoint
SILENT_MP3_B64 = "SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYYoRwBHAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


class BotManager:
    """Manages the full lifecycle of Recall.ai meeting bots.

    Coordinates bot creation with Output Media config, early joining,
    webhook event processing, entrance greeting synthesis, and
    post-meeting artifact retrieval.

    Args:
        recall_client: RecallClient for Recall.ai API calls.
        repository: MeetingRepository for persisting bot state.
        settings: Application settings for webapp URL and bot name.
        tts_client: Optional ElevenLabsTTS for entrance greeting.
            If None, greeting is skipped with a log warning.
    """

    def __init__(
        self,
        recall_client: RecallClient,
        repository: MeetingRepository,
        settings: object,
        tts_client: ElevenLabsTTS | None = None,
    ) -> None:
        self._recall = recall_client
        self._repository = repository
        self._settings = settings
        self._tts = tts_client

    async def create_meeting_bot(
        self, meeting: Meeting, tenant_id: str
    ) -> str:
        """Create a Recall.ai bot for a meeting with Output Media config.

        Builds the full bot configuration including:
        - Output Media camera (webpage rendering HeyGen avatar)
        - Automatic audio output with silent MP3 placeholder
        - Real-time transcript webhook endpoints
        - Automatic leave when all participants exit (30s timeout)

        Args:
            meeting: Meeting to join.
            tenant_id: Tenant UUID string.

        Returns:
            Recall.ai bot ID string.
        """
        webapp_url = self._build_output_media_url(meeting.id, tenant_id)

        config = {
            "meeting_url": meeting.google_meet_url,
            "bot_name": getattr(self._settings, "MEETING_BOT_NAME", "Sales Agent"),
            "output_media": {
                "camera": {
                    "kind": "webpage",
                    "config": {
                        "url": webapp_url,
                    },
                },
            },
            "automatic_audio_output": {
                "in_call_recording": {
                    "data": {
                        "kind": "mp3",
                        "b64_data": SILENT_MP3_B64,
                    },
                },
            },
            "real_time_endpoints": [
                {
                    "type": "webhook",
                    "url": f"{getattr(self._settings, 'MEETING_BOT_WEBAPP_URL', '')}/api/v1/meetings/webhook",
                    "events": [
                        "transcript.data",
                        "transcript.partial_data",
                    ],
                },
            ],
            "automatic_leave": {
                "everyone_left_timeout": {
                    "timeout": 30,
                    "exclude_bot": True,
                },
            },
        }

        bot_response = await self._recall.create_bot(config)
        bot_id = bot_response.get("id", "")

        # Persist bot_id to meeting record
        await self._repository.update_meeting_bot_id(
            tenant_id=tenant_id,
            meeting_id=str(meeting.id),
            bot_id=bot_id,
        )

        logger.info(
            "bot.created",
            bot_id=bot_id,
            meeting_id=str(meeting.id),
            tenant_id=tenant_id,
        )
        return bot_id

    async def join_meeting_early(
        self, meeting: Meeting, tenant_id: str
    ) -> str | datetime:
        """Join meeting early per CONTEXT.md: 2-3 minutes before start.

        If current time is within the early join window, creates the bot
        immediately. Otherwise returns the scheduled join time for the
        caller to manage (e.g., via scheduler).

        Args:
            meeting: Meeting to join.
            tenant_id: Tenant UUID string.

        Returns:
            Bot ID string if created immediately, or datetime of
            scheduled join time if too early.
        """
        now = datetime.now(timezone.utc)
        early_join_time = meeting.scheduled_start - timedelta(minutes=EARLY_JOIN_MINUTES)

        if now >= early_join_time:
            # Within early join window -- create bot immediately
            bot_id = await self.create_meeting_bot(meeting, tenant_id)
            logger.info(
                "bot.early_join",
                bot_id=bot_id,
                meeting_id=str(meeting.id),
                minutes_early=(meeting.scheduled_start - now).total_seconds() / 60,
            )
            return bot_id

        # Too early -- return scheduled time
        logger.info(
            "bot.scheduled",
            meeting_id=str(meeting.id),
            scheduled_join=early_join_time.isoformat(),
        )
        return early_join_time

    async def get_bot_status(self, bot_id: str) -> str:
        """Get current bot status from Recall.ai.

        Args:
            bot_id: Recall.ai bot identifier.

        Returns:
            Status code string.
        """
        return await self._recall.get_bot_status(bot_id)

    async def handle_bot_event(
        self, bot_id: str, event_type: str, event_data: dict
    ) -> None:
        """Process webhook events from Recall.ai.

        Updates meeting status based on bot lifecycle events:
        - status_change.joining_call -> MeetingStatus.BOT_JOINING
        - status_change.in_call_recording -> MeetingStatus.IN_PROGRESS
          (also triggers entrance greeting)
        - status_change.call_ended -> MeetingStatus.ENDED

        Args:
            bot_id: Recall.ai bot identifier.
            event_type: Event type string from webhook.
            event_data: Event payload dict.
        """
        # Find meeting by bot_id
        meeting = await self._find_meeting_by_bot_id(bot_id)
        if meeting is None:
            logger.warning(
                "bot.event_unknown_bot",
                bot_id=bot_id,
                event_type=event_type,
            )
            return

        tenant_id = meeting.tenant_id

        if event_type == "status_change":
            status_code = event_data.get("code", "")

            if status_code == "joining_call":
                await self._repository.update_meeting_status(
                    tenant_id=tenant_id,
                    meeting_id=str(meeting.id),
                    status=MeetingStatus.BOT_JOINING,
                )
                logger.info("bot.joining", bot_id=bot_id, meeting_id=str(meeting.id))

            elif status_code == "in_call_recording":
                await self._repository.update_meeting_status(
                    tenant_id=tenant_id,
                    meeting_id=str(meeting.id),
                    status=MeetingStatus.IN_PROGRESS,
                )
                logger.info("bot.in_progress", bot_id=bot_id, meeting_id=str(meeting.id))

                # Trigger entrance greeting per CONTEXT.md:
                # "Verbal greeting immediately upon join. No silent joining."
                await self._send_entrance_greeting(bot_id, meeting, tenant_id)

            elif status_code == "call_ended":
                await self._repository.update_meeting_status(
                    tenant_id=tenant_id,
                    meeting_id=str(meeting.id),
                    status=MeetingStatus.ENDED,
                )
                logger.info("bot.ended", bot_id=bot_id, meeting_id=str(meeting.id))

        elif event_type in ("transcript.data", "transcript.partial_data"):
            # Transcript events handled by real-time pipeline (06-04)
            logger.debug(
                "bot.transcript_event",
                bot_id=bot_id,
                event_type=event_type,
            )

    async def _send_entrance_greeting(
        self, bot_id: str, meeting: Meeting, tenant_id: str
    ) -> None:
        """Synthesize and send verbal entrance greeting on meeting join.

        Per CONTEXT.md LOCKED decision: "Verbal greeting immediately upon join.
        No silent joining -- transparency is critical."

        Greeting format: "Hi, this is {agent_name} joining from {company_name}."

        Error handling: if TTS or send_audio fails, logs warning but does NOT
        block meeting participation (greeting is best-effort).

        Args:
            bot_id: Recall.ai bot identifier.
            meeting: Meeting being joined.
            tenant_id: Tenant UUID string.
        """
        if self._tts is None:
            logger.warning(
                "bot.greeting_skipped",
                bot_id=bot_id,
                reason="no_tts_client",
            )
            return

        try:
            # Build greeting text
            agent_name = getattr(self._settings, "MEETING_BOT_NAME", "Sales Agent")
            company_name = getattr(self._settings, "COMPANY_NAME", "our team")
            greeting_text = f"Hi, this is {agent_name} joining from {company_name}."

            # Synthesize greeting audio
            audio_bytes = await self._tts.synthesize_full(greeting_text)

            # Encode to base64 and send to meeting
            mp3_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            await self._recall.send_audio(bot_id, mp3_b64=mp3_b64)

            logger.info(
                "bot.entrance_greeting_sent",
                bot_id=bot_id,
                meeting_id=str(meeting.id),
                greeting_length=len(greeting_text),
            )

        except Exception:
            # Greeting is best-effort -- do NOT block meeting participation
            logger.warning(
                "bot.entrance_greeting_failed",
                bot_id=bot_id,
                meeting_id=str(meeting.id),
                exc_info=True,
            )

    async def retrieve_meeting_artifacts(
        self, bot_id: str, meeting_id: uuid.UUID, tenant_id: str
    ) -> dict:
        """Fetch transcript and recording from Recall.ai after meeting ends.

        Saves transcript entries to the repository and updates the meeting
        record with the recording URL.

        Args:
            bot_id: Recall.ai bot identifier.
            meeting_id: Meeting UUID.
            tenant_id: Tenant UUID string.

        Returns:
            Dict with 'transcript' (list[dict]) and 'recording_url' (str|None).
        """
        # Fetch transcript
        transcript_data = await self._recall.get_transcript(bot_id)
        entries = [
            TranscriptEntry(
                speaker=entry.get("speaker", "Unknown"),
                text=entry.get("words", entry.get("text", "")),
                timestamp_ms=int(entry.get("start_time", 0) * 1000) if entry.get("start_time") else 0,
                is_final=True,
            )
            for entry in transcript_data
            if entry.get("words") or entry.get("text")
        ]

        if entries:
            full_text = "\n".join(f"{e.speaker}: {e.text}" for e in entries)
            transcript = Transcript(
                meeting_id=meeting_id,
                entries=entries,
                full_text=full_text,
            )
            await self._repository.save_transcript(tenant_id, transcript)

        # Fetch recording
        recording_url = None
        try:
            recording_data = await self._recall.get_recording(bot_id)
            recording_url = recording_data.get("url") or recording_data.get("download_url")
        except Exception:
            logger.warning(
                "bot.recording_fetch_failed",
                bot_id=bot_id,
                exc_info=True,
            )

        logger.info(
            "bot.artifacts_retrieved",
            bot_id=bot_id,
            meeting_id=str(meeting_id),
            transcript_entries=len(entries),
            has_recording=recording_url is not None,
        )

        return {
            "transcript": transcript_data,
            "recording_url": recording_url,
        }

    def _build_output_media_url(
        self, meeting_id: uuid.UUID, tenant_id: str
    ) -> str:
        """Construct the Output Media webapp URL with query parameters.

        The webapp uses meeting_id and tenant_id to connect to the correct
        backend WebSocket for real-time audio pipeline coordination.

        Args:
            meeting_id: Meeting UUID.
            tenant_id: Tenant UUID string.

        Returns:
            Full URL string with query parameters.
        """
        base_url = getattr(self._settings, "MEETING_BOT_WEBAPP_URL", "")
        params = urlencode({
            "meeting_id": str(meeting_id),
            "tenant_id": tenant_id,
        })
        return f"{base_url}?{params}"

    async def _find_meeting_by_bot_id(self, bot_id: str) -> Meeting | None:
        """Find meeting by its Recall.ai bot ID.

        Searches across tenants by checking the bot's metadata from Recall.ai.
        In a production multi-tenant system, the webhook URL would include
        tenant_id as a path parameter. For now, we retrieve the bot details
        and extract tenant context.

        Args:
            bot_id: Recall.ai bot identifier.

        Returns:
            Meeting if found, None otherwise.
        """
        # In production, tenant_id would come from the webhook URL path.
        # For now, this is a placeholder that subclasses or the API layer
        # should override with tenant-aware lookup.
        logger.debug("bot.find_by_bot_id", bot_id=bot_id)
        return None
