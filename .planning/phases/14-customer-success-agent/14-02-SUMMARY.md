---
phase: 14-customer-success-agent
plan: 02
subsystem: agent-infrastructure
tags: [health-scoring, notion-adapter, csm, churn-risk, deterministic, pydantic]

# Dependency graph
requires:
  - phase: 14-01
    provides: "CSM schemas (CSMHealthSignals, CSMHealthScore, QBRContent, ExpansionOpportunity)"
  - phase: 13-03
    provides: "TAM HealthScorer keyword-only constructor pattern, NotionTAMAdapter CRUD pattern"
provides:
  - "CSMHealthScorer: deterministic 11-signal health scoring with TAM correlation cap"
  - "NotionCSMAdapter: 6 async CRUD methods for health records, QBR pages, expansion opportunities"
  - "3 block renderers: render_health_record_blocks, render_qbr_blocks, render_expansion_blocks"
affects: [14-03, 14-04, 14-05, 14-06, 14-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Weighted signal scoring with TAM cross-agent correlation cap"
    - "Churn risk dual-trigger assessment (contract_proximity + behavioral)"
    - "NotionCSMAdapter mirrors NotionTAMAdapter: pre-authenticated AsyncClient, tenacity retry, module-level renderers"

key-files:
  created:
    - src/app/agents/customer_success/health_scorer.py
    - src/app/agents/customer_success/notion_adapter.py
  modified: []

key-decisions:
  - "Support combined weight 10 merges sentiment base with open_ticket_count deduction (min 5 tickets cap)"
  - "get_account returns both id and account_id keys for agent.py compatibility (mirrors TAM pattern)"
  - "get_health_record queries by Account ID rich_text property, sorted descending by created_time"

patterns-established:
  - "CSM signal scoring: static methods per signal, breakdown dict, TAM cap post-processing"
  - "CSM Notion adapter: settings-driven database IDs, 100-block batch creation"

# Metrics
duration: 4min
completed: 2026-02-25
---

# Phase 14 Plan 02: CSM Health Scorer & Notion Adapter Summary

**Deterministic 11-signal CSM health scorer with TAM correlation cap, churn risk dual-trigger assessment, and NotionCSMAdapter with 6 async CRUD methods for health records, QBR pages, and expansion opportunities**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-25T05:47:30Z
- **Completed:** 2026-02-25T05:51:42Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- CSMHealthScorer computes 0-100 health score from 11 weighted signals (total weight = 100) with per-tenant configurable thresholds
- TAM correlation cap reduces score by 15% (RED) or 5% (AMBER) when TAM health is degraded
- Churn risk assessment identifies contract_proximity, behavioral, or both triggers with appropriate severity levels
- NotionCSMAdapter provides 6 async methods covering full CRUD for CSM-specific Notion databases
- 3 module-level block renderers produce structured Notion content for health records, QBR pages, and expansion opportunities

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CSMHealthScorer -- deterministic 11-signal scoring** - `eb8c23d` (feat)
2. **Task 2: Create NotionCSMAdapter with full CRUD** - `4d3138d` (feat)

## Files Created/Modified
- `src/app/agents/customer_success/health_scorer.py` - CSMHealthScorer class with 11 signal scorers, TAM cap, churn risk assessment
- `src/app/agents/customer_success/notion_adapter.py` - NotionCSMAdapter with 6 async methods + 3 block renderers

## Decisions Made
- Support signal (weight 10) combines avg_ticket_sentiment base score with open_ticket_count deduction (capped at 5 tickets * 1 point, floor at 0) -- simpler than separate signals while capturing both dimensions
- get_account returns both `id` and `account_id` keys for agent.py compatibility, matching the established NotionTAMAdapter pattern (13-06)
- get_health_record queries NOTION_CSM_HEALTH_DATABASE_ID by "Account ID" rich_text property, sorted by created_time descending, returning only the latest record

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Health scorer and Notion adapter are ready for consumption by CSM agent handlers (plan 14-03)
- CSM agent.py can now orchestrate health scans, QBR generation, and expansion checks
- All schema types from 14-01 are fully utilized by both components

---
*Phase: 14-customer-success-agent*
*Completed: 2026-02-25*
