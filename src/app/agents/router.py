"""Hybrid routing with deterministic rules and LLM fallback.

The HybridRouter implements a two-phase routing strategy:
1. Rules-based (fast, confident): Iterate registered matcher functions in order.
   First match wins with confidence=1.0.
2. LLM-based (flexible, for ambiguous cases): Construct a prompt with available
   agents from the registry and ask the LLM to select the best agent.

Also provides task decomposition via LLM for complex multi-step tasks, breaking
them into subtasks with capability requirements and dependency ordering.

The router queries the AgentRegistry for available agents and their capabilities,
bridging the gap between task descriptions and agent selection.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import structlog
from pydantic import BaseModel, Field

from src.app.agents.registry import AgentRegistry
from src.app.services.llm import LLMService

logger = structlog.get_logger(__name__)


# -- Routing Models -----------------------------------------------------------


class RoutingDecision(BaseModel):
    """Result of routing a task to an agent.

    Attributes:
        agent_id: Which agent to route the task to.
        reasoning: Why this agent was chosen (for traceability and debugging).
        subtasks: Decomposed subtasks if the router detected a multi-step task.
        confidence: Routing confidence (1.0 for rules, variable for LLM).
        routed_by: Which routing method was used ("rules" or "llm").
    """

    agent_id: str
    reasoning: str
    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    routed_by: str = "rules"


class TaskDecomposition(BaseModel):
    """Result of decomposing a complex task into subtasks.

    Attributes:
        original_task: The original task that was decomposed.
        subtasks: List of subtask dicts, each with description,
            required_capabilities, priority, and depends_on.
        decomposed_by: Which method performed decomposition (always "llm").
    """

    original_task: dict[str, Any]
    subtasks: list[dict[str, Any]]
    decomposed_by: str = "llm"


# -- Hybrid Router ------------------------------------------------------------


class HybridRouter:
    """Two-phase router: deterministic rules first, LLM fallback second.

    Rules are registered as (matcher_function, agent_id) pairs. The matcher
    receives a task dict and returns True if the associated agent should handle
    it. Rules are evaluated in registration order; first match wins.

    If no rule matches, the router constructs an LLM prompt listing all
    available agents (from the registry) and asks the LLM to select the best
    agent. The LLM response is parsed into a RoutingDecision.

    Args:
        registry: AgentRegistry for looking up available agents.
        llm_service: LLMService for LLM-based routing and decomposition.
    """

    def __init__(self, registry: AgentRegistry, llm_service: LLMService) -> None:
        self._registry = registry
        self._llm_service = llm_service
        self._rules: list[tuple[Callable[[dict[str, Any]], bool], str]] = []

    def add_rule(self, matcher: Callable[[dict[str, Any]], bool], agent_id: str) -> None:
        """Register a deterministic routing rule.

        Rules are evaluated in registration order during route(). The first
        matcher that returns True wins.

        Args:
            matcher: Function that receives a task dict and returns True if
                the associated agent should handle it.
            agent_id: ID of the agent to route to when matcher returns True.
        """
        self._rules.append((matcher, agent_id))
        logger.info("routing_rule_added", agent_id=agent_id, rule_count=len(self._rules))

    def remove_rule(self, agent_id: str) -> None:
        """Remove all routing rules for a given agent_id.

        Args:
            agent_id: The agent ID whose rules should be removed.
        """
        before = len(self._rules)
        self._rules = [(m, aid) for m, aid in self._rules if aid != agent_id]
        removed = before - len(self._rules)
        logger.info("routing_rules_removed", agent_id=agent_id, removed=removed)

    async def route(self, task: dict[str, Any]) -> RoutingDecision:
        """Route a task to the best agent.

        Phase 1 (Rules): Iterate registered rules in order. First matcher
        that returns True produces a RoutingDecision with confidence=1.0
        and routed_by="rules".

        Phase 2 (LLM): If no rule matches, construct a prompt with the task
        description and all available agents from the registry. Use the LLM
        (model="fast", temperature=0.0) to select the best agent. Parse the
        structured response into a RoutingDecision with routed_by="llm".

        Args:
            task: Task dict (should contain at least a "description" key).

        Returns:
            RoutingDecision indicating which agent should handle the task.

        Raises:
            ValueError: If the LLM returns an unrecognizable response or
                references an unknown agent.
        """
        # Phase 1: Rules-based routing
        for matcher, agent_id in self._rules:
            try:
                if matcher(task):
                    decision = RoutingDecision(
                        agent_id=agent_id,
                        reasoning=f"Matched deterministic rule for agent '{agent_id}'",
                        confidence=1.0,
                        routed_by="rules",
                    )
                    logger.info(
                        "task_routed",
                        task_type=task.get("type", "unknown"),
                        agent_id=agent_id,
                        routed_by="rules",
                        confidence=1.0,
                    )
                    return decision
            except Exception as exc:
                logger.warning(
                    "routing_rule_error",
                    agent_id=agent_id,
                    error=str(exc),
                )
                continue

        # Phase 2: LLM-based routing
        return await self._llm_route(task)

    async def _llm_route(self, task: dict[str, Any]) -> RoutingDecision:
        """Route a task using the LLM when no deterministic rule matched.

        Constructs a prompt with available agents and their capabilities,
        then asks the LLM to select the best agent and explain why.

        Args:
            task: Task dict to route.

        Returns:
            RoutingDecision from LLM analysis.
        """
        available_agents = self._registry.list_agents()
        agent_ids = {a["id"] for a in available_agents}

        if not available_agents:
            raise ValueError("No agents registered -- cannot route task")

        agents_description = json.dumps(available_agents, indent=2)
        task_description = task.get("description", json.dumps(task))

        prompt = f"""You are a task router. Select the best agent to handle this task.

