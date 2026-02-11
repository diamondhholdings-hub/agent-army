---
phase: 03-knowledge-base
plan: 05
subsystem: knowledge
tags: [meddic, bant, spin, sales-methodology, regional-nuances, qdrant, pydantic, semantic-search]

# Dependency graph
requires:
  - phase: 03-01
    provides: Qdrant vector DB, EmbeddingService, QdrantKnowledgeStore, KnowledgeChunk models
provides:
  - MethodologyLibrary with MEDDIC, BANT, SPIN structured access
  - MethodologyLoader for ingesting methodology + regional content into Qdrant
  - RegionalNuances with APAC, EMEA, Americas pricing/compliance/cultural data
  - Markdown content for 3 methodologies (540 lines) and 3 regions (392 lines)
affects:
  - 03-06 (conversations may reference methodology context)
  - 03-07 (retrieval pipeline will use methodology and regional search)
  - Phase 4 (Sales Agent will query methodology frameworks and regional nuances)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MethodologyLibrary pattern: structured Pydantic models with pre-populated data"
    - "MethodologyLoader: markdown chunking at ## level with metadata classification"
    - "RegionalNuances: module-level convenience function wrapping class instance"
    - "FusionQuery(fusion=Fusion.RRF) for Python 3.13 compatible hybrid search"

key-files:
  created:
    - src/knowledge/methodology/frameworks.py
    - src/knowledge/methodology/loader.py
    - src/knowledge/regional/__init__.py
    - src/knowledge/regional/nuances.py
    - data/methodology/meddic.md
    - data/methodology/bant.md
    - data/methodology/spin.md
    - data/regional/apac.md
    - data/regional/emea.md
    - data/regional/americas.md
    - tests/knowledge/test_methodology.py
    - tests/knowledge/test_regional.py
  modified:
    - src/knowledge/qdrant_client.py

key-decisions:
  - "Methodology frameworks pre-populated in MethodologyLibrary constructor (no external config)"
  - "Markdown chunked at ## heading level for optimal search granularity"
  - "Regional pricing modifiers: APAC=0.9, EMEA=1.0, Americas=1.0"
  - "FusionQuery(fusion=Fusion.RRF) replaces broken Query(fusion='rrf') for Python 3.13"

patterns-established:
  - "Dual-access pattern: Pydantic models for structured programmatic access + markdown for semantic search"
  - "Section-level chunking: ## headings as natural chunk boundaries for methodology content"
  - "Region-coded metadata: chunks tagged with region code for filtered retrieval"

# Metrics
duration: 13min
completed: 2026-02-11
---

# Phase 3 Plan 5: Sales Methodology and Regional Nuances Summary

**MEDDIC/BANT/SPIN frameworks as Pydantic models + Qdrant-searchable markdown, plus APAC/EMEA/Americas regional nuances with pricing modifiers and compliance data**

## Performance

- **Duration:** 13 min
- **Started:** 2026-02-11T19:36:47Z
- **Completed:** 2026-02-11T19:50:13Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments
- Three sales methodology frameworks (MEDDIC, BANT, SPIN) with structured Pydantic models providing step-level access to questions, examples, and tips
- MethodologyLoader ingests methodology and regional markdown into Qdrant with metadata tagging (content_type, sales_stage, region)
- RegionalNuances provides programmatic access to APAC/EMEA/Americas cultural guidance, pricing modifiers, and compliance frameworks
- Fixed pre-existing hybrid_search bug (Query type alias incompatible with Python 3.13) -- all 55 knowledge tests now pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Create methodology frameworks and content documents** - `98bbac6` (feat)
2. **Task 2: Create regional nuances and ingest methodology + regional content into Qdrant** - `20860e6` (feat)

## Files Created/Modified
- `src/knowledge/methodology/frameworks.py` - Pydantic models for MEDDIC, BANT, SPIN with MethodologyLibrary
- `src/knowledge/methodology/loader.py` - MethodologyLoader ingests markdown into Qdrant with metadata
- `src/knowledge/regional/nuances.py` - RegionalNuances with APAC/EMEA/Americas config and pricing modifiers
- `src/knowledge/regional/__init__.py` - Regional module exports
- `data/methodology/meddic.md` - 223-line MEDDIC framework reference with examples and tips
- `data/methodology/bant.md` - 147-line BANT framework reference with modern adaptations
- `data/methodology/spin.md` - 170-line SPIN selling reference with question progression
- `data/regional/apac.md` - 114-line APAC sales guide (cultural, pricing, compliance)
- `data/regional/emea.md` - 130-line EMEA sales guide (GDPR, sub-regional variation)
- `data/regional/americas.md` - 148-line Americas sales guide (US/Canada/LATAM)
- `tests/knowledge/test_methodology.py` - 21 tests for structured access + ingestion
- `tests/knowledge/test_regional.py` - 22 tests for regional access + ingestion
- `src/knowledge/qdrant_client.py` - Fixed Query -> FusionQuery for Python 3.13

## Decisions Made
- **Methodology frameworks pre-populated in constructor:** No external config needed -- content is universal across all tenants. Adding new frameworks requires code change (acceptable for core sales methodologies that rarely change).
- **Markdown chunked at ## level:** Each ## section becomes one Qdrant chunk. This provides optimal granularity -- specific enough for targeted search results, broad enough for coherent context.
- **Regional pricing modifiers:** APAC gets 10% discount (0.9x), EMEA and Americas at baseline (1.0x). These match the plan specification and common enterprise SaaS regional pricing norms.
- **FusionQuery replaces Query:** The `qdrant_client.models.Query` is a Union type alias in newer versions, not instantiable on Python 3.13. Using `FusionQuery(fusion=Fusion.RRF)` is the correct API.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed hybrid_search Query type incompatibility with Python 3.13**
- **Found during:** Task 2 (running tests)
- **Issue:** `Query(fusion="rrf")` raises `TypeError: Cannot instantiate typing.Union` on Python 3.13 because `Query` in `qdrant_client.models` is a `typing.Union` type alias, not a class.
- **Fix:** Replaced with `FusionQuery(fusion=Fusion.RRF)` which is the correct concrete class for fusion queries.
- **Files modified:** `src/knowledge/qdrant_client.py`
- **Verification:** All 55 knowledge tests pass (12 existing + 43 new), including hybrid_search tests that were previously broken.
- **Committed in:** `20860e6` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Fix was necessary for all hybrid search functionality. This was a pre-existing bug affecting the 03-01 test suite. No scope creep.

## Issues Encountered
None beyond the pre-existing bug documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Methodology frameworks (MEDDIC, BANT, SPIN) ready for agent consumption via MethodologyLibrary or Qdrant search
- Regional nuances ready for agent consumption via RegionalNuances or Qdrant search with region filters
- MethodologyLoader.load_all() can be called during application startup to populate Qdrant
- All content is universal (tenant-agnostic) but stored per-tenant for isolation

---
*Phase: 03-knowledge-base*
*Completed: 2026-02-11*
