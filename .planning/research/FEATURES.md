# Feature Research: Agent Army Platform

**Domain:** Enterprise AI Sales Organization Platform (8 specialized agent roles)
**Researched:** 2026-02-10
**Confidence:** MEDIUM (domain knowledge is HIGH from multiple sources; specific implementation patterns for multi-agent sales crews are LOW -- this category is emerging and few production references exist)

---

## Top 1% Benchmark Definition

Before mapping features, we need to define what "top 1% performance" means for each role. An AI agent performing at top 1% does not mean "automates the average." It means the agent consistently exhibits behaviors that only the best humans exhibit -- the ones who get promoted, win President's Club, retain 99% of accounts, or close complex enterprise deals in half the typical cycle time.

**Universal top-1% traits (all 8 roles):**
- Proactive, not reactive -- identifies next actions before being asked
- Context-rich -- never asks a question the data already answers
- Methodology-disciplined -- follows frameworks consistently (humans drift)
- Stakeholder-aware -- adapts communication to audience (IC vs C-suite)
- Pattern recognition -- spots trends across accounts/deals/projects humans miss
- Self-correcting -- detects when an approach is failing and adjusts strategy
- Relentlessly follows up -- nothing falls through the cracks

**Role-specific top-1% benchmarks:**

| Role | Top 1% Human Benchmark | AI Agent Must Match/Exceed |
|------|------------------------|---------------------------|
| Sales Agent | 3x quota, 40%+ win rate, <90 day avg cycle | Execute 5+ methodologies flawlessly, never miss follow-up, perfect meeting prep |
| Solution Architect | Zero failed POCs, 95%+ technical win rate | Map any product to customer architecture, generate demo environments, pre-answer objections |
| Project Manager | 95%+ on-time delivery, zero scope surprises | Predict delays before they happen, auto-adjust plans, stakeholder-aware reporting |
| Business Analyst | Requirements captured in 1 pass, zero rework from ambiguity | Extract requirements from unstructured conversations, detect contradictions, gap analysis |
| TAM | 99% retention on assigned accounts, NPS >70 | Predict escalations before they happen, maintain technical relationship map, proactive optimization |
| Customer Success | Net revenue retention >120%, zero surprise churn | Detect churn signals 60+ days early, identify expansion opportunities, automate health scoring |
| Collections | DSO <30, 98%+ collection rate | Predict payment behavior, adaptive dunning, early intervention on at-risk accounts |
| Ops Agent | Zero data quality issues, pipeline accuracy >95% | Detect process breakdowns, auto-correct CRM hygiene, real-time forecasting |

---

## Part 1: Platform-Wide Features (Shared Infrastructure)

These features are required by all 8 agents and should be built as shared platform capabilities.

### Table Stakes (Platform)

| # | Feature | Why Expected | Complexity | Dependencies | Notes |
|---|---------|--------------|------------|--------------|-------|
| P-1 | **Multi-tenant isolation** | Skyvera/Jigtree/Totogi must not leak data | HIGH | None (foundational) | Tenant-scoped everything: knowledge base, CRM data, agent config, conversation history |
| P-2 | **Multi-region behavior customization** | APAC/EMEA/Americas have different sales cultures, legal requirements, business hours | MEDIUM | P-1 | Time zones, language nuances, cultural communication norms, regional pricing |
| P-3 | **GSuite integration (Gmail, Calendar, Meet, Chat)** | Core communication channel for all agents | HIGH | None | OAuth2, real-time event processing, send/receive/attend capabilities |
| P-4 | **Knowledge base architecture** | Agents need product/region/tenant-specific knowledge | HIGH | P-1 | Vector DB with hierarchical scoping: global > tenant > region > product > account |
| P-5 | **Agent-to-agent communication** | 8 agents must hand off work (SA needs context from Sales, CS needs context from PM) | HIGH | None (foundational) | Shared context protocol, structured handoff messages, escalation chains |
| P-6 | **CRM integration** | All agents read/write deal, account, contact data | MEDIUM | P-1 | Abstract CRM layer -- CRM type TBD per PROJECT.md |
| P-7 | **Conversation memory (per-account, per-deal)** | Agents must remember prior interactions across channels | HIGH | P-4 | Cross-channel: email threads + meeting transcripts + chat = unified context |
| P-8 | **Persona adaptation (IC/Manager/Exec/C-suite)** | Enterprise deals involve multiple stakeholder levels | MEDIUM | P-4 | Vocabulary, detail level, strategic framing all change by persona |
| P-9 | **Audit trail and explainability** | Enterprise buyers and internal compliance require it | MEDIUM | None | Every agent action logged with reasoning, reviewable by human |
| P-10 | **Human-in-the-loop escalation** | Agent must know when to defer to the human (1 per region) | LOW | P-5 | Configurable escalation rules: confidence thresholds, deal size, customer tier |

### Differentiators (Platform)

