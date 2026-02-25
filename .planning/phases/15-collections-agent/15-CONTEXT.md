---
phase: 15-collections-agent
created: 2026-02-25
source: /gsd:discuss-phase 15
---

# Phase 15 Context: Collections Agent

## Decisions

### Escalation Ladder Design

**Trigger logic:** Both time-floor AND non-response. Time-floor sets the minimum days before escalating to the next stage (prevents premature escalation); non-response accelerates through stages when a message at the current stage goes unanswered. Both conditions are tracked together.

**Stage count:** 5 stages:
1. Friendly nudge — soft, relationship-preserving, assumes oversight/admin error
2. Soft reminder — polite urgency, references invoice specifics
3. Firm notice — clear consequences stated, tone shifts professional
4. Final warning — explicit escalation timeline, final chance before human intervention
5. Human handoff — rep + finance team both notified; agent stops sending further messages

**Human handoff behavior:** Both the account rep AND the finance team are notified at Stage 5. The agent hands off completely — no further automated messages after Stage 5 escalation.

**Per-tenant configuration:** Single default ladder. No per-tenant customization in v2.0. All tenants share the same escalation policy.

---

### Message Calibration Signals

**Primary calibration factors:**
- Days overdue (primary driver of tone urgency)
- Account value/ARR (higher value = more patience, softer tone at equivalent overdue days)
- Payment history pattern (clean payer = benefit of the doubt; chronic late payer = less patience)

All three factors combine to determine tone. Days overdue is the primary driver; account value and payment history modulate from there.

**Relationship softening:** High-ARR longstanding accounts receive extra patience — they get softer tone at the same overdue days as a smaller/newer account. Relationship length (tenure) + ARR together act as a softening modifier.

**Invoice references in messages:** Messages reference both the total outstanding balance AND call out the oldest invoice specifically (invoice number + date + amount). This specificity drives action better than a general balance reference.

**Stage behavior:** All 5 stages produce Gmail drafts for rep review. No stage sends email autonomously. Human handoff (Stage 5 unanswered) triggers rep + finance notification, also as Gmail drafts. Reps review and send manually.

---

### Payment Plan Surfacing Logic

**Identification method:** LLM inference from account signals. The agent analyzes available signals (payment history trend, account health, ARR, days overdue, tenure) and infers whether the account likely has a genuine cash flow issue vs. a process/oversight issue. No explicit "payment plan request" from the customer is required — the agent surfaces options proactively when signals suggest genuine hardship.

**Payment plan options presented:**
1. Installment schedule — spread outstanding balance across 2-3 payments with defined dates
2. Partial payment to restart relationship — pay a meaningful portion now to demonstrate good faith, defer remainder with agreed timeline
3. Pay-or-suspend services — structured ultimatum option for accounts approaching service risk

**Output format:** Notion page with an options table (showing each option, terms, pros/cons) PLUS a Gmail draft for the rep with a summary and suggested conversation approach. Humans approve all terms before any offer is made to the customer.

---

### Payment Risk Prediction Model

**Model architecture:** Deterministic score + LLM narrative. Same dual-layer pattern as CSM churn: a pure Python deterministic scorer produces a numeric risk score and RAG band; an LLM generates a human-readable narrative explaining the risk factors and recommended action. The deterministic score is the truth; the LLM narrative adds context.

**Scoring signals:**
- Days overdue (primary signal — strongest weight)
- Payment history streak (consecutive on-time vs. consecutive late payments)
- Total outstanding balance (absolute dollar amount, not just days)
- Days to contract renewal (renewal proximity increases risk urgency)

**Risk bands:**
- GREEN → LOW risk
- AMBER → MEDIUM risk
- RED → HIGH risk
- RED + critical threshold breach → CRITICAL risk

**Cross-agent integration:** Collections risk feeds into CSM health score. When a Collections assessment reaches HIGH or CRITICAL, it acts as a negative signal in the CSM HealthSignals (similar to how TAM health feeds CSM). CSM health scorer should receive a `collections_risk` field on its signals model.

---

## Claude's Discretion

- Exact numeric thresholds for risk band boundaries (GREEN/AMBER/RED score cutoffs)
- Exact weight distribution across the 4 scoring signals
- Specific wording/tone templates for each of the 5 escalation stages
- Days-floor values for each stage transition (e.g., 7 days at Stage 1 before escalating)
- Whether to use tenacity retry on Notion writes (follow existing adapter pattern)
- Internal class/method naming conventions (follow CSM/TAM patterns)
- Whether LLM narrative uses model_json_schema() or plain string output

---

## Deferred Ideas

- Per-tenant escalation ladder configuration (v3.0+ scope)
- Customer-facing payment portal integration (out of scope — humans process payments)
- Automatic payment plan approval for amounts under threshold (out of scope — humans approve all terms)
- Collections → Slack notification (deferred to INT-F03 in v3.0+)
