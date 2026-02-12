# Roadmap: Agent Army Platform

## Overview

Agent Army delivers a multi-tenant AI sales organization platform where a Sales Agent autonomously executes enterprise sales methodology at top-1% level. The build progresses from infrastructure foundation through agent orchestration, knowledge base, conversational capabilities, deal management, real-time meeting attendance, and finally autonomous intelligence -- each phase delivering a complete, verifiable capability that unblocks the next. The Sales Agent validated across all 7 phases becomes the template for the remaining 7 agent roles (v2).

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Infrastructure Foundation** - Multi-tenant platform bedrock with tenant isolation, database, caching, LLM integration, deployment, and security
- [x] **Phase 2: Agent Orchestration** - Supervisor topology, event-driven coordination, context management, and observability
- [x] **Phase 3: Knowledge Base** - Product knowledge, vector search, agentic RAG, methodology library, and conversation memory
- [x] **Phase 4: Sales Agent Core** - Text-based sales conversations with email, chat, persona adaptation, and methodology execution
- [x] **Phase 4.1: Agent Learning & Performance Feedback (INSERTED)** - Outcome tracking, confidence calibration, human feedback loops, and performance analytics
- [x] **Phase 5: Deal Management** - CRM integration, opportunity tracking, account/opportunity plans, and political mapping
- [ ] **Phase 6: Meeting Capabilities** - Google Meet attendance with avatar, real-time response, recording, minutes, and distribution
- [ ] **Phase 7: Intelligence & Autonomy** - Data consolidation, pattern recognition, self-directed goals, proactive outreach, and agent cloning

## Phase Details

### Phase 1: Infrastructure Foundation
**Goal**: A multi-tenant platform exists where tenant-isolated services can be deployed, accessed securely, and monitored -- the bedrock for everything that follows
**Depends on**: Nothing (first phase)
**Requirements**: PLT-01, PLT-02, PLT-10, INF-01, INF-02, INF-03, INF-04, INF-05, INF-06, INF-07, INF-08, INF-09, INF-10
**Success Criteria** (what must be TRUE):
  1. A new tenant (e.g., Skyvera) can be provisioned and its data is completely isolated from other tenants at database, cache, and API levels
  2. Tenant context propagates correctly through API requests -- a request for Tenant A never touches Tenant B's data
  3. The API gateway authenticates requests, resolves tenant context, and routes to backend services
  4. LLM calls can be made through the gateway with provider abstraction (Claude for reasoning, OpenAI for voice) and responses return correctly
  5. The platform deploys to a staging environment via automated pipeline with secrets managed per tenant
**Plans**: 3 plans in 2 waves

Plans:
- [x] 01-01-PLAN.md -- Multi-tenant database and tenant provisioning (Wave 1)
- [x] 01-02-PLAN.md -- API gateway, authentication, and LLM integration (Wave 2, depends on 01-01)
- [x] 01-03-PLAN.md -- Deployment pipeline, monitoring, and environment management (Wave 2, depends on 01-01)

### Phase 2: Agent Orchestration
**Goal**: Agents can be registered, coordinated through a supervisor topology, and communicate via events with validated handoffs -- preventing the "bag of agents" anti-pattern
**Depends on**: Phase 1
**Requirements**: PLT-03, PLT-04, PLT-05, PLT-06, PLT-07, PLT-08, PLT-09
**Success Criteria** (what must be TRUE):
  1. The supervisor orchestrator can receive a task, decompose it, route to specialist agent(s), and synthesize results
  2. Agents communicate through the event bus (Redis Streams) with structured messages that include tenant context and source attribution
  3. Agent handoffs include validation checkpoints that reject malformed or unattributed data (preventing cascading hallucination)
  4. Three-tier context management works: working context compiles correctly per invocation, session state persists across turns, and long-term memory is searchable
  5. Agent decisions are traceable through observability tooling (LangSmith or equivalent) with per-tenant per-agent cost tracking
**Plans**: 6 plans in 4 waves

