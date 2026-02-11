# Architecture Research

**Domain:** Multi-Agent AI Sales Platform (8 Specialized Agents)
**Researched:** 2026-02-10
**Confidence:** MEDIUM — Architecture patterns for multi-agent systems are rapidly evolving; recommendations synthesize current best practices from multiple verified sources but some component-level choices will need validation during implementation.

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       CLIENT / INTERACTION LAYER                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐               │
│  │ Web UI   │  │ Meeting  │  │ Voice    │  │ Email/    │               │
│  │ Dashboard│  │ Client   │  │ Client   │  │ Chat      │               │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬─────┘               │
├───────┴──────────────┴──────────────┴──────────────┴────────────────────┤
│                         API GATEWAY / ROUTER                             │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  Auth (OAuth 2.0/OIDC) │ Rate Limiting │ Tenant Resolution      │   │
│  │  Request Routing       │ WebSocket Mgmt │ Load Balancing        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                      AGENT ORCHESTRATION LAYER                           │
│  ┌───────────────────────────────────────────────────────────────┐      │
│  │                  SUPERVISOR ORCHESTRATOR                       │      │
│  │  Task Decomposition │ Agent Routing │ Result Synthesis         │      │
│  └──────────┬────────────────────┬───────────────────┬───────────┘      │
│             │                    │                   │                   │
│  ┌──────────┴──────────┐ ┌──────┴──────┐ ┌──────────┴──────────┐       │
│  │  DEAL COORDINATION  │ │  CUSTOMER   │ │  ADMIN / ANALYTICS  │       │
│  │  AGENT GROUP        │ │  INTERACTION│ │  AGENT GROUP        │       │
│  │                     │ │  AGENT GROUP│ │                     │       │
│  │ ┌─────┐ ┌────────┐ │ │ ┌─────────┐ │ │ ┌────────┐ ┌─────┐ │       │
│  │ │Strat│ │Pipeline│ │ │ │Meeting  │ │ │ │Consoli-│ │Coach│ │       │
│  │ │-egy │ │Manager │ │ │ │Attend   │ │ │ │dation  │ │     │ │       │
│  │ └─────┘ └────────┘ │ │ └─────────┘ │ │ └────────┘ └─────┘ │       │
│  │ ┌─────┐ ┌────────┐ │ │ ┌─────────┐ │ │ ┌────────┐         │       │
│  │ │Disco│ │Proposal│ │ │ │Voice    │ │ │ │Forecast│         │       │
│  │ │-very│ │Writer  │ │ │ │Handler  │ │ │ │        │         │       │
│  │ └─────┘ └────────┘ │ │ └─────────┘ │ │ └────────┘         │       │
│  └─────────────────────┘ └─────────────┘ └─────────────────────┘       │
├─────────────────────────────────────────────────────────────────────────┤
│                     EVENT BUS / MESSAGE BACKBONE                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  Event Topics: deal.*, meeting.*, conversation.*, analytics.*    │   │
│  │  Agent-to-Agent messaging │ Async task queues │ Event sourcing   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                      SHARED SERVICES LAYER                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │ LLM      │ │ Knowledge│ │ Context  │ │ Avatar   │ │ Voice    │     │
│  │ Gateway  │ │ Base     │ │ Manager  │ │ Engine   │ │ Pipeline │     │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                               │
│  │ Tenant   │ │ Clone    │ │ Integr-  │                               │
│  │ Manager  │ │ Registry │ │ ation Hub│                               │
│  └──────────┘ └──────────┘ └──────────┘                               │
├─────────────────────────────────────────────────────────────────────────┤
│                      INTEGRATION LAYER                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │ CRM      │ │ GSuite   │ │ Meeting  │ │ Voice    │ │ Avatar   │     │
│  │ Adapter  │ │ Adapter  │ │ Platform │ │ Provider │ │ Provider │     │
│  │(Salesforc│ │(Calendar,│ │ Adapter  │ │ Adapter  │ │ Adapter  │     │
│  │ HubSpot) │ │Gmail,Doc)│ │(Zoom,etc)│ │(Twilio)  │ │(Tavus,   │     │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ │HeyGen)   │     │
│                                                       └──────────┘     │
├─────────────────────────────────────────────────────────────────────────┤
│                      DATA LAYER                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │ Primary  │ │ Vector   │ │ Session  │ │ Event    │ │ Blob     │     │
│  │ DB       │ │ Store    │ │ Store    │ │ Store    │ │ Store    │     │
│  │(Postgres)│ │(Pinecone/│ │(Redis)   │ │(Kafka/   │ │(S3)      │     │
│  │          │ │ Qdrant)  │ │          │ │ Event    │ │          │     │
│  │          │ │          │ │          │ │ Log)     │ │          │     │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘     │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **API Gateway** | Auth, tenant resolution, rate limiting, WebSocket management, request routing | Kong/AWS API Gateway + custom tenant middleware |
| **Supervisor Orchestrator** | Decomposes tasks, routes to specialized agents, synthesizes results, enforces coordination rules | Custom orchestrator built on LangGraph (graph-based workflow) |
| **Specialized Agents (x8)** | Each owns a domain: discovery, strategy, pipeline, proposal, meeting attendance, voice handling, consolidation, coaching | LangGraph agent nodes with role-specific prompts, tools, and memory |
| **Event Bus** | Async agent-to-agent messaging, event sourcing, deal lifecycle events, integration events | Apache Kafka or NATS JetStream (800K msg/s, 15ms p95) |
| **LLM Gateway** | Model routing, token budgeting, fallback chains, prompt caching, per-tenant model selection | Custom gateway with provider abstraction (OpenAI, Anthropic, Google) |
| **Knowledge Base** | Product knowledge, methodology libraries, regional customization content, tenant-specific training data | Vector DB (Pinecone/Qdrant) + document store with namespace-per-tenant |
| **Context Manager** | Conversation persistence, agent memory, working context compilation, session management | Google ADK-style three-tier model: Working Context / Session / Memory |
| **Avatar Engine** | Real-time video avatar rendering, lip sync, facial animation for meeting attendance | Tavus CVI or HeyGen LiveAvatar API (<100ms rendering latency) |
| **Voice Pipeline** | STT/TTS streaming, turn-taking, interruption handling, domain vocabulary | AssemblyAI (STT) + ElevenLabs/Cartesia (TTS) + orchestrator |
| **Tenant Manager** | Tenant configuration, subscription tiers, data isolation policies, resource quotas | Custom service with tenant config DB |
| **Clone Registry** | Per-rep agent configurations, personality profiles, tone/style settings, per-clone knowledge overrides | Configuration store keyed by (tenant_id, rep_id, agent_type) |
| **Integration Hub** | Adapter management, webhook routing, OAuth token management, retry/circuit-breaker | Custom middleware with adapter pattern per external system |
| **CRM Adapter** | Bidirectional CRM sync, deal/contact/activity mapping, field-level customization per tenant | REST/GraphQL adapters for Salesforce, HubSpot, etc. |
| **GSuite Adapter** | Calendar events, email threads, document generation, Drive storage | Google Workspace APIs with per-tenant OAuth |
| **Meeting Platform Adapter** | Join meetings programmatically, capture audio/video streams, inject avatar | Recall.ai API or Zoom SDK + Puppeteer for Google Meet |
| **Primary DB** | Deals, contacts, activities, tenant config, user management | PostgreSQL with Row-Level Security (RLS) for multi-tenancy |
| **Vector Store** | Embeddings for product knowledge, conversation history, methodology content | Pinecone (namespaces per tenant) or Qdrant (collection per tenant) |
| **Session Store** | Active conversation state, agent working memory, ephemeral context | Redis with tenant-prefixed keys, TTL-based expiry |
| **Event Store** | Durable event log, audit trail, analytics source data, replay capability | Kafka topics partitioned by tenant_id |
| **Blob Store** | Meeting recordings, generated documents, avatar assets, training media | S3 with bucket-per-tenant or prefix-based isolation |

