# Project Research Summary

**Project:** Agent Army Platform — AI Sales Agent Orchestration
**Domain:** Multi-Agent AI Sales Platform (Enterprise, Multi-Tenant)
**Researched:** 2026-02-10
**Confidence:** MEDIUM-HIGH

## Executive Summary

This is an enterprise multi-agent AI sales platform with 8 specialized agent roles (Sales, Solution Architect, Project Manager, Business Analyst, TAM, Customer Success, Collections, Operations) designed to perform at "top 1%" human levels across 3 business units (Skyvera, Jigtree, Totogi) operating in multiple regions (APAC, EMEA, Americas). The system must handle real-time interactions including voice calls and video meeting attendance with AI avatars, while maintaining strict multi-tenant data isolation and regional customization.

The recommended technical approach is Python-first with LangGraph as the orchestration backbone, implementing a Supervisor-with-Specialist-Groups topology. The architecture must be built multi-tenant from day one (retrofitting is prohibitively expensive). The highest risks are: (1) cascading hallucination amplification across agents, (2) multi-tenant data contamination through LLM context leakage, and (3) the "bag of agents" anti-pattern where uncoordinated agents produce compounding errors. These risks are mitigated through structured coordination topology, mandatory validation checkpoints at agent handoffs, and tenant isolation enforced at every layer (database, vector store, LLM context, prompt cache).

The build strategy should prioritize foundation and coordination architecture first, then implement one exceptional agent (Sales) to validate patterns, then expand to the remaining 7 agents. Real-time voice and avatar capabilities should come after core agent workflows are proven, as they introduce significant complexity and latency optimization challenges. This is a 26+ week build with clear phase dependencies: Foundation → Core Agent Infrastructure → Deal Workflow Agents → Real-Time Interaction → Analytics → Production Hardening.

## Key Findings

### Recommended Stack

**Decision: Python backend with FastAPI, not TypeScript.** LangGraph and CrewAI are Python-first with mature APIs; JavaScript ports lag 6-12 months. The AI/ML ecosystem (Deepgram, ElevenLabs, HeyGen, Vapi SDKs, Google Workspace APIs) has first-class Python support. FastAPI delivers async performance competitive with Node.js for I/O-bound agent workloads.

**Core technologies:**

- **LangGraph 1.0.x** (agent orchestration) — Graph-first architecture provides explicit control over agent routing, state management, conditional branching. Production-grade with durable execution and debugging. Enforces business rules structurally, not just via prompts.

- **Anthropic Claude Sonnet 4** (primary reasoning LLM) — Best instruction-following for complex multi-step agent tasks. Production-grade tool use. Cost-effective vs Opus for high-volume operations.

- **OpenAI gpt-realtime** (voice conversations) — Purpose-built for voice agents. Single model handles STT+reasoning+TTS. Lower latency than chained pipeline. GA with no session limits, SIP support for phone integration.

- **Qdrant 1.16.x** (vector database) — First-class multi-tenancy with tiered tenant system. Sub-100ms query times. Payload-based partitioning for tenant isolation. Open-source with managed cloud option.

- **Redis 8.2** (state cache, event streaming, semantic cache) — Sub-millisecond state access. Redis Streams for event-driven agent messaging. Semantic caching cuts LLM costs up to 70%.

- **HeyGen LiveAvatar** (real-time AI avatar) — WebRTC-based streaming with LiveKit integration. Sub-second latency. Most mature avatar-in-meeting product.

- **Recall.ai** (Google Meet bot) — Works with all Google Workspace tiers. Joins via meeting link. Custom avatar display + voice output. $0.50/hour usage-based pricing. No official Meet API exists; Recall abstracts the complexity.

- **Vapi** (voice call orchestration) — Sub-500ms voice-to-voice latency. Pluggable providers. Open architecture, can self-host. 40+ app integrations.

- **Google Cloud Run** (production hosting) — Serverless containers with auto-scaling. Ideal for variable agent workloads. Native Google Workspace integration (same cloud).

**Critical version requirements:**
- LangGraph 1.0 requires langchain-core >=0.3 (NOT 0.2.x)
- FastAPI 0.115.x requires Pydantic 2.x (NOT v1)
- Google Workspace Events API v1 (v1beta decommissioned April 2025)

**Why NOT alternatives:**
- CrewAI for core orchestration — lacks structural enforcement LangGraph provides; debugging is harder; good for rapid prototyping but not production business rules
- Kafka initially — overkill for 3 tenants; Redis Streams provides event streaming at this scale
- Kubernetes initially — operational overhead unjustified; Cloud Run provides auto-scaling without K8s complexity

### Expected Features

**Platform-wide foundation (all 8 agents require):**

