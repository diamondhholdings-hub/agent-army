# Agent Army: Enterprise Sales Organization Platform

## What This Is

A complete AI sales organization platform with 8 specialized agents (Sales Agent, Solution Architect, Project Manager, Business Analyst, Technical Account Manager, Customer Success Agent, Collections Agent, Business Operations Agent). Each agent performs at top 1% global level in their role. One human per region (APAC, EMEA, Americas) is supported by their AI crew. Multi-tenant architecture supports deployment across ESW business units (Skyvera, Jigtree, Totogi) with per-product and per-region customization.

**v1.0 shipped (2026-02-22):** Sales Agent + Platform Foundation — 10 phases, 49 plans, 1,123 tests, ~67K Python LOC. The Sales Agent is validated and ready to serve as the template for the remaining 7 agents in v2.

## Core Value

The Sales Agent autonomously executes enterprise sales methodology at top-1% level — attending meetings with avatar, applying sales frameworks (BANT, MEDDIC, QBS, Chris Voss), creating account plans, and self-directing toward revenue targets. This is the proven foundation that validates the platform architecture for all 8 agent roles.

## Requirements

### Validated (v1.0)

- ✓ GSuite integration (Gmail, Chat, Google Meet) — v1.0
- ✓ Send contextual emails and chats based on deal stage — v1.0
- ✓ Attend Google Meet meetings with avatar representation — v1.0 (Recall.ai + HeyGen; webapp deployment pending)
- ✓ Create meeting briefings (account context, objectives, talk tracks) — v1.0
- ✓ Capture meeting recordings and create minutes — v1.0
- ✓ Distribute minutes to stakeholders — v1.0 (manual trigger; automated distribution ready)
- ✓ Consolidate data across conversations/meetings/emails — v1.0
- ✓ Pattern recognition within accounts — v1.0
- ✓ Deep product knowledge (Skyvera offerings, pricing, positioning) — v1.0
- ✓ Persona-based interaction (IC, manager, exec, C-suite) — v1.0
- ✓ Self-directed goal pursuit (revenue tracking, pipeline metrics) — v1.0
- ✓ Opportunity identification and qualification (BANT, MEDDIC, QBS) — v1.0
- ✓ Sales methodology execution (BANT, MEDDIC, QBS, Chris Voss) — v1.0
- ✓ Create and maintain account plans — v1.0
- ✓ Create and maintain opportunity plans — v1.0
- ✓ Map political structures in accounts — v1.0
- ✓ Geographic customization (APAC, EMEA, Americas) — v1.0
- ✓ Low latency response for live interactions (<1s real-time pipeline) — v1.0
- ✓ Agent orchestration layer (supervisor topology, event bus) — v1.0
- ✓ Knowledge base architecture (product/region/tenant separation) — v1.0
- ✓ Multi-tenant support — v1.0
- ✓ Multi-region support — v1.0
- ✓ Multi-product support (document ingestion pipeline) — v1.0
- ✓ Agent cloning system (persona per sales rep) — v1.0
- ✓ Agent learning and performance feedback — v1.0 (bonus feature)
- ✓ QBS (Question Based Selling) methodology — v1.0 (bonus feature)

### Active (v2.0)

**7 Remaining Agents (use Sales Agent as template):**
- [ ] Solution Architect agent (product-specific technical guidance)
- [ ] Project Manager agent (PMBOK-certified delivery management)
- [ ] Business Analyst agent (requirements gathering and analysis)
- [ ] Technical Account Manager agent (escalations, technical relationships)
- [ ] Customer Success agent (adoption tracking, innovation identification)
- [ ] Collections agent (AR management)
- [ ] Business Operations/Sales Ops agent (process and systems management)

**Sales Agent — Advanced Capabilities:**
- [ ] Voice call capability (Vapi/Deepgram/ElevenLabs pipeline)
- [ ] Target Account Selling methodology
- [ ] Sandler Selling System methodology
- [ ] Competitive battlecards
- [ ] Pricing negotiation guidance

**Platform — Advanced Features:**
- [ ] Cross-agent pattern recognition ("hive mind" analysis)
- [ ] Predictive analytics (deal closure probability, churn risk)
- [ ] Agent performance dashboards per tenant
- [ ] Tenant admin UI

**Production Readiness:**
- [ ] GCP Cloud Run deployment verified (infrastructure code ready, human setup required)
- [ ] Output Media webapp deployed to Vercel + MEETING_BOT_WEBAPP_URL configured
- [ ] Google Workspace credentials configured for production
- [ ] End-to-end demo script validated with real Skyvera data

### Out of Scope

