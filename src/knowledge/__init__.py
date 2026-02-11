"""Knowledge Base module for tenant-scoped vector storage and retrieval.

Provides Qdrant-backed vector storage with payload-based multi-tenant isolation,
hybrid search (dense + sparse BM25), and Pydantic models for knowledge chunks.
"""

from src.knowledge.config import KnowledgeBaseConfig
from src.knowledge.embeddings import EmbeddingService
from src.knowledge.models import (
    ChunkMetadata,
    ConversationMessage,
    KnowledgeChunk,
    TenantConfig,
)
from src.knowledge.qdrant_client import QdrantKnowledgeStore

__all__ = [
    "ChunkMetadata",
    "ConversationMessage",
    "EmbeddingService",
    "KnowledgeBaseConfig",
    "KnowledgeChunk",
    "QdrantKnowledgeStore",
    "TenantConfig",
]
