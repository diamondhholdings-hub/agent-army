# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-10)

**Core value:** Sales Agent autonomously executing enterprise sales methodology at top-1% level -- the foundation for the entire 8-agent crew
**Current focus:** Phase 6 (Meeting Capabilities) -- In progress. Plans 01-02 complete.

## Current Position

Phase: 6 of 9 (Meeting Capabilities)
Plan: 2 of ? in phase (06-01, 06-02 complete)
Status: In progress
Last activity: 2026-02-13 -- Completed 06-02-PLAN.md (Pre-Meeting Pipeline)

Progress: [####################################] ~90% (36 plans completed, Phase 6 remaining plans + Phase 7 pending)

## Performance Metrics

**Velocity:**
- Total plans completed: 36
- Average duration: 6 min
- Total execution time: ~3h 50min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure | 3/3 | 42 min | 14 min |
| 02-agent-orchestration | 6/6 | 29 min | 5 min |
| 03-knowledge-base | 7/7 | ~61 min | 9 min |
| 04-sales-agent-core | 5/5 | 25 min | 5 min |
| 04.1-agent-learning | 3/3 | 19 min | 6 min |
| 05-deal-management | 6/6 | 29 min | 5 min |
| 04.2-qbs-methodology | 4/4 | 18 min | 5 min |
| 06-meeting-capabilities | 2/? | 11 min | 6 min |

**Recent Trend:**
- Last 5 plans: 06-02 (6 min), 06-01 (5 min), 04.2-04 (1 min), 04.2-03 (6 min), 04.2-02 (6 min)
- Trend: Consistent -- averaging 5 min per plan

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
- [03-05]: Methodology frameworks pre-populated in MethodologyLibrary constructor (no external config)
- [03-05]: Markdown chunked at ## heading level for optimal search granularity
- [03-05]: Regional pricing modifiers: APAC=0.9, EMEA=1.0, Americas=1.0
- [03-05]: FusionQuery(fusion=Fusion.RRF) replaces broken Query(fusion="rrf") for Python 3.13 compatibility
- [03-03]: Qdrant scroll API for finding existing chunks by source_document during versioning
- [03-03]: set_payload for marking old chunks is_current=False (preserves history, avoids re-upsert)
- [03-03]: Version number stored as Qdrant payload integer field (no separate metadata store)
- [03-03]: MockEmbeddingService with hash-based deterministic vectors for test reproducibility
- [03-04]: Mock embeddings produce non-semantic ranking -- retrieval tests check any result in top-K, not top-1
- [03-04]: Enterprise tier uses null pricing (contact sales model) for custom quotes
- [03-04]: Regional pricing APAC=10% discount aligns with 03-05 regional modifiers
- [03-04]: Battlecard uses generic competitor name 'Nextera BSS' for training data realism
- [03-07]: State machine pattern for RAG pipeline (not LangGraph graph compilation) for testability
- [03-07]: Separate LLM instances per component (decomposer, grading, synthesis) to prevent interference
- [03-07]: Fail-open document grading (LLM errors assume relevant) consistent with 02-03 fail-open pattern
- [03-07]: Position-based relevance scoring (decaying 0.1/rank) for deterministic ranking
- [03-07]: 50% relevance threshold triggers query rewrite, max 2 iterations
- [04-01]: Service instance caching keyed by f"gmail:{user_email}" and "chat" singleton
- [04-01]: Chat service uses service account directly (no user delegation) for bot auth
- [04-01]: Email MIME built with stdlib email.message.EmailMessage for RFC 2822 compliance
- [04-01]: HTML body with optional text fallback via set_content/add_alternative pattern
- [04-02]: Completion score as computed property (not stored) on BANTSignals (4 dims) and MEDDICSignals (6 dims)
- [04-02]: QualificationState.combined_completion averages BANT + MEDDIC scores
- [04-02]: Qualification extraction preserves existing state -- only updates fields with new evidence (anti-overwrite)
- [04-02]: Deal stage guidance for all 8 stages embedded directly in system prompts
- [04-02]: Channel configs keyed by string value (not enum) for simpler dict access in prompt builder
- [04-03]: instructor.from_litellm(litellm.acompletion) for async structured BANT+MEDDIC extraction
- [04-03]: Single LLM call for all qualification signals (anti-pattern: no per-field calls)
- [04-03]: Evidence always appended with ' | ' separator, never replaced
- [04-03]: STALLED can transition to any active stage; terminal stages (CLOSED_WON, CLOSED_LOST) have no outbound transitions
- [04-03]: qualification_data stored as JSON column for schema evolution flexibility
- [04-03]: Repository uses session_factory callable pattern for testable async CRUD
- [04-03]: _pick_by_confidence: new identified signal overrides unidentified; ties go to existing
- [04-04]: Hybrid rule-based + LLM for next-action: rules for obvious situations, LLM for nuanced
- [04-04]: Escalation trigger priority: customer_request > high_stakes > confidence_low > complexity
- [04-04]: High-stakes only triggers in NEGOTIATION and EVALUATION stages
- [04-04]: Complexity threshold: 3+ decision criteria AND 2+ identified stakeholders
- [04-04]: EventType.AGENT_HEALTH for escalation events (closest existing event type)
- [04-04]: Both NextActionEngine and EscalationManager fail-graceful with rule-based fallbacks
- [04-05]: Agent instance obtained via _get_sales_agent() reading _agent_instance from AgentRegistration (02-05 pattern)
- [04-05]: ConversationStateResponse serializes datetimes to ISO strings and enums to values for clean JSON
- [04-05]: GSuite services gracefully None when credentials missing -- agent initializes but send endpoints return 503
- [04-05]: State repository uses get_tenant_session as session_factory for tenant-scoped DB access
- [04-05]: InMemoryStateRepository in integration tests avoids database dependency
- [04.1-01]: OutcomeTracker uses session_factory callable pattern matching ConversationStateRepository
- [04.1-01]: Time windows: 24h email engagement, 168h meeting/escalation, 720h deal progression
- [04.1-01]: Deal progression scoring: 0.2 per stage advanced, capped at 1.0
- [04.1-01]: Immediate signal detection via interaction_count comparison (reply = positive)
- [04.1-01]: Bulk expire via single UPDATE statement for performance
- [04.1-01]: CalibrationBin unique constraint on (tenant_id, action_type, bin_index) for 10 bins per action type
- [04.1-01]: FeedbackEntry dual rating: -1/0/1 for inline, 1-5 for dashboard (single rating field)
- [04.1-02]: In-memory test doubles mirror service interfaces for fast unit testing without database
- [04.1-02]: Brier score uses weighted average of per-bin gaps squared, weighted by sample count
- [04.1-02]: Cold start protection: bins with < 10 samples excluded from adjustment decisions
- [04.1-02]: Adjustment damping: max 10% correction per cycle, clamped to [0.5, 1.5] scaling bounds
- [04.1-02]: Coaching uses statistical correlations (not LLM) per RESEARCH.md recommendation
- [04.1-02]: Improvement area threshold: < 40% success rate flags action type for attention
- [04.1-03]: Scheduler uses asyncio background loops (APScheduler optional upgrade path)
- [04.1-03]: CalibrationEngine.get_all_action_types requires tenant_id; scheduler calibration task is tenant-scoped placeholder
- [04.1-03]: SSE endpoint falls back to 30s polling if Redis pub/sub unavailable
- [04.1-03]: Analytics cache uses Redis with 5-min TTL per RESEARCH.md Pitfall 4
- [04.1-03]: sse-starlette added as dependency; SSE endpoint returns 501 if not installed
- [04.1-03]: Learning API dependency injection reads from app.state with 503 fallback (matches _get_sales_agent pattern)
- [05-01]: No FK constraints in deal management migration (application-level referential integrity via repository, consistent with RLS pattern)
- [05-01]: Plan data stored as JSON columns with Pydantic model_dump/model_validate for schema flexibility
- [05-01]: DealStage imported from agents.sales.schemas (not duplicated) -- single source of truth
- [05-01]: StakeholderModel allows nullable contact_email in unique constraint for stakeholders without email
- [05-01]: find_matching_opportunity uses product_line + open status for dedup simplicity
- [05-02]: instructor.from_litellm pattern for opportunity detection matching Phase 4 QualificationExtractor
- [05-02]: Title heuristic tiers: c-suite(9/8/3), vp(8/7/3), director(6/6/3), manager(4/5/3), ic(2/3/3)
- [05-02]: Conversation signals can ONLY increase scores via max() (Pitfall 5)
- [05-02]: Human overrides always win with 0-10 clamping (Pitfall 5)
- [05-02]: Company profile updates use structured data assembly, not LLM (RESEARCH.md Open Question 4)
- [05-02]: ConversationScoreRefinement and RoleDetection as dedicated Pydantic models for LLM responses
- [05-04]: MEDDIC threshold for QUALIFICATION adjusted from 0.17 to 0.16 to align with 1/6 score increment (0.1667)
- [05-04]: Signal map covers all 10 BANT+MEDDIC dimensions for future extensibility
- [05-04]: No auto-progression past NEGOTIATION -- close decisions are human-only
- [05-03]: notion-client>=2.7.0 added as dependency for Notion API 2025-09-03 support
- [05-03]: PostgresAdapter delegates all operations to DealRepository -- no additional database logic
- [05-03]: NotionAdapter gracefully handles missing notion-client with helpful ImportError
- [05-03]: SyncEngine defaults to 60-second sync interval per RESEARCH.md Pitfall 1 (Notion 3 req/sec)
- [05-03]: Field-level conflict resolution: agent-owned (agent wins), human-owned (CRM wins), shared (last-write-wins)
- [05-03]: NotionAdapter uses tenacity retry with exponential backoff (3 attempts, 1-10s wait)
- [05-05]: HookResult includes errors list for observability without breaking fire-and-forget pattern
- [05-05]: InMemoryDealRepository as test double mirrors DealRepository interface for fast unit testing
- [05-05]: All 13 API endpoints follow sales.py auth+tenant dependency pattern
- [05-06]: Request parameter (not global app import) for app.state access in sales.py hook wiring
- [05-06]: conversation_text is body.description for send_email/send_chat, body.reply_text for process_reply
- [05-06]: Hook fires synchronously after agent.invoke() but swallows all errors (fire-and-forget with warning logging)
- [05-06]: ConversationState loaded AFTER agent.invoke() so hook sees post-qualification-extraction state
- [04.2-01]: EngagementSignal.EMOTIONAL_LANGUAGE value is 'emotional_language' (not 'emotional') for clarity vs PainDepthLevel.EMOTIONAL
- [04.2-01]: QBS prompt section is a string (not messages list) for system prompt injection; analysis/expansion builders return messages lists for instructor
- [04.2-01]: build_qbs_prompt_section shows at most 3 pain topics and 3 revisit-later items to prevent prompt bloat
- [04.2-01]: Expansion detection appends known contacts to system message content (not structured parameter)
- [04.2-02]: QBS engine uses 'fast' model (not 'reasoning') for low-latency signal analysis per RESEARCH.md Pitfall 5
- [04.2-02]: Pain depth only advances forward (NOT_EXPLORED -> SURFACE -> BUSINESS_IMPACT -> EMOTIONAL), never regresses
- [04.2-02]: Back-off threshold: 3+ probes on same topic without self-elaboration or emotional recognition
- [04.2-02]: Expansion urgency override: interaction_count < 3 prevents premature 'immediate' expansion
- [04.2-02]: Max 10 pain topics with oldest-by-last_probed_at eviction; expansion state capped at 20 entries
- [04.2-02]: All three QBS components fail-open on LLM errors (engine -> rule fallback, expansion -> empty list)
- [04.2-03]: QBS methodology prompt always included in system prompt (not gated on engine presence) for base QBS awareness
- [04.2-03]: Dynamic QBS guidance is optional additive layer on top of base methodology prompt
- [04.2-03]: Pain state READ-ONLY in _get_qbs_guidance, WRITE-ONLY in _handle_process_reply -- single mutation point
- [04.2-03]: QBS processing placed BEFORE state_repository.save_state for single DB persistence call
- [04.2-04]: QBS initialization inside Phase 4 try/except (not separate block) -- failure scope matches SalesAgent lifecycle
- [06-01]: No FK constraints in meeting tables (application-level referential integrity, consistent with Phase 5 pattern)
- [06-01]: JSON columns for meeting structured data with Pydantic model_dump(mode="json")/model_validate() round-tripping
- [06-01]: TranscriptModel dual storage: entries_data JSON for real-time append + full_text Text for search
- [06-01]: Calendar service static methods for event parsing (no API call needed for invite/meet/attendee checks)
- [06-01]: CALENDAR_SCOPES as module-level constant for reuse across calendar services
- [06-01]: MeetingModel unique constraint on (tenant_id, google_event_id) for calendar event dedup
- [06-02]: CalendarMonitor classifies attendees by exact email match (AGENT), domain suffix (INTERNAL), fallback (EXTERNAL)
- [06-02]: BriefingGenerator uses model='reasoning' for LLM content (quality over latency -- briefings not time-critical)
- [06-02]: Rule-based fallback provides deal-stage-specific objectives and talk tracks for all 8 stages
- [06-02]: Adaptive briefing format uses repository history lookup for overlapping external attendees to determine detail level
- [06-02]: Last-minute meetings get immediate briefing (degraded lead time > no briefing per CONTEXT.md)
- [06-02]: Idempotent briefing keyed by meeting_id; rescheduled meetings (status reset to SCHEDULED) get new briefings

### Roadmap Evolution

Timeline of urgent insertions and roadmap adjustments:

- Phase 4.1 inserted after Phase 4: Agent Learning & Performance Feedback (2026-02-10, captured in original roadmap creation)
- Phase 4.2 inserted after Phase 4.1: QBS Methodology Integration (2026-02-12, URGENT) -- Add Question Based Selling methodology throughout all sales stages (outreach, discovery, qualification, proposal, closing) with pain funnel questions, impact questions, solution questions, confirmation questions, and expanding contacts within accounts

### Pending Todos

- None

### Blockers/Concerns

- REQUIREMENTS.md states 60 v1 requirements but actual count is 57 (10 PLT + 7 KB + 30 SA + 10 INF). No missing requirements found -- likely a counting error in the original file.
- Docker not installed on dev machine -- using Homebrew services instead. CI/CD pipeline uses GitHub Actions runners which have Docker by default.
- GCP services not yet configured -- deployment pipeline will not function until user completes setup (Cloud Run API, Secret Manager API, Workload Identity Pool, service account).
- Google Workspace credentials not yet configured -- GSuite services operational with mocked APIs in tests but require real service account and domain-wide delegation for production use.
- Full test suite: 780/780 passing as of 06-02 completion (749 prior + 31 pre-meeting pipeline tests).

## Session Continuity

Last session: 2026-02-13T14:38:21Z
Stopped at: Completed 06-02-PLAN.md (Pre-Meeting Pipeline) -- Phase 6 plan 02 complete
Resume file: None
