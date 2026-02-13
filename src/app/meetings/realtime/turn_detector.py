"""Turn detection for real-time meeting conversation.

Provides TurnDetector for tracking per-speaker silence duration and
distinguishing between thinking pauses (2-3s) and end-of-turn pauses (1s).

Per CONTEXT.md LOCKED decisions:
- Strict turn-taking: never interrupts
- Detect contemplation vs end-of-turn (don't rush customer processing time)
- Thinking pauses: 2-3 seconds (customer is contemplating)
- End-of-turn pauses: 1 second (customer is done speaking)
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Per CONTEXT.md: thinking pauses 2-3s, end-of-turn pauses 1s
THINKING_PAUSE_MS = 2000
END_OF_TURN_MS = 1000

# Speakers with less than this silence are considered "active" (currently talking)
ACTIVE_SPEAKER_THRESHOLD_MS = 300


class TurnDetector:
    """Tracks per-speaker silence duration for turn-taking decisions.

    Maintains a timestamp of the last speech activity per speaker
    and provides methods to classify current silence as thinking pause
    vs end-of-turn pause.

    Uses asyncio event loop time for consistent timestamps within
    the async pipeline.
    """

    def __init__(self) -> None:
        # speaker_id -> (is_speaking: bool, last_activity_time: float)
        self._speakers: dict[str, tuple[bool, float]] = {}

    def _get_time(self) -> float:
        """Get current event loop time in seconds.

        Uses asyncio.get_event_loop().time() for monotonic timestamps
        consistent within the async pipeline.

        Returns:
            Current time in seconds.
        """
        try:
            loop = asyncio.get_event_loop()
            return loop.time()
        except RuntimeError:
            # No event loop available -- fall back to monotonic time
            import time
            return time.monotonic()

    def update_speaker_activity(self, speaker_id: str, is_speaking: bool) -> None:
        """Track when a speaker starts or stops speaking.

        Args:
            speaker_id: Unique speaker identifier from diarization.
            is_speaking: True if speaker is currently producing speech.
        """
        now = self._get_time()
        self._speakers[speaker_id] = (is_speaking, now)
        logger.debug(
            "turn_detector.activity",
            speaker_id=speaker_id,
            is_speaking=is_speaking,
        )

    def get_silence_duration_ms(self, speaker_id: str) -> float:
        """Get milliseconds since speaker last spoke.

        Returns 0.0 if the speaker is currently speaking or unknown.

        Args:
            speaker_id: Unique speaker identifier.

        Returns:
            Silence duration in milliseconds.
        """
        if speaker_id not in self._speakers:
            return 0.0

        is_speaking, last_activity = self._speakers[speaker_id]
        if is_speaking:
            return 0.0

        now = self._get_time()
        return (now - last_activity) * 1000.0

    def is_end_of_turn(self, speaker_id: str) -> bool:
        """Check if speaker has been silent long enough to indicate end of turn.

        Returns True if silence >= END_OF_TURN_MS (1s).

        Args:
            speaker_id: Unique speaker identifier.

        Returns:
            True if silence indicates end of turn.
        """
        silence_ms = self.get_silence_duration_ms(speaker_id)
        return silence_ms >= END_OF_TURN_MS

    def is_thinking_pause(self, speaker_id: str) -> bool:
        """Check if speaker is in a thinking pause (still contemplating).

        Returns True if silence is between END_OF_TURN_MS and
        THINKING_PAUSE_MS (1-2s). This means the customer may still
        be thinking -- do not rush them.

        Args:
            speaker_id: Unique speaker identifier.

        Returns:
            True if silence indicates thinking pause.
        """
        silence_ms = self.get_silence_duration_ms(speaker_id)
        return END_OF_TURN_MS <= silence_ms < THINKING_PAUSE_MS

    def get_active_speakers(self) -> list[str]:
        """Get speakers currently talking (silence < 300ms).

        Returns:
            List of speaker IDs with recent speech activity.
        """
        active: list[str] = []
        for speaker_id, (is_speaking, _last_activity) in self._speakers.items():
            if is_speaking:
                active.append(speaker_id)
            else:
                silence_ms = self.get_silence_duration_ms(speaker_id)
                if silence_ms < ACTIVE_SPEAKER_THRESHOLD_MS:
                    active.append(speaker_id)
        return active
