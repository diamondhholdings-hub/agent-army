"""Conversation history storage and session management.

Provides persistent conversation memory for sales agents, enabling:
- Message persistence across sessions and channels
- Semantic search over conversation history
- Cross-session context assembly for agent context windows
- Session lifecycle management with metadata tracking
"""

from src.knowledge.conversations.session import ConversationSession, SessionManager
from src.knowledge.conversations.store import ConversationStore

__all__ = [
    "ConversationSession",
    "ConversationStore",
    "SessionManager",
]
