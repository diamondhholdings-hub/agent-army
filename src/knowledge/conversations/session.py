"""Session management for tracking conversation context across interactions.

Provides ConversationSession for tracking session metadata and SessionManager
for managing the full session lifecycle: creation, message addition, context
assembly (including cross-session search), and session summarization.

Cross-session context is the key differentiator: when an agent starts a new
conversation, SessionManager can find semantically relevant messages from
prior sessions so the agent "remembers" what was discussed before.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from src.knowledge.conversations.store import ConversationStore
from src.knowledge.models import ConversationMessage

logger = logging.getLogger(__name__)


# ── Stop words for keyword extraction ──────────────────────────────────────

_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "it", "its", "this", "that", "these", "those", "i", "you", "he", "she",
    "we", "they", "me", "him", "her", "us", "them", "my", "your", "his",
    "our", "their", "what", "which", "who", "whom", "how", "when", "where",
    "why", "if", "then", "so", "not", "no", "yes", "just", "also", "very",
    "about", "up", "out", "all", "some", "any", "each", "every", "both",
    "more", "most", "other", "into", "over", "after", "before", "between",
    "through", "during", "there", "here", "than", "too",
})


class ConversationSession(BaseModel):
    """Tracks metadata for a single conversation session.

    A session represents a continuous interaction on a specific channel.
    Multiple sessions can exist for the same tenant, and cross-session
    context assembly links them together semantically.

    Attributes:
        session_id: Unique session identifier (UUID4).
        tenant_id: Owning tenant.
        channel: Communication channel (e.g., "web", "email", "slack").
        started_at: When the session was created.
        last_activity: When the last message was added.
        message_count: Number of messages in this session.
        metadata: Flexible metadata (e.g., prospect_name, deal_stage).
    """

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    channel: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message_count: int = 0
    metadata: dict = Field(default_factory=dict)


class SessionManager:
    """Manages conversation session lifecycle and context assembly.

    Orchestrates session creation, message persistence, and cross-session
    context retrieval. The key feature is get_context_for_session(), which
    assembles context from both the current session and semantically
    relevant messages from prior sessions.

    Args:
        store: ConversationStore for message persistence and retrieval.
    """

    def __init__(self, store: ConversationStore) -> None:
        self._store = store

    async def create_session(
        self,
        tenant_id: str,
        channel: str,
        metadata: dict | None = None,
    ) -> ConversationSession:
        """Create a new conversation session.

        Args:
            tenant_id: Owning tenant.
            channel: Communication channel for this session.
            metadata: Optional session metadata (e.g., prospect_name).

        Returns:
            A new ConversationSession with a generated UUID.
        """
        now = datetime.now(timezone.utc)
        session = ConversationSession(
            session_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            channel=channel,
            started_at=now,
            last_activity=now,
            message_count=0,
            metadata=metadata or {},
        )
        logger.info(
            "Created session %s on %s for tenant %s",
            session.session_id,
            channel,
            tenant_id,
        )
        return session

    async def add_message_to_session(
        self,
        session: ConversationSession,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> ConversationMessage:
        """Add a message to a session and persist it.

        Creates a ConversationMessage with the session's tenant/session/channel
        context, persists it via ConversationStore, and updates the session's
        activity tracking.

        Args:
            session: The session to add the message to.
            role: Message author role ("user", "assistant", or "system").
            content: Message text content.
            metadata: Optional message-level metadata.

        Returns:
            The persisted ConversationMessage.
        """
        message = ConversationMessage(
            tenant_id=session.tenant_id,
            session_id=session.session_id,
            channel=session.channel,
            role=role,
            content=content,
            metadata=metadata or {},
        )

        await self._store.add_message(message)

        # Update session tracking
        session.last_activity = message.timestamp
        session.message_count += 1

        return message

    async def get_context_for_session(
        self,
        session: ConversationSession,
        include_cross_session: bool = True,
        max_messages: int = 20,
    ) -> list[ConversationMessage]:
        """Assemble context from current session and optionally prior sessions.

        This is the key feature enabling agent memory: retrieves current
        session messages and, if enabled, also searches for semantically
        relevant messages from other sessions for the same tenant.

        Args:
            session: The current session to build context for.
            include_cross_session: If True, also search prior sessions for
                relevant context. Defaults to True.
            max_messages: Maximum total messages to return (current + cross).

        Returns:
            List of ConversationMessage objects, deduplicated and ordered
            by timestamp. Current session messages come first, followed by
            relevant cross-session messages.
        """
        # Get current session messages
        current_messages = await self._store.get_session_history(
            tenant_id=session.tenant_id,
            session_id=session.session_id,
            limit=max_messages,
        )

        if not include_cross_session or not current_messages:
            return current_messages[:max_messages]

        # Use the last few messages as a search query for cross-session context
        recent_texts = [m.content for m in current_messages[-3:]]
        search_query = " ".join(recent_texts)

        # Search for relevant messages from OTHER sessions
        cross_session_results = await self._store.search_conversations(
            tenant_id=session.tenant_id,
            query=search_query,
            top_k=5,
        )

        # Filter out messages from the current session (we already have those)
        current_ids = {m.id for m in current_messages}
        cross_messages = [
            m for m in cross_session_results
            if m.id not in current_ids and m.session_id != session.session_id
        ]

        # Limit cross-session messages to 5
        cross_messages = cross_messages[:5]

        # Merge: current session messages + cross-session context
        # Deduplicate by ID
        seen_ids: set[str] = set()
        merged: list[ConversationMessage] = []

        for msg in current_messages:
            if msg.id not in seen_ids:
                seen_ids.add(msg.id)
                merged.append(msg)

        for msg in cross_messages:
            if msg.id not in seen_ids:
                seen_ids.add(msg.id)
                merged.append(msg)

        # Sort all by timestamp
        merged.sort(key=lambda m: m.timestamp)

        return merged[:max_messages]

    async def summarize_session(self, session: ConversationSession) -> str:
        """Generate a structured summary of a session.

        This is a simple extraction, not LLM-powered. Extracts key topics
        from message content using keyword frequency analysis.

        Args:
            session: The session to summarize.

        Returns:
            A structured text summary with session metadata and topics.
        """
        messages = await self._store.get_session_history(
            tenant_id=session.tenant_id,
            session_id=session.session_id,
        )

        if not messages:
            return (
                f"Session {session.session_id} on {session.channel} "
                f"(0 messages, no activity)"
            )

        # Calculate duration
        first_ts = messages[0].timestamp
        last_ts = messages[-1].timestamp
        duration = last_ts - first_ts
        duration_str = self._format_duration(duration.total_seconds())

        # Extract topics via keyword frequency
        all_text = " ".join(m.content for m in messages)
        topics = self._extract_topics(all_text)
        topics_str = ", ".join(topics) if topics else "general discussion"

        return (
            f"Session {session.session_id} on {session.channel} "
            f"({len(messages)} messages, {duration_str})\n"
            f"Topics discussed: {topics_str}"
        )

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format a duration in seconds to a human-readable string."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}m"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            if minutes > 0:
                return f"{hours}h {minutes}m"
            return f"{hours}h"

    @staticmethod
    def _extract_topics(text: str, max_topics: int = 5) -> list[str]:
        """Extract top keywords from text as topic indicators.

        Simple keyword frequency analysis excluding common stop words.

        Args:
            text: Combined message text to analyze.
            max_topics: Maximum number of topic keywords to return.

        Returns:
            List of top keywords by frequency.
        """
        # Tokenize: lowercase, split on non-alphanumeric
        words = re.findall(r"[a-z]+", text.lower())

        # Filter stop words and very short words
        meaningful = [w for w in words if w not in _STOP_WORDS and len(w) > 2]

        # Count frequencies
        counter = Counter(meaningful)

        # Return top N
        return [word for word, _count in counter.most_common(max_topics)]
