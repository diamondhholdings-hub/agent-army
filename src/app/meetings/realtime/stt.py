"""Deepgram streaming STT with endpointing and VAD.

Provides DeepgramSTT for real-time speech-to-text transcription using
the Deepgram Nova-3 model with WebSocket streaming. Configured per
RESEARCH.md recommendations:
- 300ms endpointing for fast-paced conversation
- 1000ms utterance_end for clear turn detection
- VAD events enabled for speech activity tracking
- Speaker diarization for multi-participant meetings
- 16kHz PCM linear16 input matching Recall.ai audio format
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Lazy import to avoid hard dependency at module level
_deepgram_imported = False
_DeepgramClient = None
_LiveOptions = None
_LiveTranscriptionEvents = None


def _ensure_deepgram() -> None:
    """Lazy import of deepgram SDK."""
    global _deepgram_imported, _DeepgramClient, _LiveOptions, _LiveTranscriptionEvents
    if _deepgram_imported:
        return
    try:
        from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
        _DeepgramClient = DeepgramClient
        _LiveOptions = LiveOptions
        _LiveTranscriptionEvents = LiveTranscriptionEvents
        _deepgram_imported = True
    except ImportError:
        raise ImportError(
            "deepgram-sdk is required for DeepgramSTT. "
            "Install with: pip install deepgram-sdk>=3.7.0"
        )


class DeepgramSTT:
    """Streaming speech-to-text with Deepgram Nova-3.

    Establishes a WebSocket connection to Deepgram for real-time
    transcription with configurable endpointing for turn detection.

    Args:
        api_key: Deepgram API key.
    """

    # Nova-3: best accuracy + streaming latency (~250ms)
    MODEL = "nova-3"
    LANGUAGE = "en-US"

    # Endpointing config per RESEARCH.md
    ENDPOINTING_MS = 300       # 300ms pause = end of utterance
    UTTERANCE_END_MS = "1000"  # 1s silence = utterance end event

    # Audio format matching Recall.ai output
    ENCODING = "linear16"
    CHANNELS = 1
    SAMPLE_RATE = 16000

    def __init__(self, api_key: str) -> None:
        _ensure_deepgram()
        self._client = _DeepgramClient(api_key)
        self._connection: Any = None
        self._on_transcript: Callable | None = None
        self._on_utterance_end: Callable | None = None

    async def connect(
        self,
        on_transcript: Callable,
        on_utterance_end: Callable,
    ) -> None:
        """Establish WebSocket connection with LiveOptions.

        Registers event handlers for Transcript and UtteranceEnd events.

        Args:
            on_transcript: Callback(transcript: str, is_final: bool, speaker_id: int | None).
            on_utterance_end: Callback() for utterance end detection.
        """
        self._on_transcript = on_transcript
        self._on_utterance_end = on_utterance_end

        self._connection = self._client.listen.websocket.v("1")

        self._connection.on(
            _LiveTranscriptionEvents.Transcript,
            self._handle_transcript,
        )
        self._connection.on(
            _LiveTranscriptionEvents.UtteranceEnd,
            self._handle_utterance_end,
        )

        options = _LiveOptions(
            model=self.MODEL,
            language=self.LANGUAGE,
            smart_format=True,
            interim_results=True,
            endpointing=self.ENDPOINTING_MS,
            utterance_end_ms=self.UTTERANCE_END_MS,
            vad_events=True,
            diarize=True,
            encoding=self.ENCODING,
            channels=self.CHANNELS,
            sample_rate=self.SAMPLE_RATE,
        )

        self._connection.start(options)
        logger.info(
            "stt.connected",
            model=self.MODEL,
            endpointing_ms=self.ENDPOINTING_MS,
        )

    def send_audio(self, audio_bytes: bytes) -> None:
        """Send raw audio bytes to Deepgram WebSocket.

        Audio must be linear16 PCM at 16kHz mono.

        Args:
            audio_bytes: Raw PCM audio data.
        """
        if self._connection:
            self._connection.send(audio_bytes)

    def _handle_transcript(self, result: Any, **kwargs: Any) -> None:
        """Handle interim and final transcript results.

        Extracts transcript text, is_final flag, and speaker ID from
        diarization. Calls on_transcript callback if text is non-empty.

        Args:
            result: Deepgram transcript result object.
        """
        try:
            channel = result.channel
            alternatives = channel.alternatives
            if not alternatives:
                return

            transcript = alternatives[0].transcript
            is_final = result.is_final

            # Extract speaker ID from diarization if available
            speaker_id = None
            words = alternatives[0].words if hasattr(alternatives[0], "words") else []
            if words:
                speaker_id = getattr(words[0], "speaker", None)

            if transcript and self._on_transcript:
                self._on_transcript(transcript, is_final, speaker_id)

        except Exception:
            logger.warning("stt.transcript_parse_error", exc_info=True)

    def _handle_utterance_end(self, result: Any, **kwargs: Any) -> None:
        """Handle utterance end (speaker stopped talking).

        Calls on_utterance_end callback to signal turn completion.

        Args:
            result: Deepgram utterance end event.
        """
        if self._on_utterance_end:
            self._on_utterance_end()

    async def close(self) -> None:
        """Gracefully close WebSocket connection."""
        if self._connection:
            try:
                self._connection.finish()
                logger.info("stt.disconnected")
            except Exception:
                logger.warning("stt.close_error", exc_info=True)
            finally:
                self._connection = None
