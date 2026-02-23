"""Agentic RAG pipeline orchestrator.

Implements the full agentic RAG flow as a state machine:
  decompose -> retrieve -> grade -> decide -> (rewrite | synthesize)

The pipeline supports iterative retrieval: if document grading determines
that >50% of retrieved chunks are irrelevant, the query is rewritten and
retrieval is retried, up to max_iterations times.

All operations are tenant-scoped and track iteration count for observability.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.knowledge.models import ConversationMessage
from src.knowledge.rag.decomposer import QueryDecomposer, SubQuery
from src.knowledge.rag.retriever import MultiSourceRetriever, RetrievedChunk
from src.knowledge.rag.synthesizer import ResponseSynthesizer, SourceCitation

logger = logging.getLogger(__name__)

GRADING_PROMPT = """Is the following document relevant to the query?
Query: {query}
Document: {document}
Answer with ONLY "yes" or "no"."""

REWRITE_PROMPT = """The following query did not retrieve relevant results.
Rewrite it to improve retrieval from a sales knowledge base.

Original query: {query}
Retrieved but irrelevant content topics: {irrelevant_topics}

Return ONLY the rewritten query, nothing else."""


class RAGResponse(BaseModel):
    """Final response from the agentic RAG pipeline.

    Attributes:
        answer: The synthesized answer text.
        sources: Source citations referenced in the answer.
        sub_queries: Sub-queries used during retrieval.
        iterations: Number of retrieve-grade cycles executed.
        confidence: Confidence score (0.0-1.0).
    """

    answer: str
    sources: list[SourceCitation] = Field(default_factory=list)
    sub_queries: list[SubQuery] = Field(default_factory=list)
    iterations: int = 1
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class RAGState(BaseModel):
    """Internal state for the RAG pipeline execution.

    Tracks the evolving state as the pipeline moves through nodes.
    """

    query: str
    tenant_id: str
    sub_queries: list[SubQuery] = Field(default_factory=list)
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    relevant_chunks: list[RetrievedChunk] = Field(default_factory=list)
    irrelevant_chunks: list[RetrievedChunk] = Field(default_factory=list)
    iterations: int = 0
    conversation_context: list[ConversationMessage] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class AgenticRAGPipeline:
    """Agentic RAG pipeline with iterative retrieval and grading.

    Orchestrates the full flow:
    1. Decompose query into sub-queries
    2. Retrieve chunks from multiple sources
    3. Grade each chunk for relevance
    4. If >50% irrelevant and iterations < max: rewrite and retry
    5. Synthesize answer from relevant chunks

    Args:
        decomposer: QueryDecomposer for breaking queries into sub-queries.
        retriever: MultiSourceRetriever for fetching from knowledge sources.
        synthesizer: ResponseSynthesizer for producing grounded answers.
        grading_llm: LLM for document relevance grading.
        max_iterations: Maximum number of retrieve-grade cycles.
    """

    def __init__(
        self,
        decomposer: QueryDecomposer,
        retriever: MultiSourceRetriever,
        synthesizer: ResponseSynthesizer,
        grading_llm: Any,
        max_iterations: int = 2,
    ) -> None:
        self._decomposer = decomposer
        self._retriever = retriever
        self._synthesizer = synthesizer
        self._grading_llm = grading_llm
        self._max_iterations = max_iterations

    async def run(
        self,
        query: str,
        tenant_id: str,
        conversation_context: list[ConversationMessage] | None = None,
        base_filters: dict[str, Any] | None = None,
    ) -> RAGResponse:
        """Execute the full agentic RAG pipeline.

        Args:
            query: The user's natural language query.
            tenant_id: Tenant scope for all operations.
            conversation_context: Optional conversation history for context.
            base_filters: Optional filters merged into every sub-query after
                decomposition. LLM-generated filters take precedence on collision.

        Returns:
            RAGResponse with answer, sources, sub-queries, and metadata.
        """
        state = RAGState(
            query=query,
            tenant_id=tenant_id,
            conversation_context=conversation_context or [],
        )

        # Step 1: Decompose
        state = await self._decompose(state)

        # Merge caller-supplied base_filters into each sub_query.
        # LLM-generated filters win on key collision.
        if base_filters:
            for sq in state.sub_queries:
                sq.filters = {**base_filters, **sq.filters}

        # Steps 2-4: Retrieve-Grade-Rewrite loop
        while state.iterations < self._max_iterations:
            state.iterations += 1

            # Step 2: Retrieve
            state = await self._retrieve(state)

            # Step 3: Grade
            state = await self._grade(state)

            # Step 4: Decide - if enough relevant, proceed to synthesis
            relevant_ratio = self._relevance_ratio(state)
            if relevant_ratio >= 0.5 or state.iterations >= self._max_iterations:
                break

            # Rewrite query for next iteration
            state = await self._rewrite(state)

        # If we exhausted iterations without enough relevant chunks,
        # use whatever we have (relevant + irrelevant)
        if not state.relevant_chunks:
            state.relevant_chunks = state.retrieved_chunks

        # Step 5: Synthesize
        relevant_ratio = self._relevance_ratio(state)
        synthesized = await self._synthesizer.synthesize(
            query=query,
            chunks=state.relevant_chunks,
            relevance_ratio=relevant_ratio if state.retrieved_chunks else None,
        )

        return RAGResponse(
            answer=synthesized.answer,
            sources=synthesized.sources,
            sub_queries=state.sub_queries,
            iterations=state.iterations,
            confidence=synthesized.confidence,
        )

    async def _decompose(self, state: RAGState) -> RAGState:
        """Decompose the query into sub-queries.

        If conversation context is present, adds a conversation sub-query
        to capture relevant history.
        """
        sub_queries = await self._decomposer.decompose(state.query)

        # If conversation context exists, add a conversation sub-query
        if state.conversation_context:
            sub_queries.append(
                SubQuery(
                    query=state.query,
                    source_type="conversation",
                    filters={},
                )
            )

        state.sub_queries = sub_queries
        return state

    async def _retrieve(self, state: RAGState) -> RAGState:
        """Retrieve chunks for the current sub-queries."""
        chunks = await self._retriever.retrieve(
            sub_queries=state.sub_queries,
            tenant_id=state.tenant_id,
        )
        state.retrieved_chunks = chunks
        state.relevant_chunks = []
        state.irrelevant_chunks = []
        return state

    async def _grade(self, state: RAGState) -> RAGState:
        """Grade each retrieved chunk for relevance to the query."""
        relevant: list[RetrievedChunk] = []
        irrelevant: list[RetrievedChunk] = []

        for chunk in state.retrieved_chunks:
            is_relevant = await self._grade_chunk(state.query, chunk)
            if is_relevant:
                relevant.append(chunk)
            else:
                irrelevant.append(chunk)

        state.relevant_chunks = relevant
        state.irrelevant_chunks = irrelevant

        logger.info(
            "Grading complete: %d relevant, %d irrelevant (iteration %d)",
            len(relevant),
            len(irrelevant),
            state.iterations,
        )
        return state

    async def _grade_chunk(self, query: str, chunk: RetrievedChunk) -> bool:
        """Grade a single chunk for relevance.

        Args:
            query: The user's query.
            chunk: The retrieved chunk to grade.

        Returns:
            True if the chunk is relevant, False otherwise.
        """
        prompt = GRADING_PROMPT.format(
            query=query,
            document=chunk.content[:500],
        )

        try:
            response = await self._grading_llm.ainvoke(prompt)
            return response.strip().lower().startswith("yes")
        except Exception:
            logger.warning("Grading failed for chunk %s, assuming relevant", chunk.chunk_id)
            return True  # Fail-open: assume relevant on error

    async def _rewrite(self, state: RAGState) -> RAGState:
        """Rewrite the query based on what was found irrelevant."""
        irrelevant_topics = ", ".join(
            c.content[:100] for c in state.irrelevant_chunks[:3]
        )

        prompt = REWRITE_PROMPT.format(
            query=state.query,
            irrelevant_topics=irrelevant_topics,
        )

        try:
            rewritten = await self._grading_llm.ainvoke(prompt)
            rewritten = rewritten.strip()
            if rewritten:
                logger.info(
                    "Rewrote query from '%s' to '%s'", state.query, rewritten
                )
                # Re-decompose with the rewritten query
                state.sub_queries = await self._decomposer.decompose(rewritten)
        except Exception:
            logger.warning("Query rewrite failed, keeping original sub-queries")

        return state

    @staticmethod
    def _relevance_ratio(state: RAGState) -> float:
        """Calculate the ratio of relevant chunks to total retrieved chunks."""
        total = len(state.relevant_chunks) + len(state.irrelevant_chunks)
        if total == 0:
            return 0.0
        return len(state.relevant_chunks) / total
