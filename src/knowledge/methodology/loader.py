"""Loader for ingesting methodology and regional content into Qdrant.

Reads markdown files from data/methodology/ and data/regional/, chunks
them at the section level (## headings), and upserts into the Qdrant
knowledge_base collection with appropriate metadata tags.

Methodology chunks are tagged with content_type="methodology" and the
relevant sales_stage. Regional chunks are tagged with content_type="regional"
and the specific region code.

Both content types are universal -- they are the same for all tenants.
The tenant_id parameter is required by the Qdrant store for isolation,
but the content itself is not tenant-specific.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from src.knowledge.embeddings import EmbeddingService
from src.knowledge.models import ChunkMetadata, KnowledgeChunk
from src.knowledge.qdrant_client import QdrantKnowledgeStore

logger = logging.getLogger(__name__)

# Base paths for data files
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_METHODOLOGY_DIR = _PROJECT_ROOT / "data" / "methodology"
_REGIONAL_DIR = _PROJECT_ROOT / "data" / "regional"

# Mapping of methodology steps to their primary sales stage
_STEP_STAGE_MAP: dict[str, str] = {
    # MEDDIC
    "metrics": "discovery",
    "economic buyer": "discovery",
    "decision criteria": "evaluation",
    "decision process": "evaluation",
    "identify pain": "discovery",
    "champion": "discovery",
    # BANT
    "budget": "discovery",
    "authority": "discovery",
    "need": "discovery",
    "timeline": "discovery",
    # SPIN
    "situation": "discovery",
    "problem": "discovery",
    "implication": "discovery",
    "need-payoff": "discovery",
}

# Mapping of regional file stems to region codes
_REGION_MAP: dict[str, str] = {
    "apac": "apac",
    "emea": "emea",
    "americas": "americas",
}

# Mapping of regional section topics to content sub-categories
_REGIONAL_TOPIC_MAP: dict[str, str] = {
    "cultural": "cultural",
    "communication": "cultural",
    "pricing": "pricing",
    "commercial": "pricing",
    "compliance": "compliance",
    "regulatory": "compliance",
    "data residency": "compliance",
    "decision": "process",
    "stakeholder": "process",
    "objection": "objections",
    "key market": "markets",
}


def _chunk_markdown_by_sections(content: str) -> list[tuple[str, str]]:
    """Split markdown content into (heading, body) tuples at ## level.

    Each chunk includes the ## heading and all content up to the next ##
    heading or end of file. The document title (# heading) and intro text
    before the first ## are included as a separate "Introduction" chunk.

    Args:
        content: Full markdown document content.

    Returns:
        List of (section_heading, section_content) tuples.
    """
    chunks: list[tuple[str, str]] = []

    # Split on ## headings (not ### or #)
    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Extract heading
        lines = section.split("\n", 1)
        heading = lines[0].lstrip("#").strip()
        body = lines[1].strip() if len(lines) > 1 else ""

        # Skip if body is too short to be useful for search
        if len(body) < 50:
            continue

        chunks.append((heading, section))

    return chunks


def _classify_section_stage(heading: str) -> str:
    """Determine the sales stage for a methodology section heading.

    Args:
        heading: The ## section heading text.

    Returns:
        Sales stage string (e.g., "discovery", "evaluation").
    """
    heading_lower = heading.lower()
    for step_name, stage in _STEP_STAGE_MAP.items():
        if step_name in heading_lower:
            return stage
    return "discovery"  # Default to discovery for methodology content


def _classify_regional_topic(heading: str) -> str:
    """Determine the topic category for a regional section heading.

    Args:
        heading: The ## section heading text.

    Returns:
        Topic category string (e.g., "cultural", "pricing", "compliance").
    """
    heading_lower = heading.lower()
    for keyword, topic in _REGIONAL_TOPIC_MAP.items():
        if keyword in heading_lower:
            return topic
    return "general"


class MethodologyLoader:
    """Loads methodology and regional content into Qdrant for semantic search.

    Reads markdown files, chunks them at the section level, generates
    embeddings, and upserts into the knowledge_base collection.

    Args:
        store: Qdrant knowledge store instance.
        embedder: Embedding service for vector generation.
    """

    def __init__(
        self, store: QdrantKnowledgeStore, embedder: EmbeddingService
    ) -> None:
        self._store = store
        self._embedder = embedder

    async def load_methodologies(self, tenant_id: str) -> int:
        """Load all methodology markdown files into Qdrant.

        Reads each .md file from data/methodology/, splits into section-level
        chunks (one per ## heading), and upserts with content_type="methodology"
        and appropriate sales_stage metadata.

        Args:
            tenant_id: Tenant ID for Qdrant storage (methodologies are
                universal but stored per-tenant for isolation).

        Returns:
            Number of chunks created and stored.
        """
        if not _METHODOLOGY_DIR.exists():
            logger.warning("Methodology data directory not found: %s", _METHODOLOGY_DIR)
            return 0

        chunks: list[KnowledgeChunk] = []

        for md_file in sorted(_METHODOLOGY_DIR.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            framework_name = md_file.stem.upper()  # e.g., "meddic" -> "MEDDIC"

            sections = _chunk_markdown_by_sections(content)
            logger.info(
                "Processing %s: %d sections", md_file.name, len(sections)
            )

            for heading, body in sections:
                stage = _classify_section_stage(heading)

                chunk = KnowledgeChunk(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    content=body,
                    metadata=ChunkMetadata(
                        product_category="monetization",  # Methodology is cross-product
                        buyer_persona=["technical", "business", "executive"],
                        sales_stage=[stage],
                        region=["global"],
                        content_type="methodology",
                        source_document=md_file.name,
                        cross_references=[framework_name],
                    ),
                )
                chunks.append(chunk)

        if chunks:
            await self._store.upsert_chunks(chunks, tenant_id=tenant_id)
            logger.info(
                "Loaded %d methodology chunks for tenant %s",
                len(chunks),
                tenant_id,
            )

        return len(chunks)

    async def load_regional_data(self, tenant_id: str) -> int:
        """Load all regional markdown files into Qdrant.

        Reads each .md file from data/regional/, splits into section-level
        chunks, and upserts with content_type="regional" and the appropriate
        region tag in metadata.

        Args:
            tenant_id: Tenant ID for Qdrant storage.

        Returns:
            Number of chunks created and stored.
        """
        if not _REGIONAL_DIR.exists():
            logger.warning("Regional data directory not found: %s", _REGIONAL_DIR)
            return 0

        chunks: list[KnowledgeChunk] = []

        for md_file in sorted(_REGIONAL_DIR.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            region_code = _REGION_MAP.get(md_file.stem, md_file.stem)

            sections = _chunk_markdown_by_sections(content)
            logger.info(
                "Processing %s: %d sections for region %s",
                md_file.name,
                len(sections),
                region_code,
            )

            for heading, body in sections:
                topic = _classify_regional_topic(heading)

                # Determine relevant sales stages based on topic
                stages = ["discovery", "negotiation"] if topic == "pricing" else ["discovery"]

                chunk = KnowledgeChunk(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    content=body,
                    metadata=ChunkMetadata(
                        product_category="monetization",  # Regional is cross-product
                        buyer_persona=["technical", "business", "executive", "operations"],
                        sales_stage=stages,
                        region=[region_code],
                        content_type="regional",
                        source_document=md_file.name,
                        cross_references=[topic],
                    ),
                )
                chunks.append(chunk)

        if chunks:
            await self._store.upsert_chunks(chunks, tenant_id=tenant_id)
            logger.info(
                "Loaded %d regional chunks for tenant %s",
                len(chunks),
                tenant_id,
            )

        return len(chunks)

    async def load_all(self, tenant_id: str) -> dict[str, int]:
        """Load both methodology and regional content.

        Convenience method that calls both load_methodologies and
        load_regional_data.

        Args:
            tenant_id: Tenant ID for Qdrant storage.

        Returns:
            Dictionary with counts: {"methodology": N, "regional": M}.
        """
        methodology_count = await self.load_methodologies(tenant_id)
        regional_count = await self.load_regional_data(tenant_id)
        return {
            "methodology": methodology_count,
            "regional": regional_count,
        }
