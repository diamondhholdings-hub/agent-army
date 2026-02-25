---
phase: 15-collections-agent
plan: 01
subsystem: api
tags: [pydantic, collections, ar-aging, payment-risk, escalation, csm-integration]

# Dependency graph
requires:
  - phase: 14-customer-success-agent
    provides: CSMHealthSignals model that collections_risk field was added to
provides:
  - 11 Pydantic models covering the full Collections agent domain
  - EscalationStage type alias (Literal[0..5])
  - collections_risk field on CSMHealthSignals enabling cross-agent integration
affects:
  - 15-02 (payment risk scorer imports PaymentRiskSignals, PaymentRiskResult)
  - 15-03 (collection message handler imports CollectionMessageStage, EscalationState)
  - 15-04 (payment plan handler imports PaymentPlanOptions, PaymentPlanOption)
  - 15-05 (Notion adapter imports ARAgingReport, EscalationState, CollectionsAlertResult)
  - 15-06 (Collections agent imports CollectionsHandoffRequest)
  - 15-07 (CSM agent imports collections_risk from CSMHealthSignals)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Collections schemas follow CSM/TAM pattern: from __future__ import annotations, model_validator for auto-computed fields"
    - "PaymentRiskResult.should_escalate mirrors CSMHealthScore.should_alert: auto-computed via model_validator(mode='after')"
    - "EscalationStage as type alias (not Enum) consistent with domain simplicity needs"
    - "collections_risk field added as Optional with None default for backward compatibility"

key-files:
  created:
    - src/app/agents/collections/__init__.py
    - src/app/agents/collections/schemas.py
  modified:
    - src/app/agents/customer_success/schemas.py

key-decisions:
  - "PaymentRiskResult score is inverted from CSM (higher = more risk, not healthier)"
  - "EscalationStage defined as Literal type alias not IntEnum for simplicity"
  - "arr_usd and tenure_years in PaymentRiskSignals are tone modifiers only, not risk score inputs"
  - "collections_risk Literal includes CRITICAL (4 values) unlike tam_health_rag (3 values GREEN/AMBER/RED)"

patterns-established:
  - "Collections schemas: same import block pattern as CSM/TAM (from __future__ import annotations)"
  - "model_validator(mode='after') for boolean auto-computation (should_escalate = score >= 60.0)"
  - "Optional fields with None default for cross-agent integration fields (backward compatible)"

# Metrics
duration: 3min
completed: 2026-02-25
---

# Phase 15 Plan 01: Collections Agent Schemas Summary

**11 Pydantic models for AR aging, payment risk scoring, escalation state, collection messages, and payment plans; CSMHealthSignals extended with collections_risk for cross-agent integration**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-25T17:41:27Z
- **Completed:** 2026-02-25T17:44:21Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `src/app/agents/collections/schemas.py` with 11 Pydantic models and 1 type alias (EscalationStage), 365 lines
- `PaymentRiskResult.should_escalate` auto-computed via `model_validator(mode="after")`: True when score >= 60.0
- `EscalationState` tracks both `payment_received_at` and `response_received_at` reset signals
- `CSMHealthSignals.collections_risk: Optional[Literal["GREEN","AMBER","RED","CRITICAL"]] = None` added for cross-agent health integration
- All 33 pre-existing CSM schema and health scorer tests continue to pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Create collections package and schemas.py with all domain models** - `c68484f` (feat)
2. **Task 2: Add collections_risk field to CSMHealthSignals** - `3c7f828` (feat)

**Plan metadata:** `(docs commit follows)`

## Files Created/Modified

- `src/app/agents/collections/__init__.py` - Package stub with lazy CollectionsAgent import comment (12 lines)
- `src/app/agents/collections/schemas.py` - 11 Pydantic models + EscalationStage type alias for collections domain (365 lines)
- `src/app/agents/customer_success/schemas.py` - Added `collections_risk` field to CSMHealthSignals (4-line addition)

## Decisions Made

- **PaymentRiskResult score semantics inverted from CSM**: Higher score = more risk (0=safe, 100=critical), unlike CSMHealthScore where higher = healthier. This matches collections domain intuition.
- **EscalationStage as type alias**: Defined as `Literal[0, 1, 2, 3, 4, 5]` rather than IntEnum for simplicity and to stay consistent with other Literal fields throughout the codebase.
- **arr_usd and tenure_years as tone modifiers only**: These fields appear in PaymentRiskSignals but are excluded from risk scoring — they only influence collection message tone (softer for high-ARR, long-tenure customers). This prevents ARR from biasing risk assessment.
- **collections_risk includes CRITICAL**: The 4-value Literal `["GREEN","AMBER","RED","CRITICAL"]` matches the PaymentRiskResult RAG field, unlike tam_health_rag which uses only 3 values. Collections has a distinct CRITICAL state (stage 5, human handoff) that CSM/TAM don't have.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The plan's verification command (`python -c "from src.app.agents.collections.schemas import ..."`) requires the project's `.venv` Python since `src/app/agents/__init__.py` triggers a langgraph import that's not available in system Python. Using `.venv/bin/python` resolved this immediately.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 11 collections domain schemas defined and verified
- `CSMHealthSignals.collections_risk` field ready for use by Collections agent
- Ready for 15-02 (payment risk scorer implementation)
- No blockers or concerns

---
*Phase: 15-collections-agent*
*Completed: 2026-02-25*
