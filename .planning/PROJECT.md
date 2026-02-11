# Agent Army: Enterprise Sales Organization Platform

## What This Is

A complete AI sales organization platform with 8 specialized agents (Sales Agent, Solution Architect, Project Manager, Business Analyst, Technical Account Manager, Customer Success Agent, Collections Agent, Business Operations Agent). Each agent performs at top 1% global level in their role. One human per region (APAC, EMEA, Americas) is supported by their AI crew. Multi-tenant architecture supports deployment across ESW business units (Skyvera, Jigtree, Totogi) with per-product and per-region customization.

## Core Value

The Sales Agent must autonomously execute enterprise sales methodology at top-1% level - attending meetings with avatar, applying sales frameworks (BANT, MEDDIC, Target Account Selling, Chris Voss, Sandler), creating account plans, and self-directing toward revenue targets. This is the foundation that validates the platform architecture for all 8 agent roles.

## Requirements

### Validated

(None yet — ship to validate)

### Active

**Sales Agent (v1 - Template for all agents):**
- [ ] GSuite integration (Gmail, Chat, Google Meet)
- [ ] Send contextual emails and chats based on deal stage
- [ ] Attend Google Meet meetings with avatar representation
- [ ] Voice call capability (optional)
- [ ] Create meeting briefings (account context, objectives, talk tracks)
- [ ] Capture meeting recordings and create minutes
- [ ] Distribute minutes to stakeholders automatically
- [ ] Consolidate data across conversations/meetings/emails
- [ ] Pattern recognition (e.g., "X customers requesting Y feature")
- [ ] Deep product knowledge (Skyvera offerings, pricing, positioning)
- [ ] Persona-based interaction (adapt to customer level: IC, manager, exec, C-suite)
- [ ] Self-directed goal pursuit (dollars identified, sold, average deal time, closing rate)
- [ ] Opportunity identification and qualification (budget, authority, need, timeline)
- [ ] Sales methodology execution (BANT, MEDDIC, Target Account Selling, Chris Voss negotiation, Sandler)
- [ ] Create and maintain account plans
- [ ] Create and maintain opportunity plans
- [ ] Map political structures in accounts (decision makers, influencers, champions, blockers)
- [ ] Geographic customization (APAC, EMEA, Americas nuances)
- [ ] Low latency response for live customer interactions

**Platform (Shared Infrastructure):**
- [ ] Agent orchestration layer (8 agents communicate and hand off work)
- [ ] Knowledge base architecture (product/region/tenant separation)
- [ ] Multi-tenant support (clone entire crew to different business units)
- [ ] Multi-region support (customize agent behavior per geography)
- [ ] Multi-product support (extensible as ESW acquires businesses)
- [ ] Agent cloning system (replicate with different persona per sales rep)

**Other 7 Agents (v1 - Parallel after sales agent reaches 30%):**
- [ ] Solution Architect agent (product-specific technical guidance)
- [ ] Project Manager agent (PMBOK-certified delivery management)
- [ ] Business Analyst agent (requirements gathering and analysis)
- [ ] Technical Account Manager agent (escalations, technical relationships)
- [ ] Customer Success agent (adoption tracking, innovation identification)
- [ ] Collections agent (AR management)
- [ ] Business Operations/Sales Ops agent (process and systems management)

### Out of Scope

- Human replacement — Agents augment the one human per region, not replace them
- Real-time video generation — Avatar in meetings is visual representation, not deepfake video
- Financial transactions — Collections agent identifies issues, doesn't process payments
- Legal document signing — Agents draft, humans approve contracts

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

**Current Challenge:**
- Inconsistent sales execution across reps
- Methodology application varies by rep skill level
- Follow-ups missed, deals slip
- Need to scale sales capacity without linear hiring

**Demo Requirements:**
- Internal: Sales leaders see their "team" in action
- External: Agents deployed in real customer situations
- Must show: Impressive individual journey (sales agent end-to-end) AND full crew collaboration

## Constraints

- **Timeline**: Days, not weeks — AI-first development with 24/7 execution
- **Quality bar**: Sales agent must reach 80%+ production-ready before becoming template for other agents
- **Performance**: Low latency required for live customer interactions (meetings, voice)
- **Accuracy**: AI agents held to higher standard than humans - must be more reliable, not less
- **Security**: Enterprise data handling, multi-tenant isolation
- **Integration**: Must work with existing GSuite, CRM systems (type TBD)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Build all 8 agents in one project | Sales agent architecture validates platform for all roles | — Pending |
| Sales agent first, others at 30% | Need proven template before parallelizing | — Pending |
| Multi-tenant from day 1 | Will port to Jigtree/Totogi immediately after Skyvera | — Pending |
| Avatar for meetings | Humanizes AI presence, increases engagement | — Pending |
| Top 1% performance benchmark | Differentiator - better than average human, not just automated | — Pending |

---
*Last updated: 2025-02-10 after initialization*