| # | Feature | Value Proposition | Complexity | Dependencies | Notes |
|---|---------|-------------------|------------|--------------|-------|
| P-11 | **Agent cloning with persona overlay** | One sales agent template, cloned per rep with different personality/style | HIGH | P-1 | Persona = tone + methodology preference + risk tolerance + communication style |
| P-12 | **Cross-agent pattern recognition** | Spots trends humans miss (e.g., "3 accounts in APAC asking about feature X") | HIGH | P-4, P-5, P-7 | This is the "hive mind" advantage -- no human sales org can do this |
| P-13 | **Multi-product extensibility** | New ESW acquisition = new product knowledge without re-architecture | MEDIUM | P-4 | Product knowledge as pluggable modules in knowledge base |
| P-14 | **Real-time methodology coaching** | Agent doesn't just execute methodology -- it explains what it's doing and why | MEDIUM | None | Transparency builds trust with the human rep it supports |
| P-15 | **Unified customer 360** | Every agent sees full picture: sales status + technical health + CS sentiment + AR status | HIGH | P-5, P-6, P-7 | This is what makes the "crew" more than 8 independent agents |

### Anti-Features (Platform)

| # | Anti-Feature | Why Avoid | What to Do Instead |
|---|-------------|-----------|-------------------|
| P-A1 | **Full autonomy without human approval on high-stakes actions** | Enterprise deals are high-value; one bad email to a C-suite can destroy a relationship | Configurable approval gates: auto-approve routine, require approval for high-stakes (contract terms, pricing, executive communication) |
| P-A2 | **Real-time deepfake video generation for meeting avatars** | Legal/ethical minefield, uncanny valley, trust-destroying if detected | Static avatar with voice capability, clearly identified as AI assistant |
| P-A3 | **Financial transaction processing** | Liability, compliance, regulatory scope explosion | Collections agent identifies issues and recommends actions; humans execute payments |
| P-A4 | **Replacing the human entirely** | The value prop is augmentation, not replacement; 1 human + 8 agents > 9 average humans | Agent defers to human for judgment calls, relationship moments, final approvals |
| P-A5 | **Building a custom CRM** | Massive scope creep; CRM is a commodity | Integrate with existing CRMs (Salesforce, HubSpot, etc.) via abstraction layer |
| P-A6 | **"AI-powered everything" feature bloat** | Shipping 80 mediocre features instead of 8 excellent ones | Each agent does its role at top 1% level. Depth over breadth. |

---

## Part 2: Sales Agent Features (Build First)

The Sales Agent is the template for all other agents. Its architecture must be generalizable.

### Table Stakes (Sales Agent)

| # | Feature | Why Expected | Complexity | Dependencies | Notes |
|---|---------|--------------|------------|--------------|-------|
| S-1 | **Meeting preparation briefings** | Top reps always prep; AI must generate pre-meeting dossiers automatically | MEDIUM | P-3, P-4, P-6, P-7 | Account context, attendee profiles, recent interactions, deal status, talk track recommendations, likely objections |
| S-2 | **Meeting attendance with avatar** | Core differentiator in PROJECT.md; agent must be "in the room" | HIGH | P-3 | Google Meet integration, avatar display, real-time transcription, contextual note-taking. NOT deepfake video -- static visual + voice |
| S-3 | **Meeting minutes and distribution** | Every meeting should produce structured output within minutes | MEDIUM | S-2, P-3 | Auto-detect action items, commitments, next steps. Distribute to relevant stakeholders per role |
| S-4 | **Email composition and sending** | Sales agents send hundreds of emails; context-aware drafting is table stakes | MEDIUM | P-3, P-7, P-8 | Must match persona level (IC gets technical detail, exec gets strategic summary) |
| S-5 | **Opportunity qualification (BANT)** | Basic qualification framework every B2B sales tool supports | MEDIUM | P-6 | Budget, Authority, Need, Timeline scoring from conversation signals |
| S-6 | **CRM data entry and maintenance** | Reps hate CRM updates; agent must auto-log all interactions | LOW | P-6 | Auto-capture from emails, meetings, chats. Structured CRM field updates |
| S-7 | **Follow-up tracking and execution** | Missed follow-ups kill deals; agent must track every commitment | LOW | P-3, P-6, P-7 | Calendar-aware: schedule follow-ups, send reminders, escalate if overdue |
| S-8 | **Product knowledge retrieval** | Agent must answer product questions accurately in real-time | MEDIUM | P-4 | Deep product knowledge for Skyvera offerings: features, pricing, positioning, competitive differentiation |
| S-9 | **Deal stage tracking** | Must know where every opportunity sits in the pipeline | LOW | P-6 | Auto-advance stages based on qualification criteria met |
| S-10 | **Low-latency response for live interactions** | In meetings and calls, delay = loss of credibility | HIGH | S-2 | Sub-second response for meeting participation; pre-computation of likely questions |

### Differentiators (Sales Agent)

