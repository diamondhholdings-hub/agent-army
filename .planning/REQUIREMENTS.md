# Requirements: Agent Army Platform v2.0 Agent Crew

**Defined:** 2026-02-22
**Core Value:** The Sales Agent is a proven template — deploy it to production and multiply its architecture across 7 additional agent roles to deliver a complete AI-powered enterprise sales organization

## v2.0 Requirements

### Production Deployment (PROD)

- [ ] **PROD-01**: Output Media webapp is deployed to Vercel production and `MEETING_BOT_WEBAPP_URL` is configured, enabling avatar join in live Google Meet meetings
- [ ] **PROD-02**: GCP Cloud Run deployment is verified — infrastructure code deployed, health checks passing, CI/CD pipeline green
- [ ] **PROD-03**: Google Workspace production credentials configured — service account with domain-wide delegation enabling Gmail, Calendar, Meet, Chat in production
- [ ] **PROD-04**: Notion CRM production workspace configured — token and database IDs wired for bidirectional CRM sync in production
- [ ] **PROD-05**: End-to-end demo scenario validated with real Skyvera data — meeting join, avatar display, conversation capture, deal update, email follow-up

### Solution Architect Agent (SA)

- [x] **SA-01**: Solution Architect can map technical requirements from sales conversations and meeting transcripts into structured requirement documents
- [x] **SA-02**: Solution Architect can generate architecture overview narratives for proposed solutions tailored to prospect technical stack
- [x] **SA-03**: Solution Architect can scope POCs — deliverables, timeline, resource estimates, success criteria
- [x] **SA-04**: Solution Architect can prepare pre-emptive technical objection responses based on product knowledge and known competitor weaknesses
- [x] **SA-05**: Solution Architect integrates with Sales Agent handoff — receives technical questions from Sales Agent, returns answers + documentation

### Project Manager Agent (PM)

- [ ] **PM-01**: Project Manager can create PMBOK-compliant project plans from deal scope and agreed deliverables
- [ ] **PM-02**: Project Manager can detect schedule risks by analyzing milestone progress and flag predicted delays before they occur
- [ ] **PM-03**: Project Manager can auto-adjust project plans when scope changes or risks materialize, maintaining stakeholder alignment
- [ ] **PM-04**: Project Manager can generate status reports and distribute to stakeholders via email/chat
- [ ] **PM-05**: Project Manager integrates with CRM — links project records to opportunity, updates deal stage on project milestones

### Business Analyst Agent (BA)

- [x] **BA-01**: Business Analyst can extract structured requirements from meeting transcripts and conversation history
- [x] **BA-02**: Business Analyst can perform gap analysis between stated requirements and product capabilities, identifying coverage and gaps
- [x] **BA-03**: Business Analyst can detect contradictions in stated requirements and surface them for resolution
- [x] **BA-04**: Business Analyst can generate user stories from business requirements in standard format (As a / I want / So that)
- [x] **BA-05**: Business Analyst can produce process documentation from workflow conversations (current state, future state, delta)

### Technical Account Manager Agent (TAM)

- [x] **TAM-01**: TAM can monitor technical health metrics per account (integration status, API usage, error rates) and surface anomalies
- [x] **TAM-02**: TAM can predict escalation risk from health trends and trigger proactive outreach before customer raises issue
- [x] **TAM-03**: TAM can generate technical advocacy communications — release notes, technical updates, roadmap previews tailored per account
- [x] **TAM-04**: TAM tracks technical relationship status — stakeholder technical maturity, integration depth, feature adoption per account
- [x] **TAM-05**: TAM can align customer technical roadmap with product roadmap, identifying co-development or integration opportunities

### Customer Success Agent (CSM)

- [ ] **CSM-01**: Customer Success agent calculates account health scores from adoption, engagement, sentiment, and support signals
- [ ] **CSM-02**: Customer Success agent predicts churn risk 60+ days in advance based on health trends and behavioral signals
- [ ] **CSM-03**: Customer Success agent identifies expansion and upsell opportunities based on usage patterns and stated needs
- [ ] **CSM-04**: Customer Success agent prepares QBR materials — health summary, ROI metrics, roadmap alignment, recommendations
- [ ] **CSM-05**: Customer Success agent tracks feature adoption per account and generates targeted adoption improvement recommendations