## Recommended Project Structure

```
agent-army/
├── packages/
│   ├── gateway/               # API Gateway service
│   │   ├── src/
│   │   │   ├── auth/          # OAuth/OIDC, tenant resolution
│   │   │   ├── routing/       # Request routing, WebSocket mgmt
│   │   │   └── middleware/    # Rate limiting, logging
│   │   └── package.json
│   │
│   ├── orchestrator/          # Supervisor Orchestrator
│   │   ├── src/
│   │   │   ├── supervisor/    # Task decomposition, agent routing
│   │   │   ├── agents/        # 8 specialized agent definitions
│   │   │   │   ├── discovery/
│   │   │   │   ├── strategy/
│   │   │   │   ├── pipeline/
│   │   │   │   ├── proposal/
│   │   │   │   ├── meeting/
│   │   │   │   ├── voice/
│   │   │   │   ├── consolidation/
│   │   │   │   └── coaching/
│   │   │   ├── coordination/  # Agent-to-agent protocols, handoffs
│   │   │   └── context/       # Context compilation pipeline
│   │   └── package.json
│   │
│   ├── llm-gateway/           # LLM provider abstraction
│   │   ├── src/
│   │   │   ├── providers/     # OpenAI, Anthropic, Google adapters
│   │   │   ├── routing/       # Model selection, fallback chains
│   │   │   ├── caching/       # Prompt caching, response caching
│   │   │   └── budgeting/     # Token tracking, cost controls
│   │   └── package.json
│   │
│   ├── knowledge-base/        # Knowledge & RAG service
│   │   ├── src/
│   │   │   ├── ingestion/     # Document processing, chunking
│   │   │   ├── retrieval/     # Vector search, reranking
│   │   │   ├── tenants/       # Namespace isolation, per-tenant config
│   │   │   └── regional/      # APAC/EMEA/Americas content variants
│   │   └── package.json
│   │
│   ├── integrations/          # External system adapters
│   │   ├── src/
│   │   │   ├── crm/           # Salesforce, HubSpot adapters
│   │   │   ├── gsuite/        # Calendar, Gmail, Docs, Drive
│   │   │   ├── meetings/      # Zoom, Teams, Google Meet bot
│   │   │   ├── voice/         # Twilio, telephony providers
│   │   │   └── avatar/        # Tavus, HeyGen provider adapters
│   │   └── package.json
│   │
│   ├── avatar-engine/         # Avatar rendering coordination
│   │   ├── src/
│   │   │   ├── rendering/     # Avatar provider management
│   │   │   ├── streaming/     # WebRTC/video stream management
│   │   │   └── sync/          # Lip-sync, gesture coordination
│   │   └── package.json
│   │
│   ├── voice-pipeline/        # Voice processing pipeline
│   │   ├── src/
│   │   │   ├── stt/           # Speech-to-text streaming
│   │   │   ├── tts/           # Text-to-speech streaming
│   │   │   ├── orchestration/ # Turn-taking, interruption handling
│   │   │   └── telephony/     # Phone call management
│   │   └── package.json
│   │
│   ├── data-consolidation/    # Analytics & pattern recognition
│   │   ├── src/
│   │   │   ├── pipelines/     # ETL from event store
│   │   │   ├── patterns/      # Cross-conversation analysis
│   │   │   ├── scoring/       # Deal health, rep performance
│   │   │   └── reporting/     # Dashboard data, exports
│   │   └── package.json
│   │
│   ├── tenant-manager/        # Multi-tenancy service
│   │   ├── src/
│   │   │   ├── provisioning/  # Tenant onboarding, teardown
│   │   │   ├── config/        # Per-tenant settings, feature flags
│   │   │   ├── isolation/     # Data boundary enforcement
│   │   │   └── billing/       # Usage tracking, quota enforcement
│   │   └── package.json
│   │
│   └── shared/                # Shared libraries
│       ├── src/
│       │   ├── types/         # Shared TypeScript types
│       │   ├── events/        # Event schemas, serialization
│       │   ├── auth/          # Auth utilities, tenant context
│       │   └── telemetry/     # Logging, tracing, metrics
│       └── package.json
│
├── infra/                     # Infrastructure as code
│   ├── terraform/             # Cloud infrastructure
│   ├── kubernetes/            # Container orchestration
│   └── docker/                # Development containers
│
├── knowledge/                 # Knowledge base content (versioned)
│   ├── products/              # Product documentation per tenant
│   ├── methodologies/         # MEDDIC, Challenger, SPIN, etc.
│   └── regional/              # APAC, EMEA, Americas variants
│
└── turbo.json / nx.json       # Monorepo orchestration
```

