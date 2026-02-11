"""Answer synthesis for the agentic RAG pipeline.

Takes the original query and retrieved chunks, uses an LLM to produce a
coherent answer grounded in the source documents. Each claim in the answer
is mapped to source citations for traceability.

The synthesizer also computes a confidence score based on the ratio of
relevant chunks to total chunks provided.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from src.knowledge.rag.retriever import RetrievedChunk

logger = logging.getLogger(__name__)

SYNTHESIS_PROMPT = """You are a sales knowledge assistant. Synthesize a clear, accurate answer
based ONLY on the provided source documents. Cite sources using [N] notation.

Query: {query}

Source Documents:
{sources}

Instructions:
1. Answer the query using ONLY information from the sources above.
2. Cite each claim with [N] where N is the source number.
3. If sources don't contain enough information, say so clearly.
4. Be concise but thorough.

Answer:"""

NO_SOURCES_RESPONSE = "I don't have enough information in the knowledge base to answer this question. Please try rephrasing your query or check if the relevant content has been ingested."


class SourceCitation(BaseModel):
    """A citation linking a claim to its source chunk.

    Attributes:
        citation_id: Numeric citation identifier (matches [N] in answer).
        chunk_id: ID of the source chunk in the knowledge base.
        source_document: Original document filename or identifier.
        content_snippet: Brief excerpt from the source for verification.
    """

    citation_id: int
    chunk_id: str
    source_document: str
    content_snippet: str = ""


class SynthesizedResponse(BaseModel):
    """The output of the response synthesis step.

    Attributes:
        answer: The synthesized answer text with inline citations.
        sources: List of source citations referenced in the answer.
        confidence: Confidence score (0.0-1.0) based on chunk relevance.
    """

    answer: str
    sources: list[SourceCitation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class ResponseSynthesizer:
    """Synthesizes grounded answers from retrieved knowledge chunks.

    Uses an LLM to produce coherent answers that cite their sources.
    Parses the LLM response to extract citation references and map
    them back to source chunks.

    Args:
        llm: LLM instance with an async ainvoke(prompt) method.
    """

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def synthesize(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        relevance_ratio: float | None = None,
    ) -> SynthesizedResponse:
        """Synthesize an answer from retrieved chunks.

        Args:
            query: The original user query.
            chunks: Retrieved and graded chunks to synthesize from.
            relevance_ratio: Optional pre-computed relevance ratio for confidence.

        Returns:
            SynthesizedResponse with answer, citations, and confidence.
        """
        if not chunks:
            return SynthesizedResponse(
                answer=NO_SOURCES_RESPONSE,
                sources=[],
                confidence=0.0,
            )

        # Build numbered source list for the prompt
        source_texts = []
        for i, chunk in enumerate(chunks, 1):
            source_texts.append(
                f"[{i}] (Source: {chunk.source_document})\n{chunk.content}"
            )

        sources_str = "\n\n".join(source_texts)
        prompt = SYNTHESIS_PROMPT.format(query=query, sources=sources_str)

        try:
            answer = await self._llm.ainvoke(prompt)
        except Exception:
            logger.warning("LLM synthesis failed", exc_info=True)
            answer = NO_SOURCES_RESPONSE

        # Extract citations from the answer
        citations = self._extract_citations(answer, chunks)

        # Compute confidence from relevance ratio or chunk scores
        if relevance_ratio is not None:
            confidence = min(max(relevance_ratio, 0.0), 1.0)
        else:
            avg_score = sum(c.relevance_score for c in chunks) / len(chunks)
            confidence = min(max(avg_score, 0.0), 1.0)

        return SynthesizedResponse(
            answer=answer,
            sources=citations,
            confidence=confidence,
        )

    @staticmethod
    def _extract_citations(
        answer: str, chunks: list[RetrievedChunk]
    ) -> list[SourceCitation]:
        """Extract [N] citation references from the answer text.

        Maps each citation number to the corresponding source chunk.

        Args:
            answer: The synthesized answer text.
            chunks: The source chunks (1-indexed in the prompt).

        Returns:
            List of SourceCitation objects for referenced sources.
        """
        # Find all [N] patterns in the answer
        citation_pattern = re.compile(r"\[(\d+)\]")
        found_ids = set()
        for match in citation_pattern.finditer(answer):
            cid = int(match.group(1))
            found_ids.add(cid)

        citations: list[SourceCitation] = []
        for cid in sorted(found_ids):
            # Citation IDs are 1-based, chunk list is 0-based
            idx = cid - 1
            if 0 <= idx < len(chunks):
                chunk = chunks[idx]
                snippet = chunk.content[:150] if chunk.content else ""
                citations.append(
                    SourceCitation(
                        citation_id=cid,
                        chunk_id=chunk.chunk_id,
                        source_document=chunk.source_document,
                        content_snippet=snippet,
                    )
                )

        return citations
