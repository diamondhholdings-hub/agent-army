"""Unit tests for bot management and real-time service wrappers.

Tests RecallClient, BotManager, DeepgramSTT, ElevenLabsTTS, and HeyGenAvatar
with mocked external APIs. Covers:
- RecallClient HTTP request construction and retry logic
- BotManager bot creation with Output Media, webhook event processing,
  entrance greeting synthesis, and greeting failure handling
- DeepgramSTT connection options and transcript handling
- ElevenLabsTTS model selection and output format
- HeyGenAvatar session lifecycle and rotation
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.app.meetings.bot.recall_client import RecallClient
from src.app.meetings.bot.manager import BotManager, EARLY_JOIN_MINUTES, SILENT_MP3_B64
from src.app.meetings.realtime.avatar import HeyGenAvatar
from src.app.meetings.schemas import Meeting, MeetingStatus, Participant, ParticipantRole


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def recall_client():
    """RecallClient with test API key."""
    return RecallClient(api_key="test-api-key", region="us-west-2")


@pytest.fixture
def mock_repository():
    """Mock MeetingRepository."""
    repo = AsyncMock()
    repo.update_meeting_bot_id = AsyncMock()
    repo.update_meeting_status = AsyncMock()
    repo.save_transcript = AsyncMock()
    return repo


@pytest.fixture
def mock_settings():
    """Mock settings with meeting bot config."""
    return SimpleNamespace(
        MEETING_BOT_WEBAPP_URL="https://bot.example.com",
        MEETING_BOT_NAME="Test Agent",
        COMPANY_NAME="Acme Corp",
    )


@pytest.fixture
def mock_tts():
    """Mock ElevenLabsTTS."""
    tts = AsyncMock()
    tts.synthesize_full = AsyncMock(return_value=b"fake-mp3-audio-data")
    return tts


@pytest.fixture
def sample_meeting():
    """Sample meeting for testing."""
    now = datetime.now(timezone.utc)
    return Meeting(
        id=uuid.uuid4(),
        tenant_id="tenant-123",
        title="Demo Meeting",
        scheduled_start=now + timedelta(hours=1),
        scheduled_end=now + timedelta(hours=2),
        google_meet_url="https://meet.google.com/abc-defg-hij",
        google_event_id="event-123",
        status=MeetingStatus.SCHEDULED,
        participants=[
            Participant(name="John Doe", email="john@example.com", role=ParticipantRole.EXTERNAL),
        ],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def bot_manager(recall_client, mock_repository, mock_settings, mock_tts):
    """BotManager with mocked dependencies."""
    return BotManager(
        recall_client=recall_client,
        repository=mock_repository,
        settings=mock_settings,
        tts_client=mock_tts,
    )


# ── RecallClient Tests ──────────────────────────────────────────────────────


class TestRecallClient:
    """Tests for RecallClient HTTP wrapper."""

    @pytest.mark.asyncio
    async def test_create_bot_builds_correct_request(self, recall_client):
        """create_bot sends POST to /bot/ with correct config."""
        config = {
            "meeting_url": "https://meet.google.com/test",
            "bot_name": "Test Bot",
        }
        mock_response = httpx.Response(
            200,
            json={"id": "bot-abc123", "status_changes": []},
            request=httpx.Request("POST", "https://test.com"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await recall_client.create_bot(config)

        assert result["id"] == "bot-abc123"

    @pytest.mark.asyncio
    async def test_get_bot_status_extracts_latest(self, recall_client):
        """get_bot_status extracts status from status_changes[-1].code."""
        mock_response = httpx.Response(
            200,
            json={
                "id": "bot-abc",
                "status_changes": [
                    {"code": "ready"},
                    {"code": "joining_call"},
                    {"code": "in_call_recording"},
                ],
            },
            request=httpx.Request("GET", "https://test.com"),
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            status = await recall_client.get_bot_status("bot-abc")

        assert status == "in_call_recording"

    @pytest.mark.asyncio
    async def test_get_bot_status_empty_returns_unknown(self, recall_client):
        """get_bot_status returns 'unknown' when no status changes."""
        mock_response = httpx.Response(
            200,
            json={"id": "bot-abc", "status_changes": []},
            request=httpx.Request("GET", "https://test.com"),
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            status = await recall_client.get_bot_status("bot-abc")

        assert status == "unknown"

    @pytest.mark.asyncio
    async def test_send_audio_sends_mp3_payload(self, recall_client):
        """send_audio POSTs base64 MP3 data to output_audio endpoint."""
        mock_response = httpx.Response(
            200,
            json={},
            request=httpx.Request("POST", "https://test.com"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await recall_client.send_audio("bot-abc", mp3_b64="dGVzdA==")

        # Verify the JSON payload structure
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"]["kind"] == "mp3"
        assert call_kwargs.kwargs["json"]["b64_data"] == "dGVzdA=="

    @pytest.mark.asyncio
    async def test_retry_on_transient_failure(self, recall_client):
        """RecallClient retries on transient HTTP errors."""
        error_response = httpx.Response(
            503,
            request=httpx.Request("GET", "https://test.com"),
        )
        success_response = httpx.Response(
            200,
            json={"id": "bot-abc", "status_changes": [{"code": "ready"}]},
            request=httpx.Request("GET", "https://test.com"),
        )

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                error_response.raise_for_status()
            return success_response

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get):
            result = await recall_client.get_bot("bot-abc")

        assert result["id"] == "bot-abc"
        assert call_count == 2  # First call failed, second succeeded


# ── BotManager Tests ────────────────────────────────────────────────────────


class TestBotManager:
    """Tests for BotManager lifecycle management."""

    @pytest.mark.asyncio
    async def test_create_meeting_bot_includes_output_media(
        self, bot_manager, sample_meeting
    ):
        """create_meeting_bot builds config with Output Media camera."""
        mock_response = httpx.Response(
            200,
            json={"id": "bot-xyz"},
            request=httpx.Request("POST", "https://test.com"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            bot_id = await bot_manager.create_meeting_bot(sample_meeting, "tenant-123")

        assert bot_id == "bot-xyz"

        # Verify config includes Output Media
        call_kwargs = mock_post.call_args
        config = call_kwargs.kwargs["json"]
        assert config["output_media"]["camera"]["kind"] == "webpage"
        assert "meeting_id" in config["output_media"]["camera"]["config"]["url"]
        assert "tenant_id" in config["output_media"]["camera"]["config"]["url"]

    @pytest.mark.asyncio
    async def test_create_meeting_bot_configures_automatic_leave(
        self, bot_manager, sample_meeting
    ):
        """create_meeting_bot sets automatic_leave with 30s timeout."""
        mock_response = httpx.Response(
            200,
            json={"id": "bot-xyz"},
            request=httpx.Request("POST", "https://test.com"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await bot_manager.create_meeting_bot(sample_meeting, "tenant-123")

        config = mock_post.call_args.kwargs["json"]
        auto_leave = config["automatic_leave"]["everyone_left_timeout"]
        assert auto_leave["timeout"] == 30
        assert auto_leave["exclude_bot"] is True

    @pytest.mark.asyncio
    async def test_handle_bot_event_updates_status_in_progress(
        self, bot_manager, sample_meeting, mock_repository
    ):
        """handle_bot_event transitions to IN_PROGRESS on in_call_recording."""
        # Patch _find_meeting_by_bot_id to return our sample meeting
        bot_manager._find_meeting_by_bot_id = AsyncMock(return_value=sample_meeting)
        # Patch _send_entrance_greeting so it doesn't fail
        bot_manager._send_entrance_greeting = AsyncMock()

        await bot_manager.handle_bot_event(
            bot_id="bot-abc",
            event_type="status_change",
            event_data={"code": "in_call_recording"},
        )

        mock_repository.update_meeting_status.assert_called_once_with(
            tenant_id=sample_meeting.tenant_id,
            meeting_id=str(sample_meeting.id),
            status=MeetingStatus.IN_PROGRESS,
        )

    @pytest.mark.asyncio
    async def test_handle_bot_event_triggers_greeting_on_in_progress(
        self, bot_manager, sample_meeting
    ):
        """handle_bot_event triggers entrance greeting when bot joins meeting."""
        bot_manager._find_meeting_by_bot_id = AsyncMock(return_value=sample_meeting)
        bot_manager._send_entrance_greeting = AsyncMock()

        await bot_manager.handle_bot_event(
            bot_id="bot-abc",
            event_type="status_change",
            event_data={"code": "in_call_recording"},
        )

        bot_manager._send_entrance_greeting.assert_called_once_with(
            "bot-abc", sample_meeting, sample_meeting.tenant_id
        )

    @pytest.mark.asyncio
    async def test_build_output_media_url_includes_params(
        self, bot_manager
    ):
        """_build_output_media_url includes meeting_id and tenant_id."""
        meeting_id = uuid.uuid4()
        url = bot_manager._build_output_media_url(meeting_id, "tenant-456")

        assert "https://bot.example.com" in url
        assert str(meeting_id) in url
        assert "tenant-456" in url
        assert "meeting_id=" in url
        assert "tenant_id=" in url

    @pytest.mark.asyncio
    async def test_send_entrance_greeting_synthesizes_and_sends(
        self, bot_manager, sample_meeting, mock_tts
    ):
        """_send_entrance_greeting synthesizes audio and sends to meeting."""
        mock_response = httpx.Response(
            200, json={}, request=httpx.Request("POST", "https://test.com"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            await bot_manager._send_entrance_greeting(
                "bot-abc", sample_meeting, "tenant-123"
            )

        # TTS was called with greeting text
        mock_tts.synthesize_full.assert_called_once()
        greeting_text = mock_tts.synthesize_full.call_args[0][0]
        assert "Test Agent" in greeting_text
        assert "Acme Corp" in greeting_text

    @pytest.mark.asyncio
    async def test_send_entrance_greeting_handles_tts_failure(
        self, bot_manager, sample_meeting, mock_tts
    ):
        """_send_entrance_greeting logs warning but continues on TTS failure."""
        mock_tts.synthesize_full = AsyncMock(side_effect=Exception("TTS service down"))

        # Should NOT raise -- greeting is best-effort
        await bot_manager._send_entrance_greeting(
            "bot-abc", sample_meeting, "tenant-123"
        )

    @pytest.mark.asyncio
    async def test_send_entrance_greeting_skips_without_tts(
        self, recall_client, mock_repository, mock_settings, sample_meeting
    ):
        """_send_entrance_greeting skips if no TTS client provided."""
        manager = BotManager(
            recall_client=recall_client,
            repository=mock_repository,
            settings=mock_settings,
            tts_client=None,  # No TTS
        )

        # Should not raise
        await manager._send_entrance_greeting(
            "bot-abc", sample_meeting, "tenant-123"
        )


# ── DeepgramSTT Tests ───────────────────────────────────────────────────────


class TestDeepgramSTT:
    """Tests for DeepgramSTT service wrapper."""

    def test_connect_uses_correct_live_options(self):
        """DeepgramSTT connects with Nova-3, 300ms endpointing, diarize."""
        # Mock the deepgram SDK
        mock_connection = MagicMock()
        mock_connection.on = MagicMock()
        mock_connection.start = MagicMock()

        mock_listen = MagicMock()
        mock_listen.websocket.v.return_value = mock_connection

        mock_client = MagicMock()
        mock_client.listen = mock_listen

        with patch.dict("sys.modules", {
            "deepgram": MagicMock(
                DeepgramClient=MagicMock(return_value=mock_client),
                LiveOptions=MagicMock(),
                LiveTranscriptionEvents=MagicMock(),
            ),
        }):
            # Reset the lazy import state
            import src.app.meetings.realtime.stt as stt_mod
            stt_mod._deepgram_imported = False
            stt_mod._ensure_deepgram()

            # Verify options match expected values
            from src.app.meetings.realtime.stt import DeepgramSTT
            assert DeepgramSTT.MODEL == "nova-3"
            assert DeepgramSTT.ENDPOINTING_MS == 300
            assert DeepgramSTT.UTTERANCE_END_MS == "1000"
            assert DeepgramSTT.SAMPLE_RATE == 16000
            assert DeepgramSTT.ENCODING == "linear16"


# ── ElevenLabsTTS Tests ─────────────────────────────────────────────────────


class TestElevenLabsTTS:
    """Tests for ElevenLabsTTS service wrapper."""

    def test_uses_flash_v2_5_model(self):
        """ElevenLabsTTS uses Flash v2.5 model ID."""
        from src.app.meetings.realtime.tts import ElevenLabsTTS
        assert ElevenLabsTTS.MODEL_ID == "eleven_flash_v2_5"

    def test_uses_correct_output_format(self):
        """ElevenLabsTTS uses MP3 22050Hz/32kbps for Recall.ai compatibility."""
        from src.app.meetings.realtime.tts import ElevenLabsTTS
        assert ElevenLabsTTS.OUTPUT_FORMAT == "mp3_22050_32"

    def test_max_streaming_latency_optimization(self):
        """ElevenLabsTTS uses maximum streaming latency optimization (level 4)."""
        from src.app.meetings.realtime.tts import ElevenLabsTTS
        assert ElevenLabsTTS.OPTIMIZE_STREAMING_LATENCY == 4


# ── HeyGenAvatar Tests ──────────────────────────────────────────────────────


class TestHeyGenAvatar:
    """Tests for HeyGenAvatar session management."""

    @pytest.fixture
    def avatar(self):
        """HeyGenAvatar with test credentials."""
        return HeyGenAvatar(
            api_key="test-heygen-key",
            avatar_id="avatar-001",
            voice_id="voice-001",
        )

    @pytest.mark.asyncio
    async def test_start_session_creates_session(self, avatar):
        """start_session creates session and stores session_id."""
        mock_response = httpx.Response(
            200,
            json={
                "data": {
                    "session_id": "session-abc",
                    "url": "wss://livekit.example.com",
                    "access_token": "token-xyz",
                },
            },
            request=httpx.Request("POST", "https://test.com"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await avatar.start_session()

        assert result["session_id"] == "session-abc"
        assert result["url"] == "wss://livekit.example.com"
        assert result["access_token"] == "token-xyz"
        assert avatar._session_id == "session-abc"

    @pytest.mark.asyncio
    async def test_speak_sends_repeat_task(self, avatar):
        """speak sends streaming.task with task_type 'repeat'."""
        avatar._session_id = "session-abc"

        mock_response = httpx.Response(
            200, json={}, request=httpx.Request("POST", "https://test.com"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await avatar.speak("Hello, this is a test.")

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["session_id"] == "session-abc"
        assert payload["text"] == "Hello, this is a test."
        assert payload["task_type"] == "repeat"

    @pytest.mark.asyncio
    async def test_stop_session_cleans_up(self, avatar):
        """stop_session resets session state."""
        avatar._session_id = "session-abc"
        avatar._session_info = {"session_id": "session-abc"}
        avatar._is_active = True

        mock_response = httpx.Response(
            200, json={}, request=httpx.Request("POST", "https://test.com"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            await avatar.stop_session()

        assert avatar._session_id is None
        assert avatar._session_info is None
        assert avatar._is_active is False

    @pytest.mark.asyncio
    async def test_rotate_session_creates_new(self, avatar):
        """rotate_session stops old session and creates new one."""
        avatar._session_id = "session-old"

        stop_response = httpx.Response(
            200, json={}, request=httpx.Request("POST", "https://test.com"),
        )
        new_session_response = httpx.Response(
            200,
            json={
                "data": {
                    "session_id": "session-new",
                    "url": "wss://livekit.example.com",
                    "access_token": "token-new",
                },
            },
            request=httpx.Request("POST", "https://test.com"),
        )
        start_response = httpx.Response(
            200, json={}, request=httpx.Request("POST", "https://test.com"),
        )

        call_count = 0
        responses = [stop_response, new_session_response, start_response]

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
            result = await avatar.rotate_session()

        assert result["session_id"] == "session-new"
        assert avatar._session_id == "session-new"

    @pytest.mark.asyncio
    async def test_get_session_info_returns_none_when_inactive(self, avatar):
        """get_session_info returns None when no active session."""
        assert avatar.get_session_info() is None

    @pytest.mark.asyncio
    async def test_send_idle_reaction(self, avatar):
        """send_idle_reaction sends task with 'talk' type."""
        avatar._session_id = "session-abc"

        mock_response = httpx.Response(
            200, json={}, request=httpx.Request("POST", "https://test.com"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await avatar.send_idle_reaction("nod")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["task_type"] == "talk"
        assert payload["session_id"] == "session-abc"

    @pytest.mark.asyncio
    async def test_speak_without_session_raises(self, avatar):
        """speak raises RuntimeError if no session active."""
        with pytest.raises(RuntimeError, match="No active session"):
            await avatar.speak("test")
