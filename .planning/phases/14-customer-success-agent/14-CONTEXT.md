# Phase 14: Customer Success Agent - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a Customer Success (CSM) agent that calculates composite account health scores, predicts churn risk (both contract-proximity and behavioral signals), identifies expansion opportunities and dispatches them to the Sales Agent, produces QBR materials as Notion pages, and tracks feature adoption per account. Follows the established agent template (LangGraph, fail-open, Notion-first, event bus, APScheduler). New cross-agent flow introduced: CSM → Sales Agent dispatch (first reverse-direction handoff in the multi-agent system).

</domain>

<decisions>
## Implementation Decisions

### Health Score Inputs

- **Signals (all of the following):** feature adoption rate, support ticket volume/sentiment, last meaningful interaction date, login frequency, usage trends (growing/declining), invoice/payment status, stakeholder engagement, NPS/satisfaction score, contract renewal date proximity, seats used vs. purchased, escalation history
- **Data source:** Notion-only (same pre-sync pattern as TAM — data fed into Notion DBs, no external API dependencies)
- **Action thresholds:** RED/AMBER/GREEN bands with threshold-triggered outreach (same pattern as TAM HealthScorer)
- **Relationship to TAM:** Separate but correlated — TAM's technical health score is one input to the CSM health score. When TAM fires an escalation, that feeds into the CSM's churn risk calculation. CSM is the commercial layer over TAM's technical layer.

### Churn Prediction Mechanics

- **Model approach:** Hybrid — deterministic rules determine the churn risk level (like TAM HealthScorer), but LLM generates the narrative "why this account is at risk" explanation for the rep
- **60-day window:** Two triggers:
  1. Contract proximity: flag when health is AMBER/RED and renewal is within 60 days
  2. Behavioral: flag when usage/engagement decline patterns appear regardless of renewal date
- **Churn alert output:** Same 4-channel pattern as TAM — Notion health update + event bus publish + Gmail draft to rep + chat alert
- **Commercial vs. technical:** CSM owns commercial/business churn risk; TAM owns technical escalation. They're complementary and correlated — TAM escalation is an input to CSM, but they serve different purposes.

### QBR Output Format

- **Sections (all 4):**
  1. Account Health Summary — health score history, RED/AMBER/GREEN trend, key signals that moved the score
  2. ROI & Business Impact — quantified value delivered (time saved, revenue influenced, efficiency gains)
  3. Feature Adoption Scorecard — features used, adoption rate vs. benchmark, underutilized features with recommendations
  4. Expansion & Next Steps — recommended next steps: additional seats, new modules, integration opportunities, renewal terms
- **Output:** Notion page (same pattern as PM agent — structured Notion page in a CSM QBR database)
- **Schedule (both):**
  - Auto-generated at the beginning of each quarter (Q1/Q2/Q3/Q4 on the 1st) for all active accounts
  - Contract-triggered: auto-generated 90 days before contract end date for that specific account
- **Tone:** Hybrid — structured sections with 2-3 sentence narrative summaries + supporting metrics/bullets. Scannable but contextual.

### Expansion → Sales Agent Handoff

- **Dispatch method:** Direct dispatch to Sales Agent (same pattern as Sales → TAM, but reversed — CSM initiates, Sales Agent receives). First bidirectional cross-agent handoff in the system.
- **Payload contains:** account_id, opportunity_type (seats/module/integration), evidence (usage pattern that triggered it), estimated ARR impact, recommended talk track for the rep
- **Task type naming:** Claude decides — should follow the established `dispatch_*` convention consistent with dispatch_tam_health_check, dispatch_ba_analysis, etc.
- **No auto-send:** Like all agents, CSM creates Gmail drafts only. Rep reviews expansion recommendations before acting.

### Claude's Discretion

- Exact CSM health score formula (how to weight each of the many signals)
- Whether to implement a CSMScheduler class (like TAMScheduler) or reuse TAMScheduler with different job configs
- NotionCSMAdapter implementation details (sub-page structure for QBRs, which Notion DBs to use)
- How TAM health score is read as an input to CSM score (direct method call vs. event bus vs. Notion field read)
- Specific task type name for Sales Agent expansion handler

</decisions>

<specifics>
## Specific Ideas

- TAMScheduler established the pattern: daily health scan + monthly cadence. CSMScheduler should follow the same graceful APScheduler pattern.
- QBR should be a Notion page structured like a PM project plan — clean sections with rich blocks, not a wall of text.
- The expansion dispatch creates the first agent-to-agent call where a "downstream" agent calls back up to the Sales Agent. This is architecturally notable — the system becomes bidirectional, not just hub-and-spoke.
- CSM health score should incorporate TAM's latest health_rag field from the Notion account page (read Notion, don't call TAM directly).

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 14-customer-success-agent*
*Context gathered: 2026-02-24*
