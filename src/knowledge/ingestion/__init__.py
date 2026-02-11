"""Document ingestion pipeline for the Knowledge Base.

Provides document loading (multi-format), feature-level chunking, and
metadata extraction. The pipeline flow is:

    load_document() -> KnowledgeChunker.chunk_sections() -> MetadataExtractor.enrich_chunks()

This produces KnowledgeChunk objects ready for embedding and Qdrant storage.
"""

from src.knowledge.ingestion.chunker import KnowledgeChunker
from src.knowledge.ingestion.loaders import DocumentLoader, RawSection, load_document
from src.knowledge.ingestion.metadata_extractor import MetadataExtractor

__all__ = [
    "DocumentLoader",
    "KnowledgeChunker",
    "MetadataExtractor",
    "RawSection",
    "load_document",
]
