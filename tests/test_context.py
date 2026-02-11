"""Tests for three-tier context management system.

Tests cover:
- MemoryEntry model validation
- Token counting accuracy
- Token budget truncation
- Working context compilation within budget
- Session message truncation (preserves most recent)
- Budget allocation per section
- ContextManager orchestration (mocked dependencies)
- ContextManager memory storage (mocked)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.context.memory import MemoryEntry
from src.app.context.working import WorkingContextCompiler
from src.app.context.manager import ContextManager
from src.app.context.session import SessionStore


# ── MemoryEntry Tests ──────────────────────────────────────────────────────


class TestMemoryEntry:
    """Test MemoryEntry Pydantic model."""

    def test_memory_entry_creation(self):
        """MemoryEntry validates required fields and sets defaults."""
        entry = MemoryEntry(
            tenant_id="tenant-1",
            agent_id="sales_agent",
            content="Customer Acme has a $500k annual budget",
        )
        assert entry.tenant_id == "tenant-1"
        assert entry.agent_id == "sales_agent"
        assert entry.content == "Customer Acme has a $500k annual budget"
        assert entry.metadata == {}
        assert entry.embedding is None
        assert isinstance(entry.memory_id, str)
        assert len(entry.memory_id) == 36  # UUID format
        assert isinstance(entry.created_at, datetime)
        assert isinstance(entry.updated_at, datetime)

    def test_memory_entry_with_metadata(self):
        """MemoryEntry accepts optional metadata."""
        entry = MemoryEntry(
            tenant_id="t1",
            agent_id="research_agent",
            content="Deal closing in Q2",
            metadata={"source": "crm", "deal_id": "deal-123"},
        )
        assert entry.metadata["source"] == "crm"
        assert entry.metadata["deal_id"] == "deal-123"

    def test_memory_entry_with_embedding(self):
        """MemoryEntry accepts pre-computed embedding."""
        embedding = [0.1] * 1536
        entry = MemoryEntry(
            tenant_id="t1",
            agent_id="a1",
            content="test",
            embedding=embedding,
        )
        assert entry.embedding is not None
        assert len(entry.embedding) == 1536


# ── WorkingContextCompiler Tests ───────────────────────────────────────────


class TestWorkingContextCompiler:
    """Test WorkingContextCompiler token counting and truncation."""

    def test_token_counting(self):
        """_count_tokens returns a reasonable count for known text."""
        compiler = WorkingContextCompiler("reasoning")
        # "Hello, world!" is typically 4 tokens with cl100k_base
        count = compiler._count_tokens("Hello, world!")
        assert count > 0
        assert count < 10  # Should be around 4 tokens

        # Empty string should be 0 tokens
        assert compiler._count_tokens("") == 0

    def test_token_counting_longer_text(self):
        """Token counting scales with text length."""
        compiler = WorkingContextCompiler("reasoning")
        short_count = compiler._count_tokens("Hello")
        long_count = compiler._count_tokens("Hello " * 100)
        assert long_count > short_count
        # 100 repetitions should be roughly 100-200 tokens
        assert long_count > 50

    def test_truncate_to_budget(self):
        """Text exceeding budget is truncated to fit."""
        compiler = WorkingContextCompiler("reasoning")
        long_text = "word " * 10000  # Very long text
        truncated = compiler._truncate_to_budget(long_text, 100)
        assert compiler._count_tokens(truncated) <= 100

    def test_truncate_to_budget_short_text(self):
        """Short text within budget is not modified."""
        compiler = WorkingContextCompiler("reasoning")
        short_text = "Hello, world!"
        result = compiler._truncate_to_budget(short_text, 100)
        assert result == short_text

    @pytest.mark.asyncio
    async def test_compile_within_budget(self):
        """Compiled context total tokens stay within budget."""
        compiler = WorkingContextCompiler("fast")  # 8k budget
        budget = compiler._total_budget  # 8000

        result = await compiler.compile(
            system_prompt="You are a helpful sales agent.",
            session_messages=[
                {"role": "user", "content": "Tell me about the deal."},
                {"role": "assistant", "content": "The deal is progressing well."},
            ],
            relevant_memories=["Customer budget is $500k", "Decision maker is the VP"],
            task={"type": "deal_analysis", "description": "Analyze current deal status"},
        )

        assert result["token_usage"]["total"] <= budget
        assert result["token_usage"]["budget"] == budget
        assert "system_prompt" in result
        assert "messages" in result
        assert "context" in result
        assert "task" in result

    @pytest.mark.asyncio
    async def test_compile_preserves_recent_messages(self):
        """Most recent session messages survive truncation."""
        compiler = WorkingContextCompiler("fast")  # 8k budget

        # Create many messages -- older ones should be dropped
        messages = [
            {"role": "user", "content": f"Message {i}: " + "x " * 200}
            for i in range(50)
        ]

        result = await compiler.compile(
            system_prompt="System prompt.",
            session_messages=messages,
            relevant_memories=[],
            task={"type": "test"},
        )

        # The last message should be present (most recent preserved)
        compiled_messages = result["messages"]
        assert len(compiled_messages) > 0
        assert len(compiled_messages) < 50  # Some were truncated

        # Most recent message should be preserved
        last_compiled = compiled_messages[-1]
        assert "Message 49" in last_compiled["content"]

    @pytest.mark.asyncio
    async def test_budget_allocation(self):
        """Each section stays within its allocated percentage."""
        compiler = WorkingContextCompiler("reasoning")
        budget = compiler._total_budget  # 32000

        result = await compiler.compile(
            system_prompt="You are a sales agent. " * 50,
            session_messages=[
                {"role": "user", "content": "Tell me about deals. " * 50},
                {"role": "assistant", "content": "Here is info. " * 50},
            ],
            relevant_memories=["Memory fact " * 50] * 5,
            task={"type": "analysis", "description": "Detailed analysis " * 50},
        )

        usage = result["token_usage"]
        # Allow 5% tolerance for rounding and overhead
        tolerance = 0.05

        # System: should be <= 15% + tolerance
        system_pct = usage["system"] / budget
        assert system_pct <= 0.15 + tolerance, (
            f"System used {system_pct:.2%}, expected <= {0.15 + tolerance:.2%}"
        )

        # Session: should be <= 35% + tolerance
        session_pct = usage["session"] / budget
        assert session_pct <= 0.35 + tolerance, (
            f"Session used {session_pct:.2%}, expected <= {0.35 + tolerance:.2%}"
        )

        # Memory: should be <= 35% + tolerance
        memory_pct = usage["memory"] / budget
        assert memory_pct <= 0.35 + tolerance, (
            f"Memory used {memory_pct:.2%}, expected <= {0.35 + tolerance:.2%}"
        )

        # Task: should be <= 15% + tolerance
        task_pct = usage["task"] / budget
        assert task_pct <= 0.15 + tolerance, (
            f"Task used {task_pct:.2%}, expected <= {0.15 + tolerance:.2%}"
        )

    def test_invalid_model_tier(self):
        """Invalid model tier raises ValueError."""
        with pytest.raises(ValueError, match="Unknown model tier"):
            WorkingContextCompiler("nonexistent")

    @pytest.mark.asyncio
    async def test_compile_empty_inputs(self):
        """Compilation works with empty inputs."""
        compiler = WorkingContextCompiler("fast")

        result = await compiler.compile(
            system_prompt="",
            session_messages=[],
            relevant_memories=[],
            task={},
        )

        assert result["token_usage"]["total"] >= 0
        assert result["messages"] == []
        assert result["context"] == ""


# ── ContextManager Tests ──────────────────────────────────────────────────


class TestContextManager:
    """Test ContextManager orchestration with mocked dependencies."""

    def _make_manager(self):
        """Create a ContextManager with mocked dependencies."""
        session_store = MagicMock(spec=SessionStore)
        session_store.get_session_messages = AsyncMock(return_value=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ])

        memory = MagicMock()
        memory.search = AsyncMock(return_value=[
            MemoryEntry(
                tenant_id="t1",
                agent_id="sales_agent",
                content="Customer budget is $500k",
            ),
        ])
        memory.store = AsyncMock(return_value="mem-123")

        compiler = WorkingContextCompiler("reasoning")

        manager = ContextManager(session_store, memory, compiler)
        return manager, session_store, memory

    @pytest.mark.asyncio
    async def test_context_manager_compile(self):
        """compile_working_context calls session and memory, returns compiled result."""
        manager, session_store, memory = self._make_manager()

        result = await manager.compile_working_context(
            tenant_id="t1",
            thread_id="thread-123",
            task={"type": "analysis", "description": "Analyze deal"},
            system_prompt="You are a sales agent.",
        )

        # Verify session store was called
        session_store.get_session_messages.assert_awaited_once_with("thread-123")

        # Verify memory search was called with tenant_id and task description
        memory.search.assert_awaited_once()
        call_args = memory.search.call_args
        assert call_args.kwargs.get("tenant_id") == "t1" or call_args.args[0] == "t1"

        # Verify result structure
        assert "system_prompt" in result
        assert "messages" in result
        assert "context" in result
        assert "task" in result
        assert "token_usage" in result
        assert result["token_usage"]["total"] > 0

    @pytest.mark.asyncio
    async def test_context_manager_store_memory(self):
        """store_memory creates MemoryEntry and delegates to memory.store."""
        manager, _, memory = self._make_manager()

        memory_id = await manager.store_memory(
            tenant_id="t1",
            agent_id="sales_agent",
            content="Customer prefers email communication",
            metadata={"source": "conversation"},
        )

        assert memory_id == "mem-123"
        memory.store.assert_awaited_once()

        # Verify the MemoryEntry was constructed correctly
        stored_entry = memory.store.call_args.args[0]
        assert isinstance(stored_entry, MemoryEntry)
        assert stored_entry.tenant_id == "t1"
        assert stored_entry.agent_id == "sales_agent"
        assert stored_entry.content == "Customer prefers email communication"
        assert stored_entry.metadata == {"source": "conversation"}

    @pytest.mark.asyncio
    async def test_context_manager_search_memory(self):
        """search_memory delegates to memory.search with correct params."""
        manager, _, memory = self._make_manager()

        results = await manager.search_memory(
            tenant_id="t1", query="customer budget", limit=5
        )

        memory.search.assert_awaited_once_with(
            tenant_id="t1", query="customer budget", limit=5
        )
        assert len(results) == 1
        assert results[0].content == "Customer budget is $500k"

    def test_context_manager_session_property(self):
        """session property returns the underlying SessionStore."""
        manager, session_store, _ = self._make_manager()
        assert manager.session is session_store

    @pytest.mark.asyncio
    async def test_context_manager_compile_no_description(self):
        """compile_working_context handles tasks without description."""
        manager, session_store, memory = self._make_manager()

        # Task without description should skip memory search
        result = await manager.compile_working_context(
            tenant_id="t1",
            thread_id="thread-123",
            task={"type": "status_check"},
            system_prompt="You are a sales agent.",
        )

        # Memory search should NOT be called (no description to search for)
        memory.search.assert_not_awaited()
        assert "token_usage" in result


# ── SessionStore Tests ─────────────────────────────────────────────────────


class TestSessionStore:
    """Test SessionStore initialization and URL conversion."""

    def test_url_conversion(self):
        """Async URL is converted to sync format."""
        store = SessionStore(
            "postgresql+asyncpg://user:pass@localhost:5432/db"
        )
        assert store._database_url == "postgresql://user:pass@localhost:5432/db"

    def test_sync_url_unchanged(self):
        """Sync URL is not modified."""
        store = SessionStore("postgresql://user:pass@localhost:5432/db")
        assert store._database_url == "postgresql://user:pass@localhost:5432/db"

    def test_checkpointer_not_initialized(self):
        """Accessing checkpointer before setup raises RuntimeError."""
        store = SessionStore("postgresql://user:pass@localhost:5432/db")
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = store.checkpointer
