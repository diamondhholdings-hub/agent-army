---
phase: 06-meeting-capabilities
plan: 02
subsystem: meetings
tags: [calendar, briefing, google-calendar, instructor, litellm, qbs, pre-meeting]

# Dependency graph
requires:
  - phase: 06-meeting-capabilities
    provides: Meeting/Briefing schemas, MeetingRepository, GoogleCalendarService, InMemoryMeetingRepository
  - phase: 04-sales-agent-core
    provides: instructor + litellm pattern for structured LLM extraction
  - phase: 04.2-qbs-methodology
    provides: QBS methodology context for talk track generation
provides:
  - CalendarMonitor service for detecting agent meeting invites via Google Calendar polling
  - BriefingGenerator service for multi-format pre-meeting briefings (structured, bullet, adaptive)
  - BriefingExtraction Pydantic model for LLM-powered content generation
  - Rule-based fallback objectives and talk tracks keyed by deal stage
  - 31 unit tests covering monitor detection, classification, processing, briefing generation, formats, and fallback
affects:
  - 06-meeting-capabilities (06-03 BotManager uses CalendarMonitor for meeting detection)
  - 06-meeting-capabilities (06-06 API endpoints wire CalendarMonitor and BriefingGenerator)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CalendarMonitor: async poll loop with per-meeting error isolation"
    - "BriefingGenerator: LLM-first with rule-based fallback per deal stage"
    - "Idempotent briefing keyed by (meeting_id, scheduled_time) for reschedule handling"
    - "Attendee classification: INTERNAL/EXTERNAL/AGENT by email domain matching"

key-files:
  created:
    - src/app/meetings/calendar/__init__.py
    - src/app/meetings/calendar/monitor.py
    - src/app/meetings/calendar/briefing.py
    - tests/test_calendar_briefing.py
  modified: []

key-decisions:
  - "CalendarMonitor _classify_attendees uses agent_email exact match for AGENT role, domain suffix for INTERNAL, fallback EXTERNAL"
  - "BriefingGenerator uses model='reasoning' for LLM briefing content (quality over latency since briefings are not time-critical)"
  - "Rule-based fallback provides deal-stage-specific objectives and talk tracks for all 8 deal stages"
  - "Adaptive format uses repository history lookup (prior meetings with overlapping external attendees) to determine detail level"
  - "Last-minute meetings (within lead time) get immediate briefing -- degraded lead time preferred over no briefing"

patterns-established:
  - "CalendarMonitor: poll loop with process_upcoming_meetings -> _process_single_meeting -> _ensure_briefing chain"
  - "BriefingGenerator: _build_content -> _generate_objectives_and_tracks with LLM-first + rule fallback"
  - "Format renderers as static methods: _build_structured_briefing, _build_bullet_briefing, _build_adaptive_briefing"

# Metrics
duration: 6min
completed: 2026-02-13
---

# Phase 6 Plan 02: Pre-Meeting Pipeline Summary

**CalendarMonitor polling for agent meeting invites with BriefingGenerator creating 3-format briefings (structured/bullet/adaptive) using instructor+litellm LLM extraction with deal-stage rule-based fallback**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-13T14:32:47Z
- **Completed:** 2026-02-13T14:38:21Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- CalendarMonitor polls Google Calendar, detects explicit agent invites with Meet links, creates meeting records, and triggers briefing generation within 2-hour lead-time window
- BriefingGenerator produces briefings in all 3 formats (structured, bullet, adaptive) with account context, attendee profiles, objectives, and talk tracks
- Rule-based fallback provides deal-stage-specific content for all 8 deal stages when LLM is unavailable
- 31 unit tests covering monitor detection, attendee classification, last-minute handling, briefing generation, format rendering, and fallback behavior

## Task Commits

Each task was committed atomically:

1. **Task 1: CalendarMonitor service** - `a553f66` (feat)
2. **Task 2: BriefingGenerator and unit tests** - `35f5aba` (feat)

## Files Created/Modified
- `src/app/meetings/calendar/__init__.py` - Calendar subpackage marker
- `src/app/meetings/calendar/monitor.py` - CalendarMonitor with poll loop, event detection, attendee classification, briefing trigger
- `src/app/meetings/calendar/briefing.py` - BriefingGenerator with 3 format renderers, LLM extraction, rule-based fallback
- `tests/test_calendar_briefing.py` - 31 unit tests with InMemoryMeetingRepository test double

## Decisions Made
- CalendarMonitor classifies attendees using exact email match for AGENT, domain suffix for INTERNAL, fallback EXTERNAL
- BriefingGenerator uses model='reasoning' for LLM content since briefings are not latency-sensitive
- Rule-based fallback covers all 8 deal stages (prospecting through stalled) with stage-specific objectives and talk tracks
- Adaptive format determines detail level by checking repository for prior meetings with overlapping external attendees
- Last-minute meetings get immediate briefing generation (degraded lead time > no briefing per CONTEXT.md)
- Idempotent briefing generation keyed by meeting_id; rescheduled meetings (status reset to SCHEDULED) get new briefings

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness
- CalendarMonitor ready for BotManager integration (06-03) -- bot_manager parameter is None placeholder
- BriefingGenerator ready for deal_repository integration once Phase 5 services are wired
- Pre-meeting pipeline complete -- 06-03 (BotManager) and 06-04 (MinutesGenerator) can proceed
- No blockers for subsequent Phase 6 plans

---
*Phase: 06-meeting-capabilities*
*Completed: 2026-02-13*
