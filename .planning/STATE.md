# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-10)

**Core value:** Sales Agent autonomously executing enterprise sales methodology at top-1% level -- the foundation for the entire 8-agent crew
**Current focus:** Phase 8 (Meeting Real-time Completion) -- Gap closure phase. 3/3 plans complete. Phase complete.

## Current Position

Phase: 8 of 9 (Meeting Real-time Completion)
Plan: 3 of 3 in phase (08-01, 08-02, 08-03 complete)
Status: Phase complete
Last activity: 2026-02-22 -- Completed 08-03-PLAN.md (Calendar Monitor Startup & Pipeline Integration Tests)

Progress: [############################################] 100% (49/49 plans completed across all phases)

## Performance Metrics

**Velocity:**
- Total plans completed: 49
- Average duration: 6 min
- Total execution time: ~5h 9min

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
| 06-meeting-capabilities | 6/6 | 41 min | 7 min |
| 07-intelligence-autonomy | 6/6 | ~37 min | 6 min |
| 08-meeting-realtime-completion | 3/3 | 10 min | 3 min |

**Recent Trend:**
- Last 5 plans: 08-03 (4 min), 08-02 (2 min), 08-01 (4 min), 07-06 (7 min), 07-05 (6 min)
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
- [06-03]: RecallClient uses httpx.AsyncClient per-request (not shared) for clean lifecycle with tenacity retry
- [06-03]: BotManager entrance greeting is best-effort: TTS failure logs warning, does NOT block meeting participation
- [06-03]: DeepgramSTT and ElevenLabsTTS use lazy imports (_ensure_X pattern) to avoid hard SDK dependency at module level
- [06-03]: HeyGenAvatar 'repeat' task_type for speak (exact text reproduction; LLM reasoning handled externally)
- [06-03]: Idle reactions mapped to text cues for avatar behavior (nod/interested/thinking)
- [06-03]: Silent MP3 placeholder in automatic_audio_output config enables output_audio REST endpoint
- [06-04]: Pipeline uses model='fast' (Haiku-class) for real-time responses (not reasoning model) per RESEARCH.md
- [06-04]: [CONF:X.XX] prefix pattern for LLM confidence signaling; SILENCE_TOKEN ("[SILENCE]") for explicit no-speak
- [06-04]: Three-gate silence check: turn-taking -> internal rep -> confidence, ALL must pass before speaking
- [06-04]: Latency degradation: 3+ consecutive budget overruns (>1000ms) triggers switch to shorter prompts
- [06-04]: Webapp uses esbuild (not webpack/vite) for lightweight bundling; only dependency: livekit-client
- [06-04]: MockLLM class (not AsyncMock) for pipeline testing to avoid hasattr attribute leak issues
- [06-05]: Minutes use model='reasoning' (Claude Sonnet) since generation is not latency-sensitive (RESEARCH.md)
- [06-05]: Map-reduce threshold MAX_TOKENS_PER_CHUNK=12000 (~15 min) using CHARS_PER_TOKEN=4.0 (matching 03-02)
- [06-05]: Chunk overlap: last 2 speaker turns from previous chunk for context continuity
- [06-05]: External email excludes participant agreement details -- customer sees decisions as simple statements
- [06-05]: save_internally is idempotent; share_externally marks minutes as shared for audit trail
- [06-06]: Briefing endpoint checks cache before requiring BriefingGenerator dependency (cache-first optimization)
- [06-06]: Webhook endpoint has no tenant auth; optional X-Recall-Token validation
- [06-06]: Phase 6 init reconstructs GSuiteAuthManager/GmailService from settings (not Phase 4 local variables)
- [06-06]: WebSocket sends silence response when no pipeline attached (graceful no-op for dev/testing)
- [07-01]: No FK constraints in intelligence tables (application-level referential integrity, consistent with Phase 5/6 pattern)
- [07-01]: GIN indexes on pattern_data and action_data JSONB columns for efficient pattern/action queries
- [07-01]: IntelligenceRepository returns Dict[str, Any] (not Pydantic schemas) -- lightweight; downstream composes as needed
- [07-01]: Goal auto-complete: update_goal_progress auto-sets status to "completed" when current_value >= target_value
- [07-01]: InMemoryIntelligenceRepository test double mirrors full interface for fast unit testing without DB
- [07-02]: GeographicAdapter composes RegionalNuances (not inherits) -- clean separation between knowledge and prompt generation
- [07-02]: CloneRepository as Protocol interface enables in-memory test doubles without mock libraries
- [07-02]: Dimension interpolation uses 3 bands: <0.3 low, 0.3-0.7 mid, >0.7 high for clear prompt guidance
- [07-02]: PersonaBuilder rule-based preview fallback ensures preview works without LLM access
- [07-02]: Region formality defaults: APAC=0.7, EMEA=0.6, Americas=0.4 (matching RegionalNuances cultural data)
- [07-02]: Methodology disclaimer mandatory in every prompt section that adapts communication style
- [07-03]: EntityLinker is stateless with per-call repository injection (no constructor dependencies)
- [07-03]: ChannelSignal as plain class (not Pydantic) for lightweight conflict resolution
- [07-03]: CustomerViewService fetches meetings via participant domain matching (MeetingRepository lacks account_id filter)
- [07-03]: Rule-based fallback summarization when LLM is unavailable (concatenate + truncate)
- [07-03]: Protocol-based interfaces (DealRepositoryProtocol, etc.) for type-safe dependency injection
- [07-04]: Hybrid rule-based + optional LLM detection for pattern recognition (rules for obvious, LLM for nuanced)
- [07-04]: Fail-open detectors: exceptions return empty list, consistent with 02-03/04-04 fail-open pattern
- [07-04]: Minimum 2 evidence points required per pattern (RESEARCH.md Pitfall 2)
- [07-04]: Confidence threshold 0.7 default, clamped to [0.3, 0.95] range for runtime tuning
- [07-04]: Real-time alerts for critical/high severity only; medium/low go to daily digest
- [07-04]: Batch deduplication by (account_id, pattern_type) within 24-hour window
- [07-05]: Stage gating includes evaluation stage (not just negotiation/closed) per CONTEXT.md
- [07-05]: Unknown action types default to approval_required (fail-safe, not hard_stop)
- [07-05]: On-track heuristic uses linear interpolation (current/target >= elapsed/total)
- [07-05]: Rule-based pattern-to-action mapping; LLM refinement is optional placeholder
- [07-05]: Critical risk -> escalation (approval required); medium risk -> follow-up (autonomous)
- [07-05]: Intelligence scheduler tasks return int count for monitoring effectiveness
- [07-06]: Persona prompt section injected AFTER methodology (Voss/QBS/BANT/MEDDIC), BEFORE Critical Rules, preventing methodology override
- [07-06]: build_system_prompt accepts optional persona_section="" for full backward compatibility with existing callers
- [07-06]: All 10 Phase 7 app.state attributes set to None in except block for graceful 503 fallback
- [07-06]: Intelligence scheduler tasks cancel during shutdown alongside Phase 4.1 learning tasks
- [07-06]: _get_intelligence_service(request, service_name) pattern for 503 fallback (matching learning.py pattern)
- [08-01]: _NoOpAvatar stub class (not MagicMock) for avatar fallback -- production-safe no-op with speak/react/stop methods
- [08-01]: Cross-tenant get_meeting_by_bot_id query safe because bot_id is globally unique (Recall.ai assigned)
- [08-01]: Pipeline stored as app.state.pipeline_{meeting.id} with UUID hyphenated string format
- [08-01]: Pipeline creation is best-effort: missing API keys skip creation with warning log
- [08-01]: TTS client for entrance greeting created separately in main.py (independent of pipeline lifecycle)
- [08-02]: Static import for livekit-client in heygen-session.js (esbuild es2020 target does not support top-level await)
- [08-02]: Vercel framework: null for plain static site deployment (no Next.js/Vite detection)
- [08-02]: Build chain: esbuild bundles JS to dist/app.js, cp copies src/index.html to dist/
- [08-03]: POLL_INTERVAL_SECONDS changed from 60 to 900 (15 minutes per roadmap)
- [08-03]: Calendar monitor task started only when both calendar_monitor and GOOGLE_DELEGATED_USER_EMAIL are available
- [08-03]: Pipeline cleanup on shutdown iterates bot_manager._active_pipelines calling shutdown on each

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
- Full test suite: 1123/1123 passing as of 08-03 completion (1116 prior + 7 pipeline lifecycle/calendar monitor integration tests).

## Session Continuity

Last session: 2026-02-22T18:00:35Z
Stopped at: Completed 08-03-PLAN.md (Calendar Monitor Startup & Pipeline Integration Tests)
Resume file: None
