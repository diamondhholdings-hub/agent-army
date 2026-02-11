---
phase: 03-knowledge-base
plan: 02
subsystem: knowledge-ingestion
tags: [langchain, tiktoken, chunking, metadata, document-parsing, yaml, pydantic]

# Dependency graph
requires:
  - phase: 03-01
    provides: "KnowledgeChunk, ChunkMetadata, TenantConfig models; pyproject.toml package structure"
provides:
  - "DocumentLoader with factory pattern for MD, PDF, DOCX, JSON, CSV, TXT"
  - "KnowledgeChunker with token-based feature-level chunking (512 tokens, 15% overlap)"
  - "MetadataExtractor with multi-signal inference (frontmatter, hierarchy, content, filename)"
  - "RawSection model for intermediate document representation"
  - "Cross-reference detection against known product names"
  - "Realistic ESW product fixtures for testing"
affects: ["03-03", "03-04", "03-05", "03-06", "03-07"]

# Tech tracking
tech-stack:
  added: ["langchain-text-splitters", "pyyaml", "chardet"]
  patterns: ["factory-pattern document loading", "token-based chunking with feature-level boundaries", "multi-signal metadata inference", "deepest-first hierarchy parsing"]

key-files:
  created:
    - "src/knowledge/ingestion/__init__.py"
    - "src/knowledge/ingestion/loaders.py"
    - "src/knowledge/ingestion/chunker.py"
    - "src/knowledge/ingestion/metadata_extractor.py"
    - "tests/knowledge/test_ingestion.py"
    - "tests/knowledge/fixtures/sample_product.md"
    - "tests/knowledge/fixtures/sample_pricing.json"
  modified:
    - "pyproject.toml"

key-decisions:
  - "RecursiveCharacterTextSplitter with [newline-newline, newline, period-space, space] separators"
  - "Token counting via tiktoken cl100k_base with 4.0 chars/token estimate for LangChain char-based splitter"
  - "Deepest-first hierarchy parsing for content_type inference (specific headers win over generic parents)"
  - "PDF/DOCX loaders use lazy imports with clear error messages if unstructured not installed"
  - "Cross-reference detection uses both full names and short names (Charging Platform + Charging)"
  - "Metadata enrichment preserves version, cross_references, and timestamps from chunker"

patterns-established:
  - "Factory pattern: DocumentLoader dispatches to format-specific loaders based on file extension"
  - "Pipeline pattern: load_document() -> chunk_sections() -> enrich_chunks() produces complete KnowledgeChunks"
  - "Multi-signal inference: frontmatter > hierarchy > filename > content keywords for metadata"
  - "Feature-level chunking: small sections kept intact, only oversized sections split"

# Metrics
duration: 9min
completed: 2026-02-11
---

# Phase 3 Plan 02: Document Ingestion Summary

**Multi-format document ingestion pipeline with feature-level chunking, cross-reference detection, and multi-signal metadata extraction for ESW product knowledge**

## Performance

- **Duration:** 9 min
- **Started:** 2026-02-11T19:35:32Z
- **Completed:** 2026-02-11T19:44:49Z
- **Tasks:** 2/2
- **Files created:** 7
- **Files modified:** 1

## Accomplishments
- DocumentLoader handles 6 formats (MD, PDF, DOCX, JSON, CSV, TXT) with factory pattern and encoding detection
- KnowledgeChunker produces feature-level chunks with 512-token target, 15% overlap, respecting section boundaries
- MetadataExtractor infers product_category, buyer_persona, sales_stage, region, content_type from multiple signals
- Cross-reference detection finds mentions of Monetization, Charging, and Billing products
- 32 tests all passing with realistic ESW Monetization Platform fixture (~2000 words) and pricing JSON

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement document loaders and feature-level chunker** - `af99864` (feat)
2. **Task 2: Implement metadata extractor and test with fixtures** - `5d4d1db` (feat)

