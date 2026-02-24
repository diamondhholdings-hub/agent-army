---
phase: 12-business-analyst-agent
plan: "02"
subsystem: agent-core
tags: [business-analyst, requirements, gap-analysis, user-stories, process-docs, baseagent]
depends_on:
  requires: ["12-01"]
  provides: ["BusinessAnalystAgent class", "BA_CAPABILITIES", "create_ba_registration", "full BA package exports"]
  affects: ["12-03", "12-04", "12-05"]
tech-stack:
  added: []
  patterns: ["fail-open handlers", "task-type router", "lazy SA import for escalation", "confidence computation helpers"]
key-files:
  created:
    - src/app/agents/business_analyst/agent.py
    - src/app/agents/business_analyst/capabilities.py
  modified:
    - src/app/agents/business_analyst/__init__.py
decisions:
  - id: "12-02-D1"
    description: "BA unknown-type returns error dict (fail-open) unlike SA/PM which raise ValueError -- deliberate divergence because BA is called from sales flow where exceptions halt conversation"
  - id: "12-02-D2"
    description: "SA escalation uses TechnicalQuestionPayload (not SAHandoffRequest which doesn't exist) with lazy import to avoid circular deps"
  - id: "12-02-D3"
    description: "LLM calls use _llm_service.completion() pattern consistent with all other agents (SA, PM, Sales), not .generate()"
  - id: "12-02-D4"
    description: "Confidence computation uses static helper methods (requirements avg confidence, gap coverage %, story low-confidence ratio)"
metrics:
  duration: "~3 min"
  completed: "2026-02-24"
---

# Phase 12 Plan 02: BA Agent Core Summary

**One-liner:** BusinessAnalystAgent with 4 fail-open handlers routing by task type, SA escalation via lazy-imported TechnicalQuestionPayload, and confidence computation helpers.

## What Was Built

### BusinessAnalystAgent (agent.py, 566 lines)

BaseAgent subclass with task-type router dispatching to 4 handlers:

1. **requirements_extraction** -- Builds prompt via `build_requirements_extraction_prompt`, single LLM call at temp 0.3, parses JSON array into `list[ExtractedRequirement]`, wraps in `BAResult`
2. **gap_analysis** -- Auto-extracts requirements if none provided, queries RAG for product capability chunks, builds gap analysis prompt, parses into `GapAnalysisResult`, checks `requires_sa_escalation` and constructs `TechnicalQuestionPayload` escalation via lazy import
3. **user_story_generation** -- Auto-extracts requirements if none provided, builds user story prompt, single LLM call at temp 0.4 (slightly higher for creative writing), parses into `list[UserStory]`
4. **process_documentation** -- Builds process documentation prompt, single LLM call at temp 0.3, parses into `ProcessDocumentation`

All handlers follow fail-open pattern: `try/except` returns `{"task_type": ..., "error": str(e), "confidence": "low", "partial": True}` on failure.

Helpers:
- `_extract_json_from_response`: Strips markdown code fences, finds first JSON array/object
- `_get_product_capabilities`: Queries RAG pipeline for product chunks, fail-open returns empty list
- `_compute_confidence` / `_compute_gap_confidence` / `_compute_story_confidence`: Static methods computing "high"/"medium"/"low" from data quality signals

### Capabilities (capabilities.py, 87 lines)

`BA_CAPABILITIES` list with 4 entries: `extract_requirements`, `analyze_gaps`, `generate_user_stories`, `document_process`. Each has description and output_schema.

`create_ba_registration()` factory returns `AgentRegistration` with `agent_id="business_analyst"`, 5 tags, `max_concurrent_tasks=3`.

### Package Init (__init__.py, 47 lines)

Full exports: `BusinessAnalystAgent`, `BA_CAPABILITIES`, `create_ba_registration`, plus all 10 schema types from plan 01.

## Key Design Choices

1. **Fail-open unknown type** -- BA returns error dict for unknown task types (unlike SA/PM which raise ValueError). Documented with inline code comment explaining the deliberate divergence: BA is called from the sales flow where exceptions would halt the conversation.

2. **SA escalation via TechnicalQuestionPayload** -- The plan referenced `SAHandoffRequest` but that schema doesn't exist. Used `TechnicalQuestionPayload` (the actual SA handoff input schema) with `question` and `deal_id` fields. Lazy imported inside the escalation block to avoid circular dependencies.

3. **LLM call convention** -- Used `_llm_service.completion(messages=..., model="reasoning", temperature=...)` matching the established pattern across all agents (SA, PM, Sales), not the `.generate()` pattern suggested in the plan spec. Response accessed via `response.get("content", "")`.

4. **RAG product capabilities** -- `_get_product_capabilities` first tries `rag_response.chunks` (list of chunk objects), then falls back to `rag_response.answer` (single string). Returns empty list if pipeline is None or query fails.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used TechnicalQuestionPayload instead of SAHandoffRequest**
- **Found during:** Task 1, gap analysis SA escalation
- **Issue:** Plan referenced `SAHandoffRequest` which does not exist in SA schemas
- **Fix:** Used `TechnicalQuestionPayload` (the actual SA handoff schema) with matching fields (question, deal_id)
- **Files modified:** src/app/agents/business_analyst/agent.py
- **Commit:** ea5c279

**2. [Rule 3 - Blocking] Used .completion() instead of .generate() for LLM calls**
- **Found during:** Task 1, all handlers
- **Issue:** Plan suggested `_llm_service.generate()` pattern but all existing agents use `_llm_service.completion()`
- **Fix:** Used `.completion()` with `messages`, `model`, `max_tokens`, `temperature` parameters consistent with SA/PM/Sales agents
- **Files modified:** src/app/agents/business_analyst/agent.py
- **Commit:** ea5c279

**3. [Rule 2 - Missing Critical] Added confidence computation helpers**
- **Found during:** Task 1, handler implementations
- **Issue:** BAResult requires a confidence field but plan did not specify computation logic
- **Fix:** Added `_compute_confidence` (requirements avg), `_compute_gap_confidence` (coverage %), `_compute_story_confidence` (low-confidence ratio) static helpers
- **Files modified:** src/app/agents/business_analyst/agent.py
- **Commit:** ea5c279

## Verification Results

| Check | Result |
|-------|--------|
| `create_ba_registration()` returns agent_id="business_analyst" with 4 capabilities | PASS |
| `BusinessAnalystAgent.__mro__` shows BaseAgent | PASS |
| `requires_sa_escalation` check present in agent.py | PASS |
| "Intentionally fail-open" design comment present | PASS |
| Existing tests pass (1173 passed) | PASS |

## Commits

| Hash | Type | Description |
|------|------|-------------|
| ea5c279 | feat | Implement BusinessAnalystAgent with 4 capability handlers |
| cd5aa41 | feat | Create capabilities declaration and full package init |

## Next Phase Readiness

Plan 12-02 delivers the BA agent core that plans 12-03 through 12-05 depend on:
- **12-03 (Integration):** Can now wire BusinessAnalystAgent into main.py lifespan and Sales Agent dispatch
- **12-04 (Tests):** Can now write unit tests against the 4 handlers and capabilities
- **12-05 (KB Seed):** Can seed knowledge base content that the gap analysis handler will query via RAG

No blockers or concerns for downstream plans.
