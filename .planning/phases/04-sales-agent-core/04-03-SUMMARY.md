---
phase: 04-sales-agent-core
plan: 03
subsystem: database, sales-agent
tags: [sqlalchemy, postgresql, instructor, litellm, pydantic, bant, meddic, qualification]

# Dependency graph
requires:
  - phase: 04-02
    provides: "BANTSignals, MEDDICSignals, QualificationState, ConversationState schemas and prompt builders"
  - phase: 01-02
    provides: "LLMService with LiteLLM Router for model routing"
  - phase: 01-01
    provides: "TenantBase, Alembic tenant migration chain, multi-tenant database"
provides:
  - "ConversationStateModel (SQLAlchemy) for tenant-scoped conversation persistence"
  - "ConversationStateRepository with async get/save/list/update_qualification CRUD"
  - "QualificationExtractor: instructor+LiteLLM structured BANT+MEDDIC extraction"
  - "Incremental merge functions: merge_bant_signals, merge_meddic_signals, merge_qualification_signals"
  - "Deal stage transition validation (VALID_TRANSITIONS map)"
  - "Alembic migration 004 for conversation_states table with RLS and indexes"
affects: [04-04, 04-05]

# Tech tracking
tech-stack:
  added: [instructor]
  patterns:
    - "Structured LLM output via instructor.from_litellm(litellm.acompletion)"
    - "Incremental qualification merge: higher-confidence wins, evidence always appends"
    - "Fail-open on LLM extraction errors (returns existing state unchanged)"
    - "Deal stage transition map with InvalidStageTransitionError"

key-files:
  created:
    - "src/app/models/sales.py"
    - "alembic/versions/add_sales_conversation_state.py"
    - "src/app/agents/sales/state_repository.py"
    - "src/app/agents/sales/qualification.py"
    - "tests/test_sales_state.py"
  modified: []

key-decisions:
  - "instructor.from_litellm(litellm.acompletion) for async structured extraction"
  - "Single LLM call for all BANT+MEDDIC signals (not per-field calls)"
  - "Evidence always appended with ' | ' separator, never replaced"
  - "STALLED can transition to any active stage (resume from stall)"
  - "Terminal stages (CLOSED_WON, CLOSED_LOST) have no outbound transitions"
  - "qualification_data stored as JSON column for schema evolution flexibility"

patterns-established:
  - "Incremental merge: _pick_by_confidence selects value from higher-confidence source"
  - "Deal stage transition validation via VALID_TRANSITIONS dict before save"
  - "Repository uses session_factory callable for testable async CRUD"

# Metrics
duration: 5min
completed: 2026-02-12
---

# Phase 4 Plan 3: Conversation State Persistence and Qualification Extraction Summary

**ConversationStateModel with tenant-scoped PostgreSQL persistence, instructor-powered BANT/MEDDIC extraction, and incremental qualification merge logic**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-12T03:39:24Z
- **Completed:** 2026-02-12T03:44:31Z
- **Tasks:** 2
- **Files created:** 5

## Accomplishments
- ConversationStateModel persists to tenant-scoped PostgreSQL with RLS, indexed on (tenant_id, account_id) and (tenant_id, deal_stage)
- ConversationStateRepository provides async get/save/list/update_qualification with JSON serialization roundtrip
- QualificationExtractor uses instructor + LiteLLM for structured BANT+MEDDIC extraction in a single LLM call
- Incremental merge preserves higher-confidence data, appends evidence, extends list fields, deduplicates insights
- Deal stage transitions validated against VALID_TRANSITIONS map (no illegal jumps)
- 17 tests covering model instantiation, serialization, roundtrip, stage transitions, and transition completeness

## Task Commits

Each task was committed atomically:

1. **Task 1: Create conversation state database model, migration, and repository** - `f19850f` (feat)
2. **Task 2: Create qualification signal extraction with instructor + merge logic** - `c69602e` (feat)

## Files Created/Modified
- `src/app/models/sales.py` - ConversationStateModel (TenantBase) with qualification_data JSON column
- `alembic/versions/add_sales_conversation_state.py` - Migration 004 with RLS, indexes on tenant_id+account_id and tenant_id+deal_stage
- `src/app/agents/sales/state_repository.py` - ConversationStateRepository (get/save/list/update_qualification), VALID_TRANSITIONS, stage validation
- `src/app/agents/sales/qualification.py` - QualificationExtractor, merge_bant_signals, merge_meddic_signals, merge_qualification_signals
- `tests/test_sales_state.py` - 17 tests for model, serialization, stage transitions

## Decisions Made
- [04-03]: instructor.from_litellm(litellm.acompletion) for async structured extraction (not instructor.patch)
- [04-03]: Single LLM call for all BANT+MEDDIC signals (anti-pattern: no per-field calls)
- [04-03]: Evidence always appended with ' | ' separator to accumulate conversation history
- [04-03]: STALLED can transition to any active stage (resume from stall); terminal stages have no outbound transitions
- [04-03]: qualification_data stored as JSON column (not normalized) for schema evolution flexibility
- [04-03]: Repository uses session_factory callable pattern for testable async CRUD
- [04-03]: _pick_by_confidence helper: new identified signal overrides unidentified; ties go to existing

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing instructor dependency**
- **Found during:** Task 2 (qualification extraction)
- **Issue:** instructor package not installed in venv, import failing
- **Fix:** Ran `python -m pip install instructor`
- **Files modified:** (venv only, no project file changes needed -- instructor already in project deps)
- **Verification:** `import instructor` succeeds, version 1.14.4
- **Committed in:** c69602e (part of Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary for instructor import. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ConversationStateModel and Repository ready for SalesAgent composition in Plan 04
- QualificationExtractor ready for integration into agent conversation loop
- Merge logic ensures qualification signals accumulate across interactions without data loss
- Deal stage validation prevents illegal transitions in the sales pipeline

---
*Phase: 04-sales-agent-core*
*Completed: 2026-02-12*
