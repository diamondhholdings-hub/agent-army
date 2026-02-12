# Phase 5: Deal Management - Context

**Gathered:** 2026-02-12
**Status:** Ready for planning

<domain>
## Phase Boundary

The Sales Agent manages the full deal lifecycle -- detecting opportunities from conversations, maintaining strategic account plans and tactical opportunity plans, mapping political structures with power/influence scoring, syncing with CRM backends bidirectionally, and advancing deals through stages based on qualification signals.

This phase is about **data integration, automated workflows, and business intelligence extraction** from sales conversations. Does NOT include forecasting, pipeline analytics, or reporting dashboards -- those are separate capabilities.

</domain>

<decisions>
## Implementation Decisions

### Opportunity Detection Triggers
- **Creation threshold:** Agent confidence >70% that deal potential exists (balance of precision/recall)
- **Bias toward precision:** Higher threshold (>80%) to minimize false positives -- better to miss marginal deals than create noise
- **New vs update logic:** Create new opportunity if discussing different product line OR significantly different timeline (>3 months apart). Otherwise update existing.
- **Autonomous creation:** Fully autonomous -- agent creates opportunities automatically, humans review in CRM later (no blocking approval workflow)

### Account & Opportunity Plan Structure
- **Clear separation:** Account plans track relationships, history, and overall strategy. Opportunity plans contain specific deal details, timeline, stakeholders, and close plan.
- **Account as container:** Account plan references all active opportunities. Each opportunity plan is self-contained with full context.
- **Real-time updates:** Update plans after every conversation -- always current. Accept higher write volume for data freshness.
- **Opportunity plan sections:**
  - Core deal info (product, value, timeline, stage, probability, close date)
  - MEDDIC/BANT tracking (qualification signals with evidence and confidence scores)
  - Stakeholder map (decision makers, influencers, champions, blockers with relationships)
  - Action items & next steps (what needs to happen, who owns it)
- **Account plan sections:**
  - Company profile (industry, size, tech stack, business model, strategic initiatives)
  - Relationship history (past interactions, wins/losses, sentiment over time, key contact history)
  - Strategic positioning (where we fit in their strategy, competitive landscape, whitespace opportunities)
  - Active opportunities (list/links to all open opportunities with status summary)

### Political Mapping Approach
- **Structured roles + quantitative scores:** Standard sales roles (decision maker, influencer, champion, blocker, user) PLUS three 0-10 scores: decision power, influence level, relationship strength
- **Hybrid scoring:** Start with title heuristics (VP=high, Manager=medium, IC=low), refine from conversation signals ("I'll need to run this by Sarah"), allow rep overrides
- **Relationship strength = composite:** Frequency (interaction count) + engagement depth (response rate, meeting attendance, time invested) + trust indicators (vulnerability shared, referrals, internal info disclosed)
- **Multiple roles allowed:** Person can be both influencer and blocker, or champion for some aspects and neutral on others -- capture complexity

### CRM Sync Strategy
- **Pluggable CRM architecture:** Generic adapter pattern with multiple backend support
- **Initial backends:** PostgreSQL (primary storage, always) + Notion database (first external CRM connector)
- **Future connectors:** Salesforce, HubSpot, Google Sheets, other CRMs as pluggable add-ons
- **Claude's discretion on sync details:**
  - Sync timing (real-time vs batch, polling frequency)
  - Conflict resolution strategy (which system wins, field-level rules)
  - API rate limiting and retry logic
  - Webhook vs polling for change detection

</decisions>

<specifics>
## Specific Ideas

- PostgreSQL as primary storage ensures agent always has data access even if external CRM is down
- Notion database as first external connector -- structured but flexible, good for early adopters without enterprise CRM
- Architecture should make adding Salesforce/HubSpot connectors straightforward (adapter pattern from the start)
- Political mapping scores should be transparent -- show evidence/reasoning for each score in the UI

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope. Forecasting, pipeline analytics, and reporting dashboards are separate phases.

</deferred>

---

*Phase: 05-deal-management*
*Context gathered: 2026-02-12*
