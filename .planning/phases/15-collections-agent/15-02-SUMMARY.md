---
phase: 15-collections-agent
plan: 02
subsystem: api
tags: [python, pydantic, collections, payment-risk, scoring, tdd, deterministic]

# Dependency graph
requires:
  - phase: 15-collections-agent
    plan: 01
    provides: PaymentRiskSignals and PaymentRiskResult schemas that scorer imports
provides:
  - PaymentRiskScorer class with 4-component deterministic risk scoring
  - compute_tone_modifier function for message firmness calibration
  - STAGE_TIME_FLOORS dict exported for handler/scheduler stage advancement logic
affects:
  - 15-03 (collection message handler uses compute_tone_modifier)
  - 15-06 (Collections agent imports PaymentRiskScorer for risk assessments)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PaymentRiskScorer mirrors CSMHealthScorer pattern: pure Python, no LLM, private static scorers, main score() method"
    - "STAGE_TIME_FLOORS exported as module-level dict (not class attribute) for direct import by handlers"
    - "Real PaymentRiskScorer used in tests (not mocked) — deterministic pure Python, same pattern as CSMHealthScorer tests"
    - "TDD: RED (ImportError) -> GREEN (30/30 pass) cycle, no REFACTOR needed"

key-files:
  created:
    - src/app/agents/collections/scorer.py
    - tests/test_collections_scorer.py
  modified: []

key-decisions:
  - "should_escalate threshold is score >= 60 (not AMBER onset at 30) — plan test case comment was misleading, spec (schemas.py model_validator) is ground truth"
  - "STAGE_TIME_FLOORS as module-level dict, not class attribute — imported directly by handlers without instantiating PaymentRiskScorer"
  - "_derive_rag evaluates CRITICAL first (top-down from highest risk) for clarity and fail-safe behavior"
  - "days_overdue param kept in compute_tone_modifier signature for future extensibility even though unused currently"

patterns-established:
  - "Collections scorer: same 4-method private static pattern as CSMHealthScorer (_score_X per component)"
  - "RAG derivation as private static method with clear threshold comments"

# Metrics
duration: 4min
completed: 2026-02-25
---

# Phase 15 Plan 02: Collections Scorer TDD Summary

**PaymentRiskScorer (4-signal, 0-100 risk score) and compute_tone_modifier ([0.6, 1.4] firmness) implemented via TDD with 30 deterministic tests covering all tier boundaries and canonical account scenarios**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-25T17:47:09Z
- **Completed:** 2026-02-25T17:50:45Z
- **Tasks:** 2 (RED + GREEN, no REFACTOR needed)
- **Files modified:** 2

## Accomplishments

- `PaymentRiskScorer.score()` computes 4-component risk score (days_overdue 40pts + streak 25pts + balance 20pts + renewal 15pts = 100pts max)
- RAG derivation: GREEN<30, AMBER<60, RED<85, CRITICAL>=85; `should_escalate` auto-computed from `PaymentRiskResult.model_validator` at score >= 60
- `compute_tone_modifier` returns float in [0.6, 1.4] using arr_mod + tenure_mod + streak_mod clamped to range
- `STAGE_TIME_FLOORS = {1:7, 2:10, 3:7, 4:5}` exported as module-level dict for stage advancement logic
- 30 tests covering 5 canonical accounts, all 4 RAG boundaries, all component tier boundaries, STAGE_TIME_FLOORS export, and 11 tone modifier cases
- All 1366 project tests pass (no regressions)

## Task Commits

Each TDD phase committed atomically:

1. **RED: Failing tests for PaymentRiskScorer and compute_tone_modifier** - `96a23fb` (test)
2. **GREEN: Implement PaymentRiskScorer and compute_tone_modifier** - `9b5eb99` (feat)

_No REFACTOR commit — implementation was clean from GREEN phase_

## Files Created/Modified

- `src/app/agents/collections/scorer.py` - PaymentRiskScorer class, compute_tone_modifier function, STAGE_TIME_FLOORS dict (216 lines)
- `tests/test_collections_scorer.py` - TDD test suite with 30 deterministic tests across 2 test classes (524 lines)

## Decisions Made

- **should_escalate threshold confirmed as score >= 60**: The plan's "Slightly late" test case comment incorrectly said "AMBER, should_escalate=True" for score=37. The spec `must_haves.truths` and `schemas.py` model_validator both say threshold is 60. Fixed test to match spec. Score=37 is AMBER but does NOT escalate.
- **STAGE_TIME_FLOORS as module-level dict**: Kept at module level (not class attribute) so handlers can `from src.app.agents.collections.scorer import STAGE_TIME_FLOORS` without instantiating the scorer.
- **days_overdue in compute_tone_modifier signature**: Kept for interface completeness and future extensibility per the plan's `<implementation>` spec, even though it doesn't affect the modifier currently.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test assertion contradiction with documented spec**

- **Found during:** GREEN phase execution (test_slightly_late_is_amber_and_escalates)
- **Issue:** Plan's test case description said "AMBER, should_escalate=True" for score=37. But both `must_haves.truths` ("should_escalate is True when score >= 60") and `schemas.py` `model_validator` (`self.should_escalate = self.score >= 60.0`) define the threshold as 60, not 30. Score=37 does not meet the escalation threshold.
- **Fix:** Renamed test to `test_slightly_late_is_amber_no_escalate`, changed assertion to `assert result.should_escalate is False`, updated docstring to clarify escalation threshold
- **Files modified:** tests/test_collections_scorer.py
- **Verification:** All 30 tests pass; schema's model_validator confirms score 37 → should_escalate=False
- **Committed in:** 9b5eb99 (GREEN phase commit)

---

**Total deviations:** 1 auto-fixed (bug: contradictory test assertion)
**Impact on plan:** Fix enforces the actual spec (score >= 60) rather than an erroneous comment. No scope creep.

## Issues Encountered

None. Standard TDD cycle completed cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `PaymentRiskScorer`, `compute_tone_modifier`, and `STAGE_TIME_FLOORS` all available for import
- Scorer produces correct RAG bands, escalation flags, and score breakdowns verified by tests
- Ready for 15-03 (collection message handler — imports compute_tone_modifier for tone calibration)
- No blockers or concerns

---
*Phase: 15-collections-agent*
*Completed: 2026-02-25*
