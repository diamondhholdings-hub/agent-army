"""Real-time meeting response pipeline: STT -> LLM -> TTS -> Avatar.

Provides RealtimePipeline orchestrating the end-to-end flow from speech
recognition through LLM reasoning to avatar-delivered speech, with
sub-1s latency target.

Per CONTEXT.md LOCKED decisions:
- Active participant posture (speaks proactively)
- Strict turn-taking (never interrupts)
- Under 1 second latency target (STT + LLM + TTS)
- Strategic silence: all three checks must pass before speaking

Per RESEARCH.md:
- Budget: 300ms STT + 500ms LLM + 100ms TTS = 900ms target
- Use model='fast' (Haiku-class) for real-time responses
- Do NOT send full history (sliding window of MAX_CONTEXT_TURNS)
- Monitor latency degradation and switch to shorter prompts if needed

Pipeline flow:
1. Receive final transcript from STT
2. Pre-LLM silence check (turn-taking + internal rep rules)
3. Build LLM context with sliding window
4. Stream LLM response with timeout (parse [CONF:X.XX] prefix)
5. Post-LLM confidence gate (BEFORE TTS/avatar delivery)
6. Buffer LLM tokens to sentence boundaries
7. Send complete sentences to avatar.speak() for lip-synced delivery
8. Record metrics at each stage
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.app.meetings.realtime.avatar import HeyGenAvatar
    from src.app.meetings.realtime.silence_checker import SilenceChecker
    from src.app.meetings.realtime.stt import DeepgramSTT
    from src.app.meetings.realtime.tts import ElevenLabsTTS

logger = structlog.get_logger(__name__)

# Latency budget per RESEARCH.md: 300ms STT + 500ms LLM + 100ms TTS
LATENCY_BUDGET_MS = 1000
LLM_TIMEOUT_MS = 500
MAX_CONTEXT_TURNS = 10

# Confidence prefix pattern: [CONF:X.XX]
CONFIDENCE_PREFIX_RE = re.compile(r"^\[CONF:(\d+\.\d{1,2})\]\s*")

# Token indicating LLM chooses silence
SILENCE_TOKEN = "[SILENCE]"

# Consecutive latency degradations before switching to shorter prompts
DEGRADATION_THRESHOLD = 3


@dataclass
class PipelineMetrics:
    """Timing metrics for real-time pipeline stages.

    Records timestamps at each stage and provides computed properties
    for per-stage and total latency in milliseconds.

    Per RESEARCH.md: budget 300ms STT + 500ms LLM + 100ms TTS = 900ms target.
    """

    speech_end_time: float = 0.0
    stt_final_time: float = 0.0
    llm_first_token_time: float = 0.0
    tts_first_byte_time: float = 0.0
    audio_play_time: float = 0.0

    @property
    def total_latency_ms(self) -> float:
        """Total end-to-end latency from speech end to audio play."""
        if self.speech_end_time and self.audio_play_time:
            return (self.audio_play_time - self.speech_end_time) * 1000.0
        return 0.0

    @property
    def stt_latency_ms(self) -> float:
        """STT processing latency."""
        if self.speech_end_time and self.stt_final_time:
            return (self.stt_final_time - self.speech_end_time) * 1000.0
        return 0.0

    @property
    def llm_latency_ms(self) -> float:
        """LLM first token latency."""
        if self.stt_final_time and self.llm_first_token_time:
            return (self.llm_first_token_time - self.stt_final_time) * 1000.0
        return 0.0

    @property
    def tts_latency_ms(self) -> float:
        """TTS first byte latency."""
        if self.llm_first_token_time and self.tts_first_byte_time:
            return (self.tts_first_byte_time - self.llm_first_token_time) * 1000.0
        return 0.0


class RealtimePipeline:
    """Orchestrates the real-time STT -> LLM -> TTS -> Avatar pipeline.

    Coordinates all components for sub-1s latency meeting responses:
    - Streaming STT for transcript capture
    - LLM reasoning with sliding window context
    - Strategic silence enforcement (pre-LLM and post-LLM gates)
    - Sentence-boundary buffering for TTS quality
    - Avatar lip-synced delivery

    Args:
        stt_client: DeepgramSTT for streaming transcription.
        tts_client: ElevenLabsTTS for text-to-speech.
        avatar_client: HeyGenAvatar for lip-synced delivery.
        silence_checker: SilenceChecker enforcing strategic silence rules.
        llm_service: LLM service with async streaming support.
        meeting_context: Meeting briefing and participant context dict.
    """

    def __init__(
        self,
        stt_client: DeepgramSTT,
        tts_client: ElevenLabsTTS,
        avatar_client: HeyGenAvatar,
        silence_checker: SilenceChecker,
        llm_service: Any,
        meeting_context: dict,
    ) -> None:
        self._stt = stt_client
        self._tts = tts_client
        self._avatar = avatar_client
        self._silence_checker = silence_checker
        self._llm = llm_service
        self._meeting_context = meeting_context

        # Transcript history for sliding window
        self._transcript_history: list[dict[str, str]] = []

        # Interim transcript accumulator
        self._interim_buffer: str = ""

        # Latest metrics snapshot
        self._metrics = PipelineMetrics()

        # Latency degradation tracking
        self._consecutive_degradations = 0
        self._use_short_prompts = False

    def _get_time(self) -> float:
        """Get current event loop time for latency tracking."""
        try:
            loop = asyncio.get_event_loop()
            return loop.time()
        except RuntimeError:
            import time
            return time.monotonic()

    async def process_speech_turn(
        self, final_transcript: str, speaker_id: str
    ) -> None:
        """Process a completed speech turn through the full pipeline.

        Pipeline stages:
        1. Record speech_end_time
        2. Pre-LLM silence check (turn-taking + internal rep)
        3. Build LLM context with sliding window
        4. Stream LLM response with timeout
        5. Parse [CONF:X.XX] prefix and extract confidence
        6. Post-LLM confidence gate (BEFORE TTS/avatar)
        7. Buffer to sentence boundaries
        8. Send sentences to avatar.speak()
        9. Record metrics

        Args:
            final_transcript: Final transcript text from STT.
            speaker_id: Speaker who just finished talking.
        """
        metrics = PipelineMetrics()
        metrics.speech_end_time = self._get_time()
        metrics.stt_final_time = self._get_time()

        # Step 2: Pre-LLM silence check (confidence defaults to 1.0)
        should_respond = await self._silence_checker.should_respond(
            transcript=final_transcript,
            speaker_id=speaker_id,
            meeting_context=self._meeting_context,
        )
        if not should_respond:
            logger.info(
                "pipeline.silence_pre_llm",
                speaker_id=speaker_id,
                transcript_len=len(final_transcript),
            )
            return

        # Step 3: Build LLM context
        context_messages = self._build_llm_context(final_transcript)

        # Step 4: Stream LLM response with timeout
        llm_response = ""
        try:
            llm_response = await asyncio.wait_for(
                self._call_llm(context_messages, metrics),
                timeout=LLM_TIMEOUT_MS / 1000.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "pipeline.llm_timeout",
                timeout_ms=LLM_TIMEOUT_MS,
                speaker_id=speaker_id,
            )
            return

        if not llm_response:
            return

        # Step 5: Parse confidence prefix
        confidence, clean_text = self._parse_confidence(llm_response)

        # Handle SILENCE_TOKEN
        if clean_text.strip() == SILENCE_TOKEN or not clean_text.strip():
            logger.info(
                "pipeline.llm_silence_token",
                speaker_id=speaker_id,
            )
            return

        # Step 6: Post-LLM confidence gate (BEFORE TTS/avatar)
        should_speak = await self._silence_checker.should_respond(
            transcript=final_transcript,
            speaker_id=speaker_id,
            meeting_context=self._meeting_context,
            confidence_score=confidence,
        )
        if not should_speak:
            logger.info(
                "pipeline.low_confidence_silence",
                confidence=confidence,
                speaker_id=speaker_id,
            )
            return

        # Step 7-8: Buffer to sentence boundaries and send to avatar
        await self._deliver_to_avatar(clean_text, metrics)

        # Step 9: Record metrics
        self._metrics = metrics
        self._track_latency(metrics)

        # Add to transcript history
        self._transcript_history.append({
            "role": "user",
            "content": f"[{speaker_id}]: {final_transcript}",
        })
        self._transcript_history.append({
            "role": "assistant",
            "content": clean_text,
        })

        # Trim history to sliding window
        if len(self._transcript_history) > MAX_CONTEXT_TURNS * 2:
            self._transcript_history = self._transcript_history[-(MAX_CONTEXT_TURNS * 2):]

    async def handle_stt_transcript(
        self, transcript: str, is_final: bool, speaker_id: str
    ) -> None:
        """Handle STT transcript events (interim and final).

        Accumulates interim results. On is_final=True, triggers
        process_speech_turn with the accumulated text.

        Args:
            transcript: Transcript text from STT.
            is_final: True if this is a final (not interim) result.
            speaker_id: Speaker identifier from diarization.
        """
        if not is_final:
            self._interim_buffer = transcript
            return

        # Final result -- combine with any interim and process
        final_text = transcript if transcript else self._interim_buffer
        self._interim_buffer = ""

        if final_text.strip():
            await self.process_speech_turn(final_text, speaker_id)

    async def _call_llm(
        self, messages: list[dict[str, str]], metrics: PipelineMetrics
    ) -> str:
        """Call LLM service with streaming and record timing.

        Uses model='fast' (Haiku-class) for real-time responses per
        RESEARCH.md recommendation.

        Args:
            messages: Chat messages for LLM.
            metrics: PipelineMetrics to record timing.

        Returns:
            Full LLM response text.
        """
        response_text = ""
        first_token = True

        try:
            # Use the llm_service to get a response
            # Expected interface: async method that returns response text
            if hasattr(self._llm, "acompletion"):
                result = await self._llm.acompletion(
                    model="fast",
                    messages=messages,
                    stream=False,
                )
                if first_token:
                    metrics.llm_first_token_time = self._get_time()
                    first_token = False

                # Extract text from result
                if hasattr(result, "choices") and result.choices:
                    response_text = result.choices[0].message.content or ""
                elif isinstance(result, str):
                    response_text = result
                elif isinstance(result, dict):
                    response_text = result.get("content", result.get("text", ""))
            else:
                # Direct callable that returns text
                response_text = await self._llm(messages)
                if first_token:
                    metrics.llm_first_token_time = self._get_time()

        except Exception:
            logger.warning("pipeline.llm_error", exc_info=True)
            return ""

        return response_text

    async def _deliver_to_avatar(
        self, text: str, metrics: PipelineMetrics
    ) -> None:
        """Buffer text to sentence boundaries and deliver to avatar.

        Sends each complete sentence to avatar.speak() for
        lip-synced delivery.

        Args:
            text: Clean response text (confidence prefix stripped).
            metrics: PipelineMetrics to record timing.
        """
        metrics.tts_first_byte_time = self._get_time()

        # Split into sentences at boundaries
        sentences = self._split_sentences(text)

        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                try:
                    await self._avatar.speak(sentence)
                except Exception:
                    logger.warning(
                        "pipeline.avatar_speak_error",
                        sentence_len=len(sentence),
                        exc_info=True,
                    )

        metrics.audio_play_time = self._get_time()

        logger.info(
            "pipeline.delivered",
            total_latency_ms=metrics.total_latency_ms,
            stt_ms=metrics.stt_latency_ms,
            llm_ms=metrics.llm_latency_ms,
            tts_ms=metrics.tts_latency_ms,
            sentences=len(sentences),
        )

    def _split_sentences(self, text: str) -> list[str]:
        """Split text at sentence boundaries.

        Splits on '.', '!', '?', ':', ';' followed by a space or end of string.

        Args:
            text: Text to split.

        Returns:
            List of sentence strings.
        """
        # Split at sentence-ending punctuation followed by space or end
        parts = re.split(r'(?<=[.!?:;])\s+', text)
        return [p for p in parts if p.strip()]

    @staticmethod
    def _is_sentence_boundary(text: str) -> bool:
        """Check if text ends with sentence-ending punctuation.

        Returns True if text ends with '.', '!', '?', ':', ';'.

        Args:
            text: Text to check.

        Returns:
            True if text ends at a sentence boundary.
        """
        if not text:
            return False
        return text.rstrip()[-1] in ".!?:;"

    def _parse_confidence(self, text: str) -> tuple[float, str]:
        """Parse [CONF:X.XX] prefix from LLM response.

        If the LLM response starts with [CONF:X.XX], extracts the
        confidence value and returns the clean text. If no prefix
        found, defaults to 1.0 confidence.

        If the response is [SILENCE], returns confidence 0.0.

        Args:
            text: Raw LLM response text.

        Returns:
            Tuple of (confidence_score, clean_text).
        """
        stripped = text.strip()

        # Check for SILENCE_TOKEN
        if stripped == SILENCE_TOKEN:
            return 0.0, SILENCE_TOKEN

        # Parse [CONF:X.XX] prefix
        match = CONFIDENCE_PREFIX_RE.match(stripped)
        if match:
            confidence = float(match.group(1))
            clean_text = stripped[match.end():]
            return min(confidence, 1.0), clean_text

        # No prefix -- default confidence
        return 1.0, stripped

    def _build_llm_context(self, current_transcript: str) -> list[dict[str, str]]:
        """Build LLM context with system prompt and sliding window.

        System message includes meeting briefing, participant info,
        QBS methodology hints, and instructions for confidence prefix.

        Per RESEARCH.md anti-pattern: do NOT send full history.
        Uses sliding window of last MAX_CONTEXT_TURNS.

        Args:
            current_transcript: Current speech turn text.

        Returns:
            List of chat messages for LLM.
        """
        # Build system prompt
        briefing = self._meeting_context.get("briefing", "")
        participants = self._meeting_context.get("participants", "")
        methodology = self._meeting_context.get("methodology", "QBS (Question Based Selling)")

        prompt_style = "concise" if self._use_short_prompts else "detailed"

        if self._use_short_prompts:
            system_content = (
                f"You are an active sales meeting participant. "
                f"Meeting context: {briefing[:200]}\n"
                f"Prefix every response with [CONF:X.XX] where X.XX is your confidence. "
                f"If confidence is very low, respond with [SILENCE]."
            )
        else:
            system_content = (
                f"You are an active sales meeting participant using {methodology} methodology. "
                f"Your role is to contribute naturally like a human salesperson -- ask questions, "
                f"make statements, and guide the conversation when appropriate.\n\n"
                f"Meeting briefing:\n{briefing}\n\n"
                f"Participants:\n{participants}\n\n"
                f"Guidelines:\n"
                f"- Be concise and natural (meeting speech, not written text)\n"
                f"- Focus on understanding customer pain points\n"
                f"- Ask clarifying questions when appropriate\n"
                f"- Provide value through insights and relevant information\n\n"
                f"Prefix every response with [CONF:X.XX] where X.XX is your confidence "
                f"(0.00-1.00) in this response's quality and relevance. "
                f"If confidence is very low, respond with [SILENCE] instead of speaking."
            )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content},
        ]

        # Add sliding window of transcript history
        window = self._transcript_history[-(MAX_CONTEXT_TURNS * 2):]
        messages.extend(window)

        # Add current turn as user message
        messages.append({
            "role": "user",
            "content": current_transcript,
        })

        logger.debug(
            "pipeline.llm_context",
            prompt_style=prompt_style,
            history_turns=len(window),
            total_messages=len(messages),
        )

        return messages

    def _track_latency(self, metrics: PipelineMetrics) -> None:
        """Track latency and handle degradation.

        Per RESEARCH Pitfall 1: If total_latency_ms > LATENCY_BUDGET_MS,
        log warning. If degraded 3+ times consecutively, switch to
        shorter prompts.

        Args:
            metrics: Pipeline metrics with timing data.
        """
        total = metrics.total_latency_ms
        if total > LATENCY_BUDGET_MS:
            self._consecutive_degradations += 1
            logger.warning(
                "pipeline.latency_exceeded",
                total_latency_ms=total,
                budget_ms=LATENCY_BUDGET_MS,
                consecutive=self._consecutive_degradations,
            )

            if self._consecutive_degradations >= DEGRADATION_THRESHOLD:
                self._use_short_prompts = True
                logger.warning(
                    "pipeline.switching_to_short_prompts",
                    consecutive=self._consecutive_degradations,
                )
        else:
            # Reset on good latency
            if self._consecutive_degradations > 0:
                self._consecutive_degradations = 0
                self._use_short_prompts = False

    def get_metrics(self) -> PipelineMetrics:
        """Return the latest pipeline metrics snapshot.

        Returns:
            PipelineMetrics with timing data from last response.
        """
        return self._metrics
