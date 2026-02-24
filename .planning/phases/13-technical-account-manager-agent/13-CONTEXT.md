# Phase 13: Technical Account Manager Agent - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a TAM agent that monitors technical health per account (from Kayako/Jira tickets + CRM + integration heartbeat), predicts and scores escalation risk, generates account-tailored technical communications (escalation outreach, release notes, roadmap previews, health check-ins, Customer Success Reviews), maintains a technical relationship profile per account, and surfaces co-development/integration opportunities to the Sales Agent. Does NOT handle churn scoring or expansion identification (Phase 14).

</domain>

<decisions>
## Implementation Decisions

### Health Signal Sources

- **Three signal categories:** Kayako/Jira ticket data + Notion CRM (deal stage, notes) + integration heartbeat (last-seen / API call count field, manually updated or posted by integration)
- **Kayako/Jira access:** Claude decides the integration mechanism (direct API polling or pre-synced to Notion/DB — whichever is most pragmatic given existing infrastructure)
- **Health = combination of three factors:** P1/P2 tickets older than a configured threshold, OR total open ticket count above threshold, OR integration heartbeat silent for too long → account is "at risk"
- **Refresh cadence:** Daily scheduled background scan (using APScheduler, already in use) PLUS on-demand refresh for a specific account when rep requests it

### Escalation Risk Scoring

- **Representation:** Numeric score (0–100, higher = healthier) PLUS a derived RAG status (Red/Amber/Green) for at-a-glance scanning
- **Proactive outreach trigger:** Either score drops below a configured threshold OR status worsens (e.g., Amber → Red) — whichever happens first
- **Notification when triggered:** Notion account page updated + Sales Agent notified via event bus + email alert to rep + chat alert to rep (all four channels)
- **Draft outreach:** TAM always auto-generates a draft outreach communication when escalation is flagged; rep reviews before sending

### Communication Generation

- **Five communication types:**
  1. Escalation outreach — triggered by risk flag, empathetic, addresses specific issues
  2. Tailored release notes — auto-generated when new release ships, highlighting features relevant to that account's known use cases
  3. Technical roadmap preview — on-demand when rep is preparing for a QBR or strategic call
  4. Periodic health check-in — scheduled (monthly or configurable), even when all is well
  5. Customer Success Reviews — structured summary of technical health, integrations, open items, and recommendations

- **Personalization depth:** Full relationship profile context — stakeholder names and technical maturity, known integrations, customer environment details, communication history
- **Scheduling:** Release notes auto-generated on new release (rep reviews before send); roadmap previews on-demand; health check-ins on schedule
- **Approval flow:** TAM creates Gmail draft in rep's inbox (same pattern as Sales Agent email flow) — rep reviews and hits send. TAM never sends autonomously.

### Relationship Profile Structure

- **Profile contains:**
  - Stakeholder technical maturity scores (low/medium/high per stakeholder)
  - Integration depth: which product integrations are active
  - Feature adoption: which features are in use (derived from heartbeat + ticket context)
  - Other applications known in the customer environment (tech stack context)
  - Communication history summary (past outreach, dates, rep-noted outcomes)
  - Customer technical roadmap alignment notes + co-development opportunity flags
- **Notion structure:** Claude decides the most practical layout (sub-page vs embedded section) given existing Notion CRM structure from prior phases
- **Stakeholder maturity:** Rep sets initial assessment; TAM refines over time based on ticket complexity and communication analysis; rep can override
- **Co-dev / integration opportunities:** Documented in relationship profile in Notion AND posted via event bus to Sales Agent for active deal follow-up

### Claude's Discretion

- Kayako/Jira integration mechanism (direct API vs pre-synced)
- Notion structure for relationship profile (sub-page vs embedded section)
- Exact escalation score thresholds (e.g., <40 = red)
- Communication scheduling specifics (monthly vs configurable interval)

</decisions>

<specifics>
## Specific Ideas

- TAM agent follows the same pattern as SA, PM, and BA agents: LangGraph BaseAgent, supervisor, event bus, Notion adapter, lazy-import dispatches
- Kayako and Jira are explicitly named as the support ticket sources
- Gmail draft creation follows the established Sales Agent email flow pattern
- All four notification channels active for escalation (Notion + Sales Agent event bus + email + chat) — not just one
- Customer Success Reviews are a distinct communication type (not the same as CSM QBR materials which belong to Phase 14)

</specifics>

<deferred>
## Deferred Ideas

- Churn risk scoring — Phase 14 (Customer Success Agent)
- Expansion/upsell identification — Phase 14
- Automated ticket creation in Kayako/Jira from TAM insights — could be added to Phase 13 gap closure or Phase 19

</deferred>

---

*Phase: 13-technical-account-manager-agent*
*Context gathered: 2026-02-24*