Plans:
- [x] 02-01-PLAN.md -- Event bus infrastructure: Redis Streams event schemas, tenant-scoped bus, consumer with retry, DLQ (Wave 1)
- [x] 02-02-PLAN.md -- Agent registry and base agent: BaseAgent abstract class, AgentRegistry with capability discovery and backup routing (Wave 1)
- [x] 02-03-PLAN.md -- Handoff validation protocol: structural Pydantic validators, LLM semantic validation, configurable strictness (Wave 2, depends on 02-01, 02-02)
- [x] 02-04-PLAN.md -- Three-tier context management: session store (PostgreSQL checkpointer), long-term memory (pgvector), working context compiler (tiktoken budget) (Wave 1)
- [x] 02-05-PLAN.md -- Supervisor orchestration: hybrid router (rules + LLM), task decomposition, backup failure handling, LLM result synthesis (Wave 3, depends on 02-02, 02-03, 02-04)
- [x] 02-06-PLAN.md -- Observability, cost tracking, and integration wiring: Langfuse tracing, per-tenant per-agent costs, Prometheus metrics, main.py wiring, integration tests (Wave 4, depends on 02-01, 02-05)

### Phase 3: Knowledge Base
**Goal**: The platform has a rich, tenant-scoped knowledge foundation that agents can query -- product data, sales methodologies, regional nuances, and conversation history are all retrievable with high relevance
**Depends on**: Phase 1, Phase 2
**Requirements**: KB-01, KB-02, KB-03, KB-04, KB-05, KB-06, KB-07
**Success Criteria** (what must be TRUE):
  1. Product knowledge for Skyvera (offerings, pricing, positioning) is ingested and retrievable with tenant-scoped vector search
  2. Agentic RAG pipeline decomposes complex queries, retrieves from multiple sources, and synthesizes coherent answers grounded in source documents
  3. Sales methodology frameworks (MEDDIC, BANT) are structured and queryable -- an agent can retrieve the right framework guidance for a given deal situation
  4. Conversation history persists across sessions and channels -- an agent can recall what was discussed in a previous email when preparing for a meeting
  5. New product documents can be ingested through the pipeline (supporting future ESW acquisitions)
**Plans**: 7 plans in 5 waves

Plans:
- [x] 03-01: Qdrant vector DB and embedding foundation (Wave 1)
- [x] 03-02: Document ingestion pipeline (Wave 2)
- [x] 03-03: End-to-end ingestion orchestration (Wave 3, depends on 03-02)
- [x] 03-04: ESW product knowledge data (Wave 4, depends on 03-03)
- [x] 03-05: Sales methodology and regional nuances (Wave 2)
- [x] 03-06: Conversation history storage (Wave 2)
- [x] 03-07: Agentic RAG pipeline (Wave 5, depends on 03-01,03-03,03-04,03-05,03-06)

### Phase 4: Sales Agent Core
**Goal**: The Sales Agent can conduct text-based sales interactions -- sending contextual emails and chats, adapting to customer personas, executing qualification frameworks, and knowing when to escalate to a human
**Depends on**: Phase 2, Phase 3
**Requirements**: SA-01, SA-02, SA-03, SA-04, SA-05, SA-06, SA-07, SA-08, SA-09, SA-10
**Success Criteria** (what must be TRUE):
  1. Sales Agent sends contextual emails via Gmail that reflect the current deal stage, account history, and appropriate persona tone (different for IC vs C-suite)
  2. Sales Agent sends Google Chat messages to customers and internal team with relevant context pulled from account/deal data
  3. Sales Agent executes BANT qualification naturally within conversations -- extracting budget, authority, need, and timeline signals without robotic interrogation
  4. Sales Agent executes MEDDIC qualification -- identifying metrics, economic buyer, decision criteria, decision process, pain, and champion through conversational discovery
  5. Sales Agent tracks conversation state across interactions and recommends next actions, escalating to human when confidence drops below threshold
**Plans**: 5 plans in 4 waves

