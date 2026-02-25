---
phase: 15-collections-agent
plan: 06
subsystem: agents
tags: collections, csm, health-scorer, main-wiring, apscheduler

# Dependency graph
requires:
  - phase: 15-05
    provides: CollectionsAgent and CollectionsScheduler implementation
  - phase: 14-05
    provides: CSM wiring pattern in main.py (template for Phase 15 block)
provides:
  - CollectionsAgent wired in main.py lifespan (app.state.collections)
  - CollectionsScheduler started and stored as app.state.col_scheduler
  - CSMHealthScorer updated with collections_risk cap (CRITICAL=0.80x, RED=0.90x)
  - Cross-agent integration path activated: Collections->CSM risk notification
affects: [phase-16-onwards, any-agent-using-csm-health-scorer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Phase 15 wiring follows exact try/except + AgentRegistration pattern as Phase 14 CSM"
    - "Collections cap applied before TAM cap: raw -> collections_risk cap -> TAM cap -> RAG"

key-files:
  created: []
  modified:
    - src/app/main.py
    - src/app/agents/customer_success/health_scorer.py

key-decisions:
  - "Use AgentRegistration directly (import alias _ColAgentRegistration) matching Phase 14 pattern, not type() trick from plan template"
  - "Collections_risk cap order: BEFORE TAM cap per plan spec — CRITICAL=0.80x, RED=0.90x"
  - "notion_collections=None with inline comment explaining NOTION_COLLECTIONS_* env var requirement"

patterns-established:
  - "Pattern: Collections phase wiring between Phase 14 (CSM) and Phase 5 (Deals) in lifespan"
  - "Pattern: col_scheduler stored on app.state.col_scheduler, stopped in shutdown after csm_scheduler"

# Metrics
duration: 3min
completed: 2026-02-25
---

# Phase 15 Plan 06: Collections Wiring + CSM Health Scorer Cap Summary

**CollectionsAgent wired in main.py lifespan (app.state.collections) and CSMHealthScorer updated with collections_risk cap (CRITICAL=0.80x, RED=0.90x before TAM cap) to activate full cross-agent integration**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-25T18:10:30Z
- **Completed:** 2026-02-25T18:13:05Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- CSMHealthScorer now applies collections_risk cap (CRITICAL→0.80x, RED→0.90x) before TAM cap, completing the Collections→CSM integration path
- CollectionsAgent wired in main.py lifespan between Phase 14 (CSM) and Phase 5 (Deals) following the exact try/except pattern
- CollectionsScheduler started and stored on app.state.col_scheduler; shutdown cleanup added after CSM scheduler stop
- notion_collections=None with inline documentation explaining NOTION_COLLECTIONS_* env var activation path

## Task Commits

Each task was committed atomically:

1. **Task 1: Update CSMHealthScorer with collections_risk cap** - `064c6c8` (feat)
2. **Task 2: Wire CollectionsAgent into main.py lifespan** - `51d48bf` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/app/agents/customer_success/health_scorer.py` - Added collections_risk cap (CRITICAL=0.80x, RED=0.90x) before TAM cap in score() method; updated module docstring, class docstring, and step comments
- `src/app/main.py` - Phase 15 Collections wiring block (import, registration, agent instantiation, scheduler start, app.state.collections); Collections scheduler stop in shutdown section

## Decisions Made

- Used `AgentRegistration` direct import alias (`_ColAgentRegistration`) matching Phase 14's pattern, rather than the `type()` trick shown in the plan template — keeps wiring pattern consistent across all phases
- `capabilities=[]` in registration (same as Phase 14 CSM) since capabilities are declared in `_TASK_HANDLERS` dict, not registration metadata
- Collections cap applied strictly before TAM cap per plan spec: raw → collections_risk cap → TAM cap → RAG derivation

## Deviations from Plan

None - plan executed exactly as written.

The only minor adaptation: used `AgentRegistration` direct import alias (same as Phase 14) rather than `type()` subclass trick shown in plan template. The plan template was illustrative; the actual pattern in the codebase uses direct import. No behavior difference.

## Issues Encountered

- `python -m pytest tests/test_csm_health_scorer.py` fails with pre-existing SQLAlchemy `MappedAnnotationError` on Python 3.9 (conftest imports `create_app` which triggers model loading). Pre-existing before this plan; confirmed by stash verification. The collections_risk cap logic was verified directly with correct multipliers (CRITICAL=0.80x, RED=0.90x confirmed).

## User Setup Required

None - no external service configuration required. Note: NotionCollectionsAdapter requires NOTION_COLLECTIONS_AR_DATABASE_ID, NOTION_COLLECTIONS_ESCALATION_DATABASE_ID, and NOTION_COLLECTIONS_EVENTS_DATABASE_ID env vars. Until those are set, `notion_collections=None` and the agent runs in degraded mode (handlers return fail-open responses).

## Next Phase Readiness

- Phase 15 plan 07 (final plan: integration tests + verification) is ready to execute
- All wiring is in place: app.state.collections, app.state.col_scheduler, CSMHealthScorer cap
- No blockers

---
*Phase: 15-collections-agent*
*Completed: 2026-02-25*