Must have:
- **P-1: Multi-tenant isolation** (Skyvera/Jigtree/Totogi data must never leak) — foundational, HIGH complexity
- **P-2: Multi-region behavior customization** (APAC/EMEA/Americas sales cultures differ) — MEDIUM complexity
- **P-3: GSuite integration** (Gmail, Calendar, Meet, Chat) — core communication channel, HIGH complexity
- **P-4: Knowledge base architecture** (product/region/tenant-specific knowledge) — HIGH complexity
- **P-5: Agent-to-agent communication** (structured handoff messages, escalation chains) — HIGH complexity
- **P-6: CRM integration** (all agents read/write deal/account data) — MEDIUM complexity
- **P-7: Conversation memory** (per-account, per-deal, cross-channel unified context) — HIGH complexity

Differentiators:
- **P-12: Cross-agent pattern recognition** — spots trends humans miss ("3 accounts in APAC asking about feature X"); this is the "hive mind" advantage
- **P-15: Unified customer 360** — every agent sees full picture: sales + technical health + CS sentiment + AR status

Anti-features:
- Full autonomy without human approval on high-stakes actions (contract terms, pricing, C-suite comms need approval gates)
- Real-time deepfake video for avatars (legal/ethical minefield, trust-destroying)
- Financial transaction processing (liability/compliance scope explosion)

**Sales Agent (MVP build first):**

Must have:
- **S-2: Meeting attendance with avatar** — core differentiator, agent "in the room"
- **S-1: Meeting prep briefings** — account context, attendee profiles, talk tracks, likely objections
- **S-3: Meeting minutes and distribution** — structured output within minutes
- **S-4: Email composition** — context-aware, persona-matched drafting
- **S-5: BANT qualification** — basic qualification framework
- **S-6: CRM data entry** — auto-log all interactions, eliminate drudge work

Differentiators:
- **S-11: MEDDIC execution** — dominant enterprise qualification framework (73% of SaaS companies >$100K ARR use it). Top 1% means MEDDIC mastery: Metrics, Economic Buyer, Decision Criteria, Decision Process, Identify Pain, Champion, Competition.
- **S-15: Political mapping** — understanding who has power/influence/champions/blocks in enterprise accounts
- **S-19: Self-directed goal pursuit** — agent sets own priorities based on $ identified, $ sold, cycle time, win rate; doesn't wait for instructions (this is the "top 1%" differentiator)
- **S-20: Multi-methodology selection** — context-dependent methodology switching between BANT/MEDDIC/Sandler/Chris Voss/TAS

Anti-features:
- Aggressive cold outreach automation (spam destroys brand)
- Hiding AI identity in meetings (trust-destroying when discovered)
- Auto-discounting without approval (destroys margins)

**Other 7 agents (defer until Sales Agent validated):**

Solution Architect: technical requirement mapping, architecture diagrams, POC scoping, pre-emptive objection prep
Project Manager: project plans, predictive delay detection, auto-adjusting plans
Business Analyst: requirements extraction from conversations, gap analysis, contradiction detection
TAM: technical health monitoring, predictive escalation prevention, technical advocacy automation
Customer Success: health scoring, 60+ day churn prediction, expansion opportunity identification
Collections: AR aging tracking, payment behavior prediction, adaptive collection messaging
Ops Agent: CRM data quality, forecast generation, process breakdown detection

### Architecture Approach

**Pattern: Supervisor-with-Specialist-Groups (Hybrid Orchestration).** A top-level Supervisor orchestrator coordinates three specialist groups: (1) Deal Coordination (Discovery, Strategy, Pipeline, Proposal agents — async-tolerant), (2) Customer Interaction (Meeting, Voice agents — latency-sensitive), (3) Admin/Analytics (Consolidation, Coaching agents — background). Within groups, agents communicate directly for tactical decisions. The Supervisor handles strategic coordination and result synthesis.

**Pattern: Event-Driven Agent Communication (Blackboard).** Agents communicate through a shared event bus (Redis Streams initially, Kafka at scale). Each agent subscribes to relevant event topics and publishes results. A "blackboard" (shared state store) accumulates deal intelligence. This decouples agents, enables asynchronous collaboration, and provides natural event sourcing for full audit trail.

**Pattern: Three-Tier Context Management.** Separate agent state into: (1) Working Context — ephemeral, per-invocation prompt compiled from state; (2) Session — durable log of all events in conversation/deal; (3) Memory — long-lived, searchable knowledge outliving sessions. This prevents context window overflow, enables caching, and allows agents to "reach for" additional context via tools rather than loading everything.

**Major components:**

