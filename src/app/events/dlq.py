"""Dead letter queue handler for failed events.

Manages DLQ streams where events that exhausted their retry budget
are stored for manual review and optional replay.

DLQ key pattern: t:{tenant_id}:events:{original_stream}:dlq
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger(__name__)


class DeadLetterQueue:
    """Dead letter queue backed by Redis Streams.

    Failed events (after MAX_RETRIES exceeded) are moved here for
    review. Supports listing messages and replaying them back to
    their original stream.

    Args:
        redis: Raw async Redis client.
        tenant_id: Tenant identifier for DLQ key scoping.
    """

    def __init__(self, redis: aioredis.Redis, tenant_id: str) -> None:
        self._redis = redis
        self._tenant_id = tenant_id

    def _dlq_key(self, original_stream: str) -> str:
        """Build a DLQ stream key for a given original stream.

        Args:
            original_stream: The stream name the event originally
                belonged to (without tenant prefix).

        Returns:
            Full DLQ key like ``t:{tenant_id}:events:{stream}:dlq``.
        """
        return f"t:{self._tenant_id}:events:{original_stream}:dlq"

    def _original_stream_key(self, original_stream: str) -> str:
        """Build the original stream key for replay.

        Args:
            original_stream: Stream name without tenant prefix.

        Returns:
            Full stream key like ``t:{tenant_id}:events:{stream}``.
        """
        return f"t:{self._tenant_id}:events:{original_stream}"

    async def send_to_dlq(
        self,
        original_stream: str,
        message_id: str,
        data: dict[str, str],
        error: str,
        retry_count: int,
    ) -> str:
        """Move a failed event to the dead letter queue.

        Stores the original event data along with failure metadata
        (error message, retry count, DLQ timestamp, original message ID).

        Args:
            original_stream: Stream name the event was consumed from.
            message_id: Original Redis message ID.
            data: Raw event data dict from the stream.
            error: Error message from the last processing attempt.
            retry_count: Number of retry attempts made.

        Returns:
            DLQ message ID assigned by XADD.
        """
        dlq_key = self._dlq_key(original_stream)

        dlq_data: dict[str, str] = {
            **data,
            "_dlq_original_stream": original_stream,
            "_dlq_original_id": message_id,
            "_dlq_error": error,
            "_dlq_retry_count": str(retry_count),
            "_dlq_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        dlq_message_id = await self._redis.xadd(dlq_key, dlq_data)

        logger.warning(
            "event_dead_lettered",
            dlq_key=dlq_key,
            original_stream=original_stream,
            original_id=message_id,
            error=error,
            retry_count=retry_count,
        )
        return dlq_message_id

    async def list_dlq_messages(
        self,
        original_stream: str,
        count: int = 50,
    ) -> list[tuple[str, dict[str, Any]]]:
        """List messages in the dead letter queue for review.

        Args:
            original_stream: Stream name whose DLQ to inspect.
            count: Maximum messages to return (default 50).

        Returns:
            List of ``(message_id, data)`` tuples from the DLQ stream.
        """
        dlq_key = self._dlq_key(original_stream)
        return await self._redis.xrange(dlq_key, count=count)

    async def replay_message(
        self,
        original_stream: str,
        dlq_message_id: str,
    ) -> str:
        """Replay a DLQ message back to its original stream.

        Reads the message from the DLQ, strips DLQ metadata and retry
        count, and re-publishes to the original stream for fresh
        processing. Deletes the message from the DLQ after replay.

        Args:
            original_stream: Stream name to replay into.
            dlq_message_id: Message ID in the DLQ stream to replay.

        Returns:
            New message ID in the original stream.

        Raises:
            ValueError: If the DLQ message ID is not found.
        """
        dlq_key = self._dlq_key(original_stream)
        stream_key = self._original_stream_key(original_stream)

        # Read the specific message from DLQ
        messages = await self._redis.xrange(
            dlq_key,
            min=dlq_message_id,
            max=dlq_message_id,
            count=1,
        )

        if not messages:
            msg = f"DLQ message '{dlq_message_id}' not found in {dlq_key}"
            raise ValueError(msg)

        _msg_id, data = messages[0]

        # Strip DLQ metadata and reset retry count
        replay_data = {
            k: v for k, v in data.items()
            if not k.startswith("_dlq_")
        }
        replay_data.pop("_retry_count", None)

        # Re-publish to original stream
        new_id = await self._redis.xadd(
            stream_key,
            replay_data,
            maxlen=1000,
            approximate=True,
        )

        # Remove from DLQ
        await self._redis.xdel(dlq_key, dlq_message_id)

        logger.info(
            "event_replayed",
            original_stream=original_stream,
            dlq_message_id=dlq_message_id,
            new_message_id=new_id,
        )
        return new_id
