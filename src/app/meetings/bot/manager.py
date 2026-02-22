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
from typing import TYPE_CHECKING, Any
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


class _NoOpAvatar:
    """Stub avatar when HeyGen API key is not configured."""

    async def speak(self, *a: Any, **kw: Any) -> None:
        pass

    async def react(self, *a: Any, **kw: Any) -> None:
        pass

    async def stop(self) -> None:
        pass


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
        deepgram_api_key: Deepgram API key for STT pipeline.
        elevenlabs_api_key: ElevenLabs API key for TTS pipeline.
        elevenlabs_voice_id: ElevenLabs voice ID for TTS pipeline.
        heygen_api_key: HeyGen API key for avatar pipeline.
        heygen_avatar_id: HeyGen avatar ID for avatar pipeline.
        llm_service: LLM service for pipeline reasoning.
        app_state: FastAPI app.state for pipeline storage.
    """

    def __init__(
        self,
        recall_client: RecallClient,
        repository: MeetingRepository,
        settings: object,
        tts_client: ElevenLabsTTS | None = None,
        # Pipeline factory dependencies (Phase 8 gap closure)
        deepgram_api_key: str = "",
        elevenlabs_api_key: str = "",
        elevenlabs_voice_id: str = "",
        heygen_api_key: str = "",
        heygen_avatar_id: str = "",
        llm_service: Any = None,
        app_state: Any = None,
    ) -> None:
        self._recall = recall_client
        self._repository = repository
        self._settings = settings
        self._tts = tts_client
        # Pipeline factory state
        self._deepgram_api_key = deepgram_api_key
        self._elevenlabs_api_key = elevenlabs_api_key
        self._elevenlabs_voice_id = elevenlabs_voice_id
        self._heygen_api_key = heygen_api_key
        self._heygen_avatar_id = heygen_avatar_id
        self._llm_service = llm_service
        self._app_state = app_state
        self._active_pipelines: dict[str, Any] = {}

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

                # Create real-time pipeline for this meeting
                pipeline = await self._create_pipeline_for_meeting(meeting, tenant_id)
                if pipeline is not None:
                    self._active_pipelines[str(meeting.id)] = pipeline
                    # Store on app.state where WebSocket handler expects it.
                    # Note: meeting.id is a uuid.UUID; str(uuid.UUID) produces the standard
                    # hyphenated format "xxxxxxxx-xxxx-..." which matches what
                    # _build_output_media_url passes as the meeting_id query param and what
                    # the WebSocket endpoint receives as its path parameter.
                    if self._app_state is not None:
                        setattr(self._app_state, f"pipeline_{meeting.id}", pipeline)
                    logger.info(
                        "pipeline.stored_on_app_state",
                        meeting_id=str(meeting.id),
                        attr_name=f"pipeline_{meeting.id}",
                    )

            elif status_code == "call_ended":
                await self._repository.update_meeting_status(
                    tenant_id=tenant_id,
                    meeting_id=str(meeting.id),
                    status=MeetingStatus.ENDED,
                )
                logger.info("bot.ended", bot_id=bot_id, meeting_id=str(meeting.id))

                # Clean up real-time pipeline
                meeting_id_str = str(meeting.id)
                pipeline = self._active_pipelines.pop(meeting_id_str, None)
                if pipeline is not None:
                    try:
                        if hasattr(pipeline, "shutdown"):
                            await pipeline.shutdown()
                    except Exception:
                        logger.warning(
                            "pipeline.shutdown_error",
                            meeting_id=meeting_id_str,
                            exc_info=True,
                        )
                    # Remove from app.state
                    if self._app_state is not None:
                        try:
                            delattr(self._app_state, f"pipeline_{meeting.id}")
                        except AttributeError:
                            pass
                    logger.info("pipeline.cleaned_up", meeting_id=meeting_id_str)

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

    async def _create_pipeline_for_meeting(
        self, meeting: Meeting, tenant_id: str
    ) -> Any | None:
        """Create a RealtimePipeline for a meeting that just started recording.

        Instantiates all real-time components (STT, TTS, Avatar, SilenceChecker)
        using stored API keys, then builds the pipeline with meeting context.

        Returns None if any required API key is missing (graceful degradation).
        """
        if not all([self._deepgram_api_key, self._elevenlabs_api_key, self._llm_service]):
            logger.warning(
                "pipeline.creation_skipped",
                meeting_id=str(meeting.id),
                reason="missing_api_keys_or_llm_service",
            )
            return None

        try:
            from src.app.meetings.realtime.stt import DeepgramSTT
            from src.app.meetings.realtime.tts import ElevenLabsTTS
            from src.app.meetings.realtime.avatar import HeyGenAvatar
            from src.app.meetings.realtime.silence_checker import SilenceChecker
            from src.app.meetings.realtime.turn_detector import TurnDetector
            from src.app.meetings.realtime.pipeline import RealtimePipeline

            stt_client = DeepgramSTT(api_key=self._deepgram_api_key)
            tts_client = ElevenLabsTTS(
                api_key=self._elevenlabs_api_key,
                voice_id=self._elevenlabs_voice_id,
            )
            # Use _NoOpAvatar stub when HeyGen key is not configured
            avatar_client: Any = HeyGenAvatar(
                api_key=self._heygen_api_key,
                avatar_id=self._heygen_avatar_id,
            ) if self._heygen_api_key else _NoOpAvatar()

            turn_detector = TurnDetector()
            from src.app.meetings.schemas import ParticipantRole
            participant_roles: dict[str, ParticipantRole] = {}
            if hasattr(meeting, "participants") and meeting.participants:
                for p in meeting.participants:
                    participant_roles[p.email] = p.role

            silence_checker = SilenceChecker(
                turn_detector=turn_detector,
                participant_roles=participant_roles,
            )

            meeting_context = {
                "meeting_id": str(meeting.id),
                "title": meeting.title,
                "tenant_id": tenant_id,
                "participants": [
                    {"name": p.name, "email": p.email, "role": p.role.value}
                    for p in (meeting.participants or [])
                ],
            }

            pipeline = RealtimePipeline(
                stt_client=stt_client,
                tts_client=tts_client,
                avatar_client=avatar_client,
                silence_checker=silence_checker,
                llm_service=self._llm_service,
                meeting_context=meeting_context,
            )

            logger.info(
                "pipeline.created",
                meeting_id=str(meeting.id),
                tenant_id=tenant_id,
                has_avatar=bool(self._heygen_api_key),
            )
            return pipeline

        except Exception:
            logger.warning(
                "pipeline.creation_failed",
                meeting_id=str(meeting.id),
                exc_info=True,
            )
            return None

    async def _find_meeting_by_bot_id(self, bot_id: str) -> Meeting | None:
        """Find meeting by its Recall.ai bot ID.

        Uses the repository's cross-tenant get_meeting_by_bot_id lookup
        since at webhook time only the bot_id is known (tenant not yet
        resolved).

        Args:
            bot_id: Recall.ai bot identifier.

        Returns:
            Meeting if found, None otherwise.
        """
        logger.debug("bot.find_by_bot_id", bot_id=bot_id)
        try:
            meeting = await self._repository.get_meeting_by_bot_id(bot_id)
            return meeting
        except Exception:
            logger.warning("bot.find_by_bot_id_failed", bot_id=bot_id, exc_info=True)
            return None
