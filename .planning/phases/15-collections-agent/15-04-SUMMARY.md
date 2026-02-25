---
phase: 15-collections-agent
plan: 04
subsystem: database
tags: [notion, collections, ar-aging, escalation, async, pydantic, tenacity]

# Dependency graph
requires:
  - phase: 15-01
    provides: Collections schemas (ARAgingReport, EscalationState, ARAgingBucket)
  - phase: 14
    provides: NotionCSMAdapter pattern (pre-authenticated client, module-level renderers, fail-open)
provides:
  - NotionCollectionsAdapter with 6 async methods for AR aging, escalation state, payment plans, and event logging
  - 3 NOTION_COLLECTIONS_* config fields + FINANCE_TEAM_EMAIL in Settings
  - Module-level block renderer helpers (_make_heading, _make_paragraph, _make_option_bullet)
affects: [15-05, 15-06, 15-07, scheduler, agent-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "NotionCollectionsAdapter follows pre-authenticated AsyncClient constructor pattern (same as CSM/TAM)"
    - "All methods fail-open: public method catches exceptions, logs, returns safe default; retry logic in private _method"
    - "Keyword-only constructor args (ar_database_id, escalation_database_id, events_database_id) enforce explicit DB wiring"
    - "Module-level block renderers decoupled from adapter class"

key-files:
  created:
    - src/app/agents/collections/notion_adapter.py
  modified:
    - src/app/config.py

key-decisions:
  - "NotionCollectionsAdapter uses same pre-authenticated AsyncClient + keyword-only DB ID pattern as NotionCSMAdapter"
  - "6 public methods each wrap a private retry-decorated _method for clean fail-open separation"
  - "get_ar_aging groups invoices into 4 buckets (0-30, 31-60, 61-90, 90+) by days_overdue field from Notion"
  - "get_all_delinquent_accounts deduplicates by account_id and aggregates total_outstanding_usd + max days_overdue"
  - "create_payment_plan_page writes to events_db (not a separate payments DB) as a structured event page"
  - "log_collection_event is append-only to events_db with no updates to existing pages"

patterns-established:
  - "Fail-open split: public method = try/except + log.exception + safe default; private _method = @retry decorated"
  - "EscalationState defaults to stage=0 when Notion record not found (not None, not error)"

# Metrics
duration: 3min
completed: 2026-02-25
---

# Phase 15 Plan 04: NotionCollectionsAdapter + Config Fields Summary

**NotionCollectionsAdapter with 6 async fail-open methods for AR aging, escalation state upsert, payment plan pages, and append-only event logging, plus 3 NOTION_COLLECTIONS_* settings and FINANCE_TEAM_EMAIL**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-25T17:47:38Z
- **Completed:** 2026-02-25T17:50:11Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added 4 new Settings fields: `NOTION_COLLECTIONS_AR_DATABASE_ID`, `NOTION_COLLECTIONS_ESCALATION_DATABASE_ID`, `NOTION_COLLECTIONS_EVENTS_DATABASE_ID`, `FINANCE_TEAM_EMAIL`
- Created `NotionCollectionsAdapter` (832 lines) following the NotionCSMAdapter pattern exactly: pre-authenticated AsyncClient, keyword-only DB IDs, module-level block renderers
- 6 async methods: `get_ar_aging`, `get_all_delinquent_accounts`, `get_escalation_state`, `update_escalation_state`, `create_payment_plan_page`, `log_collection_event`
- All methods fail-open with the clean public/private split pattern (public catches + returns default, private has @retry)
- 3 module-level block renderer helpers: `_make_heading`, `_make_paragraph`, `_make_option_bullet`

## Task Commits

Each task was committed atomically:

1. **Task 1: Add 3 NOTION_COLLECTIONS_* config fields + FINANCE_TEAM_EMAIL** - `ed17d90` (feat)
2. **Task 2: Create NotionCollectionsAdapter with 6 async methods** - `db08b88` (feat)

**Plan metadata:** `(docs commit follows)`

## Files Created/Modified

- `src/app/config.py` - Added 4 new Settings fields under "Notion Collections Agent Databases -- Phase 15" comment block
- `src/app/agents/collections/notion_adapter.py` - Full NotionCollectionsAdapter (832 lines), 6 async methods, module-level helpers

## Decisions Made

- `create_payment_plan_page` writes to `_events_db` (not a dedicated payment plans DB) since the plan spec only defines 3 DB IDs; events DB serves as both event log and structured page store
- `get_all_delinquent_accounts` deduplicates by `account_id` and tracks `max(days_overdue)` per account for scheduler priority ordering
- `EscalationState(account_id=account_id)` returned as default when Notion record not found — clean default with stage=0, no None ambiguity
- Private `_fetch_*` / `_query_*` / `_upsert_*` / `_append_*` naming convention for retry-decorated internals keeps public API clean

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required beyond Notion DB IDs already in Settings.

## Next Phase Readiness

- `NotionCollectionsAdapter` is ready for use in Collections agent.py (15-05)
- All 3 NOTION_COLLECTIONS_* settings fields + FINANCE_TEAM_EMAIL available in `get_settings()`
- Follows established adapter pattern — new agent devs can copy constructor pattern directly from CSM/TAM

---
*Phase: 15-collections-agent*
*Completed: 2026-02-25*
