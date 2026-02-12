---
phase: 05-deal-management
plan: 02
subsystem: deal-intelligence
tags: [instructor, litellm, political-mapping, opportunity-detection, pydantic, structured-extraction]

# Dependency graph
requires:
  - phase: 05-deal-management
    provides: DealRepository, Pydantic schemas (OpportunitySignals, StakeholderScores, ScoreSource, AccountPlanData, OpportunityPlanData), SQLAlchemy models
  - phase: 04-sales-agent-core
    provides: ConversationState, QualificationState, DealStage, QualificationExtractor pattern (instructor+litellm)
provides:
  - OpportunityDetector with LLM-powered signal extraction and >80% creation threshold
  - PoliticalMapper with hybrid title heuristics + LLM refinement + human override scoring
  - PlanManager for account and opportunity plan lifecycle with bounded growth
  - 43 unit tests for detection thresholds, political scoring, and plan management
affects: [05-03 crm-sync, 05-04 stage-progression, 05-05 deal-orchestration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "instructor.from_litellm(litellm.acompletion) for structured extraction (matches QualificationExtractor)"
    - "Three-layer scoring: title heuristics -> conversation signals (increase-only) -> human overrides (always-win)"
    - "Structured data assembly for plan content (not LLM generation) per RESEARCH.md"
    - "Bounded list growth via _trim_list() keeping most recent items"

key-files:
  created:
    - src/app/deals/detection.py
    - src/app/deals/political.py
    - src/app/deals/plans.py
    - tests/test_deal_detection.py
    - tests/test_deal_political.py
  modified: []

key-decisions:
  - "instructor.from_litellm pattern for opportunity detection matching Phase 4 QualificationExtractor"
  - "Title heuristic tiers: c-suite(9/8/3), vp(8/7/3), director(6/6/3), manager(4/5/3), ic(2/3/3)"
  - "Conversation signals can ONLY increase scores via max() (Pitfall 5)"
  - "Human overrides always win with 0-10 clamping (Pitfall 5)"
  - "Company profile updates via structured data assembly from conversation metadata, not LLM"
  - "ConversationScoreRefinement and RoleDetection as dedicated Pydantic models for LLM responses"

patterns-established:
  - "Three-layer political scoring: heuristic baseline -> conversation increase-only -> human override"
  - "Fail-open LLM extraction: return safe defaults on any error (consistent with 02-03, 04-03)"
  - "Bounded list growth with _trim_list() keeping most recent items (Pitfall 4)"
  - "Detection prompt includes existing opportunities to prevent duplicates (Pitfall 3)"

# Metrics
duration: 5min
completed: 2026-02-12
---

# Phase 5 Plan 02: Opportunity Detection & Political Mapping Summary

**OpportunityDetector with instructor+litellm extraction at >80% precision threshold, PoliticalMapper with 3-layer scoring (title heuristics/conversation signals/human overrides), and PlanManager with bounded account/opportunity plan lifecycle**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-12T12:56:16Z
- **Completed:** 2026-02-12T13:01:19Z
- **Tasks:** 2
- **Files created:** 5

## Accomplishments
- OpportunityDetector using instructor+litellm for structured opportunity signal extraction with deduplication via existing opportunities in prompt (Pitfall 3)
- PoliticalMapper with title heuristic tiers (c-suite/vp/director/manager/ic), LLM conversation refinement (increase-only per Pitfall 5), and human overrides that always win
- PlanManager for account and opportunity plan lifecycle with bounded list growth (MAX_KEY_EVENTS=50, MAX_INTERACTIONS=20, MAX_ACTION_ITEMS=30 per Pitfall 4)
- 43 comprehensive unit tests: 13 for detection thresholds, 30 for political scoring and plan management
- All 547 tests passing (43 new + 504 existing)

## Task Commits

Each task was committed atomically:

1. **Task 1: OpportunityDetector and PoliticalMapper** - `2807ba5` (feat)
2. **Task 2: PlanManager and unit tests** - `60fec25` (feat)

## Files Created/Modified
- `src/app/deals/detection.py` - OpportunityDetector with LLM-powered signal extraction, 0.80/0.70 thresholds
- `src/app/deals/political.py` - PoliticalMapper with title heuristics, LLM refinement, human overrides
- `src/app/deals/plans.py` - PlanManager for account/opportunity plan lifecycle with bounded growth
- `tests/test_deal_detection.py` - 13 tests for create/update thresholds and constants
- `tests/test_deal_political.py` - 30 tests for scoring, overrides, trimming, and plan CRUD

## Decisions Made
- instructor.from_litellm(litellm.acompletion) pattern matches QualificationExtractor from Phase 4 for consistency
- Title heuristic classification uses regex patterns: c-suite (CEO/CTO/CFO/COO/CIO/CISO/CRO/CMO/CPO/Chief), vp (VP/Vice President/SVP/EVP), director, manager, with ic as default
- ConversationScoreRefinement and RoleDetection as dedicated Pydantic models for LLM structured extraction responses (not inline dicts)
- Company profile updates use structured data assembly from conversation state metadata (not LLM generation) per RESEARCH.md Open Question 4
- PlanManager._trim_list keeps LAST N items (most recent) when list exceeds cap

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None -- no external service configuration required.

## Next Phase Readiness
- OpportunityDetector, PoliticalMapper, and PlanManager ready for integration in Plans 03-05
- All three services follow fail-open patterns for LLM errors
- PlanManager uses DealRepository from Plan 01 for persistence
- Political scoring and opportunity detection services are stateless (no database dependencies for scoring logic)

---
*Phase: 05-deal-management*
*Completed: 2026-02-12*
