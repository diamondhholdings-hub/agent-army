"""Session state persistence via LangGraph AsyncPostgresSaver.

Wraps the LangGraph PostgreSQL checkpointer to provide session state
that persists across conversation turns. Session lifetime follows the
LOCKED DECISION: explicit-clear-only (no time-based expiration).

The checkpointer stores full conversation state keyed by thread_id,
enabling seamless conversation resumption even after long pauses.
"""

from __future__ import annotations

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

logger = structlog.get_logger(__name__)


class SessionStore:
    """Session state persistence wrapping LangGraph's AsyncPostgresSaver.

    Usage:
        store = SessionStore("postgresql://user:pass@host/db")
        await store.setup()

        # Pass checkpointer to LangGraph graph compilation
        app = graph.compile(checkpointer=store.checkpointer)

        # Retrieve session messages for context compilation
        messages = await store.get_session_messages("thread-123")

        # Explicit clear only (no time-based expiration)
        await store.clear_session("thread-123")
    """

    def __init__(self, database_url: str) -> None:
        """Initialize SessionStore with a database URL.

        Args:
            database_url: PostgreSQL connection string. If it uses the
                asyncpg scheme (postgresql+asyncpg://), it will be
                converted to the standard postgresql:// scheme required
                by the LangGraph checkpointer (which uses psycopg).
        """
        # AsyncPostgresSaver uses psycopg, not asyncpg.
        # Convert asyncpg URLs to standard postgres URLs.
        self._database_url = database_url.replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        self._checkpointer: AsyncPostgresSaver | None = None

    async def setup(self) -> None:
        """Initialize the checkpointer and create required tables.

        Must be called before using the checkpointer. Creates the
        LangGraph checkpoint tables in the database.
        """
        self._checkpointer = AsyncPostgresSaver.from_conn_string(
            self._database_url
        )
        await self._checkpointer.setup()
        logger.info("session_store.setup_complete")

    @property
    def checkpointer(self) -> AsyncPostgresSaver:
        """Get the underlying checkpointer for LangGraph graph compilation.

        Raises:
            RuntimeError: If setup() has not been called.
        """
        if self._checkpointer is None:
            raise RuntimeError(
                "SessionStore not initialized -- call setup() first"
            )
        return self._checkpointer

    async def get_session_messages(
        self, thread_id: str, limit: int = 50
    ) -> list[dict]:
        """Retrieve recent messages from a session thread.

        Reads the latest checkpoint for the given thread_id and extracts
        the message history from channel_values.

        Args:
            thread_id: The conversation thread identifier.
            limit: Maximum number of messages to return (most recent).

        Returns:
            List of message dicts with 'role' and 'content' keys.
            Returns empty list if no session exists for the thread.
        """
        checkpointer = self.checkpointer
        config = {"configurable": {"thread_id": thread_id}}

        try:
            checkpoint_tuple = await checkpointer.aget_tuple(config)
            if checkpoint_tuple is None:
                return []

            checkpoint = checkpoint_tuple.checkpoint
            channel_values = checkpoint.get("channel_values", {})
            messages = channel_values.get("messages", [])

            # Convert LangGraph message objects to dicts
            result = []
            for msg in messages:
                if hasattr(msg, "type") and hasattr(msg, "content"):
                    # LangGraph BaseMessage objects
                    role = "assistant" if msg.type == "ai" else msg.type
                    result.append({"role": role, "content": msg.content})
                elif isinstance(msg, dict):
                    result.append(msg)

            # Return most recent messages up to limit
            return result[-limit:]

        except Exception:
            logger.warning(
                "session_store.get_messages_failed",
                thread_id=thread_id,
                exc_info=True,
            )
            return []

    async def clear_session(self, thread_id: str) -> None:
        """Clear session state for a thread (explicit-clear-only lifetime).

        This is the only way to end a session -- there is no time-based
        expiration. Sessions persist until explicitly cleared.

        Args:
            thread_id: The conversation thread identifier to clear.
        """
        checkpointer = self.checkpointer

        try:
            # Use the checkpointer's connection to delete checkpoint data
            # for this thread. The checkpointer stores data in checkpoint
            # tables keyed by thread_id.
            async with checkpointer._get_connection() as conn:
                await conn.execute(
                    "DELETE FROM checkpoint_writes WHERE thread_id = %s",
                    (thread_id,),
                )
                await conn.execute(
                    "DELETE FROM checkpoint_blobs WHERE thread_id = %s",
                    (thread_id,),
                )
                await conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = %s",
                    (thread_id,),
                )
            logger.info(
                "session_store.session_cleared", thread_id=thread_id
            )
        except Exception:
            logger.error(
                "session_store.clear_session_failed",
                thread_id=thread_id,
                exc_info=True,
            )
            raise
