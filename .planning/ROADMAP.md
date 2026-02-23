# Roadmap: Agent Army Platform

## Milestones

- ✅ **v1.0 Sales Agent MVP** — Phases 1-8 (shipped 2026-02-22) — [Archive](milestones/v1.0-ROADMAP.md)
- 🚧 **v2.0 Agent Crew** — Phases 9-19 (in progress)

## Phases

<details>
<summary>✅ v1.0 Sales Agent MVP (Phases 1-8) — SHIPPED 2026-02-22</summary>

- [x] Phase 1: Infrastructure Foundation (3/3 plans) — completed 2026-02-11
- [x] Phase 2: Agent Orchestration (6/6 plans) — completed 2026-02-11
- [x] Phase 3: Knowledge Base (7/7 plans) — completed 2026-02-11
- [x] Phase 4: Sales Agent Core (5/5 plans) — completed 2026-02-12
- [x] Phase 4.1: Agent Learning & Performance Feedback (3/3 plans, INSERTED) — completed 2026-02-12
- [x] Phase 4.2: QBS Methodology Integration (4/4 plans, INSERTED) — completed 2026-02-12
- [x] Phase 5: Deal Management (6/6 plans) — completed 2026-02-12
- [x] Phase 6: Meeting Capabilities (6/6 plans) — completed 2026-02-13
- [x] Phase 7: Intelligence & Autonomy (6/6 plans) — completed 2026-02-16
- [x] Phase 8: Meeting Real-Time Completion (3/3 plans, GAP CLOSURE) — completed 2026-02-22

**Total: 10 phases, 49 plans**
Full details: [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md)

</details>

### 🚧 v2.0 Agent Crew (In Progress)

**Milestone Goal:** Expand the validated Sales Agent template into a full 8-agent AI sales organization — with production deployment, voice capability, advanced methodology, and cross-agent intelligence.

- [ ] **Phase 9: Production Deployment** — Sales Agent running in production with verified end-to-end demo
- [ ] **Phase 10: Solution Architect Agent** — Technical guidance agent that maps requirements and scopes POCs
- [ ] **Phase 11: Project Manager Agent** — PMBOK-certified delivery management agent
- [ ] **Phase 12: Business Analyst Agent** — Requirements gathering, gap analysis, and process documentation agent
- [ ] **Phase 13: Technical Account Manager Agent** — Technical health monitoring and escalation prediction agent
- [ ] **Phase 14: Customer Success Agent** — Account health scoring, churn prediction, and expansion identification agent
- [ ] **Phase 15: Collections Agent** — AR tracking, payment prediction, and adaptive collection agent
- [ ] **Phase 16: Business Operations Agent** — CRM audit, pipeline forecasting, and process compliance agent
- [ ] **Phase 17: Sales Agent Voice Capability** — Voice call pipeline with Vapi/Deepgram/ElevenLabs integration
- [ ] **Phase 18: Sales Agent Advanced Methodology** — TAS, Sandler, battlecards, and pricing negotiation
- [ ] **Phase 19: Platform Advanced Intelligence** — Cross-agent hive mind, predictive analytics, dashboards, and admin UI

## Phase Details

### Phase 9: Production Deployment
**Goal**: Sales Agent is running in production — webapp deployed, infrastructure verified, credentials configured, and end-to-end demo validated with real Skyvera data
**Depends on**: Phase 8 (v1.0 complete)
**Requirements**: PROD-01, PROD-02, PROD-03, PROD-04, PROD-05
**Success Criteria** (what must be TRUE):
  1. A user can open the Output Media webapp URL in a browser and see the avatar interface served from Vercel production
  2. The Sales Agent health endpoint responds on Cloud Run with all dependency checks passing (DB, Redis, Qdrant, LiteLLM)
  3. The Sales Agent can send a Gmail and read a Calendar event using production Google Workspace credentials
  4. The Sales Agent can create and read CRM records in the production Notion workspace
  5. A complete demo scenario runs end-to-end: meeting join with avatar, conversation capture, deal stage update, and email follow-up — all using real Skyvera data
**Plans**: 5 plans
Plans:
- [x] 09-01-PLAN.md — Code fixes: health endpoint (Qdrant + LiteLLM), config (Notion + base64 SA), NotionAdapter wiring
- [x] 09-02-PLAN.md — CI/CD pipeline: production deploy job + smoke test script
- [ ] 09-03-PLAN.md — Credential provisioning guide + developer provisions all secrets
- [ ] 09-04-PLAN.md — First production deploy + SC1/SC2 verification
- [ ] 09-05-PLAN.md — Demo guide + SC3/SC4/SC5 manual verification

