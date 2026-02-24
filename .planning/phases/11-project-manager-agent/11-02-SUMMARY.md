---
phase: 11-project-manager-agent
plan: 02
subsystem: agent-prompts-and-crm
tags: [prompts, notion-api, pmbok, wbs, earned-value, status-reporting, risk-detection]

# Dependency graph
requires:
  - phase: 11-project-manager-agent
    plan: 01
    provides: PM Pydantic schemas (ProjectPlan, WBSPhase, WBSMilestone, WBSTask, RiskSignal, InternalStatusReport, ExternalStatusReport, ScopeChangeDelta)
  - phase: 10-solution-architect-agent
    plan: 01
    provides: SA prompts.py pattern (system prompt + builders returning messages lists)
  - phase: 05-deal-management
    provides: NotionAdapter pattern (tenacity retry, structlog, graceful import, AsyncClient)

provides:
  - PM_SYSTEM_PROMPT and 6 prompt builder functions for LLM-driven PM capabilities
  - NotionPMAdapter with 8 async CRUD methods for Projects database
  - render_wbs_to_notion_blocks and render_report_to_notion_blocks converters

affects:
  - plan: 11-03
    impact: Handlers will call prompt builders and pass results to LLM
  - plan: 11-04
    impact: LangGraph nodes will use NotionPMAdapter for CRM writes
  - plan: 11-05
    impact: Event bus integration will use NotionPMAdapter for milestone events

# Tech tracking
tech-stack:
  added: []
  patterns:
    - PM prompt builders embed JSON schema in user message (same as SA pattern)
    - NotionPMAdapter follows NotionAdapter retry/structlog/graceful-import pattern
    - WBS-to-blocks renderer maps 3-level hierarchy to Notion heading/todo structure
    - Report renderer supports both internal (RAG + earned value) and external (customer-facing) formats

# File tracking
key-files:
  created:
    - src/app/agents/project_manager/prompts.py
    - src/app/agents/project_manager/notion_pm.py
  modified: []

# Decisions
decisions:
  - id: d-1102-01
    description: PM prompt builders follow exact SA pattern (system+user message pairs with embedded JSON schemas)
    rationale: Consistency across agents enables shared handler infrastructure
  - id: d-1102-02
    description: NotionPMAdapter takes pre-authenticated AsyncClient rather than token string
    rationale: Allows sharing client instances and test mocking without token management
  - id: d-1102-03
    description: Block renderers are module-level functions, not adapter methods
    rationale: Decouples domain-to-Notion conversion from API interaction for testability

# Metrics
metrics:
  duration: 5 min
  completed: 2026-02-23
  tasks: 2/2
  test-regressions: 0
---

# Phase 11 Plan 02: PM Prompts and NotionPMAdapter Summary

**JWT auth with refresh rotation using jose library** -- PM prompt templates with PMBOK-certified persona and 6 capability-specific builders, plus NotionPMAdapter with 8 retry-wrapped async methods and WBS/report-to-Notion-blocks renderers.

## What Was Built

### PM Prompt Templates (prompts.py, 638 lines)

**PM_SYSTEM_PROMPT** establishes a PMBOK-certified delivery management expert persona with expertise in WBS planning, earned value management, risk identification, scope change management, and stakeholder communication. Includes the confidence protocol (>0.8 direct, 0.5-0.8 note assumptions, <0.5 flag gap).

**6 prompt builder functions**, each returning `list[dict[str, str]]` (system + user message pair):

1. `build_create_plan_prompt` -- 3-level WBS with phases/milestones/tasks, resource estimates, target dates, dependencies, and critical path. JSON schema matches ProjectPlan fields.
2. `build_detect_risks_prompt` -- 4 risk types (milestone_overdue, critical_path_blocked, resource_exceeded, deal_stage_stalled) with severity classification. JSON schema matches RiskSignal fields.
3. `build_adjust_plan_prompt` -- Scope change delta report (explicitly NOT plan regeneration). JSON schema matches ScopeChangeDelta fields with timeline/resource impact and recommendation.
4. `build_internal_report_prompt` -- Full-detail status report with PRE-CALCULATED earned value (explicitly instructs LLM not to recompute). Includes RAG guidelines (green/amber/red thresholds).
5. `build_external_report_prompt` -- Customer-facing report with "On Track"/"At Risk"/"Delayed" status (not red/amber/green). Excludes deal context, agent notes, SA summary, and earned value.
6. `build_process_trigger_prompt` -- Trigger-specific emphasis per event type (deal_won focuses delivery, poc_scoped focuses POC execution, complex_deal focuses comprehensive planning).

### NotionPMAdapter (notion_pm.py, 723 lines)

**NotionPMAdapter class** with 8 async methods, all wrapped with tenacity retry (3 attempts, exponential backoff):

1. `ensure_projects_database` -- Lazy init: creates Projects database with 14 properties (Name, Deal relation, Status, Overall RAG, dates, budget/actual days, BCWP, ACWP, risk count, change request count).
2. `create_project_record` -- Creates page in Projects database with property mapping.
3. `create_plan_subpage` -- Creates "Project Plan" sub-page under deal page with plan blocks.
4. `append_status_report` -- Appends report blocks to existing page.
5. `update_project_metrics` -- Updates project record properties (RAG, ACWP, BCWP, days, report date, risk count).
6. `append_risk_log_entry` -- Appends risk log blocks to risk log sub-page.
7. `append_change_request` -- Appends change request blocks.
8. `append_milestone_event` -- Appends milestone completion event blocks with structlog logging.

**Module-level renderers:**

- `render_wbs_to_notion_blocks` -- Converts ProjectPlan WBS to Notion blocks (H1 per phase, H2 per milestone, to-do per task with checked state, dividers between phases).
- `render_report_to_notion_blocks` -- Converts InternalStatusReport or ExternalStatusReport to Notion blocks (headings, paragraphs, bulleted lists). Internal includes risks, earned value; external includes accomplishments, upcoming activities.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- All 6 prompt builders import and return valid 2-message lists (system + user)
- PMBOK terminology present in all user messages
- PRE-CALCULATED instruction present in internal report prompt
- External report excludes internal metrics
- Trigger-specific emphasis verified for deal_won type
- NotionPMAdapter with all 8 methods verified
- WBS renderer produces 4+ blocks from minimal plan
- Internal report renderer produces 8+ blocks
- External report renderer produces 8+ blocks
- 1146 tests pass, 0 regressions

## Commits

| Hash | Message |
|------|---------|
| 0830c61 | feat(11-02): create PM prompt templates |
| e2d2465 | feat(11-02): create NotionPMAdapter for CRM operations |

## Next Phase Readiness

Plan 11-03 (PM capability handlers) can proceed immediately. Handlers will:
- Import prompt builders from prompts.py to construct LLM messages
- Import NotionPMAdapter from notion_pm.py for CRM writes
- Import schemas from schemas.py for Pydantic validation of LLM responses
