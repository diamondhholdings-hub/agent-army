---
phase: 13-technical-account-manager-agent
plan: 05
subsystem: agent-handoff
tags: [sales-agent, tam-agent, dispatch, handoff, lazy-import, health-check, trigger-heuristic, round-trip-test]

# Dependency graph
requires:
  - phase: 13-01
    provides: TAM schemas (TAMHandoffRequest, TAMHandoffResponse, TAMResult)
  - phase: 13-02
    provides: TAMAgent with 7 capability handlers, execute() routing
  - phase: 13-03
    provides: HealthScorer pure Python scoring, TicketClient, NotionTAMAdapter
  - phase: 12-05
    provides: Sales Agent dispatch pattern (lazy import, explicit dict mapping, 2+ keyword threshold)
provides:
  - dispatch_tam_health_check handler on Sales Agent for cross-agent TAM dispatch
  - _is_tam_trigger heuristic with 17 TAM-specific keywords and 5 post-sale stages
  - TAM_REQUEST_TO_TASK_TYPE explicit mapping dict for 6 request types
  - 25 round-trip integration tests proving Sales->TAM handoff works end-to-end
affects: [13-04 (TAM wiring in main.py), future supervisor routing for TAM tasks]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy import TAMHandoffRequest inside dispatch function body to prevent circular deps"
    - "TAM_REQUEST_TO_TASK_TYPE explicit dict mapping (same pattern as SCOPE_TO_TASK_TYPE for BA)"
    - "_is_tam_trigger requires 2+ keyword matches, same threshold as _is_technical_question and _is_ba_trigger"
    - "TAM trigger keywords are distinct from BA/SA keywords -- verified by isolation tests"

# File tracking
key-files:
  modified:
    - src/app/agents/sales/agent.py
  created:
    - tests/test_tam_handoff.py

# Decisions
decisions:
  - id: "13-05-01"
    decision: "TAM_REQUEST_TO_TASK_TYPE uses identity mapping (request type == task type) since TAM request types already match TAM agent task router keys"
    rationale: "Unlike BA where analysis_scope values don't match task_type keys, TAM request types are 1:1 with handler names. Explicit dict still used for consistency and safety."

# Metrics
metrics:
  duration: "3 min"
  completed: "2026-02-24"
---

# Phase 13 Plan 05: Sales->TAM Handoff Summary

**One-liner:** Sales Agent dispatch_tam_health_check with lazy import, 2+ keyword trigger heuristic, and 25 round-trip integration tests proving end-to-end Sales->TAM handoff.

## What Was Done

### Task 1: Add TAM dispatch to Sales Agent
- Added `TAM_REQUEST_TO_TASK_TYPE` module-level constant mapping all 6 TAM request types to TAM agent task_type keys
- Added `dispatch_tam_health_check` handler to the execute() router handlers dict
- Implemented `_handle_dispatch_tam_health_check` method with lazy import of `TAMHandoffRequest` inside function body
- Implemented `_is_tam_trigger` static method with 17 TAM-specific keywords (2+ match threshold) and 5 post-sale stage triggers
- Updated module docstring to include dispatch_tam_health_check alongside other dispatch handlers

### Task 2: Create round-trip handoff integration tests
- Created `tests/test_tam_handoff.py` with 25 tests across 8 test classes:
  - **TestSalesAgentTAMTriggerKeyword** (3 tests): 2+ keyword match triggers, 0-match rejection, 1-match rejection
  - **TestSalesAgentTAMTriggerStage** (6 tests): closed_won, Active Customer (case-insensitive), onboarding, renewal, account_management triggers; prospecting rejection
  - **TestSalesAgentDispatchTAMHealthCheck** (3 tests): valid dispatch, missing account_id, default request_type
  - **TestSalesAgentTAMRequestTypeMapping** (7 tests): all 6 request types map correctly + dict completeness
  - **TestSalesToTAMRoundTripHealthScan** (1 test): full end-to-end with real HealthScorer and mock tickets, verifying exact score computation (60 Amber)
  - **TestSalesToTAMRoundTripEscalationOutreach** (1 test): full end-to-end with mock LLM returning escalation JSON, verifying Gmail create_draft called (not send_email)
  - **TestTAMHandoffRequestSerialization** (1 test): JSON round-trip preserving all fields
  - **TestTAMTriggerDoesNotMatchOtherAgentKeywords** (3 tests): BA requirements text rejected, SA API text rejected, TAM-specific text triggers TAM but not BA

## Decisions Made

1. **Identity mapping for TAM_REQUEST_TO_TASK_TYPE:** TAM request types already match TAM agent handler names 1:1 (health_scan -> health_scan, etc.), unlike BA where analysis_scope needs remapping. Used explicit dict anyway for pattern consistency and safety against future divergence.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

1. `python -m pytest tests/test_tam_handoff.py -v` -- 25/25 passed
2. `python -m pytest tests/ -x -q --timeout=30` -- 1257 passed, full suite green
3. Sales Agent has dispatch_tam_health_check + _is_tam_trigger (verified by import check)
4. No circular imports between Sales/TAM agent modules (verified)
5. `grep TAM_REQUEST_TO_TASK_TYPE` finds explicit dict at line 73 and usage at line 1062

## Next Phase Readiness

Phase 13 plan 04 (TAM agent wiring in main.py lifespan) is the remaining plan. All TAM components are now ready:
- TAM schemas (13-01)
- TAM prompts and handoff types (13-01)
- TAM agent with 7 handlers (13-02)
- TAM capabilities declaration (13-02)
- HealthScorer, TicketClient, NotionTAMAdapter, TAMScheduler (13-03)
- Sales Agent TAM dispatch with round-trip tests (13-05, this plan)

No blockers for 13-04 wiring.
