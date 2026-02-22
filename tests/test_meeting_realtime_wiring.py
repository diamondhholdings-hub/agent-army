"""Integration tests for real-time pipeline lifecycle and calendar monitor wiring.

Tests verify:
- BotManager creates pipeline on in_call_recording and stores on app.state
- Pipeline cleaned up on call_ended
- Pipeline creation skipped without API keys
- Pipeline meeting context has expected fields
- CalendarMonitor POLL_INTERVAL_SECONDS is 900
- CalendarMonitor.run_poll_loop calls process_upcoming_meetings
- WebSocket finds pipeline on app.state and routes transcript to it

Phase 8 Plan 3 -- Gap closure integration tests.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.meetings.schemas import (
    Meeting,
    MeetingStatus,
    Participant,
    ParticipantRole,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
NOW = datetime.now(timezone.utc)


def _make_meeting(**overrides) -> Meeting:
    """Create a Meeting instance for testing."""
    meeting_id = overrides.pop("id", uuid.uuid4())
    defaults = {
        "id": meeting_id,
        "tenant_id": TENANT_ID,
        "title": "Demo with Acme",
        "scheduled_start": NOW + timedelta(hours=1),
        "scheduled_end": NOW + timedelta(hours=2),
        "google_meet_url": "https://meet.google.com/abc-defg-hij",
        "google_event_id": "event_abc",
        "status": MeetingStatus.IN_PROGRESS,
        "participants": [
            Participant(name="Alice", email="alice@acme.com", role=ParticipantRole.EXTERNAL),
            Participant(name="Agent", email="agent@ourteam.com", role=ParticipantRole.AGENT),
        ],
        "bot_id": "bot-1",
        "recording_url": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    defaults.update(overrides)
    return Meeting(**defaults)


def _make_bot_manager(
    deepgram_api_key: str = "test-dgram-key",
    elevenlabs_api_key: str = "test-el-key",
    elevenlabs_voice_id: str = "test-voice",
    heygen_api_key: str = "test-hg-key",
    heygen_avatar_id: str = "test-avatar",
    app_state: SimpleNamespace | None = None,
) -> "BotManager":
    """Create a BotManager with mocked dependencies for testing."""
    from src.app.meetings.bot.manager import BotManager

    mock_recall = MagicMock()
    mock_repo = AsyncMock()
    mock_repo.update_meeting_status = AsyncMock(return_value=_make_meeting())
    mock_settings = SimpleNamespace(
        MEETING_BOT_NAME="Sales Agent",
        MEETING_BOT_WEBAPP_URL="https://example.com",
        COMPANY_NAME="TestCo",
    )

    return BotManager(
        recall_client=mock_recall,
        repository=mock_repo,
        settings=mock_settings,
        tts_client=None,
        deepgram_api_key=deepgram_api_key,
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_voice_id=elevenlabs_voice_id,
        heygen_api_key=heygen_api_key,
        heygen_avatar_id=heygen_avatar_id,
        llm_service=MagicMock() if deepgram_api_key else None,
        app_state=app_state if app_state is not None else SimpleNamespace(),
    )


# ── Test 1: Pipeline created on in_call_recording ────────────────────────────


async def test_bot_manager_creates_pipeline_on_in_call_recording():
    """BotManager creates pipeline and stores it on app_state when bot enters in_call_recording."""
    app_state = SimpleNamespace()
    meeting = _make_meeting()
    bot_mgr = _make_bot_manager(app_state=app_state)

    mock_pipeline = MagicMock()

    with patch.object(
        bot_mgr, "_find_meeting_by_bot_id", new=AsyncMock(return_value=meeting)
    ), patch.object(
        bot_mgr, "_create_pipeline_for_meeting", new=AsyncMock(return_value=mock_pipeline)
    ):
        await bot_mgr.handle_bot_event(
            bot_id="bot-1",
            event_type="status_change",
            event_data={"code": "in_call_recording"},
        )

    # Pipeline stored on app_state
    attr_name = f"pipeline_{meeting.id}"
    assert getattr(app_state, attr_name, None) is mock_pipeline
    # Also tracked in _active_pipelines
    assert str(meeting.id) in bot_mgr._active_pipelines
    assert bot_mgr._active_pipelines[str(meeting.id)] is mock_pipeline


# ── Test 2: Pipeline cleaned up on call_ended ────────────────────────────────


async def test_bot_manager_cleans_pipeline_on_call_ended():
    """BotManager removes pipeline from app_state and _active_pipelines on call_ended."""
    app_state = SimpleNamespace()
    meeting = _make_meeting()
    bot_mgr = _make_bot_manager(app_state=app_state)

    mock_pipeline = MagicMock()
    # Remove shutdown to avoid await on MagicMock
    del mock_pipeline.shutdown

    with patch.object(
        bot_mgr, "_find_meeting_by_bot_id", new=AsyncMock(return_value=meeting)
    ), patch.object(
        bot_mgr, "_create_pipeline_for_meeting", new=AsyncMock(return_value=mock_pipeline)
    ):
        # First: trigger in_call_recording to create pipeline
        await bot_mgr.handle_bot_event(
            bot_id="bot-1",
            event_type="status_change",
            event_data={"code": "in_call_recording"},
        )

    # Verify pipeline was created
    attr_name = f"pipeline_{meeting.id}"
    assert getattr(app_state, attr_name, None) is mock_pipeline

    with patch.object(
        bot_mgr, "_find_meeting_by_bot_id", new=AsyncMock(return_value=meeting)
    ):
        # Second: trigger call_ended to clean up pipeline
        await bot_mgr.handle_bot_event(
            bot_id="bot-1",
            event_type="status_change",
            event_data={"code": "call_ended"},
        )

    # Pipeline removed from app_state
    assert not hasattr(app_state, attr_name)
    # Pipeline removed from _active_pipelines
    assert str(meeting.id) not in bot_mgr._active_pipelines


# ── Test 3: Pipeline creation skipped without API keys ───────────────────────


async def test_pipeline_creation_skipped_without_api_keys():
    """BotManager does not create pipeline when deepgram_api_key is empty."""
    app_state = SimpleNamespace()
    meeting = _make_meeting()
    bot_mgr = _make_bot_manager(
        deepgram_api_key="",
        elevenlabs_api_key="",
        app_state=app_state,
    )

    with patch.object(
        bot_mgr, "_find_meeting_by_bot_id", new=AsyncMock(return_value=meeting)
    ):
        await bot_mgr.handle_bot_event(
            bot_id="bot-1",
            event_type="status_change",
            event_data={"code": "in_call_recording"},
        )

    # No pipeline should be set on app_state
    attr_name = f"pipeline_{meeting.id}"
    assert not hasattr(app_state, attr_name)
    assert len(bot_mgr._active_pipelines) == 0


# ── Test 4: Pipeline has correct meeting context ─────────────────────────────


async def test_pipeline_has_correct_meeting_context():
    """Pipeline created by BotManager has meeting_id in its meeting_context."""
    app_state = SimpleNamespace()
    meeting = _make_meeting()
    bot_mgr = _make_bot_manager(app_state=app_state)

    mock_pipe_instance = MagicMock()
    mock_pipe_cls = MagicMock(return_value=mock_pipe_instance)

    # Patch realtime modules at their source (lazy imports in _create_pipeline_for_meeting)
    with patch.object(
        bot_mgr, "_find_meeting_by_bot_id", new=AsyncMock(return_value=meeting)
    ), patch(
        "src.app.meetings.realtime.stt.DeepgramSTT", MagicMock()
    ), patch(
        "src.app.meetings.realtime.tts.ElevenLabsTTS", MagicMock()
    ), patch(
        "src.app.meetings.realtime.avatar.HeyGenAvatar", MagicMock()
    ), patch(
        "src.app.meetings.realtime.silence_checker.SilenceChecker", MagicMock()
    ), patch(
        "src.app.meetings.realtime.turn_detector.TurnDetector", MagicMock()
    ), patch(
        "src.app.meetings.realtime.pipeline.RealtimePipeline", mock_pipe_cls
    ):
        await bot_mgr.handle_bot_event(
            bot_id="bot-1",
            event_type="status_change",
            event_data={"code": "in_call_recording"},
        )

    # The pipeline should have been created with correct meeting context
    mock_pipe_cls.assert_called_once()
    call_kwargs = mock_pipe_cls.call_args
    assert call_kwargs is not None
    # meeting_context is passed as keyword arg
    context = call_kwargs.kwargs.get("meeting_context")
    if context is None and len(call_kwargs.args) >= 6:
        context = call_kwargs.args[5]
    assert context is not None
    assert context["meeting_id"] == str(meeting.id)
    assert context["title"] == meeting.title


# ── Test 5: CalendarMonitor POLL_INTERVAL_SECONDS is 900 ─────────────────────


def test_calendar_monitor_poll_interval_is_900():
    """CalendarMonitor POLL_INTERVAL_SECONDS is set to 900 (15 minutes)."""
    from src.app.meetings.calendar.monitor import POLL_INTERVAL_SECONDS

    assert POLL_INTERVAL_SECONDS == 900


# ── Test 6: CalendarMonitor run_poll_loop calls process ──────────────────────


async def test_calendar_monitor_run_poll_loop_calls_process():
    """CalendarMonitor.run_poll_loop calls process_upcoming_meetings at least once."""
    from src.app.meetings.calendar.monitor import CalendarMonitor

    mock_calendar = MagicMock()
    mock_repo = AsyncMock()
    mock_briefing = AsyncMock()

    monitor = CalendarMonitor(
        calendar_service=mock_calendar,
        repository=mock_repo,
        briefing_generator=mock_briefing,
        bot_manager=None,
    )

    # Patch process_upcoming_meetings to be a fast no-op
    with patch.object(
        monitor, "process_upcoming_meetings", new=AsyncMock()
    ) as mock_process:
        # Start the poll loop
        task = asyncio.create_task(
            monitor.run_poll_loop(agent_email="agent@test.com", tenant_id="sys")
        )
        # Let it run at least one cycle
        await asyncio.sleep(0.05)
        monitor.stop()
        # Give it time to finish the current iteration
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert mock_process.call_count >= 1
        # run_poll_loop calls process_upcoming_meetings with positional args
        mock_process.assert_called_with("agent@test.com", "sys")


# ── Test 7: WebSocket finds pipeline on app.state ────────────────────────────


def test_websocket_finds_pipeline_on_app_state():
    """WebSocket routes transcript to pipeline found on app.state."""
    from src.app.api.v1.meetings import router as meetings_router

    meeting_id = str(uuid.uuid4())
    mock_pipeline = MagicMock()
    mock_pipeline.handle_stt_transcript = AsyncMock()

    app = FastAPI()
    app.include_router(meetings_router)

    # Place pipeline on app.state where WebSocket handler expects it
    setattr(app.state, f"pipeline_{meeting_id}", mock_pipeline)

    client = TestClient(app)

    with client.websocket_connect(f"/meetings/ws/{meeting_id}") as ws:
        ws.send_text(json.dumps({
            "type": "transcript",
            "text": "Hello everyone, let's begin.",
            "is_final": True,
            "speaker_id": "speaker_1",
        }))
        response = ws.receive_json()
        # With pipeline present, should get speak response (not silence)
        assert response["type"] == "speak"

    mock_pipeline.handle_stt_transcript.assert_called_once_with(
        transcript="Hello everyone, let's begin.",
        is_final=True,
        speaker_id="speaker_1",
    )
