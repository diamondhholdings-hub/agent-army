"""Async HTTP client wrapper for Recall.ai REST API.

Provides RecallClient with retry logic (tenacity, 3 attempts, exponential
backoff 1-10s) matching the existing pattern from NotionAdapter (05-03).
All methods are async and log with structlog for observability.

Methods cover the full bot lifecycle: create, status, audio output,
transcript retrieval, recording retrieval, and deletion.
"""

from __future__ import annotations

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)

# Retry decorator matching existing pattern from src/app/deals/crm/notion.py
_recall_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)),
)


class RecallClient:
    """Async client for Recall.ai REST API.

    Handles bot creation, monitoring, audio output, transcript and recording
    retrieval. Uses httpx.AsyncClient with configurable timeouts per
    operation type.

    Args:
        api_key: Recall.ai API token.
        region: Recall.ai region (default: us-west-2).
    """

    # Timeouts per operation type
    TIMEOUT_MUTATE = 30.0  # create/delete operations
    TIMEOUT_READ = 10.0    # get/status operations

    def __init__(self, api_key: str, region: str = "us-west-2") -> None:
        self._api_key = api_key
        self._base_url = f"https://{region}.recall.ai/api/v1"
        self._headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }

    def _client(self, timeout: float) -> httpx.AsyncClient:
        """Create a new httpx client with specified timeout."""
        return httpx.AsyncClient(
            headers=self._headers,
            timeout=timeout,
        )

    @_recall_retry
    async def create_bot(self, config: dict) -> dict:
        """Create a new meeting bot.

        POST /bot/ with the full bot configuration including Output Media,
        automatic_audio_output, real_time_endpoints, and automatic_leave.

        Args:
            config: Complete bot creation configuration dict.

        Returns:
            Bot creation response with bot id and status.
        """
        async with self._client(self.TIMEOUT_MUTATE) as client:
            response = await client.post(
                f"{self._base_url}/bot/",
                json=config,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "recall.bot_created",
                bot_id=data.get("id"),
                status="created",
            )
            return data

    @_recall_retry
    async def get_bot(self, bot_id: str) -> dict:
        """Get full bot details.

        GET /bot/{bot_id}/ returns complete bot state including
        status_changes, metadata, and configuration.

        Args:
            bot_id: Recall.ai bot identifier.

        Returns:
            Full bot detail response.
        """
        async with self._client(self.TIMEOUT_READ) as client:
            response = await client.get(
                f"{self._base_url}/bot/{bot_id}/",
            )
            response.raise_for_status()
            return response.json()

    @_recall_retry
    async def get_bot_status(self, bot_id: str) -> str:
        """Get current bot status code.

        Extracts the latest status from status_changes[-1].code.

        Args:
            bot_id: Recall.ai bot identifier.

        Returns:
            Status code string (e.g., 'ready', 'joining_call', 'in_call_recording',
            'call_ended').
        """
        bot_data = await self.get_bot(bot_id)
        status_changes = bot_data.get("status_changes", [])
        if not status_changes:
            return "unknown"
        current_status = status_changes[-1].get("code", "unknown")
        logger.debug(
            "recall.bot_status",
            bot_id=bot_id,
            status=current_status,
        )
        return current_status

    @_recall_retry
    async def send_audio(self, bot_id: str, mp3_b64: str) -> None:
        """Send MP3 audio to bot for playback in meeting.

        POST /bot/{bot_id}/output_audio/ with base64-encoded MP3 data.

        Args:
            bot_id: Recall.ai bot identifier.
            mp3_b64: Base64-encoded MP3 audio data.
        """
        async with self._client(self.TIMEOUT_MUTATE) as client:
            response = await client.post(
                f"{self._base_url}/bot/{bot_id}/output_audio/",
                json={"kind": "mp3", "b64_data": mp3_b64},
            )
            response.raise_for_status()
            logger.info(
                "recall.audio_sent",
                bot_id=bot_id,
                operation="send_audio",
            )

    @_recall_retry
    async def get_transcript(self, bot_id: str) -> list[dict]:
        """Get full transcript after meeting ends.

        GET /bot/{bot_id}/transcript/ returns per-speaker transcript entries.

        Args:
            bot_id: Recall.ai bot identifier.

        Returns:
            List of transcript entry dicts with speaker and text.
        """
        async with self._client(self.TIMEOUT_READ) as client:
            response = await client.get(
                f"{self._base_url}/bot/{bot_id}/transcript/",
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "recall.transcript_retrieved",
                bot_id=bot_id,
                entry_count=len(data) if isinstance(data, list) else 0,
            )
            return data if isinstance(data, list) else []

    @_recall_retry
    async def get_recording(self, bot_id: str) -> dict:
        """Get recording URL after meeting ends.

        GET /bot/{bot_id}/recording/ returns recording metadata and URL.

        Args:
            bot_id: Recall.ai bot identifier.

        Returns:
            Recording metadata dict with URL.
        """
        async with self._client(self.TIMEOUT_READ) as client:
            response = await client.get(
                f"{self._base_url}/bot/{bot_id}/recording/",
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "recall.recording_retrieved",
                bot_id=bot_id,
                operation="get_recording",
            )
            return data

    @_recall_retry
    async def delete_bot(self, bot_id: str) -> None:
        """Delete a bot and clean up resources.

        DELETE /bot/{bot_id}/

        Args:
            bot_id: Recall.ai bot identifier.
        """
        async with self._client(self.TIMEOUT_MUTATE) as client:
            response = await client.delete(
                f"{self._base_url}/bot/{bot_id}/",
            )
            response.raise_for_status()
            logger.info(
                "recall.bot_deleted",
                bot_id=bot_id,
                operation="delete",
            )
