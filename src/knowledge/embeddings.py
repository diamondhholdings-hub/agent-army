"""Embedding service for dense (OpenAI) and sparse (BM25) vector generation.

Provides a unified interface for generating both vector types needed by
the hybrid search system. Dense vectors capture semantic meaning via OpenAI
text-embedding-3-small, while sparse BM25 vectors capture exact keyword
matches via fastembed.

Rate limit handling uses exponential backoff on OpenAI API calls.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from openai import AsyncOpenAI, RateLimitError

from src.knowledge.config import KnowledgeBaseConfig

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generates dense and sparse embeddings for knowledge base operations.

    Dense embeddings use OpenAI text-embedding-3-small (1536 dims) for
    semantic similarity. Sparse embeddings use fastembed's BM25 model for
    exact keyword matching. Together they power hybrid search with RRF fusion.

    Args:
        config: Knowledge base configuration with API keys and model settings.
    """

    def __init__(self, config: KnowledgeBaseConfig) -> None:
        self._config = config
        self._openai = AsyncOpenAI(api_key=config.openai_api_key)
        self._model = config.embedding_model
        self._dimensions = config.embedding_dimensions

        # Lazy-initialize BM25 model on first use (heavy import)
        self._bm25_model: Any = None

    def _get_bm25_model(self) -> Any:
        """Lazy-load the fastembed BM25 model.

        Returns:
            Initialized BM25 sparse embedding model.
        """
        if self._bm25_model is None:
            from fastembed import SparseTextEmbedding

            self._bm25_model = SparseTextEmbedding(model_name="Qdrant/bm25")
        return self._bm25_model

    async def embed_text(self, text: str) -> tuple[list[float], dict]:
        """Generate dense and sparse embeddings for a single text.

        Args:
            text: Input text to embed.

        Returns:
            Tuple of (dense_vector, sparse_vector) where sparse_vector has
            format {"indices": [...], "values": [...]}.
        """
        dense = await self._embed_dense([text])
        sparse = self._embed_sparse([text])
        return dense[0], sparse[0]

    async def embed_batch(self, texts: list[str]) -> list[tuple[list[float], dict]]:
        """Generate dense and sparse embeddings for a batch of texts.

        More efficient than calling embed_text() in a loop because the
        OpenAI API supports batch embedding in a single request.

        Args:
            texts: List of input texts to embed.

        Returns:
            List of (dense_vector, sparse_vector) tuples, one per input text.
        """
        dense_vectors = await self._embed_dense(texts)
        sparse_vectors = self._embed_sparse(texts)
        return list(zip(dense_vectors, sparse_vectors, strict=True))

    async def _embed_dense(
        self, texts: list[str], max_retries: int = 3
    ) -> list[list[float]]:
        """Generate dense embeddings via OpenAI with exponential backoff.

        Args:
            texts: Input texts to embed.
            max_retries: Maximum retry attempts on rate limit errors.

        Returns:
            List of dense embedding vectors.

        Raises:
            RateLimitError: If all retries are exhausted.
        """
        for attempt in range(max_retries):
            try:
                response = await self._openai.embeddings.create(
                    input=texts,
                    model=self._model,
                    dimensions=self._dimensions,
                )
                return [item.embedding for item in response.data]
            except RateLimitError:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2**attempt
                logger.warning(
                    "OpenAI rate limit hit, retrying in %ds (attempt %d/%d)",
                    wait_time,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(wait_time)

        # Should not reach here, but satisfy type checker
        raise RuntimeError("Exhausted retries for dense embedding")  # pragma: no cover

    def _embed_sparse(self, texts: list[str]) -> list[dict]:
        """Generate sparse BM25 embeddings via fastembed.

        Args:
            texts: Input texts to embed.

        Returns:
            List of sparse vectors in {"indices": [...], "values": [...]} format
            matching Qdrant SparseVector expectations.
        """
        model = self._get_bm25_model()
        results = list(model.embed(texts))
        sparse_vectors: list[dict] = []
        for result in results:
            sparse_vectors.append(
                {
                    "indices": result.indices.tolist(),
                    "values": result.values.tolist(),
                }
            )
        return sparse_vectors
