---
phase: 12-business-analyst-agent
plan: 03
subsystem: agent-crm-adapter
tags: [notion-api, block-renderers, requirements, gap-analysis, user-stories, process-docs, tenacity-retry]

# Dependency graph
requires:
  - phase: 12-business-analyst-agent
    plan: 01
    provides: BA Pydantic schemas (ExtractedRequirement, CapabilityGap, RequirementContradiction, UserStory, ProcessDocumentation, GapAnalysisResult, BAResult)
  - phase: 11-project-manager-agent
    plan: 02
    provides: NotionPMAdapter pattern (graceful import, pre-authenticated AsyncClient, retry-wrapped CRUD, module-level block renderers, page_id return)

provides:
  - NotionBAAdapter with 3 async CRUD methods for BA analysis Notion pages
  - 4 module-level block renderers (requirements, gap analysis, user stories, process docs)
  - 5 internal block helpers (_heading_block, _paragraph_block, _bulleted_list_block, _callout_block, _toggle_block)

affects:
  - plan: 12-04
    impact: Handlers will use NotionBAAdapter to persist BA analysis results to Notion
  - plan: 12-05
    impact: LangGraph nodes and event bus integration will use NotionBAAdapter for CRM writes

# Tech tracking
tech-stack:
  added: []
  patterns:
    - BA block renderers are module-level functions decoupled from adapter (same as PM pattern)
    - NotionBAAdapter follows NotionPMAdapter pattern (pre-authenticated AsyncClient, retry, structlog, graceful import)
    - User stories rendered with dual grouping (by epic_theme AND by stakeholder_domain)
    - Low-confidence items flagged with [LOW CONFIDENCE] prefix and callout blocks
    - Notion API 100-block limit handled with batch append loop

# File tracking
key-files:
  created:
    - src/app/agents/business_analyst/notion_ba.py
  modified: []

# Decisions
decisions:
  - id: d-1203-01
    description: NotionBAAdapter takes pre-authenticated AsyncClient, same as NotionPMAdapter
    rationale: Consistency across agents, enables shared client instances and test mocking
  - id: d-1203-02
    description: Block renderers are module-level functions, not adapter methods
    rationale: Decouples domain-to-Notion conversion from API interaction for testability
  - id: d-1203-03
    description: create_requirements_page returns page_id (UUID) not page URL
    rationale: Matches NotionPMAdapter pattern for consistent return values across adapters
  - id: d-1203-04
    description: User stories dual-grouped by epic_theme and stakeholder_domain
    rationale: Provides both implementation-oriented (epic) and organizational (domain) views

patterns-established:
  - "BA Notion adapter: same graceful-import + retry + structlog pattern as PM"
  - "Block renderers: module-level functions accepting domain models, returning list[dict]"
  - "Dual grouping: user stories shown by epic/theme with full details, then by domain with cross-references"
  - "Low-confidence flagging: [LOW CONFIDENCE] prefix + callout block for items below 0.6 threshold"

# Metrics
duration: 4min
completed: 2026-02-24
---

# Phase 12 Plan 03: Notion BA Adapter Summary

**NotionBAAdapter with 4 module-level block renderers for requirements, gap analysis, dual-grouped user stories, and process docs, following NotionPMAdapter retry/structlog pattern**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-24T08:07:07Z
- **Completed:** 2026-02-24T08:11:11Z
- **Tasks:** 2
- **Files created:** 1

## Accomplishments
- 4 module-level block renderers producing correct Notion block structures for all BA domain models
- Low-confidence items visually flagged with [LOW CONFIDENCE] prefix and warning callout blocks
- User stories dual-grouped by epic_theme (full details in toggle blocks) and stakeholder_domain (cross-references)
- NotionBAAdapter with 3 retry-wrapped async CRUD methods (create, update, query)
- Batch handling for Notion API 100-block limit with overflow append loop
- Graceful import pattern for notion-client with helpful error message on missing dependency

## Task Commits

Each task was committed atomically:

1. **Task 1: Create module-level block renderers for BA domain models** - `daeafe6` (feat) -- includes NotionBAAdapter class since both tasks target the same file

**Note:** Task 2 (NotionBAAdapter class) was implemented in the same file creation as Task 1. Since both tasks target `notion_ba.py` and the complete module was written atomically, a single commit covers both tasks.

## Files Created/Modified
- `src/app/agents/business_analyst/notion_ba.py` - NotionBAAdapter class + 4 module-level block renderers + 5 internal block helpers (635 lines)

## Decisions Made
- NotionBAAdapter takes pre-authenticated AsyncClient (not token string), matching NotionPMAdapter pattern
- Block renderers are module-level functions decoupled from adapter class for testability
- create_requirements_page returns page_id (UUID), matching NotionPMAdapter pattern (not page URL)
- User stories dual-grouped: by epic_theme (full toggle blocks with details) and by stakeholder_domain (cross-reference list)
- Blocks exceeding Notion API 100-block limit are appended in subsequent batch calls

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Python 3.9 compatibility: the agents/__init__.py import chain triggers config.py which uses `str | None` syntax (requires Python 3.10+). Resolved by installing `eval_type_backport` package for Pydantic runtime evaluation and using sys.modules isolation for verification. This is a pre-existing project issue, not introduced by this plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- NotionBAAdapter ready for integration in BA capability handlers (12-04)
- Block renderers independently testable without Notion client
- All 4 render functions exported in __all__ for clean imports
- Adapter follows same patterns as NotionPMAdapter for consistency

---
*Phase: 12-business-analyst-agent*
*Completed: 2026-02-24*
