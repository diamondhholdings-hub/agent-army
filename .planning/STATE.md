# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-22)

**Core value:** The Sales Agent is a proven template — multiply its architecture across 7 additional agent roles to deliver a complete AI-powered enterprise sales organization
**Current focus:** v2.0 Agent Crew — Phase 13 complete: Technical Account Manager Agent

## Current Position

Phase: 13 of 19 (Technical Account Manager Agent)
Plan: 7 of 7 in current phase
Status: Phase complete
Last activity: 2026-02-24 — Completed 13-06-PLAN.md (gap closure: NotionTAMAdapter CRUD)

Progress: [████████████████████████████████████████░░░░░░░] 45% (25/55 plans, v2.0 phases 9-19)

## Performance Metrics

**v1.0 Velocity:**
- Total plans completed: 49
- Average duration: 6 min/plan
- Total execution time: ~5h 9min

**By Phase (v1.0):**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure | 3/3 | 42 min | 14 min |
| 02-agent-orchestration | 6/6 | 29 min | 5 min |
| 03-knowledge-base | 7/7 | ~61 min | 9 min |
| 04-sales-agent-core | 5/5 | 25 min | 5 min |
| 04.1-agent-learning | 3/3 | 19 min | 6 min |
| 04.2-qbs-methodology | 4/4 | 18 min | 5 min |
| 05-deal-management | 6/6 | 29 min | 5 min |
| 06-meeting-capabilities | 6/6 | 41 min | 7 min |
| 07-intelligence-autonomy | 6/6 | ~37 min | 6 min |
| 08-meeting-realtime-completion | 3/3 | 10 min | 3 min |

## Accumulated Context

### Architecture Decisions Carried Forward

