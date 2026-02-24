---
phase: 12-business-analyst-agent
plan: 04
subsystem: agent-wiring-and-testing
tags: [business-analyst, main-wiring, integration-tests, fail-open, lifespan]
depends_on:
  requires: ["12-02", "12-03"]
  provides: ["BA agent live in app lifespan", "14 integration tests covering all handlers"]
  affects: ["12-05"]
tech-stack:
  added: []
  patterns: ["fail-tolerant lifespan wiring", "mocked LLM/RAG integration tests"]
key-files:
  created:
    - tests/test_business_analyst.py
  modified:
    - src/app/main.py
decisions:
  - id: ba-wiring-pattern
    decision: "BA agent wired identically to SA/PM pattern in main.py lifespan"
    rationale: "Consistency across all agent wirings enables predictable debugging and maintenance"
  - id: ba-test-mock-pattern
    decision: "Tests use _make_mock_llm pattern with raw JSON (no code fences) to match SA test style"
    rationale: "BA agent _extract_json_from_response handles both fenced and raw JSON"
metrics:
  duration: "3 min"
  completed: "2026-02-24"
---

# Phase 12 Plan 04: Main Wiring and Tests Summary

BA agent wired into main.py lifespan with fail-tolerant try/except, 14 integration tests covering all 4 handlers, error paths, Fibonacci validation, handoff payloads, and Notion renderers.

## Tasks Completed

### Task 1: Wire BA agent into main.py lifespan
- Added Phase 12 initialization block after PM (Phase 11), before Deals (Phase 5)
- Follows exact SA/PM pattern: import inside try, create registration, instantiate with shared llm_service + rag_pipeline
- Registers in AgentRegistry with `_agent_instance` linkage
- Stores on `app.state.business_analyst` for runtime access
- Fail-tolerant: logs warning but does not prevent startup
- **Commit:** ef69fb8

### Task 2: Create comprehensive integration tests
- Created `tests/test_business_analyst.py` (740 lines, 14 tests)
- All tests use mocked LLM and RAG (no external dependencies)
- Tests organized in 7 test classes:
  - TestBARegistration: agent_id, capability count, capability names
  - TestBARequirementsExtraction: handler routing, low-confidence flagging
  - TestBAGapAnalysis: handler routing, contradictions included, coverage_percentage 0-100
  - TestBAUserStoryGeneration: handler routing, Fibonacci validation, low-confidence flagging
  - TestBAProcessDocumentation: handler routing, all fields populated
  - TestBAErrorHandling: unknown type returns error dict (not exception), LLM failure fail-open
  - TestBAHandoffPayloads: BAHandoffRequest/Response round-trip serialization
  - TestBANotionRenderers: all 4 block renderers produce non-empty block lists
- **Commit:** 05ea321

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed Fibonacci validation test for story_points=0**
- **Found during:** Task 2
- **Issue:** Test expected `match="Fibonacci"` for `story_points=0`, but Pydantic's `ge=1` constraint fires first with "greater than or equal to 1" error message, before the custom Fibonacci field_validator runs
- **Fix:** Split test into two cases: `story_points=0` caught by `ge=1` (no match filter), and `story_points >= 1` non-Fibonacci values caught by custom validator (with `match="Fibonacci"`)
- **Files modified:** tests/test_business_analyst.py
- **Commit:** 05ea321 (included in same task commit)

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| ba-wiring-pattern | BA agent wired identically to SA/PM pattern | Consistency across all agent wirings |
| ba-test-mock-pattern | Tests use raw JSON mock responses (no code fences) | BA _extract_json_from_response handles both formats; raw JSON is simpler |

## Verification Results

1. `python -m pytest tests/test_business_analyst.py -v` -- 14/14 passed
2. `grep 'phase12.business_analyst' src/app/main.py` -- found init + warning log lines
3. `grep 'app.state.business_analyst' src/app/main.py` -- found state assignment
4. `python -m pytest tests/ -x -q --timeout=30` -- 1187 passed (full suite, no regressions)

## Next Phase Readiness

Plan 12-04 complete. Plan 12-05 (Sales Agent BA dispatch integration) can proceed -- BA agent is now live in the application with `app.state.business_analyst` available for dispatch routing.
