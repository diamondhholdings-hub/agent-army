"""Tests for the event-driven backbone: schemas, bus, consumer, and DLQ.

Covers:
- AgentEvent creation, validation, and serialization roundtrip
- TenantEventBus tenant isolation and publish/subscribe
- EventConsumer retry tracking and DLQ escalation
- DeadLetterQueue storage, listing, and replay
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.events.bus import TenantEventBus
from src.app.events.consumer import EventConsumer
from src.app.events.dlq import DeadLetterQueue
from src.app.events.schemas import AgentEvent, EventPriority, EventType


# ── Schema Tests ──────────────────────────────────────────────────────────


class TestAgentEvent:
    """Tests for AgentEvent creation and validation."""

    def test_create_minimal_event(self):
        """Event with required fields and sensible defaults."""
        event = AgentEvent(
            event_type=EventType.TASK_ASSIGNED,
            tenant_id="tenant-1",
            source_agent_id="supervisor",
            call_chain=["supervisor"],
        )
        assert event.event_id  # UUID generated
        assert event.version == "1.0"
        assert event.priority == EventPriority.NORMAL
        assert event.data == {}
        assert event.context_refs == []
        assert event.correlation_id is None
        assert event.parent_event_id is None
        assert isinstance(event.timestamp, datetime)

    def test_create_full_event(self):
        """Event with all optional fields populated."""
        event = AgentEvent(
            event_type=EventType.HANDOFF_REQUEST,
            tenant_id="tenant-2",
            source_agent_id="research_agent",
            call_chain=["user", "supervisor", "research_agent"],
            priority=EventPriority.HIGH,
            data={"query": "Find customer revenue"},
            context_refs=["ctx:doc-123", "ctx:doc-456"],
            correlation_id="corr-abc",
            parent_event_id="evt-parent",
        )
        assert event.priority == EventPriority.HIGH
        assert event.data == {"query": "Find customer revenue"}
        assert event.context_refs == ["ctx:doc-123", "ctx:doc-456"]
        assert event.correlation_id == "corr-abc"

    def test_validation_empty_call_chain_fails(self):
        """Empty call_chain must be rejected."""
        with pytest.raises(ValueError, match="call_chain must not be empty"):
            AgentEvent(
                event_type=EventType.TASK_ASSIGNED,
                tenant_id="t",
                source_agent_id="agent",
                call_chain=[],
            )

    def test_validation_source_not_in_chain_fails(self):
        """source_agent_id must appear in call_chain."""
        with pytest.raises(ValueError, match="must appear in call_chain"):
            AgentEvent(
                event_type=EventType.TASK_ASSIGNED,
                tenant_id="t",
                source_agent_id="agent_a",
                call_chain=["agent_b", "agent_c"],
            )

    def test_stream_dict_roundtrip(self):
        """to_stream_dict -> from_stream_dict preserves all fields."""
        original = AgentEvent(
            event_type=EventType.CONTEXT_UPDATED,
            tenant_id="tenant-rt",
            source_agent_id="writer",
            call_chain=["user", "supervisor", "writer"],
            priority=EventPriority.CRITICAL,
            data={"key": "value", "nested": {"a": 1}},
            context_refs=["ref-1", "ref-2"],
            correlation_id="corr-xyz",
            parent_event_id="parent-xyz",
        )

        stream_dict = original.to_stream_dict()

        # All values must be strings for Redis Streams
        assert all(isinstance(v, str) for v in stream_dict.values())

        restored = AgentEvent.from_stream_dict(stream_dict)

        assert restored.event_id == original.event_id
        assert restored.version == original.version
        assert restored.event_type == original.event_type
        assert restored.tenant_id == original.tenant_id
        assert restored.priority == original.priority
        assert restored.source_agent_id == original.source_agent_id
        assert restored.call_chain == original.call_chain
        assert restored.data == original.data
        assert restored.context_refs == original.context_refs
        assert restored.correlation_id == original.correlation_id
        assert restored.parent_event_id == original.parent_event_id

    def test_stream_dict_roundtrip_empty_optionals(self):
        """Roundtrip works when optional fields are None/empty."""
        original = AgentEvent(
            event_type=EventType.AGENT_HEALTH,
            tenant_id="tenant-emp",
            source_agent_id="monitor",
            call_chain=["monitor"],
        )

        stream_dict = original.to_stream_dict()
        restored = AgentEvent.from_stream_dict(stream_dict)

        assert restored.correlation_id is None
        assert restored.parent_event_id is None
        assert restored.data == {}
        assert restored.context_refs == []

    def test_all_event_types_exist(self):
        """Verify all required event types are defined."""
        expected = {
            "TASK_ASSIGNED", "TASK_COMPLETED", "TASK_FAILED",
            "HANDOFF_REQUEST", "HANDOFF_VALIDATED", "HANDOFF_REJECTED",
            "CONTEXT_UPDATED", "AGENT_REGISTERED", "AGENT_HEALTH",
        }
        actual = {e.name for e in EventType}
        assert expected == actual

    def test_all_priority_levels_exist(self):
        """Verify all priority levels are defined."""
        expected = {"LOW", "NORMAL", "HIGH", "CRITICAL"}
        actual = {p.name for p in EventPriority}
        assert expected == actual


# ── TenantEventBus Tests ─────────────────────────────────────────────────


class TestTenantEventBus:
    """Tests for tenant-scoped event bus."""

    def test_stream_key_format(self):
        """Stream key follows t:{tenant_id}:events:{stream} pattern."""
        mock_redis = MagicMock()
        bus = TenantEventBus(redis=mock_redis, tenant_id="acme-corp")
        assert bus._stream_key("tasks") == "t:acme-corp:events:tasks"
        assert bus._stream_key("handoffs") == "t:acme-corp:events:handoffs"

    @pytest.mark.asyncio
    async def test_publish_tenant_mismatch_raises(self):
        """Publishing an event with wrong tenant_id raises ValueError."""
        mock_redis = AsyncMock()
        bus = TenantEventBus(redis=mock_redis, tenant_id="tenant-a")

        event = AgentEvent(
            event_type=EventType.TASK_ASSIGNED,
            tenant_id="tenant-b",  # Mismatch!
            source_agent_id="agent",
            call_chain=["agent"],
        )

        with pytest.raises(ValueError, match="does not match"):
            await bus.publish("tasks", event)

    @pytest.mark.asyncio
    async def test_publish_calls_xadd(self):
        """Publish serializes event and calls xadd with MAXLEN trimming."""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")
        bus = TenantEventBus(redis=mock_redis, tenant_id="tenant-pub")

        event = AgentEvent(
            event_type=EventType.TASK_COMPLETED,
            tenant_id="tenant-pub",
            source_agent_id="worker",
            call_chain=["supervisor", "worker"],
        )

        msg_id = await bus.publish("tasks", event)

        assert msg_id == "1234567890-0"
        mock_redis.xadd.assert_called_once()

        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "t:tenant-pub:events:tasks"
        # Check data dict is passed
        data = call_args[0][1]
        assert data["event_type"] == "task.completed"
        assert data["tenant_id"] == "tenant-pub"
        # Check MAXLEN trimming
        assert call_args[1]["maxlen"] == 1000
        assert call_args[1]["approximate"] is True

    @pytest.mark.asyncio
    async def test_subscribe_creates_group_and_reads(self):
        """Subscribe creates consumer group (idempotent) and reads messages."""
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=[])
        bus = TenantEventBus(redis=mock_redis, tenant_id="tenant-sub")

        result = await bus.subscribe("tasks", "workers", "worker-1")

        mock_redis.xgroup_create.assert_called_once_with(
            "t:tenant-sub:events:tasks", "workers", id="0", mkstream=True,
        )
        mock_redis.xreadgroup.assert_called_once()
        assert result == []

    @pytest.mark.asyncio
    async def test_ack_calls_xack(self):
        """Ack forwards to Redis XACK."""
        mock_redis = AsyncMock()
        bus = TenantEventBus(redis=mock_redis, tenant_id="tenant-ack")

        await bus.ack("tasks", "workers", "1234-0")

        mock_redis.xack.assert_called_once_with(
            "t:tenant-ack:events:tasks", "workers", "1234-0",
        )


# ── EventConsumer Tests ──────────────────────────────────────────────────


class TestEventConsumer:
    """Tests for consumer retry logic and DLQ escalation."""

    def _make_event_data(self, retry_count: int = 0) -> dict[str, str]:
        """Build a valid event stream dict for testing."""
        event = AgentEvent(
            event_type=EventType.TASK_ASSIGNED,
            tenant_id="tenant-cons",
            source_agent_id="supervisor",
            call_chain=["supervisor"],
        )
        data = event.to_stream_dict()
        if retry_count > 0:
            data["_retry_count"] = str(retry_count)
        return data

    @pytest.mark.asyncio
    async def test_successful_processing_acks_message(self):
        """Handler success leads to message acknowledgment."""
        mock_redis = AsyncMock()
        bus = TenantEventBus(redis=mock_redis, tenant_id="tenant-cons")
        dlq = DeadLetterQueue(redis=mock_redis, tenant_id="tenant-cons")
        consumer = EventConsumer(
            bus=bus, stream="tasks", group="workers",
            consumer_name="w1", dlq=dlq,
        )

        handler = AsyncMock()
        data = self._make_event_data()

        await consumer._process_with_retry("msg-1", data, handler)

        handler.assert_called_once()
        mock_redis.xack.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_below_max_retries_republishes(self):
        """Failure with retry_count < MAX_RETRIES re-publishes with incremented count."""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="new-msg-id")
        bus = TenantEventBus(redis=mock_redis, tenant_id="tenant-cons")
        dlq = DeadLetterQueue(redis=mock_redis, tenant_id="tenant-cons")
        consumer = EventConsumer(
            bus=bus, stream="tasks", group="workers",
            consumer_name="w1", dlq=dlq,
        )

        handler = AsyncMock(side_effect=RuntimeError("processing failed"))
        data = self._make_event_data(retry_count=1)

        with patch("src.app.events.consumer.asyncio.sleep", new_callable=AsyncMock):
            await consumer._process_with_retry("msg-retry", data, handler)

        # Should re-publish with incremented retry count
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        republished_data = call_args[0][1]
        assert republished_data["_retry_count"] == "2"

        # Should ack the original
        mock_redis.xack.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_at_max_retries_sends_to_dlq(self):
        """Failure at MAX_RETRIES sends to DLQ and acks original."""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="dlq-msg-id")
        bus = TenantEventBus(redis=mock_redis, tenant_id="tenant-cons")
        dlq = DeadLetterQueue(redis=mock_redis, tenant_id="tenant-cons")
        consumer = EventConsumer(
            bus=bus, stream="tasks", group="workers",
            consumer_name="w1", dlq=dlq,
        )

        handler = AsyncMock(side_effect=RuntimeError("permanent failure"))
        data = self._make_event_data(retry_count=3)  # == MAX_RETRIES

        await consumer._process_with_retry("msg-dlq", data, handler)

        # Should have sent to DLQ via xadd
        mock_redis.xadd.assert_called_once()
        dlq_call = mock_redis.xadd.call_args
        dlq_key = dlq_call[0][0]
        assert dlq_key == "t:tenant-cons:events:tasks:dlq"

        dlq_data = dlq_call[0][1]
        assert dlq_data["_dlq_error"] == "permanent failure"
        assert dlq_data["_dlq_retry_count"] == "3"

        # Should ack the original message
        mock_redis.xack.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_delays_are_exponential(self):
        """Retry delays follow the [1, 4, 16] pattern."""
        assert EventConsumer.RETRY_DELAYS == [1, 4, 16]
        assert EventConsumer.MAX_RETRIES == 3

    def test_stop_sets_running_false(self):
        """stop() signals the processing loop to exit."""
        mock_redis = MagicMock()
        bus = TenantEventBus(redis=mock_redis, tenant_id="t")
        dlq = DeadLetterQueue(redis=mock_redis, tenant_id="t")
        consumer = EventConsumer(
            bus=bus, stream="s", group="g",
            consumer_name="c", dlq=dlq,
        )
        consumer._running = True
        consumer.stop()
        assert consumer._running is False


# ── DeadLetterQueue Tests ────────────────────────────────────────────────


class TestDeadLetterQueue:
    """Tests for DLQ storage, listing, and replay."""

    def test_dlq_key_format(self):
        """DLQ key follows t:{tenant}:events:{stream}:dlq pattern."""
        mock_redis = MagicMock()
        dlq = DeadLetterQueue(redis=mock_redis, tenant_id="acme")
        assert dlq._dlq_key("tasks") == "t:acme:events:tasks:dlq"

    @pytest.mark.asyncio
    async def test_send_to_dlq_adds_metadata(self):
        """send_to_dlq stores original data plus DLQ metadata."""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="dlq-1234-0")
        dlq = DeadLetterQueue(redis=mock_redis, tenant_id="tenant-dlq")

        data = {"event_type": "task.assigned", "tenant_id": "tenant-dlq"}

        result = await dlq.send_to_dlq(
            original_stream="tasks",
            message_id="orig-msg-1",
            data=data,
            error="Handler crashed",
            retry_count=3,
        )

        assert result == "dlq-1234-0"
        mock_redis.xadd.assert_called_once()

        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "t:tenant-dlq:events:tasks:dlq"
        dlq_data = call_args[0][1]
        assert dlq_data["_dlq_error"] == "Handler crashed"
        assert dlq_data["_dlq_retry_count"] == "3"
        assert dlq_data["_dlq_original_stream"] == "tasks"
        assert dlq_data["_dlq_original_id"] == "orig-msg-1"
        assert "_dlq_timestamp" in dlq_data

    @pytest.mark.asyncio
    async def test_list_dlq_messages(self):
        """list_dlq_messages reads from the DLQ stream."""
        mock_redis = AsyncMock()
        mock_redis.xrange = AsyncMock(return_value=[
            ("dlq-1", {"event_type": "task.failed"}),
        ])
        dlq = DeadLetterQueue(redis=mock_redis, tenant_id="tenant-list")

        messages = await dlq.list_dlq_messages("tasks", count=10)

        mock_redis.xrange.assert_called_once_with(
            "t:tenant-list:events:tasks:dlq", count=10,
        )
        assert len(messages) == 1

    @pytest.mark.asyncio
    async def test_replay_message_republishes_and_deletes(self):
        """replay_message re-publishes to original stream and removes from DLQ."""
        mock_redis = AsyncMock()
        mock_redis.xrange = AsyncMock(return_value=[
            ("dlq-msg-1", {
                "event_type": "task.assigned",
                "tenant_id": "tenant-rpl",
                "_dlq_original_stream": "tasks",
                "_dlq_original_id": "orig-1",
                "_dlq_error": "test error",
                "_dlq_retry_count": "3",
                "_dlq_timestamp": "2026-01-01T00:00:00",
                "_retry_count": "3",
            }),
        ])
        mock_redis.xadd = AsyncMock(return_value="new-msg-1")
        mock_redis.xdel = AsyncMock()
        dlq = DeadLetterQueue(redis=mock_redis, tenant_id="tenant-rpl")

        new_id = await dlq.replay_message("tasks", "dlq-msg-1")

        assert new_id == "new-msg-1"

        # Check re-publish to original stream
        xadd_call = mock_redis.xadd.call_args
        assert xadd_call[0][0] == "t:tenant-rpl:events:tasks"
        replay_data = xadd_call[0][1]
        # DLQ metadata and retry count should be stripped
        assert "_dlq_original_stream" not in replay_data
        assert "_dlq_error" not in replay_data
        assert "_retry_count" not in replay_data
        # Original event data preserved
        assert replay_data["event_type"] == "task.assigned"

        # Check deletion from DLQ
        mock_redis.xdel.assert_called_once_with(
            "t:tenant-rpl:events:tasks:dlq", "dlq-msg-1",
        )

    @pytest.mark.asyncio
    async def test_replay_nonexistent_message_raises(self):
        """replay_message raises ValueError for missing DLQ message."""
        mock_redis = AsyncMock()
        mock_redis.xrange = AsyncMock(return_value=[])
        dlq = DeadLetterQueue(redis=mock_redis, tenant_id="tenant-miss")

        with pytest.raises(ValueError, match="not found"):
            await dlq.replay_message("tasks", "nonexistent-id")


# ── Integration Import Test ──────────────────────────────────────────────


class TestPackageImports:
    """Test that the events package exports all expected names."""

    def test_all_exports_importable(self):
        """All names in __all__ are importable."""
        from src.app.events import (
            AgentEvent,
            DeadLetterQueue,
            EventConsumer,
            EventPriority,
            EventType,
            TenantEventBus,
        )

        assert AgentEvent is not None
        assert EventType is not None
        assert EventPriority is not None
        assert TenantEventBus is not None
        assert EventConsumer is not None
        assert DeadLetterQueue is not None