### Collections Agent (COL)

- [ ] **COL-01**: Collections agent tracks AR aging per account — outstanding invoices, days overdue, amounts by aging bucket
- [ ] **COL-02**: Collections agent predicts payment behavior and risk based on payment history and account signals
- [ ] **COL-03**: Collections agent generates adaptive collection messages calibrated to payment stage, relationship, and account value
- [ ] **COL-04**: Collections agent escalates delinquent accounts per configurable escalation policy — soft reminder → firm notice → human handoff
- [ ] **COL-05**: Collections agent surfaces payment plan structuring options for accounts with genuine cash flow issues (humans approve terms)

### Business Operations / Sales Ops Agent (OPS)

- [ ] **OPS-01**: BizOps agent audits CRM data quality — identifies missing fields, stale records, inconsistent stage/close date entries
- [ ] **OPS-02**: BizOps agent generates pipeline forecasts from deal data — weighted pipeline, coverage analysis, commit vs. best case
- [ ] **OPS-03**: BizOps agent detects process breakdowns in sales workflows — stalled deals, skipped stages, methodology compliance
- [ ] **OPS-04**: BizOps agent produces pipeline analytics reports per rep, region, and tenant
- [ ] **OPS-05**: BizOps agent automates recurring reporting tasks — weekly pipeline review, monthly forecast, quarterly business review data prep

### Sales Agent — Voice Capability (VOICE)

- [ ] **VOICE-01**: Sales Agent can initiate and receive voice calls via Vapi orchestration layer
- [ ] **VOICE-02**: Voice pipeline uses Deepgram STT for real-time speech transcription during calls
- [ ] **VOICE-03**: Voice pipeline uses ElevenLabs TTS for natural-sounding Sales Agent voice synthesis
- [ ] **VOICE-04**: Voice call transcripts and intelligence are captured and integrated into deal context (same pipeline as meeting intelligence)
- [ ] **VOICE-05**: Voice pipeline achieves <500ms voice-to-voice latency for natural conversational flow

### Sales Agent — Advanced Methodology (METH)

- [ ] **METH-01**: Sales Agent executes Target Account Selling (TAS) framework — strategic account prioritization, white space analysis, account entry strategies
- [ ] **METH-02**: Sales Agent executes Sandler Selling System — up-front contracts, pain funnel, identity-level selling, no-pressure closing
- [ ] **METH-03**: Sales Agent has competitive battlecards for known competitors — handles objections with evidence-based differentiation
- [ ] **METH-04**: Sales Agent provides pricing negotiation guidance — structured concession strategies within approved pricing bands (humans approve exceptions)
- [ ] **METH-05**: Sales Agent selects methodology contextually — adds TAS/Sandler to existing BANT/MEDDIC/QBS/Voss selection logic

### Platform — Advanced Intelligence (PLAT)

- [ ] **PLAT-01**: Cross-agent hive mind detects patterns across accounts, regions, and agents — surfaces insights humans would miss (e.g., "3 APAC accounts asking about feature X this week")
- [ ] **PLAT-02**: Platform generates deal closure probability scores — ML-derived from deal signals, historical patterns, and MEDDIC completeness
- [ ] **PLAT-03**: Platform generates account churn risk scores — derived from CSM health signals, TAM technical health, and engagement trends
- [ ] **PLAT-04**: Agent performance dashboards available per tenant — metrics per agent role (emails sent, meetings attended, deals influenced, methodology scores)
- [ ] **PLAT-05**: Tenant admin UI — web interface for tenant configuration, agent persona management, knowledge base ingestion, user provisioning, and feature flags

## Future Requirements (v3.0+)

### Sales Agent — Additional Methodologies
- **METH-F01**: Challenger Sale methodology
- **METH-F02**: SPIN Selling (advanced configuration beyond current baseline)

### Platform — Multi-Region Deployment
- **INFRA-F01**: APAC edge deployment (reduce latency for APAC region)
- **INFRA-F02**: EMEA edge deployment (data residency compliance)

