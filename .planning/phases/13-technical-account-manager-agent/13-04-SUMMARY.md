---
phase: 13-technical-account-manager-agent
plan: 04
subsystem: agent-wiring
tags: [main-py, lifespan, agent-registry, tam-scheduler, integration-tests, health-scorer, gmail-draft, fail-open]

# Dependency graph
requires:
  - phase: 13-02
    provides: TAMAgent class with 7 handlers, create_tam_registration factory
  - phase: 13-03
    provides: HealthScorer, TAMScheduler, TicketClient, NotionTAMAdapter
  - phase: 12-04
    provides: BA agent wiring pattern in main.py lifespan
provides:
  - TAM agent live in app lifespan with AgentRegistry registration
  - app.state.technical_account_manager set for runtime access
  - TAMScheduler running daily health scans + monthly check-ins
  - 23 integration tests covering all 7 handlers, HealthScorer, error paths, schemas
affects:
  - phase: 13-05
    why: TAM agent wired and tested, ready for Sales Agent handoff integration

# Tech tracking
tech-stack:
  added: []
  patterns:
    - TAM lifespan wiring follows SA/PM/BA pattern with try/except fail-tolerant init
    - TAMScheduler started and stored on app.state, shutdown cleanup in shutdown section
    - Real HealthScorer used in tests (no mocking) for deterministic assertions
    - GmailService.create_draft mocked with DraftResult-like object

# File tracking
key-files:
  created:
    - tests/test_technical_account_manager.py
  modified:
    - src/app/main.py

# Decisions
decisions:
  - id: d-1304-01
    description: TAM wiring placed after BA (Phase 12) and before Deal Management (Phase 5) in lifespan order
    rationale: Follows chronological agent addition pattern, mirrors SA/PM/BA placement
  - id: d-1304-02
    description: HealthScorer used as real implementation in tests (not mocked)
    rationale: Pure Python, deterministic, zero external dependencies -- mocking would reduce test value
  - id: d-1304-03
    description: TAM scheduler shutdown cleanup placed after Phase 7 intelligence scheduler cleanup
    rationale: Reverse order of initialization for clean shutdown sequence

# Metrics
metrics:
  duration: 5 min
  completed: 2026-02-24
  tests_added: 23
  test_categories: registration(2), health_scorer(8), handlers(7), error_handling(3), schemas(2), gmail_draft(1)
---

# Phase 13 Plan 04: Wiring & Integration Tests Summary

**One-liner:** TAM agent wired into main.py lifespan with TAMScheduler for daily health scans, plus 23 integration tests covering all 7 handlers, HealthScorer edge cases, and error paths.

## What Was Done

### Task 1: Wire TAM agent and TAMScheduler into main.py lifespan
- Added Phase 13 initialization block after BA (Phase 12) and before Deal Management (Phase 5)
- TAMAgent instantiated with shared services: llm_service, gmail_service, chat_service, event_bus, health_scorer
- Registered in AgentRegistry with `_agent_instance` pattern matching SA/PM/BA
- `app.state.technical_account_manager` set for runtime API endpoint access
- TAMScheduler instantiated with tam_agent and notion_tam, started via `.start()`
- Scheduler stored on `app.state.tam_scheduler` for shutdown cleanup
- Shutdown section: `tam_scheduler_ref.stop()` stops APScheduler cleanly
- Fail-tolerant: entire block wrapped in try/except, logs warning on failure

### Task 2: Create comprehensive integration tests (23 tests)
- **Registration (2):** agent_id correctness + 5 capabilities, BaseAgent subclass check
- **HealthScorer (8):** Perfect health (100/Green), P1/P2 penalty (60/Amber), excess tickets (85/Green), heartbeat silence (65/Amber), None heartbeat (100/Green), combined penalties (0/Red), all 3 escalation conditions, custom thresholds
- **Handlers (7):** health_scan with mocked tickets, escalation_outreach (verifies create_draft NOT send_email), release_notes, roadmap_preview (verifies event_bus.publish to "opportunities"), health_checkin, customer_success_review, update_relationship_profile (verifies Notion writes)
- **Error handling (3):** Unknown type raises ValueError (PM pattern), LLM failure returns fail-open dict, partial notification failure (chat fails but other channels succeed)
- **Schemas (2):** HealthScoreResult auto-computes should_escalate for all 4 conditions, TAMHandoffRequest/Response round-trip serialization
- **Gmail draft (1):** create_draft returns DraftResult with draft_id, EmailMessage has to/subject/body_html

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed heartbeat silence test assertion**
- **Found during:** Task 2
- **Issue:** Score 70 with amber_threshold=70 means `70 < 70` is False, so rag is "Green" not "Amber" -- test assertion was wrong
- **Fix:** Added 1 excess ticket (total 6) to push score to 65, which correctly yields "Amber"
- **Files modified:** tests/test_technical_account_manager.py

**2. [Rule 1 - Bug] Fixed health_scan test mock for notion_tam.get_account**
- **Found during:** Task 2
- **Issue:** AsyncMock's default return for `get_account()` was another AsyncMock object, which the agent code treated as a truthy account_page, causing account_id to be the mock's string representation
- **Fix:** Explicitly set `mock_notion.get_account = AsyncMock(return_value=None)` so agent falls through to default dict path
- **Files modified:** tests/test_technical_account_manager.py

## Verification Results

| Check | Result |
|-------|--------|
| python -m pytest tests/test_technical_account_manager.py -v | 23 passed |
| grep 'phase13.technical_account_manager' src/app/main.py | Found (2 lines) |
| grep 'app.state.technical_account_manager' src/app/main.py | Found |
| grep 'TAMScheduler' src/app/main.py | Found (4 references) |
| grep 'tam_scheduler.start' src/app/main.py | Found |
| grep 'tam_scheduler_ref.stop' src/app/main.py | Found |
| python -m pytest tests/ -x -q --timeout=30 | 1257 passed |

## Next Phase Readiness

Plan 13-05 (Sales Agent TAM handoff) can proceed -- TAM agent is wired, registered, tested, and accessible via `app.state.technical_account_manager`.
