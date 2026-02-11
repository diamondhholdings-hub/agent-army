"""Event consumer with retry logic and consumer group management.

Reads events from a tenant-scoped Redis Stream via a consumer group,
deserializes them into AgentEvent instances, and invokes a handler.
Failed events are retried with exponential backoff (1s, 4s, 16s) and
moved to a dead letter queue after 3 attempts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import structlog

from src.app.events.bus import TenantEventBus
from src.app.events.dlq import DeadLetterQueue
from src.app.events.schemas import AgentEvent

logger = structlog.get_logger(__name__)


class EventConsumer:
    """Consumer that processes events from a Redis Stream with retry logic.

    Uses a consumer group for parallel processing. Failed messages are
    retried up to MAX_RETRIES times with exponential backoff delays,
    then moved to the dead letter queue for manual review.

    Args:
        bus: TenantEventBus for reading events.
        stream: Stream name to consume from.
        group: Consumer group name.
        consumer_name: Unique consumer identifier within the group.
        dlq: DeadLetterQueue for permanently failed messages.
    """

    MAX_RETRIES: int = 3
    RETRY_DELAYS: list[int] = [1, 4, 16]  # Exponential backoff: 1s, 4s, 16s

    def __init__(
        self,
        bus: TenantEventBus,
        stream: str,
        group: str,
        consumer_name: str,
        dlq: DeadLetterQueue,
    ) -> None:
        self._bus = bus
        self._stream = stream
        self._group = group
        self._consumer_name = consumer_name
        self._dlq = dlq
        self._running = False

    async def process_loop(
        self,
        handler: Callable[[AgentEvent], Awaitable[None]],
    ) -> None:
        """Main processing loop: read, deserialize, handle, ack.

        Blocks indefinitely reading from the consumer group. For each
        message, deserializes to AgentEvent and invokes the handler.
        On handler failure, delegates to _process_with_retry.

        Args:
            handler: Async callable that processes a single AgentEvent.
                Must raise on failure for retry to engage.
        """
        self._running = True
        logger.info(
            "consumer_started",
            stream=self._stream,
            group=self._group,
            consumer=self._consumer_name,
        )

        while self._running:
            messages = await self._bus.subscribe(
                self._stream,
                self._group,
                self._consumer_name,
            )

            for _stream_key, stream_messages in messages:
                for message_id, raw_data in stream_messages:
                    await self._process_with_retry(
                        message_id, raw_data, handler,
                    )

    async def _process_with_retry(
        self,
        message_id: str,
        raw_data: dict[str, str],
        handler: Callable[[AgentEvent], Awaitable[None]],
    ) -> None:
        """Process a message with exponential backoff retry.

        On success, acknowledges the original message. On failure:
        - If retry count >= MAX_RETRIES, sends to DLQ and acks original.
        - Otherwise, sleeps with backoff and re-publishes with incremented
          retry count. The re-published message will be picked up as a
          new delivery.

        Args:
            message_id: Redis message ID.
            raw_data: Raw string dict from Redis Stream.
            handler: Async handler callable.
        """
        retry_count = int(raw_data.get("_retry_count", "0"))

        try:
            event = AgentEvent.from_stream_dict(raw_data)
            await handler(event)
            await self._bus.ack(self._stream, self._group, message_id)

            logger.debug(
                "event_processed",
                event_id=event.event_id,
                event_type=event.event_type.value,
                message_id=message_id,
            )

        except Exception as exc:
            logger.warning(
                "event_processing_failed",
                message_id=message_id,
                retry_count=retry_count,
                error=str(exc),
            )

            if retry_count >= self.MAX_RETRIES:
                # Exhausted retries -- send to dead letter queue
                await self._dlq.send_to_dlq(
                    original_stream=self._stream,
                    message_id=message_id,
                    data=raw_data,
                    error=str(exc),
                    retry_count=retry_count,
                )
                await self._bus.ack(self._stream, self._group, message_id)

                logger.error(
                    "event_sent_to_dlq",
                    message_id=message_id,
                    retry_count=retry_count,
                    error=str(exc),
                )
            else:
                # Backoff and re-publish
                delay_idx = min(retry_count, len(self.RETRY_DELAYS) - 1)
                delay = self.RETRY_DELAYS[delay_idx]
                await asyncio.sleep(delay)

                # Re-publish with incremented retry count
                retry_data = dict(raw_data)
                retry_data["_retry_count"] = str(retry_count + 1)
                await self._bus._redis.xadd(
                    self._bus._stream_key(self._stream),
                    retry_data,
                    maxlen=1000,
                    approximate=True,
                )
                await self._bus.ack(self._stream, self._group, message_id)

                logger.info(
                    "event_retried",
                    message_id=message_id,
                    retry_count=retry_count + 1,
                    delay=delay,
                )

    async def reclaim_abandoned(
        self,
        idle_time_ms: int = 60000,
    ) -> list:
        """Reclaim messages from dead or stalled consumers.

        Uses XAUTOCLAIM to take ownership of messages that have been
        idle in the pending entry list for longer than idle_time_ms.

        Args:
            idle_time_ms: Minimum idle time in milliseconds (default 60s).

        Returns:
            List of reclaimed messages.
        """
        result = await self._bus._redis.xautoclaim(
            self._bus._stream_key(self._stream),
            self._group,
            self._consumer_name,
            min_idle_time=idle_time_ms,
            start_id="0",
            count=10,
        )
        return result

    def stop(self) -> None:
        """Signal the processing loop to stop after current iteration."""
        self._running = False
