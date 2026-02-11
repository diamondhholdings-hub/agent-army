"""Supervisor orchestrator for multi-agent task coordination.

The SupervisorOrchestrator is the "conductor" of the agent system. It receives
tasks, decides which agent(s) should handle them, decomposes complex tasks into
subtasks, validates handoffs, executes agents with backup failure handling, and
synthesizes results via LLM.

Key design decisions:
- Hybrid routing: deterministic rules for known patterns, LLM for ambiguous cases
- Task decomposition: LLM breaks complex tasks into parallelizable subtasks
- Failure handling: route to backup agent (not retry same agent)
- Result synthesis: LLM combines multiple agent outputs into a coherent response
- Full call chain: maintained for traceability (["user", "supervisor", "agent_id"])
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from src.app.agents.base import BaseAgent
from src.app.agents.registry import AgentRegistry
from src.app.agents.router import HybridRouter, RoutingDecision
from src.app.context.manager import ContextManager
from src.app.handoffs.protocol import HandoffProtocol, HandoffRejectedError
from src.app.handoffs.validators import HandoffPayload
from src.app.services.llm import LLMService

logger = structlog.get_logger(__name__)


# -- Exceptions ---------------------------------------------------------------


class AgentExecutionError(Exception):
    """Raised when an agent execution fails and no backup is available.

    Attributes:
        agent_id: The agent that failed.
        original_error: The underlying exception.
        backup_tried: Whether a backup agent was attempted.
    """

    def __init__(
        self,
        agent_id: str,
        original_error: Exception,
        backup_tried: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self.original_error = original_error
        self.backup_tried = backup_tried
        backup_msg = " (backup also failed)" if backup_tried else " (no backup available)"
        super().__init__(
            f"Agent '{agent_id}' execution failed{backup_msg}: {original_error}"
        )


# -- Supervisor Orchestrator --------------------------------------------------


class SupervisorOrchestrator:
    """Coordinates specialist agents through routing, decomposition, and synthesis.

    The supervisor does not do work itself -- it coordinates specialists:
    1. Compile working context for the task
    2. Decide if the task needs decomposition (heuristic check)
    3. Simple tasks: route directly to a single agent
    4. Complex tasks: decompose into subtasks, route each, execute in
       dependency order (parallel where possible via asyncio.gather)
    5. Validate each agent's output via handoff protocol
    6. Synthesize results if multiple agents contributed
    7. Return final result with full call chain for traceability

    Args:
        registry: AgentRegistry for looking up agents.
        router: HybridRouter for task-to-agent routing.
        handoff_protocol: HandoffProtocol for validating agent outputs.
        context_manager: ContextManager for compiling working context.
        llm_service: LLMService for result synthesis.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        router: HybridRouter,
        handoff_protocol: HandoffProtocol,
        context_manager: ContextManager,
        llm_service: LLMService,
    ) -> None:
        self._registry = registry
        self._router = router
        self._handoff_protocol = handoff_protocol
        self._context_manager = context_manager
        self._llm_service = llm_service

    async def execute_task(
        self,
        task: dict[str, Any],
        tenant_id: str,
        thread_id: str,
    ) -> dict[str, Any]:
        """Execute a task through the full supervisor orchestration flow.

        This is the main entry point. Orchestrates context compilation,
        routing, agent execution, handoff validation, and result synthesis.

        Args:
            task: Task dict (should contain at least a "description" key).
            tenant_id: Tenant ID for context and isolation.
            thread_id: Conversation thread ID for session context.

        Returns:
            Result dict with:
                - result: The final output (synthesized if multiple agents)
                - call_chain: Full traceability chain
                - routed_by: How routing was decided
                - decomposed: Whether the task was decomposed
                - agent_results: Individual agent results (if decomposed)
        """
        call_chain = ["user", "supervisor"]

        logger.info(
            "supervisor_task_started",
            tenant_id=tenant_id,
            thread_id=thread_id,
            task_type=task.get("type", "unknown"),
        )

        # Step 1: Compile working context
        context = await self._context_manager.compile_working_context(
            tenant_id=tenant_id,
            thread_id=thread_id,
            task=task,
            system_prompt="You are a supervisor agent coordinating specialist agents.",
        )

        # Step 2: Check if task needs decomposition
        should_decompose = await self._should_decompose(task)

        if not should_decompose:
            # Step 3a: Simple task -- route directly
            decision = await self._router.route(task)
            result = await self._execute_agent(
                agent_id=decision.agent_id,
                task=task,
                context=context,
                call_chain=list(call_chain),
                tenant_id=tenant_id,
            )
            return {
                "result": result["output"],
                "call_chain": result["call_chain"],
                "routed_by": decision.routed_by,
                "decomposed": False,
                "agent_results": [result],
            }

        # Step 3b: Complex task -- decompose and execute subtasks
        decomposition = await self._router.decompose(task)
        routed_subtasks = await self._router.route_subtasks(decomposition.subtasks)

        # Step 4: Execute subtasks in dependency order
        agent_results = await self._execute_subtasks_in_order(
            routed_subtasks=routed_subtasks,
            context=context,
            call_chain=list(call_chain),
            tenant_id=tenant_id,
        )

        # Step 5: Synthesize results if multiple agents contributed
        if len(agent_results) > 1:
            synthesized = await self._synthesize_results(agent_results, task)
        else:
            synthesized = agent_results[0]["output"] if agent_results else {}

        # Build combined call chain
        combined_chain = list(call_chain)
        for r in agent_results:
            for agent_id in r["call_chain"]:
                if agent_id not in combined_chain:
                    combined_chain.append(agent_id)

        logger.info(
            "supervisor_task_completed",
            tenant_id=tenant_id,
            task_type=task.get("type", "unknown"),
            agent_count=len(agent_results),
            decomposed=True,
        )

        return {
            "result": synthesized,
            "call_chain": combined_chain,
            "routed_by": "llm",  # decomposition always uses LLM
            "decomposed": True,
            "agent_results": agent_results,
        }

    async def _execute_agent(
        self,
        agent_id: str,
        task: dict[str, Any],
        context: dict[str, Any],
        call_chain: list[str],
        tenant_id: str,
    ) -> dict[str, Any]:
        """Execute a single agent with backup failure handling.

        1. Get the agent from the registry
        2. Call agent.invoke(task, context)
        3. Validate output via handoff protocol
        4. On failure: try backup agent (LOCKED DECISION: route to backup, not retry)
        5. If backup also fails or no backup: raise AgentExecutionError

        Args:
            agent_id: ID of the agent to execute.
            task: Task dict for the agent.
            context: Compiled working context.
            call_chain: Current call chain for traceability.
            tenant_id: Tenant ID for handoff payload.

        Returns:
            Dict with output, call_chain, and agent_id.

        Raises:
            AgentExecutionError: If the agent (and backup) fail.
        """
        agent_chain = call_chain + [agent_id]

        # Get the agent instance from registry
        registration = self._registry.get(agent_id)
        if registration is None:
            raise AgentExecutionError(
                agent_id=agent_id,
                original_error=ValueError(f"Agent '{agent_id}' not found in registry"),
            )

        # The registry stores AgentRegistration, not agent instances.
        # For execution, we need the actual agent. The agent is expected
        # to be resolvable from the registration. In practice, a factory
        # or agent pool would provide the instance. For the supervisor,
        # we pass the task to the agent via a protocol that the concrete
        # implementations provide. Here we use a duck-typing approach:
        # the agent is expected to be set on the registration or provided
        # via a lookup. We'll use a simple attribute check.
        agent: BaseAgent | None = getattr(registration, "_agent_instance", None)

        if agent is None:
            raise AgentExecutionError(
                agent_id=agent_id,
                original_error=ValueError(
                    f"Agent '{agent_id}' registered but no instance available for execution"
                ),
            )

        try:
            output = await agent.invoke(task, context)

            # Validate the handoff from agent back to supervisor.
            # The HandoffPayload requires source_agent_id IN call_chain
            # and target_agent_id NOT in call_chain. For agent->supervisor
            # handoffs, the call_chain contains only the agent (source),
            # and the supervisor is the target (not yet in chain).
            payload = HandoffPayload(
                source_agent_id=agent_id,
                target_agent_id="supervisor",
                call_chain=[agent_id],
                tenant_id=tenant_id,
                handoff_type=task.get("handoff_type", "status_update"),
                data=output,
            )
            await self._handoff_protocol.validate_or_reject(payload)

            return {
                "output": output,
                "call_chain": agent_chain,
                "agent_id": agent_id,
            }

        except HandoffRejectedError:
            logger.warning(
                "agent_handoff_rejected",
                agent_id=agent_id,
                task_type=task.get("type", "unknown"),
            )
            raise

        except Exception as primary_error:
            logger.warning(
                "agent_execution_failed",
                agent_id=agent_id,
                error=str(primary_error),
                error_type=type(primary_error).__name__,
            )

            # Try backup agent (LOCKED DECISION)
            backup_reg = self._registry.get_backup(agent_id)
            if backup_reg is None:
                raise AgentExecutionError(
                    agent_id=agent_id,
                    original_error=primary_error,
                    backup_tried=False,
                )

            backup_agent: BaseAgent | None = getattr(
                backup_reg, "_agent_instance", None
            )
            if backup_agent is None:
                raise AgentExecutionError(
                    agent_id=agent_id,
                    original_error=primary_error,
                    backup_tried=False,
                )

            logger.info(
                "trying_backup_agent",
                original_agent=agent_id,
                backup_agent=backup_reg.agent_id,
            )

            try:
                backup_chain = call_chain + [backup_reg.agent_id]
                output = await backup_agent.invoke(task, context)

                payload = HandoffPayload(
                    source_agent_id=backup_reg.agent_id,
                    target_agent_id="supervisor",
                    call_chain=[backup_reg.agent_id],
                    tenant_id=tenant_id,
                    handoff_type=task.get("handoff_type", "status_update"),
                    data=output,
                )
                await self._handoff_protocol.validate_or_reject(payload)

                return {
                    "output": output,
                    "call_chain": backup_chain,
                    "agent_id": backup_reg.agent_id,
                }

            except Exception as backup_error:
                logger.error(
                    "backup_agent_also_failed",
                    original_agent=agent_id,
                    backup_agent=backup_reg.agent_id,
                    backup_error=str(backup_error),
                )
                raise AgentExecutionError(
                    agent_id=agent_id,
                    original_error=primary_error,
                    backup_tried=True,
                )

    async def _execute_subtasks_in_order(
        self,
        routed_subtasks: list[tuple[dict[str, Any], RoutingDecision]],
        context: dict[str, Any],
        call_chain: list[str],
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Execute subtasks respecting dependency order.

        Independent subtasks (no dependencies or all dependencies resolved)
        execute concurrently via asyncio.gather. Dependent subtasks wait
        for their prerequisites.

        Args:
            routed_subtasks: List of (subtask, routing_decision) pairs.
            context: Compiled working context.
            call_chain: Current call chain.
            tenant_id: Tenant ID for handoff payloads.

        Returns:
            List of agent result dicts.
        """
        results: list[dict[str, Any] | None] = [None] * len(routed_subtasks)
        completed: set[int] = set()

        # Build dependency graph
        deps: dict[int, list[int]] = {}
        for i, (subtask, _) in enumerate(routed_subtasks):
            deps[i] = subtask.get("depends_on", [])

        # Execute in waves until all complete
        max_iterations = len(routed_subtasks) + 1
        iteration = 0

        while len(completed) < len(routed_subtasks) and iteration < max_iterations:
            iteration += 1

            # Find ready subtasks: all dependencies completed
            ready = []
            for i in range(len(routed_subtasks)):
                if i not in completed and all(d in completed for d in deps.get(i, [])):
                    ready.append(i)

            if not ready:
                logger.error(
                    "subtask_dependency_deadlock",
                    completed=list(completed),
                    total=len(routed_subtasks),
                )
                break

            # Execute ready subtasks in parallel
            async def _exec(idx: int) -> tuple[int, dict[str, Any]]:
                subtask, decision = routed_subtasks[idx]
                result = await self._execute_agent(
                    agent_id=decision.agent_id,
                    task=subtask,
                    context=context,
                    call_chain=list(call_chain),
                    tenant_id=tenant_id,
                )
                return idx, result

            gathered = await asyncio.gather(
                *[_exec(i) for i in ready],
                return_exceptions=True,
            )

            for item in gathered:
                if isinstance(item, Exception):
                    raise item
                idx, result = item
                results[idx] = result
                completed.add(idx)

        return [r for r in results if r is not None]

    async def _synthesize_results(
        self,
        results: list[dict[str, Any]],
        original_task: dict[str, Any],
    ) -> dict[str, Any]:
        """Combine multiple agent outputs into a coherent response via LLM.

        LOCKED DECISION: LLM synthesis for combining multi-agent outputs.
        The synthesis prompt includes the original task and each agent's
        output, asking the LLM to produce a unified, non-redundant response.

        Args:
            results: List of agent result dicts (each has "output" and "agent_id").
            original_task: The original task for context.

        Returns:
            Synthesized result dict.
        """
        task_description = original_task.get("description", json.dumps(original_task))

        agent_outputs = []
        for r in results:
            agent_outputs.append({
                "agent_id": r.get("agent_id", "unknown"),
                "output": r.get("output", {}),
            })

        prompt = f"""You are a result synthesis engine. Combine these agent outputs into a single coherent response.

Original task:
{task_description}

Agent outputs:
{json.dumps(agent_outputs, indent=2, default=str)}

Instructions:
- Combine all relevant information from each agent's output
- Remove redundant or duplicate information
- Resolve any contradictions (prefer more specific/detailed information)
- Produce a unified response that directly addresses the original task
- Preserve important details from all agents

Respond with a JSON object containing the synthesized result:
{{
    "summary": "<unified response addressing the task>",
    "details": {{<merged structured data from all agents>}},
    "sources": ["<agent_ids that contributed>"]
}}"""

        response = await self._llm_service.completion(
            messages=[{"role": "user", "content": prompt}],
            model="reasoning",
            temperature=0.0,
            max_tokens=2048,
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
                # Fallback: return raw content as summary
                parsed = {
                    "summary": content,
                    "details": {},
                    "sources": [r.get("agent_id", "unknown") for r in results],
                }

        logger.info(
            "results_synthesized",
            agent_count=len(results),
            source_agents=[r.get("agent_id") for r in results],
        )

        return parsed

    async def _should_decompose(self, task: dict[str, Any]) -> bool:
        """Heuristic check for whether a task needs decomposition.

        Conservative -- when in doubt, don't decompose. Let the single
        agent handle the full task. Decomposition triggers:
        - Task description > 200 characters
        - Contains "and" joining distinct actions
        - Has explicit subtask markers (numbered list, bullets)

        Args:
            task: Task dict to evaluate.

        Returns:
            True if the task should be decomposed into subtasks.
        """
        description = task.get("description", "")

        if not description:
            return False

        # Check length threshold
        if len(description) > 200:
            # Long descriptions often contain multiple objectives
            # But also check for multiple action verbs as a secondary signal
            action_keywords = ["and then", "also ", "additionally", "after that", "next "]
            has_multiple_actions = any(kw in description.lower() for kw in action_keywords)
            if has_multiple_actions:
                return True

        # Check for explicit subtask markers
        subtask_markers = ["1.", "2.", "- ", "* ", "step 1", "step 2", "first,", "second,"]
        has_markers = sum(1 for m in subtask_markers if m in description.lower()) >= 2
        if has_markers:
            return True

        return False


# -- Factory ------------------------------------------------------------------


def create_supervisor_graph(
    registry: AgentRegistry,
    router: HybridRouter,
    handoff_protocol: HandoffProtocol,
    context_manager: ContextManager,
    llm_service: LLMService,
    checkpointer: Any = None,
) -> SupervisorOrchestrator:
    """Factory function that wires all dependencies and returns a ready-to-use supervisor.

    Args:
        registry: AgentRegistry for agent lookup.
        router: HybridRouter for task routing.
        handoff_protocol: HandoffProtocol for validating handoffs.
        context_manager: ContextManager for working context compilation.
        llm_service: LLMService for LLM calls (synthesis, routing).
        checkpointer: Optional LangGraph checkpointer (reserved for future
            graph-based execution).

    Returns:
        Configured SupervisorOrchestrator instance.
    """
    supervisor = SupervisorOrchestrator(
        registry=registry,
        router=router,
        handoff_protocol=handoff_protocol,
        context_manager=context_manager,
        llm_service=llm_service,
    )

    logger.info(
        "supervisor_graph_created",
        agent_count=len(registry),
        has_checkpointer=checkpointer is not None,
    )

    return supervisor
