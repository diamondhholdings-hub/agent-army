---
phase: 06-meeting-capabilities
plan: 04
subsystem: meetings
tags: [realtime-pipeline, turn-detection, silence-checker, stt, llm, tts, avatar, heygen, deepgram, livekit, vanilla-js, recall-ai, webapp]

# Dependency graph
requires:
  - phase: 06-meeting-capabilities
    provides: Meeting schemas (ParticipantRole), DeepgramSTT, ElevenLabsTTS, HeyGenAvatar wrappers, BotManager with Output Media config
  - phase: 04.2-qbs-methodology
    provides: QBS methodology context for meeting LLM prompts
provides:
  - TurnDetector for per-speaker silence tracking and pause type classification
  - SilenceChecker enforcing all three strategic silence rules (turn-taking, internal rep, confidence threshold)
  - RealtimePipeline orchestrating STT->LLM->TTS->Avatar with sub-1s latency target
  - PipelineMetrics for per-stage latency tracking
  - Output Media webapp (vanilla JS) for Recall.ai bot camera rendering HeyGen avatar
  - 33 unit tests covering all pipeline components
affects:
  - 06-meeting-capabilities (Plan 06 API endpoints will wire pipeline to WebSocket handlers)
  - 07-infrastructure-hardening (latency monitoring and pipeline health checks)

# Tech tracking
tech-stack:
  added: [livekit-client ^2.0.0 (JS, webapp only), esbuild ^0.20.0 (JS dev, webapp only)]
  patterns:
    - "TurnDetector: per-speaker silence tracking with asyncio event loop timestamps"
    - "SilenceChecker: three-gate check (turn-taking + internal rep + confidence) before every response"
    - "RealtimePipeline: [CONF:X.XX] prefix parsing for LLM confidence gating and SILENCE_TOKEN handling"
    - "MockLLM: simple async callable class for pipeline testing without AsyncMock attribute leaks"
    - "Latency degradation handling: 3+ consecutive budget overruns switches to shorter prompts"

key-files:
  created:
    - src/app/meetings/realtime/turn_detector.py
    - src/app/meetings/realtime/silence_checker.py
    - src/app/meetings/realtime/pipeline.py
    - tests/test_realtime_pipeline.py
    - meeting-bot-webapp/package.json
    - meeting-bot-webapp/src/index.html
    - meeting-bot-webapp/src/app.js
    - meeting-bot-webapp/src/pipeline/deepgram-stt.js
    - meeting-bot-webapp/src/pipeline/llm-bridge.js
    - meeting-bot-webapp/src/avatar/heygen-session.js
    - meeting-bot-webapp/src/utils/audio-processor.js
  modified: []

key-decisions:
  - "MockLLM class (not AsyncMock) for pipeline testing: avoids auto-created acompletion attribute leaking through hasattr checks"
  - "Pipeline uses model='fast' (Haiku-class) for real-time responses per RESEARCH.md (not reasoning model)"
  - "[CONF:X.XX] prefix pattern for LLM confidence signaling with regex parsing and SILENCE_TOKEN for explicit no-speak"
  - "Latency degradation threshold: 3 consecutive budget overruns triggers switch to shorter prompts"
  - "Webapp uses esbuild for lightweight bundling (no webpack/vite) per RESEARCH Pitfall 2"
  - "AudioCaptureProcessor with MediaStreamTrackProcessor primary and ScriptProcessorNode fallback for browser compatibility"
  - "LLMBridge reconnection with exponential backoff capped at 4s"

patterns-established:
  - "Three-gate silence check: turn-taking -> internal rep -> confidence, ALL must pass before speaking"
  - "Dual silence check flow: pre-LLM (rules a+b, confidence=1.0) and post-LLM (all three with actual confidence)"
  - "Pipeline confidence parsing: [CONF:X.XX] regex extraction, SILENCE_TOKEN detection, default 1.0 fallback"
  - "Sentence-boundary buffering: split at .!?:; before avatar delivery for natural speech"
  - "Output Media webapp pattern: URL params for config, getUserMedia for audio, WebSocket for backend coordination"

# Metrics
duration: 11min
completed: 2026-02-13
---

# Phase 6 Plan 04: Real-Time Pipeline & Output Media Webapp Summary

**TurnDetector/SilenceChecker/RealtimePipeline backend with three-gate strategic silence enforcement, [CONF:X.XX] confidence gating, and SILENCE_TOKEN handling -- plus vanilla JS Output Media webapp coordinating Deepgram STT, LLM Bridge, HeyGen LiveKit avatar, and PCM audio capture for Recall.ai bot camera**

