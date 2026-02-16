# Phase 7 Plan 05: Autonomy System Summary

**One-liner:** GuardrailChecker with three-tier action classification (9 autonomous, 8 approval, 7 hard-stop), GoalTracker for self-directed revenue target pursuit, AutonomyEngine for guardrail-gated action planning, ProactiveScheduler with 5 background tasks, 37 passing tests.

---

## Metadata

| Field | Value |
|-------|-------|
| Phase | 07-intelligence-autonomy |
| Plan | 05 |
| Subsystem | autonomy-engine |
| Tags | guardrails, goals, autonomy, scheduler, safety |
| Duration | ~6 minutes |
| Completed | 2026-02-16 |

### Dependency Graph

- **Requires:** 07-01 (schemas, models, repository), 07-03 (consolidation schemas), 07-04 (pattern engine, insight generator)
- **Provides:** GuardrailChecker, GoalTracker, AutonomyEngine, ProactiveScheduler
- **Affects:** 07-06 (API wiring), main.py integration

### Tech Stack

- **Added:** None (all dependencies already in project)
- **Patterns:** Three-tier guardrail classification, stage gating, on-track heuristic, asyncio background loops (extending Phase 4.1)

---

## What Was Built

### GuardrailChecker (guardrails.py)

Critical safety mechanism for all autonomous actions. Three-tier classification:

| Tier | Count | Actions | Behavior |
|------|-------|---------|----------|
| Autonomous | 9 | send_follow_up_email, send_routine_response, send_chat_message, schedule_meeting, qualify_conversation, progress_early_stage, update_account_context, create_briefing, log_interaction | Allowed (unless stage-gated) |
| Approval Required | 8 | send_proposal, discuss_pricing, negotiate_terms, progress_past_evaluation, contact_c_suite, share_minutes_externally, modify_account_plan, escalate_to_management | Blocked, requires human |
| Hard Stop | 7 | commit_pricing, modify_contract, approve_discount, strategic_decision, initiate_executive_relationship, legal_commitment, market_positioning_change | NEVER allowed |

Additional protections:
- **Stage gating:** Autonomous actions blocked in negotiation, evaluation, closed_won, closed_lost stages
- **Fail-safe:** Unknown action types default to approval_required (RESEARCH.md Pitfall 3)
- **Utility methods:** classify_action(), get_allowed_actions(), get_restricted_actions()

### GoalTracker (goals.py)

Self-directed revenue target pursuit with 4 metric types:

| Method | Purpose |
|--------|---------|
| create_goal | Create with validation (target > 0, end > start) |
| update_progress | Track progress, auto-complete on target reached, detect missed deadlines |
| get_active_goals | Query active goals for tenant/clone |
| compute_metrics | Compute pipeline, activity, quality, revenue from repository |
| check_goal_status | Evaluate all goals with on-track heuristic |
| suggest_actions | Goal-type-specific corrective action suggestions |

On-track heuristic: `current_value / target_value >= days_elapsed / total_days`

### AutonomyEngine (engine.py)

Central guardrail-gated decision-making service:

| Method | Purpose |
|--------|---------|
| propose_action | Check guardrails, log for audit, route to approval workflow |
| plan_proactive_actions | Generate actions from patterns + goals (rule-based with LLM placeholder) |
| execute_approved_action | Execute after human approval verification |
| get_pending_approvals | List actions awaiting approval |
| resolve_approval | Approve or reject pending actions |

Pattern-to-action mapping:
- Buying signal -> send_follow_up_email (autonomous)
- Critical risk -> escalate_to_management (approval required)
- Medium risk -> send_follow_up_email (autonomous)
- Engagement change -> send_chat_message (autonomous)
- Goal behind target -> goal-type-specific action

### ProactiveScheduler (scheduler.py)

5 background tasks extending Phase 4.1 asyncio pattern:

| Task | Interval | Purpose |
|------|----------|---------|
| pattern_scan | 6 hours | Scan recently-active accounts for pattern changes |
| proactive_outreach_check | 1 hour | Evaluate triggered outreach through guardrails |
| goal_progress_update | 24 hours | Refresh goal progress from latest metrics |
| daily_digest_generation | 24 hours | Generate and deliver daily insight digests |
| context_summarization | 24 hours | Progressive summarization on stale customer views |

- `setup_intelligence_scheduler()` returns task dict compatible with Phase 4.1 format
- `start_intelligence_scheduler_background()` mirrors Phase 4.1 start function, stores as `app.state.intelligence_scheduler_tasks`

### Test Suite (37 tests)

| Category | Count | Coverage |
|----------|-------|----------|
| GuardrailChecker | 16 | All 3 tiers, all 7 hard stops, 4 stage gates, fail-safe, classify, utility methods |
| GoalTracker | 9 | Create, validation, progress, completion, on-track, suggestions, metrics, active filter |
| AutonomyEngine | 8 | Propose (allow/block/approval), plan proactive (buying signal, risk, empty), execute, resolve |
| ProactiveScheduler | 4 | Task definitions, interval values, resilience |
| **Total** | **37** | |

---

## Key Files

### Created
- `src/app/intelligence/autonomy/guardrails.py`
- `src/app/intelligence/autonomy/goals.py`
- `src/app/intelligence/autonomy/engine.py`
- `src/app/intelligence/autonomy/scheduler.py`
- `tests/test_autonomy.py`

### Modified
None

---

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Stage gating includes evaluation (not just negotiation/closed) | CONTEXT.md: "Deal progression past evaluation stage requires human approval" |
| Unknown actions default to approval_required (not hard_stop) | Fail-safe should require approval, not block entirely -- allows humans to still approve if needed |
| On-track heuristic uses linear interpolation | Simple and transparent; if 50% of time elapsed, 50% of target should be reached |
| Rule-based pattern-to-action mapping (LLM placeholder) | Works without LLM dependency; LLM refinement is optional enhancement |
| Scheduler tasks return int (count) | Consistent with Phase 4.1 pattern; enables monitoring of task effectiveness |
| Critical risk -> escalation, medium risk -> follow-up | Severity determines action type: critical needs human attention, medium is autonomous |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test timing drift in on-track heuristic test**
- **Found during:** Task 2 test execution
- **Issue:** Module-level `NOW` constant drifted from `datetime.now()` used inside `check_goal_status`, making 50% progress appear slightly behind 50.01% elapsed time
- **Fix:** Used fresh `datetime.now()` in test setup and set progress to 55% (comfortably ahead of ~50% elapsed)
- **Files modified:** `tests/test_autonomy.py`
- **Commit:** 8ebbb3b

---

## Next Phase Readiness

Plan 07-06 (API Wiring) can proceed:
- **GuardrailChecker** ready for API endpoints (action classification, allowed/restricted queries)
- **GoalTracker** ready for goal CRUD endpoints
- **AutonomyEngine** ready for propose/approve/reject endpoints
- **ProactiveScheduler** ready for main.py lifespan integration

No blockers identified.
