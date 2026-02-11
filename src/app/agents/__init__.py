"""Agent orchestration package.

Provides the base agent abstractions, registry, hybrid router, and supervisor
for multi-agent coordination. Agents register with typed capabilities and can
be discovered by capability name, tag, or agent ID. Backup agent routing
enables failure handling without retrying the same agent.

Exports:
    BaseAgent: Abstract base class for all agent implementations.
    AgentCapability: Typed capability declaration for an agent.
    AgentRegistration: Metadata describing a registered agent.
    AgentStatus: Runtime status enum (IDLE, BUSY, ERROR, OFFLINE).
    AgentRegistry: Registry for agent discovery and routing.
    get_agent_registry: Singleton accessor for the global registry.
    HybridRouter: Two-phase router with rules and LLM fallback.
    RoutingDecision: Result model for routing decisions.
    SupervisorOrchestrator: Coordinator for multi-agent task execution.
    create_supervisor_graph: Factory for wiring supervisor dependencies.
"""

from __future__ import annotations

from src.app.agents.base import (
    AgentCapability,
    AgentRegistration,
    AgentStatus,
    BaseAgent,
)
from src.app.agents.registry import AgentRegistry, get_agent_registry
from src.app.agents.router import HybridRouter, RoutingDecision
from src.app.agents.supervisor import SupervisorOrchestrator, create_supervisor_graph

__all__ = [
    "AgentCapability",
    "AgentRegistration",
    "AgentRegistry",
    "AgentStatus",
    "BaseAgent",
    "HybridRouter",
    "RoutingDecision",
    "SupervisorOrchestrator",
    "create_supervisor_graph",
    "get_agent_registry",
]
