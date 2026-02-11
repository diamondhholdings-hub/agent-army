# Stack Research: Agent Army Platform

**Domain:** AI Sales Agent Orchestration Platform (Multi-Agent, Multi-Tenant, Real-Time)
**Researched:** 2026-02-10
**Confidence:** MEDIUM-HIGH (verified across Context7, official docs, and multiple web sources)

---

## Executive Decision: Python Backend

**Recommendation:** Python with FastAPI for the agent orchestration backend, TypeScript/Next.js for dashboards/UI only.

**Why Python over TypeScript for agents:**
- LangGraph and CrewAI are Python-first with mature, production-tested APIs. JS ports lag 6-12 months.
- Deepgram, ElevenLabs, HeyGen, Vapi SDKs all have first-class Python support.
- Google Workspace APIs have official Python client libraries (`google-api-python-client`).
- The AI/ML ecosystem (embeddings, vector ops, data processing) is overwhelmingly Python.
- FastAPI delivers async performance competitive with Node.js for I/O-bound agent workloads.

**Confidence:** HIGH -- verified via Context7 (LangGraph, CrewAI docs) and ecosystem analysis.

---

## Recommended Stack

### 1. Agent Orchestration Framework

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **LangGraph** | 1.0.x (GA) | Core agent orchestration, state machines, multi-agent coordination | Graph-first architecture gives explicit control over agent routing, state management, and conditional branching. Production-grade with durable execution, human-in-the-loop, and time-travel debugging. Enforces business rules structurally (not just via prompts). LangGraph Platform (now LangSmith Deployment) provides managed hosting. |
| **LangSmith** | Latest | Observability, tracing, monitoring, deployment | Deep visibility into agent behavior. Trace every LLM call, tool invocation, and state transition. 1-click deploy or self-hosted. Set one env var to enable tracing. |
| **Redis 8.2** | 8.2.x | Agent state cache, event streaming, semantic cache | Sub-millisecond state access. Redis Streams for event-driven agent messaging. Semantic caching cuts LLM costs up to 70%. Vectors + caching + queues in one platform. |

**Architecture pattern:** LangGraph StateGraph as the outer skeleton. Each of the 8 agents is a node in the graph. Conditional edges route based on conversation context, customer stage, and agent expertise. Shared MessagesState maintains conversation history across agent handoffs.

```python
# Core pattern for Agent Army
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.types import Command

multi_agent_graph = (
    StateGraph(MessagesState)
    .add_node("sales_agent", sales_agent)
    .add_node("solution_architect", sa_agent)
    .add_node("pm_agent", pm_agent)
    .add_node("ba_agent", ba_agent)
    .add_node("tam_agent", tam_agent)
    .add_node("cs_agent", cs_agent)
    .add_node("collections_agent", collections_agent)
    .add_node("ops_agent", ops_agent)
    .add_edge(START, "sales_agent")  # Sales is default entry
    .compile()
)
```

**Why NOT CrewAI for core orchestration:**
- CrewAI excels at rapid prototyping and "team-of-agents" metaphors, but lacks the structural enforcement LangGraph provides for production business rules.
- Debugging is harder in CrewAI -- logging inside Tasks is a known pain point.
- LangGraph enforces "agent will never proceed with low confidence" structurally via conditional edges; CrewAI can only ask agents to be careful via prompts.
- CrewAI is good for brainstorming/creative sub-tasks. Consider nesting a CrewAI crew inside a LangGraph node for specific collaborative reasoning tasks (hybrid pattern).

**Confidence:** HIGH -- verified via Context7 (LangGraph docs, CrewAI docs), IBM comparison, multiple production comparisons.

---

