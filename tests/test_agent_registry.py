"""Tests for agent registry, discovery, backup routing, and base agent abstractions.

Covers:
- Agent registration and unregistration
- Duplicate registration rejection
- Discovery by capability and tag
- Backup agent routing (locked decision: route to backup on failure)
- LLM-friendly agent listing
- BaseAgent invoke() status lifecycle
- AgentRegistration defaults and edge cases
"""

from __future__ import annotations

from typing import Any

import pytest

from src.app.agents.base import (
    AgentCapability,
    AgentRegistration,
    AgentStatus,
    BaseAgent,
)
from src.app.agents.registry import AgentRegistry


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_cap(name: str, description: str = "test capability") -> AgentCapability:
    """Create a test capability."""
    return AgentCapability(name=name, description=description)


def _make_reg(
    agent_id: str,
    capabilities: list[str] | None = None,
    backup_agent_id: str | None = None,
    tags: list[str] | None = None,
) -> AgentRegistration:
    """Create a test registration with sensible defaults."""
    caps = [_make_cap(c) for c in (capabilities or ["default"])]
    return AgentRegistration(
        agent_id=agent_id,
        name=f"{agent_id.replace('_', ' ').title()}",
        description=f"Test agent: {agent_id}",
        capabilities=caps,
        backup_agent_id=backup_agent_id,
        tags=tags or [],
    )


class StubAgent(BaseAgent):
    """Concrete agent for testing BaseAgent lifecycle."""

    def __init__(self, registration: AgentRegistration, result: dict | None = None, error: Exception | None = None):
        super().__init__(registration)
        self._result = result or {"status": "ok"}
        self._error = error

    async def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if self._error:
            raise self._error
        return self._result


# ── Registration Tests ───────────────────────────────────────────────────────


def test_register_agent():
    """Register an agent and verify it is in the registry."""
    registry = AgentRegistry()
    reg = _make_reg("research_agent", capabilities=["research"])
    registry.register(reg)
    assert "research_agent" in registry
    assert len(registry) == 1


def test_register_duplicate_raises():
    """Registering the same agent_id twice raises ValueError."""
    registry = AgentRegistry()
    reg = _make_reg("research_agent")
    registry.register(reg)
    with pytest.raises(ValueError, match="Agent already registered: research_agent"):
        registry.register(reg)


def test_unregister_agent():
    """Register then unregister an agent; verify it is gone."""
    registry = AgentRegistry()
    reg = _make_reg("research_agent")
    registry.register(reg)
    assert "research_agent" in registry

    registry.unregister("research_agent")
    assert "research_agent" not in registry
    assert len(registry) == 0


def test_unregister_nonexistent_raises():
    """Unregistering a non-existent agent raises KeyError."""
    registry = AgentRegistry()
    with pytest.raises(KeyError, match="Agent not registered: ghost"):
        registry.unregister("ghost")


# ── Get / Lookup Tests ───────────────────────────────────────────────────────


def test_get_agent():
    """Register and retrieve an agent by ID."""
    registry = AgentRegistry()
    reg = _make_reg("research_agent", capabilities=["research"])
    registry.register(reg)
    result = registry.get("research_agent")
    assert result is reg
    assert result.agent_id == "research_agent"


def test_get_nonexistent_returns_none():
    """Getting an unregistered agent returns None."""
    registry = AgentRegistry()
    assert registry.get("nonexistent") is None


# ── Backup Agent Routing Tests ───────────────────────────────────────────────


def test_get_backup_agent():
    """Agent A has backup_agent_id='B', register B, get_backup('A') returns B."""
    registry = AgentRegistry()
    agent_b = _make_reg("agent_b", capabilities=["research"])
    agent_a = _make_reg("agent_a", capabilities=["research"], backup_agent_id="agent_b")

    registry.register(agent_a)
    registry.register(agent_b)

    backup = registry.get_backup("agent_a")
    assert backup is agent_b
    assert backup.agent_id == "agent_b"


def test_get_backup_no_backup_configured():
    """Agent without backup_agent_id returns None from get_backup."""
    registry = AgentRegistry()
    reg = _make_reg("agent_no_backup")
    registry.register(reg)
    assert registry.get_backup("agent_no_backup") is None


def test_get_backup_backup_not_registered():
    """Agent with backup_agent_id pointing to unregistered agent returns None."""
    registry = AgentRegistry()
    reg = _make_reg("agent_a", backup_agent_id="agent_ghost")
    registry.register(reg)
    # agent_ghost is not registered
    assert registry.get_backup("agent_a") is None


def test_get_backup_agent_not_registered():
    """get_backup for an unregistered agent returns None."""
    registry = AgentRegistry()
    assert registry.get_backup("nonexistent") is None


# ── Discovery Tests ──────────────────────────────────────────────────────────


def test_find_by_capability():
    """Find agents by capability name -- returns only matching agents."""
    registry = AgentRegistry()
    registry.register(_make_reg("researcher", capabilities=["research", "analysis"]))
    registry.register(_make_reg("writer", capabilities=["writing", "editing"]))
    registry.register(_make_reg("analyst", capabilities=["analysis", "reporting"]))

    research_agents = registry.find_by_capability("research")
    assert len(research_agents) == 1
    assert research_agents[0].agent_id == "researcher"

    analysis_agents = registry.find_by_capability("analysis")
    assert len(analysis_agents) == 2
    agent_ids = {a.agent_id for a in analysis_agents}
    assert agent_ids == {"researcher", "analyst"}

    # No agents have this capability
    assert registry.find_by_capability("nonexistent") == []