- Sales Agent is the template — all 7 agents clone its structure (LangGraph, supervisor, event bus, RLS, Qdrant tenant namespace)
- Fail-open pattern throughout — LLM errors return fallback, not 500
- No auto-progression past NEGOTIATION — close decisions are human-only
- Single LLM call for all qualification signals (anti-pattern: no per-field calls)
- Production secrets via GitHub Actions env_vars, not GCP Secret Manager (09-02)
- SHA-tagged Docker images reused from staging to production (no rebuild)
- Health endpoint checks 4 deps: DB, Redis, Qdrant, LiteLLM; "local"/"no_keys" count as healthy in dev (09-01)
- Base64-encoded service account JSON for containerized deployments via get_service_account_path() (09-01)
- SA content types additive to ChunkMetadata Literal — competitor_analysis, architecture_template, poc_template (10-01)
- SA handoff types technical_question/technical_answer both STRICT validation (10-01)
- SA prompt builders embed JSON schema in user message for structured LLM output (10-01)
- SA handlers use low temperature (0.3-0.4) for JSON output reliability (10-02)
- SA fail-open returns {"error", "confidence": "low", "partial": True} per handler (10-02)
- SA seed script uses metadata_overrides for content_type from filename prefix mapping (10-03)
- Fictional competitors: BillingPro (legacy), ChargeStack (modern), RevenueOS (enterprise) covering 3 archetype patterns (10-03)
- Sales Agent dispatch_technical_question uses lazy import for SA schemas to avoid circular deps (10-05)
- _is_technical_question heuristic requires 2+ keyword matches to reduce false positives (10-05)
- PM total_budget_days is a plain Field(ge=0) not computed_field -- caller computes from phase estimates (11-01)
- PM handoff types: project_plan STRICT, status_report LENIENT, risk_alert STRICT (11-01)
- PM earned value uses 0/100 rule: tasks binary complete/incomplete, no subjective percent-complete (11-01)
- PM prompt builders embed JSON schema in user message, same pattern as SA (11-02)
- NotionPMAdapter takes pre-authenticated AsyncClient, not token string (11-02)
- PM block renderers are module-level functions decoupled from adapter (11-02)
- PM auto-risk adjustments use trigger="manual_input" since ScopeChangeDelta Literal doesn't include auto_risk_response (11-03)
- PM detect_risks uses raw JSON parsing for flexible risk list structure (11-03)
- PMScheduler gracefully handles missing APScheduler -- start() returns False (11-03)
- PM agent wired in main.py lifespan between Phase 10 (SA) and Phase 5 (Deals), stored on app.state.project_manager (11-04)
- APScheduler is runtime dependency (not dev-only) since PMScheduler uses it in production (11-04)
- Sales Agent dispatch_project_trigger uses lazy import for PM schemas, same pattern as SA dispatch (11-05)
- Handoff task key must be "trigger_type" (not "trigger") to match PM agent's task.get("trigger_type") reader (11-05)
- _is_project_trigger normalizes stage with lower().replace(" ", "_") for case-insensitive matching (11-05)
- BA schemas define 10 Pydantic models with model_validator for auto-computed is_low_confidence and field_validator for Fibonacci story points (12-01)
- BA prompt builders return str (not list[dict]), embedding model_json_schema() for structured LLM output (12-01)
- BA handoff type requirements_analysis registered as STRICT in StrictnessConfig (12-01)
- BA unknown-type returns error dict (fail-open) unlike SA/PM which raise ValueError -- deliberate divergence for sales flow (12-02)
- BA SA escalation uses TechnicalQuestionPayload with lazy import (SAHandoffRequest doesn't exist) (12-02)
- BA LLM calls use .completion() pattern matching all other agents, not .generate() (12-02)
- NotionBAAdapter takes pre-authenticated AsyncClient, same pattern as NotionPMAdapter (12-03)
- BA block renderers are module-level functions decoupled from adapter class (12-03)
- create_requirements_page returns page_id (UUID), matching NotionPMAdapter return pattern (12-03)
- User stories dual-grouped by epic_theme (full details in toggles) and stakeholder_domain (cross-reference list) (12-03)
- BA agent wired in main.py lifespan between Phase 11 (PM) and Phase 5 (Deals), stored on app.state.business_analyst (12-04)
- BA agent wiring pattern identical to SA/PM: try/except, import inside try, create registration, register in AgentRegistry (12-04)
- SCOPE_TO_TASK_TYPE uses explicit dict mapping, NOT .replace("_only", "") which produces wrong BA task keys (12-05)
- Sales Agent _is_ba_trigger requires 2+ keyword matches, same threshold as _is_technical_question (12-05)
- PM Agent scope change dispatch hardcodes analysis_scope="gap_only" since scope changes need gap analysis (12-05)
- BA trigger heuristic stages: technical_evaluation, evaluation, discovery -- normalized with lower().replace(" ", "_") (12-05)
- TAM schemas define 13 Pydantic models; HealthScoreResult auto-computes should_escalate via model_validator (13-01)
- TAM handoff types: health_report STRICT, escalation_alert STRICT (13-01)
- TAM prompt output schemas are plain dicts (not Pydantic models) since they describe LLM output shapes (13-01)
- TAM prompt builders return str with embedded JSON schema, same pattern as BA/SA (13-01)
- All TAM communications are DRAFT-only -- TAM never sends email autonomously (13-01)
- TAM agent raises ValueError for unknown task type, matching PM pattern not BA fail-open (13-02)
- TAM escalation alert email is also a draft -- rep reviews and manually sends both alert and outreach (13-02)
- TAM escalation alerts rate-limited to max 5 per scan run to prevent alert fatigue (13-02)
- GmailService.create_draft added for TAM draft-only communication pattern (13-02)
- HealthScorer uses keyword-only constructor args for per-tenant threshold customization (13-03)
- TicketClient pre-sync approach: reads from Notion DB, avoids Kayako/Jira API dependencies (13-03)
- NotionTAMAdapter stores relationship profiles as sub-pages (not embedded sections) for growth flexibility (13-03)
- TAMScheduler rate-limits escalation alerts to max 5 per daily scan run (13-03)
- Heartbeat None = "not monitored" (no penalty), not "silent" (penalty) -- prevents false at-risk for new accounts (13-03)
- Sales Agent dispatch_tam_health_check uses lazy import for TAMHandoffRequest, same pattern as SA/PM/BA dispatch (13-05)
- TAM_REQUEST_TO_TASK_TYPE uses identity mapping (request type == task type) since TAM types already match handler keys (13-05)
- _is_tam_trigger requires 2+ keyword matches from 17 TAM-specific keywords, same threshold as other triggers (13-05)
- TAM trigger stages: closed_won, onboarding, active_customer, renewal, account_management -- normalized with lower().replace(" ", "_") (13-05)
- TAM agent wired in main.py lifespan between Phase 12 (BA) and Phase 5 (Deals), stored on app.state.technical_account_manager (13-04)
- TAMScheduler started and stored on app.state.tam_scheduler with shutdown cleanup in shutdown section (13-04)
- Real HealthScorer used in tests (not mocked) since it's pure Python and deterministic (13-04)
- All trigger heuristics (_is_technical_question, _is_ba_trigger, _is_project_trigger, _is_tam_trigger) are supervisor-level static methods by established pattern -- NOT wired internally in _handle_process_reply() (13-07)
- NotionTAMAdapter.get_relationship_profile uses pragmatic block parsing (string splitting on ": " and " | ") for LLM prompt context, not exact round-trip (13-06)
- NotionTAMAdapter.update_relationship_profile tries RelationshipProfile model first, falls back to paragraph blocks (13-06)
- NotionTAMAdapter.log_communication accepts both dict and CommunicationRecord, converts dict to model before delegating (13-06)
- NotionTAMAdapter.get_account returns both `id` and `account_id` keys for agent.py compatibility (13-06)

### Open Blockers/Concerns

- Docker not installed on dev machine — CI/CD uses GitHub Actions runners
- GCP Cloud Run not human-verified (Phase 9 addresses this)
- Avatar render needs live manual test after Vercel deployment (Phase 9 addresses this)
- CalendarMonitor bot-join trigger partially implemented (manual bot join via REST works)

### Roadmap Evolution

- v1.0: 10 phases (including 2 INSERTED + 1 GAP CLOSURE), 49 plans
- v2.0: 11 phases (9-19), 55 requirements across 11 categories

## Session Continuity

Last session: 2026-02-24
Stopped at: Completed 13-06-PLAN.md (Phase 13 complete)
Resume file: None

**Note:** Phase 9 (09-03 Task 2) still pending human action for credential provisioning. Phase 13 complete -- all 7 plans executed (5 core + 2 gap closure). Ready for Phase 14.
