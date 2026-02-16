# Phase 7: Intelligence & Autonomy - Context

**Gathered:** 2026-02-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Transform the Sales Agent from reactive executor to autonomous operator. The agent consolidates data across all channels (emails, chats, meetings, CRM) into unified customer views, recognizes actionable patterns, pursues revenue goals self-directedly within defined guardrails, adapts communication style for geographic regions, and supports agent cloning with persona customization per sales rep.

This phase delivers the intelligence layer that makes the agent truly autonomous while maintaining appropriate human oversight.

</domain>

<decisions>
## Implementation Decisions

### Autonomy Scope & Guardrails

**What the agent can initiate autonomously:**
- Proactive outreach (emails, chats) based on triggers (follow-ups, deal milestones, buying signals)
- Routine responses and qualification conversations
- Meeting scheduling and calendar coordination
- Deal progression through early stages (discovery, qualification)

**What requires human approval:**
- Strategic moves: proposals, pricing discussions, contract terms
- Deal progression past evaluation stage (negotiation, closing)
- Executive-level outreach (C-suite contacts)

**Hard stops (NEVER autonomous):**
- Pricing commitments or discount approvals
- Contract language modifications or legal commitments
- Strategic decisions (market entry, positioning changes, ICP redefinition)
- Executive relationship initiation without approval

**Goal pursuit approach:**
- Claude's discretion — determine appropriate balance between self-directed action plans and opportunity suggestions

**Performance metrics to track:**
- Pipeline metrics: dollars identified, dollars in pipeline, deal velocity, stage conversion rates
- Activity metrics: emails sent, meetings booked, responses received, engagement rate
- Quality metrics: qualification completion rate, escalation rate, customer satisfaction signals
- Revenue outcomes: dollars closed, win rate, average deal size, sales cycle length

### Pattern Recognition & Insights

**Pattern types to detect:**
- Buying signals: budget mentions, timeline urgency, competitive evaluations, stakeholder expansion
- Risk indicators: radio silence, delayed responses, budget freezes, champion departure, competitor preference
- Cross-account patterns: common feature requests, shared objections, industry trends
- Engagement patterns: response rate changes, meeting attendance, time-to-reply trends, engagement depth

**Insight delivery:**
- Real-time alerts for critical patterns (strong buying signals, major risk indicators)
- Daily digest for lower-priority insights
- Alert fatigue prevention via confidence thresholds

**Action vs inform:**
- Act automatically on routine patterns (follow up after silence, engage on buying signal)
- Alert human on strategic patterns (risk mitigation needed, cross-sell opportunity, executive escalation)

**Confidence handling:**
- Set confidence threshold for alerts (e.g., >70%)
- Human feedback loop: "This was useful" / "False alarm" tunes thresholds over time
- Continuous calibration to reduce false positives while maintaining pattern sensitivity

### Cross-Channel Data Consolidation

**Conflict resolution:**
- Most recent wins — latest information across channels is assumed correct
- Example: Budget mentioned in email ($500K) vs meeting ($750K) → meeting value is truth

**Entity linking strategy:**
- Email domain + participant matching to link conversations to accounts/deals
- Same email domain (@acmecorp.com) + overlapping participants = same context
- No fuzzy matching — explicit domain/participant overlap only

**Unified customer view includes:**
- Full conversation history: all emails, chats, meeting transcripts chronologically ordered with channel tags
- Extracted signals & state: BANT/MEDDIC signals, deal stage, pain points, stakeholder map
- Action history: timeline of agent actions (emails sent, meetings attended, proposals shared) with outcomes
- External context: CRM data, company info, news mentions, social signals

**Scale handling:**
- Intelligent summarization for long-running accounts
- Recent interactions (last 30-60 days) kept in full detail
- Older context progressively summarized
- Agent can drill into full history when needed for specific questions

### Geographic & Persona Customization

**Geographic adaptation depth:**
- Communication style only — adjust tone, formality, relationship-building approach per region
- Core sales methodologies stay consistent across regions
- Examples: APAC more relationship-first in tone, Americas more direct and value-focused
- Includes timezone awareness, language preferences, holiday awareness

**Agent cloning architecture:**
- Persona unique, knowledge shared
- Each clone has different communication style and personality
- All clones share: product knowledge, sales methodologies, regional settings, pattern insights

**Persona customization approach:**
- Guided persona builder (wizard/form interface)
- Key personality dimensions: formal vs casual, aggressive vs consultative, technical vs business-focused, relationship-driven vs transaction-driven
- Generate persona configuration from user choices
- Preview before deployment

**Learning model:**
- Hybrid: shared patterns, individual performance
- Insights shared across clones: "Objection X responds well to Y approach", "Signal Z predicts deal close"
- Performance metrics tracked per clone: individual quota attainment, win rates, customer feedback
- Pattern recognition benefits all clones within tenant

### Claude's Discretion

- Exact implementation of goal pursuit (balance between proactive plans and opportunity suggestions)
- Technical architecture for cross-channel data consolidation
- Summarization algorithm for long-running account context
- Confidence threshold starting values (human feedback will tune)
- Geographic nuance details beyond core communication style adaptation

</decisions>

<specifics>
## Specific Ideas

**Autonomy guardrails:**
- "The agent should feel like a junior rep that needs approval for big moves, not a senior rep operating independently"
- Hard stops are non-negotiable — pricing, contracts, strategy, executive relationships always require human

**Pattern recognition:**
- "I want to be alerted when deals are heating up or cooling down, not just see a dashboard I have to check"
- False positives are okay if they're rare — better to catch important patterns than miss them

**Data consolidation:**
- "If a customer mentions budget in a meeting, that overrides what they said in email last week — people's thinking evolves"
- "The agent should know everything that happened across every channel when it talks to a customer"

**Agent cloning:**
- "Each regional director should feel like they have 'their' agent that talks like them, not a generic robot"
- "But they shouldn't have to teach the agent about products — that knowledge should be shared"

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 07-intelligence-autonomy*
*Context gathered: 2026-02-16*
