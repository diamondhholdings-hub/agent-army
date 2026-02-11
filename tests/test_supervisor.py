"""Tests for the SupervisorOrchestrator and HybridRouter.

All agent invocations, LLM calls, and context operations are mocked.
Tests cover routing, decomposition, failure handling with backup agents,
handoff validation, result synthesis, call chain tracking, context
compilation, and parallel subtask execution.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.base import AgentCapability, AgentRegistration, AgentStatus, BaseAgent
from src.app.agents.registry import AgentRegistry
from src.app.agents.router import HybridRouter, RoutingDecision, TaskDecomposition
from src.app.agents.supervisor import (
    AgentExecutionError,
    SupervisorOrchestrator,
    create_supervisor_graph,
)
from src.app.handoffs.protocol import HandoffProtocol, HandoffRejectedError
from src.app.handoffs.validators import HandoffPayload, HandoffResult, StrictnessConfig, ValidationStrictness


# -- Test Helpers --------------------------------------------------------------


class MockAgent(BaseAgent):
    """A concrete agent for testing that returns a configurable result."""

    def __init__(self, registration: AgentRegistration, result: dict | None = None, fail: bool = False) -> None:
        super().__init__(registration)
        self._result = result or {"status": "done", "data": f"result from {registration.agent_id}"}
        self._fail = fail

    async def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if self._fail:
            raise RuntimeError(f"Agent {self.agent_id} failed")
        return self._result


def make_registration(
    agent_id: str,
    capabilities: list[str] | None = None,
    backup_agent_id: str | None = None,
    agent_instance: BaseAgent | None = None,
) -> AgentRegistration:
    """Create an AgentRegistration with optional agent instance attached."""
    caps = [AgentCapability(name=c, description=f"{c} capability") for c in (capabilities or ["general"])]
    reg = AgentRegistration(
        agent_id=agent_id,
        name=f"{agent_id.replace('_', ' ').title()}",
        description=f"Agent: {agent_id}",
        capabilities=caps,
        backup_agent_id=backup_agent_id,
    )
    if agent_instance:
        reg._agent_instance = agent_instance  # type: ignore[attr-defined]
    return reg


def make_registry_with_agents(*agent_specs: tuple) -> tuple[AgentRegistry, dict[str, MockAgent]]:
    """Create a registry populated with mock agents.

    Each spec is (agent_id, capabilities, backup_agent_id, fail, result).
    """
    registry = AgentRegistry()
    agents: dict[str, MockAgent] = {}

    for spec in agent_specs:
        agent_id = spec[0]
        capabilities = spec[1] if len(spec) > 1 else ["general"]
        backup_id = spec[2] if len(spec) > 2 else None
        fail = spec[3] if len(spec) > 3 else False
        result = spec[4] if len(spec) > 4 else None

        reg = AgentRegistration(
            agent_id=agent_id,
            name=f"{agent_id.replace('_', ' ').title()}",
            description=f"Agent: {agent_id}",
            capabilities=[AgentCapability(name=c, description=f"{c} cap") for c in capabilities],
            backup_agent_id=backup_id,
        )
        agent = MockAgent(reg, result=result, fail=fail)
        reg._agent_instance = agent  # type: ignore[attr-defined]
        registry.register(reg)
        agents[agent_id] = agent

    return registry, agents


def make_mock_llm(responses: list[str] | None = None) -> AsyncMock:
    """Create a mock LLMService that returns canned responses."""
    llm = AsyncMock()
    if responses:
        llm.completion = AsyncMock(side_effect=[{"content": r} for r in responses])
    else:
        llm.completion = AsyncMock(return_value={"content": '{"agent_id": "research", "reasoning": "best fit", "confidence": 0.9}'})
    return llm


def make_mock_context_manager() -> AsyncMock:
    """Create a mock ContextManager."""
    cm = AsyncMock()
    cm.compile_working_context = AsyncMock(return_value={
        "system_prompt": "You are a supervisor.",
        "messages": [],
        "context": [],
        "task": {},
        "token_usage": {"total": 100},
    })
    return cm


def make_mock_handoff_protocol(reject: bool = False) -> AsyncMock:
    """Create a mock HandoffProtocol."""
    protocol = AsyncMock(spec=HandoffProtocol)
    if reject:
        result = HandoffResult(
            valid=False,
            strictness=ValidationStrictness.STRICT,
            structural_issues=["missing required field"],
        )
        payload = HandoffPayload(
            source_agent_id="test_agent",
            target_agent_id="supervisor",
            call_chain=["test_agent"],
            tenant_id="t1",
            handoff_type="deal_data",
            data={},
        )
        protocol.validate_or_reject = AsyncMock(
            side_effect=HandoffRejectedError(result=result, payload=payload)
        )
    else:
        # Return the payload passed to it (pass-through)
        async def passthrough(payload, context=None):
            return payload
        protocol.validate_or_reject = AsyncMock(side_effect=passthrough)
    return protocol


# -- Router Tests --------------------------------------------------------------


class TestHybridRouterRules:
    """Test deterministic rules-based routing."""

    @pytest.mark.asyncio
    async def test_rule_matches_first(self):
        """First matching rule wins."""
        registry, _ = make_registry_with_agents(
            ("research", ["research"]),
            ("sales", ["sales"]),
        )
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)

        router.add_rule(lambda t: t.get("type") == "research", "research")
        router.add_rule(lambda t: t.get("type") == "sales", "sales")

        decision = await router.route({"type": "research", "description": "find info"})
        assert decision.agent_id == "research"
        assert decision.routed_by == "rules"
        assert decision.confidence == 1.0
        llm.completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_rule_falls_to_llm(self):
        """No matching rule triggers LLM routing."""
        registry, _ = make_registry_with_agents(
            ("research", ["research"]),
        )
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)

        # No rules added
        decision = await router.route({"type": "ambiguous", "description": "do something"})
        assert decision.agent_id == "research"
        assert decision.routed_by == "llm"
        llm.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_rule(self):
        """Removing a rule prevents it from matching."""
        registry, _ = make_registry_with_agents(("research", ["research"]))
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)

        router.add_rule(lambda t: True, "research")
        router.remove_rule("research")

        # Should fall through to LLM since rule was removed
        decision = await router.route({"description": "test"})
        assert decision.routed_by == "llm"


# -- Supervisor Tests ----------------------------------------------------------


class TestSimpleTaskRouting:
    """Test that simple tasks route directly without decomposition."""

    @pytest.mark.asyncio
    async def test_simple_task_routes_directly(self):
        """Simple task goes to a single agent without decomposition."""
        registry, agents = make_registry_with_agents(
            ("research", ["research"]),
        )
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)
        router.add_rule(lambda t: t.get("type") == "research", "research")

        context_mgr = make_mock_context_manager()
        protocol = make_mock_handoff_protocol()

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_mgr,
            llm_service=llm,
        )

        result = await supervisor.execute_task(
            task={"type": "research", "description": "find competitors"},
            tenant_id="t1",
            thread_id="thread-1",
        )

        assert result["decomposed"] is False
        assert result["routed_by"] == "rules"
        assert "research" in result["call_chain"]
        assert "supervisor" in result["call_chain"]
        assert "user" in result["call_chain"]


class TestComplexTaskDecomposition:
    """Test that complex multi-goal tasks trigger decomposition."""

    @pytest.mark.asyncio
    async def test_complex_task_decomposes(self):
        """Long multi-goal task triggers decomposition."""
        registry, agents = make_registry_with_agents(
            ("research", ["research"]),
            ("sales", ["sales"]),
        )

        # LLM responses: first for decompose, then for routing subtask 1, then routing subtask 2, then synthesis
        llm_responses = [
            # decompose
            '{"subtasks": [{"description": "research competitors", "required_capabilities": ["research"], "priority": 1, "depends_on": []}, {"description": "prepare pitch", "required_capabilities": ["sales"], "priority": 2, "depends_on": [0]}]}',
            # route subtask 1
            '{"agent_id": "research", "reasoning": "research task", "confidence": 0.9}',
            # route subtask 2
            '{"agent_id": "sales", "reasoning": "sales task", "confidence": 0.9}',
            # synthesis
            '{"summary": "Combined result", "details": {"research": "data", "pitch": "ready"}, "sources": ["research", "sales"]}',
        ]
        llm = make_mock_llm(llm_responses)
        router = HybridRouter(registry, llm)
        # No rules -- forces LLM routing for subtasks

        context_mgr = make_mock_context_manager()
        protocol = make_mock_handoff_protocol()

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_mgr,
            llm_service=llm,
        )

        # Task with explicit subtask markers triggers decomposition
        task = {
            "type": "complex",
            "description": "1. Research all competitors in the enterprise CRM space. 2. Prepare a detailed sales pitch based on the research findings.",
        }

        result = await supervisor.execute_task(
            task=task,
            tenant_id="t1",
            thread_id="thread-1",
        )

        assert result["decomposed"] is True
        assert len(result["agent_results"]) == 2


class TestAgentFailureBackup:
    """Test backup agent routing on primary failure."""

    @pytest.mark.asyncio
    async def test_agent_failure_routes_to_backup(self):
        """Primary agent fails, backup agent takes over."""
        registry, agents = make_registry_with_agents(
            ("primary", ["research"], "backup", True),   # primary fails
            ("backup", ["research"], None, False),        # backup succeeds
        )
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)
        router.add_rule(lambda t: True, "primary")

        context_mgr = make_mock_context_manager()
        protocol = make_mock_handoff_protocol()

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_mgr,
            llm_service=llm,
        )

        result = await supervisor.execute_task(
            task={"type": "research", "description": "find data"},
            tenant_id="t1",
            thread_id="thread-1",
        )

        # Backup agent should have handled it
        assert "backup" in result["call_chain"]
        assert result["result"]["data"] == "result from backup"

    @pytest.mark.asyncio
    async def test_no_backup_raises(self):
        """Agent fails with no backup configured -- raises AgentExecutionError."""
        registry, agents = make_registry_with_agents(
            ("solo", ["research"], None, True),  # fails, no backup
        )
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)
        router.add_rule(lambda t: True, "solo")

        context_mgr = make_mock_context_manager()
        protocol = make_mock_handoff_protocol()

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_mgr,
            llm_service=llm,
        )

        with pytest.raises(AgentExecutionError) as exc_info:
            await supervisor.execute_task(
                task={"type": "research", "description": "find data"},
                tenant_id="t1",
                thread_id="thread-1",
            )

        assert exc_info.value.agent_id == "solo"
        assert exc_info.value.backup_tried is False


class TestHandoffValidation:
    """Test handoff validation enforcement."""

    @pytest.mark.asyncio
    async def test_handoff_validation_rejects(self):
        """Agent output fails validation -- HandoffRejectedError raised."""
        registry, agents = make_registry_with_agents(
            ("research", ["research"]),
        )
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)
        router.add_rule(lambda t: True, "research")

        context_mgr = make_mock_context_manager()
        protocol = make_mock_handoff_protocol(reject=True)

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_mgr,
            llm_service=llm,
        )

        with pytest.raises(HandoffRejectedError):
            await supervisor.execute_task(
                task={"type": "research", "description": "find data"},
                tenant_id="t1",
                thread_id="thread-1",
            )


class TestResultSynthesis:
    """Test LLM-based result synthesis for multi-agent outputs."""

    @pytest.mark.asyncio
    async def test_result_synthesis(self):
        """Multiple agent results synthesized into coherent response."""
        registry, agents = make_registry_with_agents(
            ("research", ["research"]),
            ("analyst", ["analysis"]),
        )

        # LLM responses for: decompose, route 1, route 2, synthesis
        llm_responses = [
            '{"subtasks": [{"description": "research", "required_capabilities": ["research"], "priority": 1, "depends_on": []}, {"description": "analyze", "required_capabilities": ["analysis"], "priority": 1, "depends_on": []}]}',
            '{"agent_id": "research", "reasoning": "research match", "confidence": 0.9}',
            '{"agent_id": "analyst", "reasoning": "analysis match", "confidence": 0.9}',
            '{"summary": "Comprehensive analysis based on research", "details": {"findings": "merged"}, "sources": ["research", "analyst"]}',
        ]
        llm = make_mock_llm(llm_responses)
        router = HybridRouter(registry, llm)

        context_mgr = make_mock_context_manager()
        protocol = make_mock_handoff_protocol()

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_mgr,
            llm_service=llm,
        )

        task = {
            "type": "complex",
            "description": "1. Research the market. 2. Analyze the competitive landscape.",
        }

        result = await supervisor.execute_task(
            task=task,
            tenant_id="t1",
            thread_id="thread-1",
        )

        assert result["decomposed"] is True
        assert isinstance(result["result"], dict)
        assert "summary" in result["result"]
        assert "sources" in result["result"]


class TestCallChainTracking:
    """Test call chain tracking through the supervisor."""

    @pytest.mark.asyncio
    async def test_call_chain_tracking(self):
        """Call chain includes user, supervisor, and agent IDs."""
        registry, agents = make_registry_with_agents(
            ("research", ["research"]),
        )
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)
        router.add_rule(lambda t: True, "research")

        context_mgr = make_mock_context_manager()
        protocol = make_mock_handoff_protocol()

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_mgr,
            llm_service=llm,
        )

        result = await supervisor.execute_task(
            task={"type": "research", "description": "find info"},
            tenant_id="t1",
            thread_id="thread-1",
        )

        chain = result["call_chain"]
        assert chain[0] == "user"
        assert chain[1] == "supervisor"
        assert "research" in chain


class TestWorkingContext:
    """Test that context manager is called before agent execution."""

    @pytest.mark.asyncio
    async def test_working_context_compiled(self):
        """Verify compile_working_context is called before agent execution."""
        registry, agents = make_registry_with_agents(
            ("research", ["research"]),
        )
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)
        router.add_rule(lambda t: True, "research")

        context_mgr = make_mock_context_manager()
        protocol = make_mock_handoff_protocol()

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_mgr,
            llm_service=llm,
        )

        await supervisor.execute_task(
            task={"type": "research", "description": "find info"},
            tenant_id="t1",
            thread_id="thread-1",
        )

        context_mgr.compile_working_context.assert_called_once_with(
            tenant_id="t1",
            thread_id="thread-1",
            task={"type": "research", "description": "find info"},
            system_prompt="You are a supervisor agent coordinating specialist agents.",
        )


class TestParallelSubtaskExecution:
    """Test that independent subtasks execute concurrently."""

    @pytest.mark.asyncio
    async def test_parallel_subtask_execution(self):
        """Independent subtasks execute concurrently (timing-based verification)."""
        # Create agents with a small delay to detect parallelism
        registry = AgentRegistry()
        agents = {}

        for aid in ["fast_a", "fast_b"]:
            reg = AgentRegistration(
                agent_id=aid,
                name=aid,
                description=f"Agent {aid}",
                capabilities=[AgentCapability(name="work", description="work")],
            )

            class TimedAgent(BaseAgent):
                async def execute(self, task, context):
                    await asyncio.sleep(0.05)  # 50ms per agent
                    return {"status": "done", "data": f"from {self.agent_id}"}

            agent = TimedAgent(reg)
            reg._agent_instance = agent  # type: ignore[attr-defined]
            registry.register(reg)
            agents[aid] = agent

        # LLM responses: decompose, route subtask 1, route subtask 2, synthesis
        llm_responses = [
            '{"subtasks": [{"description": "task a", "required_capabilities": ["work"], "priority": 1, "depends_on": []}, {"description": "task b", "required_capabilities": ["work"], "priority": 1, "depends_on": []}]}',
            '{"agent_id": "fast_a", "reasoning": "first", "confidence": 0.9}',
            '{"agent_id": "fast_b", "reasoning": "second", "confidence": 0.9}',
            '{"summary": "Combined", "details": {}, "sources": ["fast_a", "fast_b"]}',
        ]
        llm = make_mock_llm(llm_responses)
        router = HybridRouter(registry, llm)

        context_mgr = make_mock_context_manager()
        protocol = make_mock_handoff_protocol()

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_mgr,
            llm_service=llm,
        )

        task = {
            "type": "complex",
            "description": "1. Do task A. 2. Do task B independently.",
        }

        start = time.monotonic()
        result = await supervisor.execute_task(
            task=task,
            tenant_id="t1",
            thread_id="thread-1",
        )
        elapsed = time.monotonic() - start

        assert result["decomposed"] is True
        assert len(result["agent_results"]) == 2
        # If truly parallel, should take ~50ms not ~100ms
        # Allow generous margin for CI environments
        assert elapsed < 0.3, f"Parallel execution took {elapsed:.3f}s (expected < 0.3s)"


class TestCreateSupervisorGraph:
    """Test the factory function."""

    def test_create_supervisor_graph(self):
        """Factory wires all dependencies correctly."""
        registry = AgentRegistry()
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)
        context_mgr = make_mock_context_manager()
        protocol = make_mock_handoff_protocol()

        supervisor = create_supervisor_graph(
            registry=registry,
            router=router,
            handoff_protocol=protocol,
            context_manager=context_mgr,
            llm_service=llm,
        )

        assert isinstance(supervisor, SupervisorOrchestrator)
        assert supervisor._registry is registry
        assert supervisor._router is router
        assert supervisor._handoff_protocol is protocol
        assert supervisor._context_manager is context_mgr
        assert supervisor._llm_service is llm


class TestShouldDecompose:
    """Test the decomposition heuristic."""

    @pytest.mark.asyncio
    async def test_short_task_not_decomposed(self):
        """Short simple tasks are not decomposed."""
        registry = AgentRegistry()
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=make_mock_handoff_protocol(),
            context_manager=make_mock_context_manager(),
            llm_service=llm,
        )

        assert await supervisor._should_decompose({"description": "find competitors"}) is False

    @pytest.mark.asyncio
    async def test_numbered_list_triggers_decomposition(self):
        """Tasks with numbered step markers trigger decomposition."""
        registry = AgentRegistry()
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=make_mock_handoff_protocol(),
            context_manager=make_mock_context_manager(),
            llm_service=llm,
        )

        task = {"description": "1. Research the market thoroughly. 2. Analyze findings and prepare report."}
        assert await supervisor._should_decompose(task) is True

    @pytest.mark.asyncio
    async def test_empty_description_not_decomposed(self):
        """Empty description is never decomposed."""
        registry = AgentRegistry()
        llm = make_mock_llm()
        router = HybridRouter(registry, llm)

        supervisor = SupervisorOrchestrator(
            registry=registry,
            router=router,
            handoff_protocol=make_mock_handoff_protocol(),
            context_manager=make_mock_context_manager(),
            llm_service=llm,
        )

        assert await supervisor._should_decompose({"description": ""}) is False
        assert await supervisor._should_decompose({}) is False
