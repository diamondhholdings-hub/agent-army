"""Tests for real-time meeting pipeline: TurnDetector, SilenceChecker, RealtimePipeline.

Tests cover:
- TurnDetector pause classification (end-of-turn vs thinking pause)
- SilenceChecker strategic silence enforcement (all three rules)
- RealtimePipeline orchestration with mock LLM, TTS, avatar
- Pipeline confidence gating, SILENCE_TOKEN, sentence boundaries
- PipelineMetrics computed properties
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.meetings.realtime.pipeline import (
    CONFIDENCE_PREFIX_RE,
    LATENCY_BUDGET_MS,
    LLM_TIMEOUT_MS,
    MAX_CONTEXT_TURNS,
    SILENCE_TOKEN,
    PipelineMetrics,
    RealtimePipeline,
)
from src.app.meetings.realtime.silence_checker import (
    CONFIDENCE_THRESHOLD,
    SilenceChecker,
)
from src.app.meetings.realtime.turn_detector import (
    ACTIVE_SPEAKER_THRESHOLD_MS,
    END_OF_TURN_MS,
    THINKING_PAUSE_MS,
    TurnDetector,
)
from src.app.meetings.schemas import ParticipantRole


class MockLLM:
    """Simple async callable LLM mock for pipeline tests.

    Does NOT have an acompletion attribute, so the pipeline
    uses the direct callable path in _call_llm.
    """

    def __init__(self, return_value: str = "") -> None:
        self.return_value = return_value
        self.call_count = 0
        self.last_messages: list[dict] | None = None
        self.side_effect: Any = None

    async def __call__(self, messages: list[dict]) -> str:
        self.call_count += 1
        self.last_messages = messages
        if self.side_effect is not None:
            if callable(self.side_effect):
                return await self.side_effect(messages)
            raise self.side_effect
        return self.return_value

    def assert_not_called(self) -> None:
        assert self.call_count == 0, f"Expected no calls, got {self.call_count}"

    def assert_called(self) -> None:
        assert self.call_count > 0, "Expected at least one call"


# ── TurnDetector Tests ───────────────────────────────────────────────────────


class TestTurnDetector:
    """Tests for TurnDetector pause classification."""

    def test_is_end_of_turn_after_1s_silence(self) -> None:
        """TurnDetector.is_end_of_turn returns True after 1s silence."""
        detector = TurnDetector()

        # Simulate speaker stopping 1.5s ago
        now = time.monotonic()
        detector._speakers["speaker_1"] = (False, now - 1.5)

        with patch.object(detector, "_get_time", return_value=now):
            assert detector.is_end_of_turn("speaker_1") is True

    def test_is_end_of_turn_returns_false_during_speech(self) -> None:
        """is_end_of_turn returns False when speaker is still talking."""
        detector = TurnDetector()
        now = time.monotonic()
        detector._speakers["speaker_1"] = (True, now)

        with patch.object(detector, "_get_time", return_value=now):
            assert detector.is_end_of_turn("speaker_1") is False

    def test_is_thinking_pause_between_1_and_2s(self) -> None:
        """TurnDetector.is_thinking_pause returns True between 1-2s silence."""
        detector = TurnDetector()
        now = time.monotonic()

        # 1.5s of silence -- between END_OF_TURN_MS (1s) and THINKING_PAUSE_MS (2s)
        detector._speakers["speaker_1"] = (False, now - 1.5)

        with patch.object(detector, "_get_time", return_value=now):
            assert detector.is_thinking_pause("speaker_1") is True

    def test_is_thinking_pause_false_after_2s(self) -> None:
        """is_thinking_pause returns False after 2s (no longer thinking)."""
        detector = TurnDetector()
        now = time.monotonic()

        # 2.5s of silence -- past THINKING_PAUSE_MS
        detector._speakers["speaker_1"] = (False, now - 2.5)

        with patch.object(detector, "_get_time", return_value=now):
            assert detector.is_thinking_pause("speaker_1") is False

    def test_get_active_speakers_tracks_active(self) -> None:
        """get_active_speakers returns speakers currently talking."""
        detector = TurnDetector()
        now = time.monotonic()

        # speaker_1 is currently speaking
        detector._speakers["speaker_1"] = (True, now)
        # speaker_2 stopped just 100ms ago (still active)
        detector._speakers["speaker_2"] = (False, now - 0.1)
        # speaker_3 stopped 2s ago (not active)
        detector._speakers["speaker_3"] = (False, now - 2.0)

        with patch.object(detector, "_get_time", return_value=now):
            active = detector.get_active_speakers()
            assert "speaker_1" in active
            assert "speaker_2" in active
            assert "speaker_3" not in active

    def test_update_speaker_activity(self) -> None:
        """update_speaker_activity records speaker state."""
        detector = TurnDetector()
        detector.update_speaker_activity("s1", True)
        assert "s1" in detector._speakers
        assert detector._speakers["s1"][0] is True

        detector.update_speaker_activity("s1", False)
        assert detector._speakers["s1"][0] is False


# ── SilenceChecker Tests ────────────────────────────────────────────────────


class TestSilenceChecker:
    """Tests for SilenceChecker strategic silence enforcement."""

    @pytest.fixture
    def turn_detector(self) -> TurnDetector:
        """Create a TurnDetector with mocked time."""
        return TurnDetector()

    @pytest.fixture
    def silence_checker(self, turn_detector: TurnDetector) -> SilenceChecker:
        """Create a SilenceChecker with participant roles."""
        roles = {
            "customer_1": ParticipantRole.EXTERNAL,
            "rep_1": ParticipantRole.INTERNAL,
            "agent": ParticipantRole.AGENT,
        }
        return SilenceChecker(turn_detector, roles)

    @pytest.mark.asyncio
    async def test_returns_false_when_internal_rep_speaking(
        self, silence_checker: SilenceChecker, turn_detector: TurnDetector
    ) -> None:
        """SilenceChecker returns False when internal rep is speaking."""
        now = time.monotonic()

        # Customer finished speaking 1.5s ago (end of turn)
        turn_detector._speakers["customer_1"] = (False, now - 1.5)
        # Internal rep is actively speaking
        turn_detector._speakers["rep_1"] = (True, now)

        with patch.object(turn_detector, "_get_time", return_value=now):
            result = await silence_checker.should_respond(
                transcript="What about pricing?",
                speaker_id="customer_1",
                meeting_context={},
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_during_thinking_pause(
        self, silence_checker: SilenceChecker, turn_detector: TurnDetector
    ) -> None:
        """SilenceChecker returns False during thinking pause (1-2s)."""
        now = time.monotonic()

        # Customer paused 1.5s ago (thinking pause range)
        turn_detector._speakers["customer_1"] = (False, now - 1.5)

        with patch.object(turn_detector, "_get_time", return_value=now):
            result = await silence_checker.should_respond(
                transcript="Let me think about that...",
                speaker_id="customer_1",
                meeting_context={},
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_valid_end_of_turn(
        self, silence_checker: SilenceChecker, turn_detector: TurnDetector
    ) -> None:
        """SilenceChecker returns True when all conditions pass."""
        now = time.monotonic()

        # Customer stopped 2.5s ago (past thinking pause -- definite end of turn)
        turn_detector._speakers["customer_1"] = (False, now - 2.5)
        # No active internal speakers
        turn_detector._speakers["rep_1"] = (False, now - 5.0)

        with patch.object(turn_detector, "_get_time", return_value=now):
            result = await silence_checker.should_respond(
                transcript="Tell me about your product.",
                speaker_id="customer_1",
                meeting_context={},
                confidence_score=0.9,
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_confidence_below_threshold(
        self, silence_checker: SilenceChecker, turn_detector: TurnDetector
    ) -> None:
        """SilenceChecker returns False when confidence_score < CONFIDENCE_THRESHOLD."""
        now = time.monotonic()

        # Customer done speaking, no internal speakers
        turn_detector._speakers["customer_1"] = (False, now - 2.5)
        turn_detector._speakers["rep_1"] = (False, now - 5.0)

        with patch.object(turn_detector, "_get_time", return_value=now):
            result = await silence_checker.should_respond(
                transcript="Hmm...",
                speaker_id="customer_1",
                meeting_context={},
                confidence_score=0.5,
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_confidence_above_threshold(
        self, silence_checker: SilenceChecker, turn_detector: TurnDetector
    ) -> None:
        """SilenceChecker returns True when confidence >= CONFIDENCE_THRESHOLD with other checks passing."""
        now = time.monotonic()

        turn_detector._speakers["customer_1"] = (False, now - 2.5)
        turn_detector._speakers["rep_1"] = (False, now - 5.0)

        with patch.object(turn_detector, "_get_time", return_value=now):
            result = await silence_checker.should_respond(
                transcript="What's the ROI?",
                speaker_id="customer_1",
                meeting_context={},
                confidence_score=CONFIDENCE_THRESHOLD,
            )
            assert result is True

    def test_update_and_get_participant_role(
        self, silence_checker: SilenceChecker
    ) -> None:
        """update_participant_role and get_participant_role work correctly."""
        # Default for unknown speaker
        assert silence_checker.get_participant_role("unknown") == ParticipantRole.EXTERNAL

        # Update and check
        silence_checker.update_participant_role("new_speaker", ParticipantRole.INTERNAL)
        assert silence_checker.get_participant_role("new_speaker") == ParticipantRole.INTERNAL


# ── RealtimePipeline Tests ──────────────────────────────────────────────────


class TestRealtimePipeline:
    """Tests for RealtimePipeline orchestration."""

    @pytest.fixture
    def mock_components(self) -> dict:
        """Create mock pipeline components.

        The LLM mock is a simple callable class (no acompletion attribute)
        so the pipeline uses the direct callable path in _call_llm.
        """
        stt = MagicMock()
        tts = MagicMock()
        avatar = AsyncMock()
        silence_checker = AsyncMock(spec=SilenceChecker)

        # Simple async callable LLM mock -- no acompletion attribute
        llm = MockLLM()

        meeting_context = {
            "briefing": "Test meeting briefing",
            "participants": "Alice (customer), Bob (rep)",
            "methodology": "QBS",
        }
        return {
            "stt": stt,
            "tts": tts,
            "avatar": avatar,
            "silence_checker": silence_checker,
            "llm": llm,
            "meeting_context": meeting_context,
        }

    @pytest.fixture
    def pipeline(self, mock_components: dict) -> RealtimePipeline:
        """Create pipeline with mock components."""
        return RealtimePipeline(
            stt_client=mock_components["stt"],
            tts_client=mock_components["tts"],
            avatar_client=mock_components["avatar"],
            silence_checker=mock_components["silence_checker"],
            llm_service=mock_components["llm"],
            meeting_context=mock_components["meeting_context"],
        )

    @pytest.mark.asyncio
    async def test_process_speech_turn_with_mock_llm(
        self, pipeline: RealtimePipeline, mock_components: dict
    ) -> None:
        """Pipeline processes speech turn and delivers to avatar."""
        mock_components["silence_checker"].should_respond = AsyncMock(return_value=True)
        mock_components["llm"].return_value = "[CONF:0.85] That's a great question about pricing."

        await pipeline.process_speech_turn("What about pricing?", "customer_1")

        # Avatar should have been called to speak
        mock_components["avatar"].speak.assert_called()
        # LLM should have been called
        mock_components["llm"].assert_called()

    @pytest.mark.asyncio
    async def test_respects_silence_checker_pre_llm(
        self, pipeline: RealtimePipeline, mock_components: dict
    ) -> None:
        """Pipeline skips response when pre-LLM silence check fails."""
        # First call (pre-LLM) returns False
        mock_components["silence_checker"].should_respond = AsyncMock(return_value=False)

        await pipeline.process_speech_turn("Hello", "customer_1")

        # LLM should NOT have been called (silence checker blocked it)
        mock_components["llm"].assert_not_called()
        # Avatar should NOT have been called
        mock_components["avatar"].speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_llm_timeout(
        self, pipeline: RealtimePipeline, mock_components: dict
    ) -> None:
        """Pipeline stays silent when LLM exceeds timeout."""
        mock_components["silence_checker"].should_respond = AsyncMock(return_value=True)

        # LLM takes too long -- set side_effect on the MockLLM
        async def slow_llm(messages: list) -> str:
            await asyncio.sleep(2.0)
            return "Late response"

        mock_components["llm"].side_effect = slow_llm

        await pipeline.process_speech_turn("Question?", "customer_1")

        # Avatar should NOT have been called (LLM timed out)
        mock_components["avatar"].speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_silence_token_handling(
        self, pipeline: RealtimePipeline, mock_components: dict
    ) -> None:
        """Pipeline treats SILENCE_TOKEN as confidence=0.0 and does not speak."""
        mock_components["silence_checker"].should_respond = AsyncMock(return_value=True)
        mock_components["llm"].return_value = SILENCE_TOKEN

        await pipeline.process_speech_turn("What do you think?", "customer_1")

        # Avatar should NOT have spoken (SILENCE_TOKEN)
        mock_components["avatar"].speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_llm_confidence_gate_blocks_low_confidence(
        self, pipeline: RealtimePipeline, mock_components: dict
    ) -> None:
        """Post-LLM confidence gate blocks low-confidence responses BEFORE TTS."""
        # Pre-LLM check passes, post-LLM check fails (low confidence)
        call_count = 0

        async def conditional_should_respond(*args, **kwargs) -> bool:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return True  # Pre-LLM check passes
            return False  # Post-LLM check fails (confidence below threshold)

        mock_components["silence_checker"].should_respond = AsyncMock(
            side_effect=conditional_should_respond
        )
        mock_components["llm"].return_value = "[CONF:0.3] Maybe something about pricing?"

        await pipeline.process_speech_turn("Tell me about pricing.", "customer_1")

        # Avatar should NOT have spoken (post-LLM confidence gate blocked)
        mock_components["avatar"].speak.assert_not_called()
        # LLM was called (pre-LLM check passed)
        mock_components["llm"].assert_called()

    @pytest.mark.asyncio
    async def test_parses_confidence_prefix(
        self, pipeline: RealtimePipeline
    ) -> None:
        """Pipeline correctly parses [CONF:X.XX] prefix from LLM response."""
        confidence, text = pipeline._parse_confidence("[CONF:0.85] Great question!")
        assert confidence == 0.85
        assert text == "Great question!"

    @pytest.mark.asyncio
    async def test_parses_silence_token_confidence(
        self, pipeline: RealtimePipeline
    ) -> None:
        """Pipeline returns 0.0 confidence for SILENCE_TOKEN."""
        confidence, text = pipeline._parse_confidence(SILENCE_TOKEN)
        assert confidence == 0.0
        assert text == SILENCE_TOKEN

    @pytest.mark.asyncio
    async def test_default_confidence_when_no_prefix(
        self, pipeline: RealtimePipeline
    ) -> None:
        """Pipeline defaults to 1.0 confidence when no prefix."""
        confidence, text = pipeline._parse_confidence("Just a plain response.")
        assert confidence == 1.0
        assert text == "Just a plain response."

    @pytest.mark.asyncio
    async def test_handle_stt_transcript_interim_accumulates(
        self, pipeline: RealtimePipeline, mock_components: dict
    ) -> None:
        """handle_stt_transcript accumulates interim results."""
        mock_components["silence_checker"].should_respond = AsyncMock(return_value=False)

        # Interim result -- should not trigger processing
        await pipeline.handle_stt_transcript("Hello wo", is_final=False, speaker_id="s1")
        mock_components["llm"].assert_not_called()

        # Final result -- triggers processing (silence_checker blocks before LLM)
        await pipeline.handle_stt_transcript("Hello world", is_final=True, speaker_id="s1")
        # silence_checker was called (even though it returned False)
        mock_components["silence_checker"].should_respond.assert_called()
        # LLM still not called because silence_checker returned False
        mock_components["llm"].assert_not_called()


# ── PipelineMetrics Tests ───────────────────────────────────────────────────


class TestPipelineMetrics:
    """Tests for PipelineMetrics computed properties."""

    def test_total_latency_ms(self) -> None:
        """total_latency_ms computes end-to-end latency."""
        metrics = PipelineMetrics(
            speech_end_time=100.0,
            audio_play_time=100.9,
        )
        assert abs(metrics.total_latency_ms - 900.0) < 1.0

    def test_stt_latency_ms(self) -> None:
        """stt_latency_ms computes STT processing time."""
        metrics = PipelineMetrics(
            speech_end_time=100.0,
            stt_final_time=100.3,
        )
        assert abs(metrics.stt_latency_ms - 300.0) < 1.0

    def test_llm_latency_ms(self) -> None:
        """llm_latency_ms computes LLM first token time."""
        metrics = PipelineMetrics(
            stt_final_time=100.3,
            llm_first_token_time=100.8,
        )
        assert abs(metrics.llm_latency_ms - 500.0) < 1.0

    def test_tts_latency_ms(self) -> None:
        """tts_latency_ms computes TTS first byte time."""
        metrics = PipelineMetrics(
            llm_first_token_time=100.8,
            tts_first_byte_time=100.9,
        )
        assert abs(metrics.tts_latency_ms - 100.0) < 1.0

    def test_zero_latency_when_timestamps_missing(self) -> None:
        """Returns 0.0 when timestamps are not set."""
        metrics = PipelineMetrics()
        assert metrics.total_latency_ms == 0.0
        assert metrics.stt_latency_ms == 0.0
        assert metrics.llm_latency_ms == 0.0
        assert metrics.tts_latency_ms == 0.0


# ── Sentence Boundary Tests ─────────────────────────────────────────────────


class TestSentenceBoundary:
    """Tests for _is_sentence_boundary helper."""

    def test_period_is_boundary(self) -> None:
        """Period is a sentence boundary."""
        assert RealtimePipeline._is_sentence_boundary("Hello.") is True

    def test_question_mark_is_boundary(self) -> None:
        """Question mark is a sentence boundary."""
        assert RealtimePipeline._is_sentence_boundary("What?") is True

    def test_exclamation_is_boundary(self) -> None:
        """Exclamation mark is a sentence boundary."""
        assert RealtimePipeline._is_sentence_boundary("Great!") is True

    def test_colon_is_boundary(self) -> None:
        """Colon is a sentence boundary."""
        assert RealtimePipeline._is_sentence_boundary("Here's the thing:") is True

    def test_semicolon_is_boundary(self) -> None:
        """Semicolon is a sentence boundary."""
        assert RealtimePipeline._is_sentence_boundary("First point;") is True

    def test_no_boundary_mid_sentence(self) -> None:
        """Non-punctuation ending is not a boundary."""
        assert RealtimePipeline._is_sentence_boundary("Hello world") is False

    def test_empty_string_not_boundary(self) -> None:
        """Empty string is not a boundary."""
        assert RealtimePipeline._is_sentence_boundary("") is False
