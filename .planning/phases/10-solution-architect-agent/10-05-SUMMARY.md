---
phase: 10-solution-architect-agent
plan: 05
subsystem: inter-agent-handoff
tags: [sales-agent, solution-architect, handoff, dispatch, technical-question]

dependency-graph:
  requires: ["10-01", "10-02", "10-04"]
  provides: ["Sales Agent dispatch_technical_question handler", "Sales->SA round-trip handoff"]
  affects: ["11-supervisor-wiring", "future supervisor routing"]

tech-stack:
  added: []
  patterns: ["lazy import for cross-agent schema references", "typed handoff payload validation", "keyword-based question detection heuristic"]

key-files:
  created:
    - tests/test_sales_sa_handoff.py
  modified:
    - src/app/agents/sales/agent.py

decisions:
  - id: "10-05-D1"
    description: "Lazy import of TechnicalQuestionPayload inside handler to avoid circular dependency between sales and solution_architect packages"
    rationale: "The SA schemas module imports from pydantic only, but the agents __init__.py re-exports could create circular chains"
  - id: "10-05-D2"
    description: "Keyword-match heuristic requires 2+ matches for technical question detection to reduce false positives"
    rationale: "Single keyword matches like 'api' could appear in non-technical contexts; 2+ provides better signal-to-noise"

metrics:
  duration: "3 min"
  completed: "2026-02-23"
  tests_added: 6
  tests_total: 1140
  regressions: 0
---

# Phase 10 Plan 05: Sales Agent -> SA Handoff Dispatch Summary

**One-liner:** Sales Agent dispatch_technical_question handler with lazy-imported TechnicalQuestionPayload validation and keyword detection heuristic, proven by 6-test round-trip integration suite.

## What Was Done

### Task 1: Add technical question dispatch to Sales Agent
- Added `dispatch_technical_question` to Sales Agent's `execute()` routing dict (6th handler)
- Implemented `_handle_dispatch_technical_question` handler that:
  - Validates question is non-empty (returns `status=failed` if empty)
  - Builds a `TechnicalQuestionPayload` via lazy import from SA schemas
  - Constructs a `handoff_task` dict with `type=technical_handoff` matching SA's execute() routing
  - Returns `status=dispatched`, the handoff_task, serialized payload, and `target_agent_id=solution_architect`
- Added `_is_technical_question()` static method in Helpers section:
  - 35 technical keywords covering API, integration, security, compliance, infrastructure domains
  - Requires 2+ matches to return True (reduces false positives from single-keyword hits)
- All existing 5 handlers unchanged; purely additive

### Task 2: Create round-trip integration tests
- Created `tests/test_sales_sa_handoff.py` with 6 test cases across 5 test classes:
  1. `test_sales_agent_dispatches_technical_question` - verifies handler output shape and content
  2. `test_sales_agent_dispatch_empty_question_fails` - verifies graceful failure on empty input
  3. `test_sa_agent_receives_handoff_task` - verifies SA processes the handoff_task dict
  4. `test_full_round_trip_sales_to_sa_and_back` - end-to-end: Sales dispatch -> SA process -> TechnicalAnswerPayload validation
  5. `test_is_technical_question_detection` - verifies heuristic accuracy on 4 test cases
  6. `test_dispatch_preserves_context_chunks` - verifies context passthrough

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| 10-05-D1 | Lazy import of SA schemas inside handler | Avoids circular dependency between sales and solution_architect packages |
| 10-05-D2 | 2+ keyword match threshold for detection | Single matches produce too many false positives in sales contexts |

## Verification Results

- `pytest tests/test_sales_sa_handoff.py -v`: 6/6 passed
- `pytest tests/ -x -q`: 1140 passed, 0 failed, 0 regressions
- `grep dispatch_technical_question src/app/agents/sales/agent.py`: found in routing dict and method definition
- `grep _is_technical_question src/app/agents/sales/agent.py`: found in Helpers section

## Commits

| Hash | Message |
|------|---------|
| 7e2af08 | feat(10-05): add dispatch_technical_question handler to Sales Agent |
| b9e5542 | test(10-05): add round-trip integration tests for Sales Agent -> SA handoff |

## Next Phase Readiness

- Sales Agent now has 6 task types (send_email, send_chat, process_reply, qualify, recommend_action, dispatch_technical_question)
- SA agent's technical_handoff handler (built in 10-02) receives the exact dict shape produced by Sales Agent's dispatch
- Supervisor wiring (future phase) needs to route tasks with `target_agent_id=solution_architect` to the SA agent
- The `_is_technical_question` heuristic is available for Supervisor's routing logic to use as a pre-filter before LLM-based routing
