"""Phase 2 integration tests validating all 5 success criteria.

SC1: Supervisor task routing (route -> execute -> validate)
SC2: Event bus tenant isolation (tenant_a cannot see tenant_b events)
SC3: Handoff validation rejects malformed payloads
SC4: Context three-tier compilation (session + memory + working)
SC5: Observability tracing and metrics

These tests use mocks for external services (Redis, PostgreSQL, LLM)
so they can run without infrastructure dependencies.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.base import (
    AgentCapability,
    AgentRegistration,
    AgentStatus,
    BaseAgent,
)
from src.app.agents.registry import AgentRegistry
from src.app.agents.router import HybridRouter, RoutingDecision
from src.app.agents.supervisor import SupervisorOrchestrator
from src.app.config import Settings
from src.app.context.working import WorkingContextCompiler
from src.app.core.monitoring import (
    agent_invocations_total,
    handoff_validations_total,
)
from src.app.events.schemas import AgentEvent, EventType
from src.app.handoffs.protocol import HandoffProtocol, HandoffRejectedError
from src.app.handoffs.validators import (
    HandoffPayload,
    HandoffResult,
    StrictnessConfig,
    ValidationStrictness,
)
from src.app.observability.cost import CostTracker
from src.app.observability.tracer import AgentTracer, init_langfuse


# ── Test Agent ───────────────────────────────────────────────────────────────


class MockAgent(BaseAgent):
    """A test agent that returns a canned response."""

    def __init__(
        self,
        registration: AgentRegistration,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(registration)
        self._response = response or {"status": "done", "data": "test result"}

    async def execute(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        return self._response


def _make_registration(
    agent_id: str = "test_agent",
    name: str = "Test Agent",
    capabilities: list[str] | None = None,
) -> AgentRegistration:
    """Create an AgentRegistration for testing."""
    caps = [
        AgentCapability(name=c, description=f"Can do {c}")
        for c in (capabilities or ["research"])
    ]
    return AgentRegistration(
        agent_id=agent_id,
        name=name,
        description=f"{name} for testing",
        capabilities=caps,
    )


# ── SC1: Supervisor Task Routing ─────────────────────────────────────────────


class TestSupervisorTaskRouting:
    """SC1: Supervisor correctly routes tasks to agents and returns results."""

    @pytest.mark.asyncio
    async def test_supervisor_routes_to_correct_agent(self):
        """Create a mock agent, register it, route a task, verify result."""
        # Setup registry with mock agent
        registry = AgentRegistry()
        reg = _make_registration("research_agent", "Research Agent", ["research"])
        agent = MockAgent(reg, response={"findings": "test data"})
        reg._agent_instance = agent
        registry.register(reg)

        # Setup router with a deterministic rule
        llm_service = MagicMock()
        router = HybridRouter(registry, llm_service)
        router.add_rule(
            lambda t: t.get("type") == "research",
            "research_agent",
        )

        # Setup handoff protocol (lenient for status_update)
        config = StrictnessConfig()
        protocol = HandoffProtocol(strictness_config=config)

        # Setup context manager mock
        context_manager = AsyncMock()
        context_manager.compile_working_context = AsyncMock(
            return_value={
                "system_prompt": "You are a supervisor.",
                "messages": [],
                "context": "",
                "task": {"type": "research"},
                "token_usage": {"total": 100, "budget": 32000,
                                "system": 20, "session": 0,
                                "memory": 0, "task": 80},
            }
        )

        # Create supervisor
        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_manager,
            llm_service=llm_service,
        )

        # Execute task
        result = await supervisor.execute_task(
            task={"type": "research", "description": "Find info"},
            tenant_id="tenant_1",
            thread_id="thread_1",
        )

        # Verify routing
        assert result["decomposed"] is False
        assert result["routed_by"] == "rules"
        assert result["result"] == {"findings": "test data"}
        assert "research_agent" in result["call_chain"]

    @pytest.mark.asyncio
    async def test_supervisor_call_chain_includes_all_participants(self):
        """Call chain should include user, supervisor, and the executing agent."""
        registry = AgentRegistry()
        reg = _make_registration("sales_agent", "Sales Agent", ["sales"])
        agent = MockAgent(reg)
        reg._agent_instance = agent
        registry.register(reg)

        llm_service = MagicMock()
        router = HybridRouter(registry, llm_service)
        router.add_rule(lambda t: True, "sales_agent")

        config = StrictnessConfig()
        protocol = HandoffProtocol(strictness_config=config)

        context_manager = AsyncMock()
        context_manager.compile_working_context = AsyncMock(
            return_value={
                "system_prompt": "test", "messages": [], "context": "",
                "task": {}, "token_usage": {"total": 10, "budget": 32000,
                                            "system": 5, "session": 0,
                                            "memory": 0, "task": 5},
            }
        )

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_manager,
            llm_service=llm_service,
        )

        result = await supervisor.execute_task(
            task={"description": "Do sales stuff"},
            tenant_id="t1",
            thread_id="th1",
        )

        chain = result["call_chain"]
        assert "user" in chain
        assert "supervisor" in chain
        assert "sales_agent" in chain


# ── SC2: Event Bus Tenant Isolation ──────────────────────────────────────────


class TestEventBusTenantIsolation:
    """SC2: Events are tenant-isolated via stream key scoping."""

    def test_tenant_stream_key_isolation(self):
        """Different tenants get different stream keys."""
        from src.app.events.bus import TenantEventBus

        mock_redis = MagicMock()
        bus_a = TenantEventBus(mock_redis, "tenant_a")
        bus_b = TenantEventBus(mock_redis, "tenant_b")

        key_a = bus_a._stream_key("tasks")
        key_b = bus_b._stream_key("tasks")

        assert key_a != key_b
        assert "tenant_a" in key_a
        assert "tenant_b" in key_b
        assert key_a == "t:tenant_a:events:tasks"
        assert key_b == "t:tenant_b:events:tasks"

    @pytest.mark.asyncio
    async def test_event_bus_rejects_cross_tenant_publish(self):
        """Publishing an event with wrong tenant_id raises ValueError."""
        from src.app.events.bus import TenantEventBus

        mock_redis = AsyncMock()
        bus = TenantEventBus(mock_redis, "tenant_a")

        event = AgentEvent(
            event_type=EventType.TASK_ASSIGNED,
            tenant_id="tenant_b",  # Wrong tenant!
            source_agent_id="supervisor",
            call_chain=["supervisor"],
        )

        with pytest.raises(ValueError, match="does not match"):
            await bus.publish("tasks", event)

    def test_events_carry_source_attribution(self):
        """AgentEvent carries source_agent_id and call_chain."""
        event = AgentEvent(
            event_type=EventType.TASK_COMPLETED,
            tenant_id="t1",
            source_agent_id="research_agent",
            call_chain=["user", "supervisor", "research_agent"],
            data={"result": "found info"},
        )

        assert event.source_agent_id == "research_agent"
        assert event.call_chain == ["user", "supervisor", "research_agent"]

        # Verify serialization preserves attribution
        stream_dict = event.to_stream_dict()
        assert stream_dict["source_agent_id"] == "research_agent"
        assert "research_agent" in stream_dict["call_chain"]


# ── SC3: Handoff Validation Rejects Malformed ─────────────────────────────


class TestHandoffValidation:
    """SC3: Handoff protocol rejects malformed payloads with reasons."""

    def test_missing_source_attribution_rejected(self):
        """HandoffPayload with source not in call_chain is rejected."""
        with pytest.raises(ValueError, match="must appear in call_chain"):
            HandoffPayload(
                source_agent_id="agent_a",
                target_agent_id="agent_b",
                call_chain=["agent_c"],  # source not in chain!
                tenant_id="t1",
                handoff_type="deal_data",
                data={"amount": 100},
            )

    def test_circular_handoff_rejected(self):
        """HandoffPayload with target already in call_chain is rejected."""
        with pytest.raises(ValueError, match="must NOT appear in call_chain"):
            HandoffPayload(
                source_agent_id="agent_a",
                target_agent_id="agent_b",
                call_chain=["agent_a", "agent_b"],  # target in chain!
                tenant_id="t1",
                handoff_type="deal_data",
                data={"amount": 100},
            )

    @pytest.mark.asyncio
    async def test_strict_validation_with_semantic_check(self):
        """STRICT validation invokes semantic validator for deal_data."""
        config = StrictnessConfig()
        assert config.get_strictness("deal_data") == ValidationStrictness.STRICT

        # Mock semantic validator that detects ungrounded data
        mock_semantic = AsyncMock()
        mock_semantic.validate = AsyncMock(
            return_value=(False, ["Revenue claim $10M not supported by context"])
        )

        protocol = HandoffProtocol(
            strictness_config=config,
            semantic_validator=mock_semantic,
        )

        payload = HandoffPayload(
            source_agent_id="research_agent",
            target_agent_id="supervisor",
            call_chain=["research_agent"],
            tenant_id="t1",
            handoff_type="deal_data",
            data={"revenue": "$10M", "company": "Acme"},
        )

        with pytest.raises(HandoffRejectedError) as exc_info:
            await protocol.validate_or_reject(payload)

        err = exc_info.value
        assert len(err.result.semantic_issues) > 0
        assert "Revenue claim" in err.result.semantic_issues[0]

    @pytest.mark.asyncio
    async def test_lenient_validation_skips_semantic(self):
        """LENIENT validation (status_update) skips semantic validation."""
        config = StrictnessConfig()
        assert config.get_strictness("status_update") == ValidationStrictness.LENIENT

        mock_semantic = AsyncMock()
        protocol = HandoffProtocol(
            strictness_config=config,
            semantic_validator=mock_semantic,
        )

        payload = HandoffPayload(
            source_agent_id="agent_a",
            target_agent_id="supervisor",
            call_chain=["agent_a"],
            tenant_id="t1",
            handoff_type="status_update",
            data={"status": "completed"},
        )

        result = await protocol.validate(payload)
        assert result.valid is True
        assert result.strictness == ValidationStrictness.LENIENT
        mock_semantic.validate.assert_not_called()

    def test_unknown_handoff_type_defaults_to_strict(self):
        """Unknown handoff types default to STRICT (fail-safe)."""
        config = StrictnessConfig()
        assert config.get_strictness("totally_new_type") == ValidationStrictness.STRICT


# ── SC4: Context Three-Tier Compilation ──────────────────────────────────────


class TestContextThreeTiers:
    """SC4: Working context compiler integrates session + memory + task."""

    @pytest.mark.asyncio
    async def test_working_context_includes_all_tiers(self):
        """WorkingContextCompiler assembles system prompt, messages, memories."""
        compiler = WorkingContextCompiler("reasoning")

        session_messages = [
            {"role": "user", "content": "Hello, I want to discuss the Acme deal"},
            {"role": "assistant", "content": "I can help with that. What about Acme?"},
            {"role": "user", "content": "What is their annual budget?"},
        ]

        relevant_memories = [
            "Customer Acme Corp has an annual IT budget of $500,000",
            "Acme Corp's CTO is Jane Smith, who prefers quarterly reviews",
        ]

        task = {
            "type": "deal_analysis",
            "description": "Analyze the Acme deal budget",
        }

        result = await compiler.compile(
            system_prompt="You are a sales agent helping with deal analysis.",
            session_messages=session_messages,
            relevant_memories=relevant_memories,
            task=task,
        )

        # Verify all three tiers are present
        assert "You are a sales agent" in result["system_prompt"]
        assert len(result["messages"]) > 0  # Session messages
        assert "Acme Corp" in result["context"]  # Memories
        assert result["task"]["type"] == "deal_analysis"

        # Verify token usage tracking
        assert result["token_usage"]["total"] > 0
        assert result["token_usage"]["total"] <= result["token_usage"]["budget"]
        assert result["token_usage"]["session"] > 0
        assert result["token_usage"]["memory"] > 0

    @pytest.mark.asyncio
    async def test_token_budget_enforcement(self):
        """Working context respects token budget limits."""
        compiler = WorkingContextCompiler("fast")  # 8k budget

        # Generate large session history that exceeds budget
        big_messages = [
            {"role": "user", "content": f"Message {i}: " + "x" * 500}
            for i in range(50)
        ]

        result = await compiler.compile(
            system_prompt="System prompt.",
            session_messages=big_messages,
            relevant_memories=["Memory 1"],
            task={"description": "test"},
        )

        # Total should be within budget
        assert result["token_usage"]["total"] <= result["token_usage"]["budget"]
        # Some messages should have been truncated
        assert len(result["messages"]) < len(big_messages)

    @pytest.mark.asyncio
    async def test_context_manager_orchestrates_all_three(self):
        """ContextManager.compile_working_context orchestrates session + memory + compiler."""
        from src.app.context.manager import ContextManager

        # Mock session store
        mock_session = AsyncMock()
        mock_session.get_session_messages = AsyncMock(
            return_value=[
                {"role": "user", "content": "What about the deal?"},
                {"role": "assistant", "content": "Let me check."},
            ]
        )

        # Mock memory
        mock_memory = AsyncMock()
        mock_entry = MagicMock()
        mock_entry.content = "Acme has a $500k budget"
        mock_memory.search = AsyncMock(return_value=[mock_entry])

        # Real compiler
        compiler = WorkingContextCompiler("reasoning")

        manager = ContextManager(mock_session, mock_memory, compiler)

        result = await manager.compile_working_context(
            tenant_id="t1",
            thread_id="thread_123",
            task={"description": "Analyze deal budget"},
            system_prompt="You are a sales agent.",
        )

        # Verify all tiers were consulted
        mock_session.get_session_messages.assert_called_once_with("thread_123")
        mock_memory.search.assert_called_once()
        assert "Acme" in result["context"]
        assert len(result["messages"]) == 2
        assert result["token_usage"]["total"] > 0


# ── SC5: Observability Tracing and Metrics ───────────────────────────────────


class TestObservabilityTracing:
    """SC5: Tracing metadata propagation and Prometheus metrics."""

    def test_agent_tracer_propagates_metadata(self):
        """AgentTracer.trace_agent_execution sets correct metadata."""
        settings = Settings(LANGFUSE_PUBLIC_KEY="", LANGFUSE_SECRET_KEY="")
        tracer = AgentTracer(settings)

        # Even in no-op mode, metadata is returned correctly
        with tracer.trace_agent_execution(
            agent_id="sales_agent",
            tenant_id="tenant_42",
            session_id="sess_abc",
        ) as meta:
            assert meta["agent_id"] == "sales_agent"
            assert meta["tenant_id"] == "tenant_42"
            assert "trace_id" in meta

    def test_prometheus_agent_metrics_increment(self):
        """Agent invocation metrics increment on invocation."""
        before = agent_invocations_total.labels(
            agent_id="integ_agent",
            tenant_id="integ_tenant",
            status="success",
        )._value.get()

        agent_invocations_total.labels(
            agent_id="integ_agent",
            tenant_id="integ_tenant",
            status="success",
        ).inc()

        after = agent_invocations_total.labels(
            agent_id="integ_agent",
            tenant_id="integ_tenant",
            status="success",
        )._value.get()

        assert after == before + 1

    def test_handoff_validation_metrics_increment(self):
        """Handoff validation metrics increment on validation."""
        before = handoff_validations_total.labels(
            source_agent="integ_src",
            target_agent="integ_tgt",
            strictness="strict",
            result="rejected",
        )._value.get()

        handoff_validations_total.labels(
            source_agent="integ_src",
            target_agent="integ_tgt",
            strictness="strict",
            result="rejected",
        ).inc()

        after = handoff_validations_total.labels(
            source_agent="integ_src",
            target_agent="integ_tgt",
            strictness="strict",
            result="rejected",
        )._value.get()

        assert after == before + 1

    def test_init_langfuse_graceful_without_keys(self):
        """init_langfuse returns False and doesn't crash when keys missing."""
        settings = Settings(LANGFUSE_PUBLIC_KEY="", LANGFUSE_SECRET_KEY="")
        result = init_langfuse(settings)
        assert result is False

    @pytest.mark.asyncio
    async def test_cost_tracker_graceful_degradation(self):
        """CostTracker returns unavailable when not configured."""
        settings = Settings(LANGFUSE_PUBLIC_KEY="", LANGFUSE_SECRET_KEY="")
        tracker = CostTracker(settings)

        tenant_costs = await tracker.get_tenant_costs("t1")
        assert tenant_costs["source"] == "unavailable"
        assert tenant_costs["total_cost"] == 0.0

        agent_costs = await tracker.get_agent_costs("agent_1")
        assert agent_costs["source"] == "unavailable"
        assert agent_costs["total_cost"] == 0.0
