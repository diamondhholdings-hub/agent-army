---
phase: 14-customer-success-agent
plan: 06
subsystem: testing
tags: [pytest, asyncio, mock, csm, notion, health-scorer, prompt-builders]

# Dependency graph
requires:
  - phase: 14-03
    provides: CSM agent handlers and execute() routing
  - phase: 14-04
    provides: CSM wiring confirmation and health scorer integration
provides:
  - 24 tests covering CSM handler routing, prompt builders, and Notion adapter
  - Regression safety for CSM agent behavior
affects: [15-presales-engineer-agent, 16-training-specialist-agent]

# Tech tracking
tech-stack:
  added: []
  patterns: [real-scorer-in-tests, mock-notion-asyncclient, fail-open-assertion]

key-files:
  created:
    - tests/test_csm_handlers.py
    - tests/test_csm_prompt_builders.py
    - tests/test_csm_notion_adapter.py
  modified: []

key-decisions:
  - "Real CSMHealthScorer in handler tests (not mocked) -- pure Python, deterministic"
  - "Mock Notion AsyncClient at method level (pages.retrieve, pages.create, etc.)"
  - "Patched get_settings for NotionCSMAdapter to avoid env dependency"

patterns-established:
  - "CSM test fixtures: _make_csm_agent() with configurable deps, _make_mock_notion() with standard returns"
  - "Fail-open assertion pattern: error key + confidence=low + partial=True"

# Metrics
duration: 3min
completed: 2026-02-25
---

# Phase 14 Plan 06: CSM Agent Test Suite Summary

**24 pytest tests covering handler routing (10), prompt builders (7), and NotionCSMAdapter CRUD (7) with real health scorer and mocked external dependencies**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-25T06:12:18Z
- **Completed:** 2026-02-25T06:15:16Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments
- 10 handler tests proving task routing, health scan uses real scorer (no LLM), QBR calls LLM + Notion, expansion dispatches to sales agent, fail-open on exceptions
- 7 prompt builder tests validating string output with embedded JSON schema fields for all 5 CSM capabilities
- 7 Notion adapter tests proving get_account returns id + account_id, create_qbr_page uses database_id parent, render_qbr_blocks produces 4+ blocks

## Task Commits

Each task was committed atomically:

1. **Task 1: Write CSM handler and prompt builder tests** - `e8fd1c2` (test)
2. **Task 2: Write NotionCSMAdapter mock tests** - `03e1675` (test)

## Files Created/Modified
- `tests/test_csm_handlers.py` - 10 handler routing and behavior tests (TestCSMHandlers class)
- `tests/test_csm_prompt_builders.py` - 7 prompt builder output validation tests (TestCSMPromptBuilders class)
- `tests/test_csm_notion_adapter.py` - 7 Notion adapter mock tests (TestNotionCSMAdapter class)

## Decisions Made
- Used real CSMHealthScorer in handler tests (not mocked) since it is pure Python and deterministic, matching the established pattern from TAM tests (13-04)
- Patched get_settings() in NotionCSMAdapter tests to avoid environment variable dependency while still testing real adapter logic
- Used call_args inspection to verify QBRContent instance passed to create_qbr_page and database_id parent structure

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- CSM agent fully tested: schemas (14-01), health scorer (14-04), handlers + prompts + Notion adapter (14-06)
- Ready for 14-07 if it exists, or phase completion

---
*Phase: 14-customer-success-agent*
*Completed: 2026-02-25*
