---
phase: 15-collections-agent
plan: 03
subsystem: api
tags: [python, pydantic, collections, prompt-builders, handlers, fail-open, gmail-draft, escalation]

# Dependency graph
requires:
  - phase: 15-collections-agent
    plan: 01
    provides: ARAgingReport, PaymentRiskResult, CollectionMessageStage, PaymentPlanOptions, EscalationState, CollectionsAlertResult schemas
  - phase: 15-collections-agent
    plan: 02
    provides: PaymentRiskScorer.score(), compute_tone_modifier(), STAGE_TIME_FLOORS
provides:
  - COLLECTIONS_SYSTEM_PROMPT and 5 prompt builders with embedded JSON schemas
  - 5 async fail-open handlers covering all CollectionsHandoffRequest.request_type values
  - Deterministic escalation check with draft-on-advance (stages 1-4) and stage 5 dual-draft notification
affects:
  - 15-05 (CollectionsAgent._execute_task() routes to these handlers)
  - 15-06 (agent wiring imports handlers from this module)
  - 15-07 (scheduler calls handle_run_escalation_check)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Collections prompt builders: str return with embedded model_json_schema(), same pattern as CSM/TAM"
    - "Collections handlers: async fail-open dict return, same pattern as CSM agent handlers"
    - "Deterministic escalation advancement: STAGE_TIME_FLOORS + messages_unanswered check, no LLM in decision path"
    - "Draft-on-advance: handle_generate_collection_message called internally in handle_run_escalation_check for stages 1-4"
    - "Stage 5 dual-draft: build_escalation_check_prompt -> LLM -> create_draft for rep AND finance team"
    - "compute_tone_modifier imported from scorer and called per-message-generation for firmness calibration"

key-files:
  created:
    - src/app/agents/collections/prompt_builders.py
    - src/app/agents/collections/handlers.py
  modified: []

key-decisions:
  - "COLLECTIONS_SYSTEM_PROMPT includes draft-only constraint -- LLM aware it never sends autonomously"
  - "build_escalation_check_prompt generates Stage 5 notification EMAIL CONTENT only, not advancement decision"
  - "handle_run_escalation_check: stage 0 treated with time_floor_met=True (immediate advance if unanswered) since no floor defined"
  - "send_email appears only in module docstring as constraint note, never as actual code call"
  - "Finance team email sourced from task, kwargs, or settings.FINANCE_TEAM_EMAIL in priority order"

patterns-established:
  - "Collections handlers: same async fail-open pattern as CSM/TAM/BA handlers, consistent across agents"
  - "Internal handler calls: handle_run_escalation_check calls handle_generate_collection_message, same pattern as agent-internal dispatching"

# Metrics
duration: 6min
completed: 2026-02-25
---

# Phase 15 Plan 03: Collections Prompt Builders and Handlers Summary

**5 prompt builders with embedded Pydantic JSON schemas and 5 async fail-open handlers implementing full collections lifecycle — AR aging, risk assessment, stage-appropriate email drafts, deterministic escalation advancement with dual-draft stage 5 notification, and payment plan surfacing**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-25T17:54:08Z
- **Completed:** 2026-02-25T18:00:18Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `prompt_builders.py` (416 lines): COLLECTIONS_SYSTEM_PROMPT + 5 builders embedding ARAgingReport, PaymentRiskResult, CollectionMessageStage, PaymentPlanOptions schemas; build_escalation_check_prompt generates Stage 5 notification email body (not an advancement decision)
- `handlers.py` (931 lines): 5 async fail-open handlers — handle_ar_aging_report, handle_payment_risk_assessment (deterministic score + LLM narrative), handle_generate_collection_message (tone_modifier calibration), handle_run_escalation_check (deterministic advancement with internal draft call), handle_surface_payment_plan
- Escalation check handler: STAGE_TIME_FLOORS + messages_unanswered >= 1 determines advancement; stages 1-4 internally call handle_generate_collection_message producing a ready-to-send Gmail draft; stage 5 calls build_escalation_check_prompt + LLM for dual rep+finance create_draft calls
- No csm_agent reference in any handler — CSM notification path delegated to CollectionsAgent._execute_task()
- Zero send_email calls — all communications via gmail_service.create_draft()

## Task Commits

Each task was committed atomically:

1. **Task 1: Create prompt builders for all 5 collections task types** - `4f2092e` (feat)
2. **Task 2: Create 5 task handlers with fail-open semantics and draft-on-advance for stages 1-4** - `7e57286` (feat)

**Plan metadata:** `[see final commit]` (docs: complete plan)

## Files Created/Modified

- `src/app/agents/collections/prompt_builders.py` - COLLECTIONS_SYSTEM_PROMPT + 5 prompt builders with embedded JSON schemas (416 lines)
- `src/app/agents/collections/handlers.py` - 5 async fail-open handlers implementing full collections lifecycle (931 lines)

## Decisions Made

- **COLLECTIONS_SYSTEM_PROMPT draft-only constraint**: System prompt explicitly states "All communications are DRAFT ONLY — you never send emails autonomously" so the LLM is aware of this constraint at the persona level.
- **build_escalation_check_prompt purpose**: This builder generates Stage 5 notification EMAIL CONTENT only. The escalation advancement decision itself is fully deterministic (STAGE_TIME_FLOORS check + messages_unanswered check). The NOTE in the docstring and module docstring both clarify this to prevent future confusion.
- **Stage 0 time floor**: Stage 0 (not started) has no entry in STAGE_TIME_FLOORS. Handler treats time_floor_met=True for stage 0, meaning any unanswered message at stage 0 immediately advances to stage 1. This is the logical behavior — stage 0 is the pre-action state with no waiting period.
- **Finance team email priority order**: task.get("finance_team_email") → kwargs.get("finance_team_email") → settings.FINANCE_TEAM_EMAIL (lazy import). If empty after all checks, finance draft is skipped with a warning log (not an error).
- **send_email in docstring**: The word "send_email" appears once in the module docstring (line 16) as a constraint note ("NEVER send_email"). All 6 verification checks pass when properly distinguishing doc mentions from actual code calls.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `prompt_builders.py` exports all 5 builders + COLLECTIONS_SYSTEM_PROMPT — ready for agent.py import
- `handlers.py` exports all 5 handlers — ready for CollectionsAgent._execute_task() routing
- All handlers fail-open and callable with None services — safe for unit testing
- All communications via create_draft() only — draft-only contract enforced
- No csm_agent in handler signatures — CSM notification path clean
- Ready for 15-05 (CollectionsAgent implementation)

---
*Phase: 15-collections-agent*
*Completed: 2026-02-25*
