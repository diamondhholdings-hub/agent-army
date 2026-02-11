"""Event-driven backbone for agent coordination.

Provides tenant-scoped Redis Streams pub/sub with structured event
schemas, consumer group processing, exponential-backoff retry, and
dead letter queue handling.

Exports:
    AgentEvent: Core event Pydantic model with source attribution.
    EventType: Enum of event categories (task, handoff, context, agent).
    EventPriority: Processing priority levels (LOW through CRITICAL).
    TenantEventBus: Publish/subscribe to tenant-scoped Redis Streams.
    EventConsumer: Consumer with retry logic and consumer group management.
    DeadLetterQueue: DLQ handler for failed event review and replay.
"""

from __future__ import annotations

from src.app.events.schemas import AgentEvent, EventPriority, EventType

__all__ = [
    "AgentEvent",
    "DeadLetterQueue",
    "EventConsumer",
    "EventPriority",
    "EventType",
    "TenantEventBus",
]


def __getattr__(name: str):  # noqa: N807
    """Lazy-load bus, consumer, and DLQ to avoid circular imports."""
    if name == "TenantEventBus":
        from src.app.events.bus import TenantEventBus

        return TenantEventBus
    if name == "EventConsumer":
        from src.app.events.consumer import EventConsumer

        return EventConsumer
    if name == "DeadLetterQueue":
        from src.app.events.dlq import DeadLetterQueue

        return DeadLetterQueue
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