### Phase 10: Solution Architect Agent
**Goal**: A Solution Architect agent exists that maps technical requirements from sales conversations, generates architecture narratives, scopes POCs, prepares technical objection responses, and integrates with the Sales Agent via handoff protocol
**Depends on**: Phase 9 (production foundation)
**Requirements**: SA-01, SA-02, SA-03, SA-04, SA-05
**Success Criteria** (what must be TRUE):
  1. Given a meeting transcript mentioning technical needs, the Solution Architect produces a structured requirements document with categorized technical requirements
  2. Given a prospect's technical stack description, the Solution Architect generates an architecture narrative showing how Skyvera integrates with their environment
  3. Given a deal scope, the Solution Architect outputs a POC plan with deliverables, timeline, resource estimates, and success criteria
  4. The Solution Architect responds to technical objections with evidence-based differentiation using product knowledge and competitor weakness data
  5. The Sales Agent can hand off a technical question to the Solution Architect and receive a structured answer back through the event bus
**Plans**: 5 plans
Plans:
- [x] 10-01-PLAN.md — Shared model extension (content types, handoff types) + SA schemas + prompts
- [x] 10-02-PLAN.md — SA agent core implementation (5 capability handlers + capabilities + package init)
- [x] 10-03-PLAN.md — Knowledge seed data (competitor analysis, architecture templates, POC templates) + seed script
- [x] 10-04-PLAN.md — Registration, main.py wiring + integration tests
- [x] 10-05-PLAN.md — Sales Agent technical question dispatch + round-trip handoff test

### Phase 11: Project Manager Agent
**Goal**: A Project Manager agent exists that creates PMBOK-compliant project plans, detects schedule risks, auto-adjusts plans on scope changes, generates status reports, and integrates with CRM
**Depends on**: Phase 9 (production foundation)
**Requirements**: PM-01, PM-02, PM-03, PM-04, PM-05
**Success Criteria** (what must be TRUE):
  1. Given agreed deal deliverables, the Project Manager produces a PMBOK-compliant project plan with WBS, milestones, and dependencies
  2. The Project Manager flags predicted schedule delays before they occur by analyzing milestone progress against the plan
  3. When a scope change is introduced, the Project Manager produces an adjusted plan showing impact on timeline and deliverables
  4. The Project Manager generates a status report and distributes it to stakeholders via email or chat
  5. Project records in the CRM are linked to opportunities, and deal stage updates when project milestones complete
**Plans**: 5 plans
Plans:
- [ ] 11-01-PLAN.md — PM Pydantic schemas (20 models), earned value module, handoff validator registration
- [ ] 11-02-PLAN.md — PM prompt templates (system prompt + 6 builders) + NotionPMAdapter for CRM operations
- [ ] 11-03-PLAN.md — ProjectManagerAgent core (6 handlers) + capabilities + scheduler + package init
- [ ] 11-04-PLAN.md — APScheduler dependency + main.py wiring + integration tests (12 tests)
- [ ] 11-05-PLAN.md — Sales Agent project trigger dispatch + round-trip handoff tests

### Phase 12: Business Analyst Agent
**Goal**: A Business Analyst agent exists that extracts requirements from conversations, performs gap analysis against product capabilities, detects contradictions, generates user stories, and produces process documentation
**Depends on**: Phase 9 (production foundation)
**Requirements**: BA-01, BA-02, BA-03, BA-04, BA-05
**Success Criteria** (what must be TRUE):
  1. Given meeting transcripts and conversation history, the Business Analyst produces a structured requirements document with categorized and prioritized requirements
  2. The Business Analyst compares stated requirements against known product capabilities and outputs a gap analysis showing coverage percentage and specific gaps
  3. When requirements contain contradictions, the Business Analyst surfaces them with specific conflict descriptions and resolution suggestions
  4. The Business Analyst converts business requirements into user stories in standard As-a / I-want / So-that format
  5. Given workflow conversations, the Business Analyst produces process documentation showing current state, future state, and delta
**Plans**: TBD