| # | Feature | Value Proposition | Complexity | Dependencies | Notes |
|---|---------|-------------------|------------|--------------|-------|
| S-11 | **MEDDIC/MEDDPICC execution** | The dominant enterprise qualification framework. 73% of SaaS companies >$100K ARR use it. Top 1% means MEDDIC mastery | HIGH | S-5, P-6, P-7 | Metrics, Economic Buyer, Decision Criteria, Decision Process, Identify Pain, Champion, Competition. Agent must track all 7 dimensions across every deal |
| S-12 | **Target Account Selling (TAS) execution** | Methodology for large enterprise accounts with long cycles. Research-intensive. Perfect for AI | HIGH | P-4, P-6 | Automated account intelligence gathering, strategic account planning, territory alignment |
| S-13 | **Chris Voss negotiation techniques** | Tactical empathy, calibrated questions, labeling, mirroring, accusation audits. Transforms negotiation from confrontational to collaborative | HIGH | P-7, P-8 | Agent must detect negotiation moments and apply appropriate technique. Labels emotions ("It seems like you're concerned about..."), uses calibrated questions ("How am I supposed to do that?"), deploys late-night FM DJ voice in appropriate contexts |
| S-14 | **Sandler selling methodology** | Pain funnel execution: surface pain -> business impact -> personal impact. Consultative, not pushy | HIGH | P-7, P-8 | Three levels of pain discovery. Agent guides conversations through the funnel without feeling mechanical |
| S-15 | **Political mapping in enterprise accounts** | Understanding who has power, who influences, who champions, who blocks. Top 1% reps always map the org | HIGH | P-6, P-7 | Build and maintain org charts with roles: Decision Maker, Economic Buyer, Champion, Coach, Blocker. Track influence relationships and engagement history |
| S-16 | **Account planning** | Strategic plans for named accounts: whitespace analysis, expansion opportunities, risk assessment | MEDIUM | P-4, P-6, S-15 | Auto-generated account plans updated after every interaction. Include competitive threats, stakeholder sentiment, revenue potential |
| S-17 | **Opportunity planning** | Deal-specific strategy: win themes, competitive positioning, proof points needed, resource plan | MEDIUM | S-11, S-15, P-6 | Living document that evolves with the deal. Maps to MEDDIC dimensions |
| S-18 | **Data consolidation across touchpoints** | Unify signals from email, meetings, chat, CRM into coherent deal narrative | HIGH | P-7, P-3, P-6 | "What's really happening in this deal?" -- synthesize 50 interactions into a 1-paragraph deal summary |
| S-19 | **Self-directed goal pursuit** | Agent doesn't wait for instructions. Sets its own priorities based on: $ identified, $ sold, avg deal time, closing rate | HIGH | P-6, all S-features | This is the "top 1%" differentiator. Agent wakes up, reviews pipeline, identifies highest-impact actions, executes. Reports results, not just activity |
| S-20 | **Multi-methodology selection** | Agent picks the right methodology for the situation: BANT for simple qualification, MEDDIC for complex deals, Sandler for pain discovery, Chris Voss for negotiation, TAS for named accounts | HIGH | S-5, S-11, S-12, S-13, S-14 | Context-dependent methodology switching. No single framework works for all situations. Top 1% reps switch fluently |
| S-21 | **Competitive intelligence** | Know competitor positioning, pricing, weaknesses in real-time. Prep counter-arguments before they're needed | MEDIUM | P-4 | Competitive battle cards auto-generated and updated. Objection handling playbooks per competitor |
| S-22 | **Geographic and cultural adaptation** | APAC relationship-first selling vs Americas direct approach vs EMEA consensus-driven buying | MEDIUM | P-2, P-8 | Not just language -- selling rhythm, relationship expectations, decision-making patterns per region |
| S-23 | **Voice call capability** | Some interactions require phone presence; optional but powerful | HIGH | P-3 | Real-time voice with low latency, natural conversation flow. Marked as optional in PROJECT.md |

### Anti-Features (Sales Agent)

| # | Anti-Feature | Why Avoid | What to Do Instead |
|---|-------------|-----------|-------------------|
| S-A1 | **Aggressive cold outreach automation** | Spam destroys brand. Top 1% reps are targeted and strategic, not volume-based | Qualify targets with TAS methodology, send personalized high-value outreach to researched accounts |
| S-A2 | **Hiding AI identity in meetings** | Trust-destroying when discovered (and it will be discovered). Violates regulations in many jurisdictions | Clearly identify as AI sales assistant. The avatar and capability should be impressive enough to be a feature, not hidden |
| S-A3 | **Rigid scripted conversations** | Humans detect scripts instantly. Kills credibility | Methodology-guided conversations with natural language generation. Framework provides structure, not a script |
| S-A4 | **Auto-discounting without approval** | Destroys margins, trains buyers to wait | Agent can identify when discount might be appropriate and recommend to human. Never auto-approve price changes |
| S-A5 | **Over-promising on product capabilities** | Short-term win, long-term churn and reputation damage | Agent is bounded by product knowledge base. Cannot claim features that don't exist. Flags feature gaps to SA/PM |

---

## Part 3: Solution Architect Agent Features

### Table Stakes (Solution Architect)

| # | Feature | Why Expected | Complexity | Dependencies | Notes |
|---|---------|--------------|------------|--------------|-------|
| SA-1 | **Technical requirement mapping** | Map customer needs to product capabilities | MEDIUM | P-4, P-5 | Receive deal context from Sales Agent, map to technical architecture |
| SA-2 | **Architecture diagram generation** | Visual representation of proposed solutions | MEDIUM | P-4 | Auto-generate based on customer requirements and product modules |
| SA-3 | **Technical objection handling** | Pre-answer "can your product do X?" questions | MEDIUM | P-4 | Knowledge base of product capabilities, limitations, and workarounds |
| SA-4 | **POC/demo scoping** | Define what a proof-of-concept should prove | LOW | P-5 (handoff from Sales) | Scope POCs to customer's specific pain points, not generic demos |
| SA-5 | **Integration assessment** | Evaluate how product fits customer's existing tech stack | MEDIUM | P-4 | API compatibility, data migration complexity, security requirements |
| SA-6 | **Technical documentation delivery** | Provide relevant technical docs to customer | LOW | P-4 | Context-aware: send the docs that matter for their use case |

