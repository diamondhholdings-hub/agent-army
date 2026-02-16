---
phase: 06-meeting-capabilities
created: 2026-02-12
status: ready_for_research
---

# Phase 6: Meeting Capabilities — Implementation Context

**Phase Goal:** The Sales Agent attends Google Meet meetings with an avatar representation, participates in real-time conversation, and produces meeting minutes distributed to stakeholders — the "wow" differentiator

**Context gathered:** 2026-02-12

## Decisions Made

These choices are **LOCKED** — research and planning must honor these exactly. Do not explore alternatives or suggest changes.

### 1. Avatar Representation and Visual Presence

**Appearance:**
- **Customizable per tenant** — each tenant can configure their own avatar style
- No single default appearance; system must support multiple avatar configurations
- This enables brand alignment per customer (e.g., Skyvera gets their own avatar)

**Animation Level:**
- **Fully animated with natural movements**
- Includes: lip-sync, head nods, eye contact simulation
- Target: indistinguishable from video of human participant
- Accept: highest complexity and latency cost for maximum realism

**Idle Behavior (when not speaking):**
- **Context-aware reactions**
- Avatar reacts to meeting content: nods at agreement points, interested look at key points
- Signals active engagement even when silent
- Requires: real-time content analysis to drive appropriate reactions

**Camera Presence:**
- **Always visible like other participants**
- Same size and prominence as human participants in meeting grid
- Equal participant treatment — not minimized or hidden
- Agent is a full team member, not a support tool in the background

**Engineering Implications:**
- HeyGen LiveAvatar API integration must support tenant-specific avatar selection
- Animation pipeline must achieve natural movement quality (lip-sync accuracy critical)
- Idle reaction system requires real-time sentiment/content analysis
- No fallback to static images — animated presence is core UX

---

### 2. Meeting Joining Flow and Control

**Join Trigger:**
- **Explicit invite/tag required**
- Agent only joins meetings where it is explicitly added to calendar invite OR tagged in meeting description
- No automatic joining of all calendar meetings (respects privacy for internal meetings)
- Clear opt-in model: presence is intentional, not assumed

**Arrival Time:**
- **2-3 minutes early** (professional standard)
- Mirrors best practice for sales calls: prepared and ready before customer arrives
- Accept: agent may wait in empty meeting briefly; this is preferred to being late

**Entrance Announcement:**
- **Verbal greeting immediately** upon join
- Example: "Hi, this is [Agent Name] joining from [Company]."
- Clear audio announcement so participants know agent has entered
- No silent joining — transparency is critical

**Exit Trigger:**
- **All customers leave**
- Agent stays as long as any external (non-internal) participant is present
- Mirrors professional behavior: salesperson doesn't leave before customer
- Internal-only debrief can happen after agent exits

**Engineering Implications:**
- Calendar integration must parse invite attendees and detect explicit agent inclusion
- Recall.ai bot must join early (support 2-3 minute pre-start window)
- TTS greeting must fire immediately on successful join
- Participant tracking to distinguish internal vs external attendees

---

### 3. Real-Time Response Behavior

**Speaking Posture:**
- **Active participant** (speaks proactively)
- Agent contributes naturally like a human salesperson
- Not passive/responsive-only — agent can initiate questions, make statements, guide conversation
- Accept: risk of over-participation; requires sophisticated participation calibration

**Turn-Taking:**
- **Strict turn-taking** (never interrupts)
- Agent waits for clear speech pauses before speaking
- Even with active posture, agent is polite: no interruptions, no talking over others
- Prefers missing an opportunity to being rude

**Latency Target:**
- **Under 1 second** (human-like)
- From end of customer speech to start of agent speech: <1s total
- This is VERY AGGRESSIVE given: STT processing + LLM reasoning + TTS generation + network latency
- Requires: streaming STT, aggressive LLM optimization (possibly parallel generation), streaming TTS, edge deployment

