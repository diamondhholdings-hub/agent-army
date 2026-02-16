---
phase: 07-intelligence-autonomy
plan: 04
subsystem: intelligence
tags: pattern-recognition, detectors, buying-signals, risk-indicators, engagement, insights, alerts, digest

# Dependency graph
requires:
  - phase: 07-01
    provides: PatternMatch/Insight/Alert/DailyDigest schemas, IntelligenceRepository, InsightModel
provides:
  - BuyingSignalDetector, RiskIndicatorDetector, EngagementChangeDetector
  - PatternRecognitionEngine with parallel detection and confidence/evidence filtering
  - InsightGenerator for alert creation, daily digests, and feedback tracking
  - create_default_engine factory function
affects: [07-05-autonomy-engine, 07-06-api-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns: [hybrid rule-based + LLM detection, parallel asyncio.gather detector orchestration, deduplication by account+type within 24h, severity-sorted results]

key-files:
  created:
    - src/app/intelligence/patterns/detectors.py
    - src/app/intelligence/patterns/engine.py
    - src/app/intelligence/patterns/insights.py
    - tests/test_patterns.py
  modified: []

key-decisions:
  - "Hybrid detection: rule-based for obvious patterns + optional LLM for nuanced signals"
  - "Fail-open detectors: exceptions return empty list, consistent with 02-03/04-04"
  - "Minimum 2 evidence points per pattern (per RESEARCH.md Pitfall 2)"
  - "Confidence threshold 0.7 default, clamped to [0.3, 0.95] range"
  - "Real-time alerts for critical/high severity only; medium/low go to daily digest"
  - "Batch deduplication by (account_id, pattern_type) within 24-hour window"

patterns-established:
  - "Detector protocol: async detect(timeline, signals) -> list[PatternMatch]"
  - "Engine composition: detectors injected, run in parallel via asyncio.gather"
  - "Evidence-based filtering: patterns must have minimum evidence count to pass"
  - "Severity ordering: critical(0) > high(1) > medium(2) > low(3)"

# Metrics
duration: 6min
completed: 2026-02-16
---

# Phase 7 Plan 04: Pattern Recognition Summary

**Hybrid rule-based + LLM pattern detectors for buying signals, risk indicators, and engagement changes with InsightGenerator for real-time alerts, daily digests, and feedback-driven threshold tuning**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-16T19:09:53Z
- **Completed:** 2026-02-16T19:15:29Z
- **Tasks:** 2
- **Files created:** 4

## Accomplishments

- 3 pattern detectors: BuyingSignalDetector (budget, timeline, competitive, stakeholder), RiskIndicatorDetector (radio silence, budget freeze, champion departure, competitor preference, delayed responses), EngagementChangeDetector (response rate, meeting attendance, engagement depth)
- PatternRecognitionEngine orchestrates parallel detection with confidence filtering (0.7 default), evidence filtering (min 2 data points), and severity-based sorting
- InsightGenerator creates insights, deduplicates batches, sends real-time alerts for critical/high severity patterns, generates daily digests, and tracks useful/false_alarm feedback
- 38 comprehensive tests covering all detectors, engine orchestration, and insight lifecycle

## Task Commits

Each task was committed atomically:

1. **Task 1: Pattern detectors and recognition engine** - `f4ce3b2` (feat)
2. **Task 2: InsightGenerator and comprehensive tests** - `d8bb1c7` (feat)

## Files Created/Modified

- `src/app/intelligence/patterns/detectors.py` - BuyingSignalDetector, RiskIndicatorDetector, EngagementChangeDetector with hybrid rule+LLM detection
- `src/app/intelligence/patterns/engine.py` - PatternRecognitionEngine orchestrator, create_default_engine factory
- `src/app/intelligence/patterns/insights.py` - InsightGenerator for alerts, digests, feedback tracking
- `tests/test_patterns.py` - 38 tests covering all components with in-memory doubles

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Hybrid rule-based + optional LLM detection | Rules catch obvious patterns reliably; LLM catches nuanced signals rules miss. LLM is optional for environments without API access. |
| Fail-open detector pattern (return empty on error) | Consistent with existing 02-03/04-04 fail-open pattern. A broken detector should not prevent other detectors from running. |
| Minimum 2 evidence points required | Per RESEARCH.md Pitfall 2: single data points produce false positives. Requiring 2+ evidence points reduces alert fatigue. |
| Confidence threshold clamped to [0.3, 0.95] | Prevents threshold from being set too low (alert flood) or too high (misses everything). Reasonable operational bounds. |
| Pattern deduplication by (account_id, pattern_type) within 24h | Prevents the same signal from creating duplicate insights when pattern scanning runs multiple times per day. |
| Engine stamps account_id onto patterns | Detectors return patterns with empty account_id; engine fills in from UnifiedCustomerView. Keeps detectors decoupled from customer view structure. |

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Pattern recognition system complete and ready for integration with:
  - **07-05 (Autonomy Engine):** Can use PatternRecognitionEngine to detect patterns that trigger autonomous actions
  - **07-06 (API Wiring):** InsightGenerator methods ready for API endpoint binding
- create_default_engine factory provides single entry point for service initialization
- All 38 tests pass with no database dependency

---
*Phase: 07-intelligence-autonomy*
*Completed: 2026-02-16*