### 2. LLM Integration Layer

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Anthropic Claude (claude-sonnet-4-20250514)** | API v1 | Primary reasoning LLM for agent decision-making, email drafting, analysis | Best instruction-following for complex multi-step agent tasks. Tool use / function calling is production-grade. Cost-effective for high-volume agent operations vs Opus. |
| **OpenAI gpt-realtime** | Realtime API GA | Voice conversations, speech-to-speech for phone calls | Purpose-built for voice agents. Single model handles STT+reasoning+TTS. Lower latency than chained pipeline. GA with no session limits as of Feb 2025. SIP support for phone integration. |
| **OpenAI gpt-4o** | Latest | Fallback reasoning, multi-modal (image analysis of documents/screenshots) | Multi-modal capabilities for analyzing customer-shared documents, screenshots. Good fallback if Claude rate-limited. |
| **Model Context Protocol (MCP)** | v1 (Linux Foundation) | Standardized tool/resource connections for agents | Open standard for connecting agents to external systems. 75+ connectors available. Anthropic + OpenAI + Google backing ensures longevity. Tool Search and Programmatic Tool Calling optimize production at scale. |

**LLM routing strategy:**
- **Text reasoning/planning:** Claude Sonnet 4 (primary), GPT-4o (fallback)
- **Voice conversations:** OpenAI gpt-realtime (dedicated)
- **Quick classification/routing:** Claude Haiku or GPT-4o-mini (cost optimization)
- **Embeddings:** OpenAI `text-embedding-3-large` (1536 dims, best price/performance for RAG)

**Why NOT single-provider:**
- No single provider excels at everything. Claude leads in instruction-following for agents; OpenAI leads in real-time voice.
- Multi-provider reduces single-point-of-failure risk for a production sales platform.
- MCP standardizes the integration pattern so switching/adding providers is clean.

**Confidence:** HIGH for Claude/OpenAI recommendations. MEDIUM for specific model versions (models update frequently).

---

### 3. Avatar & Video Meeting

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **HeyGen LiveAvatar** | LiveAvatar API (latest) | Real-time AI avatar for video meetings | WebRTC-based streaming with LiveKit integration. Sub-second latency for natural conversation. Custom avatar creation from video sample. Integrates with OpenAI Realtime for voice. Most mature avatar-in-meeting product. |
| **Recall.ai** | Meeting Bot API | Google Meet attendance, audio/video I/O, transcription | Works with all Google Workspace tiers. Joins via meeting link (no API limitations to work around). Custom avatar display + voice output in meetings. Real-time transcripts via webhook. $0.50/hour usage-based pricing. |

**Integration pattern:**
1. Recall.ai bot joins Google Meet as a participant with custom avatar overlay.
2. HeyGen LiveAvatar renders the visual avatar in real-time.
3. Recall.ai captures meeting audio and delivers to the LangGraph agent pipeline.
4. Agent response is rendered back through HeyGen avatar (lip-synced) and played through Recall.ai bot's audio output.

**Why NOT build a custom meeting bot:**
- Google Meet has NO official API for joining meetings or accessing real-time audio/video streams.
- The only viable approach is a headless browser bot joining as a participant via WebRTC.
- Recall.ai abstracts this complexity. Building your own means maintaining browser automation across Meet UI changes.
- At $0.50/hour, the cost is negligible compared to development time.

**Why HeyGen over alternatives:**
- **D-ID:** Good avatar quality but lacks the real-time interactive streaming maturity of HeyGen LiveAvatar.
- **Synthesia:** Focused on pre-recorded video generation, not real-time interactive avatars.
- **Tavus:** High-quality but extremely expensive and limited scalability.

**Confidence:** MEDIUM-HIGH -- HeyGen LiveAvatar is new (replacing legacy Interactive Avatar). Recall.ai is well-established. Integration between the two requires custom glue code.

---

