"""Feature-level text chunking with configurable size and overlap.

Implements a chunking strategy that respects document structure: sections
that fit within the chunk size are kept intact, while larger sections are
split using RecursiveCharacterTextSplitter with proper overlap.

Each chunk produces a KnowledgeChunk object ready for metadata enrichment
and vector storage.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.knowledge.ingestion.loaders import RawSection
from src.knowledge.models import ChunkMetadata, KnowledgeChunk

logger = logging.getLogger(__name__)

# Default known product names for cross-reference detection
DEFAULT_PRODUCT_NAMES: list[str] = [
    "Monetization Platform",
    "Monetization",
    "Charging Platform",
    "Charging",
    "Billing Platform",
    "Billing",
]


def _count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """Count tokens in text using tiktoken encoding."""
    enc = tiktoken.get_encoding(encoding_name)
    return len(enc.encode(text))


def _estimate_chars_per_token(encoding_name: str = "cl100k_base") -> float:
    """Estimate average characters per token.

    Uses a representative sample to calibrate the char-to-token ratio
    for RecursiveCharacterTextSplitter (which works in characters).
    """
    # Typical English technical text averages ~4 chars per token
    return 4.0


class KnowledgeChunker:
    """Feature-level text chunker that produces KnowledgeChunk objects.

    Respects document structure by keeping sections that fit within
    chunk_size intact. Only splits sections that exceed the limit.

    Args:
        chunk_size: Target chunk size in tokens (not characters).
        overlap_pct: Overlap between consecutive chunks as a fraction (0.0-1.0).
        product_names: Known product names for cross-reference detection.

    Usage:
        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(sections, "tenant-1", "product-doc.md")
    """

    def __init__(
        self,
        chunk_size: int = 512,
        overlap_pct: float = 0.15,
        product_names: list[str] | None = None,
    ):
        self.chunk_size = chunk_size
        self.overlap_pct = overlap_pct
        self.product_names = product_names or DEFAULT_PRODUCT_NAMES

        # Convert token-based sizes to character estimates for LangChain
        chars_per_token = _estimate_chars_per_token()
        self._chunk_size_chars = int(chunk_size * chars_per_token)
        self._overlap_chars = int(self._chunk_size_chars * overlap_pct)

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self._chunk_size_chars,
            chunk_overlap=self._overlap_chars,
            separators=["\n\n", "\n", ". ", " "],
            keep_separator=True,
        )

    def chunk_sections(
        self,
        sections: list[RawSection],
        tenant_id: str,
        document_source: str,
    ) -> list[KnowledgeChunk]:
        """Split sections into feature-level chunks.

        Strategy:
        - If a section fits within chunk_size tokens, keep it as one chunk.
        - If a section exceeds chunk_size, split with RecursiveCharacterTextSplitter.
        - Preserve hierarchy metadata from each section.
        - Track chunk position for ordering.

        Args:
            sections: Raw sections from document loading.
            tenant_id: Tenant identifier for chunk ownership.
            document_source: Original document path/name.

        Returns:
            List of KnowledgeChunk objects with partial metadata.
        """
        chunks: list[KnowledgeChunk] = []
        chunk_index = 0
        now = datetime.now(timezone.utc)

        # Extract frontmatter from first section if available
        frontmatter = None
        for section in sections:
            if section.frontmatter:
                frontmatter = section.frontmatter
                break

        # Infer product_category from frontmatter or document source
        product_category = self._infer_product_category(frontmatter, document_source)

        for section in sections:
            section_tokens = _count_tokens(section.content)

            if section_tokens <= self.chunk_size:
                # Section fits in one chunk -- keep intact
                chunk = self._create_chunk(
                    content=section.content,
                    tenant_id=tenant_id,
                    document_source=document_source,
                    section=section,
                    product_category=product_category,
                    chunk_index=chunk_index,
                    now=now,
                )
                chunks.append(chunk)
                chunk_index += 1
            else:
                # Section too large -- split it
                sub_texts = self._splitter.split_text(section.content)
                for sub_text in sub_texts:
                    chunk = self._create_chunk(
                        content=sub_text,
                        tenant_id=tenant_id,
                        document_source=document_source,
                        section=section,
                        product_category=product_category,
                        chunk_index=chunk_index,
                        now=now,
                    )
                    chunks.append(chunk)
                    chunk_index += 1

        logger.info(
            "Chunked %d sections into %d chunks for %s (tenant: %s)",
            len(sections),
            len(chunks),
            document_source,
            tenant_id,
        )
        return chunks

    def _create_chunk(
        self,
        content: str,
        tenant_id: str,
        document_source: str,
        section: RawSection,
        product_category: str,
        chunk_index: int,
        now: datetime,
    ) -> KnowledgeChunk:
        """Create a single KnowledgeChunk with partial metadata."""
        cross_refs = self._detect_cross_references(content)

        metadata = ChunkMetadata(
            product_category=product_category,
            content_type="product",  # Default; enriched later by MetadataExtractor
            source_document=document_source,
            version=1,
            valid_from=now,
            is_current=True,
            cross_references=cross_refs,
        )

        return KnowledgeChunk(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            content=content,
            metadata=metadata,
            created_at=now,
            updated_at=now,
        )

    def _detect_cross_references(self, content: str) -> list[str]:
        """Detect cross-references to known products in chunk content.

        Uses case-insensitive matching against product_names list.
        Returns unique product names found in the content.
        """
        found: list[str] = []
        content_lower = content.lower()
        for name in self.product_names:
            # Use word boundary matching to avoid partial matches
            pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
            if pattern.search(content):
                # Use canonical name (from product_names list)
                if name not in found:
                    found.append(name)
        return found

    def _infer_product_category(
        self,
        frontmatter: dict | None,
        document_source: str,
    ) -> str:
        """Infer product_category from frontmatter or document source.

        Falls back to 'monetization' as default if no signal found.
        """
        # Check frontmatter
        if frontmatter:
            cat = frontmatter.get("product_category")
            if cat and cat in ("monetization", "charging", "billing"):
                return cat

        # Check document source filename
        source_lower = document_source.lower()
        if "charging" in source_lower:
            return "charging"
        elif "billing" in source_lower:
            return "billing"
        elif "monetization" in source_lower:
            return "monetization"

        # Default
        return "monetization"
