"""Agent registry for discovery, routing, and backup agent resolution.

The AgentRegistry is the central directory of all registered agents. It
supports:
- Registration and unregistration of agents
- Discovery by capability name or tag
- Backup agent resolution for failure routing (locked decision: route to
  backup agent with similar capabilities instead of retrying the same agent)
- Serializable agent listing for LLM routing context

A module-level singleton is provided via get_agent_registry() for
application-wide access.
"""

from __future__ import annotations

import structlog

from src.app.agents.base import AgentRegistration

logger = structlog.get_logger(__name__)


class AgentRegistry:
    """Registry for discovering and managing agents.

    Stores AgentRegistration instances and provides lookup by ID, capability,
    tag, and backup chain. The list_agents() method returns LLM-friendly
    routing info suitable for inclusion in supervisor prompts.

    Thread safety note: This registry is designed for use in an async
    single-threaded event loop (FastAPI/uvicorn). If concurrent mutation
    is needed, external synchronization should be added.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentRegistration] = {}

    def register(self, registration: AgentRegistration) -> None:
        """Register an agent in the registry.

        Args:
            registration: The agent's registration metadata.

        Raises:
            ValueError: If an agent with the same agent_id is already registered.
        """
        if registration.agent_id in self._agents:
            raise ValueError(
                f"Agent already registered: {registration.agent_id}"
            )
        self._agents[registration.agent_id] = registration
        logger.info(
            "agent_registered",
            agent_id=registration.agent_id,
            agent_name=registration.name,
            capabilities=[c.name for c in registration.capabilities],
            backup_agent_id=registration.backup_agent_id,
        )

    def unregister(self, agent_id: str) -> None:
        """Remove an agent from the registry.

        Args:
            agent_id: The unique identifier of the agent to remove.

        Raises:
            KeyError: If no agent with the given ID is registered.
        """
        if agent_id not in self._agents:
            raise KeyError(f"Agent not registered: {agent_id}")
        del self._agents[agent_id]
        logger.info("agent_unregistered", agent_id=agent_id)

    def get(self, agent_id: str) -> AgentRegistration | None:
        """Get an agent's registration by ID.

        Args:
            agent_id: The unique identifier of the agent.

        Returns:
            The AgentRegistration if found, None otherwise.
        """
        return self._agents.get(agent_id)

    def get_backup(self, agent_id: str) -> AgentRegistration | None:
        """Get the backup agent for failure routing.

        Implements the locked decision: on agent failure, route to the
        configured backup agent with similar capabilities rather than
        retrying the same agent. Returns None if:
        - The agent is not registered
        - The agent has no backup_agent_id configured
        - The backup agent is not registered

        Args:
            agent_id: The ID of the agent whose backup is needed.

        Returns:
            The backup agent's registration, or None.
        """
        agent = self._agents.get(agent_id)
        if agent is None or agent.backup_agent_id is None:
            return None
        return self._agents.get(agent.backup_agent_id)

    def find_by_capability(self, capability_name: str) -> list[AgentRegistration]:
        """Find all agents that have a specific capability.

        Args:
            capability_name: The capability name to search for.

        Returns:
            List of registrations for agents with the matching capability.
        """
        return [
            agent
            for agent in self._agents.values()
            if any(c.name == capability_name for c in agent.capabilities)
        ]

    def find_by_tag(self, tag: str) -> list[AgentRegistration]:
        """Find all agents that have a specific tag.

        Args:
            tag: The tag to search for.

        Returns:
            List of registrations for agents with the matching tag.
        """
        return [
            agent
            for agent in self._agents.values()
            if tag in agent.tags
        ]

    def list_agents(self) -> list[dict]:
        """List all registered agents with routing info.

        Returns a list of dictionaries suitable for inclusion in LLM
        routing prompts. Each dict contains the agent's id, name,
        description, and list of capability names.

        Returns:
            List of routing info dictionaries.
        """
        return [
            {
                "id": a.agent_id,
                "name": a.name,
                "description": a.description,
                "capabilities": [c.name for c in a.capabilities],
            }
            for a in self._agents.values()
        ]

    def list_agent_ids(self) -> list[str]:
        """Return all registered agent IDs.

        Returns:
            List of agent ID strings.
        """
        return list(self._agents.keys())

    def __len__(self) -> int:
        """Return the number of registered agents."""
        return len(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        """Check if an agent is registered."""
        return agent_id in self._agents


# ── Module-level singleton ───────────────────────────────────────────────────

_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    """Get the global AgentRegistry singleton.

    Creates the registry on first call. Subsequent calls return the same
    instance.

    Returns:
        The global AgentRegistry instance.
    """
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
