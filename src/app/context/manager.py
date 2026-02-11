"""Context manager orchestrating all three context tiers.

Provides a single entry point for compiling working context from:
1. Session state (LangGraph checkpointer)
2. Long-term memory (pgvector semantic search)
3. Working context compilation (token-budgeted assembly)

Also exposes convenience methods for storing and searching memories.
"""

from __future__ import annotations

import structlog

from src.app.context.memory import LongTermMemory, MemoryEntry
from src.app.context.session import SessionStore
from src.app.context.working import WorkingContextCompiler

logger = structlog.get_logger(__name__)


class ContextManager:
    """Orchestrates all three context tiers into a single interface.

    The ContextManager is the primary entry point for context operations:
    - Compile working context (pulls from session + memory + task)
    - Store new memories
    - Search existing memories
    - Access the session store for LangGraph checkpointer

    Usage:
        manager = ContextManager(session_store, memory, compiler)
        context = await manager.compile_working_context(
            tenant_id="t1",
            thread_id="thread-123",
            task={"type": "deal_analysis", "description": "Analyze deal"},
            system_prompt="You are a sales agent...",
        )
    """

    def __init__(
        self,
        session_store: SessionStore,
        memory: LongTermMemory,
        compiler: WorkingContextCompiler,
    ) -> None:
        """Initialize the context manager.

        Args:
            session_store: SessionStore for session state persistence.
            memory: LongTermMemory for semantic search over memories.
            compiler: WorkingContextCompiler for token-budgeted assembly.
        """
        self._session_store = session_store
        self._memory = memory
        self._compiler = compiler

    async def compile_working_context(
        self,
        tenant_id: str,
        thread_id: str,
        task: dict,
        system_prompt: str,
        model_tier: str = "reasoning",
    ) -> dict:
        """Compile working context from all three tiers.

        Step 1: Get session messages from the checkpointer.
        Step 2: Search long-term memory for relevant facts.
        Step 3: Compile everything within the token budget.

        Args:
            tenant_id: The tenant scope for memory search.
            thread_id: The conversation thread for session state.
            task: Task data dict (should contain 'description' key).
            system_prompt: The agent's system instructions.
            model_tier: Token budget tier ("fast" or "reasoning").

        Returns:
            Compiled working context dict with system_prompt, messages,
            context (memories), task, and token_usage.
        """
        # Step 1: Get session history
        session_messages = await self._session_store.get_session_messages(
            thread_id
        )

        # Step 2: Search relevant memories using task description
        query = task.get("description", "")
        memories: list[MemoryEntry] = []
        if query:
            memories = await self._memory.search(
                tenant_id=tenant_id, query=query, limit=10
            )

        # Step 3: Compile working context with token budget
        # Use a tier-specific compiler if the tier differs
        compiler = self._compiler
        if model_tier != compiler._model_tier:
            compiler = WorkingContextCompiler(model_tier)

        result = await compiler.compile(
            system_prompt=system_prompt,
            session_messages=session_messages,
            relevant_memories=[m.content for m in memories],
            task=task,
        )

        logger.info(
            "context_manager.compiled",
            tenant_id=tenant_id,
            thread_id=thread_id,
            session_messages=len(session_messages),
            memories_found=len(memories),
            total_tokens=result["token_usage"]["total"],
        )

        return result

    async def store_memory(
        self,
        tenant_id: str,
        agent_id: str,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        """Store a new long-term memory.

        Creates a MemoryEntry and stores it with an embedding for
        future semantic search.

        Args:
            tenant_id: The tenant this memory belongs to.
            agent_id: The agent that learned this fact.
            content: The factual content to store.
            metadata: Optional metadata (source, deal_id, etc.).

        Returns:
            The memory_id of the stored entry.
        """
        entry = MemoryEntry(
            tenant_id=tenant_id,
            agent_id=agent_id,
            content=content,
            metadata=metadata or {},
        )
        memory_id = await self._memory.store(entry)
        logger.info(
            "context_manager.memory_stored",
            memory_id=memory_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        return memory_id

    async def search_memory(
        self, tenant_id: str, query: str, limit: int = 10
    ) -> list[MemoryEntry]:
        """Search long-term memories by semantic similarity.

        Args:
            tenant_id: The tenant scope.
            query: The search query.
            limit: Maximum results.

        Returns:
            List of MemoryEntry objects ordered by relevance.
        """
        return await self._memory.search(
            tenant_id=tenant_id, query=query, limit=limit
        )

    @property
    def session(self) -> SessionStore:
        """Access the session store (e.g., for LangGraph checkpointer).

        Returns:
            The underlying SessionStore instance.
        """
        return self._session_store