### Structure Rationale

- **packages/ monorepo:** Each service is independently deployable but shares types and event schemas. Monorepo enables atomic changes across service boundaries during early development.
- **agents/ inside orchestrator:** Agents are not separate services; they are nodes in the orchestration graph. Separating them as microservices would add unnecessary latency for intra-agent coordination. They share a process but have isolated state.
- **integrations/ as one package:** External adapters share common patterns (OAuth management, retry, circuit-breaker). Grouping reduces boilerplate while each adapter is internally modular.
- **knowledge/ at root:** Knowledge content is versioned alongside code but is distinct from application logic. Enables non-engineers to contribute product documentation.

## Architectural Patterns

### Pattern 1: Supervisor-with-Specialist-Groups (Hybrid Orchestration)

**What:** A top-level Supervisor orchestrator coordinates three specialist groups (Deal Coordination, Customer Interaction, Admin/Analytics). Within each group, agents can communicate directly (mesh) for tactical decisions. The Supervisor handles strategic coordination, task decomposition across groups, and result synthesis.

**When to use:** When agents need both structured oversight (for compliance, auditability, deal-level coordination) and low-latency tactical communication (for real-time meeting interactions).

**Trade-offs:**
- PRO: Auditability of all agent decisions via Supervisor logging
- PRO: Low-latency within groups for real-time scenarios (meeting, voice)
- PRO: Groups can scale independently
- CON: Supervisor is a single point of failure (mitigate with active-passive failover)
- CON: 200%+ token overhead for Supervisor reasoning (mitigate with caching, concise protocols)

**Example:**
```
Enterprise deal workflow:

1. Customer emails requesting pricing → GSuite Adapter emits "email.received" event
2. Supervisor receives event, decomposes:
   a. Route to Discovery Agent → extract requirements, identify stakeholders
   b. Route to Strategy Agent → map to product offerings, build positioning
   c. Route to Proposal Agent → generate pricing document
3. Within Deal Coordination group, agents share context directly:
   Discovery passes stakeholder map to Strategy (intra-group, low latency)
   Strategy passes positioning to Proposal (intra-group, low latency)
4. Supervisor synthesizes: creates CRM activity, schedules follow-up, notifies rep
```

**Confidence:** MEDIUM — This hybrid pattern is recommended by multiple sources (Kore.ai, Confluent, ClickIT) as the production-grade approach for 2026. Specific implementation details need validation.

### Pattern 2: Event-Driven Agent Communication (Blackboard Pattern)

**What:** Agents communicate through a shared event bus rather than direct calls. Each agent subscribes to relevant event topics and publishes results. A "blackboard" (shared state store) accumulates deal intelligence that any agent can read. This decouples agents and enables asynchronous collaboration.

**When to use:** For cross-cutting workflows where multiple agents need to react to the same event (e.g., meeting transcript triggers Consolidation Agent, Strategy Agent, and Coaching Agent simultaneously). Also critical for auditability — every agent action is an event in the log.

**Trade-offs:**
- PRO: Agents are independently deployable and scalable
- PRO: Natural event sourcing provides full audit trail
- PRO: Resilient — if one agent fails, events queue and replay when recovered
- PRO: Enables analytics pipeline (Consolidation Agent reads event stream)
- CON: Eventual consistency — agents may act on stale data
- CON: Debugging distributed event chains is harder than tracing synchronous calls
- CON: Requires careful event schema design upfront