### 4. Voice Call Handling

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Vapi** | Latest API | Voice call orchestration, phone number management, call routing | Orchestration layer over STT/LLM/TTS. Sub-500ms voice-to-voice latency. Pluggable providers (swap Deepgram/ElevenLabs/OpenAI). Open architecture -- can self-host. WebSocket + webhook support. 40+ app integrations. |
| **Deepgram** | Nova-3 | Speech-to-text (STT) for real-time transcription | Sub-300ms end-to-end latency. WebSocket streaming with persistent connections. 100ms frame chunking for low perceived delay. Best price/performance for production STT. |
| **ElevenLabs** | Flash v2.5 / Turbo v2.5 | Text-to-speech (TTS) for natural agent voice | Flash v2.5: ~75ms inference latency. Turbo v2.5: ~250ms with higher quality. Instant voice cloning from 10-second sample. 32+ languages. Streaming output starts before generation completes. |

**Voice pipeline architecture:**
```
Inbound Call (Twilio/Vapi)
  -> Deepgram STT (WebSocket, <300ms)
    -> LangGraph Agent (Claude reasoning)
      -> ElevenLabs TTS (streaming, <75ms)
        -> Audio output to caller
```

**Alternative for simpler voice:** OpenAI gpt-realtime handles the entire STT+LLM+TTS pipeline in a single model. Use this for straightforward voice conversations. Use the Vapi+Deepgram+ElevenLabs stack when you need fine-grained control over each component or want to use Claude as the reasoning LLM.

