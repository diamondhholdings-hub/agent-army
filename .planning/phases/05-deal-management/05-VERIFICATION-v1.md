---
phase: 05-deal-management
verified: 2026-02-12T15:30:00Z
status: gaps_found
score: 4/5 must-haves verified
gaps:
  - truth: "Deal stages progress automatically based on qualification signals"
    status: failed
    reason: "PostConversationHook exists but is not called from sales conversation flow"
    artifacts:
      - path: "src/app/deals/hooks.py"
        issue: "Hook implementation complete but not wired into sales API endpoints"
      - path: "src/app/api/v1/sales.py"
        issue: "No call to app.state.deal_hook.run() after conversation processing"
    missing:
      - "Call deal_hook.run() from POST /sales/conversations endpoint after agent processes message"
      - "Call deal_hook.run() from POST /sales/email endpoint after email processing"
      - "Ensure hook fires for all conversation channels (chat, email)"
---

# Phase 5: Deal Management Verification Report

**Phase Goal:** The Sales Agent manages the full deal lifecycle -- identifying opportunities from conversations, maintaining strategic account plans and tactical opportunity plans, mapping political structures, and keeping CRM in sync

**Verified:** 2026-02-12T15:30:00Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Sales Agent identifies opportunity signals from conversations and creates qualified opportunities | ✓ VERIFIED | OpportunityDetector in `src/app/deals/detection.py` with instructor+litellm extraction, >0.80 creation threshold (line 43), deduplication via existing opportunities (line 176-190), should_create_opportunity logic (line 115-131) |
| 2 | Sales Agent creates and maintains account plans and opportunity plans that update as new information emerges | ✓ VERIFIED | PlanManager in `src/app/deals/plans.py` with create_or_update_account_plan (line 67-133), create_or_update_opportunity_plan (line 135-217), bounded list growth (MAX_KEY_EVENTS=50, MAX_INTERACTIONS=20, MAX_ACTION_ITEMS=30 at lines 60-62) |
| 3 | Sales Agent maps political structures with decision makers, influencers, champions, blockers and power dynamics | ✓ VERIFIED | PoliticalMapper in `src/app/deals/political.py` with 3-layer scoring (title heuristics line 80-87, conversation refinement line 120-220, human overrides line 222-247), role detection line 249-341, increase-only conversation signals (line 182-188) |
| 4 | CRM integration works bidirectionally with agent creates/updates and CRM changes flow back | ✓ VERIFIED | SyncEngine in `src/app/deals/crm/sync.py` with outbound sync (line 64-118), inbound sync (line 120-183), field-level conflict resolution (line 185-234), PostgresAdapter + NotionAdapter with full CRUD (src/app/deals/crm/postgres.py, src/app/deals/crm/notion.py) |
| 5 | Deal stages progress automatically based on qualification signals | ✗ FAILED | StageProgressionEngine exists in `src/app/deals/progression.py` with evidence-based evaluation (line 135-209) and stage requirements (line 74-99), PostConversationHook orchestrates all steps (src/app/deals/hooks.py line 72-315), BUT hook is not called from sales conversation endpoints -- no integration point in src/app/api/v1/sales.py |

