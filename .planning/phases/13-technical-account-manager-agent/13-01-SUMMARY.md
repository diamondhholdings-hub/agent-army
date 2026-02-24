---
phase: 13-technical-account-manager-agent
plan: 01
subsystem: agent
tags: [pydantic, tam, health-score, escalation, relationship-profile, handoff]

# Dependency graph
requires:
  - phase: 12-business-analyst-agent
    provides: BA schemas/prompts pattern, validators.py with handoff type registration
provides:
  - 13 TAM Pydantic domain models (TicketSummary, HealthScoreResult, RelationshipProfile, etc.)
  - 5 communication prompt builders with JSON schema embedding
  - TAM system prompt for LLM persona
  - health_report and escalation_alert handoff types registered as STRICT
affects: [13-02 (handlers), 13-03 (Notion adapter), 13-04 (health scorer/scheduler), 13-05 (wiring/tests)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TAM model_validator for auto-computed should_escalate flag"
    - "Output schema dicts (not Pydantic models) for LLM communication output shapes"
    - "Five communication types as Literal values in TAMTask"

key-files:
  created:
    - src/app/agents/technical_account_manager/__init__.py
    - src/app/agents/technical_account_manager/schemas.py
    - src/app/agents/technical_account_manager/prompts.py
  modified:
    - src/app/handoffs/validators.py

key-decisions:
  - "HealthScoreResult escalation triggers: score < 40, non-Red -> Red, Green -> Amber"
  - "Prompt output schemas defined as plain dicts, not Pydantic models, because they are LLM output shapes"
  - "All 5 communication prompts include DRAFT notice since TAM never sends email autonomously"

patterns-established:
  - "TAM schemas follow BA/PM pattern: __future__ annotations, BaseModel, Field, model_validator"
  - "TAM prompts follow BA pattern: system prompt + N builder functions returning str with embedded JSON schema"
  - "TAM handoff types registered in validators.py same block pattern as PM/BA"

# Metrics
duration: 5min
completed: 2026-02-24
---

# Phase 13 Plan 01: TAM Schemas and Prompts Summary

**13 Pydantic domain models with auto-computed escalation logic, 5 communication prompt builders with JSON schema embedding, and STRICT handoff type registration**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-24T16:26:27Z
- **Completed:** 2026-02-24T16:31:15Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Defined all 13 TAM Pydantic models covering tickets, health scores, relationship profiles, escalation notifications, task/result envelopes, and handoff payloads
- HealthScoreResult auto-computes should_escalate via model_validator with three trigger conditions (score < 40, non-Red to Red, Green to Amber)
- Built 5 communication prompt builders (escalation outreach, release notes, roadmap preview, health check-in, CSR) each embedding JSON output schema
- Registered health_report and escalation_alert as STRICT in StrictnessConfig

## Task Commits

Each task was committed atomically:

1. **Task 1: Create TAM Pydantic schemas and handoff payloads** - `568157b` (feat)
2. **Task 2: Create TAM prompt templates with JSON schema embedding** - `8cc4258` (feat)

## Files Created/Modified
- `src/app/agents/technical_account_manager/schemas.py` - All 13 TAM domain models with validation
- `src/app/agents/technical_account_manager/prompts.py` - TAM system prompt + 5 communication prompt builders
- `src/app/agents/technical_account_manager/__init__.py` - Minimal package init importing all schemas
- `src/app/handoffs/validators.py` - Added health_report and escalation_alert as STRICT

## Decisions Made
- HealthScoreResult escalation triggers follow CONTEXT.md decision: score < 40 (Red threshold), non-Red to Red (worsened), Green to Amber (early warning)
- Prompt output schemas defined as plain dicts (not Pydantic models) since they describe LLM output shapes, not internal domain models -- simpler and avoids coupling LLM output structure to internal types
- All communication prompts explicitly note "DRAFT for rep review" matching the locked decision that TAM never sends email autonomously
- CommunicationRecord.communication_type uses the same 5-value Literal as TAMTask task_type (minus health_scan and update_relationship_profile which are not communications)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Python 3.9.6 on dev machine causes pre-existing `str | None` TypeError in `config.py` (missing `from __future__ import annotations`). This prevents importing via the parent `src.app.agents.__init__.py` but is NOT caused by this plan's changes. TAM schemas verified via namespace stub imports. The test suite has the same pre-existing failure.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All 13 TAM Pydantic models available for import by handlers (13-02), Notion adapter (13-03), health scorer (13-04), and tests (13-05)
- Prompt builders ready for LLM call integration in handlers
- Handoff types registered for inter-agent communication validation
- No blockers for subsequent plans

---
*Phase: 13-technical-account-manager-agent*
*Completed: 2026-02-24*