Plans:
- [x] 04-01-PLAN.md -- GSuite integration services: Gmail and Google Chat async wrappers with auth caching (Wave 1)
- [x] 04-02-PLAN.md -- Sales schemas and persona-adapted prompt system with Chris Voss methodology (Wave 1)
- [x] 04-03-PLAN.md -- Conversation state persistence and qualification signal extraction with instructor (Wave 2, depends on 04-02)
- [x] 04-04-PLAN.md -- SalesAgent class, next-action engine, and escalation manager (Wave 3, depends on 04-01, 04-02, 04-03)
- [x] 04-05-PLAN.md -- API endpoints, agent registration, and integration tests (Wave 4, depends on 04-04)

### Phase 4.1: Agent Learning & Performance Feedback (INSERTED)
**Goal**: The Sales Agent learns from its interactions and improves over time through outcome tracking, confidence calibration, human feedback loops, and performance analytics -- enabling continuous improvement and sales team insights
**Depends on**: Phase 4
**Requirements**: Extension of SA requirements (outcome tracking, feedback systems, analytics)
**Success Criteria** (what must be TRUE):
  1. Outcome tracking captures whether agent actions led to positive or negative results -- customer engaged vs ghosted, deal progressed vs stalled, response quality indicators
  2. Human feedback mechanism allows sales reps and managers to mark agent responses as good/bad/needs-improvement, feeding into the learning system
  3. Confidence calibration tracks agent confidence scores vs actual success rates and identifies calibration gaps (overconfident or underconfident predictions)
  4. Performance analytics dashboard shows agent effectiveness metrics -- response quality trends, escalation rate patterns, customer engagement scores, qualification completion rates
  5. Sales training module identifies patterns from escalations and successful interactions to train human reps on what works (turning AI insights into human coaching)
**Plans**: 3 plans in 3 waves

Plans:
- [x] 04.1-01-PLAN.md -- Outcome tracking data models, Pydantic schemas, OutcomeTracker service, and migration (Wave 1)
- [x] 04.1-02-PLAN.md -- FeedbackCollector, CalibrationEngine, CoachingPatternExtractor services (Wave 2, depends on 04.1-01)
- [x] 04.1-03-PLAN.md -- AnalyticsService, scheduler, API endpoints, SSE streaming, main.py wiring, and integration tests (Wave 3, depends on 04.1-01, 04.1-02)

### Phase 5: Deal Management
**Goal**: The Sales Agent manages the full deal lifecycle -- identifying opportunities from conversations, maintaining strategic account plans and tactical opportunity plans, mapping political structures, and keeping CRM in sync
**Depends on**: Phase 4
**Requirements**: SA-19, SA-20, SA-21, SA-22, SA-23, SA-24
**Success Criteria** (what must be TRUE):
  1. Sales Agent identifies opportunity signals (budget mentions, pain points, timeline urgency) from conversations and creates qualified opportunities
  2. Sales Agent creates and maintains account plans (strategic relationship view) and opportunity plans (tactical deal view) that update as new information emerges
  3. Sales Agent maps political structures within accounts -- identifying decision makers, influencers, champions, and blockers with power dynamics
  4. CRM integration (Salesforce or HubSpot) works bidirectionally -- agent creates/updates opportunities, contacts, and activities; CRM changes flow back to agent context
  5. Deal stages progress automatically based on qualification signals -- agent moves opportunities through the pipeline when evidence supports advancement
**Plans**: 6 plans in 4 waves

Plans:
- [x] 05-01-PLAN.md -- Deal management data models, schemas, repository, and migration (Wave 1)
- [x] 05-02-PLAN.md -- Opportunity detection, political mapping, and plan manager (Wave 2, depends on 05-01)
- [x] 05-03-PLAN.md -- CRM adapter, Notion connector, and sync engine (Wave 2, depends on 05-01)
- [x] 05-04-PLAN.md -- Evidence-based stage progression engine (Wave 2, depends on 05-01)
- [x] 05-05-PLAN.md -- API endpoints, post-conversation hooks, main.py wiring, and integration tests (Wave 3, depends on 05-01, 05-02, 05-03, 05-04)
- [x] 05-06-PLAN.md -- Gap closure: wire PostConversationHook into sales conversation endpoints (Wave 4, depends on 05-05)

