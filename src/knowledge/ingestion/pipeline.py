"""End-to-end ingestion pipeline connecting loaders, chunking, embedding, and storage.

Orchestrates the complete document ingestion flow:

    DocumentLoader.load() -> KnowledgeChunker.chunk_sections()
    -> MetadataExtractor.enrich_chunks() -> EmbeddingService.embed_batch()
    -> QdrantKnowledgeStore.upsert_chunks()

Supports single document, directory, and document update (versioning) operations.
All operations are tenant-scoped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.knowledge.embeddings import EmbeddingService
from src.knowledge.ingestion.chunker import KnowledgeChunker
from src.knowledge.ingestion.loaders import DocumentLoader, SUPPORTED_EXTENSIONS
from src.knowledge.ingestion.metadata_extractor import MetadataExtractor
from src.knowledge.models import KnowledgeChunk
from src.knowledge.qdrant_client import QdrantKnowledgeStore

logger = logging.getLogger(__name__)


# ── Result Model ──────────────────────────────────────────────────────────


class IngestionResult(BaseModel):
    """Result of a single document ingestion operation.

    Attributes:
        chunks_created: Number of chunks successfully stored.
        document_source: Original document path or identifier.
        version: The version number assigned to these chunks.
        errors: List of error messages encountered during ingestion.
    """

    chunks_created: int = 0
    document_source: str = ""
    version: int = 1
    errors: list[str] = Field(default_factory=list)


# ── Ingestion Pipeline ────────────────────────────────────────────────────


class IngestionPipeline:
    """Orchestrates load -> chunk -> enrich -> embed -> store for documents.

    Wires together all ingestion components into a single pipeline that
    accepts any supported document and stores it as enriched, embedded
    chunks in Qdrant.

    Args:
        store: Qdrant knowledge store for vector storage.
        embedder: Embedding service for dense + sparse vector generation.
        chunker: Feature-level text chunker.
        extractor: Metadata extractor for content enrichment.
    """

    def __init__(
        self,
        store: QdrantKnowledgeStore,
        embedder: EmbeddingService,
        chunker: KnowledgeChunker,
        extractor: MetadataExtractor,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._chunker = chunker
        self._extractor = extractor
        self._loader = DocumentLoader()

    async def ingest_document(
        self,
        file_path: str | Path,
        tenant_id: str,
        metadata_overrides: dict[str, Any] | None = None,
    ) -> IngestionResult:
        """Ingest a single document through the full pipeline.

        Steps:
        1. Load document via DocumentLoader
        2. Chunk sections via KnowledgeChunker
        3. Enrich metadata via MetadataExtractor + apply overrides
        4. Generate embeddings via EmbeddingService
        5. Store in Qdrant via QdrantKnowledgeStore

        Args:
            file_path: Path to the document file.
            tenant_id: Tenant to ingest for.
            metadata_overrides: Optional dict to force metadata field values
                on all chunks (e.g., {"product_category": "billing"}).

        Returns:
            IngestionResult with chunk count and any errors.
        """
        path = Path(file_path)
        result = IngestionResult(document_source=str(path))

        try:
            # 1. Load document into raw sections
            sections = self._loader.load(path)
            if not sections:
                result.errors.append(f"No sections extracted from {path}")
                return result

            # Extract frontmatter from first section if available
            frontmatter = None
            for section in sections:
                if section.frontmatter:
                    frontmatter = section.frontmatter
                    break

            # 2. Chunk sections into KnowledgeChunks
            chunks = self._chunker.chunk_sections(
                sections=sections,
                tenant_id=tenant_id,
                document_source=str(path),
            )
            if not chunks:
                result.errors.append(f"No chunks produced from {path}")
                return result

            # 3. Enrich metadata
            chunks = self._extractor.enrich_chunks(
                chunks=chunks,
                frontmatter=frontmatter,
                overrides=metadata_overrides,
            )

            # 4. Generate embeddings
            texts = [chunk.content for chunk in chunks]
            embeddings = await self._embedder.embed_batch(texts)
            for chunk, (dense, sparse) in zip(chunks, embeddings, strict=True):
                chunk.embedding_dense = dense
                chunk.embedding_sparse = sparse

            # 5. Store in Qdrant
            await self._store.upsert_chunks(chunks, tenant_id)

            result.chunks_created = len(chunks)
            logger.info(
                "Ingested %s: %d chunks for tenant %s",
                path.name,
                len(chunks),
                tenant_id,
            )

        except Exception as e:
            logger.error("Failed to ingest %s: %s", path, e)
            result.errors.append(str(e))

        return result

    async def ingest_directory(
        self,
        dir_path: str | Path,
        tenant_id: str,
        recursive: bool = True,
        metadata_overrides: dict[str, Any] | None = None,
    ) -> list[IngestionResult]:
        """Ingest all supported documents in a directory.

        Walks the directory (optionally recursively), identifies supported
        file formats, and ingests each through the full pipeline.

        Args:
            dir_path: Path to directory containing documents.
            tenant_id: Tenant to ingest for.
            recursive: Whether to walk subdirectories (default True).
            metadata_overrides: Optional metadata overrides applied to all docs.

        Returns:
            List of IngestionResult, one per file processed.
        """
        directory = Path(dir_path)
        results: list[IngestionResult] = []

        if not directory.is_dir():
            return [
                IngestionResult(
                    document_source=str(directory),
                    errors=[f"Not a directory: {directory}"],
                )
            ]

        # Collect supported files
        files: list[Path] = []
        if recursive:
            for ext in SUPPORTED_EXTENSIONS:
                files.extend(directory.rglob(f"*{ext}"))
        else:
            for ext in SUPPORTED_EXTENSIONS:
                files.extend(directory.glob(f"*{ext}"))

        # Sort for deterministic ordering
        files.sort()

        if not files:
            logger.warning("No supported files found in %s", directory)
            return results

        logger.info(
            "Found %d supported files in %s (recursive=%s)",
            len(files),
            directory,
            recursive,
        )

        for file_path in files:
            result = await self.ingest_document(
                file_path=file_path,
                tenant_id=tenant_id,
                metadata_overrides=metadata_overrides,
            )
            results.append(result)

        return results

    async def update_document(
        self,
        file_path: str | Path,
        tenant_id: str,
        metadata_overrides: dict[str, Any] | None = None,
    ) -> IngestionResult:
        """Re-ingest a document, versioning old chunks.

        1. Find existing chunks for this source_document + tenant_id
        2. Mark all existing chunks as is_current=False
        3. Determine next version number
        4. Ingest new version with incremented version

        Args:
            file_path: Path to the updated document.
            tenant_id: Tenant owning the document.
            metadata_overrides: Optional metadata overrides for new chunks.

        Returns:
            IngestionResult for the new version.
        """
        path = Path(file_path)
        source_document = str(path)

        # Find existing chunks for this document + tenant
        existing_chunks = await self._find_chunks_by_source(
            source_document=source_document,
            tenant_id=tenant_id,
        )

        # Determine next version
        current_max_version = 0
        if existing_chunks:
            current_max_version = max(
                c.get("version", 1) for c in existing_chunks
            )

        next_version = current_max_version + 1

        # Mark old chunks as not current via set_payload
        if existing_chunks:
            old_ids = [c["id"] for c in existing_chunks]
            self._store.client.set_payload(
                collection_name=self._store._config.collection_knowledge,
                payload={"is_current": False},
                points=old_ids,
            )
            logger.info(
                "Marked %d old chunks as is_current=False for %s (tenant %s)",
                len(old_ids),
                source_document,
                tenant_id,
            )

        # Ingest new version
        result = await self.ingest_document(
            file_path=path,
            tenant_id=tenant_id,
            metadata_overrides=metadata_overrides,
        )

        # Update version on newly created chunks
        if result.chunks_created > 0 and next_version > 1:
            new_chunks = await self._find_chunks_by_source(
                source_document=source_document,
                tenant_id=tenant_id,
                is_current=True,
            )
            if new_chunks:
                new_ids = [c["id"] for c in new_chunks]
                self._store.client.set_payload(
                    collection_name=self._store._config.collection_knowledge,
                    payload={"version": next_version},
                    points=new_ids,
                )

        result.version = next_version
        logger.info(
            "Updated %s to version %d (%d chunks) for tenant %s",
            source_document,
            next_version,
            result.chunks_created,
            tenant_id,
        )

        return result

    async def _find_chunks_by_source(
        self,
        source_document: str,
        tenant_id: str,
        is_current: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Find chunks by source_document and tenant_id using Qdrant scroll.

        Args:
            source_document: The source document path to filter on.
            tenant_id: The tenant ID to filter on.
            is_current: Optional filter for is_current field.

        Returns:
            List of dicts with 'id', 'version', and other payload fields.
        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        must_conditions = [
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=tenant_id),
            ),
            FieldCondition(
                key="source_document",
                match=MatchValue(value=source_document),
            ),
        ]

        if is_current is not None:
            must_conditions.append(
                FieldCondition(
                    key="is_current",
                    match=MatchValue(value=is_current),
                )
            )

        scroll_filter = Filter(must=must_conditions)

        # Scroll through all matching points
        all_points: list[dict[str, Any]] = []
        offset = None

        while True:
            results, next_offset = self._store.client.scroll(
                collection_name=self._store._config.collection_knowledge,
                scroll_filter=scroll_filter,
                limit=100,
                offset=offset,
                with_payload=True,
            )

            for point in results:
                payload = point.payload or {}
                all_points.append(
                    {
                        "id": str(point.id),
                        "version": payload.get("version", 1),
                        "is_current": payload.get("is_current", True),
                        "source_document": payload.get("source_document", ""),
                    }
                )

            if next_offset is None:
                break
            offset = next_offset

        return all_points