### Differentiators (Solution Architect)

| # | Feature | Value Proposition | Complexity | Dependencies | Notes |
|---|---------|-------------------|------------|--------------|-------|
| SA-7 | **Pre-emptive objection preparation** | Before a technical meeting, predict and prepare for every objection | HIGH | P-7, SA-3 | Analyze customer's tech stack, industry, past objections from similar deals |
| SA-8 | **Competitive technical differentation** | Know competitor architectures and articulate why ours is better for this customer | HIGH | P-4, S-21 | Not generic "we're better" -- specific to customer's architecture and requirements |
| SA-9 | **Real-time technical Q&A in meetings** | Answer deep technical questions live during customer calls | HIGH | S-2, P-4, P-10 | Requires sub-second retrieval from knowledge base + ability to synthesize |
| SA-10 | **Custom demo environment provisioning** | Spin up tailored demo environments matching customer's scenario | HIGH | P-4 | Integration with product deployment systems. Per-customer configuration |

---

## Part 4: Project Manager Agent Features

### Table Stakes (Project Manager)

| # | Feature | Why Expected | Complexity | Dependencies | Notes |
|---|---------|--------------|------------|--------------|-------|
| PM-1 | **Project plan creation and maintenance** | PMBOK-aligned project plans from requirements | MEDIUM | P-5 | WBS, milestones, dependencies, resource assignments |
| PM-2 | **Status reporting** | Regular status reports to stakeholders | LOW | P-3, P-5 | Auto-generated from task completion data, risk register, issue log |
| PM-3 | **Risk identification and tracking** | Proactive risk management | MEDIUM | P-7 | Scan project signals for emerging risks, maintain risk register |
| PM-4 | **Meeting facilitation (standups, reviews)** | Run regular project ceremonies | MEDIUM | S-2, P-3 | Prep agendas, run meetings, capture actions, track completion |
| PM-5 | **Timeline management and deadline tracking** | Track every deliverable against committed dates | LOW | P-6 | Automated alerts for approaching deadlines, auto-escalation on slippage |
| PM-6 | **Stakeholder communication** | Right information to right stakeholder at right time | MEDIUM | P-8 | Exec summary for sponsors, detail for team leads, action items for doers |

### Differentiators (Project Manager)

| # | Feature | Value Proposition | Complexity | Dependencies | Notes |
|---|---------|-------------------|------------|--------------|-------|
| PM-7 | **Predictive delay detection** | Identify projects that will slip BEFORE they slip | HIGH | P-7, PM-3 | Analyze velocity, dependency chains, resource bottlenecks. Alert 2+ weeks before deadline miss |
| PM-8 | **Auto-adjusting plans** | When scope changes, auto-rebalance timeline and resources | HIGH | PM-1, PM-7 | What-if scenario modeling. "If we add this requirement, delivery moves from March to April" |
| PM-9 | **Cross-project resource optimization** | Balance resources across multiple simultaneous projects | HIGH | PM-1, P-1 | Multi-tenant consideration: resources shared across business units |

---

## Part 5: Business Analyst Agent Features

### Table Stakes (Business Analyst)

| # | Feature | Why Expected | Complexity | Dependencies | Notes |
|---|---------|--------------|------------|--------------|-------|
| BA-1 | **Requirements extraction from conversations** | Turn unstructured discussions into structured requirements | MEDIUM | P-7, S-2 | Parse meeting transcripts, emails, chat for requirements statements |
| BA-2 | **Requirements documentation** | Produce formal requirements documents (BRD, FRD) | MEDIUM | BA-1 | Templates per document type, auto-populated from extracted requirements |
| BA-3 | **Gap analysis** | Identify gaps between customer needs and product capabilities | MEDIUM | P-4, BA-1 | Cross-reference requirements against product knowledge base |
| BA-4 | **User story creation** | Translate requirements into development-ready user stories | LOW | BA-1 | Acceptance criteria, definition of done, priority suggestion |
| BA-5 | **Stakeholder requirements traceability** | Track which stakeholder requested which requirement | LOW | BA-1, P-7 | Critical for managing conflicting requirements |

### Differentiators (Business Analyst)

| # | Feature | Value Proposition | Complexity | Dependencies | Notes |
|---|---------|-------------------|------------|--------------|-------|
| BA-6 | **Contradiction detection** | Spot contradictory requirements across stakeholders | HIGH | BA-1, BA-5 | "Stakeholder A says the system must be real-time; Stakeholder B says batch processing is fine" |
| BA-7 | **Requirements impact analysis** | When a requirement changes, show downstream effects | HIGH | BA-1, PM-1 | Connect requirements to design, development, testing artifacts |
| BA-8 | **Cross-deal pattern analysis** | Identify requirements patterns across multiple customers | HIGH | P-12, BA-1 | "5 customers in financial services all need feature X" -- feeds product roadmap |

---

## Part 6: Technical Account Manager (TAM) Agent Features

### Table Stakes (TAM)

