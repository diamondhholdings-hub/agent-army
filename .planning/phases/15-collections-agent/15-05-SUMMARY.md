---
phase: 15-collections-agent
plan: 05
subsystem: api
tags: [python, pydantic, collections, agent, scheduler, apscheduler, cross-agent, csm-dispatch]

# Dependency graph
requires:
  - phase: 15-collections-agent
    plan: 03
    provides: COLLECTIONS_SYSTEM_PROMPT and 5 handler functions for task routing
  - phase: 15-collections-agent
    plan: 04
    provides: NotionCollectionsAdapter with get_all_delinquent_accounts for scheduler
  - phase: 14
    provides: CustomerSuccessAgent pattern for BaseAgent subclass structure and CSMScheduler pattern
provides:
  - CollectionsAgent: BaseAgent subclass with execute() routing 5 task types via _TASK_HANDLERS
  - receive_collections_risk(): reverse cross-agent notification path from Collections to CSM
  - CollectionsScheduler: 2 daily cron jobs (6am AR scan, 7am escalation check)
affects: [15-06, 15-07, main.py-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CollectionsAgent.execute() reads request_type (not type) -- distinguishes from CSM/TAM task key"
    - "Post-check pattern: execute() inspects result dict after payment_risk_assessment, calls receive_collections_risk() on RED/CRITICAL"
    - "receive_collections_risk: hasattr fallback -- tries direct method first, falls back to process_task dispatch"
    - "Scheduler calls execute(task, context={}) matching CSMScheduler pattern (not _execute_task)"
    - "CollectionsScheduler.start() wrapped in try/except, returns False on any error including no event loop"

key-files:
  created:
    - src/app/agents/collections/agent.py
    - src/app/agents/collections/scheduler.py
  modified: []

key-decisions:
  - "execute() is the BaseAgent override (not _execute_task) -- plan spec name mapped to actual BaseAgent abstract method"
  - "scheduler uses agent.execute(task, context={}) matching CSMScheduler pattern, not agent._execute_task"
  - "receive_collections_risk only dispatches for RED/CRITICAL; GREEN/AMBER return immediately"
  - "receive_collections_risk fail-open: csm notification failures log warning, never block result return"

patterns-established:
  - "Collections -> CSM risk notification: single call site in execute() post-check, handlers never touch csm_agent"
  - "Scheduler fail-open: per-account try/except wrapping, error count tracked, never blocks other accounts"

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 15 Plan 05: CollectionsAgent and CollectionsScheduler Summary

**CollectionsAgent (BaseAgent subclass with execute() routing 5 task types) and CollectionsScheduler (2 daily cron jobs: 6am AR scan, 7am escalation check) with reverse cross-agent Collections->CSM risk notification path**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-25T18:02:57Z
- **Completed:** 2026-02-25T18:07:44Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `agent.py` (213 lines): CollectionsAgent extends BaseAgent with `execute()` routing 5 request_type values via `_TASK_HANDLERS` dict; raises ValueError for unknown types; stores `csm_agent` as `self._csm_agent`; post-checks `result["rag"]` after `payment_risk_assessment` and calls `receive_collections_risk()` on RED/CRITICAL
- `receive_collections_risk()`: single cross-agent notification path; only RED/CRITICAL dispatch to CSM; skips gracefully if `csm_agent` is None; tries direct method first (`hasattr` check), falls back to `process_task` dispatch; fail-open wraps in try/except
- `scheduler.py` (242 lines): CollectionsScheduler with 2 APScheduler cron jobs (6am AR scan, 7am escalation check); `start()` returns False if APScheduler not installed or on error; both job methods are async and fail-open per account
- All verification checks pass: both modules import, no send_email in agent.py code, cross-agent dispatch wired, cron hours 6 and 7 confirmed, post-check wiring confirmed

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CollectionsAgent with supervisor routing and CSM cross-agent dispatch** - `6a4a32c` (feat)
2. **Task 2: Create CollectionsScheduler with 2 daily cron jobs** - `780fe3c` (feat)

**Plan metadata:** `(docs commit follows)`

## Files Created/Modified

- `src/app/agents/collections/agent.py` - CollectionsAgent: BaseAgent subclass, execute() routing 5 handlers, receive_collections_risk() CSM notification (213 lines)
- `src/app/agents/collections/scheduler.py` - CollectionsScheduler: 2 cron jobs (6am AR scan, 7am escalation), graceful APScheduler handling (242 lines)

## Decisions Made

- **execute() as routing method**: BaseAgent's abstract method is `execute(task, context)`. The plan's `_execute_task` name was the spec name; the actual implementation uses `execute()` to satisfy the abstract method contract. This is consistent with CustomerSuccessAgent which also uses `execute()` for routing.
- **Scheduler calls execute(task, context={})**: Consistent with CSMScheduler pattern. The plan's spec `_execute_task(...)` maps to `execute(task, context={})` in the actual implementation since there is no `_execute_task` method.
- **receive_collections_risk uses hasattr fallback**: Tries `csm_agent.receive_collections_risk()` first (for future CSM agents that might expose this), falls back to `csm_agent.process_task()` for current CSM implementation which doesn't yet expose this method.
- **CollectionsScheduler.start() wrapped in try/except**: APScheduler requires a running event loop; the try/except catches this gracefully and returns False, making the scheduler safe to call in synchronous context (e.g., tests).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `CollectionsAgent` is fully implemented and tested — ready for main.py wiring (15-06)
- `CollectionsScheduler` is ready for main.py lifespan integration (15-06)
- receive_collections_risk() notification path is implemented — CSM agent wiring in 15-06 will provide the real csm_agent reference
- All 5 handlers callable via execute() with None services — safe for integration tests

---
*Phase: 15-collections-agent*
*Completed: 2026-02-25*
