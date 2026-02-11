"""Metadata extraction from document structure, frontmatter, and content.

Enriches KnowledgeChunk objects with structured metadata:
- product_category from frontmatter or document structure
- buyer_persona from content keyword matching
- sales_stage from content keyword mapping
- region from frontmatter or defaults
- content_type from hierarchy and filename conventions

The MetadataExtractor is the final step in the ingestion pipeline,
applied after loading and chunking to produce fully enriched chunks.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.knowledge.ingestion.loaders import RawSection
from src.knowledge.models import ChunkMetadata, KnowledgeChunk

logger = logging.getLogger(__name__)

# ── Persona Detection Keywords ─────────────────────────────────────────────

PERSONA_KEYWORDS: dict[str, list[str]] = {
    "technical": [
        "CTO",
        "VP Engineering",
        "architect",
        "developer",
        "engineer",
        "DevOps",
        "technical lead",
        "API",
        "SDK",
        "integration",
        "infrastructure",
    ],
    "business": [
        "CFO",
        "VP Sales",
        "CEO",
        "VP Marketing",
        "revenue",
        "ROI",
        "business case",
        "budget",
        "stakeholder",
        "executive sponsor",
    ],
    "operations": [
        "COO",
        "IT Manager",
        "operations manager",
        "support",
        "implementation",
        "deployment",
        "migration",
        "onboarding",
    ],
}

# ── Sales Stage Keywords ───────────────────────────────────────────────────

STAGE_KEYWORDS: dict[str, list[str]] = {
    "discovery": [
        "pain point",
        "challenge",
        "current solution",
        "discovery",
        "qualification",
        "needs analysis",
        "use case",
        "problem",
    ],
    "demo": [
        "demo",
        "demonstration",
        "walkthrough",
        "showcase",
        "proof of concept",
        "POC",
    ],
    "evaluation": [
        "ROI",
        "return on investment",
        "total cost of ownership",
        "TCO",
        "comparison",
        "competitive",
        "versus",
        "vs.",
        "alternative",
        "benchmark",
        "value proposition",
        "differentiation",
    ],
    "negotiation": [
        "pricing",
        "discount",
        "contract",
        "terms",
        "SLA",
        "license",
        "subscription",
        "tier",
        "enterprise pricing",
        "volume",
        "per unit",
        "per seat",
    ],
    "implementation": [
        "implementation",
        "onboarding",
        "migration",
        "setup",
        "configuration",
        "deployment",
        "go-live",
        "timeline",
        "kickoff",
    ],
}

# ── Content Type from Hierarchy Keywords ───────────────────────────────────

HIERARCHY_CONTENT_TYPE_MAP: dict[str, str] = {
    "pricing": "pricing",
    "price": "pricing",
    "cost": "pricing",
    "tier": "pricing",
    "plan": "pricing",
    "feature": "product",
    "capability": "product",
    "overview": "product",
    "product": "product",
    "methodology": "methodology",
    "framework": "methodology",
    "process": "methodology",
    "competitive": "positioning",
    "comparison": "positioning",
    "battlecard": "positioning",
    "versus": "positioning",
    "vs": "positioning",
    "positioning": "positioning",
    "differentiation": "positioning",
    "region": "regional",
    "market": "regional",
    "compliance": "regional",
    "regulation": "regional",
    "local": "regional",
}

# ── Filename Content Type Patterns ─────────────────────────────────────────

FILENAME_CONTENT_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("battlecard", "positioning"),
    ("competitive", "positioning"),
    ("comparison", "positioning"),
    ("pricing", "pricing"),
    ("methodology", "methodology"),
    ("framework", "methodology"),
    ("regional", "regional"),
    ("region", "regional"),
    ("market", "regional"),
]


class MetadataExtractor:
    """Extracts and infers metadata from document content and structure.

    Uses multiple signals to populate ChunkMetadata fields:
    1. YAML frontmatter (explicit metadata)
    2. Document hierarchy (header keywords)
    3. Content keywords (persona and stage inference)
    4. Filename conventions (content type)

    Args:
        default_region: Default region when none can be inferred.
    """

    def __init__(self, default_region: str = "global"):
        self.default_region = default_region

    def extract_metadata(
        self,
        raw_section: RawSection,
        overrides: dict[str, Any] | None = None,
    ) -> ChunkMetadata:
        """Extract metadata from a raw section.

        Combines signals from frontmatter, hierarchy, content, and filename
        to produce a complete ChunkMetadata object.

        Args:
            raw_section: The raw section to extract metadata from.
            overrides: Optional dict to force any metadata field values.

        Returns:
            ChunkMetadata with all fields populated.
        """
        # Start with defaults
        product_category = "monetization"
        buyer_persona: list[str] = []
        sales_stage: list[str] = []
        region: list[str] = [self.default_region]
        content_type = "product"
        source_document = raw_section.source

        # 1. Extract from frontmatter
        if raw_section.frontmatter:
            fm = raw_section.frontmatter
            if "product_category" in fm:
                cat = fm["product_category"]
                if cat in ("monetization", "charging", "billing"):
                    product_category = cat
            if "buyer_persona" in fm:
                val = fm["buyer_persona"]
                buyer_persona = val if isinstance(val, list) else [val]
            if "sales_stage" in fm:
                val = fm["sales_stage"]
                sales_stage = val if isinstance(val, list) else [val]
            if "region" in fm:
                val = fm["region"]
                region = val if isinstance(val, list) else [val]
            if "content_type" in fm:
                content_type = fm["content_type"]

        # 2. Infer content_type from hierarchy
        inferred_type = self._infer_content_type_from_hierarchy(raw_section.hierarchy)
        if inferred_type:
            content_type = inferred_type

        # 3. Infer content_type from filename
        inferred_from_filename = self._infer_content_type_from_filename(source_document)
        if inferred_from_filename:
            content_type = inferred_from_filename

        # 4. Infer buyer_persona from content
        if not buyer_persona:
            buyer_persona = self._infer_personas(raw_section.content)

        # 5. Infer sales_stage from content
        if not sales_stage:
            sales_stage = self._infer_sales_stages(raw_section.content)

        # 6. Apply overrides (force any field)
        if overrides:
            if "product_category" in overrides:
                product_category = overrides["product_category"]
            if "buyer_persona" in overrides:
                buyer_persona = overrides["buyer_persona"]
            if "sales_stage" in overrides:
                sales_stage = overrides["sales_stage"]
            if "region" in overrides:
                region = overrides["region"]
            if "content_type" in overrides:
                content_type = overrides["content_type"]
            if "source_document" in overrides:
                source_document = overrides["source_document"]

        return ChunkMetadata(
            product_category=product_category,
            buyer_persona=buyer_persona,
            sales_stage=sales_stage,
            region=region,
            content_type=content_type,
            source_document=source_document,
        )

    def enrich_chunks(
        self,
        chunks: list[KnowledgeChunk],
        frontmatter: dict[str, Any] | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> list[KnowledgeChunk]:
        """Enrich a list of KnowledgeChunks with extracted metadata.

        For each chunk, creates a RawSection from the chunk content to
        feed into extract_metadata, then replaces the chunk's metadata
        with the enriched version (preserving version, cross_references,
        and source_document from the original).

        Args:
            chunks: Chunks to enrich (modified in place and returned).
            frontmatter: Optional frontmatter dict applied to all chunks.
            overrides: Optional overrides applied to all chunks.

        Returns:
            The same list of chunks with enriched metadata.
        """
        for chunk in chunks:
            # Build a RawSection from chunk content for metadata extraction
            raw_section = RawSection(
                content=chunk.content,
                source=chunk.metadata.source_document,
                section_title=None,
                hierarchy=[],
                frontmatter=frontmatter,
            )

            # Extract new metadata
            enriched = self.extract_metadata(raw_section, overrides)

            # Preserve fields from original metadata
            enriched.version = chunk.metadata.version
            enriched.valid_from = chunk.metadata.valid_from
            enriched.valid_until = chunk.metadata.valid_until
            enriched.is_current = chunk.metadata.is_current
            enriched.cross_references = chunk.metadata.cross_references
            enriched.source_document = chunk.metadata.source_document

            # Replace metadata
            chunk.metadata = enriched

        return chunks

    def _infer_content_type_from_hierarchy(self, hierarchy: list[str]) -> str | None:
        """Infer content_type from section hierarchy keywords.

        Iterates deepest-first (reversed) so more specific headers take
        priority over generic parent headers (e.g., "Pricing Overview"
        wins over "Product").
        """
        for header in reversed(hierarchy):
            header_lower = header.lower()
            for keyword, ctype in HIERARCHY_CONTENT_TYPE_MAP.items():
                if keyword in header_lower:
                    return ctype
        return None

    def _infer_content_type_from_filename(self, source: str) -> str | None:
        """Infer content_type from filename conventions."""
        source_lower = source.lower()
        for pattern, ctype in FILENAME_CONTENT_TYPE_PATTERNS:
            if pattern in source_lower:
                return ctype
        return None

    def _infer_personas(self, content: str) -> list[str]:
        """Infer buyer personas from content keywords."""
        found: list[str] = []
        content_lower = content.lower()
        for persona, keywords in PERSONA_KEYWORDS.items():
            for keyword in keywords:
                # Case-insensitive word boundary match
                pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
                if pattern.search(content):
                    if persona not in found:
                        found.append(persona)
                    break  # One match per persona is enough
        return found

    def _infer_sales_stages(self, content: str) -> list[str]:
        """Infer sales stages from content keywords."""
        found: list[str] = []
        content_lower = content.lower()
        for stage, keywords in STAGE_KEYWORDS.items():
            for keyword in keywords:
                pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
                if pattern.search(content):
                    if stage not in found:
                        found.append(stage)
                    break  # One match per stage is enough
        return found