## Performance

- **Duration:** 11 min
- **Started:** 2026-02-13T14:42:32Z
- **Completed:** 2026-02-13T14:53:26Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- TurnDetector distinguishes thinking pauses (2-3s) from end-of-turn pauses (1s) using asyncio event loop timestamps
- SilenceChecker enforces all three CONTEXT.md strategic silence rules (turn-taking, internal rep, confidence) with dual pre-LLM/post-LLM check flow
- RealtimePipeline orchestrates full STT->LLM->TTS->Avatar flow with sub-1s latency target, LLM timeout handling, sentence-boundary buffering, [CONF:X.XX] prefix parsing, and SILENCE_TOKEN support
- Output Media webapp in vanilla JS captures meeting audio, streams to Deepgram, routes transcripts to backend, and renders HeyGen avatar via LiveKit
- 33 unit tests covering all pipeline components (6 TurnDetector, 6 SilenceChecker, 9 RealtimePipeline, 5 PipelineMetrics, 7 sentence boundary)

## Task Commits

Each task was committed atomically:

1. **Task 1: TurnDetector, SilenceChecker, RealtimePipeline + tests** - `4c43114` (feat)
2. **Task 2: Output Media webapp (vanilla JS)** - `18889d8` (feat)

## Files Created/Modified
- `src/app/meetings/realtime/turn_detector.py` - TurnDetector: per-speaker silence tracking, pause type classification (142 lines)
- `src/app/meetings/realtime/silence_checker.py` - SilenceChecker: three strategic silence rules enforcement (152 lines)
- `src/app/meetings/realtime/pipeline.py` - RealtimePipeline + PipelineMetrics: full STT->LLM->TTS->Avatar orchestration (553 lines)
- `tests/test_realtime_pipeline.py` - 33 unit tests with MockLLM for pipeline testing
- `meeting-bot-webapp/package.json` - Webapp config with livekit-client dependency
- `meeting-bot-webapp/src/index.html` - Minimal HTML: full-viewport video element + status overlay
- `meeting-bot-webapp/src/app.js` - Main orchestrator: audio capture, STT, LLM bridge, avatar coordination (178 lines)
- `meeting-bot-webapp/src/pipeline/deepgram-stt.js` - Browser-side Deepgram WebSocket STT client (154 lines)
- `meeting-bot-webapp/src/pipeline/llm-bridge.js` - WebSocket to backend with exponential backoff reconnection
- `meeting-bot-webapp/src/avatar/heygen-session.js` - HeyGen LiveKit room connection with speak + idle reactions (207 lines)
- `meeting-bot-webapp/src/utils/audio-processor.js` - Audio capture with Float32->Int16 PCM conversion

## Decisions Made
- MockLLM class (plain async callable, no AsyncMock) for pipeline testing -- avoids auto-created `acompletion` attribute that caused `hasattr` check to falsely trigger the wrong code path
- Pipeline uses `model='fast'` (Haiku-class) for real-time responses per RESEARCH.md recommendation -- reasoning model too slow for <1s latency
- [CONF:X.XX] prefix pattern for LLM confidence signaling parsed via regex; SILENCE_TOKEN (`[SILENCE]`) treated as confidence=0.0
- Latency degradation handling: 3+ consecutive budget overruns (>1000ms) triggers switch to shorter prompts and faster model
- Webapp uses esbuild (not webpack/vite) for lightweight bundling per RESEARCH Pitfall 2 (minimize headless browser load)
- AudioCaptureProcessor uses MediaStreamTrackProcessor (Chrome 94+) with ScriptProcessorNode fallback for older browsers
- LLM Bridge reconnection: exponential backoff at 1s -> 2s -> 4s cap

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered
- Initial test failures: AsyncMock auto-creates attributes (including `acompletion`) when checked via `hasattr`, causing pipeline to take the wrong LLM call path and pass MagicMock objects to regex parsing. Fixed by creating a simple `MockLLM` class that only implements `__call__` without extraneous attributes.

## Next Phase Readiness
- Real-time pipeline backend complete -- TurnDetector, SilenceChecker, RealtimePipeline ready for WebSocket handler wiring
- Output Media webapp ready for deployment and Recall.ai Output Media URL configuration
- Total test suite: 866 tests (833 prior + 33 new pipeline tests)
- No blockers for Plan 06-06 (Meeting API endpoints and WebSocket handlers)

---
*Phase: 06-meeting-capabilities*
*Completed: 2026-02-13*
