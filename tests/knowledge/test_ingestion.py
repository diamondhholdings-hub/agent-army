"""Tests for the document ingestion pipeline.

Tests cover:
- Document loading (markdown, JSON, CSV, text)
- Feature-level chunking with size/overlap control
- Metadata extraction from frontmatter and content
- Cross-reference detection
- Version assignment
- Full pipeline integration (load -> chunk -> enrich)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.knowledge.ingestion.chunker import KnowledgeChunker, _count_tokens
from src.knowledge.ingestion.loaders import DocumentLoader, RawSection, load_document
from src.knowledge.ingestion.metadata_extractor import MetadataExtractor
from src.knowledge.models import ChunkMetadata, KnowledgeChunk

# ── Paths to fixtures ──────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PRODUCT_MD = FIXTURES_DIR / "sample_product.md"
SAMPLE_PRICING_JSON = FIXTURES_DIR / "sample_pricing.json"


# ── Test: Markdown Loading ─────────────────────────────────────────────────


class TestMarkdownLoading:
    """Tests for markdown document loading."""

    def test_markdown_loading_produces_sections(self):
        """Load sample_product.md and verify sections extracted with correct hierarchy."""
        loader = DocumentLoader()
        sections = loader.load(SAMPLE_PRODUCT_MD)

        assert len(sections) > 0, "Should produce at least one section"

        # Should have sections for major headers
        section_titles = [s.section_title for s in sections if s.section_title]
        assert "Subscription Management" in section_titles
        assert "Usage-Based Pricing" in section_titles
        assert "Analytics and Reporting" in section_titles

    def test_markdown_frontmatter_parsed(self):
        """Verify YAML frontmatter is parsed from markdown."""
        loader = DocumentLoader()
        sections = loader.load(SAMPLE_PRODUCT_MD)

        # At least the first section should have frontmatter
        sections_with_fm = [s for s in sections if s.frontmatter]
        assert len(sections_with_fm) > 0, "At least one section should have frontmatter"

        fm = sections_with_fm[0].frontmatter
        assert fm["product_category"] == "monetization"
        assert "global" in fm["region"]

    def test_markdown_hierarchy_preserved(self):
        """Verify header hierarchy is tracked for sections."""
        loader = DocumentLoader()
        sections = loader.load(SAMPLE_PRODUCT_MD)

        # Find a subsection (e.g., under Usage-Based Pricing)
        metering_sections = [
            s for s in sections if s.section_title and "Metering" in s.section_title
        ]
        if metering_sections:
            # Should have parent headers in hierarchy
            hierarchy = metering_sections[0].hierarchy
            assert len(hierarchy) > 1, "Subsection should have parent in hierarchy"

    def test_markdown_source_tracked(self):
        """Verify source file path is tracked in sections."""
        loader = DocumentLoader()
        sections = loader.load(SAMPLE_PRODUCT_MD)

        for section in sections:
            assert str(SAMPLE_PRODUCT_MD) in section.source

    def test_load_document_convenience_function(self):
        """Test the load_document convenience function."""
        sections = load_document(SAMPLE_PRODUCT_MD)
        assert len(sections) > 0


# ── Test: JSON Loading ─────────────────────────────────────────────────────


class TestJsonLoading:
    """Tests for JSON document loading."""

    def test_json_loading_produces_sections(self):
        """Load sample_pricing.json and verify structured data converted to sections."""
        loader = DocumentLoader()
        sections = loader.load(SAMPLE_PRICING_JSON)

        assert len(sections) > 0, "Should produce at least one section"

        # Each top-level key becomes a section
        section_titles = [s.section_title for s in sections if s.section_title]
        assert len(section_titles) > 0, "Sections should have titles from JSON keys"

    def test_json_pricing_data_readable(self):
        """Verify JSON pricing data is converted to readable text."""
        loader = DocumentLoader()
        sections = loader.load(SAMPLE_PRICING_JSON)

        # Find the tiers section
        tiers_sections = [s for s in sections if s.section_title and "Tier" in s.section_title]
        assert len(tiers_sections) > 0, "Should have tiers section"

        # Content should be readable text, not raw JSON
        content = tiers_sections[0].content
        assert "{" not in content or ":" in content, "Content should be formatted, not raw JSON"

    def test_json_section_hierarchy(self):
        """Verify JSON sections have hierarchy."""
        loader = DocumentLoader()
        sections = loader.load(SAMPLE_PRICING_JSON)

        for section in sections:
            if section.section_title:
                assert len(section.hierarchy) > 0, "JSON sections should have hierarchy"


# ── Test: CSV Loading ──────────────────────────────────────────────────────


class TestCsvLoading:
    """Tests for CSV document loading."""

    def test_csv_loading(self):
        """Verify CSV files are loaded with column headers as context."""
        csv_content = "Name,Price,Features\nStarter,2500,Basic\nPro,7500,Advanced\n"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write(csv_content)
            tmp_path = f.name

        try:
            loader = DocumentLoader()
            sections = loader.load(tmp_path)

            assert len(sections) == 2, "Should have one section per row"
            # Each row should include column headers
            assert "Name:" in sections[0].content
            assert "Price:" in sections[0].content
        finally:
            Path(tmp_path).unlink()

    def test_csv_row_titles(self):
        """Verify CSV rows use first column as section title."""
        csv_content = "Product,Price\nMonetization,2500\nCharging,1500\n"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write(csv_content)
            tmp_path = f.name

        try:
            loader = DocumentLoader()
            sections = loader.load(tmp_path)
            titles = [s.section_title for s in sections]
            assert "Monetization" in titles
            assert "Charging" in titles
        finally:
            Path(tmp_path).unlink()


# ── Test: Text Loading ─────────────────────────────────────────────────────


class TestTextLoading:
    """Tests for plain text loading."""

    def test_text_loading(self):
        """Verify plain text files are loaded as single sections."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("This is a simple text document.\nWith multiple lines.\n")
            tmp_path = f.name

        try:
            loader = DocumentLoader()
            sections = loader.load(tmp_path)
            assert len(sections) == 1
            assert "simple text document" in sections[0].content
        finally:
            Path(tmp_path).unlink()