| # | Feature | Why Expected | Complexity | Dependencies | Notes |
|---|---------|--------------|------------|--------------|-------|
| TAM-1 | **Technical health monitoring** | Track product adoption, performance, issues per account | MEDIUM | P-6, P-4 | Integration with product telemetry, support tickets, monitoring |
| TAM-2 | **Escalation management** | Route and track technical escalations | MEDIUM | P-5, P-3 | Severity classification, SLA tracking, stakeholder notification |
| TAM-3 | **Technical relationship mapping** | Know who the technical stakeholders are at each account | LOW | S-15, P-6 | Subset of political map focused on technical decision-makers |
| TAM-4 | **Proactive optimization recommendations** | Identify ways customer can get more value from product | MEDIUM | P-4, TAM-1 | Usage pattern analysis, underutilized features, configuration improvements |
| TAM-5 | **Quarterly business review (QBR) preparation** | Prepare comprehensive technical QBR presentations | MEDIUM | TAM-1, P-7 | Metrics, achievements, recommendations, roadmap alignment |

### Differentiators (TAM)

| # | Feature | Value Proposition | Complexity | Dependencies | Notes |
|---|---------|-------------------|------------|--------------|-------|
| TAM-6 | **Predictive escalation prevention** | Detect issues before customer notices them | HIGH | TAM-1 | Anomaly detection on product usage, performance, support ticket velocity |
| TAM-7 | **Technical advocacy automation** | Route customer needs to engineering, track resolution | HIGH | P-5, TAM-2 | Bridge between customer and product team. Track feature requests through to delivery |
| TAM-8 | **Cross-account technical intelligence** | "3 accounts on v2.1 hit the same bug" -- proactive outreach | HIGH | P-12, TAM-1 | Hive-mind advantage: detect patterns across all managed accounts simultaneously |

---

## Part 7: Customer Success Agent Features

### Table Stakes (Customer Success)

| # | Feature | Why Expected | Complexity | Dependencies | Notes |
|---|---------|--------------|------------|--------------|-------|
| CS-1 | **Health score calculation** | Multi-signal account health: usage, support tickets, sentiment, engagement | MEDIUM | P-6, P-7 | Configurable weights per metric. Visual dashboard per account |
| CS-2 | **Churn risk identification** | Flag accounts showing churn signals | MEDIUM | CS-1 | Declining usage, increasing complaints, champion departure, contract approaching end |
| CS-3 | **Onboarding tracking** | Ensure new customers complete onboarding milestones | LOW | P-6 | Checklist-based, milestone-driven, auto-remind |
| CS-4 | **Renewal management** | Track and prepare for renewals well ahead of expiry | MEDIUM | P-6, CS-1 | 90-day, 60-day, 30-day renewal workflows |
| CS-5 | **Customer communication cadence** | Regular touchpoints based on tier and health | LOW | P-3, CS-1 | High-touch for at-risk, low-touch for healthy. Auto-adjust |

### Differentiators (Customer Success)

| # | Feature | Value Proposition | Complexity | Dependencies | Notes |
|---|---------|-------------------|------------|--------------|-------|
| CS-6 | **60+ day churn prediction** | Detect churn signals before conventional metrics show problems | HIGH | CS-1, P-12 | Sentiment analysis on interactions, behavioral pattern changes, competitive signals |
| CS-7 | **Expansion opportunity identification** | Identify upsell/cross-sell opportunities from usage and conversation data | MEDIUM | CS-1, P-7, P-4 | "Customer is using 90% of capacity" or "Customer mentioned need for feature in adjacent product" |
| CS-8 | **Innovation identification** | Spot when customers find novel uses for the product | MEDIUM | P-7, TAM-1 | Use cases that could inform product roadmap or marketing |
| CS-9 | **Net revenue retention optimization** | Proactive strategy to hit >120% NRR target | HIGH | CS-6, CS-7, CS-4 | Combine retention (prevent churn) + expansion (grow accounts) into unified strategy |

---

## Part 8: Collections Agent Features

### Table Stakes (Collections)

| # | Feature | Why Expected | Complexity | Dependencies | Notes |
|---|---------|--------------|------------|--------------|-------|
| CO-1 | **AR aging tracking** | Track invoices by aging bucket (current, 30, 60, 90, 90+) | LOW | P-6 | Integration with billing/ERP system |
| CO-2 | **Automated dunning sequences** | Multi-step collection outreach based on aging | MEDIUM | P-3, CO-1 | Configurable timing, escalation steps, tone progression (friendly -> firm -> formal) |
| CO-3 | **Payment status tracking** | Real-time view of payment status per invoice, per account | LOW | P-6 | Integration with payment systems and bank feeds |
| CO-4 | **Dispute management** | Track and manage payment disputes | MEDIUM | P-3, CO-1 | Categorize disputes, route to correct resolver, track resolution |
| CO-5 | **Collection priority ranking** | Prioritize which accounts to collect from first | MEDIUM | CO-1 | By amount, aging, payment history, account value |

### Differentiators (Collections)

| # | Feature | Value Proposition | Complexity | Dependencies | Notes |
|---|---------|-------------------|------------|--------------|-------|
| CO-6 | **Payment behavior prediction** | Predict when an invoice will be paid based on historical patterns | HIGH | CO-1, CO-3 | ML model on payment history, communication patterns, external signals |
| CO-7 | **Adaptive collection messaging** | Adjust tone and approach based on customer behavior and relationship status | MEDIUM | P-7, P-8, CO-2 | Cross-reference with CS health score -- don't threaten a strategic account |
| CO-8 | **Early intervention on at-risk receivables** | Flag collection risk before invoice goes overdue | HIGH | CO-6, CS-1 | Proactive outreach: "Your invoice is due in 5 days, here's how to pay" |
| CO-9 | **DSO optimization strategy** | Continuously optimize Days Sales Outstanding across the portfolio | HIGH | CO-1, CO-6 | Agent sets its own collection strategy to minimize DSO. Self-directed goal pursuit for collections |

