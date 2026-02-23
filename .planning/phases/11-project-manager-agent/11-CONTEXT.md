# Phase 11: Project Manager Agent - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

A Project Manager agent that ingests deal deliverables from SA artifacts and CRM data, produces PMBOK-compliant 3-level project plans (phases → milestones → tasks), detects and responds to schedule risks and scope changes, generates internal and customer-facing status reports, and writes project records back to the Notion CRM.

</domain>

<decisions>
## Implementation Decisions

### Project Plan Structure
- **3-level WBS**: Phases → Milestones → Tasks (with owners and durations)
- **Required fields per plan**: milestones with target dates, resource estimates (days/effort), task dependencies, success criteria per phase
- **Trigger sources** (any of the following generates a plan):
  - Sales Agent closes a deal (deal stage = WON)
  - SA agent completes a POC scope document
  - Sales Agent identifies a complex deal (RFP, large expansion)
  - Manual trigger via HITL or another agent API call
- **Input sources**: SA artifacts (TechnicalRequirementsDoc + POC plan) + CRM deal data (deliverables, timeline, stakeholders) + request payload from HITL or agent

### Risk and Scope Change Behavior
- **Risk trigger signals** (all four active):
  - Milestone overdue by N days (threshold: Claude's discretion for N)
  - Dependent task blocked and critical path affected
  - Resource estimate exceeded beyond threshold
  - Deal stage stalled (no CRM activity beyond plan schedule)
- **Risk response**: Flag + auto-adjust plan + notify stakeholders (no human approval gate for adjustments)
- **Scope change detection**: Both agent-detected (SA agent produces updated requirements) and human-triggered (manual input via CRM or API)
- **Scope change output**: Delta report — original vs. revised plan side by side (not a regenerated full document)

### Status Report Format
- **Required sections in every report**:
  - Overall RAG status (Red / Amber / Green)
  - Milestone progress (% complete, on-track / at-risk per milestone)
  - Risks and issues log (active risks with severity and owner)
  - Next actions (concrete next steps with owners and due dates)
  - ACWP vs BCWP (Actual Cost of Work Performed vs Budgeted Cost of Work Performed — earned value metric)
- **Delivery**: Both email (via existing Gmail integration) + stored as CRM record on the deal
- **Recipients**: Two versions:
  - Internal: account executive + SA agent summary (full detail)
  - External: customer-facing polished summary (subset of internal)
- **Cadence**: Weekly scheduled reports + immediate trigger on milestone completion or milestone slip event

### CRM Integration
- **Writes to Notion CRM**:
  - Project plan as a deal sub-page
  - Milestone completion events (recorded but do NOT trigger Sales Agent deal stage changes)
  - Risk and issue log entries
  - Status report history (timestamped entries)
  - Change request log including approvals and declines
- **Deal stage ownership**: PM agent tracks its own project lifecycle separately — deal stages remain Sales Agent territory
- **Reads from Notion CRM**:
  - Deal stakeholders (for report distribution lists)
  - Agreed deliverables and timeline fields
  - Deal stage changes from Sales Agent (watches for transitions that affect the project plan)
- **Data model**: Claude's discretion — pick the cleanest model given existing Notion structure (either new PM properties on deals database or a linked Projects database)

### Claude's Discretion
- Exact threshold for "N days overdue" risk trigger
- Notion data model choice (extend deals DB vs. separate Projects DB linked to deals)
- Internal format of the project plan document (Notion page structure)
- Earned value calculation method details for ACWP vs BCWP

</decisions>

<specifics>
## Specific Ideas

- PMBOK compliance is explicit — the plan structure, terminology, and report sections should align with PMBOK standards (WBS, milestones, earned value)
- ACWP vs BCWP is a hard requirement in every status report — this is earned value management, not just a RAG status
- Change request log must track both approvals and declines — audit trail matters
- Two-version status reports (internal vs customer-facing) must be structurally different, not just the same doc with redactions

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 11-project-manager-agent*
*Context gathered: 2026-02-23*
