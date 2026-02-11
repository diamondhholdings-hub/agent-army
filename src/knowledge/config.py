"""Knowledge Base configuration via Pydantic BaseSettings.

All settings load from environment variables with the KNOWLEDGE_ prefix.
For example, KNOWLEDGE_QDRANT_PATH sets qdrant_path.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class KnowledgeBaseConfig(BaseSettings):
    """Configuration for the Knowledge Base vector storage and embedding services.

    Attributes:
        qdrant_path: Local filesystem path for Qdrant storage (dev mode).
        qdrant_url: Remote Qdrant server URL (production mode). If set, takes
            precedence over qdrant_path.
        qdrant_api_key: API key for remote Qdrant authentication.
        openai_api_key: OpenAI API key for dense embedding generation.
        embedding_model: OpenAI embedding model name.
        embedding_dimensions: Dimensionality of dense embeddings.
        collection_knowledge: Name of the knowledge base collection in Qdrant.
        collection_conversations: Name of the conversations collection in Qdrant.
        default_top_k: Default number of results returned by search.
        chunk_size: Target token count per knowledge chunk.
        chunk_overlap_pct: Overlap percentage between consecutive chunks (0.0-1.0).
    """

    model_config = SettingsConfigDict(
        env_prefix="KNOWLEDGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Qdrant connection
    qdrant_path: str = "./qdrant_data"
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None

    # Embedding
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Collections
    collection_knowledge: str = "knowledge_base"
    collection_conversations: str = "conversations"

    # Search
    default_top_k: int = 7

    # Chunking
    chunk_size: int = 512
    chunk_overlap_pct: float = 0.15