1. **Supervisor Orchestrator** (custom on LangGraph) — Decomposes tasks, routes to specialists, monitors progress, synthesizes results, enforces coordination rules
2. **8 Specialized Agents** (LangGraph nodes) — Each owns domain with role-specific prompts, tools, memory; share process but isolated state
3. **Event Bus** (Redis Streams → Kafka at scale) — Async agent messaging, event sourcing, deal lifecycle events
4. **LLM Gateway** (custom) — Model routing, token budgeting, fallback chains, prompt caching, per-tenant model selection
5. **Knowledge Base** (Qdrant + pgvector) — Vector DB with hierarchical scoping: global > tenant > region > product > account
6. **Context Manager** (custom) — Three-tier model implementation, conversation persistence, working context compilation
7. **Avatar Engine** (HeyGen LiveAvatar API) — Real-time video avatar rendering, lip sync coordination
8. **Voice Pipeline** (Vapi + Deepgram + ElevenLabs) — STT/TTS streaming, turn-taking, interruption handling
9. **Integration Hub** (adapter pattern) — CRM, GSuite, Meeting Platform, Voice, Avatar provider adapters with retry/circuit-breaker
10. **Primary DB** (PostgreSQL with Row-Level Security) — Deals, contacts, activities; schema-per-tenant for isolation
11. **Tenant Manager** (custom) — Tenant config, subscription tiers, data isolation policies, resource quotas

**Data flow:** External trigger (email/meeting/call/CRM) → Integration Adapter → Event Bus → Supervisor → Specialist Agent(s) → Context Manager + Knowledge Base + LLM Gateway + Integration Hub → Result emission → Event Store + Consolidation Agent + Real-time UI updates

**Latency budget for real-time meeting interaction:** Target <1,000ms end-to-end (user-stops-speaking to agent-starts-speaking). Budget: STT 100-300ms + LLM (fast model) 200-500ms + TTS 200-400ms + Avatar Sync <100ms + Network 50-150ms = 650-1,450ms with streaming overlap.

### Critical Pitfalls

1. **The "Bag of Agents" Trap — Flat Topology Without Coordination Hierarchy**
   - What: 8 agents operate in flat structure with no orchestrator; descend into circular logic, echo hallucinations, 17x error amplification
   - How to avoid: Design coordination topology FIRST before building any agent. Implement clear hierarchy (Orchestrator → specialist agents) with structured communication protocols. Define who talks to whom, who arbitrates conflicts, who validates outputs.
   - Phase: Phase 1 (Foundation) — orchestration topology must be the FIRST thing built
   - Impact if ignored: System becomes unmaintainable; each new agent makes it worse; 40% of multi-agent pilots fail within 6 months from this

