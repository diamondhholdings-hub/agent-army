# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-10)

**Core value:** Sales Agent autonomously executing enterprise sales methodology at top-1% level -- the foundation for the entire 8-agent crew
**Current focus:** Phase 3 IN PROGRESS (Knowledge Base) -- 03-01, 03-02, 03-06 complete. Document ingestion pipeline and conversation storage operational.

## Current Position

Phase: 3 of 7 (Knowledge Base)
Plan: 03-01, 03-02, 03-06 complete; 7 total in phase
Status: In progress
Last activity: 2026-02-11 -- Completed 03-02-PLAN.md (Document Ingestion)

Progress: [##############------] 72%

## Performance Metrics

**Velocity:**
- Total plans completed: 12
- Average duration: 8 min
- Total execution time: ~1.7 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure | 3/3 | 42 min | 14 min |
| 02-agent-orchestration | 6/6 | 29 min | 5 min |
| 03-knowledge-base | 3/7 | ~30 min | 10 min |

**Recent Trend:**
- Last 5 plans: 02-06 (5 min), 03-01 (~15 min), 03-06 (6 min), 03-02 (9 min)
- Trend: Consistent ~8-10 min for Phase 3 plans

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 7 phases derived from 57 v1 requirements with dependency-driven ordering
- [Roadmap]: Multi-tenant isolation in Phase 1 (cannot be retrofitted per research)
- [Roadmap]: Async deal workflows (Phase 4-5) before real-time meetings (Phase 6)
- [Roadmap]: Phases 5 and 6 can parallelize after Phase 4 completes
- [01-01]: PostgreSQL role must be NOSUPERUSER for RLS FORCE to work
- [01-01]: Alembic uses branch labels for independent shared/tenant migration chains
- [01-01]: Tenant provisioning uses inline DDL instead of Alembic programmatic calls
- [01-01]: PostgreSQL/Redis via Homebrew locally (Docker not available); docker-compose.yml retained
- [01-01]: asyncio_default_test_loop_scope=session for consistent event loop in async tests
- [01-02]: JWT auth with python-jose, bcrypt directly (not passlib -- Python 3.13 compatibility)
- [01-02]: LiteLLM Router for provider abstraction (Claude Sonnet 4 primary, GPT-4o fallback)
- [01-02]: Prompt injection detection as heuristic layer (4 pattern categories); architectural defense is tenant isolation
- [01-02]: statement_cache_size=0 for asyncpg to avoid RLS SET command conflicts
- [01-02]: Explicit commit after SET app.current_tenant_id for session visibility
- [01-03]: Prometheus metrics with tenant_id labels for multi-tenant observability
- [01-03]: Workload Identity Federation for GitHub Actions to GCP (no long-lived keys)
- [01-03]: Google Secret Manager with per-tenant naming convention {tenant-slug}-{secret-name}
- [01-03]: Environment tiers (dev/staging/production) at deployment level, not per-tenant in v1
- [01-03]: Three health check endpoints: /health (liveness), /health/ready (readiness), /health/startup (startup)
- [01-03]: Sentry sample rates: 100% staging, 10% production
- [02-01]: TenantEventBus uses raw redis.asyncio.Redis (not TenantRedis) for direct Streams access
- [02-01]: Stream trimming via approximate MAXLEN ~1000
- [02-01]: Retry re-publishes as new message with _retry_count field
- [02-01]: DLQ replay strips all _dlq_ metadata for clean reprocessing
- [02-01]: datetime.now(timezone.utc) instead of deprecated datetime.utcnow()
- [02-02]: AgentRegistration is a dataclass (not Pydantic) -- internal metadata, not API-facing
- [02-02]: Registry stores AgentRegistration, not BaseAgent instances -- decouples metadata from lifecycle
- [02-02]: get_backup returns None for missing/unconfigured backups -- callers decide fallback
- [02-03]: Unknown handoff types default to STRICT validation (fail-safe over performance)
- [02-03]: SemanticValidator uses model='fast' (Haiku) with temperature=0.0 for deterministic validation
- [02-03]: LLM failure is fail-open to prevent blocking all agent handoffs
- [02-03]: target_agent_id must NOT be in call_chain (prevents circular handoffs)
- [02-03]: Low confidence (<0.5) handoffs logged as warnings but not rejected structurally
- [02-04]: Raw asyncpg SQL for pgvector operations (avoids SQLAlchemy pgvector complexity)
- [02-04]: cl100k_base tiktoken encoding as cross-model token counting approximation
- [02-04]: IVFFlat index with lists=100 for cosine similarity (deferred on empty tables)
- [02-04]: psycopg-binary installed for LangGraph AsyncPostgresSaver (requires psycopg3)
- [02-05]: HandoffPayload for agent->supervisor uses [agent_id] call_chain (not full chain) to satisfy validation constraints
- [02-05]: Conservative decomposition heuristic: only numbered lists or long descriptions with multiple action keywords
- [02-05]: Agent instances attached to AgentRegistration via _agent_instance for supervisor execution
- [02-05]: LLM routing uses model='fast', decomposition and synthesis use model='reasoning'
- [02-06]: Langfuse integration via LiteLLM callbacks (not @observe decorator) for automatic tracing
- [02-06]: LANGFUSE_* env vars from Settings only if not already in os.environ (env precedence)
- [02-06]: Per-module try/except in lifespan for maximum Phase 2 init resilience
- [02-06]: CostTracker returns "source: unavailable" to distinguish missing data from zero cost
- [02-06]: Agent Prometheus metrics follow existing HTTP/LLM metric patterns with tenant_id scoping
- [03-01]: Qdrant local mode for dev (path=./qdrant_data), remote URL for production
- [03-01]: Payload-based multitenancy with is_tenant=True on tenant_id for per-tenant HNSW indexes
- [03-01]: Hybrid search: dense (OpenAI text-embedding-3-small 1536d) + sparse (fastembed BM25) with RRF fusion
- [03-01]: Lazy BM25 model init to avoid heavy import on startup
- [03-01]: src/knowledge/ as separate top-level module (not under src/app/)
- [03-01]: UUID string IDs for Qdrant points matching KnowledgeChunk.id pattern
- [03-02]: RecursiveCharacterTextSplitter with ["\n\n", "\n", ". ", " "] separators for natural text boundaries
- [03-02]: Token counting via tiktoken cl100k_base, 4.0 chars/token estimate for LangChain char-based splitter
- [03-02]: Deepest-first hierarchy parsing for content_type inference (specific headers win over generic parents)
- [03-02]: PDF/DOCX loaders use lazy imports; unstructured[all-docs] not yet installed
- [03-02]: Cross-reference detection matches both full ("Charging Platform") and short ("Charging") product names
- [03-02]: MetadataExtractor enrichment preserves version, cross_references, timestamps from chunker
- [03-06]: Dense-only embeddings for conversations (no BM25 sparse) -- short natural language, semantic similarity is primary
- [03-06]: Timestamp stored as epoch float for Qdrant Range queries on integer-indexed field
- [03-06]: Cross-session context limited to 5 messages from prior sessions to avoid context bloat
- [03-06]: Non-LLM session summarization via keyword extraction (Counter) -- LLM summarization deferred to RAG layer

### Pending Todos

- None (03-01 uncommitted files resolved during 03-06 execution)

### Blockers/Concerns

- REQUIREMENTS.md states 60 v1 requirements but actual count is 57 (10 PLT + 7 KB + 30 SA + 10 INF). No missing requirements found -- likely a counting error in the original file.
- Docker not installed on dev machine -- using Homebrew services instead. CI/CD pipeline uses GitHub Actions runners which have Docker by default.
- GCP services not yet configured -- deployment pipeline will not function until user completes setup (Cloud Run API, Secret Manager API, Workload Identity Pool, service account).
- 1 pre-existing test failure (test_prompt_injection_detection from 01-02) -- does not affect functionality, likely a test sensitivity issue. Note: full suite now at 180/180 pass.

## Session Continuity

Last session: 2026-02-11T19:44:49Z
Stopped at: Completed 03-02-PLAN.md (Document Ingestion)
Resume file: None
