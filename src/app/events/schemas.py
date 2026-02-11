"""Event schemas for inter-agent communication via Redis Streams.

Provides the core event model (AgentEvent) with source attribution,
call chain traceability, and hybrid payload support. Events serialize
to flat string dicts for Redis Streams and deserialize back losslessly.

Stream key pattern: t:{tenant_id}:events:{stream_name}
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class EventPriority(str, Enum):
    """Priority levels for event processing ordering."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class EventType(str, Enum):
    """Types of events exchanged between agents.

    Covers task lifecycle, handoff validation, context updates,
    and agent registry/health signals.
    """

    TASK_ASSIGNED = "task.assigned"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    HANDOFF_REQUEST = "handoff.request"
    HANDOFF_VALIDATED = "handoff.validated"
    HANDOFF_REJECTED = "handoff.rejected"
    CONTEXT_UPDATED = "context.updated"
    AGENT_REGISTERED = "agent.registered"
    AGENT_HEALTH = "agent.health"


class AgentEvent(BaseModel):
    """Core event schema for inter-agent communication.

    Every event carries source attribution (which agent emitted it and
    the full call chain that led to it) and tenant context for isolation.
    Payload uses a hybrid approach: small data inline, large data by
    reference to the shared context store.

    Attributes:
        event_id: Unique identifier (auto-generated UUID4).
        version: Schema version for forward compatibility.
        event_type: The kind of event (task, handoff, context, agent).
        timestamp: UTC creation time.
        tenant_id: Owning tenant for stream isolation.
        priority: Processing priority hint.
        source_agent_id: Agent that emitted this event.
        call_chain: Full trace of agents involved, e.g.
            ["user", "supervisor", "research_agent"].
        data: Small inline payload data.
        context_refs: References to large data in shared context store.
        correlation_id: Groups related events across a workflow.
        parent_event_id: Links to the event that triggered this one.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    version: str = "1.0"
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tenant_id: str
    priority: EventPriority = EventPriority.NORMAL

    # Source attribution (locked decision: agent ID in every event)
    source_agent_id: str

    # Full call chain for traceability (locked decision)
    call_chain: list[str]

    # Hybrid payload (locked decision: small inline, large by reference)
    data: dict[str, Any] = Field(default_factory=dict)
    context_refs: list[str] = Field(default_factory=list)

    # Correlation
    correlation_id: str | None = None
    parent_event_id: str | None = None

    @model_validator(mode="after")
    def _validate_call_chain(self) -> AgentEvent:
        """Ensure call_chain is non-empty and includes the source agent."""
        if not self.call_chain:
            msg = "call_chain must not be empty"
            raise ValueError(msg)
        if self.source_agent_id not in self.call_chain:
            msg = f"source_agent_id '{self.source_agent_id}' must appear in call_chain {self.call_chain}"
            raise ValueError(msg)
        return self

    def to_stream_dict(self) -> dict[str, str]:
        """Serialize all fields to a flat dict of strings for Redis Streams.

        Redis Streams require all field values to be strings. Complex
        types are JSON-encoded; lists of strings are comma-joined;
        datetimes use ISO format; None becomes empty string.

        Returns:
            Dictionary with string keys and string values suitable for XADD.
        """
        return {
            "event_id": self.event_id,
            "version": self.version,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "tenant_id": self.tenant_id,
            "priority": self.priority.value,
            "source_agent_id": self.source_agent_id,
            "call_chain": ",".join(self.call_chain),
            "data": json.dumps(self.data),
            "context_refs": ",".join(self.context_refs),
            "correlation_id": self.correlation_id or "",
            "parent_event_id": self.parent_event_id or "",
        }

    @classmethod
    def from_stream_dict(cls, raw: dict[str, str]) -> AgentEvent:
        """Deserialize from a Redis Streams flat dict back to AgentEvent.

        Reverses the encoding performed by ``to_stream_dict()``.

        Args:
            raw: Dictionary of string key-value pairs from XREADGROUP.

        Returns:
            Reconstructed AgentEvent instance.
        """
        return cls(
            event_id=raw["event_id"],
            version=raw.get("version", "1.0"),
            event_type=EventType(raw["event_type"]),
            timestamp=datetime.fromisoformat(raw["timestamp"]),
            tenant_id=raw["tenant_id"],
            priority=EventPriority(raw["priority"]),
            source_agent_id=raw["source_agent_id"],
            call_chain=raw["call_chain"].split(",") if raw["call_chain"] else [],
            data=json.loads(raw["data"]) if raw.get("data") else {},
            context_refs=[r for r in raw.get("context_refs", "").split(",") if r],
            correlation_id=raw.get("correlation_id") or None,
            parent_event_id=raw.get("parent_event_id") or None,
        )
