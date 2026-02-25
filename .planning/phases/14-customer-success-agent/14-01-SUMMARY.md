---
phase: 14-customer-success-agent
plan: 01
subsystem: agents
tags: [pydantic, schemas, prompt-builders, csm, customer-success, health-scoring, churn, expansion]

# Dependency graph
requires:
  - phase: 13-technical-account-manager
    provides: TAM schemas pattern (model_validator, __all__, docstrings), prompt builder pattern (str with embedded JSON schema)
provides:
  - 8 CSM Pydantic models (CSMHealthSignals, CSMHealthScore, ChurnRiskResult, ExpansionOpportunity, QBRContent, FeatureAdoptionReport, CSMHandoffRequest, CSMAlertResult)
  - 5 CSM prompt builder functions with embedded JSON schema
  - CSM_SYSTEM_PROMPT constant
  - 3 Notion CSM database ID config fields
affects: [14-02 health scorer and adapter, 14-03 agent handlers, 14-04 TDD tests, 14-05 wiring, 14-06 tests, 14-07 tests]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CSM model_validator auto-computes should_alert from RAG + churn_risk_level"
    - "CSM prompt builders use model_json_schema() for embedded output schemas"
    - "CSMHealthSignals captures 13 signal dimensions for composite health scoring"

key-files:
  created:
    - src/app/agents/customer_success/__init__.py
    - src/app/agents/customer_success/schemas.py
    - src/app/agents/customer_success/prompt_builders.py
  modified:
    - src/app/config.py

key-decisions:
  - "CSMHealthScore.should_alert triggers on RED rag OR high/critical churn_risk_level (broader than TAM which only triggers on score thresholds)"
  - "Prompt builders use model_json_schema() directly from Pydantic models rather than hand-written dict schemas (diverges from TAM which uses plain dicts)"
  - "CSMHealthSignals has 13 fields covering adoption, usage, engagement, support, financial, and TAM health dimensions"

patterns-established:
  - "CSM model_validator pattern: should_alert = (rag == RED) or (churn_risk_level in high/critical)"
  - "CSM prompt builders embed Pydantic model_json_schema() for LLM structured output"

# Metrics
duration: 4min
completed: 2026-02-25
---

# Phase 14 Plan 01: CSM Schemas, Prompt Builders, and Config Summary

**8 Pydantic CSM models with model_validator alert logic, 5 prompt builders using model_json_schema(), and 3 Notion DB config fields**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-25T05:40:27Z
- **Completed:** 2026-02-25T05:44:35Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- CSMHealthSignals model with all 13 health signal fields covering adoption, usage, engagement, support, financial, and TAM health dimensions
- CSMHealthScore with model_validator auto-computing should_alert when RAG is RED or churn_risk_level is high/critical
- 5 prompt builder functions each embedding Pydantic model_json_schema() for structured LLM output
- 3 Notion DB ID config fields (NOTION_CSM_HEALTH_DATABASE_ID, NOTION_CSM_QBR_DATABASE_ID, NOTION_CSM_EXPANSION_DATABASE_ID)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CSM schemas module with all Pydantic models** - `461e78a` (feat)
2. **Task 2: Create CSM prompt builders and add config fields** - `4a952d0` (feat)

## Files Created/Modified
- `src/app/agents/customer_success/__init__.py` - Module init with forward-compatible CustomerSuccessAgent stub
- `src/app/agents/customer_success/schemas.py` - 8 Pydantic models (CSMHealthSignals, CSMHealthScore, ChurnRiskResult, ExpansionOpportunity, QBRContent, FeatureAdoptionReport, CSMHandoffRequest, CSMAlertResult)
- `src/app/agents/customer_success/prompt_builders.py` - CSM_SYSTEM_PROMPT + 5 prompt builder functions
- `src/app/config.py` - Added 3 NOTION_CSM_* database ID fields to Settings class

## Decisions Made
- CSMHealthScore.should_alert triggers on RED rag OR high/critical churn_risk_level -- broader trigger surface than TAM's HealthScoreResult.should_escalate which only considers score < 40 and RAG transitions. Rationale: CSM needs to flag accounts where churn risk is high even if the overall RAG isn't yet RED.
- Prompt builders use model_json_schema() directly from Pydantic models rather than hand-written dict schemas (TAM pattern uses plain dicts). Rationale: keeps schema in sync with models automatically, reduces maintenance burden. The schemas are output shapes that map directly to CSM domain models.
- CSMHealthSignals.seats_utilization_rate allows up to 2.0 (not 1.0) to capture over-utilization scenarios where accounts have more active users than purchased seats.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 8 CSM models ready for import by Plan 02 (health scorer, Notion adapter)
- Prompt builders ready for use by Plan 03 (agent handlers)
- Config fields ready for Plan 02 (NotionCSMAdapter will use them)
- Ready for 14-02-PLAN.md

---
*Phase: 14-customer-success-agent*
*Completed: 2026-02-25*
