---
phase: 14-customer-success-agent
plan: 03
subsystem: agent
tags: [csm, health-scoring, scheduler, apscheduler, fail-open, cross-agent-handoff]

# Dependency graph
requires:
  - phase: 14-01
    provides: "CSM schemas (CSMHealthScore, QBRContent, ExpansionOpportunity, FeatureAdoptionReport, CSMAlertResult)"
  - phase: 14-02
    provides: "CSMHealthScorer, NotionCSMAdapter, CSM prompt builders"
  - phase: 13-02
    provides: "TAMAgent pattern (ValueError routing, fail-open, 4-channel alerts, draft-only comms)"
provides:
  - "CustomerSuccessAgent with 4 task handlers (health_scan, generate_qbr, check_expansion, track_feature_adoption)"
  - "CSMScheduler with 3 APScheduler cron jobs (daily scan, daily contract check, quarterly QBR)"
  - "CSM-to-Sales expansion dispatch (first reverse-direction cross-agent handoff)"
affects: [14-04, 14-05, 15-collections-agent, 16-business-operations-agent]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CSM agent mirrors TAM agent ValueError routing pattern"
    - "CSM 4-channel churn alerts (Notion, event bus, email draft, chat)"
    - "CSM->Sales reverse cross-agent handoff via self._sales_agent.execute()"
    - "CSMScheduler 3-job pattern: daily scan + daily contract check + quarterly QBR"

key-files:
  created:
    - "src/app/agents/customer_success/agent.py"
    - "src/app/agents/customer_success/scheduler.py"
  modified:
    - "src/app/agents/customer_success/__init__.py"

key-decisions:
  - "CSM raises ValueError for unknown task type, matching TAM pattern not BA fail-open"
  - "CSM never calls send_email -- all communications use gmail_service.create_draft()"
  - "CSM holds sales_agent reference for expansion dispatch; skip gracefully if None"
  - "CSMScheduler has 3 cron jobs vs TAM's 2, adding daily contract renewal check"
  - "Contract check filters accounts with days_to_renewal <= 60"

patterns-established:
  - "CSM agent constructor: registration, llm_service, notion_csm, gmail_service, chat_service, event_bus, health_scorer, sales_agent"
  - "CSM _dispatch_churn_alerts mirrors TAM _dispatch_escalation_notifications (4-channel independent try/except)"
  - "CSMScheduler.start() returns False gracefully if APScheduler not installed"

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 14 Plan 03: CustomerSuccessAgent and CSMScheduler Summary

**CustomerSuccessAgent with 4 fail-open handlers (health_scan, generate_qbr, check_expansion, track_feature_adoption) plus CSMScheduler with 3 APScheduler cron jobs (daily scan 7am, daily contract check 8am, quarterly QBR)**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-25T05:54:42Z
- **Completed:** 2026-02-25T05:59:18Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- CustomerSuccessAgent routes 4 task types with ValueError for unknown (TAM pattern)
- Each handler follows fail-open pattern returning {error, confidence: low, partial: True}
- health_scan uses pure Python CSMHealthScorer (no LLM), triggers 4-channel churn alerts when should_alert=True
- check_expansion dispatches ExpansionOpportunity to Sales Agent via self._sales_agent.execute() -- first reverse cross-agent handoff
- CSM never calls send_email -- all communications use gmail_service.create_draft()
- CSMScheduler registers 3 cron jobs with graceful APScheduler-missing fallback

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CustomerSuccessAgent with 4 capability handlers** - `3f95051` (feat)
2. **Task 2: Create CSMScheduler with 3 cron jobs** - `7e6bb70` (feat)

## Files Created/Modified
- `src/app/agents/customer_success/agent.py` - CustomerSuccessAgent with 4 handlers, _dispatch_churn_alerts, _extract_json_from_response
- `src/app/agents/customer_success/scheduler.py` - CSMScheduler with 3 cron jobs (daily scan, daily contract check, quarterly QBR)
- `src/app/agents/customer_success/__init__.py` - Updated to export CustomerSuccessAgent from agent.py

## Decisions Made
- CSM raises ValueError for unknown task type, matching TAM/PM pattern (not BA fail-open) -- consistency across non-sales agents
- CSM holds a direct reference to sales_agent for expansion dispatch; gracefully skips if None (logged warning)
- CSMScheduler has 3 jobs (vs TAM's 2): the additional daily contract check at 8am identifies accounts with days_to_renewal <= 60
- health_scan handler builds CSMHealthSignals from task-provided signals and account data, enabling flexible signal sourcing
- Quarterly QBR auto-computes quarter label from current date (Q1-Q4 YYYY)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- CustomerSuccessAgent and CSMScheduler ready for wiring into main.py lifespan (Plan 04)
- Sales Agent expansion handoff interface defined -- needs Sales Agent to support "handle_expansion_opportunity" task type
- All 14-01 schemas, 14-02 scorer/adapter/prompts, and 14-03 agent/scheduler form complete CSM capability stack

---
*Phase: 14-customer-success-agent*
*Completed: 2026-02-25*
