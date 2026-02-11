---
phase: 02-agent-orchestration
plan: 04
subsystem: context
tags: [langgraph, pgvector, tiktoken, asyncpg, session, memory, embeddings, token-budget]

# Dependency graph
requires:
  - phase: 01-infrastructure
    provides: "PostgreSQL with RLS, Redis, LiteLLM Router, asyncpg engine"
provides:
  - "SessionStore wrapping LangGraph AsyncPostgresSaver for session persistence"
  - "LongTermMemory with pgvector semantic search, tenant-scoped"
  - "WorkingContextCompiler with tiktoken token budget enforcement"
  - "ContextManager orchestrating all three context tiers"
  - "Alembic migration for pgvector extension and agent_memories table"
affects: [02-agent-orchestration, 03-knowledge-base, 04-sales-agent]

# Tech tracking
tech-stack:
  added: [langgraph-checkpoint-postgres, pgvector, tiktoken, psycopg-binary]
  patterns: [three-tier-context, token-budgeted-compilation, tenant-scoped-memory, semantic-search]

key-files:
  created:
    - src/app/context/__init__.py
    - src/app/context/session.py
    - src/app/context/memory.py
    - src/app/context/working.py
    - src/app/context/manager.py
    - tests/test_context.py
    - alembic/versions/add_pgvector_and_memory_table.py
  modified: []

key-decisions:
  - "Raw asyncpg SQL for pgvector operations (avoids SQLAlchemy pgvector integration complexity)"
  - "cl100k_base tiktoken encoding as cross-model token counting approximation"
  - "IVFFlat index with lists=100 for cosine similarity (deferred creation on empty tables)"
  - "psycopg-binary installed for LangGraph AsyncPostgresSaver (requires psycopg3, not psycopg2)"

patterns-established:
  - "Three-tier context: session (checkpointer) + memory (pgvector) + working (compiled per-invocation)"
  - "Token budget allocation: 15% system, 35% session, 35% memory, 15% task+buffer"
  - "Priority truncation: oldest session messages first, least relevant memories first"
  - "Tenant isolation via WHERE tenant_id = $1 in every memory query"

# Metrics
duration: 5min
completed: 2026-02-11
---

# Phase 2 Plan 4: Context Management Summary

**Three-tier context system with LangGraph session persistence, pgvector semantic memory search, and tiktoken-budgeted working context compilation**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-11T13:02:16Z
- **Completed:** 2026-02-11T13:07:00Z
- **Tasks:** 2
- **Files created:** 7

## Accomplishments
- SessionStore wrapping LangGraph AsyncPostgresSaver with explicit-clear-only session lifetime (no time-based expiration)
- LongTermMemory with pgvector cosine similarity search, tenant-scoped, embedding generation via LiteLLM
- WorkingContextCompiler enforcing token budgets per model tier (8k fast, 32k reasoning) with priority-based truncation
- ContextManager orchestrating all three tiers in a single compile_working_context() call
- 20 unit tests covering token counting, truncation, budget allocation, orchestration, and memory operations

## Task Commits

Each task was committed atomically:

1. **Task 1: Create SessionStore and LongTermMemory** - `60fc5c2` (feat)
2. **Task 2: Build WorkingContextCompiler and ContextManager** - `e5750df` (feat)

## Files Created/Modified
- `src/app/context/__init__.py` - Package exports for all context classes
- `src/app/context/session.py` - SessionStore wrapping AsyncPostgresSaver for session persistence
- `src/app/context/memory.py` - LongTermMemory with pgvector semantic search and MemoryEntry model
- `src/app/context/working.py` - WorkingContextCompiler with tiktoken token budget enforcement
- `src/app/context/manager.py` - ContextManager orchestrating all three context tiers
- `tests/test_context.py` - 20 unit tests (371 lines) for all context components
- `alembic/versions/add_pgvector_and_memory_table.py` - Migration for pgvector extension and agent_memories table

## Decisions Made
- **Raw asyncpg for vector ops:** Used raw SQL via asyncpg instead of SQLAlchemy pgvector integration to avoid unnecessary complexity for vector operations. SQLAlchemy's pgvector support requires additional model changes that don't add value for our use case.
- **cl100k_base encoding:** Selected as a reasonable approximation for both Claude and GPT models. Exact token counts vary by model but this encoding provides consistent, accurate-enough counting for budget enforcement.
- **IVFFlat index deferred:** The IVFFlat index creation may fail on empty tables in some pgvector versions. Handled gracefully with a warning -- the index is created when possible and exact search works as fallback.
- **psycopg-binary dependency:** LangGraph's AsyncPostgresSaver requires psycopg3 (not the psycopg2-binary already in the project). Installed psycopg-binary to satisfy this requirement.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed psycopg-binary for AsyncPostgresSaver**
- **Found during:** Task 1 (SessionStore implementation)
- **Issue:** LangGraph's AsyncPostgresSaver imports from psycopg (v3), but only psycopg2-binary was installed. Import failed with "no pq wrapper available."
- **Fix:** Installed psycopg-binary via uv to provide the binary psycopg3 backend.
- **Files modified:** None (runtime dependency only)
- **Verification:** `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver` succeeds
- **Committed in:** Part of Task 1 setup

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential for AsyncPostgresSaver to function. No scope creep.

## Issues Encountered
None beyond the psycopg dependency issue handled above.

## User Setup Required
None - no external service configuration required. pgvector extension must be enabled in PostgreSQL (handled by setup() method and Alembic migration).

## Next Phase Readiness
- Context package is ready for integration with agent orchestration (supervisor, event bus)
- SessionStore.checkpointer can be passed directly to LangGraph graph.compile()
- LongTermMemory.search() and ContextManager.compile_working_context() are ready for agent invocations
- Token budget enforcement is in place for both fast (8k) and reasoning (32k) model tiers

---
*Phase: 02-agent-orchestration*
*Completed: 2026-02-11*