**Four event-driven sub-patterns** (per Confluent's framework):

| Sub-Pattern | Description | Use In This Platform |
|-------------|-------------|---------------------|
| **Orchestrator-Worker** | Supervisor emits task events, workers consume and report back | Primary deal workflow coordination |
| **Hierarchical Agent** | Group leaders manage sub-agents, report to Supervisor | Agent group management |
| **Blackboard** | Shared knowledge store agents read/write asynchronously | Deal intelligence accumulation |
| **Market-Based** | Agents bid on tasks based on capability/availability | Future: load balancing across agent clones |

**Confidence:** MEDIUM — Event-driven patterns for multi-agent AI are well-documented by Confluent (2025) and are becoming standard. Specific message broker choice needs benchmarking.

### Pattern 3: Three-Tier Context Management

**What:** Separate agent state into three tiers, following Google ADK's architecture: (1) Working Context — ephemeral, per-invocation prompt compiled from state; (2) Session — durable log of all events in a conversation/deal; (3) Memory — long-lived, searchable knowledge that outlives sessions.

**When to use:** Always. This is the foundational pattern for managing LLM context in multi-agent systems. Without it, agents either lose context (stateless) or blow up context windows (dump everything into prompt).

**Trade-offs:**
- PRO: Decouples storage schema from prompt format
- PRO: Enables context caching (stable prefix + variable suffix)
- PRO: Agents can "reach for" additional context via tools rather than having everything loaded
- PRO: Memory tier enables cross-session learning
- CON: Complexity in context compilation pipeline
- CON: Requires careful tuning of what to include vs. exclude per agent invocation

**Implementation:**
```
┌─────────────────────────────────────────────────────┐
│                  CONTEXT COMPILER                     │
│                                                       │
│  1. System Instructions (stable, cached)              │
│  2. Agent Identity + Role (stable, cached)            │
│  3. Relevant Memory (retrieved via similarity search) │
│  4. Session History (filtered, compacted)             │
│  5. Current Task Context (variable, from event)       │
│  6. Available Tools (agent-specific)                  │
│                                                       │
│  Output: Compiled prompt for LLM invocation           │
└─────────────────────────────────────────────────────┘

Storage:
  Session Store (Redis)  → Active conversations, TTL-based
  Memory Store (Vector DB) → Long-term knowledge, searchable
  Event Store (Kafka)    → Durable log, replayable
```

**Confidence:** HIGH — This pattern is documented by Google's Agent Development Kit (ADK) and verified through their developer blog. It is the recommended approach for production multi-agent systems in 2026.

## Data Flow

### Primary Deal Workflow

```
[External Trigger: Email / Meeting / Call / CRM Update]
    │
    ▼
[Integration Adapter] → emits domain event (e.g., "email.received")
    │
    ▼
[Event Bus] → routes to subscribed agents
    │
    ├──▶ [Supervisor Orchestrator]
    │        │
    │        ├── Decomposes task
    │        ├── Routes to specialist agents
    │        ├── Monitors progress
    │        └── Synthesizes result
    │             │
    │             ▼
    │        [Specialist Agent(s)]
    │             │
    │             ├── Retrieves context (Context Manager)
    │             ├── Queries knowledge (Knowledge Base)
    │             ├── Calls LLM (LLM Gateway)
    │             ├── Executes tools (Integration Hub)
    │             └── Emits result event
    │
    ├──▶ [Consolidation Agent] (parallel subscriber)
    │        │
    │        └── Indexes conversation data for pattern analysis
    │
    └──▶ [Event Store] (all events persisted for audit + replay)
```

### Real-Time Meeting Flow (Low Latency Path)

```
[Meeting Platform (Zoom/Teams/Meet)]
    │
    ▼
[Meeting Bot] → joins meeting as participant via SDK/API
    │
    ├── Audio Stream ──▶ [STT Engine] ──▶ [Transcript Chunks]
    │                                          │
    │                                          ▼
    │                                    [Meeting Agent]
    │                                          │
    │                                    ┌─────┴──────┐
    │                                    │ Context     │
    │                                    │ Compiler    │
    │                                    │  + Deal KB  │
    │                                    │  + Product  │
    │                                    │    Knowledge│
    │                                    └─────┬──────┘
    │                                          │
    │                                          ▼
    │                                    [LLM Gateway]
    │                                    (fast model:
    │                                     Claude Haiku
    │                                     or Gemini Flash)
    │                                          │
    │                                          ▼
    │                                    [Response Text]
    │                                          │
    │                            ┌─────────────┴──────────────┐
    │                            ▼                            ▼
    │                      [TTS Engine]                 [Avatar Engine]
    │                            │                            │
    │                            ▼                            ▼
    │                      [Audio Stream]              [Video Stream]
    │                            │                            │
    └────────────────────────────┴────────────────────────────┘
                                 │
                                 ▼
                          [Meeting Platform]
                          (avatar speaks with
                           lip-synced video)

Target Latency Budget:
  STT:          100-300ms (streaming)
  LLM (fast):   200-500ms (TTFT, streaming)
  TTS:          200-400ms (streaming)
  Avatar Sync:  <100ms (real-time rendering)
  Network:       50-150ms
  ─────────────────────────────
  Total:        650-1,450ms (with streaming overlap: <1,000ms target)
```

### Agent Cloning Data Flow

```
[Sales Rep Onboarding]
    │
    ▼
[Clone Registry]
    │
    ├── Base Agent Template (from tenant config)
    ├── Rep Personality Profile (tone, style, verbosity)
    ├── Rep Knowledge Overrides (specific deal history, relationships)
    ├── Rep Communication Samples (email tone training)
    └── Regional Config (APAC/EMEA/Americas defaults)
         │
         ▼
    [Clone Instance] = Base Template
                     + Personality Layer
                     + Knowledge Overrides
                     + Regional Defaults
         │
         ▼
    [8 Agent Clones per Rep]
    (Each of the 8 specialized agents gets
     the rep's personality and knowledge overlay)
```

### Cross-Conversation Analytics Flow

```
[Event Store (all agent events)]
    │
    ▼
[Data Consolidation Engine]
    │
    ├── Pattern Extraction Pipeline
    │   ├── Objection frequency analysis
    │   ├── Winning talk tracks identification
    │   ├── Competitor mention tracking
    │   ├── Deal velocity patterns
    │   └── Rep performance signals
    │
    ├── Deal Health Scoring
    │   ├── Engagement metrics (email response rates, meeting attendance)
    │   ├── Stakeholder mapping completeness
    │   ├── Buying signal detection
    │   └── Risk indicator aggregation
    │
    └── Output
        ├── Dashboard API (real-time metrics)
        ├── Coaching Agent feed (per-rep improvement areas)
        ├── Strategy Agent feed (updated competitive intelligence)
        └── Knowledge Base updates (winning patterns → training data)
```

## Multi-Tenancy Architecture

### Isolation Strategy: Hybrid Model (Recommended)

Use a **hybrid isolation architecture** — share infrastructure (compute, event bus, LLM Gateway) while isolating data at the logical and encryption level. This balances cost efficiency with the strict data separation required for Skyvera, Jigtree, and Totogi.

```
┌───────────────────────────────────────────────────┐
│              SHARED INFRASTRUCTURE                  │
│                                                     │
│  Compute: Shared Kubernetes cluster                 │
│  Event Bus: Shared Kafka cluster, partitioned       │
│  LLM Gateway: Shared, per-tenant routing            │
│  Avatar Engine: Shared provider connections          │
│  Voice Pipeline: Shared STT/TTS services            │
│                                                     │
├───────────────────────────────────────────────────┤
│              LOGICALLY ISOLATED (per tenant)         │
│                                                     │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐  │
│  │  Skyvera    │ │  Jigtree    │ │  Totogi     │  │
│  │             │ │             │ │             │  │
│  │ DB Schema   │ │ DB Schema   │ │ DB Schema   │  │
│  │ Vector NS   │ │ Vector NS   │ │ Vector NS   │  │
│  │ Event Topics│ │ Event Topics│ │ Event Topics│  │
│  │ Redis Prefix│ │ Redis Prefix│ │ Redis Prefix│  │
│  │ S3 Prefix   │ │ S3 Prefix   │ │ S3 Prefix   │  │
│  │ Encrypt Key │ │ Encrypt Key │ │ Encrypt Key │  │
│  │ OAuth Creds │ │ OAuth Creds │ │ OAuth Creds │  │
│  │ Clone Regs  │ │ Clone Regs  │ │ Clone Regs  │  │
│  │ KB Content  │ │ KB Content  │ │ KB Content  │  │
│  └─────────────┘ └─────────────┘ └─────────────┘  │
│                                                     │
├───────────────────────────────────────────────────┤
│              SHARED KNOWLEDGE (opt-in)              │
│                                                     │
│  Methodology Libraries (MEDDIC, Challenger, SPIN)   │
│  Sales Best Practices                               │
│  Industry Frameworks                                │
│                                                     │
└───────────────────────────────────────────────────┘
```

### Isolation Mechanisms

| Layer | Isolation Method | Rationale |
|-------|-----------------|-----------|
| **Database** | PostgreSQL schema-per-tenant + Row-Level Security (RLS) | Schema isolation prevents cross-tenant queries; RLS adds defense-in-depth |
| **Vector Store** | Namespace-per-tenant (Pinecone) or Collection-per-tenant (Qdrant) | Native multi-tenancy support with complete data separation |
| **Event Bus** | Topic prefix per tenant (`skyvera.deal.*`, `jigtree.deal.*`) | Partitioning prevents cross-tenant event leakage |
| **Session Store** | Redis key prefix (`tenant:{id}:session:{sid}`) with ACL | Logical separation with TTL-based cleanup |
| **Blob Storage** | S3 prefix-per-tenant with IAM policies | Cost-effective; IAM prevents cross-tenant access |
| **Encryption** | Tenant-specific encryption keys (AWS KMS / Vault) | Data at rest encrypted with tenant-owned keys; compromising one tenant cannot expose another |
| **LLM Calls** | Tenant context injected into system prompt; per-tenant token budgets | Prevents knowledge leakage; enables per-tenant cost tracking |
| **Integrations** | Per-tenant OAuth credentials stored in encrypted vault | Each tenant's CRM, GSuite, etc. credentials are isolated |

### Tenant Context Propagation

Every request carries a `TenantContext` that propagates through all layers:

```
TenantContext {
  tenant_id: string           // "skyvera" | "jigtree" | "totogi"
  tenant_config: {
    products: ProductCatalog
    region_defaults: RegionalConfig
    llm_preferences: LLMConfig
    integration_credentials: EncryptedRef
    knowledge_namespaces: string[]
    methodology: string       // "MEDDIC" | "Challenger" | etc.
  }
  rep_id?: string             // For clone resolution
  clone_config?: CloneConfig  // Resolved personality + knowledge overlay
}
```

This context is set at the API Gateway and passed through every service call and event. No service can operate without valid tenant context.

**Confidence:** MEDIUM — Hybrid isolation with schema-per-tenant is well-documented (AWS, Azure, multiple production guides). Specific implementation choices (RLS vs. separate databases) should be validated against actual data volume and compliance requirements per tenant.

## Agent Coordination Patterns

### Pattern: Supervisor + Specialist Groups

The 8 agents are organized into three functional groups:

**Group 1: Deal Coordination (async-tolerant)**
- Discovery Agent — Research prospects, extract requirements, identify stakeholders
- Strategy Agent — Build positioning, competitive analysis, methodology application
- Pipeline Agent — Track deal stages, update CRM, manage timelines
- Proposal Agent — Generate proposals, pricing, SOWs

**Group 2: Customer Interaction (latency-sensitive)**
- Meeting Agent — Attend meetings, answer questions, take notes, represent via avatar
- Voice Agent — Handle phone calls, real-time conversation

**Group 3: Admin & Analytics (background)**
- Consolidation Agent — Pattern recognition across conversations, deal health scoring
- Coaching Agent — Analyze rep performance, suggest improvements, training content

### Coordination Rules

```
1. SUPERVISOR routes cross-group tasks:
   Meeting transcript → Supervisor → {Strategy (update positioning),
                                       Pipeline (update CRM),
                                       Coaching (analyze performance)}

2. INTRA-GROUP agents communicate directly (low latency):
   Discovery finds stakeholder → directly passes to Strategy
   Meeting Agent needs product info → directly queries Knowledge Base

3. EVENT BUS for fire-and-forget notifications:
   Any agent completes task → emits event → Consolidation Agent indexes it

4. BLACKBOARD for shared deal state:
   All agents read/write to shared deal record
   Conflict resolution: last-write-wins with version vector,
   Supervisor arbitrates conflicts on critical fields

5. BUDGET CONTROLS:
   Each agent invocation has max token budget
   Coordination loops have max iteration count (prevent runaway costs)
   Supervisor enforces total deal-level cost ceiling
```

### Agent Handoff Protocol

```
AgentHandoff {
  from_agent: AgentType
  to_agent: AgentType
  task: TaskDefinition
  context: {
    deal_id: string
    relevant_history: CompactedContext   // Not full history — summarized
    specific_data: any                   // Task-specific payload
    deadline?: timestamp                 // For time-sensitive tasks
  }
  metadata: {
    tenant_id: string
    clone_id: string
    priority: "critical" | "high" | "normal" | "low"
    correlation_id: string              // For tracing
  }
}
```

**Confidence:** MEDIUM — Supervisor pattern is well-established (Kore.ai, multiple frameworks). Grouping agents by latency profile is a practical application of the hybrid orchestration pattern. Specific inter-agent protocol needs to be designed and tested.

## Knowledge Base Structure

### Architecture: Agentic RAG with Namespace Isolation

```
┌─────────────────────────────────────────────────────────┐
│                   KNOWLEDGE BASE SERVICE                  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              INGESTION PIPELINE                      │ │
│  │  Document Upload → Chunking → Embedding → Indexing   │ │
│  │                                                      │ │
│  │  Chunking Strategy: Semantic chunking (not fixed-    │ │
│  │  size) for better retrieval quality                  │ │
│  │                                                      │ │
│  │  Embedding Model: Per-tenant configurable            │ │
│  │  (default: OpenAI text-embedding-3-large)            │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              RETRIEVAL ENGINE                        │ │
│  │                                                      │ │
│  │  1. Query → Embed → Vector Search (tenant namespace) │ │
│  │  2. Rerank results (cross-encoder or LLM reranker)   │ │
│  │  3. Merge with methodology content (shared)          │ │
│  │  4. Return ranked context for agent consumption      │ │
│  │                                                      │ │
│  │  Mode: Agentic RAG — agents decide when to retrieve  │ │
│  │  and what queries to run (not pre-loaded context)     │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              CONTENT NAMESPACES                      │ │
│  │                                                      │ │
│  │  Per-Tenant:                                         │ │
│  │    {tenant}/products/     → Product catalog, specs   │ │
│  │    {tenant}/competitors/  → Competitive intel        │ │
│  │    {tenant}/deals/        → Historical deal data     │ │
│  │    {tenant}/training/     → Rep onboarding content   │ │
│  │    {tenant}/custom/       → Tenant-specific content  │ │
│  │                                                      │ │
│  │  Per-Region (within tenant):                         │ │
│  │    {tenant}/regional/apac/   → APAC pricing, regs   │ │
│  │    {tenant}/regional/emea/   → EMEA compliance, lang │ │
│  │    {tenant}/regional/amer/   → Americas specifics    │ │
│  │                                                      │ │
│  │  Shared (read-only, all tenants):                    │ │
│  │    shared/methodologies/     → MEDDIC, Challenger    │ │
│  │    shared/frameworks/        → Sales frameworks      │ │
│  │    shared/best-practices/    → Industry patterns     │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Knowledge Update Flow

```
Product Update (e.g., acquisition adds new product line):
  1. Tenant admin uploads new product docs
  2. Ingestion pipeline processes → chunks → embeds → indexes
  3. New content lands in {tenant}/products/ namespace
  4. All 8 agents for that tenant immediately have access
  5. No agent reconfiguration needed — agents query KB dynamically

Regional Customization:
  1. Regional content stored in {tenant}/regional/{region}/
  2. Agent context includes rep's region → queries include regional namespace
  3. Strategy Agent queries both global product KB and regional content
  4. Pricing, compliance, and cultural context are region-aware
```

**Confidence:** MEDIUM — Agentic RAG is the recommended 2026 pattern (replacing standard RAG). Namespace-per-tenant is supported natively by Pinecone and Qdrant. Semantic chunking and reranking are established best practices. Specific chunking strategy and embedding model choice need benchmarking with actual content.

## Integration Architecture

### Adapter Pattern with Event Bridge

```
┌──────────────────────────────────────────────────┐
│               INTEGRATION HUB                      │
│                                                    │
│  ┌────────────────────────────────────────────┐   │
│  │           ADAPTER REGISTRY                  │   │
│  │                                             │   │
│  │  Each adapter implements:                   │   │
│  │    - connect(tenant_creds)                  │   │
│  │    - sync_inbound() → domain events         │   │
│  │    - sync_outbound(domain_event) → API call │   │
│  │    - health_check()                         │   │
│  │    - retry_with_backoff()                   │   │
│  │    - circuit_breaker()                      │   │
│  └────────────────────────────────────────────┘   │
│                                                    │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐     │
│  │Salesfor│ │HubSpot │ │GSuite  │ │Zoom    │     │
│  │ce      │ │        │ │        │ │        │     │
│  │- Deals │ │- Deals │ │- Cal   │ │- Meet  │     │
│  │- Contac│ │- Contac│ │- Gmail │ │- Record│     │
│  │- Activi│ │- Activi│ │- Docs  │ │- Transc│     │
│  │- Custom│ │- Custom│ │- Drive │ │        │     │
│  └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘     │
│      │          │          │          │           │
│  ┌───┴──────────┴──────────┴──────────┴────────┐  │
│  │         WEBHOOK / POLLING MANAGER            │  │
│  │                                              │  │
│  │  Inbound: Webhooks → Domain Events           │  │
│  │  Outbound: Domain Events → API Calls         │  │
│  │  Polling: For systems without webhooks        │  │
│  │  OAuth: Token refresh, per-tenant credential  │  │
│  └──────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

### Meeting Bot Architecture

```
Meeting Platform Adapter:

  Option A: Recall.ai API (recommended for MVP)
    - Single API covers Zoom, Teams, Google Meet
    - Handles bot deployment, scaling, maintenance
    - Returns raw audio/video streams
    - Cost: per-meeting-minute pricing

  Option B: Custom Bot (recommended for scale)
    - Zoom: Native Linux SDK, cloud-deployed instances
    - Google Meet: Puppeteer/Playwright browser automation
    - Teams: Microsoft Graph API + Bot Framework
    - Requires: Kubernetes auto-scaling, per-meeting container
    - Advantage: Full control over avatar injection, latency
```

**Confidence:** MEDIUM — Adapter pattern is standard. Recall.ai for meeting bots is a proven solution (used by Otter, Gong, etc.). Custom bot path is more complex but documented (Zoom SDK, Puppeteer approach verified).

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| **1-3 tenants, <50 reps** | Monolithic deployment on single K8s cluster. Shared Postgres with schema isolation. Single Kafka instance. All agents in one process. |
| **3-10 tenants, 50-500 reps** | Split into microservices along package boundaries. Dedicated Kafka topics per tenant. Connection pooling for external APIs. LLM response caching becomes critical. Introduce Redis cluster for session management. |
| **10+ tenants, 500+ reps** | Database-per-tenant for largest tenants. Multi-region deployment (APAC, EMEA, Americas clusters). CDN for avatar assets. Dedicated LLM quota per tenant. Event store archival to cold storage. Horizontal scaling of agent orchestrator. |

### Scaling Priorities

1. **First bottleneck: LLM token costs and rate limits.** With 8 agents per rep, each deal interaction may trigger multiple LLM calls. At 50 reps running 10 deals each, this is thousands of LLM invocations daily. Mitigation: aggressive prompt caching, response caching, model tiering (fast model for simple tasks, powerful model for complex reasoning), per-agent token budgets.

2. **Second bottleneck: Real-time meeting capacity.** Each active meeting requires: 1 meeting bot instance, 1 STT stream, 1 LLM context, 1 TTS stream, 1 avatar render. At 20 concurrent meetings, this is significant compute. Mitigation: auto-scaling meeting bot pool, use provider-hosted avatar rendering (Tavus/HeyGen), edge deployment for latency.

3. **Third bottleneck: Knowledge base query volume.** Every agent invocation may trigger 1-3 RAG queries. At scale, vector search becomes a bottleneck. Mitigation: query caching, embedding caching, read replicas of vector store, pre-computation of common query results.

4. **Fourth bottleneck: Event bus throughput.** With 8 agents emitting events per interaction across hundreds of deals, event volume grows non-linearly. Mitigation: event batching, topic partitioning by tenant, consumer group scaling, event compaction for historical data.

### Cost Architecture

**Critical concern for 2026:** Token cost optimization is a first-class architectural concern.

```
Cost Control Mechanisms:
  1. Per-agent token budget per invocation
  2. Per-deal total token ceiling
  3. Per-tenant monthly token quota
  4. Model tiering: route simple tasks to cheaper models
  5. Prompt caching: reuse system prompts across invocations
  6. Response caching: cache common queries (product info, pricing)
  7. Context compaction: summarize older events, don't include raw history
  8. Coordination loop limits: max 3 agent-to-agent hops per task
```

## Anti-Patterns

### Anti-Pattern 1: Every Agent as a Separate Microservice

**What people do:** Deploy each of the 8 agents as an independent microservice with its own database, API, and deployment pipeline.

**Why it's wrong:** Inter-agent communication becomes network calls with serialization overhead. Coordinating 8 services for a single deal interaction adds 100-500ms per hop. Deployment complexity explodes. Testing requires running all 8 services. With 3 tenants x 50 reps, you have potentially hundreds of service instances.

**Do this instead:** Agents are logical components within an orchestration service, not separate services. They share a process and communicate via in-memory function calls within their group. The orchestrator service itself can be horizontally scaled. Only split into separate services when a specific agent has radically different scaling needs (e.g., meeting bot needs GPU; consolidation needs batch compute).

### Anti-Pattern 2: Dumping Full Context into Every Agent Prompt

**What people do:** Pass the entire deal history, all product knowledge, and full conversation transcript to every agent on every invocation.

**Why it's wrong:** Context windows are finite and expensive. A 200K token context costs 10-50x more than a 10K token context. At 8 agents per interaction, this multiplies. Beyond cost, retrieval quality degrades with context length — LLMs perform worse with massive contexts (the "lost in the middle" problem).

**Do this instead:** Use the three-tier context model. Agents get minimal context by default and explicitly request additional information via tools (Agentic RAG pattern). Context compiler builds a focused prompt per invocation. Cache stable prefixes (system instructions, agent identity).

### Anti-Pattern 3: Synchronous Agent Chains for Everything

**What people do:** Agent A calls Agent B which calls Agent C which calls Agent D, all synchronously waiting for each response.

**Why it's wrong:** Latency compounds — if each agent takes 2-3 seconds (LLM call + tool use), a 4-agent chain takes 8-12 seconds. Users experience this as unresponsive. One slow agent blocks everything downstream. No parallelism exploited.

**Do this instead:** Use the Supervisor to identify parallelizable tasks and execute them concurrently. Use async event-driven patterns for non-blocking coordination. Only use synchronous chains when there is a genuine data dependency (Agent B literally cannot start without Agent A's output).

### Anti-Pattern 4: Single-Tenant Design Retrofitted for Multi-Tenancy

**What people do:** Build for one tenant first, plan to "add multi-tenancy later."

**Why it's wrong:** Multi-tenancy is an architectural property, not a feature. Retrofitting requires touching every database query, every event emission, every LLM call, every integration credential lookup. It is the single most expensive retrofit in SaaS architecture.

**Do this instead:** Build tenant context propagation from Day 1. Every function, every query, every event includes `tenant_id`. Use PostgreSQL RLS from the first migration. Use namespaced vector stores from the first embedding. This adds minimal upfront cost but prevents a rewrite.

### Anti-Pattern 5: Uncontrolled Agent Coordination Loops

**What people do:** Allow agents to freely call other agents without limits, creating cycles (A calls B which calls C which calls A again).

**Why it's wrong:** This is the most significant hidden expense in multi-agent systems. Without explicit loop limits, spending budgets, and termination conditions, token costs escalate rapidly. A single deal interaction can consume hundreds of dollars in API calls.

**Do this instead:** Every coordination path has a max depth (recommend: 3 hops). Every agent invocation has a token budget. The Supervisor enforces a total cost ceiling per task. Implement circuit breakers on agent-to-agent calls.

## Suggested Build Order (Dependencies)

Build order is dictated by component dependencies. Each layer depends on the one below it.

```
Phase 1: Foundation (Weeks 1-4)
─────────────────────────────────
  ├── Tenant Manager (everything depends on tenant context)
  ├── Primary Database + schema-per-tenant
  ├── Event Bus setup (Kafka/NATS)
  ├── API Gateway with auth + tenant resolution
  ├── Shared types/events library
  └── LLM Gateway (provider abstraction, basic routing)

Phase 2: Core Agent Infrastructure (Weeks 5-8)
───────────────────────────────────────────────
  ├── Context Manager (three-tier model)
  ├── Knowledge Base service (ingestion + retrieval)
  ├── Vector Store with tenant namespaces
  ├── Supervisor Orchestrator (basic task routing)
  └── First 2 agents: Discovery + Strategy
      (simplest to validate orchestration)

Phase 3: Deal Workflow Agents (Weeks 9-12)
──────────────────────────────────────────
  ├── Pipeline Agent (CRM integration dependency)
  ├── Proposal Agent (KB + template dependency)
  ├── CRM Adapter (Salesforce/HubSpot)
  ├── GSuite Adapter (Calendar, Gmail)
  ├── Clone Registry (per-rep configuration)
  └── End-to-end deal workflow validation

Phase 4: Real-Time Interaction (Weeks 13-18)
────────────────────────────────────────────
  ├── Voice Pipeline (STT + TTS + orchestration)
  ├── Meeting Bot integration (Recall.ai or custom)
  ├── Meeting Agent (real-time conversation)
  ├── Avatar Engine integration (Tavus/HeyGen)
  └── Low-latency path optimization

Phase 5: Analytics & Coaching (Weeks 19-22)
──────────────────────────────────────────
  ├── Data Consolidation Engine
  ├── Consolidation Agent (pattern recognition)
  ├── Coaching Agent (performance analysis)
  ├── Dashboard API
  └── Cross-conversation analytics

Phase 6: Production Hardening (Weeks 23-26)
──────────────────────────────────────────
  ├── Multi-region deployment
  ├── Regional knowledge content (APAC, EMEA, Americas)
  ├── Cost optimization (caching, model tiering)
  ├── Security audit (tenant isolation verification)
  ├── Load testing (concurrent meetings, agent storms)
  └── Monitoring, alerting, observability
```

**Build order rationale:**
- **Phase 1 first** because every component needs tenant context and event infrastructure
- **Phase 2 before agents** because agents need context management and knowledge retrieval to function
- **Phase 3 before real-time** because deal workflow is the core value; real-time interaction is an enhancement
- **Phase 4 is the hardest** — real-time latency constraints require the most engineering. Deferring it lets the team validate the agent model on async workflows first
- **Phase 5 after data exists** — analytics require conversation data to analyze, which only exists after Phase 3-4 agents are producing interactions
- **Phase 6 last** because premature optimization is wasteful, and security/load testing needs a complete system

## Sources

### HIGH Confidence (Context7 / Official Documentation)
- Google Developers Blog: [Architecting Efficient Context-Aware Multi-Agent Framework for Production](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/) — Three-tier context model, context compilation pipeline
- Microsoft Azure Architecture Center: [Multi-tenant AI Architecture](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/approaches/ai-machine-learning) — Isolation models, per-tenant customization
- Azure AI in Production Guide: [Multi-Tenant Architecture Chapter](https://azure.github.io/AI-in-Production-Guide/chapters/chapter_13_building_for_everyone_multitenant_architecture) — Data separation, resource allocation

### MEDIUM Confidence (WebSearch verified with official sources)
- Kore.ai: [Choosing the Right Orchestration Pattern for Multi-Agent Systems](https://www.kore.ai/blog/choosing-the-right-orchestration-pattern-for-multi-agent-systems) — Supervisor, Adaptive Network, Custom patterns
- Confluent: [Four Design Patterns for Event-Driven Multi-Agent Systems](https://www.confluent.io/blog/event-driven-multi-agent-systems/) — Orchestrator-Worker, Hierarchical, Blackboard, Market-Based
- AssemblyAI: [The Voice AI Stack for Building Agents in 2026](https://www.assemblyai.com/blog/the-voice-ai-stack-for-building-agents) — STT/TTS/LLM/Orchestration stack, latency budgets
- Ingenimax: [Building a Multi-Tenant Production-Grade AI Agent](https://ingenimax.ai/blog/building-multi-tenant-ai-agent) — Isolation strategies, LLM routing, tenant management
- IBM: [Agent2Agent (A2A) Protocol](https://www.ibm.com/think/topics/agent2agent-protocol) — Agent communication standards
- Auth0: [MCP vs A2A Protocols](https://auth0.com/blog/mcp-vs-a2a/) — Protocol complementarity
- Recall.ai: [Creating Meeting Bots](https://www.recall.ai/blog/how-can-i-create-a-zoom-bot-that-joins-meetings-and-interacts-as-a-participant) — Meeting bot architecture
- ClickIT: [Multi-Agent System Architecture Guide 2026](https://www.clickittech.com/ai/multi-agent-system-architecture/) — Framework selection, cost management
- Lindy.ai: [AI Agent Architecture Guide 2026](https://www.lindy.ai/blog/ai-agent-architecture) — Five essential components, memory patterns
- AWS: [Multi-Tenant RAG with Bedrock](https://aws.amazon.com/blogs/machine-learning/multi-tenant-rag-with-amazon-bedrock-knowledge-bases/) — Namespace-based RAG isolation

### LOW Confidence (WebSearch only, needs validation)
- A2E.ai avatar API comparison — Claims of superior lip-sync need independent verification
- Specific latency numbers for avatar rendering (<100ms) — Sourced from vendor marketing, validate in POC
- "40% of enterprise applications will embed AI agents by 2026" — Gartner forecast, cited widely but forward-looking

---
*Architecture research for: Multi-Agent AI Sales Platform (Agent Army)*
*Researched: 2026-02-10*