### Agent — Advanced Integrations
- **INT-F01**: Salesforce CRM adapter (beyond Notion adapter)
- **INT-F02**: HubSpot CRM adapter
- **INT-F03**: Slack integration for agent-to-human escalation notifications

## Out of Scope (v2.0)

| Feature | Reason |
|---------|--------|
| Human replacement | Agents augment the one human per region, not replace them |
| Real-time video deepfake | Avatar is visual placeholder, not photorealistic simulation — legal/ethical risk |
| Financial transaction processing | Collections agent identifies issues; humans process payments |
| Legal document execution | Agents draft; humans and legal team approve |
| Auto-discounting without approval | Destroys margins; pricing guidance stays within approved bands |
| Customer data cross-training | Multi-tenant isolation prevents using Skyvera data for Jigtree agents |
| Marketing automation | Pre-lead is a separate system; agents operate post-lead |
| Kafka migration | Redis Streams adequate for current scale (3 tenants) |
| Kubernetes | Cloud Run handles auto-scaling without K8s complexity overhead |
| Mobile app | Web-first platform; mobile deferred indefinitely |
| Automatic contract signing | Legal approval required; humans sign |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PROD-01 | Phase 9 | Pending |
| PROD-02 | Phase 9 | Pending |
| PROD-03 | Phase 9 | Pending |
| PROD-04 | Phase 9 | Pending |
| PROD-05 | Phase 9 | Pending |
| SA-01 | Phase 10 | Complete |
| SA-02 | Phase 10 | Complete |
| SA-03 | Phase 10 | Complete |
| SA-04 | Phase 10 | Complete |
| SA-05 | Phase 10 | Complete |
| PM-01 | Phase 11 | Complete |
| PM-02 | Phase 11 | Complete |
| PM-03 | Phase 11 | Complete |
| PM-04 | Phase 11 | Complete |
| PM-05 | Phase 11 | Complete |
| BA-01 | Phase 12 | Complete |
| BA-02 | Phase 12 | Complete |
| BA-03 | Phase 12 | Complete |
| BA-04 | Phase 12 | Complete |
| BA-05 | Phase 12 | Complete |
| TAM-01 | Phase 13 | Complete |
| TAM-02 | Phase 13 | Complete |
| TAM-03 | Phase 13 | Complete |
| TAM-04 | Phase 13 | Complete |
| TAM-05 | Phase 13 | Complete |
| CSM-01 | Phase 14 | Complete |
| CSM-02 | Phase 14 | Complete |
| CSM-03 | Phase 14 | Complete |
| CSM-04 | Phase 14 | Complete |
| CSM-05 | Phase 14 | Complete |
| COL-01 | Phase 15 | Pending |
| COL-02 | Phase 15 | Pending |
| COL-03 | Phase 15 | Pending |
| COL-04 | Phase 15 | Pending |
| COL-05 | Phase 15 | Pending |
| OPS-01 | Phase 16 | Pending |
| OPS-02 | Phase 16 | Pending |
| OPS-03 | Phase 16 | Pending |
| OPS-04 | Phase 16 | Pending |
| OPS-05 | Phase 16 | Pending |
| VOICE-01 | Phase 17 | Pending |
| VOICE-02 | Phase 17 | Pending |
| VOICE-03 | Phase 17 | Pending |
| VOICE-04 | Phase 17 | Pending |
| VOICE-05 | Phase 17 | Pending |
| METH-01 | Phase 18 | Pending |
| METH-02 | Phase 18 | Pending |
| METH-03 | Phase 18 | Pending |
| METH-04 | Phase 18 | Pending |
| METH-05 | Phase 18 | Pending |
| PLAT-01 | Phase 19 | Pending |
| PLAT-02 | Phase 19 | Pending |
| PLAT-03 | Phase 19 | Pending |
| PLAT-04 | Phase 19 | Pending |
| PLAT-05 | Phase 19 | Pending |

**Coverage:**
- v2.0 requirements: 55 total
- Mapped to phases: 55
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-22*
*Last updated: 2026-02-22 after v2.0 milestone start*
