"""HeyGen avatar session management via REST API.

Provides HeyGenAvatar for managing animated avatar sessions with
lip-sync driven by the streaming.task API. Uses httpx.AsyncClient
for HeyGen REST API calls.

Per CONTEXT.md LOCKED decisions:
- Fully animated with natural movements (lip-sync, head nods, eye contact)
- Context-aware idle reactions (nod, interested, thinking)
- Customizable per tenant (avatar_id parameter)
- Session rotation support for duration limits (RESEARCH Pitfall 4)
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class HeyGenAvatar:
    """Manages HeyGen avatar sessions with lip-sync via streaming.task API.

    Handles the full avatar session lifecycle: creation with LiveKit
    connection details, streaming start, text-to-speech with lip-sync,
    idle reactions, session stop, and session rotation for duration limits.

    Args:
        api_key: HeyGen API key.
        avatar_id: HeyGen avatar identifier (tenant-specific).
        voice_id: Optional HeyGen voice ID. If None, uses avatar default.
    """

    BASE_URL = "https://api.heygen.com/v1"
    TIMEOUT = 30.0

    def __init__(
        self,
        api_key: str,
        avatar_id: str,
        voice_id: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._avatar_id = avatar_id
        self._voice_id = voice_id
        self._session_id: str | None = None
        self._session_info: dict | None = None
        self._is_active = False

    def _headers(self) -> dict[str, str]:
        """Build request headers with API key."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    async def start_session(self) -> dict:
        """Create a new HeyGen streaming session.

        POST streaming.new with v2 protocol, high quality, and
        configured avatar/voice. Returns session data including
        session_id, LiveKit url, and access_token.

        Returns:
            Session data dict with session_id, url, access_token.
        """
        payload: dict[str, Any] = {
            "version": "v2",
            "avatar_name": self._avatar_id,
            "quality": "high",
            "video_encoding": "H264",
        }

        if self._voice_id:
            payload["voice"] = {
                "voice_id": self._voice_id,
                "rate": 1.0,
            }

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            response = await client.post(
                f"{self.BASE_URL}/streaming.new",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        session_data = data.get("data", data)
        self._session_id = session_data.get("session_id")
        self._session_info = {
            "session_id": self._session_id,
            "url": session_data.get("url"),
            "access_token": session_data.get("access_token"),
        }

        logger.info(
            "avatar.session_created",
            session_id=self._session_id,
            avatar_id=self._avatar_id,
        )
        return self._session_info

    async def start_streaming(self) -> None:
        """Start the avatar streaming session.

        POST streaming.start marks the session as active and begins
        rendering the avatar.
        """
        if not self._session_id:
            raise RuntimeError("No active session. Call start_session() first.")

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            response = await client.post(
                f"{self.BASE_URL}/streaming.start",
                headers=self._headers(),
                json={"session_id": self._session_id},
            )
            response.raise_for_status()

        self._is_active = True
        logger.info("avatar.streaming_started", session_id=self._session_id)

    async def speak(self, text: str) -> None:
        """Make the avatar speak with lip-sync.

        POST streaming.task with task_type "repeat" for exact text
        reproduction. The "repeat" mode ensures the avatar speaks the
        exact text provided (we handle LLM reasoning ourselves).

        Per CONTEXT.md: fully animated with natural movements, lip-sync critical.

        Args:
            text: Text for the avatar to speak.
        """
        if not self._session_id:
            raise RuntimeError("No active session. Call start_session() first.")

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            response = await client.post(
                f"{self.BASE_URL}/streaming.task",
                headers=self._headers(),
                json={
                    "session_id": self._session_id,
                    "text": text,
                    "task_type": "repeat",
                },
            )
            response.raise_for_status()

        logger.debug(
            "avatar.speak",
            session_id=self._session_id,
            text_length=len(text),
        )

    async def send_idle_reaction(self, reaction: str) -> None:
        """Send context-aware idle reaction to the avatar.

        POST streaming.task with task_type "talk" for context-aware
        idle behavior. Supported reactions map to avatar behaviors.

        Per CONTEXT.md: context-aware reactions even when not speaking.

        Args:
            reaction: Reaction type -- "nod", "interested", "thinking".
        """
        if not self._session_id:
            raise RuntimeError("No active session. Call start_session() first.")

        # Map reaction types to avatar-appropriate text cues
        reaction_cues = {
            "nod": "I see.",
            "interested": "That's interesting.",
            "thinking": "Let me think about that.",
        }
        cue_text = reaction_cues.get(reaction, "I see.")

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            response = await client.post(
                f"{self.BASE_URL}/streaming.task",
                headers=self._headers(),
                json={
                    "session_id": self._session_id,
                    "text": cue_text,
                    "task_type": "talk",
                },
            )
            response.raise_for_status()

        logger.debug(
            "avatar.idle_reaction",
            session_id=self._session_id,
            reaction=reaction,
        )

    async def stop_session(self) -> None:
        """Stop the avatar streaming session and clean up resources.

        POST streaming.stop with the current session_id.
        """
        if not self._session_id:
            logger.debug("avatar.stop_no_session")
            return

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.post(
                    f"{self.BASE_URL}/streaming.stop",
                    headers=self._headers(),
                    json={"session_id": self._session_id},
                )
                response.raise_for_status()
        except Exception:
            logger.warning(
                "avatar.stop_error",
                session_id=self._session_id,
                exc_info=True,
            )
        finally:
            logger.info("avatar.session_stopped", session_id=self._session_id)
            self._session_id = None
            self._session_info = None
            self._is_active = False

    def get_session_info(self) -> dict | None:
        """Return current session info (session_id, LiveKit url, access_token).

        Used by Output Media webapp to connect to the LiveKit room
        for avatar video rendering.

        Returns:
            Session info dict if active, None otherwise.
        """
        return self._session_info

    async def rotate_session(self) -> dict:
        """Create a new session for seamless rotation.

        Per RESEARCH Pitfall 4: handle session duration limits by
        creating a new session before the current one expires.
        The caller is responsible for transitioning from old to new session.

        Returns:
            New session info dict with session_id, url, access_token.
        """
        old_session_id = self._session_id
        logger.info(
            "avatar.rotating_session",
            old_session_id=old_session_id,
        )

        # Stop the old session
        await self.stop_session()

        # Start a new one
        new_session = await self.start_session()
        await self.start_streaming()

        logger.info(
            "avatar.session_rotated",
            old_session_id=old_session_id,
            new_session_id=self._session_id,
        )
        return new_session
