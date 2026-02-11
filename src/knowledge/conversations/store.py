"""Conversation history storage and retrieval using Qdrant.

Persists conversation messages as embedded vectors in the Qdrant conversations
collection, enabling semantic search over conversation history. All operations
are tenant-scoped to enforce multi-tenant isolation.

Key capabilities:
- Add individual or batched messages with dense embeddings
- Retrieve session history (ordered by timestamp)
- Retrieve channel history across sessions
- Semantic search over conversation history with optional filters
- Recent context assembly for agent context windows
- Session deletion with tenant guard
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    DatetimeRange,
    FieldCondition,
    Filter,
    MatchValue,
    OrderBy,
    PointStruct,
    Range,
)

from src.knowledge.embeddings import EmbeddingService
from src.knowledge.models import ConversationMessage

logger = logging.getLogger(__name__)


class ConversationStore:
    """Tenant-scoped conversation message storage backed by Qdrant.

    Stores conversation messages as embedded vectors in the conversations
    collection, enabling both exact-match retrieval (by session, channel)
    and semantic search over conversation history.

    Args:
        qdrant_client: Initialized Qdrant client instance.
        embedder: Embedding service for generating dense vectors.
        collection_name: Qdrant collection for conversations.
    """

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embedder: EmbeddingService,
        collection_name: str = "conversations",
    ) -> None:
        self._client = qdrant_client
        self._embedder = embedder
        self._collection = collection_name

    async def add_message(self, message: ConversationMessage) -> str:
        """Persist a single conversation message with its embedding.

        Embeds the message content and stores it in Qdrant with full
        payload metadata for filtered retrieval.

        Args:
            message: The conversation message to persist.

        Returns:
            The message ID (same as message.id).
        """
        dense_vector, _sparse = await self._embedder.embed_text(message.content)

        point = PointStruct(
            id=message.id,
            vector={"dense": dense_vector},
            payload=self._message_to_payload(message),
        )

        self._client.upsert(
            collection_name=self._collection,
            points=[point],
        )
        logger.debug(
            "Stored message %s for session %s (tenant %s)",
            message.id,
            message.session_id,
            message.tenant_id,
        )
        return message.id

    async def add_messages(self, messages: list[ConversationMessage]) -> list[str]:
        """Batch-persist multiple conversation messages.

        More efficient than calling add_message() in a loop because
        embeddings are generated in a single batch API call.

        Args:
            messages: List of conversation messages to persist.

        Returns:
            List of message IDs in the same order as input.
        """
        if not messages:
            return []

        # Batch embed all message contents
        texts = [m.content for m in messages]
        embeddings = await self._embedder.embed_batch(texts)

        points: list[PointStruct] = []
        for message, (dense_vector, _sparse) in zip(messages, embeddings, strict=True):
            point = PointStruct(
                id=message.id,
                vector={"dense": dense_vector},
                payload=self._message_to_payload(message),
            )
            points.append(point)

        self._client.upsert(
            collection_name=self._collection,
            points=points,
        )
        logger.info(
            "Batch stored %d messages for tenant %s",
            len(messages),
            messages[0].tenant_id,
        )
        return [m.id for m in messages]

    async def get_session_history(
        self, tenant_id: str, session_id: str, limit: int = 50
    ) -> list[ConversationMessage]:
        """Retrieve all messages for a session, ordered by timestamp.

        Args:
            tenant_id: Mandatory tenant scope.
            session_id: Session to retrieve messages for.
            limit: Maximum number of messages to return.

        Returns:
            List of ConversationMessage objects ordered by timestamp ascending.
        """
        results = self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    FieldCondition(key="session_id", match=MatchValue(value=session_id)),
                ]
            ),
            limit=limit,
            order_by=OrderBy(key="timestamp", direction="asc"),
            with_payload=True,
            with_vectors=False,
        )

        points, _next_page = results
        return [self._payload_to_message(str(p.id), p.payload or {}) for p in points]

    async def get_channel_history(
        self, tenant_id: str, channel: str, limit: int = 50
    ) -> list[ConversationMessage]:
        """Retrieve recent messages for a channel across all sessions.

        Useful for seeing all interactions on a specific communication channel,
        regardless of which session they belong to.

        Args:
            tenant_id: Mandatory tenant scope.
            channel: Channel to filter by (e.g., "email", "slack", "web").
            limit: Maximum number of messages to return.

        Returns:
            List of ConversationMessage objects ordered by timestamp descending.
        """
        results = self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    FieldCondition(key="channel", match=MatchValue(value=channel)),
                ]
            ),
            limit=limit,
            order_by=OrderBy(key="timestamp", direction="desc"),
            with_payload=True,
            with_vectors=False,
        )

        points, _next_page = results
        return [self._payload_to_message(str(p.id), p.payload or {}) for p in points]

    async def search_conversations(
        self,
        tenant_id: str,
        query: str,
        top_k: int = 10,
        session_id: str | None = None,
        channel: str | None = None,
        time_range: tuple[datetime, datetime] | None = None,
    ) -> list[ConversationMessage]:
        """Semantic search over conversation history.

        The key feature: "What did we discuss about pricing last week?"
        Embeds the query and performs dense vector search with mandatory
        tenant scoping and optional filters.

        Args:
            tenant_id: Mandatory tenant scope.
            query: Natural language search query.
            top_k: Maximum number of results.
            session_id: Optional filter to search within a specific session.
            channel: Optional filter to search within a specific channel.
            time_range: Optional (start, end) datetime tuple to restrict results.

        Returns:
            List of ConversationMessage objects ranked by semantic similarity.
        """
        dense_vector, _sparse = await self._embedder.embed_text(query)

        # Build filter conditions
        must_conditions: list[FieldCondition] = [
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
        ]

        if session_id is not None:
            must_conditions.append(
                FieldCondition(key="session_id", match=MatchValue(value=session_id))
            )

        if channel is not None:
            must_conditions.append(
                FieldCondition(key="channel", match=MatchValue(value=channel))
            )

        if time_range is not None:
            start_ts, end_ts = time_range
            must_conditions.append(
                FieldCondition(
                    key="timestamp",
                    range=Range(
                        gte=start_ts.timestamp(),
                        lte=end_ts.timestamp(),
                    ),
                )
            )

        query_filter = Filter(must=must_conditions)

        results = self._client.query_points(
            collection_name=self._collection,
            query=dense_vector,
            using="dense",
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )

        return [
            self._payload_to_message(str(p.id), p.payload or {})
            for p in results.points
        ]

    async def get_recent_context(
        self, tenant_id: str, limit: int = 10
    ) -> list[ConversationMessage]:
        """Get the most recent messages across all sessions for a tenant.

        Useful for building agent context windows with the latest
        interaction history.

        Args:
            tenant_id: Mandatory tenant scope.
            limit: Maximum number of messages to return.

        Returns:
            List of ConversationMessage objects ordered by timestamp descending.
        """
        results = self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                ]
            ),
            limit=limit,
            order_by=OrderBy(key="timestamp", direction="desc"),
            with_payload=True,
            with_vectors=False,
        )

        points, _next_page = results
        return [self._payload_to_message(str(p.id), p.payload or {}) for p in points]

    async def delete_session(self, tenant_id: str, session_id: str) -> int:
        """Delete all messages for a session with tenant isolation guard.

        Args:
            tenant_id: Mandatory tenant scope (deletion guard).
            session_id: Session whose messages should be deleted.

        Returns:
            Number of messages deleted.
        """
        # First count messages to report how many were deleted
        points, _ = self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    FieldCondition(key="session_id", match=MatchValue(value=session_id)),
                ]
            ),
            limit=10000,
            with_payload=False,
            with_vectors=False,
        )
        count = len(points)

        if count > 0:
            from qdrant_client.models import FilterSelector

            self._client.delete(
                collection_name=self._collection,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="tenant_id",
                                match=MatchValue(value=tenant_id),
                            ),
                            FieldCondition(
                                key="session_id",
                                match=MatchValue(value=session_id),
                            ),
                        ]
                    )
                ),
            )
            logger.info(
                "Deleted %d messages for session %s (tenant %s)",
                count,
                session_id,
                tenant_id,
            )

        return count

    # ── Internal helpers ───────────────────────────────────────────────────

    @staticmethod
    def _message_to_payload(message: ConversationMessage) -> dict[str, Any]:
        """Convert a ConversationMessage to a Qdrant payload dict."""
        return {
            "tenant_id": message.tenant_id,
            "session_id": message.session_id,
            "channel": message.channel,
            "role": message.role,
            "content": message.content,
            "timestamp": message.timestamp.timestamp(),
            "timestamp_iso": message.timestamp.isoformat(),
            "metadata": message.metadata,
        }

    @staticmethod
    def _payload_to_message(point_id: str, payload: dict[str, Any]) -> ConversationMessage:
        """Convert a Qdrant payload dict back to a ConversationMessage."""
        # Reconstruct timestamp from epoch float
        ts_value = payload.get("timestamp", 0)
        if isinstance(ts_value, (int, float)):
            timestamp = datetime.fromtimestamp(ts_value, tz=timezone.utc)
        else:
            timestamp = datetime.fromisoformat(str(ts_value))

        return ConversationMessage(
            id=point_id,
            tenant_id=payload.get("tenant_id", ""),
            session_id=payload.get("session_id", ""),
            channel=payload.get("channel", ""),
            role=payload.get("role", "user"),
            content=payload.get("content", ""),
            timestamp=timestamp,
            metadata=payload.get("metadata", {}),
        )
