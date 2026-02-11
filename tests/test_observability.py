"""Unit tests for observability: Langfuse tracing and cost tracking.

Tests cover:
- init_langfuse with and without configured keys
- AgentTracer no-op behavior without Langfuse
- AgentTracer context manager metadata propagation
- CostTracker unavailable mode
- Agent Prometheus metrics increment
- track_agent_invocation context manager
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.app.config import Settings
from src.app.core.monitoring import (
    agent_invocations_total,
    agent_invocation_duration_seconds,
    handoff_validations_total,
    supervisor_tasks_total,
    context_compilation_duration_seconds,
    track_agent_invocation,
)
from src.app.observability.cost import CostTracker
from src.app.observability.tracer import AgentTracer, init_langfuse


def _make_settings(**overrides) -> Settings:
    """Create a Settings instance with Langfuse keys optionally set."""
    defaults = {
        "LANGFUSE_PUBLIC_KEY": "",
        "LANGFUSE_SECRET_KEY": "",
        "LANGFUSE_HOST": "https://cloud.langfuse.com",
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ── init_langfuse ────────────────────────────────────────────────────────────


class TestInitLangfuse:
    """Tests for the init_langfuse function."""

    def test_init_langfuse_with_keys(self):
        """When keys are configured, litellm callbacks are set."""
        settings = _make_settings(
            LANGFUSE_PUBLIC_KEY="pk-test-123",
            LANGFUSE_SECRET_KEY="sk-test-456",
        )

        import litellm

        # Save originals and reset
        orig_success = litellm.success_callback
        orig_failure = litellm.failure_callback
        litellm.success_callback = []
        litellm.failure_callback = []

        try:
            result = init_langfuse(settings)

            assert result is True
            assert "langfuse" in litellm.success_callback
            assert "langfuse" in litellm.failure_callback
        finally:
            litellm.success_callback = orig_success
            litellm.failure_callback = orig_failure

    def test_init_langfuse_without_keys(self):
        """When keys are not configured, Langfuse is skipped gracefully."""
        settings = _make_settings()

        result = init_langfuse(settings)

        assert result is False

    def test_init_langfuse_idempotent(self):
        """Calling init_langfuse twice does not duplicate callbacks."""
        settings = _make_settings(
            LANGFUSE_PUBLIC_KEY="pk-test",
            LANGFUSE_SECRET_KEY="sk-test",
        )

        import litellm

        orig_success = litellm.success_callback
        orig_failure = litellm.failure_callback
        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]

        try:
            init_langfuse(settings)

            # Should not have duplicate entries
            assert litellm.success_callback.count("langfuse") == 1
            assert litellm.failure_callback.count("langfuse") == 1
        finally:
            litellm.success_callback = orig_success
            litellm.failure_callback = orig_failure


# ── AgentTracer ──────────────────────────────────────────────────────────────


class TestAgentTracer:
    """Tests for the AgentTracer class."""

    def test_noop_without_langfuse(self):
        """AgentTracer methods are no-ops when Langfuse is not configured."""
        settings = _make_settings()
        tracer = AgentTracer(settings)

        assert tracer.enabled is False

        # Context manager should work as no-op
        with tracer.trace_agent_execution("test_agent", "tenant_1") as meta:
            assert "trace_id" in meta
            assert meta["agent_id"] == "test_agent"
            assert meta["tenant_id"] == "tenant_1"

        # trace_handoff should not raise
        tracer.trace_handoff("agent_a", "agent_b", "tenant_1", valid=True)

    def test_trace_agent_execution_yields_metadata(self):
        """trace_agent_execution yields metadata dict with trace info."""
        settings = _make_settings()
        tracer = AgentTracer(settings)

        with tracer.trace_agent_execution(
            "sales_agent", "tenant_42", session_id="session_abc"
        ) as meta:
            assert meta["agent_id"] == "sales_agent"
            assert meta["tenant_id"] == "tenant_42"
            assert "trace_id" in meta
            assert isinstance(meta["trace_id"], str)
            assert len(meta["trace_id"]) > 0

    def test_trace_handoff_noop(self):
        """trace_handoff is safe to call when Langfuse is disabled."""
        settings = _make_settings()
        tracer = AgentTracer(settings)

        # Should not raise even when called with various parameters
        tracer.trace_handoff("agent_a", "agent_b", "t1", valid=True)
        tracer.trace_handoff("agent_x", "agent_y", "t2", valid=False)


# ── CostTracker ──────────────────────────────────────────────────────────────


class TestCostTracker:
    """Tests for the CostTracker class."""

    @pytest.mark.asyncio
    async def test_cost_tracker_unavailable(self):
        """CostTracker returns zero costs when Langfuse is not configured."""
        settings = _make_settings()
        tracker = CostTracker(settings)

        assert tracker.enabled is False

        result = await tracker.get_tenant_costs("tenant_1")
        assert result["source"] == "unavailable"
        assert result["total_cost"] == 0.0
        assert result["tenant_id"] == "tenant_1"
        assert result["agents"] == {}

    @pytest.mark.asyncio
    async def test_agent_costs_unavailable(self):
        """get_agent_costs returns unavailable when Langfuse is not configured."""
        settings = _make_settings()
        tracker = CostTracker(settings)

        result = await tracker.get_agent_costs("sales_agent")
        assert result["source"] == "unavailable"
        assert result["total_cost"] == 0.0
        assert result["agent_id"] == "sales_agent"
        assert result["tenants"] == {}

    @pytest.mark.asyncio
    async def test_cost_tracker_period_days(self):
        """Period days parameter is included in the response."""
        settings = _make_settings()
        tracker = CostTracker(settings)

        result = await tracker.get_tenant_costs("t1", period_days=7)
        assert result["period_days"] == 7


# ── Agent Prometheus Metrics ─────────────────────────────────────────────────


class TestAgentMetrics:
    """Tests for agent-specific Prometheus metrics."""

    def test_agent_invocations_total_increment(self):
        """agent_invocations_total counter increments correctly."""
        before = agent_invocations_total.labels(
            agent_id="test_agent",
            tenant_id="t1",
            status="success",
        )._value.get()

        agent_invocations_total.labels(
            agent_id="test_agent",
            tenant_id="t1",
            status="success",
        ).inc()

        after = agent_invocations_total.labels(
            agent_id="test_agent",
            tenant_id="t1",
            status="success",
        )._value.get()

        assert after == before + 1

    def test_handoff_validations_total_increment(self):
        """handoff_validations_total counter increments correctly."""
        before = handoff_validations_total.labels(
            source_agent="agent_a",
            target_agent="agent_b",
            strictness="strict",
            result="valid",
        )._value.get()

        handoff_validations_total.labels(
            source_agent="agent_a",
            target_agent="agent_b",
            strictness="strict",
            result="valid",
        ).inc()

        after = handoff_validations_total.labels(
            source_agent="agent_a",
            target_agent="agent_b",
            strictness="strict",
            result="valid",
        )._value.get()

        assert after == before + 1

    def test_supervisor_tasks_counter_exists(self):
        """supervisor_tasks_total counter has expected labels."""
        supervisor_tasks_total.labels(
            tenant_id="t1",
            decomposed="false",
            status="success",
        ).inc()
        # No assertion needed -- just verifying no error on label access

    def test_context_compilation_histogram_exists(self):
        """context_compilation_duration_seconds histogram has expected labels."""
        context_compilation_duration_seconds.labels(
            tenant_id="t1",
            model_tier="reasoning",
        ).observe(0.5)
        # No assertion needed -- verifying no error on label access

    @pytest.mark.asyncio
    async def test_track_agent_invocation_success(self):
        """track_agent_invocation records success metrics."""
        before = agent_invocations_total.labels(
            agent_id="tracked_agent",
            tenant_id="t_track",
            status="success",
        )._value.get()

        async with track_agent_invocation("tracked_agent", "t_track"):
            pass  # Simulate successful invocation

        after = agent_invocations_total.labels(
            agent_id="tracked_agent",
            tenant_id="t_track",
            status="success",
        )._value.get()

        assert after == before + 1

    @pytest.mark.asyncio
    async def test_track_agent_invocation_error(self):
        """track_agent_invocation records error metrics on exception."""
        before = agent_invocations_total.labels(
            agent_id="error_agent",
            tenant_id="t_err",
            status="error",
        )._value.get()

        with pytest.raises(ValueError, match="test error"):
            async with track_agent_invocation("error_agent", "t_err"):
                raise ValueError("test error")

        after = agent_invocations_total.labels(
            agent_id="error_agent",
            tenant_id="t_err",
            status="error",
        )._value.get()

        assert after == before + 1