## Files Created/Modified
- `src/knowledge/ingestion/__init__.py` - Package exports: DocumentLoader, KnowledgeChunker, MetadataExtractor, RawSection, load_document
- `src/knowledge/ingestion/loaders.py` - DocumentLoader with factory pattern, RawSection model, format-specific parsers
- `src/knowledge/ingestion/chunker.py` - KnowledgeChunker with token-based sizing, feature-level strategy, cross-reference detection
- `src/knowledge/ingestion/metadata_extractor.py` - MetadataExtractor with frontmatter, hierarchy, filename, content keyword inference
- `tests/knowledge/test_ingestion.py` - 32 tests covering loading, chunking, metadata extraction, cross-refs, full pipeline
- `tests/knowledge/fixtures/sample_product.md` - Realistic ESW Monetization Platform document with frontmatter and multiple sections
- `tests/knowledge/fixtures/sample_pricing.json` - Tiered pricing structure with regional variations and add-ons
- `pyproject.toml` - Added langchain-text-splitters, pyyaml, chardet dependencies

## Decisions Made
- **RecursiveCharacterTextSplitter separators:** Used `["\n\n", "\n", ". ", " "]` for natural text boundaries
- **Token estimation:** 4.0 chars/token ratio for cl100k_base encoding, used to convert token-based chunk_size to character-based LangChain splitter
- **Deepest-first hierarchy parsing:** When inferring content_type from hierarchy, iterate from deepest header upward so "Pricing Overview" beats "Product" as parent
- **Lazy PDF/DOCX imports:** `unstructured` library imported lazily with clear ImportError guidance, avoiding heavy dependency for non-PDF/DOCX workflows
- **Cross-reference granularity:** Both full names ("Charging Platform") and short names ("Charging") are detected separately, giving consumers flexibility
- **Metadata enrichment preservation:** enrich_chunks() preserves version, valid_from, is_current, cross_references, and source_document from the original chunker output

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed PayloadIndexParams import in qdrant_client.py**
- **Found during:** Task 1 (import verification)
- **Issue:** `PayloadIndexParams` was removed/renamed in qdrant-client 1.16.x; import from `src.knowledge.__init__` cascaded to qdrant_client.py and failed
- **Fix:** Replaced `PayloadIndexParams` with `KeywordIndexParams` from `qdrant_client.http.models.models`
- **Files modified:** src/knowledge/qdrant_client.py
- **Verification:** `from src.knowledge.ingestion import DocumentLoader, KnowledgeChunker` succeeds
- **Committed in:** af99864 (part of Task 1 -- pyproject.toml also captured this)

**2. [Rule 3 - Blocking] Installed missing Python dependencies**
- **Found during:** Task 1 (environment setup)
- **Issue:** langchain-text-splitters, pyyaml, chardet, qdrant-client not installed in venv
- **Fix:** Ran `pip install` for each; bootstrapped pip in venv with ensurepip; added to pyproject.toml
- **Files modified:** pyproject.toml
- **Verification:** All imports succeed
- **Committed in:** af99864 (Task 1 commit)

**3. [Rule 1 - Bug] Fixed hierarchy content_type inference priority**
- **Found during:** Task 2 (test_metadata_content_type_from_hierarchy)
- **Issue:** Forward iteration through hierarchy matched "Product" parent before "Pricing Overview" child, returning "product" instead of "pricing"
- **Fix:** Reversed iteration order so deepest (most specific) headers are checked first
- **Files modified:** src/knowledge/ingestion/metadata_extractor.py
- **Verification:** test passes, hierarchy ["Product", "Pricing Overview"] now correctly returns "pricing"
- **Committed in:** 5d4d1db (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (1 bug, 2 blocking)
**Impact on plan:** All auto-fixes necessary for correct operation. No scope creep.

## Issues Encountered
- Previous session (03-01) left commits pending in STATE.md. Committed those files before proceeding with 03-02 work.
- qdrant-client 1.16.x removed `PayloadIndexParams` API from 03-01 code. Fixed with `KeywordIndexParams` equivalent.

## User Setup Required
None - no external service configuration required. All tests run without external services.

## Next Phase Readiness
- Ingestion pipeline complete: load -> chunk -> enrich produces full KnowledgeChunk objects
- Ready for Plan 03 (Qdrant storage integration) to wire ingestion output into vector storage
- Ready for Plan 04+ to add retrieval pipelines that consume enriched chunks
- PDF and Word loading requires `unstructured[all-docs]` installation (not yet installed, lazy import)

---
*Phase: 03-knowledge-base*
*Completed: 2026-02-11*
