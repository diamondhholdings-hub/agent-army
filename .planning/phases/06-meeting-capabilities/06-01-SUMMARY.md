---
phase: 06-meeting-capabilities
plan: 01
subsystem: meetings
tags: [pydantic, sqlalchemy, alembic, google-calendar, recall-ai, deepgram, elevenlabs, heygen, meetings]

# Dependency graph
requires:
  - phase: 01-infrastructure
    provides: TenantBase, database engine, RLS policies, config pattern
  - phase: 04-sales-agent-core
    provides: GSuiteAuthManager for Calendar API credential management
  - phase: 05-deal-management
    provides: DealRepository session_factory pattern, migration pattern, no-FK convention
provides:
  - Meeting Pydantic schemas (Meeting, Briefing, Transcript, MeetingMinutes, Participant, ActionItem, Decision)
  - SQLAlchemy models (MeetingModel, BriefingModel, TranscriptModel, MinutesModel)
  - MeetingRepository with full async CRUD for all meeting entities
  - GoogleCalendarService with explicit invite detection and Meet URL extraction
  - Alembic migration for meetings, briefings, transcripts, meeting_minutes tables
  - InMemoryMeetingRepository test double for future tests
  - Config settings for all Phase 6 external APIs (Recall.ai, Deepgram, ElevenLabs, HeyGen)
affects:
  - 06-meeting-capabilities (all subsequent plans import schemas, models, repository)
  - 07-infrastructure-hardening (may need meeting table indexes or RLS tuning)

# Tech tracking
tech-stack:
  added: [deepgram-sdk>=3.7.0, elevenlabs>=1.15.0]
  patterns:
    - "MeetingRepository with session_factory callable (matching DealRepository/ConversationStateRepository)"
    - "JSON columns with Pydantic model_dump(mode='json')/model_validate() for schema round-tripping"
    - "GoogleCalendarService extending GSuiteAuthManager with service caching per user_email"
    - "InMemoryMeetingRepository test double for database-free unit testing"

key-files:
  created:
    - src/app/meetings/__init__.py
    - src/app/meetings/schemas.py
    - src/app/meetings/models.py
    - src/app/meetings/repository.py
    - src/app/services/gsuite/calendar.py
    - alembic/versions/add_meeting_tables.py
    - tests/test_meeting_foundation.py
  modified:
    - src/app/config.py
    - pyproject.toml

key-decisions:
  - "No FK constraints in meeting tables (application-level referential integrity, consistent with Phase 5 pattern)"
  - "JSON columns for participants_data, entries_data, action_items_data, decisions_data, key_topics_data, content_data"
  - "Calendar service uses static methods for invite/meet/attendee parsing (no API call needed for these checks)"
  - "CALENDAR_SCOPES as module-level constant for reuse across calendar-related services"
  - "TranscriptModel stores both entries_data JSON array and full_text Text column (dual storage for real-time append + search)"

patterns-established:
  - "MeetingRepository: session_factory CRUD with model_dump/model_validate for JSON columns"
  - "GoogleCalendarService: static helpers for event parsing, instance methods for API calls"
  - "InMemoryMeetingRepository: in-memory test double mirroring full repository interface"

# Metrics
duration: 5min
completed: 2026-02-13
---

# Phase 6 Plan 01: Meeting Data Foundation Summary

**Meeting schemas, SQLAlchemy models, Alembic migration, MeetingRepository CRUD, GoogleCalendarService with invite detection, and external API settings for Recall.ai/Deepgram/ElevenLabs/HeyGen**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-13T14:24:50Z
- **Completed:** 2026-02-13T14:29:53Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Complete Pydantic v2 schema contract for meetings, briefings, transcripts, minutes, participants, action items, decisions
- Four SQLAlchemy models with TenantBase, RLS policies, and three indexes per table (event dedup, status, scheduled_start)
- MeetingRepository with 15 async CRUD methods covering full meeting lifecycle
- GoogleCalendarService extending GSuiteAuthManager for Calendar API v3 with explicit invite detection
- 35 unit tests (12 schema, 12 repository, 11 calendar) all passing
- External API settings for all Phase 6 services configured in Settings class

