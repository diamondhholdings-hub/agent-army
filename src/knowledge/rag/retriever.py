"""Multi-source retriever for the agentic RAG pipeline.

Fetches knowledge chunks from multiple sources (product knowledge, methodology,
regional content, conversation history) based on decomposed sub-queries.
Results are merged, deduplicated by chunk ID, and ranked by relevance score.

All operations are tenant-scoped to enforce multi-tenant isolation.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.knowledge.rag.decomposer import SubQuery

logger = logging.getLogger(__name__)


class RetrievedChunk(BaseModel):
    """A chunk retrieved from a knowledge source with relevance metadata.

    Attributes:
        chunk_id: Unique identifier of the retrieved chunk.
        content: Text content of the chunk.
        relevance_score: Score between 0.0 and 1.0 indicating relevance.
        source_type: Which knowledge source this came from.
        source_document: Original document filename or identifier.
        sub_query: The sub-query that retrieved this chunk.
    """

    chunk_id: str
    content: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    source_type: str
    source_document: str = ""
    sub_query: str = ""


class MultiSourceRetriever:
    """Retrieves and merges chunks from multiple knowledge sources.

    Executes each sub-query against the appropriate store (knowledge base
    or conversation store), deduplicates results by chunk ID, and returns
    the top_k most relevant chunks.

    Args:
        knowledge_store: QdrantKnowledgeStore for product/methodology/regional.
        conversation_store: ConversationStore for conversation history.
        top_k: Maximum number of results to return.
    """

    def __init__(
        self,
        knowledge_store: Any,
        conversation_store: Any,
        top_k: int = 7,
    ) -> None:
        self._knowledge_store = knowledge_store
        self._conversation_store = conversation_store
        self._top_k = top_k

    @property
    def top_k(self) -> int:
        """Maximum number of results to return."""
        return self._top_k

    async def retrieve(
        self,
        sub_queries: list[SubQuery],
        tenant_id: str,
    ) -> list[RetrievedChunk]:
        """Retrieve chunks for all sub-queries, merge and deduplicate.

        For each sub-query:
        - "conversation" source_type -> searches conversation store
        - All others -> searches knowledge base with metadata filters

        Args:
            sub_queries: Decomposed sub-queries with source types and filters.
            tenant_id: Tenant to search within (mandatory).

        Returns:
            Deduplicated list of RetrievedChunk objects, limited to top_k.
        """
        all_chunks: list[RetrievedChunk] = []

        for sq in sub_queries:
            if sq.source_type == "conversation":
                chunks = await self._retrieve_conversations(sq, tenant_id)
            else:
                chunks = await self._retrieve_knowledge(sq, tenant_id)
            all_chunks.extend(chunks)

        # Deduplicate by chunk_id, keeping highest relevance score
        deduplicated = self._deduplicate(all_chunks)

        # Sort by relevance score descending
        deduplicated.sort(key=lambda c: c.relevance_score, reverse=True)

        return deduplicated[: self._top_k]

    async def _retrieve_knowledge(
        self, sub_query: SubQuery, tenant_id: str
    ) -> list[RetrievedChunk]:
        """Retrieve from the knowledge base using hybrid search.

        Args:
            sub_query: Sub-query with filters for metadata-scoped retrieval.
            tenant_id: Tenant scope.

        Returns:
            List of RetrievedChunk objects from knowledge base.
        """
        try:
            results = await self._knowledge_store.hybrid_search(
                query_text=sub_query.query,
                tenant_id=tenant_id,
                filters=sub_query.filters if sub_query.filters else None,
                top_k=self._top_k,
            )

            chunks: list[RetrievedChunk] = []
            for i, chunk in enumerate(results):
                # Assign a decaying relevance score based on position
                score = max(0.1, 1.0 - (i * 0.1))
                chunks.append(
                    RetrievedChunk(
                        chunk_id=chunk.id,
                        content=chunk.content,
                        relevance_score=min(score, 1.0),
                        source_type=sub_query.source_type,
                        source_document=chunk.metadata.source_document,
                        sub_query=sub_query.query,
                    )
                )
            return chunks

        except Exception:
            logger.warning(
                "Knowledge retrieval failed for sub-query: %s",
                sub_query.query,
                exc_info=True,
            )
            return []

    async def _retrieve_conversations(
        self, sub_query: SubQuery, tenant_id: str
    ) -> list[RetrievedChunk]:
        """Retrieve from conversation history using semantic search.

        Args:
            sub_query: Sub-query targeting conversation history.
            tenant_id: Tenant scope.

        Returns:
            List of RetrievedChunk objects from conversation history.
        """
        try:
            results = await self._conversation_store.search_conversations(
                tenant_id=tenant_id,
                query=sub_query.query,
                top_k=self._top_k,
            )

            chunks: list[RetrievedChunk] = []
            for i, msg in enumerate(results):
                score = max(0.1, 1.0 - (i * 0.1))
                chunks.append(
                    RetrievedChunk(
                        chunk_id=msg.id,
                        content=msg.content,
                        relevance_score=min(score, 1.0),
                        source_type="conversation",
                        source_document=f"conversation:{msg.session_id}",
                        sub_query=sub_query.query,
                    )
                )
            return chunks

        except Exception:
            logger.warning(
                "Conversation retrieval failed for sub-query: %s",
                sub_query.query,
                exc_info=True,
            )
            return []

    @staticmethod
    def _deduplicate(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Deduplicate chunks by chunk_id, keeping highest relevance score.

        Args:
            chunks: All retrieved chunks (may contain duplicates).

        Returns:
            Deduplicated list of chunks.
        """
        seen: dict[str, RetrievedChunk] = {}
        for chunk in chunks:
            existing = seen.get(chunk.chunk_id)
            if existing is None or chunk.relevance_score > existing.relevance_score:
                seen[chunk.chunk_id] = chunk
        return list(seen.values())
