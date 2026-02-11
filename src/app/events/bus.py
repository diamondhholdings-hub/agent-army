"""Tenant-scoped event bus using Redis Streams.

Provides publish/subscribe to tenant-isolated streams with consumer
group management, message acknowledgment, and stream monitoring.

Stream key pattern: t:{tenant_id}:events:{stream_name}

Note: This module uses raw redis.asyncio.Redis instead of the TenantRedis
wrapper because Redis Streams have their own key pattern and need direct
access to XADD/XREADGROUP/XACK commands not exposed by TenantRedis.
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
import structlog

from src.app.events.schemas import AgentEvent

logger = structlog.get_logger(__name__)


class TenantEventBus:
    """Publish and subscribe to tenant-scoped Redis Streams.

    Each tenant's events are isolated by stream key prefix. Consumer
    groups enable parallel processing with exactly-once delivery semantics
    via acknowledgment.

    Args:
        redis: Raw async Redis client (NOT TenantRedis wrapper).
        tenant_id: Tenant identifier for stream key scoping.
    """

    def __init__(self, redis: aioredis.Redis, tenant_id: str) -> None:
        self._redis = redis
        self._tenant_id = tenant_id

    def _stream_key(self, stream: str) -> str:
        """Build a tenant-scoped stream key.

        Args:
            stream: Stream name (e.g. "tasks", "handoffs").

        Returns:
            Full key like ``t:{tenant_id}:events:{stream}``.
        """
        return f"t:{self._tenant_id}:events:{stream}"

    async def publish(self, stream: str, event: AgentEvent) -> str:
        """Publish an event to a tenant-scoped stream.

        Validates that the event's tenant_id matches this bus, serializes
        the event, and appends to the stream with approximate trimming.

        Args:
            stream: Stream name to publish to.
            event: AgentEvent to publish.

        Returns:
            Redis message ID assigned by XADD.

        Raises:
            ValueError: If event.tenant_id does not match bus tenant_id.
        """
        if event.tenant_id != self._tenant_id:
            msg = (
                f"Event tenant_id '{event.tenant_id}' does not match "
                f"bus tenant_id '{self._tenant_id}'"
            )
            raise ValueError(msg)

        stream_key = self._stream_key(stream)
        data = event.to_stream_dict()

        message_id = await self._redis.xadd(
            stream_key,
            data,
            maxlen=1000,
            approximate=True,
        )

        logger.debug(
            "event_published",
            stream=stream_key,
            event_type=event.event_type.value,
            event_id=event.event_id,
            message_id=message_id,
        )
        return message_id

    async def subscribe(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block: int = 5000,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        """Read new events as a consumer in a consumer group.

        Creates the consumer group if it does not already exist.

        Args:
            stream: Stream name to consume from.
            group: Consumer group name.
            consumer: Consumer name within the group.
            count: Maximum messages to read per call.
            block: Milliseconds to block waiting for new messages.

        Returns:
            List of ``(stream_key, [(message_id, data), ...])`` tuples.
        """
        stream_key = self._stream_key(stream)

        # Create the consumer group (idempotent)
        try:
            await self._redis.xgroup_create(
                stream_key, group, id="0", mkstream=True,
            )
        except aioredis.ResponseError:
            pass  # Group already exists

        messages = await self._redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream_key: ">"},
            count=count,
            block=block,
        )
        return messages

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge a processed message.

        Args:
            stream: Stream name the message belongs to.
            group: Consumer group name.
            message_id: Redis message ID to acknowledge.
        """
        await self._redis.xack(self._stream_key(stream), group, message_id)

    async def get_stream_info(self, stream: str) -> dict[str, Any]:
        """Get stream metadata for monitoring.

        Args:
            stream: Stream name to inspect.

        Returns:
            Dictionary with stream length, groups, first/last entry, etc.
        """
        return await self._redis.xinfo_stream(self._stream_key(stream))

    async def get_pending(self, stream: str, group: str) -> dict[str, Any]:
        """Get pending message summary for a consumer group.

        Useful for monitoring message backlog and consumer health.

        Args:
            stream: Stream name.
            group: Consumer group name.

        Returns:
            Pending summary with count, min/max IDs, and per-consumer counts.
        """
        return await self._redis.xpending(self._stream_key(stream), group)