# ── Test: Unsupported Format ───────────────────────────────────────────────


class TestUnsupportedFormat:
    """Tests for error handling on unsupported formats."""

    def test_unsupported_format_raises(self):
        """Verify unsupported format raises ValueError with guidance."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xyz", delete=False
        ) as f:
            f.write("content")
            tmp_path = f.name

        try:
            loader = DocumentLoader()
            with pytest.raises(ValueError, match="Unsupported file format"):
                loader.load(tmp_path)
        finally:
            Path(tmp_path).unlink()

    def test_missing_file_raises(self):
        """Verify missing file raises FileNotFoundError."""
        loader = DocumentLoader()
        with pytest.raises(FileNotFoundError):
            loader.load("/nonexistent/file.md")


# ── Test: Chunking ─────────────────────────────────────────────────────────


class TestChunking:
    """Tests for feature-level chunking."""

    def test_chunking_respects_feature_boundaries(self):
        """Verify features that fit in chunk_size stay as single chunks."""
        # Create sections that are each under 512 tokens
        sections = [
            RawSection(
                content="Feature A: This is a short feature description.",
                source="test.md",
                section_title="Feature A",
                hierarchy=["Product", "Feature A"],
            ),
            RawSection(
                content="Feature B: Another short feature description.",
                source="test.md",
                section_title="Feature B",
                hierarchy=["Product", "Feature B"],
            ),
        ]

        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(sections, "tenant-1", "test.md")

        # Each small section should be one chunk
        assert len(chunks) == 2, "Two small sections should produce two chunks"

    def test_chunking_splits_large_sections(self):
        """Verify oversized sections are split with overlap."""
        # Create a section that's way too large for one chunk
        # 512 tokens ~ 2048 chars, so create ~4000 char section
        large_content = " ".join(["This is a sentence about monetization features."] * 200)

        sections = [
            RawSection(
                content=large_content,
                source="test.md",
                section_title="Large Section",
                hierarchy=["Product", "Large Section"],
            ),
        ]

        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(sections, "tenant-1", "test.md")

        # Large section should be split into multiple chunks
        assert len(chunks) > 1, f"Large section should be split, got {len(chunks)} chunks"

    def test_chunking_produces_knowledge_chunks(self):
        """Verify chunks are proper KnowledgeChunk objects."""
        sections = [
            RawSection(
                content="Test content for chunking.",
                source="test.md",
                section_title="Test",
                hierarchy=["Test"],
            ),
        ]

        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(sections, "tenant-1", "test.md")

        assert len(chunks) == 1
        chunk = chunks[0]

        assert isinstance(chunk, KnowledgeChunk)
        assert chunk.tenant_id == "tenant-1"
        assert chunk.content == "Test content for chunking."
        assert isinstance(chunk.metadata, ChunkMetadata)

    def test_chunking_with_real_markdown(self):
        """Test chunking with the sample product markdown."""
        loader = DocumentLoader()
        sections = loader.load(SAMPLE_PRODUCT_MD)

        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(sections, "tenant-1", str(SAMPLE_PRODUCT_MD))

        assert len(chunks) > 0, "Should produce chunks from real markdown"

        # Verify each chunk has content
        for chunk in chunks:
            assert len(chunk.content) > 0


# ── Test: Metadata Extraction ──────────────────────────────────────────────


class TestMetadataExtraction:
    """Tests for metadata extraction."""

    def test_metadata_extraction_from_frontmatter(self):
        """Verify YAML frontmatter metadata is parsed correctly."""
        section = RawSection(
            content="Product description content.",
            source="monetization-platform.md",
            section_title="Overview",
            hierarchy=["Monetization Platform"],
            frontmatter={
                "product_category": "monetization",
                "region": ["global", "emea"],
            },
        )

        extractor = MetadataExtractor()
        metadata = extractor.extract_metadata(section)

        assert metadata.product_category == "monetization"
        assert "global" in metadata.region
        assert "emea" in metadata.region

    def test_metadata_inference_from_content_persona(self):
        """Verify buyer_persona is inferred from content keywords."""
        section = RawSection(
            content="The CTO and VP Engineering will appreciate the API-first architecture.",
            source="test.md",
            section_title="Technical Overview",
            hierarchy=["Product"],
        )

        extractor = MetadataExtractor()
        metadata = extractor.extract_metadata(section)

        assert "technical" in metadata.buyer_persona, (
            f"Should detect technical persona, got {metadata.buyer_persona}"
        )

    def test_metadata_inference_from_content_business_persona(self):
        """Verify business persona is inferred from business keywords."""
        section = RawSection(
            content="The CFO will see strong ROI from our platform. The business case is clear.",
            source="test.md",
            section_title="Business Value",
            hierarchy=["Product"],
        )

        extractor = MetadataExtractor()
        metadata = extractor.extract_metadata(section)

        assert "business" in metadata.buyer_persona

    def test_metadata_inference_sales_stage_negotiation(self):
        """Verify sales_stage is inferred from pricing keywords."""
        section = RawSection(
            content="Enterprise pricing starts at $7,500/month with volume discounts for annual contracts.",
            source="test.md",
            section_title="Pricing",
            hierarchy=["Product", "Pricing"],
        )

        extractor = MetadataExtractor()
        metadata = extractor.extract_metadata(section)

        assert "negotiation" in metadata.sales_stage, (
            f"Should detect negotiation stage, got {metadata.sales_stage}"
        )

    def test_metadata_inference_sales_stage_evaluation(self):
        """Verify evaluation stage detected from competitive keywords."""
        section = RawSection(
            content="Compared to Zuora, our ROI is 3x better. The competitive advantage is clear.",
            source="test.md",
            section_title="Competitive Analysis",
            hierarchy=["Product", "Competitive Positioning"],
        )

        extractor = MetadataExtractor()
        metadata = extractor.extract_metadata(section)

        assert "evaluation" in metadata.sales_stage

    def test_metadata_content_type_from_hierarchy(self):
        """Verify content_type is inferred from section hierarchy."""
        section = RawSection(
            content="Monthly pricing for each tier.",
            source="test.md",
            section_title="Pricing Overview",
            hierarchy=["Product", "Pricing Overview"],
        )

        extractor = MetadataExtractor()
        metadata = extractor.extract_metadata(section)

        assert metadata.content_type == "pricing"

    def test_metadata_content_type_from_filename(self):
        """Verify content_type is inferred from filename conventions."""
        section = RawSection(
            content="Our platform vs competitor analysis.",
            source="monetization-platform-battlecard-vs-zuora.md",
            section_title="Overview",
            hierarchy=["Overview"],
        )

        extractor = MetadataExtractor()
        metadata = extractor.extract_metadata(section)

        assert metadata.content_type == "positioning"

    def test_metadata_overrides(self):
        """Verify overrides dict forces metadata fields."""
        section = RawSection(
            content="Generic content.",
            source="test.md",
            section_title="Test",
            hierarchy=[],
        )

        extractor = MetadataExtractor()
        metadata = extractor.extract_metadata(
            section,
            overrides={
                "product_category": "billing",
                "buyer_persona": ["executive"],
                "content_type": "methodology",
            },
        )

        assert metadata.product_category == "billing"
        assert metadata.buyer_persona == ["executive"]
        assert metadata.content_type == "methodology"


# ── Test: Cross-Reference Detection ────────────────────────────────────────


class TestCrossReferenceDetection:
    """Tests for cross-reference detection in chunks."""

    def test_cross_reference_detection(self):
        """Verify cross-references found when chunk mentions another product."""
        sections = [
            RawSection(
                content="The Subscription Management module integrates with the ESW Charging Platform for metering.",
                source="test.md",
                section_title="Integration",
                hierarchy=["Product"],
            ),
        ]

        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(sections, "tenant-1", "test.md")

        assert len(chunks) == 1
        refs = chunks[0].metadata.cross_references
        # Should detect "Charging Platform" or "Charging"
        charging_found = any("Charging" in ref for ref in refs)
        assert charging_found, f"Should detect Charging cross-reference, got {refs}"

    def test_cross_reference_multiple_products(self):
        """Verify multiple cross-references detected."""
        sections = [
            RawSection(
                content="Integrates with both the Charging Platform and the Billing Platform.",
                source="test.md",
                section_title="Integration",
                hierarchy=["Product"],
            ),
        ]

        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(sections, "tenant-1", "test.md")

        refs = chunks[0].metadata.cross_references
        charging_found = any("Charging" in ref for ref in refs)
        billing_found = any("Billing" in ref for ref in refs)
        assert charging_found, f"Should detect Charging, got {refs}"
        assert billing_found, f"Should detect Billing, got {refs}"


# ── Test: Version Assignment ───────────────────────────────────────────────


class TestVersionAssignment:
    """Tests for version tracking on new chunks."""

    def test_version_assignment(self):
        """Verify new chunks get version=1, is_current=True."""
        sections = [
            RawSection(
                content="Test content.",
                source="test.md",
                section_title="Test",
                hierarchy=[],
            ),
        ]

        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(sections, "tenant-1", "test.md")

        for chunk in chunks:
            assert chunk.metadata.version == 1
            assert chunk.metadata.is_current is True
            assert chunk.metadata.valid_from is not None


# ── Test: Full Pipeline ────────────────────────────────────────────────────


class TestFullPipeline:
    """Integration test for the complete ingestion pipeline."""

    def test_full_pipeline(self):
        """Load -> chunk -> extract metadata -> verify complete KnowledgeChunk objects."""
        # 1. Load
        loader = DocumentLoader()
        sections = loader.load(SAMPLE_PRODUCT_MD)
        assert len(sections) > 0

        # Extract frontmatter for enrichment
        frontmatter = None
        for section in sections:
            if section.frontmatter:
                frontmatter = section.frontmatter
                break

        # 2. Chunk
        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(sections, "tenant-esw", str(SAMPLE_PRODUCT_MD))
        assert len(chunks) > 0

        # 3. Enrich metadata
        extractor = MetadataExtractor()
        enriched = extractor.enrich_chunks(chunks, frontmatter=frontmatter)
        assert len(enriched) == len(chunks)

        # 4. Verify complete KnowledgeChunk objects
        for chunk in enriched:
            assert isinstance(chunk, KnowledgeChunk)
            assert chunk.tenant_id == "tenant-esw"
            assert len(chunk.content) > 0
            assert chunk.id  # UUID assigned
            assert isinstance(chunk.metadata, ChunkMetadata)

            # Metadata should be populated
            assert chunk.metadata.product_category == "monetization"
            assert chunk.metadata.source_document == str(SAMPLE_PRODUCT_MD)
            assert chunk.metadata.version == 1
            assert chunk.metadata.is_current is True
            assert chunk.metadata.content_type in (
                "product",
                "pricing",
                "positioning",
                "methodology",
                "regional",
            )

        # Should have some chunks with inferred personas
        all_personas = set()
        for chunk in enriched:
            all_personas.update(chunk.metadata.buyer_persona)
        assert len(all_personas) > 0, "At least some chunks should have inferred personas"

        # Should have some chunks with cross-references
        all_refs = set()
        for chunk in enriched:
            all_refs.update(chunk.metadata.cross_references)
        assert len(all_refs) > 0, "At least some chunks should have cross-references"

    def test_full_pipeline_json(self):
        """Full pipeline with JSON pricing data."""
        # 1. Load
        loader = DocumentLoader()
        sections = loader.load(SAMPLE_PRICING_JSON)
        assert len(sections) > 0

        # 2. Chunk
        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(
            sections, "tenant-esw", str(SAMPLE_PRICING_JSON)
        )
        assert len(chunks) > 0

        # 3. Enrich
        extractor = MetadataExtractor()
        enriched = extractor.enrich_chunks(chunks)

        # Verify all chunks are valid
        for chunk in enriched:
            assert isinstance(chunk, KnowledgeChunk)
            assert len(chunk.content) > 0
            assert chunk.metadata.version == 1

    def test_enrich_preserves_cross_references(self):
        """Verify enrichment preserves cross-references from chunking."""
        sections = [
            RawSection(
                content="Integrates with the Charging Platform for metering.",
                source="test.md",
                section_title="Integration",
                hierarchy=["Product"],
                frontmatter={"product_category": "monetization"},
            ),
        ]

        chunker = KnowledgeChunker(chunk_size=512, overlap_pct=0.15)
        chunks = chunker.chunk_sections(sections, "tenant-1", "test.md")

        # Chunks should have cross-references before enrichment
        assert len(chunks[0].metadata.cross_references) > 0

        # Enrich should preserve them
        extractor = MetadataExtractor()
        enriched = extractor.enrich_chunks(chunks, frontmatter={"product_category": "monetization"})

        assert len(enriched[0].metadata.cross_references) > 0


# ── Test: Import Verification ──────────────────────────────────────────────


class TestImports:
    """Verify all expected exports are available."""

    def test_ingestion_package_imports(self):
        """Verify all expected classes can be imported from ingestion package."""
        from src.knowledge.ingestion import (
            DocumentLoader,
            KnowledgeChunker,
            MetadataExtractor,
            RawSection,
            load_document,
        )

        assert DocumentLoader is not None
        assert KnowledgeChunker is not None
        assert MetadataExtractor is not None
        assert RawSection is not None
        assert load_document is not None