---

## Part 9: Business Operations / Sales Ops Agent Features

### Table Stakes (Ops Agent)

| # | Feature | Why Expected | Complexity | Dependencies | Notes |
|---|---------|--------------|------------|--------------|-------|
| OPS-1 | **CRM data quality management** | Clean, complete, consistent CRM data | MEDIUM | P-6 | Detect duplicates, missing fields, stale data. Auto-correct where possible |
| OPS-2 | **Pipeline reporting** | Accurate pipeline views by stage, region, product, rep | LOW | P-6 | Real-time dashboards, automated report distribution |
| OPS-3 | **Forecast generation** | Revenue forecasting by period | MEDIUM | P-6, OPS-1 | Weighted pipeline, historical conversion rates, trend analysis |
| OPS-4 | **Process compliance monitoring** | Ensure sales process steps are followed | MEDIUM | P-6 | Detect when deals skip stages, miss required fields, lack next steps |
| OPS-5 | **Territory and quota management** | Track territory assignments and quota attainment | LOW | P-6, P-2 | By region, by product, by rep. Auto-calculate attainment |

### Differentiators (Ops Agent)

| # | Feature | Value Proposition | Complexity | Dependencies | Notes |
|---|---------|-------------------|------------|--------------|-------|
| OPS-6 | **Forecast accuracy optimization** | Self-improving forecasting model that gets more accurate over time | HIGH | OPS-3 | Track forecast vs actual, identify systematic biases, adjust methodology |
| OPS-7 | **Process breakdown detection** | Identify where in the sales process deals are failing and why | HIGH | OPS-4, P-12 | "40% of APAC deals stall at technical validation -- SA coverage may be insufficient" |
| OPS-8 | **Real-time revenue intelligence** | Live view of revenue trajectory with automated course-correction recommendations | HIGH | OPS-3, P-15 | Not just "we'll miss the quarter" but "here are 3 deals that could close with these specific actions" |
| OPS-9 | **Cross-team workflow automation** | Automate handoffs between Sales, SA, PM, CS, Collections | HIGH | P-5 | Define and enforce workflow rules: "When deal closes, auto-trigger PM project kickoff and CS onboarding" |

---

## Feature Dependencies

```
[Platform Foundation]
    P-1 (Multi-tenant) ──foundational──> ALL features
    P-4 (Knowledge base) ──foundational──> ALL product knowledge features
    P-3 (GSuite) ──foundational──> ALL communication features
    P-5 (Agent-to-agent) ──foundational──> ALL cross-agent features
    P-6 (CRM integration) ──foundational──> ALL deal/account features

[Sales Agent Core Path]
    P-3 ──requires──> S-4 (Email)
    P-3 ──requires──> S-2 (Meeting attendance)
    S-2 ──requires──> S-3 (Meeting minutes)
    P-4 ──requires──> S-8 (Product knowledge)
    P-6 ──requires──> S-5 (BANT qualification)
    P-6 ──requires──> S-6 (CRM entry)
    P-7 ──requires──> S-1 (Meeting prep)

[Sales Agent Differentiation Path]
    S-5 ──requires──> S-11 (MEDDIC) [BANT is simpler subset]
    P-6 + P-4 ──requires──> S-12 (TAS)
    P-7 + P-8 ──requires──> S-13 (Chris Voss)
    P-7 + P-8 ──requires──> S-14 (Sandler)
    P-6 + P-7 ──requires──> S-15 (Political mapping)
    S-15 ──requires──> S-16 (Account planning)
    S-11 + S-15 ──requires──> S-17 (Opportunity planning)
    All S-features ──requires──> S-19 (Self-directed goal pursuit) [capstone]
    S-5 + S-11..S-14 ──requires──> S-20 (Multi-methodology selection) [capstone]

[Cross-Agent Dependencies]
    S-15 (Political mapping) ──feeds──> TAM-3 (Technical relationship mapping)
    CS-1 (Health score) ──feeds──> CO-7 (Adaptive collection messaging)
    S-18 (Data consolidation) ──feeds──> P-15 (Customer 360)
    OPS-9 (Workflow automation) ──requires──> P-5 (Agent-to-agent communication)
    BA-1 (Requirements extraction) ──requires──> S-2 (Meeting attendance) [uses transcripts]
    PM-1 (Project plans) ──triggered-by──> Sales deal close
    CS-3 (Onboarding) ──triggered-by──> Sales deal close
```

### Dependency Notes

- **P-1 (Multi-tenant) is the true foundation:** Without tenant isolation, nothing else can safely be built. This must be the absolute first infrastructure work.
- **P-3 (GSuite) is the interaction foundation:** Sales agents that can't send email or attend meetings are useless. This is the first integration to build.
- **S-5 (BANT) before S-11 (MEDDIC):** BANT is a simpler qualification subset. Build BANT first, then extend to MEDDIC's 7 dimensions.
- **S-19 (Self-directed goal pursuit) is the capstone:** It requires almost every other Sales Agent feature to be functional. This is what makes the agent "top 1%." Build last, but design for it from the start.
- **P-12 (Cross-agent pattern recognition) enables the "hive mind":** Features TAM-8, BA-8, CS-6, OPS-7 all depend on this platform capability.