def test_find_by_tag():
    """Find agents by tag -- returns only matching agents."""
    registry = AgentRegistry()
    registry.register(_make_reg("researcher", tags=["sales", "research"]))
    registry.register(_make_reg("writer", tags=["sales", "content"]))
    registry.register(_make_reg("ops_agent", tags=["operations"]))

    sales_agents = registry.find_by_tag("sales")
    assert len(sales_agents) == 2
    agent_ids = {a.agent_id for a in sales_agents}
    assert agent_ids == {"researcher", "writer"}

    # No agents have this tag
    assert registry.find_by_tag("nonexistent") == []


# ── Listing Tests ────────────────────────────────────────────────────────────


def test_list_agents():
    """list_agents returns all agents with correct routing info structure."""
    registry = AgentRegistry()
    registry.register(_make_reg("research_agent", capabilities=["research", "analysis"]))
    registry.register(_make_reg("writing_agent", capabilities=["writing"]))

    agents = registry.list_agents()
    assert len(agents) == 2

    # Check structure of each entry
    for agent_info in agents:
        assert "id" in agent_info
        assert "name" in agent_info
        assert "description" in agent_info
        assert "capabilities" in agent_info
        assert isinstance(agent_info["capabilities"], list)

    # Verify specific agent data
    research_info = next(a for a in agents if a["id"] == "research_agent")
    assert set(research_info["capabilities"]) == {"research", "analysis"}


def test_list_agent_ids():
    """list_agent_ids returns all registered agent IDs."""
    registry = AgentRegistry()
    registry.register(_make_reg("agent_a"))
    registry.register(_make_reg("agent_b"))
    registry.register(_make_reg("agent_c"))

    ids = registry.list_agent_ids()
    assert set(ids) == {"agent_a", "agent_b", "agent_c"}


# ── Dunder Method Tests ──────────────────────────────────────────────────────


def test_len_and_contains():
    """Test __len__ and __contains__ dunder methods."""
    registry = AgentRegistry()
    assert len(registry) == 0
    assert "agent_a" not in registry

    registry.register(_make_reg("agent_a"))
    assert len(registry) == 1
    assert "agent_a" in registry
    assert "agent_b" not in registry

    registry.register(_make_reg("agent_b"))
    assert len(registry) == 2
    assert "agent_b" in registry


# ── BaseAgent Lifecycle Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_base_agent_invoke_success():
    """invoke() transitions IDLE -> BUSY -> IDLE on success."""
    reg = _make_reg("test_agent")
    agent = StubAgent(reg, result={"answer": 42})

    assert agent.status == AgentStatus.IDLE

    result = await agent.invoke({"question": "meaning"}, {})

    assert result == {"answer": 42}
    assert agent.status == AgentStatus.IDLE


@pytest.mark.asyncio
async def test_base_agent_invoke_error():
    """invoke() transitions IDLE -> BUSY -> ERROR on exception."""
    reg = _make_reg("failing_agent")
    agent = StubAgent(reg, error=RuntimeError("boom"))

    assert agent.status == AgentStatus.IDLE

    with pytest.raises(RuntimeError, match="boom"):
        await agent.invoke({"task": "fail"}, {})

    assert agent.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_base_agent_to_routing_info():
    """to_routing_info() returns correct structure with current status."""
    reg = _make_reg("research_agent", capabilities=["research", "analysis"])
    agent = StubAgent(reg)

    info = agent.to_routing_info()
    assert info["id"] == "research_agent"
    assert info["name"] == "Research Agent"
    assert info["description"] == "Test agent: research_agent"
    assert set(info["capabilities"]) == {"research", "analysis"}
    assert info["status"] == "idle"


@pytest.mark.asyncio
async def test_base_agent_properties():
    """agent_id and capabilities properties are shortcuts to registration."""
    reg = _make_reg("test_agent", capabilities=["cap_a", "cap_b"])
    agent = StubAgent(reg)

    assert agent.agent_id == "test_agent"
    assert len(agent.capabilities) == 2
    assert agent.capabilities[0].name == "cap_a"


# ── AgentRegistration Defaults Test ──────────────────────────────────────────


def test_agent_registration_defaults():
    """AgentRegistration has correct defaults for optional fields."""
    cap = _make_cap("test")
    reg = AgentRegistration(
        agent_id="minimal",
        name="Minimal Agent",
        description="Bare minimum",
        capabilities=[cap],
    )
    assert reg.backup_agent_id is None
    assert reg.tags == []
    assert reg.max_concurrent_tasks == 5


# ── Singleton Test ───────────────────────────────────────────────────────────


def test_get_agent_registry_singleton():
    """get_agent_registry returns the same instance on repeated calls."""
    from src.app.agents.registry import get_agent_registry, _registry

    # Reset singleton for isolated test
    import src.app.agents.registry as registry_module
    registry_module._registry = None

    r1 = get_agent_registry()
    r2 = get_agent_registry()
    assert r1 is r2

    # Cleanup
    registry_module._registry = None
