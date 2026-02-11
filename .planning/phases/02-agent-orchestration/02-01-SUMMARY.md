---
phase: 02-agent-orchestration
plan: 01
subsystem: events
tags: [redis-streams, pydantic, event-bus, consumer-groups, dlq, langgraph, langfuse]

# Dependency graph
requires:
  - phase: 01-infrastructure
    provides: Redis connection pool (redis-py >=5.0.0), FastAPI app, structlog
provides:
  - AgentEvent Pydantic model with source attribution and call chain traceability
  - TenantEventBus for tenant-scoped Redis Streams publish/subscribe
  - EventConsumer with exponential backoff retry (1s, 4s, 16s) and DLQ escalation
  - DeadLetterQueue with message review and replay
  - All Phase 2 dependencies installed (langgraph, langfuse, langchain-anthropic, langchain-openai, tiktoken, pgvector)
affects: [02-agent-orchestration, 03-knowledge-base]

# Tech tracking
tech-stack:
  added: [langgraph>=1.0.8, langgraph-supervisor>=0.0.31, langgraph-checkpoint-postgres>=3.0.4, langfuse>=3.14.1, langchain-anthropic>=0.3.0, langchain-openai>=0.3.0, tiktoken>=0.7.0, pgvector>=0.3.0]
  patterns: [tenant-scoped Redis Streams, consumer group processing, exponential backoff retry, dead letter queue, event source attribution with call chains]

key-files:
  created: [src/app/events/__init__.py, src/app/events/schemas.py, src/app/events/bus.py, src/app/events/consumer.py, src/app/events/dlq.py, tests/test_events.py]
  modified: [pyproject.toml]

key-decisions:
  - "Event schemas use Pydantic BaseModel with model_validator for call chain integrity"
  - "TenantEventBus uses raw redis.asyncio.Redis (not TenantRedis wrapper) for direct Streams access"
  - "Stream trimming via approximate MAXLEN ~1000 to prevent unbounded growth"
  - "Retry re-publishes as new message with incremented _retry_count (not in-place retry)"
  - "DLQ replay strips all _dlq_ metadata and _retry_count for clean reprocessing"
  - "datetime.now(timezone.utc) instead of deprecated datetime.utcnow()"

patterns-established:
  - "Stream key pattern: t:{tenant_id}:events:{stream_name}"
  - "DLQ key pattern: t:{tenant_id}:events:{stream_name}:dlq"
  - "Event serialization: to_stream_dict() for XADD, from_stream_dict() for deserialization"
  - "Source attribution: every event carries source_agent_id + call_chain for traceability"
  - "Lazy __getattr__ imports in __init__.py for clean package exports"

# Metrics
duration: 5min
completed: 2026-02-11
---

# Phase 2 Plan 01: Event Bus Infrastructure Summary

**Tenant-scoped Redis Streams event bus with AgentEvent schema, consumer group retry (1s/4s/16s backoff), and dead letter queue for agent coordination backbone**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-11T12:58:38Z
- **Completed:** 2026-02-11T13:03:39Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- AgentEvent Pydantic model with source attribution (agent ID + call chain), hybrid payload (inline data + context refs), and lossless Redis Streams serialization roundtrip
- TenantEventBus publishing/subscribing to tenant-isolated Redis Streams with MAXLEN trimming and consumer group management
- EventConsumer with exponential backoff retry (3 attempts at 1s, 4s, 16s delays) then automatic DLQ escalation
- DeadLetterQueue with message review listing and replay back to original stream
- All Phase 2 dependencies installed upfront (langgraph, langfuse, langchain-anthropic/openai, tiktoken, pgvector)
- 24 unit tests covering schema validation, serialization, tenant isolation, retry logic, DLQ flow, and package imports

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Phase 2 dependencies and create event schemas** - `9a5e159` (feat)
2. **Task 2: Build TenantEventBus, EventConsumer, DeadLetterQueue, and tests** - `b5fdcd9` (feat)

## Files Created/Modified
- `pyproject.toml` - Added 8 Phase 2 dependencies (langgraph, langfuse, langchain-*, tiktoken, pgvector)
- `src/app/events/__init__.py` - Package exports with lazy imports for bus/consumer/dlq
- `src/app/events/schemas.py` - AgentEvent model, EventType enum (9 types), EventPriority enum (4 levels)
- `src/app/events/bus.py` - TenantEventBus with publish/subscribe/ack/monitoring on tenant-scoped streams
- `src/app/events/consumer.py` - EventConsumer with process_loop, retry logic, DLQ escalation, reclaim_abandoned
- `src/app/events/dlq.py` - DeadLetterQueue with send_to_dlq, list_dlq_messages, replay_message
- `tests/test_events.py` - 24 tests across 6 test classes covering all event components

## Decisions Made
- Used `datetime.now(timezone.utc)` instead of deprecated `datetime.utcnow()` for Python 3.12+ best practice
- TenantEventBus takes raw redis.asyncio.Redis (not TenantRedis wrapper) because Streams need direct XADD/XREADGROUP access not exposed by TenantRedis
- Retry mechanism re-publishes failed messages as new stream entries with `_retry_count` field (clean separation from original message)
- DLQ replay strips all `_dlq_*` metadata and `_retry_count` to ensure clean reprocessing without residual failure state
- Used approximate MAXLEN (~1000) for stream trimming to balance memory efficiency with Redis performance
- Lazy `__getattr__` in `__init__.py` for bus/consumer/dlq to avoid import errors during incremental development

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Event bus infrastructure ready for all subsequent Phase 2 plans
- All Phase 2 dependencies pre-installed so plans 02-02 through 02-06 can focus on implementation
- TenantEventBus ready for supervisor (02-02), handoff validators (02-03), and context managers (02-04) to use
- EventConsumer + DLQ pattern established for any stream consumer in the system

---
*Phase: 02-agent-orchestration*
*Completed: 2026-02-11*