---

## MVP Definition

### Launch With (v1) -- Sales Agent Only

Minimum viable product that proves the platform architecture works.

- [ ] P-1 (Multi-tenant isolation) -- foundational for Skyvera, needed before Jigtree/Totogi
- [ ] P-3 (GSuite integration) -- email + calendar + Meet
- [ ] P-4 (Knowledge base) -- Skyvera product knowledge
- [ ] P-6 (CRM integration) -- read/write deal data
- [ ] P-7 (Conversation memory) -- cross-channel context
- [ ] S-1 (Meeting prep briefings) -- high-visibility, immediate value
- [ ] S-2 (Meeting attendance with avatar) -- the "wow" demo moment
- [ ] S-3 (Meeting minutes and distribution) -- immediate daily utility
- [ ] S-4 (Email composition) -- core communication
- [ ] S-5 (BANT qualification) -- basic deal qualification
- [ ] S-6 (CRM data entry) -- eliminate drudge work
- [ ] S-7 (Follow-up tracking) -- never miss a follow-up
- [ ] S-8 (Product knowledge) -- Skyvera deep knowledge
- [ ] P-8 (Persona adaptation) -- basic IC/exec differentiation
- [ ] P-10 (Human escalation) -- safety net for the one human per region

### Add After Validation (v1.x) -- Sales Agent Differentiation

Once core is working and generating value:

- [ ] S-11 (MEDDIC) -- when deal complexity demands deeper qualification
- [ ] S-15 (Political mapping) -- when enterprise account complexity becomes apparent
- [ ] S-16 (Account planning) -- when managing 10+ active accounts
- [ ] S-18 (Data consolidation) -- when information volume exceeds human processing
- [ ] S-21 (Competitive intelligence) -- when competitive displacement deals appear
- [ ] P-5 (Agent-to-agent communication) -- when other agents begin development
- [ ] P-2 (Regional customization) -- when second region activates

### Future Consideration (v2+) -- Full Agent Army

Defer until Sales Agent reaches 80%+ production quality:

- [ ] S-12, S-13, S-14 (TAS, Chris Voss, Sandler) -- advanced methodologies
- [ ] S-19 (Self-directed goal pursuit) -- capstone feature
- [ ] S-20 (Multi-methodology selection) -- requires all methodologies built
- [ ] S-23 (Voice calls) -- marked optional in PROJECT.md
- [ ] All SA, PM, BA, TAM, CS, CO, OPS features -- wait for platform template validation
- [ ] P-11 (Agent cloning) -- after single-agent architecture proven
- [ ] P-12 (Cross-agent pattern recognition) -- after multiple agents deployed
- [ ] P-15 (Customer 360) -- after multiple agents contributing data

---

## Feature Prioritization Matrix

| Feature | User Value | Impl. Cost | Priority | Rationale |
|---------|------------|------------|----------|-----------|
| P-1 Multi-tenant | HIGH | HIGH | **P1** | Foundational, can't ship without it |
| P-3 GSuite | HIGH | HIGH | **P1** | No communication = no agent |
| P-4 Knowledge base | HIGH | HIGH | **P1** | Agent with no knowledge is useless |
| S-1 Meeting prep | HIGH | MEDIUM | **P1** | Immediate visible value |
| S-2 Meeting attendance | HIGH | HIGH | **P1** | Core differentiator and demo anchor |
| S-3 Meeting minutes | HIGH | MEDIUM | **P1** | Daily utility, proves value fast |
| S-4 Email composition | HIGH | MEDIUM | **P1** | Core sales workflow |
| S-5 BANT qualification | HIGH | MEDIUM | **P1** | Basic deal management |
| S-6 CRM entry | HIGH | LOW | **P1** | Eliminates most-hated task |
| S-7 Follow-up tracking | HIGH | LOW | **P1** | Immediate revenue protection |
| P-6 CRM integration | HIGH | MEDIUM | **P1** | Required by S-5, S-6, S-7, S-9 |
| P-7 Conversation memory | HIGH | HIGH | **P1** | Required by S-1, S-18 |
| S-8 Product knowledge | HIGH | MEDIUM | **P1** | Can't sell without product knowledge |
| S-11 MEDDIC | HIGH | HIGH | **P2** | Differentiator but needs S-5 first |
| S-15 Political mapping | HIGH | HIGH | **P2** | Critical for enterprise but complex |
| S-16 Account planning | HIGH | MEDIUM | **P2** | Builds on S-15 |
| S-18 Data consolidation | HIGH | HIGH | **P2** | Powerful but needs data first |
| S-19 Self-directed goals | HIGH | HIGH | **P2** | Capstone -- needs everything else |
| S-12 TAS | MEDIUM | HIGH | **P3** | Named account methodology, niche |
| S-13 Chris Voss | MEDIUM | HIGH | **P3** | Negotiation refinement |
| S-14 Sandler | MEDIUM | HIGH | **P3** | Pain discovery refinement |
| S-23 Voice calls | MEDIUM | HIGH | **P3** | Optional per PROJECT.md |
| P-11 Agent cloning | MEDIUM | HIGH | **P3** | After base agent proven |
| P-12 Cross-agent patterns | HIGH | HIGH | **P3** | Needs multiple agents |