2. **Cascading Hallucination Amplification**
   - What: Single agent hallucinates detail (budget figure, stakeholder role); downstream agents treat as trusted input, amplify error; entire deal context becomes poisoned
   - How to avoid: Mandatory output validation at every agent handoff. "Fact registry" of verified facts from sources (CRM, prospect's words, documents). Structured data formats (JSON schemas with source attribution) for inter-agent communication, not free-form natural language.
   - Phase: Phase 1-2 (Foundation + Agent Implementation)
   - Impact if ignored: Deals pursued on fabricated data; agents make promises company can't keep; legal liability for misrepresentation

3. **Multi-Tenant Data Contamination — LLM Context Leaking Between Tenants**
   - What: Tenant A's proprietary sales data, customer info, pricing strategies leak into Tenant B's agent responses through shared LLM context, contaminated vectors, cached prompts
   - How to avoid: Tenant isolation at ALL layers: database, vector store, LLM context, prompt cache, agent memory, model weights. Tenant-scoped API keys. Vector DB with mandatory tenant_id filters enforced at query level. LLM context fully cleared (not truncated) between tenant switches. Red team for cross-tenant leakage.
   - Phase: Phase 1 (Foundation) — design before any data stored; retrofitting is one of the most expensive refactors
   - Impact if ignored: Catastrophic — enterprise clients terminate immediately, regulatory violations (GDPR, SOC 2), lawsuits, complete loss of market trust, existential risk

4. **Voice/Avatar Latency Exceeding Conversational Threshold**
   - What: Full pipeline (speech recognition + LLM + TTS + network) exceeds 1.5 seconds; at 3+ seconds, 40% abandon; agent appears robotic/broken
   - How to avoid: Hard latency budget of 800ms for voice. Response streaming (start speaking before full response generated — 7x perceived latency reduction). Use fastest adequate model (Gemini Flash 200-350ms TTFT vs GPT-4o 350-500ms vs Claude Sonnet 400-600ms). KV cache optimization (800ms → 150ms). Regional edge deployment (cut network latency by 72%).
   - Phase: Phase 2-3 (Voice/Avatar Implementation) — hard requirement during development, not "optimize later"
   - Impact if ignored: Product feels broken; users compare to Siri/Alexa and find it unacceptably slow; "top 1% performer" illusion shatters

5. **Escalation Failures — Agent Doesn't Know When to Hand Off to Humans**
   - What: Under-escalation (agent makes commitments it shouldn't — pricing, terms) or over-escalation (alert fatigue, humans ignore)
   - How to avoid: "Bounded autonomy" — explicit documented boundaries. Confidence-threshold escalation (composite score, not just LLM temperature). Tiered framework: autonomous (standard questions) → logging (pricing in ranges) → human-in-loop (custom pricing, legal) → immediate takeover (lawsuits, regulatory, dissatisfaction). Feedback loop: human overrides generate training signals.
   - Phase: Phase 2-3 (Agent Implementation) — framework defined during agent design, boundaries from sales leadership
   - Impact if ignored: Unauthorized commitments create liability; alert fatigue leads to missed critical situations; sales team loses trust, reverts to manual

6. **The Robotic Sales Agent — Executing Methodology as Interrogation**
   - What: Agent executes MEDDIC/SPIN as rigid checklist ("What's your budget?" "Who's the decision maker?") like survey; fails to read social cues; transparently artificial
   - How to avoid: Train on TRANSCRIPTS of top performers, not methodology docs. "Conversation state" model (track what data gathered organically), not "checklist state." Social signal detection (sentiment, engagement, topic-shift). Never ask >1 qualification question per exchange. Embed discovery in value ("depends on your deal size... what are you working with?").
   - Phase: Phase 2-3 (Agent Implementation + Methodology Integration) — requires ongoing tuning
   - Impact if ignored: Entire value prop collapses; agent sounds robotic, performs bottom 10% not top 1%; prospects demand human reps

7. **"Dumb RAG" — Flooding LLM Context with Irrelevant Data**
   - What: Dump all data into vector DB, RAG retrieves "relevant" context; LLM drowns in irrelevant info; critical deal context pushed out by noise
   - How to avoid: Hierarchical context architecture (Layer 1 always present: deal summary, prospect profile, current conversation; Layer 2 retrieved on demand; Layer 3 available but not default). Cap context injection at 8-16K tokens even if model supports 128K+. Context relevance scoring layer BEFORE injecting. Structured "deal context" object actively managed, not reconstructed from RAG every call.
   - Phase: Phase 1-2 (Foundation + Knowledge Base) — design with curation from start
   - Impact if ignored: Agent responses degrade over time; costs escalate with data volume; critical context lost in noise

## Implications for Roadmap

Based on research dependencies and risk mitigation priorities, suggested 6-phase structure over 26 weeks:

### Phase 1: Foundation (Weeks 1-4)
**Rationale:** Every component depends on tenant context, event infrastructure, and orchestration topology. This MUST come first. Multi-tenancy retrofitted later is prohibitively expensive. The "bag of agents" anti-pattern is prevented by designing coordination topology before any specialist agent.

**Delivers:**
- Tenant Manager with multi-tenant isolation architecture (P-1)
- Primary Database with schema-per-tenant + Row-Level Security
- Event Bus setup (Redis Streams)
- API Gateway with auth + tenant resolution
- Shared types/events library
- LLM Gateway with provider abstraction and basic routing
- Orchestration topology designed and documented

**Addresses features:**
- P-1 (Multi-tenant isolation) — foundational for all
- Partial P-5 (Agent-to-agent communication backbone)

**Avoids pitfalls:**
- Pitfall 1 (Bag of Agents) — orchestration topology designed first
- Pitfall 3 (Multi-tenant data contamination) — tenant isolation built in from day one
- Pitfall 9 (Premature platformization) — keep foundation thin, just enough for Agent 1

**Research flags:** Standard patterns, well-documented. Skip deeper research.

---

### Phase 2: Core Agent Infrastructure (Weeks 5-8)
**Rationale:** Agents need context management and knowledge retrieval to function. These shared services enable the first specialist agents. Building Discovery + Strategy first (simpler than real-time interaction) validates the orchestration model.

**Delivers:**
- Context Manager (three-tier model: Working/Session/Memory)
- Knowledge Base service (ingestion + retrieval + Agentic RAG)
- Vector Store with tenant namespaces (Qdrant)
- Supervisor Orchestrator (basic task routing)
- First 2 agents: Discovery Agent + Strategy Agent

**Addresses features:**
- P-4 (Knowledge base architecture)
- P-7 (Conversation memory)
- Partial P-5 (Agent coordination patterns)

**Avoids pitfalls:**
- Pitfall 2 (Cascading hallucinations) — validation checkpoints at agent handoffs
- Pitfall 7 (Dumb RAG) — hierarchical context with relevance scoring

**Research flags:** Agentic RAG patterns need validation during implementation. Standard multi-agent orchestration is well-documented.

---

### Phase 3: Deal Workflow Agents (Weeks 9-12)
**Rationale:** Core deal workflow is the primary value. This validates the platform architecture before adding complex real-time interaction. Sales Agent first (validates patterns), then expand to Pipeline and Proposal agents.

**Delivers:**
- Sales Agent (S-1 through S-10: meeting prep, email, BANT, CRM entry, follow-up, product knowledge)
- Pipeline Agent (deal stage tracking, CRM updates)
- Proposal Agent (proposal generation with KB + templates)
- CRM Adapter (Salesforce/HubSpot bidirectional sync)
- GSuite Adapter (Calendar, Gmail)
- Clone Registry (per-rep agent configurations)
- End-to-end deal workflow validation (prospect email → agent processing → CRM update → follow-up)

**Addresses features:**
- P-3 (GSuite integration) — email, calendar
- P-6 (CRM integration)
- S-1, S-4, S-5, S-6, S-7, S-8 (Sales Agent core)
- P-8 (Persona adaptation) — basic IC/exec differentiation
- P-10 (Human escalation) — safety net

**Avoids pitfalls:**
- Pitfall 5 (Escalation failures) — bounded autonomy framework, tiered escalation
- Pitfall 6 (Robotic execution) — train on transcripts, conversation state model
- Pitfall 10 (Missing observability) — tracing from day one

**Research flags:**
- **Needs deeper research:** CRM-specific integration patterns (Salesforce vs HubSpot differences)
- **Needs validation:** Sales methodology execution patterns (BANT, MEDDIC transcripts)
- Standard patterns: GSuite APIs well-documented

---

### Phase 4: Real-Time Interaction (Weeks 13-18)
**Rationale:** Real-time voice and avatar are the most complex features with strict latency requirements. Deferring until core agent workflows are proven reduces risk. Meeting attendance is the "wow" differentiator but shouldn't gate core product value.

**Delivers:**
- Voice Pipeline (STT + TTS + orchestration with Vapi, Deepgram, ElevenLabs)
- Meeting Bot integration (Recall.ai API for Google Meet)
- Meeting Agent (real-time conversation, low-latency path)
- Avatar Engine integration (HeyGen LiveAvatar)
- Low-latency optimization (streaming, model tiering, edge deployment, KV caching)
- S-2 (Meeting attendance with avatar)
- S-3 (Meeting minutes and distribution)

**Addresses features:**
- S-2 (Meeting attendance) — core differentiator
- S-3 (Meeting minutes)
- Optional S-23 (Voice calls)
- P-3 (GSuite Meet integration)

**Avoids pitfalls:**
- Pitfall 4 (Voice latency) — hard 800ms budget, streaming, fast models, edge deployment
- Pitfall 8 (Avatar uncanny valley) — behavioral realism prioritized over visual realism, voice-only fallback

**Research flags:**
- **Needs deeper research:** Latency optimization techniques, meeting bot deployment patterns, avatar provider APIs
- **High complexity:** Sub-second response pipeline requires careful orchestration

---

### Phase 5: Analytics & Remaining Agents (Weeks 19-22)
**Rationale:** Analytics requires conversation data to analyze, which only exists after Phases 3-4 agents produce interactions. Consolidation and Coaching agents provide cross-conversation intelligence. Other specialist agents (SA, PM, BA, TAM, CS, Collections, Ops) expand the platform once Sales Agent template is validated.

**Delivers:**
- Data Consolidation Engine (ETL from event store)
- Consolidation Agent (cross-conversation pattern recognition)
- Coaching Agent (performance analysis)
- Dashboard API (real-time metrics)
- Solution Architect Agent
- Project Manager Agent
- Business Analyst Agent
- TAM Agent
- Customer Success Agent
- Collections Agent
- Ops Agent

**Addresses features:**
- P-12 (Cross-agent pattern recognition) — "hive mind" advantage
- P-15 (Unified customer 360)
- All SA, PM, BA, TAM, CS, CO, OPS features
- S-11 (MEDDIC) — deeper qualification
- S-15 (Political mapping) — enterprise account complexity
- S-16 (Account planning)

**Avoids pitfalls:**
- Pitfall 11 (Token cost explosion) — per-agent budgets, tiered models, cost monitoring

**Research flags:**
- **Standard patterns:** Most agent types follow Sales Agent template
- **Needs validation:** Methodology execution depth (MEDDIC, TAS, Chris Voss, Sandler)

---

### Phase 6: Production Hardening (Weeks 23-26)
**Rationale:** Security, multi-region, cost optimization, and load testing need a complete system. Premature optimization is wasteful.

**Delivers:**
- Multi-region deployment (APAC, EMEA, Americas)
- Regional knowledge content variants
- P-2 (Regional behavior customization)
- Cost optimization (caching, model tiering, context compression)
- Security audit (tenant isolation verification, prompt injection testing)
- Load testing (concurrent meetings, agent storms, token budgets under load)
- Monitoring, alerting, observability dashboards
- S-12, S-13, S-14 (TAS, Chris Voss, Sandler) — advanced methodologies
- S-19 (Self-directed goal pursuit) — capstone feature
- S-20 (Multi-methodology selection)
- P-11 (Agent cloning with persona overlay)

**Addresses features:**
- P-2 (Multi-region customization)
- Advanced Sales Agent differentiation
- P-11 (Agent cloning)

**Avoids pitfalls:**
- Pitfall 12 (Prompt injection) — red team testing, input sanitization
- All pitfalls verification through load testing and security audit

**Research flags:**
- **Needs validation:** Regional customization patterns, advanced methodology transcripts
- **Standard patterns:** Load testing, security hardening

---

### Phase Ordering Rationale

**Why Foundation first:** Every component needs tenant context, event infrastructure, orchestration topology. Multi-tenancy and coordination architecture cannot be retrofitted — they are architectural properties, not features. Cost to fix if ignored: EXTREME.

**Why Core Infrastructure before agents:** Agents need context management, knowledge retrieval, and validation checkpoints to function safely. Building agents before these exist leads to Pitfall 2 (cascading hallucinations) and Pitfall 7 (dumb RAG).

**Why Deal Workflow before Real-Time:** Core deal workflow (email, CRM, qualification, follow-up) is the primary value. It validates the agent model on async workflows where latency is forgiving. Real-time voice/avatar is enhancement, not core. Latency optimization is hard; deferring it reduces early risk. Cost to fix if voice comes first: MEDIUM-HIGH (latency optimization is additive but streaming pipeline refactor is significant).

**Why Analytics after data exists:** Consolidation Agent needs conversation data to analyze. Pattern recognition across accounts requires multiple agents producing interactions. Building analytics first means no data to analyze.

**Why Production Hardening last:** Security audits, load testing, cost optimization need a complete system. Premature optimization wastes effort. Once complete, hardening can be layered on.

**Dependency chain:**
```
Foundation (tenant + events + orchestration)
  ↓
Core Infrastructure (context + knowledge + validation)
  ↓
Deal Workflow Agents (Sales → Pipeline → Proposal)
  ↓
Real-Time Interaction (Voice → Meeting → Avatar)
  ↓
Analytics & Remaining Agents (Consolidation → 7 specialist agents)
  ↓
Production Hardening (multi-region + security + optimization)
```

### Research Flags

**Phases needing deeper research during planning:**

- **Phase 3 (Deal Workflow):** CRM integration patterns vary significantly between Salesforce/HubSpot. Custom field mappings, workflow triggers, and API rate limits need per-tenant discovery. Sales methodology execution (MEDDIC, BANT) needs transcript data from top performers to train conversation models naturally.

- **Phase 4 (Real-Time Interaction):** Latency optimization techniques need validation with production audio/video streams. Meeting bot deployment patterns (Recall.ai vs custom) need POC to determine trade-offs. Avatar provider APIs (HeyGen LiveAvatar) are new; integration patterns need validation.

- **Phase 6 (Production Hardening):** Regional customization patterns (APAC relationship-first vs Americas direct) need cultural research. Advanced methodology transcripts (TAS, Chris Voss, Sandler) need sourcing from enterprise sales training content.

**Phases with standard patterns (skip research):**

- **Phase 1 (Foundation):** Multi-tenant SaaS patterns, event-driven architecture, tenant isolation are well-documented. PostgreSQL RLS, Redis Streams, API Gateway auth are established.

- **Phase 2 (Core Infrastructure):** LangGraph orchestration, three-tier context management (Google ADK pattern), Agentic RAG, vector DB multi-tenancy are documented in official sources.

- **Phase 5 (Analytics):** Data consolidation, pattern recognition, dashboard APIs are standard data engineering patterns.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| **Stack** | **HIGH** | Python + LangGraph + FastAPI is verified through official docs (LangGraph, Context7). Voice/avatar/meeting bot stack (Vapi, Deepgram, ElevenLabs, HeyGen, Recall.ai) verified through vendor documentation. GCP deployment patterns are standard. Model choices (Claude Sonnet, gpt-realtime) confirmed via official APIs. Version compatibility checked. |
| **Features** | **MEDIUM-HIGH** | Platform features (multi-tenant, knowledge base, agent communication) are well-understood enterprise patterns. Sales Agent features (MEDDIC, BANT, political mapping) are documented in sales methodology literature. Feature complexity estimates based on similar production systems. Uncertainty: specific sales methodology execution depth (MEDDIC transcripts, Chris Voss tactics) needs validation with actual training data. |
| **Architecture** | **MEDIUM** | Supervisor-with-Specialist-Groups pattern documented by Kore.ai, Confluent, multiple sources. Three-tier context management from Google ADK (verified official source). Event-driven multi-agent patterns well-established. Agentic RAG is 2026 best practice. Uncertainty: specific inter-agent protocol design needs testing. Meeting bot architecture (Recall.ai vs custom) needs POC validation. Avatar integration patterns are new (HeyGen LiveAvatar is recent). |
| **Pitfalls** | **HIGH** | Critical pitfalls verified through multiple authoritative sources: Cornell arXiv paper (bag of agents, cascading hallucinations), OWASP ASI08 (cascading failures), multiple enterprise AI post-mortems (2025 failures), Ruh.ai (voice latency benchmarks), security frameworks (multi-tenant isolation). Recovery costs estimated from production refactor data. Pitfall-to-phase mapping clear from dependencies. |

**Overall confidence:** **MEDIUM-HIGH**

High confidence on foundational technology choices (stack, pitfalls, multi-tenancy architecture). Medium confidence on specific agent behavior patterns (how to execute MEDDIC naturally, how to avoid robotic conversations). These areas need validation during implementation with real conversation data and transcript training.

### Gaps to Address

**Gap 1: Sales methodology execution patterns**
- Research identified WHAT methodologies to implement (MEDDIC, BANT, TAS, Chris Voss, Sandler) but not HOW to execute them naturally in conversation
- Need: Transcripts from top 1% performers showing how they weave qualification into value conversations
- **How to handle:** During Phase 3 planning, source training transcripts from sales training platforms (Gong, Chorus, sales methodology vendors). Use for agent prompt engineering and evaluation benchmarks.

**Gap 2: Avatar provider integration specifics**
- HeyGen LiveAvatar is new (replaced Interactive Avatar); integration patterns not widely documented
- Need: POC to validate WebRTC streaming, lip sync quality under load, Recall.ai integration glue code
- **How to handle:** During Phase 4 planning, run 2-week POC with HeyGen LiveAvatar API + Recall.ai bot. Measure latency, sync quality, concurrent stream limits. Have fallback to voice-only if avatar quality insufficient.

**Gap 3: CRM customization discovery**
- Each tenant (Skyvera, Jigtree, Totogi) will have heavily customized Salesforce/HubSpot instances with custom fields, workflows, validation rules
- Need: Schema mapping for each tenant's CRM instance
- **How to handle:** During Phase 3 planning, export CRM schemas from each tenant. Build adapter layer with per-tenant configuration. Assume 5,000+ custom fields (per PITFALLS.md integration gotchas). Test with real tenant CRM exports, not sample data.

**Gap 4: Regional customization content**
- Research identified THAT regions differ (APAC relationship-first, Americas direct, EMEA consensus-driven) but not specific conversation pattern differences
- Need: Cultural sales research for each region
- **How to handle:** During Phase 6 planning, engage regional sales leaders to document communication norms, decision-making patterns, relationship expectations. Build region-specific conversation examples for agent training.

**Gap 5: Token cost projections at scale**
- Research provides optimization techniques (caching, tiering, compression) but not specific cost projections for 3 tenants x 50 reps x 10 deals each
- Need: Cost model with usage estimates
- **How to handle:** During Phase 2 planning, build cost simulator projecting monthly spend based on: agents per interaction, tokens per agent, interactions per deal, deals per tenant. Set budget alerts. Revisit after Phase 3 with real usage data.

## Sources

### Primary (HIGH confidence)

**Context7 verified:**
- `/llmstxt/langchain-ai_github_io_langgraph_llms_txt` — LangGraph multi-agent architecture, StateGraph, Command patterns, deployment
- `/crewaiinc/crewai` — CrewAI memory, knowledge, agent orchestration (comparison to LangGraph)

**Official documentation:**
- [Google Developers Blog: Architecting Efficient Context-Aware Multi-Agent Framework for Production](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/) — Three-tier context model (HIGH confidence)
- [HeyGen Streaming API docs](https://docs.heygen.com/docs/streaming-api) — LiveAvatar WebRTC, SDK details
- [Qdrant Multitenancy Guide](https://qdrant.tech/documentation/guides/multitenancy/) — Payload partitioning, tiered multitenancy v1.16
- [Vapi Quickstart](https://docs.vapi.ai/quickstart) — Architecture, latency targets, provider pluggability
- [Google Workspace Developer Products](https://developers.google.com/workspace/products) — API availability, Events API v1 GA
- [OpenAI Realtime API announcement](https://openai.com/index/introducing-gpt-realtime/) — GA status, gpt-realtime model
- [ElevenLabs latency optimization](https://elevenlabs.io/docs/developers/best-practices/latency-optimization) — Flash v2.5 75ms, Turbo v2.5 250ms
- [Deepgram Streaming API](https://developers.deepgram.com/reference/speech-to-text/listen-streaming) — WebSocket streaming, sub-300ms latency

**Research papers:**
- [Cornell arXiv: Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/pdf/2503.13657) — Analysis of 1,642 multi-agent traces (HIGH confidence)
- [OWASP ASI08: Cascading Failures in Agentic AI](https://adversa.ai/blog/cascading-failures-in-agentic-ai-complete-owasp-asi08-security-guide-2026/) — January 2026 security framework

### Secondary (MEDIUM confidence)

**Multi-agent architecture:**
- [Kore.ai: Choosing the Right Orchestration Pattern for Multi-Agent Systems](https://www.kore.ai/blog/choosing-the-right-orchestration-pattern-for-multi-agent-systems) — Supervisor, Adaptive Network, Custom patterns
- [Confluent: Four Design Patterns for Event-Driven Multi-Agent Systems](https://www.confluent.io/blog/event-driven-multi-agent-systems/) — Orchestrator-Worker, Hierarchical, Blackboard, Market-Based
- [IBM: Agent2Agent (A2A) Protocol](https://www.ibm.com/think/topics/agent2agent-protocol)

**Voice/Avatar:**
- [AssemblyAI: The Voice AI Stack for Building Agents in 2026](https://www.assemblyai.com/blog/the-voice-ai-stack-for-building-agents) — STT/TTS/LLM stack, latency budgets
- [Ruh.ai: Voice AI Latency Optimization: Sub-Second Agent Responses](https://www.ruh.ai/blogs/voice-ai-latency-optimization) — Specific benchmarks with methodology (HIGH confidence)
- [Andreessen Horowitz: AI Avatars Escape the Uncanny Valley](https://a16z.com/ai-avatars/)

**Security and multi-tenancy:**
- [Microsoft Azure Architecture Center: Multi-tenant AI Architecture](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/approaches/ai-machine-learning) — Isolation models
- [Ingenimax: Building a Multi-Tenant Production-Grade AI Agent](https://ingenimax.ai/blog/building-multi-tenant-ai-agent) — Isolation strategies, LLM routing
- [FastGPT: How AI Agents Avoid Data Leakage in Multi-Tenant Environments](https://fastgpt.io/en/faq/How-AI-Agents-Avoid-Data)
- [Security Boulevard: Tenant Isolation in Multi-Tenant Systems](https://securityboulevard.com/2025/12/tenant-isolation-in-multi-tenant-systems-architecture-identity-and-security/) — December 2025
- [WSO2: Why AI Agents Need Their Own Identity](https://wso2.com/library/blogs/why-ai-agents-need-their-own-identity-lessons-from-2025-and-resolutions-for-2026/)

**Sales methodology:**
- [Salesforce: BANT vs MEDDIC](https://www.salesforce.com/blog/bant-vs-meddic/) — Methodology comparison (HIGH confidence)
- [Gong: Sales Methodologies](https://www.gong.io/blog/sales-methodologies) — Methodology overview
- [Oliv AI: MEDDIC Sales Methodology: Training, Implementation & AI](https://www.oliv.ai/blog/meddic-sales-methodology)
- [DemandFarm: Relationship Mapping](https://www.demandfarm.com/org-chart-software/) — Political mapping tools

**Enterprise AI failures:**
- [Sweep: Why Enterprise AI Stalled in 2025: A Post-Mortem](https://www.sweep.io/blog/2025-the-year-enterprise-ai-hit-the-system-wall/)
- [Composio: Why AI Pilots Fail in Production: 2026 Integration Roadmap](https://composio.dev/blog/why-ai-agent-pilots-fail-2026-integration-roadmap)
- [Accelirate: 5 Agentic AI Pitfalls That Derail Enterprise Projects](https://www.accelirate.com/agentic-ai-pitfalls/)

**Technical comparisons:**
- [AI Agent Frameworks Comparison 2025](https://www.getmaxim.ai/articles/top-5-ai-agent-frameworks-in-2025-a-practical-guide-for-ai-builders/) — LangGraph vs CrewAI
- [IBM: Comparing AI Agent Frameworks (CrewAI, LangGraph, BeeAI)](https://developer.ibm.com/articles/awb-comparing-ai-agent-frameworks-crewai-langgraph-and-beeai/)
- [Voice AI Platform Ranking 2025](https://softcery.com/lab/choosing-the-right-voice-agent-platform-in-2025) — Vapi vs Retell vs Bland
- [Vector Database Comparison 2025](https://www.firecrawl.dev/blog/best-vector-databases-2025) — Qdrant vs Pinecone vs pgvector

### Tertiary (LOW confidence, needs validation)

- HeyGen LiveAvatar pricing (credit-based, check current pricing page)
- Redis 8.2 "35% faster" claim (marketing, benchmark independently)
- Specific token cost estimates (vendor marketing, validate with production data)
- Chris Voss AI negotiation prompts (implementation approach, not verified in production context)

---

**Research completed:** 2026-02-10
**Ready for roadmap:** Yes

**Orchestrator note:** All 4 research files (STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md) synthesized. Key findings extracted and distilled into roadmap implications. Phase structure (6 phases, 26 weeks) derived from dependency analysis and risk mitigation priorities. Research flags identified for complex phases. Confidence assessed honestly with gaps documented. SUMMARY.md ready for gsd-roadmapper consumption.