Available agents:
{agents_description}

Task to route:
{task_description}

Respond with ONLY a JSON object (no markdown, no explanation outside the JSON):
{{
    "agent_id": "<id of the best agent>",
    "reasoning": "<brief explanation of why this agent was chosen>",
    "confidence": <float between 0.0 and 1.0>
}}"""

        response = await self._llm_service.completion(
            messages=[{"role": "user", "content": prompt}],
            model="fast",
            temperature=0.0,
            max_tokens=256,
        )

        content = response.get("content", "").strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from the response
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(content[start:end])
            else:
                raise ValueError(f"LLM returned non-JSON routing response: {content[:200]}")

        chosen_id = parsed.get("agent_id", "")
        if chosen_id not in agent_ids:
            # Fall back to first available agent with a warning
            fallback_id = available_agents[0]["id"]
            logger.warning(
                "llm_routed_to_unknown_agent",
                chosen_id=chosen_id,
                fallback_id=fallback_id,
                available=list(agent_ids),
            )
            chosen_id = fallback_id

        decision = RoutingDecision(
            agent_id=chosen_id,
            reasoning=parsed.get("reasoning", "LLM routing (no reasoning provided)"),
            confidence=min(1.0, max(0.0, float(parsed.get("confidence", 0.7)))),
            routed_by="llm",
        )

        logger.info(
            "task_routed",
            task_type=task.get("type", "unknown"),
            agent_id=decision.agent_id,
            routed_by="llm",
            confidence=decision.confidence,
        )

        return decision

    async def decompose(self, task: dict[str, Any]) -> TaskDecomposition:
        """Decompose a complex task into subtasks using the LLM.

        Uses the "reasoning" model for deeper analysis of task structure.
        Each subtask includes a description, required capabilities,
        priority (1=highest), and dependency list.

        Args:
            task: Task dict to decompose.

        Returns:
            TaskDecomposition with the original task and subtask list.
        """
        task_description = task.get("description", json.dumps(task))

        available_agents = self._registry.list_agents()
        capabilities_list = set()
        for agent in available_agents:
            for cap in agent.get("capabilities", []):
                capabilities_list.add(cap)

        prompt = f"""You are a task decomposition engine. Break this task into smaller subtasks.

Task:
{task_description}

Known capabilities in the system: {json.dumps(sorted(capabilities_list))}

Respond with ONLY a JSON object (no markdown, no explanation outside the JSON):
{{
    "subtasks": [
        {{
            "description": "<what this subtask does>",
            "required_capabilities": ["<capability_name>"],
            "priority": 1,
            "depends_on": []
        }}
    ]
}}

Rules:
- Each subtask should be independently executable by a single agent
- priority: 1 = highest priority, higher numbers = lower priority
- depends_on: list of subtask indices (0-based) that must complete first
- required_capabilities: list of capability names needed (from known capabilities if possible)
- Produce 2-5 subtasks (no more)"""

        response = await self._llm_service.completion(
            messages=[{"role": "user", "content": prompt}],
            model="reasoning",
            temperature=0.0,
            max_tokens=1024,
        )

        content = response.get("content", "").strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(content[start:end])
            else:
                raise ValueError(f"LLM returned non-JSON decomposition response: {content[:200]}")

        subtasks = parsed.get("subtasks", [])

        # Validate subtask structure
        validated_subtasks = []
        for i, st in enumerate(subtasks):
            validated_subtasks.append({
                "description": st.get("description", f"Subtask {i}"),
                "required_capabilities": st.get("required_capabilities", []),
                "priority": st.get("priority", i + 1),
                "depends_on": st.get("depends_on", []),
            })

        logger.info(
            "task_decomposed",
            original_task_type=task.get("type", "unknown"),
            subtask_count=len(validated_subtasks),
        )

        return TaskDecomposition(
            original_task=task,
            subtasks=validated_subtasks,
            decomposed_by="llm",
        )

    async def route_subtasks(
        self, subtasks: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], RoutingDecision]]:
        """Route each subtask independently via self.route().

        Args:
            subtasks: List of subtask dicts to route.

        Returns:
            List of (subtask, routing_decision) pairs.
        """
        results = []
        for subtask in subtasks:
            decision = await self.route(subtask)
            results.append((subtask, decision))
        return results
