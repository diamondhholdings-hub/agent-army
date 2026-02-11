"""Working context compiler with token budget enforcement.

Compiles a per-invocation working context from system prompt, session
history, retrieved memories, and task data. Each section is allocated a
percentage of the total token budget, and content is truncated to fit.

Budget allocation (from research recommendation):
- 15% system prompt
- 35% session history (most recent messages preserved)
- 35% relevant context (memories, highest relevance preserved)
- 15% task data + response buffer
"""

from __future__ import annotations

import json

import structlog
import tiktoken

logger = structlog.get_logger(__name__)


class WorkingContextCompiler:
    """Token-budgeted working context compiler.

    Compiles working context for each agent invocation by assembling
    system prompt, session history, retrieved memories, and task data
    within a strict token budget. Uses tiktoken for accurate counting.

    Usage:
        compiler = WorkingContextCompiler("reasoning")  # 32k budget
        result = await compiler.compile(
            system_prompt="You are a sales agent...",
            session_messages=[{"role": "user", "content": "Hello"}],
            relevant_memories=["Customer Acme has $500k budget"],
            task={"type": "deal_analysis", "description": "Analyze deal"},
        )
        print(result["token_usage"])
    """

    TOKEN_BUDGETS: dict[str, int] = {
        "fast": 8_000,       # Haiku-class models
        "reasoning": 32_000,  # Sonnet/GPT-4o-class models
    }

    BUDGET_ALLOCATION: dict[str, float] = {
        "system_prompt": 0.15,       # 15%
        "session_history": 0.35,     # 35%
        "relevant_context": 0.35,    # 35%
        "task_and_buffer": 0.15,     # 15%
    }

    def __init__(self, model_tier: str = "reasoning") -> None:
        """Initialize the compiler with a model tier.

        Args:
            model_tier: One of "fast" or "reasoning". Determines the
                total token budget.

        Raises:
            ValueError: If model_tier is not recognized.
        """
        if model_tier not in self.TOKEN_BUDGETS:
            raise ValueError(
                f"Unknown model tier '{model_tier}'. "
                f"Must be one of: {list(self.TOKEN_BUDGETS.keys())}"
            )
        self._model_tier = model_tier
        self._total_budget = self.TOKEN_BUDGETS[model_tier]
        # cl100k_base works as a reasonable approximation for both
        # Claude and GPT models
        self._encoding = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(self, text: str) -> int:
        """Count tokens in a text string using tiktoken.

        Args:
            text: The text to count tokens for.

        Returns:
            Number of tokens.
        """
        if not text:
            return 0
        return len(self._encoding.encode(text))

    def _truncate_to_budget(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within a token budget.

        Keeps the beginning of the text (for system prompts and
        context). For session history, use _truncate_messages_to_budget
        which preserves the most recent messages.

        Args:
            text: The text to potentially truncate.
            max_tokens: Maximum number of tokens allowed.

        Returns:
            The text, truncated if necessary.
        """
        if not text:
            return text

        tokens = self._encoding.encode(text)
        if len(tokens) <= max_tokens:
            return text

        truncated_tokens = tokens[:max_tokens]
        return self._encoding.decode(truncated_tokens)

    def _truncate_messages_to_budget(
        self, messages: list[dict], max_tokens: int
    ) -> list[dict]:
        """Truncate session messages to fit budget, keeping most recent.

        Removes oldest messages first to preserve recent conversation
        context, which is more relevant for the current interaction.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            max_tokens: Maximum total tokens for all messages.

        Returns:
            Truncated list of messages (most recent preserved).
        """
        if not messages:
            return messages

        # Calculate total tokens per message
        message_tokens = []
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            # Account for role label overhead (~4 tokens per message)
            tokens = self._count_tokens(content) + self._count_tokens(role) + 4
            message_tokens.append(tokens)

        total = sum(message_tokens)
        if total <= max_tokens:
            return messages

        # Remove oldest messages first until within budget
        result = list(messages)
        result_tokens = list(message_tokens)
        while sum(result_tokens) > max_tokens and len(result) > 1:
            result.pop(0)
            result_tokens.pop(0)

        # If single remaining message still exceeds budget, truncate it
        if result and sum(result_tokens) > max_tokens:
            content = result[0].get("content", "")
            truncated = self._truncate_to_budget(content, max_tokens - 8)
            result[0] = {**result[0], "content": truncated}

        return result

    def _truncate_memories_to_budget(
        self, memories: list[str], max_tokens: int
    ) -> list[str]:
        """Truncate memories to fit budget, keeping most relevant.

        Memories are assumed to be ordered by relevance (most relevant
        first from semantic search). Removes least relevant (last)
        memories first.

        Args:
            memories: List of memory content strings, ordered by
                relevance (most relevant first).
            max_tokens: Maximum total tokens for all memories.

        Returns:
            Truncated list of memory strings (most relevant preserved).
        """
        if not memories:
            return memories

        result = []
        tokens_used = 0

        for memory in memories:
            memory_tokens = self._count_tokens(memory)
            if tokens_used + memory_tokens <= max_tokens:
                result.append(memory)
                tokens_used += memory_tokens
            else:
                # Try to fit a truncated version of this memory
                remaining = max_tokens - tokens_used
                if remaining > 20:  # Only include if meaningful
                    truncated = self._truncate_to_budget(memory, remaining)
                    result.append(truncated)
                break

        return result

    async def compile(
        self,
        system_prompt: str,
        session_messages: list[dict],
        relevant_memories: list[str],
        task: dict,
    ) -> dict:
        """Compile working context within token budget.

        Allocates the total budget across sections and truncates each
        to fit. Priority order for preservation:
        1. System prompt (essential instructions)
        2. Recent session messages (immediate context)
        3. Relevant memories (knowledge)
        4. Task data (current objective)

        Args:
            system_prompt: The agent's system instructions.
            session_messages: Recent conversation messages (dicts with
                'role' and 'content').
            relevant_memories: Memory content strings ordered by
                relevance (from semantic search).
            task: Task data dict with at minimum a 'description' key.

        Returns:
            Dict with compiled context and token usage metrics:
            {
                "system_prompt": str,
                "messages": list[dict],
                "context": str,
                "task": dict,
                "token_usage": {
                    "total": int,
                    "system": int,
                    "session": int,
                    "memory": int,
                    "task": int,
                },
            }
        """
        # Calculate budget for each section
        system_budget = int(
            self._total_budget * self.BUDGET_ALLOCATION["system_prompt"]
        )
        session_budget = int(
            self._total_budget * self.BUDGET_ALLOCATION["session_history"]
        )
        memory_budget = int(
            self._total_budget * self.BUDGET_ALLOCATION["relevant_context"]
        )
        task_budget = int(
            self._total_budget * self.BUDGET_ALLOCATION["task_and_buffer"]
        )

        # 1. Truncate system prompt (defensive -- usually fits)
        compiled_system = self._truncate_to_budget(system_prompt, system_budget)
        system_tokens = self._count_tokens(compiled_system)

        # 2. Truncate session messages (oldest removed first)
        compiled_messages = self._truncate_messages_to_budget(
            session_messages, session_budget
        )
        session_tokens = sum(
            self._count_tokens(m.get("content", ""))
            + self._count_tokens(m.get("role", ""))
            + 4
            for m in compiled_messages
        )

        # 3. Truncate memories (least relevant removed first)
        compiled_memories = self._truncate_memories_to_budget(
            relevant_memories, memory_budget
        )
        memory_text = "\n\n".join(compiled_memories) if compiled_memories else ""
        memory_tokens = self._count_tokens(memory_text)

        # 4. Format task data within budget
        task_text = json.dumps(task, default=str)
        compiled_task_text = self._truncate_to_budget(task_text, task_budget)
        task_tokens = self._count_tokens(compiled_task_text)

        # Re-parse task if it was truncated (best effort)
        try:
            compiled_task = json.loads(compiled_task_text)
        except json.JSONDecodeError:
            compiled_task = task  # Fall back to original if truncation broke JSON

        total_tokens = (
            system_tokens + session_tokens + memory_tokens + task_tokens
        )

        token_usage = {
            "total": total_tokens,
            "budget": self._total_budget,
            "system": system_tokens,
            "session": session_tokens,
            "memory": memory_tokens,
            "task": task_tokens,
        }

        logger.info(
            "working_context.compiled",
            model_tier=self._model_tier,
            total_tokens=total_tokens,
            budget=self._total_budget,
            utilization=f"{(total_tokens / self._total_budget) * 100:.1f}%",
            sections={
                "system": system_tokens,
                "session": session_tokens,
                "memory": memory_tokens,
                "task": task_tokens,
            },
        )

        return {
            "system_prompt": compiled_system,
            "messages": compiled_messages,
            "context": memory_text,
            "task": compiled_task,
            "token_usage": token_usage,
        }