### Phase 13: Technical Account Manager Agent
**Goal**: A TAM agent exists that monitors technical health metrics per account, predicts escalation risk, generates technical advocacy communications, tracks technical relationship status, and aligns customer-product roadmaps
**Depends on**: Phase 9 (production foundation)
**Requirements**: TAM-01, TAM-02, TAM-03, TAM-04, TAM-05
**Success Criteria** (what must be TRUE):
  1. The TAM surfaces technical health anomalies per account by monitoring integration status, API usage patterns, and error rates
  2. The TAM predicts escalation risk from health trends and triggers proactive outreach communication before the customer raises an issue
  3. The TAM generates account-tailored technical communications — release notes, technical updates, and roadmap previews
  4. The TAM maintains a technical relationship profile per account showing stakeholder technical maturity, integration depth, and feature adoption
  5. The TAM identifies co-development or integration opportunities by aligning customer technical roadmap with product roadmap
**Plans**: TBD

### Phase 14: Customer Success Agent
**Goal**: A Customer Success agent exists that calculates account health scores, predicts churn risk 60+ days in advance, identifies expansion opportunities, prepares QBR materials, and tracks feature adoption
**Depends on**: Phase 9 (production foundation)
**Requirements**: CSM-01, CSM-02, CSM-03, CSM-04, CSM-05
**Success Criteria** (what must be TRUE):
  1. The Customer Success agent calculates a composite health score per account from adoption, engagement, sentiment, and support signals
  2. The Customer Success agent flags churn risk 60+ days before potential churn based on health trends and behavioral signals
  3. The Customer Success agent identifies specific expansion and upsell opportunities based on usage patterns and stated needs
  4. The Customer Success agent produces QBR materials including health summary, ROI metrics, roadmap alignment, and recommendations
  5. The Customer Success agent tracks feature adoption per account and generates targeted adoption improvement recommendations
**Plans**: TBD

### Phase 15: Collections Agent
**Goal**: A Collections agent exists that tracks AR aging, predicts payment behavior, generates adaptive collection messages, escalates per configurable policy, and surfaces payment plan options
**Depends on**: Phase 9 (production foundation)
**Requirements**: COL-01, COL-02, COL-03, COL-04, COL-05
**Success Criteria** (what must be TRUE):
  1. The Collections agent displays AR aging per account with outstanding invoices, days overdue, and amounts bucketed by aging period
  2. The Collections agent predicts payment risk per account based on payment history and account signals
  3. The Collections agent generates collection messages calibrated to payment stage, relationship value, and account importance
  4. The Collections agent escalates delinquent accounts through a configurable escalation ladder — soft reminder, firm notice, human handoff
  5. The Collections agent surfaces payment plan structuring options for accounts with genuine cash flow issues, with human approval required for terms
**Plans**: TBD

### Phase 16: Business Operations Agent
**Goal**: A BizOps agent exists that audits CRM data quality, generates pipeline forecasts, detects process breakdowns, produces pipeline analytics, and automates recurring reporting
**Depends on**: Phase 9 (production foundation)
**Requirements**: OPS-01, OPS-02, OPS-03, OPS-04, OPS-05
**Success Criteria** (what must be TRUE):
  1. The BizOps agent identifies CRM data quality issues — missing fields, stale records, and inconsistent stage/close date entries
  2. The BizOps agent generates pipeline forecasts with weighted pipeline, coverage analysis, and commit vs. best case breakdowns
  3. The BizOps agent detects process breakdowns — stalled deals, skipped stages, and methodology compliance violations — and surfaces them
  4. The BizOps agent produces pipeline analytics reports segmented by rep, region, and tenant
  5. The BizOps agent automates weekly pipeline review, monthly forecast, and quarterly business review data preparation on a recurring schedule
**Plans**: TBD

### Phase 17: Sales Agent Voice Capability
**Goal**: The Sales Agent can conduct voice calls with natural conversational flow — initiating/receiving calls via Vapi, transcribing with Deepgram, speaking with ElevenLabs, and capturing call intelligence into deal context
**Depends on**: Phase 9 (production foundation)
**Requirements**: VOICE-01, VOICE-02, VOICE-03, VOICE-04, VOICE-05
**Success Criteria** (what must be TRUE):
  1. The Sales Agent can initiate an outbound voice call and receive an inbound voice call through the Vapi orchestration layer
  2. During a voice call, spoken words are transcribed in real-time via Deepgram STT and available to the Sales Agent for response generation
  3. The Sales Agent speaks during voice calls using ElevenLabs TTS with natural-sounding voice synthesis
  4. After a voice call completes, the full transcript and extracted intelligence appear in the deal context alongside meeting and email intelligence
  5. The voice pipeline achieves less than 500ms voice-to-voice latency, enabling natural conversational back-and-forth
**Plans**: TBD

