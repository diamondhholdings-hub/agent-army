# Phase 4: Sales Agent Core - Context

**Gathered:** 2026-02-11
**Status:** Ready for planning

<domain>
## Phase Boundary

The Sales Agent conducts text-based sales interactions via email (Gmail) and chat (Google Chat), adapting communication style to customer personas (IC, manager, C-suite), executing qualification frameworks (BANT and MEDDIC), and escalating to humans when appropriate. This phase delivers the conversational sales capability - deal management (CRM, opportunity tracking) and meeting capabilities are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Communication Style & Tone
- **Baseline tone:** Professional but warm - like a top sales rep who builds rapport, shows personality while maintaining credibility
- **Persona adaptation:** Distinct shifts per seniority level
  - IC: Conversational, friendly
  - Manager: Balance of friendly and strategic
  - C-suite: More formal, business-case focused, concise
- **Channel differences:** Both email and chat leverage Chris Voss methodology
  - Email: More structured and formal
  - Chat: Lighter, shorter, more conversational (like Slack)
- **Message length:** Contextual - adjust based on situation, deal stage, and what's needed (not rigidly brief or verbose)

### Qualification Approach
- **Discovery method:** Balanced ask + infer - use calibrated questions (Voss style) to probe directly, but also read between the lines
- **Framework selection:** Always use both BANT and MEDDIC in parallel - they complement each other, not mutually exclusive
- **Avoid interrogation:** Combination approach
  - Voss tactical empathy (labeling, mirroring, calibrated questions)
  - Share insights to earn questions (give value first)
  - Natural conversation flow (weave qualification into organic dialogue)
- **Incomplete qualification:** Continue with partial data - don't block progress, fill gaps opportunistically over time

### Follow-up Cadence & Timing
- **Default strategy:** Hybrid approach - start with multi-touch sequence, adjust timing based on engagement signals and deal progression
- **Persistence level:** Varies by buying signal strength
  - High intent (demo request, pricing question) = more persistent
  - Low intent (cold outreach) = more patient
- **Time intervals:** Adaptive timing based on deal stage, seniority, and engagement (not fixed cadence)
- **Follow-up triggers:** Multiple signal types
  - Deal milestones (pricing page visit, resource download, webinar attendance)
  - External events (company news, industry trends, product updates)
  - Internal signals (timeline approaching, competitor engagement, org changes)

### Human Escalation Logic
- **Escalation triggers:** All of the following
  - Low confidence in response (<70% confidence threshold)
  - High-stakes moments (pricing negotiation, contract terms, executive engagement, competitive displacement)
  - Explicit customer request (asks for human, wants call)
  - Deal complexity threshold (multi-stakeholder, political complexity, custom requirements)
- **Confidence threshold:** Conservative 70% for Phase 4 - prioritize accuracy and customer experience
  - Configurable setting - can adjust to balanced (50%) or autonomous (30%) later based on real-world performance
- **Handoff format:** Structured handoff report
  - Account context
  - Deal stage
  - What agent tried
  - Why it's escalating
  - Recommended next action
  - Relevant conversation excerpts
- **Notification routing:** Sales rep + manager (for initial rollout)
  - Rep handles the escalation
  - Manager gets visibility for coaching and oversight
  - Configurable later per tenant/team

### Claude's Discretion
- Exact wording of Voss-style calibrated questions
- Specific timing calculations for adaptive cadence
- Detailed formatting of structured handoff reports

</decisions>

<specifics>
## Specific Ideas

- **Chris Voss methodology:** Leverage tactical empathy, mirroring, labeling ("It seems like..."), and calibrated questions ("How are you thinking about...?") to make discovery feel collaborative, not interrogative
- **Training visibility:** Escalation notifications to manager create opportunity for sales coaching - manager can see what agents escalate and coach reps accordingly

</specifics>

<deferred>
## Deferred Ideas

- **Phase 4.1: Agent Learning & Performance Feedback** - NEW PHASE ADDED TO ROADMAP
  - Outcome tracking (did customer engage/ghost after agent messages?)
  - Human feedback mechanism (sales rep marks agent responses as good/bad)
  - Confidence calibration (track confidence vs actual success rate to self-improve)
  - Performance analytics dashboard
  - Sales training module (learn from escalations to train human reps)
  - Pattern-based self-improvement (adjust strategies based on what works)

</deferred>

---

*Phase: 04-sales-agent-core*
*Context gathered: 2026-02-11*