- Human replacement — Agents augment the one human per region, not replace them
- Real-time video deepfake — Avatar is visual placeholder, not photorealistic simulation
- Financial transaction processing — Collections agent identifies issues; humans process payments
- Legal document execution — Agents draft contracts; humans and legal team approve
- Automated contract signing — Legal approval required; out of scope for v1-v2
- Customer data cross-training — Multi-tenant isolation prevents using Skyvera data for Jigtree agents
- Marketing automation — Focus is post-lead (sales/delivery); pre-lead is separate system

## Context

**Company:**
- Building for Skyvera (ESW business unit)
- Will port to Jigtree and Totogi (other ESW business units)
- Growing through acquisition, need product extensibility

**Sales Environment:**
- Enterprise B2B sales
- Complex, multi-stakeholder deals
- Long sales cycles requiring consistent methodology execution
- Geographic distribution (APAC, EMEA, Americas)

**Current State (post-v1.0):**
- Sales Agent is production-ready for text-based interactions (email, chat, deal management, intelligence)
- Meeting capabilities ready for staging (avatar deployment requires `vercel --prod` + MEETING_BOT_WEBAPP_URL)
- Platform architecture validated — ready to clone for 7 additional agents
- Tech stack: Python/FastAPI, PostgreSQL (RLS), Qdrant, Redis, LiteLLM, Langfuse, Recall.ai, HeyGen
- ~67,354 Python LOC, 1,123 tests passing

**Known Issues / Tech Debt:**
- GCP deployment not human-verified (requires Cloud Run project setup)
- CalendarMonitor bot-join trigger partially implemented (manual bot join via REST works)
- Avatar render needs live manual test after Vercel deployment
- CRM integration uses Notion adapter (pattern supports future Salesforce/HubSpot adapter)

## Constraints

- **Timeline**: Days, not weeks — AI-first development with 24/7 execution
- **Quality bar**: Sales agent template validated at 80%+ production-ready ✓ (exceeded — 1,123 tests)
- **Performance**: Low latency for live interactions (<1s real-time pipeline implemented)
- **Accuracy**: AI agents held to higher standard than humans
- **Security**: Enterprise data handling, multi-tenant isolation (RLS enforced)
- **Integration**: GSuite ✓, CRM via Notion adapter ✓

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Build all 8 agents in one project | Sales agent architecture validates platform for all roles | ✓ Good — architecture proven, template ready for 7 agents |
| Sales agent first, others at 30% | Need proven template before parallelizing | ✓ Good — v1.0 shipped, clear path to v2.0 |
| Multi-tenant from day 1 | Will port to Jigtree/Totogi immediately after Skyvera | ✓ Good — RLS isolation works, tenant provisioning verified |
| Avatar for meetings | Humanizes AI presence, increases engagement | ✓ Good — HeyGen + Recall.ai wired; deployment pending |
| Top 1% performance benchmark | Differentiator - better than average human, not just automated | — Pending validation with real customers |
| Fail-open pattern throughout | LLM errors return fallback, not 500 | ✓ Good — consistent across all 10 phases |
| Async deal workflows before real-time | Phase 4-5 before Phase 6 | ✓ Good — stable foundation before real-time complexity |
| Single LLM call for all qualification signals | Anti-pattern: no per-field calls | ✓ Good — performance + coherence |
| No auto-progression past NEGOTIATION | Close decisions are human-only | ✓ Good — guardrail preserved agent trust |
| QBS methodology (INSERTED phase) | Completes methodology stack alongside BANT/MEDDIC/Voss | ✓ Good — 5 question types functional |
| Agent learning (INSERTED phase) | Agent improves over time from outcomes | ✓ Good — calibration + coaching operational |
| Pipeline factory on bot join | Create pipeline on in_call_recording, destroy on call_ended | ✓ Good — clean lifecycle, no wasted connections |

## Current Milestone: v2.0 Agent Crew

**Goal:** Expand the validated Sales Agent template into a full 8-agent AI sales organization — with production deployment, voice capability, and cross-agent intelligence.

**Target features:**
- Production deployment (GCP Cloud Run, Vercel webapp, Google Workspace prod credentials, Notion CRM)
- 7 remaining agents using Sales Agent as template (Solution Architect, PM, BA, TAM, Customer Success, Collections, BizOps)
- Sales Agent advanced capabilities (voice calls via Vapi, Target Account Selling, Sandler, competitive battlecards, pricing negotiation)
- Platform advanced features (cross-agent hive mind, predictive analytics, agent dashboards, tenant admin UI)

---
*Last updated: 2026-02-22 after v2.0 milestone started*