**Score:** 4/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/app/deals/models.py` | 5 SQLAlchemy models with TenantBase | ✓ VERIFIED | AccountModel (line 35-76), OpportunityModel (line 78-136), StakeholderModel (line 138-204), AccountPlanModel (line 206-246), OpportunityPlanModel (line 248-288). All inherit TenantBase, use schema="tenant", have proper unique constraints |
| `src/app/deals/schemas.py` | Pydantic schemas for plans, political mapping, CRM, signals | ✓ VERIFIED | 25+ schemas: 4 enums (line 29-62), StakeholderScores (line 67-73), AccountPlanData (line 149-167), OpportunityPlanData (line 215-231), OpportunitySignals (line 395-412), CRM schemas (line 323-390) |
| `src/app/deals/repository.py` | DealRepository with session_factory pattern and 16 async CRUD methods | ✓ VERIFIED | DealRepository class (line 132-693), session_factory callable pattern (line 143-145), all account/opportunity/stakeholder/plan CRUD methods present and substantive (10-50 lines each) |
| `src/app/deals/detection.py` | OpportunityDetector with instructor+litellm extraction | ✓ VERIFIED | OpportunityDetector class (line 24-226), uses instructor.from_litellm (line 82), CREATION_THRESHOLD=0.80 (line 43), detect_signals method with existing opportunities dedup (line 49-113), prompt building (line 151-225) |
| `src/app/deals/political.py` | PoliticalMapper with hybrid scoring | ✓ VERIFIED | PoliticalMapper class (line 62-360), TITLE_HEURISTICS dict (line 81-87), score_from_title (line 100-118), refine_from_conversation with increase-only logic (line 120-220), apply_override (line 222-247), detect_roles_from_conversation (line 249-341) |
| `src/app/deals/plans.py` | PlanManager with bounded list growth | ✓ VERIFIED | PlanManager class (line 44-314), MAX constants (line 60-62), create_or_update_account_plan (line 67-133), create_or_update_opportunity_plan (line 135-217), _trim_list helper (line 301-313) |
| `src/app/deals/crm/sync.py` | SyncEngine with bidirectional sync and field-level conflict resolution | ✓ VERIFIED | SyncEngine class (line 33-273), sync_outbound (line 64-118), sync_inbound (line 120-183), _resolve_conflict with ownership rules (line 185-234), _filter_outbound_fields (line 236-255) |
| `src/app/deals/progression.py` | StageProgressionEngine with evidence-based thresholds | ✓ VERIFIED | StageProgressionEngine class (line 121-326), STAGE_EVIDENCE_REQUIREMENTS dict (line 74-99), evaluate_progression (line 138-209), check_requirements (line 211-263), _check_signal with signal mapping (line 295-325) |
| `src/app/deals/hooks.py` | PostConversationHook orchestrating all 4 deal operations | ⚠️ ORPHANED | PostConversationHook class exists (line 43-351) with run method orchestrating detection/political/plans/progression (line 72-315), fire-and-forget error handling (line 99-303), HookResult model (line 32-40). HOWEVER: not called from any sales conversation endpoint |
| `src/app/api/v1/deals.py` | REST API with 13 endpoints for accounts/opportunities/stakeholders/plans/pipeline | ✓ VERIFIED | 13 endpoints: accounts CRUD (3 endpoints line 236-290), opportunities CRUD (5 endpoints line 292-389), stakeholders CRUD (3 endpoints line 390-492), plans (2 endpoints line 494-530), pipeline view (1 endpoint line 533+) |
| `src/app/main.py` | Phase 5 initialization in lifespan | ✓ VERIFIED | Phase 5 initialization block present with DealRepository, OpportunityDetector, PoliticalMapper, PlanManager, StageProgressionEngine, PostConversationHook, SyncEngine all instantiated and stored on app.state |
| `alembic/versions/add_deal_management_tables.py` | Migration creating 5 tables with RLS and indexes | ✓ VERIFIED | Migration 006_deal_management creating accounts, opportunities, stakeholders, account_plans, opportunity_plans with RLS policies and composite indexes (line 32-83 for accounts, similar for others) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| hooks.py | detection.py | OpportunityDetector | ✓ WIRED | PostConversationHook imports OpportunityDetector (line 18), uses detector.detect_signals in run method (line 114-118) |
| hooks.py | political.py | PoliticalMapper | ✓ WIRED | PostConversationHook imports PoliticalMapper (line 19), uses mapper.refine_from_conversation and mapper.detect_roles_from_conversation (line 175-186) |
| hooks.py | plans.py | PlanManager | ✓ WIRED | PostConversationHook imports PlanManager (line 20), calls plan_manager.create_or_update_account_plan and plan_manager.create_or_update_opportunity_plan (line 224-247) |
| hooks.py | progression.py | StageProgressionEngine | ✓ WIRED | PostConversationHook imports StageProgressionEngine (line 21), calls progression.evaluate_progression (line 270-292) |
| api/v1/deals.py | repository.py | DealRepository | ✓ WIRED | deals.py uses _get_deal_repository helper that retrieves app.state.deal_repository (seen in endpoint signatures), DealRepository methods called in endpoints |
| api/v1/router.py | api/v1/deals.py | include_router | ✓ WIRED | router.py includes deals.router (line 17) |
| **api/v1/sales.py** | **hooks.py** | **PostConversationHook.run()** | ✗ NOT_WIRED | No call to app.state.deal_hook.run() found in sales.py. Hook is initialized in main.py and stored on app.state, but never invoked after conversation processing |

### Requirements Coverage

All Phase 5 requirements (SA-19 through SA-24) mapped from ROADMAP:
- SA-19 (Opportunity detection): ✓ SATISFIED (OpportunityDetector functional)
- SA-20 (Account/opportunity plans): ✓ SATISFIED (PlanManager functional)
- SA-21 (Political mapping): ✓ SATISFIED (PoliticalMapper functional)
- SA-22 (CRM sync): ✓ SATISFIED (SyncEngine functional)
- SA-23 (Stage progression): ✗ BLOCKED (Engine exists but not triggered)
- SA-24 (Deal pipeline): ✓ SATISFIED (API pipeline endpoint exists)

**Coverage:** 5/6 requirements satisfied

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | - | - | - | No anti-patterns (TODOs, placeholders, empty returns, console-only handlers) detected in substantive code |

### Human Verification Required

1. **CRM Sync Workflow**
   - **Test:** Configure Notion integration token and database ID in environment. Create an opportunity via API. Check if it appears in Notion database within 60 seconds.
   - **Expected:** Opportunity should be created in Notion with all agent-owned and shared fields populated.
   - **Why human:** Requires real Notion workspace and API token. Integration tests mock Notion API.

2. **Political Mapping Score Accuracy**
   - **Test:** Create stakeholders with different titles (CEO, VP, Manager, IC). Have a conversation mentioning each stakeholder with clear authority signals ("Sarah will make the final call"). Check stakeholder scores via GET /deals/accounts/{account_id}/stakeholders.
   - **Expected:** Title heuristics should set baseline (CEO decision_power=9, IC decision_power=2). Conversation refinement should increase scores when authority is mentioned.
   - **Why human:** LLM extraction quality depends on conversation content and prompt effectiveness. Unit tests mock LLM responses.

3. **Opportunity Detection Precision**
   - **Test:** Have 10 conversations: 3 with clear budget+timeline+product mentions, 4 with vague exploratory talk, 3 with no deal signals. Check how many opportunities are created via GET /deals/opportunities.
   - **Expected:** Creation threshold >0.80 should result in ~3 opportunities (only the clear ones). False positive rate should be low.
   - **Why human:** Requires evaluating LLM judgment on real conversation variability. Unit tests use fixed confidence values.

4. **Stage Progression Evidence Thresholds**
   - **Test:** Track a deal through multiple conversations, checking deal_stage after each. Verify stage advances only when BANT/MEDDIC thresholds are met per STAGE_EVIDENCE_REQUIREMENTS.
   - **Expected:** Deal should progress PROSPECTING -> DISCOVERY (need identified) -> QUALIFICATION (25% BANT, 16% MEDDIC) -> EVALUATION (50% BANT, 33% MEDDIC) -> NEGOTIATION (75% BANT, 50% MEDDIC) as evidence accumulates.
   - **Why human:** Requires multi-turn conversation sequence and verification that progression happens at correct evidence points. This test CANNOT RUN until the hook is wired into conversation flow.

### Gaps Summary

**Gap: PostConversationHook not called from sales conversation endpoints**

**Impact:** The entire Phase 5 deal management system is built but not operational. Opportunities are not detected, political maps are not updated, plans are not maintained, and stages do not progress automatically despite the code existing and being tested in isolation.

**Evidence:**
- PostConversationHook exists in `src/app/deals/hooks.py` (line 43-351) with complete 4-step orchestration
- Hook is initialized in `src/app/main.py` and stored on `app.state.deal_hook`
- Searching `src/app/api/v1/sales.py` for "deal_hook" returns no results
- No invocation of `await app.state.deal_hook.run()` in POST /sales/conversations or POST /sales/email endpoints

**What needs to be added:**
1. In `src/app/api/v1/sales.py`, after the agent processes a conversation (currently returns ConversationResponse), add:
   ```python
   # Fire post-conversation hook for deal management (fire-and-forget)
   if hasattr(app.state, 'deal_hook') and app.state.deal_hook:
       try:
           await app.state.deal_hook.run(
               tenant_id=tenant.id,
               conversation_text=response.agent_message,  # or full conversation
               conversation_state=state,
           )
       except Exception as exc:
           logger.warning("deal_hook_failed", error=str(exc))
   ```

2. Add similar invocation in email processing endpoint
3. Ensure conversation_text passed to hook includes both user and agent messages for full context

**Verification blockers:** Without this integration, human verification item 4 (stage progression) cannot be tested end-to-end. The system is structurally complete but functionally inactive.

---

_Verified: 2026-02-12T15:30:00Z_
_Verifier: Claude (gsd-verifier)_