**Why Vapi over alternatives:**
- **Bland.ai:** Infrastructure-level but more opinionated. Less pluggable. Good for high-volume cold calling but less flexible for complex agent reasoning.
- **Retell:** Strong in regulated industries (healthcare, finance). Slower latency (~800ms vs Vapi's <500ms). Better compliance tooling but overkill for sales.

**Confidence:** HIGH -- Vapi architecture verified via official docs. Deepgram/ElevenLabs latency verified via official documentation.

---

### 5. GSuite Integration

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Google Workspace APIs** | v1 (GA) | Gmail, Calendar, Chat, Meet integration | Official APIs. Events API v1 is GA (v1beta decommissioned April 2025). Workspace Add-ons framework GA for multi-app integration. |
| **google-api-python-client** | Latest | Python SDK for Google APIs | Official Google-maintained. Supports all Workspace APIs. Service account + domain-wide delegation for automation. |
| **Google Workspace Add-ons** | Framework GA | Single app across Gmail, Calendar, Drive, Chat | Build once, deploy across multiple Workspace apps. GA as of 2025. |

**Integration patterns:**

| Integration | API | Auth Pattern | Notes |
|------------|-----|-------------|-------|
| **Send/read email** | Gmail API | OAuth2 (NOT service account for sending) | Service accounts cannot send email. Must use OAuth2 with user impersonation via domain-wide delegation. |
| **Calendar management** | Calendar API v3 | Service account + domain-wide delegation | Create/read/update events. Auto-schedule meetings. |
| **Google Chat messaging** | Chat API v1 | Service account as Chat app | Send messages, create spaces, manage notifications. Custom emoji support added 2025. |
| **Google Meet attendance** | Meet API via Recall.ai bot | Recall.ai API (not direct Meet API) | No official API for joining meetings. Use Recall.ai meeting bot. |
| **Meet configuration** | Meet REST API v2 | Service account | Pre-configure recording, transcripts, moderation settings programmatically. |

**Critical constraint -- Gmail sending:**
Gmail API with service accounts CANNOT send email. The service account is a "role" not a user. You MUST use OAuth2 with domain-wide delegation to impersonate a user for sending. This is a common gotcha that wastes days of debugging.

**Confidence:** HIGH for API capabilities. MEDIUM for Gmail sending limitation specifics (verified via multiple sources but nuanced -- domain-wide delegation with service account impersonation is the workaround).

---

### 6. Knowledge Base & Vector Database

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Qdrant** | 1.16.x+ | Vector database for RAG, semantic search | First-class multi-tenancy with tiered tenant system (small tenants share fallback shard, large tenants get dedicated shards). Payload-based partitioning for tenant isolation. Sub-100ms query times. Open-source with managed cloud option. Complex filtering + hybrid scoring. |
| **PostgreSQL + pgvector** | PG 16 + pgvector 0.8.x | Structured data + simple vector queries | Keep vectors alongside relational data (customers, deals, activities). Good for <5M vectors per table. Use for operational data with occasional vector search. |
| **Supabase** | Latest | Managed PostgreSQL + pgvector + auth + realtime | All-in-one backend. Built-in pgvector. Row-level security for multi-tenancy. Real-time subscriptions. Reduces infrastructure management. |

**Knowledge base architecture (multi-tenant, multi-region, multi-product):**

```
Qdrant Collection: "knowledge_base"
  |-- Payload field: "tenant_id" (skyvera | jigtree | totogi)
  |-- Payload field: "region" (apac | emea | americas)
  |-- Payload field: "product" (product identifiers)
  |-- Payload field: "doc_type" (sales_playbook | case_study | pricing | competitor_intel)
  |
  |-- Small tenants: Shared fallback shard (efficient)
  |-- Large tenants: Promoted to dedicated shards (performance isolation)
  |
  |-- HNSW config: payload_m=16, m=0 (skip global index, index per tenant)
  |-- Keyword index on tenant_id with is_tenant=true
```

**Why Qdrant over Pinecone:**
- Qdrant is open-source. Self-host or use managed cloud. No vendor lock-in.
- Tiered multitenancy (v1.16) is purpose-built for the 3-tenant (Skyvera/Jigtree/Totogi) use case.
- Pinecone's namespace-based isolation is simpler but less flexible for tenant-aware sharding.
- Cost: Qdrant self-hosted is free. Pinecone's managed pricing scales with vectors stored.

**Why keep pgvector too:**
- Operational queries ("show me all deals where the customer mentioned competitor X") need JOIN with relational data.
- pgvector handles this natively. Qdrant does not do relational queries.
- Use pgvector for <5M vectors co-located with business data. Use Qdrant for the large semantic knowledge base.

**Confidence:** HIGH -- Qdrant multitenancy verified via official docs (WebFetch). Tiered multitenancy confirmed in v1.16.

---

### 7. Real-Time Data & Event Infrastructure

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Redis 8.2** | 8.2.x | State cache, event streaming, pub/sub, semantic cache | Sub-millisecond reads. Redis Streams for agent event coordination. Pub/sub for real-time dashboard updates. Up to 35% faster in 8.2. Unified platform: vectors + cache + queues + streams. |
| **FastAPI** | 0.115.x | HTTP API server, WebSocket server | Async Python web framework. Auto-generated OpenAPI docs. Native WebSocket support for real-time client connections. Type-safe with Pydantic. |
| **Celery** | 5.4.x | Async task queue for background agent work | Distribute long-running agent tasks. Redis as broker. Retry logic, task chaining, rate limiting built-in. |
| **Server-Sent Events (SSE)** | Native | Real-time streaming of agent responses to UI | Simpler than WebSockets for server-to-client streaming. Works through proxies/load balancers. LangGraph supports SSE streaming natively. |

**Data flow architecture:**
```
Customer Interaction (email/chat/call/meeting)
  -> FastAPI ingestion endpoint
    -> Redis Stream (event bus)
      -> LangGraph agent pipeline (processing)
        -> Redis (state updates, cache)
        -> Qdrant (knowledge retrieval)
        -> PostgreSQL (business data persistence)
        -> SSE/WebSocket (real-time UI updates)
```

**Pattern recognition pipeline:**
```
All interactions -> Redis Stream -> Consolidation Worker
  -> Pattern detection (cross-customer, cross-agent insights)
    -> Qdrant (store embeddings of patterns)
    -> PostgreSQL (store structured pattern data)
    -> Alert system (notify relevant agents of patterns)
```

**Why NOT Kafka:**
- Kafka is overkill for the scale of 3 tenants with dozens of concurrent conversations.
- Redis Streams provides event streaming, consumer groups, and replay capability.
- Kafka adds operational complexity (ZooKeeper/KRaft, partition management) without proportional benefit at this scale.
- If scale exceeds thousands of concurrent conversations, migrate to Kafka. Redis Streams is the right starting point.

**Confidence:** HIGH -- Redis capabilities verified via official docs. FastAPI is well-established.

---

### 8. Deployment Architecture

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Docker** | 27.x | Containerization | Standard. All components containerized. Consistent dev/prod environments. |
| **Docker Compose** | 2.x | Local development orchestration | Run all services locally with one command. Fast iteration. |
| **Google Cloud Run** | Latest | Production container hosting | Serverless containers. Auto-scaling to zero. Pay per request. Ideal for variable agent workloads. Native Google Workspace integration (same cloud). |
| **Cloud SQL (PostgreSQL)** | PG 16 | Managed PostgreSQL | Automatic backups, failover, maintenance. pgvector extension supported. |
| **Memorystore (Redis)** | Redis 8.x | Managed Redis | Low-latency managed Redis. Redis Streams support. Same GCP region as Cloud Run. |
| **Qdrant Cloud** | 1.16.x | Managed vector database | Production-managed Qdrant with tiered multitenancy. Or self-host on GKE for cost control. |

**Why GCP over AWS/Azure:**
- GSuite/Google Workspace integration is the core requirement. GCP provides the lowest latency to Google APIs.
- Cloud Run's serverless model fits bursty agent workloads (quiet overnight, busy during business hours).
- Same IAM system for Google Workspace and infrastructure.
- If already on AWS, use ECS/Fargate instead. The stack is cloud-agnostic except for Workspace API latency.

**Why NOT Kubernetes (initially):**
- K8s adds operational overhead that is unjustified for an initial 3-tenant deployment.
- Cloud Run provides auto-scaling, rolling deploys, and traffic splitting without K8s complexity.
- Migrate to GKE when you need: custom networking, GPU workloads, or >50 microservices.

**Confidence:** MEDIUM-HIGH -- Architecture pattern is standard. Specific GCP services may change based on existing infrastructure.

---

## Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **Pydantic** | 2.x | Data validation, settings management | Everywhere. Agent state schemas, API request/response models, config. |
| **LangChain Core** | 0.3.x | LLM abstraction, tool definitions, message types | Use alongside LangGraph. NOT for agent orchestration (use LangGraph). |
| **tiktoken** | Latest | Token counting for context window management | Budget LLM context across 8 agents sharing conversation history. |
| **tenacity** | 9.x | Retry logic with exponential backoff | All external API calls (LLM, voice, avatar, GSuite). Production resilience. |
| **structlog** | 24.x | Structured logging | JSON-structured logs. Correlation IDs across agent handoffs. Essential for debugging multi-agent flows. |
| **Alembic** | 1.14.x | Database migrations | PostgreSQL schema management. Version-controlled migrations. |
| **SQLAlchemy** | 2.0.x | ORM for PostgreSQL | Async support. Type-safe queries. Alembic integration. |
| **httpx** | 0.28.x | Async HTTP client | Replace requests for async API calls to external services. |
| **pytest** | 8.x | Testing framework | Agent behavior testing, integration tests, API tests. |
| **pytest-asyncio** | Latest | Async test support | Test async agent pipelines and FastAPI endpoints. |

---

## Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **uv** | Python package manager | 10-100x faster than pip. Lock files for reproducible builds. Use over pip/poetry. |
| **Ruff** | Linter + formatter | Replaces Black + isort + flake8. Single tool. Extremely fast. |
| **pre-commit** | Git hooks | Run Ruff, type checks, tests before commit. |
| **mypy** | Static type checking | Catch type errors in agent state/message passing. Critical for multi-agent systems. |

---

## Installation

```bash
# Use uv for package management (NOT pip)
pip install uv

# Core agent framework
uv add langgraph langchain-core langchain-anthropic langchain-openai langsmith

# API framework
uv add fastapi uvicorn[standard] pydantic

# Database
uv add sqlalchemy[asyncio] asyncpg alembic psycopg2-binary

# Vector database
uv add qdrant-client

# Redis
uv add redis[hiredis]

# Task queue
uv add celery[redis]

# Google Workspace
uv add google-api-python-client google-auth-httplib2 google-auth-oauthlib

# Voice/Avatar (via their REST APIs, minimal SDK deps)
uv add httpx websockets elevenlabs deepgram-sdk

# Supporting
uv add structlog tenacity tiktoken python-dotenv

# Dev dependencies
uv add --dev pytest pytest-asyncio pytest-cov ruff mypy pre-commit
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **LangGraph** | **CrewAI** | When you need rapid prototyping of agent "teams" or creative brainstorming sub-tasks. Nest CrewAI inside a LangGraph node. |
| **LangGraph** | **AutoGen (Microsoft)** | When you need multi-agent debate/discussion patterns. Less production-ready than LangGraph. |
| **Qdrant** | **Pinecone** | When you want zero-ops fully managed and budget is not a concern. Simpler namespace isolation. |
| **Qdrant** | **Weaviate** | When you need built-in multi-modal search (text + images). HIPAA compliance on AWS (2025). |
| **Vapi** | **Bland.ai** | When doing high-volume outbound cold calling with less complex reasoning. Bland self-hosts entire model stack. |
| **Vapi** | **Retell** | When operating in healthcare/finance with strict compliance requirements. Better audit trails. |
| **HeyGen LiveAvatar** | **D-ID** | When you need simpler avatar generation without real-time interactive streaming. Lower cost for pre-recorded content. |
| **HeyGen LiveAvatar** | **Tavus** | When highest-possible avatar quality matters more than cost. Expensive and less scalable. |
| **Redis Streams** | **Apache Kafka** | When event volume exceeds thousands of concurrent conversations or you need multi-datacenter replication. |
| **Cloud Run** | **GKE (Kubernetes)** | When you need custom networking, GPU inference, or >50 microservices. |
| **FastAPI** | **LangServe** | When deploying LangChain/LangGraph chains as APIs directly. Less flexible than FastAPI for custom endpoints. |
| **Claude Sonnet** | **GPT-4o** | When you need multi-modal reasoning (image analysis). Claude is better at instruction-following for agents. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **LangChain (for agents)** | LangChain team themselves say "Use LangGraph for agents, not LangChain." LangChain is for RAG/document chains only. | LangGraph for agent orchestration. LangChain Core for types/abstractions only. |
| **Chroma** | Not production-ready for multi-tenant workloads. No built-in tenant isolation. In-memory by default. | Qdrant for production vector search. |
| **FAISS** | Library, not a database. No persistence, no multi-tenancy, no API server. Good for benchmarks, bad for production. | Qdrant or pgvector. |
| **pip / Poetry** | pip has no lock files. Poetry is slow and has dependency resolution issues. Both are inferior to uv in 2025. | uv for package management. |
| **Black + isort + flake8** | Three separate tools doing what one tool does. Slower, more config. | Ruff (single tool, 100x faster). |
| **Selenium/Playwright for Meet** | Fragile. Breaks on every Google Meet UI update. Maintenance nightmare. | Recall.ai for meeting bot abstraction. |
| **OpenAI Assistants API** | Opinionated, limited orchestration control. Vendor lock-in. No multi-agent graph support. | LangGraph + OpenAI models directly. |
| **Custom STT pipeline** | Building your own speech-to-text pipeline wastes months. | Deepgram (sub-300ms, production-ready). |
| **Kafka (at initial scale)** | Operational complexity unjustified for 3 tenants. ZooKeeper/KRaft management overhead. | Redis Streams. Migrate to Kafka when scale demands it. |
| **Kubernetes (initially)** | Operational overhead for a team building fast. Day-2 ops distraction. | Cloud Run for serverless containers. Migrate to GKE when needed. |

---

## Stack Patterns by Variant

**If only doing text interactions (email/chat, no voice/avatar):**
- Drop Vapi, Deepgram, ElevenLabs, HeyGen, Recall.ai
- Use: LangGraph + Claude + Qdrant + Redis + FastAPI + Google Workspace APIs
- This is ~60% simpler and can be built in days

**If deploying on AWS instead of GCP:**
- Replace Cloud Run with ECS Fargate or AWS Lambda
- Replace Cloud SQL with RDS PostgreSQL
- Replace Memorystore with ElastiCache Redis
- Note: Google Workspace API latency will be slightly higher (~10-30ms) from AWS regions

**If single-tenant (one business unit only):**
- Qdrant multitenancy becomes optional. Single collection with no partitioning.
- Simplify PostgreSQL schema (no tenant_id on every table).
- Remove Row Level Security complexity.

**If budget-constrained (MVP mode):**
- Replace Qdrant Cloud with self-hosted Qdrant in Docker
- Replace HeyGen LiveAvatar with static avatar image in meetings (Recall.ai supports this)
- Use OpenAI gpt-realtime-mini instead of full gpt-realtime for voice
- Use Claude Haiku for classification tasks, Sonnet only for complex reasoning

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| LangGraph 1.0.x | LangChain Core 0.3.x | LangGraph 1.0 requires langchain-core >=0.3. Do NOT use langchain-core 0.2.x. |
| LangGraph 1.0.x | langchain-anthropic latest | Use `model="anthropic:claude-sonnet-4-20250514"` format in create_react_agent. |
| FastAPI 0.115.x | Pydantic 2.x | FastAPI requires Pydantic v2. Do NOT use Pydantic v1. |
| SQLAlchemy 2.0.x | asyncpg latest | Use SQLAlchemy 2.0 async engine with asyncpg driver for PostgreSQL. |
| Qdrant Client | Qdrant 1.16.x | Client version should match or exceed server version for tiered multitenancy features. |
| Redis 8.2.x | redis-py latest | Use `redis[hiredis]` for C-accelerated parser. Hiredis gives 10x throughput improvement. |
| Google Workspace Events API | v1 (GA) | v1beta was decommissioned April 2025. Must use v1 endpoint for Chat and Meet events. |

---

## Multi-Tenancy Considerations

| Layer | Isolation Strategy | Implementation |
|-------|-------------------|----------------|
| **Application** | Tenant context middleware | FastAPI middleware extracts tenant_id from JWT. All downstream calls include tenant context. |
| **LLM/Agents** | Tenant-scoped system prompts | Each tenant's agents get tenant-specific knowledge, pricing, products, and sales methodology. |
| **Vector DB (Qdrant)** | Payload-based partitioning | `tenant_id` payload field + keyword index with `is_tenant=true`. Tiered sharding for large tenants. |
| **Relational DB** | Row Level Security (RLS) | Supabase RLS policies enforce tenant isolation at the database level. Every table has `tenant_id`. |
| **Redis** | Key prefix namespacing | All Redis keys prefixed with `{tenant_id}:`. Redis Streams per tenant for event isolation. |
| **File Storage** | Bucket/path isolation | Separate GCS buckets or path prefixes per tenant. Signed URLs for secure access. |
| **Observability** | Tenant-tagged traces | LangSmith traces tagged with tenant_id for isolated debugging and cost attribution. |

---

## Low-Latency Considerations

| Interaction Type | Latency Target | How Achieved |
|-----------------|----------------|--------------|
| **Voice call response** | <700ms voice-to-voice | Vapi orchestration + Deepgram STT (<300ms) + Claude Haiku routing (<100ms) + ElevenLabs Flash TTS (~75ms) |
| **Chat response (first token)** | <500ms | Claude streaming + SSE to client. First token appears while generation continues. |
| **Email response** | <5 seconds | Async processing. Not latency-critical. Use Sonnet for quality. |
| **Meeting avatar response** | <1 second | HeyGen LiveAvatar WebRTC + OpenAI Realtime for voice. Recall.ai handles media I/O. |
| **Knowledge retrieval** | <100ms | Qdrant sub-100ms query times. Redis semantic cache for repeated queries. |
| **Agent handoff** | <200ms | LangGraph in-process state transition. Redis for cross-instance state sync. |

---

## Sources

### Verified via Context7 (HIGH confidence)
- `/llmstxt/langchain-ai_github_io_langgraph_llms_txt` -- LangGraph multi-agent architecture, StateGraph, Command/handoff patterns, deployment
- `/crewaiinc/crewai` -- CrewAI memory, knowledge, agent orchestration, production patterns

### Verified via Official Documentation (HIGH confidence)
- [HeyGen Streaming API docs](https://docs.heygen.com/docs/streaming-api) -- LiveAvatar migration, WebRTC/LiveKit, SDK details
- [Qdrant Multitenancy Guide](https://qdrant.tech/documentation/guides/multitenancy/) -- Payload partitioning, tiered multitenancy v1.16, HNSW config
- [Vapi Quickstart docs](https://docs.vapi.ai/quickstart) -- Architecture (transcriber/model/voice), latency targets, provider pluggability
- [Google Workspace Developer Products](https://developers.google.com/workspace/products) -- API availability, Events API v1 GA
- [OpenAI Realtime API announcement](https://openai.com/index/introducing-gpt-realtime/) -- GA status, gpt-realtime model, SIP support, no session limits
- [ElevenLabs latency optimization docs](https://elevenlabs.io/docs/developers/best-practices/latency-optimization) -- Flash v2.5 75ms, Turbo v2.5 250ms
- [Deepgram Streaming API](https://developers.deepgram.com/reference/speech-to-text/listen-streaming) -- WebSocket streaming, sub-300ms latency

### Verified via Multiple Web Sources (MEDIUM confidence)
- [AI Agent Frameworks Comparison 2025](https://www.getmaxim.ai/articles/top-5-ai-agent-frameworks-in-2025-a-practical-guide-for-ai-builders/) -- LangGraph vs CrewAI ecosystem analysis
- [LangGraph vs CrewAI Production Comparison](https://xcelore.com/blog/langgraph-vs-crewai/) -- Production readiness, hybrid pattern
- [IBM Agent Framework Comparison](https://developer.ibm.com/articles/awb-comparing-ai-agent-frameworks-crewai-langgraph-and-beeai/) -- CrewAI vs LangGraph vs BeeAI
- [Voice AI Platform Ranking 2025](https://softcery.com/lab/choosing-the-right-voice-agent-platform-in-2025) -- Vapi vs Retell vs Bland comparison
- [Vector Database Comparison 2025](https://www.firecrawl.dev/blog/best-vector-databases-2025) -- Qdrant vs Pinecone vs pgvector
- [Avatar API Comparison](https://a2e.ai/top-5-best-avatar-apis-2025/) -- HeyGen vs D-ID vs Tavus vs Synthesia
- [Recall.ai Meeting Bot API](https://www.recall.ai/product/meeting-bot-api/google-meet) -- Google Meet integration, pricing
- [Redis for AI Agents](https://redis.io/redis-for-ai/) -- State management, semantic caching, event streaming
- [TypeScript vs Python for AI Agents](https://visiononedge.com/typescript-replacing-python-in-multiagent-systems/) -- Language choice analysis
- [Multi-Tenant AI Agent Architecture](https://ingenimax.ai/blog/building-multi-tenant-ai-agent) -- Isolation patterns, production considerations
- [MCP / Agentic AI Foundation](https://www.anthropic.com/news/donating-the-model-context-protocol-and-establishing-of-the-agentic-ai-foundation) -- MCP standardization, industry adoption

### Unverified / LOW Confidence (flag for validation)
- Specific pricing tiers for HeyGen LiveAvatar may have changed (credit-based, check current pricing page)
- Redis 8.2 "35% faster" claim from Redis marketing -- benchmark independently
- CrewAI "$18M Series A, 60% of Fortune 500" -- marketing claims, not independently verified

---

*Stack research for: Agent Army Platform -- AI Sales Agent Orchestration*
*Researched: 2026-02-10*
