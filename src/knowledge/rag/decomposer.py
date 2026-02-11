"""Query decomposition for the agentic RAG pipeline.

Breaks complex multi-faceted queries into targeted sub-queries, each aimed
at a specific knowledge source (product, methodology, regional, conversation).
Simple single-intent queries pass through as a single sub-query.

Uses an LLM to analyze query intent and determine decomposition strategy.
The LLM returns structured JSON that maps to SubQuery objects.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

VALID_SOURCE_TYPES = {"product", "methodology", "regional", "conversation"}

DECOMPOSITION_PROMPT = """You are a query decomposition engine for a sales knowledge base.
Given a user query, break it into sub-queries targeting specific knowledge sources.

Available source types:
- "product": Product features, pricing, positioning, technical specs
- "methodology": Sales frameworks (MEDDIC, BANT), qualification criteria, sales process
- "regional": Region-specific sales approaches, pricing modifiers, cultural considerations
- "conversation": Previous conversation history, past discussions

Available filter fields:
- "content_type": "product", "methodology", "regional", "positioning", "pricing"
- "product_category": "monetization", "charging", "billing"
- "region": "apac", "emea", "americas", "global"

Rules:
1. Simple queries (single intent, single source) -> 1 sub-query
2. Complex queries (multi-faceted, cross-source) -> 2-4 sub-queries
3. Each sub-query must have: query (str), source_type (str), filters (dict)
4. Return ONLY a JSON array of sub-query objects. No explanation.

Query: {query}

JSON array:"""


class SubQuery(BaseModel):
    """A targeted sub-query for a specific knowledge source.

    Attributes:
        query: The search query text.
        source_type: Which knowledge source to search.
        filters: Metadata filters for targeted retrieval.
    """

    query: str
    source_type: Literal["product", "methodology", "regional", "conversation"]
    filters: dict[str, Any] = Field(default_factory=dict)


class QueryDecomposer:
    """Decomposes complex queries into source-targeted sub-queries.

    Uses an LLM to analyze query intent and produce structured sub-queries.
    Simple queries pass through as a single sub-query. Complex queries
    are decomposed into 2-4 sub-queries targeting different knowledge sources.

    Args:
        llm: LLM instance with an async ainvoke(prompt) method.
    """

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def decompose(self, query: str) -> list[SubQuery]:
        """Decompose a query into sub-queries.

        Args:
            query: The user's natural language query.

        Returns:
            List of SubQuery objects targeting specific knowledge sources.
        """
        if not query or not query.strip():
            return [
                SubQuery(
                    query=query or "",
                    source_type="product",
                    filters={},
                )
            ]

        prompt = DECOMPOSITION_PROMPT.format(query=query)

        try:
            response = await self._llm.ainvoke(prompt)
            sub_queries = self._parse_response(response)
            if sub_queries:
                return sub_queries
        except Exception:
            logger.warning(
                "LLM decomposition failed for query: %s, falling back to passthrough",
                query,
                exc_info=True,
            )

        # Fallback: single sub-query passthrough
        return [
            SubQuery(
                query=query,
                source_type="product",
                filters={},
            )
        ]

    def _parse_response(self, response: str) -> list[SubQuery]:
        """Parse the LLM JSON response into SubQuery objects.

        Args:
            response: Raw LLM response (expected JSON array).

        Returns:
            List of SubQuery objects, or empty list if parsing fails.
        """
        try:
            # Find JSON array in response (may have surrounding text)
            text = response.strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start == -1 or end == 0:
                return []

            data = json.loads(text[start:end])
            if not isinstance(data, list):
                return []

            sub_queries: list[SubQuery] = []
            for item in data:
                if not isinstance(item, dict):
                    continue

                source_type = item.get("source_type", "product")
                if source_type not in VALID_SOURCE_TYPES:
                    source_type = "product"

                sub_queries.append(
                    SubQuery(
                        query=item.get("query", ""),
                        source_type=source_type,
                        filters=item.get("filters", {}),
                    )
                )

            return sub_queries

        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Failed to parse decomposition response: %s", response)
            return []
