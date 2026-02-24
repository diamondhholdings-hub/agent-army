# Phase 12: Business Analyst Agent - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a Business Analyst agent that extracts structured requirements from any conversation input, performs gap analysis against known product capabilities, detects requirement contradictions, generates user stories, produces process documentation, and integrates with the Sales Agent and Project Manager Agent via handoff protocol.

Creating or modifying product capabilities, building a requirements management UI, or adding approval workflows are out of scope for this phase.

</domain>

<decisions>
## Implementation Decisions

### Requirements Extraction

- Input source: Any free-form conversation text — meeting transcripts, email threads, chat logs, or notes
- Categorization uses all three schemes simultaneously:
  - Functional / Non-functional / Constraint (standard BA taxonomy)
  - MoSCoW priority (Must-have / Should-have / Could-have / Won't-have)
  - Stakeholder domain (Sales / Tech / Ops / Finance)
- Each extracted requirement gets both a priority score (high/med/low) and an extraction confidence score
- Output: Pydantic schema (machine-readable, for agent consumption) + rendered Notion page linked to the deal

### Gap Analysis Behavior

- Contradiction detection is part of gap analysis — same output, not a separate handler
- Gaps are surfaced with a recommended action per gap: build it / find a partner / descope it
- When a gap has no workaround, the BA escalates to the Solution Architect Agent (same cross-agent dispatch pattern used by Sales Agent → SA)
- Source of truth for product capabilities: Claude's Discretion — researcher should evaluate whether the existing Qdrant knowledge base is sufficient or a dedicated structured capabilities registry is needed

### User Story Format & Output

- Full agile card format per story: As-a / I-want / So-that + acceptance criteria + story points estimate + priority
- Stories grouped by epic/theme AND by stakeholder domain (dual-grouping in the output structure)
- Low-confidence stories (below extraction confidence threshold) are included but flagged — not excluded
- Delivery: Both handoff response payload (for calling agent consumption) AND a Notion page under the deal record

### Sales Agent Handoff Integration

- Dispatch trigger: Either keyword signals (e.g., "we need", "our process requires", "does it support") OR deal reaching a stage threshold (e.g., Technical Evaluation) — both can trigger BA dispatch
- BA returns to Sales Agent: gap list + recommended next action (what the Sales Agent should do: address gap X, escalate to SA, defer, etc.)
- PM-to-BA handoff: Yes — the Project Manager Agent can dispatch to the BA for scope change impact analysis
- Handoff type name: Claude's Discretion — pick a name consistent with existing patterns (technical_question, project_trigger, etc.)

### Claude's Discretion

- Exact handoff type name (e.g., `requirements_analysis` or `business_analysis_request`) — pick consistent with existing naming conventions
- Whether to use Qdrant knowledge base or a new dedicated capabilities registry as product capability source of truth
- Confidence score thresholds for low-confidence flagging
- Story points estimation approach (T-shirt sizes vs numeric Fibonacci)

</decisions>

<specifics>
## Specific Ideas

- Follow the same agent architecture pattern established by Phase 10 (SA) and Phase 11 (PM): Pydantic schemas → prompt builders → capability handlers → main.py wiring → Sales Agent dispatch → round-trip tests
- Gap escalation to SA Agent should use the same cross-agent dispatch mechanism as `dispatch_technical_question` — lazy import pattern to avoid circular deps
- Notion output should follow the NotionPMAdapter pattern from Phase 11 — block renderers as module-level functions decoupled from the adapter

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 12-business-analyst-agent*
*Context gathered: 2026-02-23*