**Strategic Silence (when agent should NOT speak):**
- **All of the following** must be checked before speaking:
  1. **Customer thinking/pausing**: detect contemplation vs end-of-turn (don't rush customer processing time)
  2. **Internal rep speaking**: never talk over the human salesperson (clear hierarchy)
  3. **Confidence below threshold**: only speak when highly confident in response quality
- Multiple safety checks prevent low-quality or inappropriate contributions
- Better to stay silent than to speak poorly

**Engineering Implications:**
- Sub-1s latency requires end-to-end pipeline optimization:
  - Streaming STT (Deepgram/AssemblyAI)
  - LLM with aggressive timeout and streaming (Claude with <500ms first-token)
  - Streaming TTS (ElevenLabs turbo or similar)
  - Low-latency audio infrastructure
- Pause detection: distinguish thinking pauses (2-3s) from end-of-turn pauses (1s)
- Participant role tracking: identify internal vs external speakers
- Confidence scoring: LLM must self-assess response quality before committing to speak

---

### 4. Meeting Artifacts (Briefings & Minutes)

**Pre-Meeting Briefing Format:**
- **Multiple formats** available:
  1. **Structured document** (PDF/Markdown) — formal, shareable, comprehensive
  2. **Bullet-point summary** (email/Slack) — quick-scan, fast to consume
  3. **Adaptive by context** — detailed for new customer contacts, brief for ongoing relationships
- System generates all formats; rep can access preferred view

**Briefing Timing:**
- **2 hours before meeting**
- Recent data (not stale), still time to review and prepare
- Automatic generation and delivery (no manual trigger)

**Post-Meeting Minutes Content:**
- **Comprehensive** — all of the following included:
  1. **Verbatim transcript** — full conversation record (searchable)
  2. **Executive summary** — high-level takeaways (quick read)
  3. **Action items with owners** — clear next steps assigned to participants
  4. **Decisions and commitments** — what was agreed (critical for deal tracking)
- Minutes are structured in sections for easy navigation

**Minutes Distribution:**
- **Internal-only by default, manual share**
- Minutes saved to internal system immediately after meeting
- Rep/manager notified when ready
- Rep decides what to share externally (may clean up internal notes, extract customer-appropriate summary)
- No automatic external distribution (prevents leaking internal discussion)

**Engineering Implications:**
- Briefing pipeline: account context + deal context + attendee profiles + talk tracks → multiple format renderers
- Generation must complete reliably 2 hours before (not on-demand); requires scheduled job
- Minutes extraction: STT transcript → structured parsing (LLM-powered) → multi-section output
- Action item extraction with owner assignment (requires named entity recognition + role mapping)
- Storage: minutes in database, searchable via vector embeddings
- Distribution: internal notification system (email/Slack), external share as manual API endpoint

---

## Claude's Discretion

These areas were NOT discussed in detail. Claude (researcher & planner) can make implementation choices here based on technical best practices.

### Technical Architecture
- Choice of STT provider (Deepgram, AssemblyAI, etc.)
- LLM routing strategy (when to use fast vs accurate models)
- TTS provider selection and voice configuration
- Audio pipeline architecture (buffering, streaming, codec choice)
- Error handling and fallback behavior when latency exceeds 1s

### Integration Details
- Recall.ai API integration patterns
- HeyGen LiveAvatar API usage and avatar upload workflow
- Google Meet joining mechanics (bot authentication, permissions)
- Calendar integration approach (Google Calendar API vs webhook)

### Data Models
- Meeting state schema (participants, timeline, context)
- Transcript storage format
- Action item and decision data structures
- Briefing template schemas

### Observability
- Latency tracking (pipeline stage breakdown)
- Quality metrics (transcript accuracy, action item precision)
- Avatar animation quality monitoring
- User satisfaction signals

### Failure Modes
- What happens when latency exceeds 1s? (degrade gracefully? notify?)
- Avatar connection loss handling
- STT/TTS service outages
- Partial transcript scenarios

---

## Deferred Ideas

These are OUT OF SCOPE for Phase 6. Do not include in this phase. Capture for future consideration.

*(None captured during discussion)*

---

## Success Criteria Context

The roadmap defines 5 success criteria. These decisions clarify HOW to verify each:

1. **Meeting briefings** → Must generate in all 3 formats (structured/bullet/adaptive) 2 hours before; verify content includes account context, attendee profiles, objectives, suggested talk tracks

2. **Join Google Meet with avatar** → Verify explicit invite detection, 2-3 min early arrival, verbal greeting, HeyGen avatar visible and fully animated

3. **Real-time response <1s latency** → Measure end-to-end pipeline; verify strict turn-taking, strategic silence checks, active participation quality

4. **Recording capture and storage** → Verify full transcript + structured sections saved, searchable via embeddings

5. **Minutes generation and distribution** → Verify all 4 content types (transcript/summary/actions/decisions) generated, internal-only default, manual share flow works

---

## Key Constraints

**Non-negotiable requirements:**

1. **<1 second latency** — This is a hard requirement. If not achievable, Phase 6 is blocked until solved.
2. **Explicit opt-in** — No automatic joining without invite. Privacy is critical.
3. **Never interrupts** — Strict turn-taking even with active posture. Politeness over efficiency.
4. **Internal-only minutes** — No accidental external distribution. Rep controls sharing.
5. **Fully animated avatar** — No fallback to static. Animation quality is the "wow" factor.

**Trade-off priorities:**

When forced to choose, prioritize in this order:
1. Latency < 1s (hard requirement)
2. Response quality (high confidence threshold)
3. Avatar animation quality (realism over performance)
4. Briefing/minutes completeness (comprehensive over fast)

---

*Context finalized: 2026-02-12*
*Ready for: /gsd:plan-phase 6 (research will use this context)*