## Task Commits

Each task was committed atomically:

1. **Task 1: Meeting schemas, models, migration, and settings** - `b67f345` (feat)
2. **Task 2: MeetingRepository, GoogleCalendarService, and tests** - `cf118c2` (feat)

## Files Created/Modified
- `src/app/meetings/__init__.py` - Module marker with Phase 6 docstring
- `src/app/meetings/schemas.py` - 13 Pydantic models: Meeting, MeetingCreate, Briefing, BriefingContent, Transcript, TranscriptEntry, MeetingMinutes, Participant, ActionItem, Decision, MeetingBriefingRequest, MinutesShareRequest + 2 enums
- `src/app/meetings/models.py` - 4 SQLAlchemy models: MeetingModel, BriefingModel, TranscriptModel, MinutesModel with TenantBase
- `src/app/meetings/repository.py` - MeetingRepository with 15 async CRUD methods using session_factory pattern
- `src/app/services/gsuite/calendar.py` - GoogleCalendarService with Calendar API v3, invite detection, Meet URL extraction
- `alembic/versions/add_meeting_tables.py` - Migration for 4 tenant-scoped tables with RLS and indexes
- `tests/test_meeting_foundation.py` - 35 unit tests with InMemoryMeetingRepository test double
- `src/app/config.py` - Added 8 Phase 6 settings (RECALL_AI, DEEPGRAM, ELEVENLABS, HEYGEN, MEETING_BOT_WEBAPP_URL)
- `pyproject.toml` - Added deepgram-sdk>=3.7.0, elevenlabs>=1.15.0

## Decisions Made
- No FK constraints in meeting tables -- application-level referential integrity via repository, consistent with Phase 5 pattern (05-01 decision)
- JSON columns for structured data with Pydantic model_dump(mode="json")/model_validate() round-tripping per 05-01 pattern
- TranscriptModel has dual storage: entries_data JSON for real-time streaming append + full_text Text for minutes generation and search
- Calendar service uses static methods for event parsing (is_agent_invited, has_google_meet_link, get_meet_url, get_attendees) since these don't require API calls
- CALENDAR_SCOPES defined as module-level constant for reuse by CalendarMonitor (future 06-02)
- MeetingModel has unique constraint on (tenant_id, google_event_id) for calendar event dedup

## Deviations from Plan

None -- plan executed exactly as written.

## User Setup Required

**External services require manual configuration.** The following environment variables need to be set before Phase 6 subsystems are operational:

- `RECALL_AI_API_KEY` - Recall.ai Dashboard -> API Keys
- `RECALL_AI_REGION` - Recall.ai Dashboard -> Settings (default: us-west-2)
- `DEEPGRAM_API_KEY` - Deepgram Console -> API Keys
- `ELEVENLABS_API_KEY` - ElevenLabs Dashboard -> API Keys
- `ELEVENLABS_VOICE_ID` - ElevenLabs Dashboard -> Voices -> select voice -> Voice ID
- `HEYGEN_API_KEY` - HeyGen Dashboard -> Settings -> API
- `HEYGEN_AVATAR_ID` - HeyGen Dashboard -> Avatars -> select avatar
- `MEETING_BOT_WEBAPP_URL` - URL where the Output Media webapp will be hosted

**Google Calendar API scopes** need to be added to domain-wide delegation:
- Add `https://www.googleapis.com/auth/calendar.readonly` and `https://www.googleapis.com/auth/calendar.events.readonly` to the service account scopes in Google Workspace Admin -> Security -> API Controls -> Domain-wide delegation

## Next Phase Readiness
- Schema contract established -- all subsequent Phase 6 plans can import Meeting, Briefing, Transcript, MeetingMinutes
- MeetingRepository ready for CalendarMonitor (06-02), BotManager (06-03), MinutesGenerator (06-04)
- GoogleCalendarService ready for CalendarMonitor to detect agent meeting invites
- InMemoryMeetingRepository available as test double for all Phase 6 integration tests
- No blockers for subsequent Phase 6 plans

---
*Phase: 06-meeting-capabilities*
*Completed: 2026-02-13*
