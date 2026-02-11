"""Base agent abstractions for the multi-agent orchestration system.

Defines the foundational types for agent registration, capability declaration,
and the abstract base class that all agents must implement. The BaseAgent
provides status tracking, structured logging, and an invoke() wrapper that
handles the IDLE -> BUSY -> IDLE/ERROR lifecycle.

These types are consumed by the AgentRegistry (registry.py) for discovery,
routing, and backup agent resolution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


# ── Agent Status ─────────────────────────────────────────────────────────────


class AgentStatus(str, Enum):
    """Runtime status of an agent instance."""

    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    OFFLINE = "offline"


# ── Agent Capability ─────────────────────────────────────────────────────────


@dataclass
class AgentCapability:
    """A typed capability that an agent can perform.

    Capabilities are the primary unit of discovery -- the supervisor finds
    agents by matching task requirements to capability names. The description
    is included in LLM routing context so the model can reason about which
    agent is best suited for a task.

    Attributes:
        name: Machine-readable capability identifier (e.g., "research", "crm_lookup").
        description: Human-readable description used by the LLM router for
            capability matching.
        input_schema: Optional Pydantic model defining expected input structure.
        output_schema: Optional Pydantic model defining expected output structure.
    """

    name: str
    description: str
    input_schema: type[BaseModel] | None = None
    output_schema: type[BaseModel] | None = None


# ── Agent Registration ───────────────────────────────────────────────────────


@dataclass
class AgentRegistration:
    """Metadata describing a registered agent.

    Stored in the AgentRegistry and used for discovery, routing, and backup
    agent resolution. The backup_agent_id field implements the locked decision
    to route to a backup agent with similar capabilities on failure (rather
    than retrying the same agent).

    Attributes:
        agent_id: Unique identifier (e.g., "research_agent").
        name: Human-readable name (e.g., "Research Agent").
        description: What this agent does -- included in LLM routing context.
        capabilities: List of capabilities this agent provides.
        backup_agent_id: ID of the agent to route to on failure. None if no
            backup is configured.
        tags: Searchable labels (e.g., ["sales", "research"]).
        max_concurrent_tasks: Maximum number of tasks this agent can handle
            simultaneously.
    """

    agent_id: str
    name: str
    description: str
    capabilities: list[AgentCapability]
    backup_agent_id: str | None = None
    tags: list[str] = field(default_factory=list)
    max_concurrent_tasks: int = 5


# ── Base Agent ───────────────────────────────────────────────────────────────


class BaseAgent(ABC):
    """Abstract base class for all agents in the orchestration system.

    Provides a consistent interface with:
    - Status lifecycle tracking (IDLE -> BUSY -> IDLE/ERROR)
    - Structured logging bound to agent_id
    - invoke() wrapper that handles status transitions and error capture
    - to_routing_info() for LLM routing context serialization

    Subclasses must implement execute() with their domain-specific logic.
    External callers should use invoke() which wraps execute() with status
    tracking and error handling.
    """

    def __init__(self, registration: AgentRegistration) -> None:
        self.registration = registration
        self.status: AgentStatus = AgentStatus.IDLE
        self._logger = structlog.get_logger(__name__).bind(
            agent_id=registration.agent_id,
            agent_name=registration.name,
        )

    @property
    def agent_id(self) -> str:
        """Shortcut to the agent's unique identifier."""
        return self.registration.agent_id

    @property
    def capabilities(self) -> list[AgentCapability]:
        """Shortcut to the agent's declared capabilities."""
        return self.registration.capabilities

    @abstractmethod
    async def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Execute a task with the given context.

        This is the core method that subclasses implement with their
        domain-specific logic. It should NOT manage status transitions --
        that is handled by invoke().

        Args:
            task: Task specification (structure varies by agent type).
            context: Execution context including tenant info, session data, etc.

        Returns:
            Result dictionary with agent-specific output.
        """
        ...

    async def invoke(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Invoke the agent with status tracking, logging, and error handling.

        Wraps execute() with the IDLE -> BUSY -> IDLE/ERROR lifecycle:
        1. Sets status to BUSY and logs task start
        2. Calls execute() with the provided task and context
        3. On success: resets status to IDLE and returns result
        4. On failure: sets status to ERROR, logs the exception, and re-raises

        Args:
            task: Task specification passed through to execute().
            context: Execution context passed through to execute().

        Returns:
            Result dictionary from execute().

        Raises:
            Exception: Any exception raised by execute() is re-raised after
                status is set to ERROR.
        """
        self._logger.info("agent_task_started", task_keys=list(task.keys()))
        self.status = AgentStatus.BUSY

        try:
            result = await self.execute(task, context)
            self.status = AgentStatus.IDLE
            self._logger.info("agent_task_completed", task_keys=list(task.keys()))
            return result
        except Exception as exc:
            self.status = AgentStatus.ERROR
            self._logger.error(
                "agent_task_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise

    def to_routing_info(self) -> dict[str, Any]:
        """Serialize agent metadata for LLM routing context.

        Returns a dictionary suitable for inclusion in supervisor prompts
        so the LLM can reason about which agent to route a task to.

        Returns:
            Dict with id, name, description, capabilities list, and status.
        """
        return {
            "id": self.agent_id,
            "name": self.registration.name,
            "description": self.registration.description,
            "capabilities": [cap.name for cap in self.capabilities],
            "status": self.status.value,
        }