### Phase 6: Meeting Capabilities
**Goal**: The Sales Agent attends Google Meet meetings with an avatar representation, participates in real-time conversation, and produces meeting minutes distributed to stakeholders -- the "wow" differentiator
**Depends on**: Phase 4
**Requirements**: SA-11, SA-12, SA-13, SA-14, SA-15, SA-16, SA-17, SA-18
**Success Criteria** (what must be TRUE):
  1. Sales Agent creates meeting briefings before scheduled calls -- including account context, attendee profiles, objectives, and suggested talk tracks
  2. Sales Agent joins Google Meet via meeting bot (Recall.ai) with avatar representation (HeyGen LiveAvatar) that is visually present to attendees
  3. Real-time speech-to-text captures the meeting conversation and the agent generates responses within the latency budget (target under 1 second end-to-end)
  4. Meeting recordings are captured, stored, and searchable -- feeding back into the agent's knowledge of the account
  5. Structured meeting minutes (summary, action items, decisions) are generated and automatically distributed to stakeholders within minutes of meeting end
**Plans**: TBD

Plans:
- [ ] 06-01: Meeting briefing generation and Google Meet bot integration
- [ ] 06-02: Avatar representation and real-time response pipeline
- [ ] 06-03: Recording capture, minutes generation, and stakeholder distribution

### Phase 7: Intelligence & Autonomy
**Goal**: The Sales Agent operates with autonomous intelligence -- consolidating data across all channels, recognizing patterns, pursuing revenue goals self-directedly, adapting to geographic norms, and being clonable per sales rep
**Depends on**: Phase 4, Phase 5, Phase 6
**Requirements**: SA-25, SA-26, SA-27, SA-28, SA-29, SA-30
**Success Criteria** (what must be TRUE):
  1. Sales Agent consolidates data across emails, chats, meetings, and CRM into a unified customer view -- no information silo between channels
  2. Sales Agent recognizes patterns within accounts (e.g., "champion has mentioned budget freeze in 3 separate conversations") and surfaces actionable insights
  3. Sales Agent tracks its own performance metrics (dollars identified, dollars sold, average deal time, closing rate) and self-directs toward revenue targets without human prompting
  4. Sales Agent adapts behavior for geographic context -- different communication styles, relationship expectations, and decision-making norms for APAC, EMEA, and Americas
  5. Agent cloning system allows replication with different persona per sales rep -- each regional director gets their own Sales Agent tuned to their style
**Plans**: TBD

Plans:
- [ ] 07-01: Cross-channel data consolidation and pattern recognition
- [ ] 07-02: Self-directed goal tracking and proactive outreach
- [ ] 07-03: Geographic customization and agent cloning system

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 4.1 -> 5 -> 6 -> 7
Note: Phase 4.1 was inserted to add learning capabilities before deal management complexity.
Note: Phases 5 and 6 both depend on Phase 4 and could execute in parallel after Phase 4.1.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure Foundation | 3/3 | Complete | 2026-02-11 |
| 2. Agent Orchestration | 6/6 | Complete | 2026-02-11 |
| 3. Knowledge Base | 7/7 | Complete | 2026-02-11 |
| 4. Sales Agent Core | 5/5 | Complete | 2026-02-12 |
| 4.1. Agent Learning & Performance Feedback | 3/3 | Complete | 2026-02-12 |
| 5. Deal Management | 6/6 | Complete | 2026-02-12 |
| 6. Meeting Capabilities | 0/3 | Not started | - |
| 7. Intelligence & Autonomy | 0/3 | Not started | - |

---
*Roadmap created: 2026-02-10*
*Last updated: 2026-02-12 after Phase 5 completion*
