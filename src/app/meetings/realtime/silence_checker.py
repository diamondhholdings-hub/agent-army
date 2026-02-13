"""Strategic silence enforcement for real-time meeting responses.

Provides SilenceChecker implementing ALL THREE strategic silence rules
from CONTEXT.md. These rules are checked BEFORE every response:

1. Customer not still thinking: check turn_detector.is_end_of_turn()
   - If is_thinking_pause: return False (don't rush customer)
2. Internal rep not speaking: check active speakers against participant roles
   - If any active speaker has role INTERNAL: return False (never talk over salesperson)
3. Confidence above threshold: if confidence_score < CONFIDENCE_THRESHOLD: return False
   - Per CONTEXT.md: "Better to stay silent than to speak poorly"

Per CONTEXT.md LOCKED decision: ALL THREE checks MUST pass before speaking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from src.app.meetings.schemas import ParticipantRole

if TYPE_CHECKING:
    from src.app.meetings.realtime.turn_detector import TurnDetector

logger = structlog.get_logger(__name__)

# Confidence threshold -- only speak when highly confident
# Per CONTEXT.md: "Confidence below threshold" prevents speaking
CONFIDENCE_THRESHOLD = 0.7


class SilenceChecker:
    """Enforces strategic silence rules before every agent response.

    Implements the three-gate check from CONTEXT.md. Called twice
    in the pipeline flow:
    1. Pre-LLM call (checks rules a + b only; confidence defaults to 1.0)
    2. Post-LLM/pre-TTS call (checks all three with actual confidence)

    Args:
        turn_detector: TurnDetector for pause classification.
        participant_roles: Mapping of speaker_id -> ParticipantRole.
    """

    def __init__(
        self,
        turn_detector: TurnDetector,
        participant_roles: dict[str, ParticipantRole] | None = None,
    ) -> None:
        self._turn_detector = turn_detector
        self._participant_roles: dict[str, ParticipantRole] = participant_roles or {}

    async def should_respond(
        self,
        transcript: str,
        speaker_id: str,
        meeting_context: dict,
        confidence_score: float = 1.0,
    ) -> bool:
        """Check ALL THREE strategic silence rules before responding.

        Returns True ONLY if all conditions pass:
        a. Customer is done speaking (end of turn, not thinking pause)
        b. No internal rep is currently speaking
        c. Confidence is above threshold

        Args:
            transcript: Current transcript text.
            speaker_id: Speaker who just finished talking.
            meeting_context: Current meeting context dict.
            confidence_score: LLM confidence (0.0-1.0). Defaults to 1.0
                for pre-LLM check (only rules a+b apply).

        Returns:
            True if agent should speak, False if agent should stay silent.
        """
        # Rule A: Customer not still thinking
        # Check if speaker is in a thinking pause (1-2s silence)
        if self._turn_detector.is_thinking_pause(speaker_id):
            logger.info(
                "silence_checker.thinking_pause",
                speaker_id=speaker_id,
                silence_ms=self._turn_detector.get_silence_duration_ms(speaker_id),
            )
            return False

        # Also check: has the speaker actually finished their turn?
        if not self._turn_detector.is_end_of_turn(speaker_id):
            # Speaker hasn't been silent long enough -- still speaking
            logger.debug(
                "silence_checker.not_end_of_turn",
                speaker_id=speaker_id,
                silence_ms=self._turn_detector.get_silence_duration_ms(speaker_id),
            )
            return False

        # Rule B: Internal rep not speaking
        active_speakers = self._turn_detector.get_active_speakers()
        for active_id in active_speakers:
            role = self.get_participant_role(active_id)
            if role == ParticipantRole.INTERNAL:
                logger.info(
                    "silence_checker.internal_rep_speaking",
                    active_speaker_id=active_id,
                    role=role.value,
                )
                return False

        # Rule C: Confidence above threshold
        if confidence_score < CONFIDENCE_THRESHOLD:
            logger.info(
                "silence_checker.low_confidence",
                confidence_score=confidence_score,
                threshold=CONFIDENCE_THRESHOLD,
            )
            return False

        logger.debug(
            "silence_checker.approved",
            speaker_id=speaker_id,
            confidence_score=confidence_score,
        )
        return True

    def update_participant_role(
        self, speaker_id: str, role: ParticipantRole
    ) -> None:
        """Update the role mapping for a speaker.

        Args:
            speaker_id: Unique speaker identifier.
            role: ParticipantRole (INTERNAL, EXTERNAL, AGENT).
        """
        self._participant_roles[speaker_id] = role
        logger.debug(
            "silence_checker.role_updated",
            speaker_id=speaker_id,
            role=role.value,
        )

    def get_participant_role(self, speaker_id: str) -> ParticipantRole:
        """Get the role of a participant, defaulting to EXTERNAL if unknown.

        Args:
            speaker_id: Unique speaker identifier.

        Returns:
            ParticipantRole for the speaker.
        """
        return self._participant_roles.get(speaker_id, ParticipantRole.EXTERNAL)
