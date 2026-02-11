"""Document ingestion pipeline for the Knowledge Base.

Provides document loading (multi-format), feature-level chunking,
metadata extraction, and end-to-end pipeline orchestration.

The pipeline flow is:

    DocumentLoader.load() -> KnowledgeChunker.chunk_sections()
    -> MetadataExtractor.enrich_chunks() -> EmbeddingService.embed_batch()
    -> QdrantKnowledgeStore.upsert_chunks()

This produces embedded KnowledgeChunk objects stored in Qdrant.
"""

from src.knowledge.ingestion.chunker import KnowledgeChunker
from src.knowledge.ingestion.loaders import DocumentLoader, RawSection, load_document
from src.knowledge.ingestion.metadata_extractor import MetadataExtractor
from src.knowledge.ingestion.pipeline import IngestionPipeline, IngestionResult

__all__ = [
    "DocumentLoader",
    "IngestionPipeline",
    "IngestionResult",
    "KnowledgeChunker",
    "MetadataExtractor",
    "RawSection",
    "load_document",
]