**Priority key:**
- P1: Must have for launch -- Sales Agent v1
- P2: Should have, add when Sales Agent core is working (v1.x)
- P3: Nice to have, future consideration (v2+)

---

## Competitor Feature Analysis

| Feature Area | Salesforce Agentforce | Gong | Outreach | Clari | Our Approach |
|-------------|----------------------|------|----------|-------|--------------|
| Meeting attendance | No (assists, doesn't attend) | Records/analyzes | No | No | **Agent attends meetings with avatar** -- our core differentiator |
| Methodology execution | Basic playbooks | Conversation signals mapped to methodology | Sequence-based | Forecast-focused | **Full multi-methodology engine** (BANT + MEDDIC + TAS + Voss + Sandler) |
| Political mapping | Basic org charts via AppExchange | Stakeholder mentions in calls | Contact engagement scoring | Relationship intelligence | **AI-built and maintained org power maps** with champion/blocker tracking |
| Self-directed behavior | Human-directed | Analytics only | Sequence-driven | Predictive but passive | **Autonomous goal pursuit** -- agent decides what to do next |
| Multi-role support | Single role per agent | Sales-focused only | Sales outreach only | Revenue-focused only | **8 specialized agents as a crew** with inter-agent communication |
| Meeting prep | Basic account summary | Pre-call briefs | Sequence context | Deal context | **Full dossier**: account history + attendee profiles + methodology talk tracks + likely objections |
| Cultural adaptation | Language only | No | Template localization | No | **Region-specific selling approach** (APAC relationship-first, Americas direct, EMEA consensus) |
| Data consolidation | Within Salesforce only | Call data only | Email/call data | Pipeline data | **Cross-channel synthesis**: email + meetings + chat + CRM into deal narrative |

**Key competitive insight:** No existing platform combines meeting attendance with methodology execution with multi-agent orchestration. Competitors are either analytics tools (Gong, Clari) or automation tools (Outreach, Agentforce). None are autonomous sales agents that attend meetings, execute methodology, and self-direct toward goals.

---

## Complexity Estimates Summary

| Complexity | Feature Count | Description |
|-----------|--------------|-------------|
| LOW | 14 | Straightforward CRUD, integrations with clear APIs, template-based outputs |
| MEDIUM | 31 | Significant logic, multiple integrations, requires domain knowledge |
| HIGH | 29 | Novel AI capabilities, real-time requirements, multi-system orchestration, ML models |

**Risk concentration:** The highest-value differentiators are almost all HIGH complexity. This is expected -- if they were easy, competitors would already have them. The build strategy should interleave HIGH features with LOW/MEDIUM ones to maintain momentum.

---

## Sources

- [BCG: How AI Agents Will Transform B2B Sales](https://www.bcg.com/publications/2025/how-ai-agents-will-transform-b2b-sales) -- MEDIUM confidence, strategic framing
- [Workist: Best AI Agents for Sales 2026](https://www.workist.com/en/blog/best-ai-agents-for-sales-tool-comparison-2026) -- MEDIUM confidence, competitive landscape
- [Salesforce: BANT vs MEDDIC](https://www.salesforce.com/blog/bant-vs-meddic/) -- HIGH confidence, methodology comparison
- [Gong: Sales Methodologies](https://www.gong.io/blog/sales-methodologies) -- HIGH confidence, methodology overview
- [Epicflow: AI Agents for Project Management](https://www.epicflow.com/blog/ai-agents-for-project-management/) -- MEDIUM confidence, PM agent capabilities
- [Velaris: Top AI Customer Success Tools 2026](https://www.velaris.io/articles/top-10-ai-customer-success-tools) -- MEDIUM confidence, CS feature landscape
- [Kolleno: AI Agents for AR Feature Checklist 2026](https://www.kolleno.com/ai-agents-for-accounts-receivable-feature-checklist-for-finance-teams-in-2026/) -- MEDIUM confidence, collections features
- [Matillion: AI Agents Transforming Business Analysis](https://www.matillion.com/blog/ai-agents-business-analysis) -- MEDIUM confidence, BA capabilities
- [DemandFarm: Relationship Mapping](https://www.demandfarm.com/org-chart-software/) -- HIGH confidence, political mapping tools
- [The AI Corner: Chris Voss AI Negotiation Prompts](https://www.the-ai-corner.com/p/chris-voss-ai-negotiation-prompts) -- LOW confidence, implementation approach
- [Oliv: Sandler Sales Methodology with AI](https://www.oliv.ai/blog/sandler-sales-methodology) -- MEDIUM confidence, Sandler + AI
- [Glean: The Future of RevOps](https://www.glean.com/blog/ai-in-revenue-operations) -- MEDIUM confidence, ops agent framing
- [Peterson Technology Partners: Top AI Agents 2026](https://www.ptechpartners.com/2026/02/04/top-10-ai-agents-transforming-sales-and-customer-engagement-in-2026/) -- MEDIUM confidence, market landscape
- [Landbase: Agentic AI Powers B2B GTM 2026](https://www.landbase.com/blog/agentic-ai-in-go-to-market-how-autonomous-ai-agents-drive-gtm-processes) -- MEDIUM confidence, autonomous pipeline management

---
*Feature research for: Agent Army Enterprise AI Sales Organization Platform*
*Researched: 2026-02-10*
