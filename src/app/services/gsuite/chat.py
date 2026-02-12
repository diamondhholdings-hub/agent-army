"""Async Google Chat API service for sending messages to spaces.

All Google API calls are wrapped in asyncio.to_thread() to avoid
blocking the event loop (Pitfall 7 from research).
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from src.app.services.gsuite.auth import GSuiteAuthManager
from src.app.services.gsuite.models import ChatMessage, SentChatResult

logger = structlog.get_logger(__name__)


class ChatService:
    """Async wrapper around Google Chat API for sending messages to spaces."""

    def __init__(self, auth_manager: GSuiteAuthManager) -> None:
        self._auth = auth_manager

    async def send_message(self, message: ChatMessage) -> SentChatResult:
        """Send a message to a Google Chat space.

        Supports threaded conversations via thread_key. When thread_key
        is provided, uses REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD to reply
        to an existing thread or create a new one if the thread doesn't exist.

        Args:
            message: The ChatMessage to send.

        Returns:
            SentChatResult with message_name and create_time.
        """
        service = self._auth.get_chat_service()

        message_body: dict[str, Any] = {"text": message.text}
        kwargs: dict[str, Any] = {
            "parent": message.space_name,
            "body": message_body,
        }

        if message.thread_key:
            kwargs["messageReplyOption"] = (
                "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
            )
            message_body["thread"] = {"threadKey": message.thread_key}

        def _send() -> dict:
            return (
                service.spaces()
                .messages()
                .create(**kwargs)
                .execute()
            )

        logger.info(
            "sending_chat_message",
            space=message.space_name,
            thread_key=message.thread_key,
        )
        result = await asyncio.to_thread(_send)

        return SentChatResult(
            message_name=result.get("name", ""),
            create_time=result.get("createTime", ""),
        )

    async def list_spaces(self) -> list[dict[str, str]]:
        """List Google Chat spaces the bot has access to.

        Returns:
            List of dicts with 'name' and 'displayName' keys.
        """
        service = self._auth.get_chat_service()

        def _list() -> dict:
            return service.spaces().list().execute()

        logger.info("listing_chat_spaces")
        result = await asyncio.to_thread(_list)

        spaces: list[dict[str, str]] = []
        for space in result.get("spaces", []):
            spaces.append({
                "name": space.get("name", ""),
                "displayName": space.get("displayName", ""),
            })

        return spaces