### Phase 18: Sales Agent Advanced Methodology
**Goal**: The Sales Agent executes Target Account Selling and Sandler Selling System alongside existing methodologies, uses competitive battlecards for objection handling, provides pricing negotiation guidance, and selects methodology contextually
**Depends on**: Phase 9 (production foundation), Phase 4.2 (existing methodology stack)
**Requirements**: METH-01, METH-02, METH-03, METH-04, METH-05
**Success Criteria** (what must be TRUE):
  1. The Sales Agent executes Target Account Selling — strategic account prioritization, white space analysis, and account entry strategies appear in account plans
  2. The Sales Agent executes Sandler Selling System — up-front contracts, pain funnel progression, and no-pressure closing techniques appear in deal interactions
  3. Given a competitive mention, the Sales Agent responds with evidence-based differentiation from battlecard data specific to the named competitor
  4. The Sales Agent provides pricing negotiation guidance with structured concession strategies within approved pricing bands, flagging exceptions for human approval
  5. The Sales Agent selects the optimal methodology (BANT, MEDDIC, QBS, Voss, TAS, or Sandler) based on deal context — account size, stage, buyer persona, and complexity
**Plans**: TBD

### Phase 19: Platform Advanced Intelligence
**Goal**: The platform provides cross-agent intelligence that no single agent can deliver — hive mind pattern recognition, predictive deal/churn scoring, agent performance dashboards, and a tenant admin UI for configuration
**Depends on**: Phases 10-16 (all agents exist for cross-agent analysis), Phase 14 (CSM health for churn risk), Phase 13 (TAM health for churn risk)
**Requirements**: PLAT-01, PLAT-02, PLAT-03, PLAT-04, PLAT-05
**Success Criteria** (what must be TRUE):
  1. The platform surfaces cross-agent patterns that span accounts, regions, and agent roles — e.g., "3 APAC accounts asked about feature X this week" — insights no single agent would detect
  2. Each deal has an ML-derived closure probability score based on deal signals, historical patterns, and MEDDIC completeness
  3. Each account has a churn risk score derived from CSM health signals, TAM technical health, and engagement trends
  4. A per-tenant dashboard displays agent performance metrics — emails sent, meetings attended, deals influenced, and methodology scores — for each agent role
  5. A tenant admin web interface allows tenant configuration, agent persona management, knowledge base ingestion, user provisioning, and feature flag management
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18 → 19

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Infrastructure Foundation | v1.0 | 3/3 | Complete | 2026-02-11 |
| 2. Agent Orchestration | v1.0 | 6/6 | Complete | 2026-02-11 |
| 3. Knowledge Base | v1.0 | 7/7 | Complete | 2026-02-11 |
| 4. Sales Agent Core | v1.0 | 5/5 | Complete | 2026-02-12 |
| 4.1. Agent Learning & Performance Feedback | v1.0 | 3/3 | Complete | 2026-02-12 |
| 4.2. QBS Methodology Integration | v1.0 | 4/4 | Complete | 2026-02-12 |
| 5. Deal Management | v1.0 | 6/6 | Complete | 2026-02-12 |
| 6. Meeting Capabilities | v1.0 | 6/6 | Complete | 2026-02-13 |
| 7. Intelligence & Autonomy | v1.0 | 6/6 | Complete | 2026-02-16 |
| 8. Meeting Real-Time Completion | v1.0 | 3/3 | Complete | 2026-02-22 |
| 9. Production Deployment | v2.0 | 2/5 | In progress | - |
| 10. Solution Architect Agent | v2.0 | 5/5 | Complete | 2026-02-23 |
| 11. Project Manager Agent | v2.0 | 0/5 | Not started | - |
| 12. Business Analyst Agent | v2.0 | 0/TBD | Not started | - |
| 13. Technical Account Manager Agent | v2.0 | 0/TBD | Not started | - |
| 14. Customer Success Agent | v2.0 | 0/TBD | Not started | - |
| 15. Collections Agent | v2.0 | 0/TBD | Not started | - |
| 16. Business Operations Agent | v2.0 | 0/TBD | Not started | - |
| 17. Sales Agent Voice Capability | v2.0 | 0/TBD | Not started | - |
| 18. Sales Agent Advanced Methodology | v2.0 | 0/TBD | Not started | - |
| 19. Platform Advanced Intelligence | v2.0 | 0/TBD | Not started | - |

---
*Roadmap created: 2026-02-10*
*v2.0 roadmap added: 2026-02-22*
*Last updated: 2026-02-23*
