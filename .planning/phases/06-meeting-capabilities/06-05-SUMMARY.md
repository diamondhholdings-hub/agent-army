---
phase: 06-meeting-capabilities
plan: 05
subsystem: meetings
tags: [instructor, litellm, pydantic, minutes-generation, map-reduce, email-distribution, llm-extraction]

# Dependency graph
requires:
  - phase: 06-meeting-capabilities
    provides: Meeting schemas (MeetingMinutes, Transcript, Participant, ActionItem, Decision), MeetingRepository, MeetingStatus
  - phase: 04-sales-agent-core
    provides: instructor+litellm pattern for structured LLM extraction, GmailService for email sending
provides:
  - MinutesGenerator with map-reduce for long transcript extraction
  - MinutesDistributor for internal-only storage and manual external sharing
  - Pydantic instructor response models (ExtractedActionItem, ExtractedDecision, ExtractedMinutes, ChunkSummary)
  - Internal and external email builders with appropriate content filtering
  - 29 unit tests covering generator, distributor, email content, and no-auto-share
affects:
  - 06-meeting-capabilities (API endpoints will wire MinutesGenerator and MinutesDistributor)
  - 07-infrastructure-hardening (minutes generation may need performance tuning for long transcripts)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "instructor.from_litellm(litellm.acompletion) for structured minutes extraction (extends Phase 4 pattern)"
    - "Map-reduce for long transcripts: chunk at speaker boundaries, summarize chunks, synthesize final minutes"
    - "Internal-only distribution by default with manual share_externally endpoint"
    - "Graceful LLM fallback: returns empty extracted fields when instructor/litellm unavailable"

key-files:
  created:
    - src/app/meetings/minutes/__init__.py
    - src/app/meetings/minutes/generator.py
    - src/app/meetings/minutes/distributor.py
    - tests/test_minutes.py
  modified: []

key-decisions:
  - "Minutes use model='reasoning' (Claude Sonnet) since generation is not latency-sensitive (RESEARCH.md)"
  - "Map-reduce threshold: MAX_TOKENS_PER_CHUNK=12000 (~15 min of conversation) using CHARS_PER_TOKEN=4.0 estimation"
  - "Chunk overlap: last 2 speaker turns from previous chunk included for context continuity"
  - "External email excludes participant agreement details (no 'Agreed by:') for customer-appropriate content"
  - "save_internally is idempotent -- checks for existing minutes before re-saving"
  - "share_externally marks minutes as shared_externally in repository for audit trail"

patterns-established:
  - "MinutesGenerator: structured LLM extraction with map-reduce for long content"
  - "MinutesDistributor: internal-only default with explicit manual external sharing"
  - "_build_internal_email vs _build_external_email: content filtering for appropriate audience"

# Metrics
duration: 6min
completed: 2026-02-13
---

# Phase 6 Plan 05: Minutes Pipeline Summary

**MinutesGenerator with instructor+litellm map-reduce extraction and MinutesDistributor with internal-only default and manual external sharing**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-13T14:32:45Z
- **Completed:** 2026-02-13T14:38:34Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- MinutesGenerator extracts all 4 content types (verbatim transcript, executive summary, action items with owners, decisions/commitments) from transcripts using instructor+litellm
- Map-reduce handles long transcripts: chunks at speaker boundaries with 2-turn overlap, summarizes each, synthesizes final minutes
- MinutesDistributor ensures internal-only default -- no automatic external distribution (CONTEXT.md, Pitfall 7)
- Manual share_externally endpoint builds customer-appropriate emails excluding internal strategy
- Graceful fallback returns empty extracted fields when LLM unavailable
- 29 unit tests covering all generator, distributor, email builder, and anti-auto-share scenarios

## Task Commits

Each task was committed atomically:

1. **Task 1: MinutesGenerator with map-reduce** - `00edf1d` (feat)
2. **Task 2: MinutesDistributor and unit tests** - `f1f6537` (feat)

## Files Created/Modified
- `src/app/meetings/minutes/__init__.py` - Module marker for post-meeting pipeline
- `src/app/meetings/minutes/generator.py` - MinutesGenerator with map-reduce, 4 Pydantic instructor models, chunking at speaker boundaries (527 lines)
- `src/app/meetings/minutes/distributor.py` - MinutesDistributor with save_internally, notify_internal, share_externally, and email builders (398 lines)
- `tests/test_minutes.py` - 29 unit tests with InMemoryMeetingRepository test double (773 lines)

## Decisions Made
- Minutes use model='reasoning' (Claude Sonnet) since generation is not latency-sensitive per RESEARCH.md recommendation
- Map-reduce threshold set at MAX_TOKENS_PER_CHUNK=12000 tokens (~15 min of conversation) using CHARS_PER_TOKEN=4.0 estimation (matching 03-02 decision)
- Transcript chunking prefers speaker turn boundaries with 2-turn overlap for context continuity
- External email deliberately excludes "Agreed by" participant details -- customer sees decisions as simple statements
- save_internally is idempotent: checks for existing minutes before re-saving
- share_externally marks minutes as shared_externally in repository for audit trail

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None -- no new external service configuration required. Minutes generation uses existing instructor+litellm from Phase 4 and GmailService from Phase 4 for email distribution.

## Next Phase Readiness
- MinutesGenerator ready for integration with real-time pipeline (triggered by bot exit event)
- MinutesDistributor ready for API endpoint wiring (share_externally for manual distribution)
- All 4 content types confirmed: verbatim transcript (from Transcript.full_text), executive summary, action items with owners, decisions/commitments
- No blockers for subsequent Phase 6 plans

---
*Phase: 06-meeting-capabilities*
*Completed: 2026-02-13*
