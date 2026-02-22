---
phase: 08-meeting-realtime-completion
plan: 01
subsystem: meetings
tags: [realtime, pipeline, botmanager, recall-ai, deepgram, elevenlabs, heygen, websocket]

# Dependency graph
requires:
  - phase: 06-meeting-capabilities
    provides: "BotManager, MeetingRepository, RealtimePipeline, STT/TTS/Avatar components"
  - phase: 07-intelligence-autonomy
    provides: "llm_service initialization in main.py lifespan"
provides:
  - "Pipeline factory method in BotManager (_create_pipeline_for_meeting)"
  - "Pipeline lifecycle management (create on in_call_recording, cleanup on call_ended)"
  - "Pipeline stored on app.state where WebSocket handler expects it"
  - "Cross-tenant get_meeting_by_bot_id repository method"
  - "MEETING_BOT_NAME, COMPANY_NAME, RECALL_AI_WEBHOOK_TOKEN config settings"
  - "_NoOpAvatar stub for graceful avatar degradation"
affects: [08-02, 08-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pipeline factory pattern: BotManager creates RealtimePipeline on bot lifecycle event"
    - "app.state pipeline storage: setattr/delattr for WebSocket handler discovery"
    - "Cross-tenant repository query: bot_id lookup without tenant_id filter"
    - "_NoOpAvatar stub pattern for graceful degradation when optional service unavailable"

key-files:
  created: []
  modified:
    - "src/app/config.py"
    - "src/app/meetings/bot/manager.py"
    - "src/app/main.py"
    - "src/app/meetings/repository.py"

key-decisions:
  - "_NoOpAvatar stub (not MagicMock) for avatar fallback -- production-safe no-op"
  - "Cross-tenant get_meeting_by_bot_id query safe because bot_id is globally unique (Recall.ai assigned)"
  - "Pipeline stored as app.state.pipeline_{meeting.id} with UUID hyphenated string format"
  - "Pipeline creation is best-effort: missing API keys skip creation with warning log"
  - "TTS client created separately for entrance greeting (independent of pipeline lifecycle)"

patterns-established:
  - "Pipeline factory: BotManager._create_pipeline_for_meeting() handles full component wiring"
  - "app.state.pipeline_{meeting_id} convention for WebSocket handler pipeline discovery"

# Metrics
duration: 4min
completed: 2026-02-22
---

# Phase 8 Plan 1: Pipeline Factory & Bot Lifecycle Wiring Summary

**RealtimePipeline factory in BotManager with app.state lifecycle, cross-tenant bot_id lookup, and _NoOpAvatar stub for graceful degradation**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-22T17:40:07Z
- **Completed:** 2026-02-22T17:43:44Z
- **Tasks:** 3/3
- **Files modified:** 4

## Accomplishments

- BotManager._create_pipeline_for_meeting() creates fully configured RealtimePipeline with STT, TTS, Avatar, SilenceChecker, and LLM service
- Pipeline stored on app.state.pipeline_{meeting_id} on in_call_recording event (where WebSocket handler reads it), cleaned up on call_ended
- MeetingRepository.get_meeting_by_bot_id performs cross-tenant query for webhook bot_id resolution
- main.py passes all 5 API keys, llm_service, and app.state to BotManager constructor
- Config extended with MEETING_BOT_NAME, COMPANY_NAME, RECALL_AI_WEBHOOK_TOKEN settings
- _NoOpAvatar stub provides production-safe fallback when HeyGen key not configured

## Task Commits

Each task was committed atomically:

1. **Task 1: Add missing config settings and update BotManager with pipeline factory** - `36bf420` (feat)
2. **Task 2: Update main.py BotManager instantiation to pass pipeline dependencies** - `a013178` (feat)
3. **Task 3: Add get_meeting_by_bot_id to MeetingRepository** - `d75360a` (feat)

## Files Created/Modified

- `src/app/config.py` - Added MEETING_BOT_NAME, COMPANY_NAME, RECALL_AI_WEBHOOK_TOKEN settings
- `src/app/meetings/bot/manager.py` - Added _NoOpAvatar stub, pipeline factory method, pipeline lifecycle in handle_bot_event, repository-based _find_meeting_by_bot_id
- `src/app/main.py` - Updated BotManager instantiation with all pipeline dependencies (API keys, llm_service, app.state, TTS client)
- `src/app/meetings/repository.py` - Added cross-tenant get_meeting_by_bot_id method

## Decisions Made

- [08-01]: _NoOpAvatar stub class (not MagicMock) for avatar fallback -- production-safe no-op with speak/react/stop methods
- [08-01]: Cross-tenant get_meeting_by_bot_id query is safe because bot_id is globally unique (assigned by Recall.ai per bot)
- [08-01]: Pipeline stored as app.state.pipeline_{meeting.id} using UUID hyphenated string format (matches WebSocket endpoint path parameter)
- [08-01]: Pipeline creation is best-effort: missing API keys or llm_service skip creation with warning log (graceful degradation)
- [08-01]: TTS client for entrance greeting created separately in main.py (independent of pipeline lifecycle)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Gap 1 from v1 milestone audit is closed: RealtimePipeline is now created and stored on app.state when bot enters in_call_recording state
- Ready for 08-02-PLAN.md (next gap closure plan in Phase 8)
- All 62 existing meeting tests pass after changes

---
*Phase: 08-meeting-realtime-completion*
*Completed: 2026-02-22*
