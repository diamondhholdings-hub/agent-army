---
phase: 13-technical-account-manager-agent
plan: 03
subsystem: agent-infrastructure
tags: [health-scoring, notion-adapter, scheduler, apscheduler, ticket-client, gmail-draft, tenacity, retry]

# Dependency graph
requires:
  - phase: 13-01
    provides: TAM schemas (HealthScoreResult, TicketSummary, RelationshipProfile, CommunicationRecord, etc.)
  - phase: 11-02
    provides: NotionPMAdapter pattern, PMScheduler pattern
  - phase: 12-03
    provides: NotionBAAdapter pattern with module-level block renderers
provides:
  - HealthScorer: pure Python deterministic 0-100 health scoring with configurable thresholds
  - TicketClient: Notion DB abstraction for pre-synced Kayako/Jira ticket data
  - NotionTAMAdapter: 5 retry-wrapped methods for relationship profiles and health dashboards
  - 3 module-level block renderers for relationship profiles, health dashboards, communication logs
  - TAMScheduler: APScheduler wrapper for daily health scan and monthly check-ins
affects: [13-04 (TAM agent handlers), 13-05 (TAM wiring/dispatch)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure Python health scoring (no LLM) with configurable per-tenant thresholds"
    - "TicketClient reads from Notion DB (pre-synced Kayako/Jira) to avoid new external API dependencies"
    - "Escalation rate-limiting: max 5 alerts per daily scan to prevent notification storms"
    - "Relationship profile as Notion sub-page under account page"

key-files:
  created:
    - src/app/agents/technical_account_manager/health_scorer.py
    - src/app/agents/technical_account_manager/ticket_client.py
    - src/app/agents/technical_account_manager/notion_tam.py
    - src/app/agents/technical_account_manager/scheduler.py
  modified: []

key-decisions:
  - "HealthScorer uses keyword-only constructor args for per-tenant threshold customization"
  - "TicketClient pre-sync approach: reads from Notion DB, avoids Kayako/Jira API dependencies"
  - "GmailService.create_draft already existed from prior plan -- no modification needed"
  - "NotionTAMAdapter stores relationship profiles as sub-pages (not embedded sections) for growth flexibility"
  - "TAMScheduler rate-limits escalation alerts to max 5 per scan to prevent notification storms"

patterns-established:
  - "HealthScorer: deterministic Python scoring with RAG derivation and escalation trigger logic"
  - "TicketClient: Notion DB as unified data layer for external ticket system data"
  - "TAMScheduler: two-job pattern (daily scan + monthly check-ins) cloning PMScheduler"

# Metrics
duration: 4min
completed: 2026-02-24
---

# Phase 13 Plan 03: TAM Infrastructure Summary

**Pure Python health scorer with RAG derivation, Notion ticket client abstraction, relationship profile adapter with 3 block renderers, and dual-job scheduler for daily scans and monthly check-ins**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-24T16:38:13Z
- **Completed:** 2026-02-24T16:42:42Z
- **Tasks:** 2
- **Files created:** 4

## Accomplishments
- HealthScorer computes deterministic 0-100 scores from 3 signal categories (P1/P2 age, ticket volume, heartbeat silence) with configurable thresholds and RAG/escalation derivation -- no LLM dependency
- TicketClient abstracts Notion DB queries for pre-synced Kayako/Jira ticket data with tenacity retry, returning typed TicketSummary models
- NotionTAMAdapter with 5 retry-wrapped methods: create_relationship_profile, update_health_score, append_communication_log, query_all_accounts, get_relationship_profile_page
- 3 module-level block renderers decoupled from adapter class: render_relationship_profile_blocks, render_health_dashboard_blocks, render_communication_log_blocks
- TAMScheduler with daily health scan (7am) and monthly check-ins (1st at 10am), rate-limited escalation alerts (max 5 per scan)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create HealthScorer, TicketClient** - `348cee8` (feat)
2. **Task 2: Create NotionTAMAdapter and TAMScheduler** - `2787aa7` (feat)

## Files Created/Modified
- `src/app/agents/technical_account_manager/health_scorer.py` - Pure Python health scoring with configurable thresholds, RAG derivation, escalation trigger logic
- `src/app/agents/technical_account_manager/ticket_client.py` - Notion DB abstraction for ticket data with retry-wrapped async queries
- `src/app/agents/technical_account_manager/notion_tam.py` - NotionTAMAdapter with 5 methods + 3 module-level block renderers
- `src/app/agents/technical_account_manager/scheduler.py` - APScheduler wrapper for daily scan and monthly check-ins

## Decisions Made
- **HealthScorer keyword-only args:** Constructor uses `*` separator for all threshold params, enabling per-tenant customization without positional argument confusion
- **GmailService.create_draft already exists:** The plan specified adding create_draft to GmailService, but it was already present from a prior plan. No modifications needed, verified via AST inspection.
- **Relationship profile as sub-page:** Creates sub-pages under account pages (not embedded sections) matching PM pattern, allowing unlimited growth
- **Escalation rate-limiting:** Max 5 alerts per daily scan run, preventing notification storms when multiple accounts cross threshold simultaneously (per RESEARCH.md Pitfall 6)
- **Heartbeat None = no penalty:** None/missing heartbeat treated as "not monitored" (no penalty), not "silent" (penalty), preventing false at-risk scoring for new accounts

## Deviations from Plan

None - plan executed exactly as written. The only notable observation is that GmailService.create_draft was already implemented, so Task 1's gmail.py modification was unnecessary (no harm, just no-op).

## Issues Encountered
- Python 3.9.6 on dev machine doesn't support `str | None` syntax in config.py (requires `from __future__ import annotations`), causing existing test suite to fail on import. This is a pre-existing issue unrelated to this plan's changes. All new files use `from __future__ import annotations` for 3.9 compatibility.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All TAM infrastructure building blocks are ready for plan 04 (agent handlers)
- HealthScorer, TicketClient, NotionTAMAdapter, and TAMScheduler can be injected into TAMAgent constructor
- GmailService.create_draft available for TAM's draft-only communication pattern
- Block renderers ready for Notion page creation in handler workflows

---
*Phase: 13-technical-account-manager-agent*
*Completed: 2026-02-24*
