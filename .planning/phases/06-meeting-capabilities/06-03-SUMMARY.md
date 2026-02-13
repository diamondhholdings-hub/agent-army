---
phase: 06-meeting-capabilities
plan: 03
subsystem: meetings
tags: [recall-ai, deepgram, elevenlabs, heygen, httpx, tenacity, websocket, streaming, avatar, stt, tts]

# Dependency graph
requires:
  - phase: 06-meeting-capabilities
    provides: Meeting schemas, MeetingRepository, MeetingStatus, config settings (RECALL_AI, DEEPGRAM, ELEVENLABS, HEYGEN)
  - phase: 05-deal-management
    provides: tenacity retry pattern (NotionAdapter), session_factory CRUD pattern
provides:
  - RecallClient async HTTP wrapper for Recall.ai REST API with retry
  - BotManager for full bot lifecycle (create, early join, webhook events, entrance greeting, artifacts)
  - DeepgramSTT streaming speech-to-text with Nova-3 and endpointing
  - ElevenLabsTTS streaming text-to-speech with Flash v2.5
  - HeyGenAvatar session management with lip-sync and idle reactions
  - 24 unit tests covering all service wrappers
affects:
  - 06-meeting-capabilities (Plan 04 RealtimePipeline orchestrates these wrappers)
  - 06-meeting-capabilities (Plan 05/06 uses BotManager for meeting lifecycle)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RecallClient: tenacity retry decorator with httpx.HTTPStatusError/ConnectError/TimeoutException retry types"
    - "Lazy SDK imports for DeepgramSTT and ElevenLabsTTS (avoids hard dependency at module level)"
    - "HeyGenAvatar session rotation for duration limit handling (RESEARCH Pitfall 4)"
    - "BotManager entrance greeting as best-effort (exception swallowed, meeting continues)"

key-files:
  created:
    - src/app/meetings/bot/__init__.py
    - src/app/meetings/bot/recall_client.py
    - src/app/meetings/bot/manager.py
    - src/app/meetings/realtime/__init__.py
    - src/app/meetings/realtime/stt.py
    - src/app/meetings/realtime/tts.py
    - src/app/meetings/realtime/avatar.py
    - tests/test_bot_services.py
  modified: []

key-decisions:
  - "RecallClient uses httpx.AsyncClient per-request (not shared) for thread safety with tenacity retry"
  - "BotManager entrance greeting is best-effort: TTS or send_audio failure logs warning but does NOT block meeting"
  - "DeepgramSTT and ElevenLabsTTS use lazy imports to avoid hard dependency at module level"
  - "HeyGenAvatar 'repeat' task_type for speak (exact text reproduction, LLM handled externally)"
  - "HeyGenAvatar idle reactions map to text cues ('I see.', 'That's interesting.', 'Let me think about that.')"
  - "Silent MP3 placeholder for automatic_audio_output initialization (enables output_audio endpoint)"

patterns-established:
  - "Lazy SDK import pattern: module-level _ensure_X() for optional dependencies"
  - "Best-effort side-effects: entrance greeting wraps in try/except, logs warning, continues"
  - "Session rotation: stop old, start new, return new session info for seamless swap"

# Metrics
duration: 6min
completed: 2026-02-13
---

# Phase 6 Plan 03: Bot Services & Real-Time Wrappers Summary

**RecallClient/BotManager for Recall.ai bot lifecycle with Output Media + entrance greeting, DeepgramSTT (Nova-3 streaming), ElevenLabsTTS (Flash v2.5), and HeyGenAvatar (lip-sync + rotation) -- all with 24 unit tests**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-13T14:32:47Z
- **Completed:** 2026-02-13T14:38:57Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- RecallClient with tenacity retry (3 attempts, exponential 1-10s) covering create, status, audio, transcript, recording, delete
- BotManager with Output Media config, early join, webhook event processing, and verbal entrance greeting on join (per CONTEXT.md: no silent joining)
- DeepgramSTT configured for Nova-3 streaming with 300ms endpointing, 1s utterance_end, VAD, diarization, 16kHz PCM
- ElevenLabsTTS with Flash v2.5 (~75ms TTFB), streaming and full synthesis, MP3 output for Recall.ai
- HeyGenAvatar with session lifecycle, lip-sync speak (repeat mode), idle reactions, and session rotation for duration limits
- 24 unit tests with mocked external APIs -- full coverage of all service wrappers

## Task Commits

Each task was committed atomically:

1. **Task 1: RecallClient and BotManager** - `f95644c` (feat)
2. **Task 2: DeepgramSTT, ElevenLabsTTS, HeyGenAvatar wrappers and tests** - `0b82860` (feat)

## Files Created/Modified
- `src/app/meetings/bot/__init__.py` - Bot management module marker
- `src/app/meetings/bot/recall_client.py` - Async HTTP client for Recall.ai REST API with tenacity retry
- `src/app/meetings/bot/manager.py` - BotManager for full bot lifecycle (create, join, events, greeting, artifacts)
- `src/app/meetings/realtime/__init__.py` - Real-time services module marker
- `src/app/meetings/realtime/stt.py` - DeepgramSTT streaming speech-to-text with Nova-3
- `src/app/meetings/realtime/tts.py` - ElevenLabsTTS streaming TTS with Flash v2.5
- `src/app/meetings/realtime/avatar.py` - HeyGenAvatar session management with lip-sync and rotation
- `tests/test_bot_services.py` - 24 unit tests for all bot/realtime service wrappers

## Decisions Made
- RecallClient creates a new httpx.AsyncClient per request (not shared instance) for clean lifecycle with tenacity retry decorator
- BotManager entrance greeting is best-effort: TTS or send_audio failure logs warning but does NOT block meeting participation
- DeepgramSTT and ElevenLabsTTS use lazy imports (_ensure_X pattern) to avoid hard dependency at module level
- HeyGenAvatar uses "repeat" task_type for speak (exact text reproduction since LLM reasoning is handled externally)
- Idle reactions mapped to text cues for avatar behavior: "nod" -> "I see.", "interested" -> "That's interesting.", "thinking" -> "Let me think about that."
- Silent MP3 placeholder included in automatic_audio_output config to enable the output_audio REST endpoint

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- All five service wrappers ready for RealtimePipeline orchestration in Plan 06-04
- BotManager ready for integration with CalendarMonitor (06-02) and meeting API endpoints
- DeepgramSTT, ElevenLabsTTS, and HeyGenAvatar are standalone wrappers ready for pipeline coordination
- Total test suite: 833 tests (749 prior + 60 from 06-02 + 24 new bot services tests)
- No blockers for subsequent Phase 6 plans

---
*Phase: 06-meeting-capabilities*
*Completed: 2026-02-13*
