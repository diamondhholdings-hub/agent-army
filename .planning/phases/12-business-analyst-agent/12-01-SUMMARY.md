---
phase: 12-business-analyst-agent
plan: 01
subsystem: business-analyst-schemas
tags: [pydantic, schemas, prompts, handoffs, requirements-engineering]
depends_on:
  requires: []
  provides:
    - BA Pydantic domain models (10 models)
    - BA prompt builders with JSON schema embedding (4 builders + system prompt)
    - requirements_analysis handoff type (STRICT)
  affects:
    - 12-02 (BA agent class + capabilities use schemas and prompts)
    - 12-03 (Notion adapter uses schemas for serialization)
    - 12-04 (tests import schemas and prompts)
    - 12-05 (Sales Agent dispatch uses BAHandoffRequest)
tech-stack:
  added: []
  patterns:
    - model_json_schema() embedding in prompts for structured LLM output
    - model_validator(mode="after") for computed fields
    - field_validator for Fibonacci story points constraint
key-files:
  created:
    - src/app/agents/business_analyst/__init__.py
    - src/app/agents/business_analyst/schemas.py
    - src/app/agents/business_analyst/prompts.py
  modified:
    - src/app/handoffs/validators.py
decisions:
  - BA prompt builders return str (not list[dict]) since the BA agent will construct the messages list in the handler, keeping prompts.py focused on content generation
  - model_json_schema() used for dynamic schema embedding rather than inline JSON strings, providing automatic schema updates when models change
  - ExtractedRequirement low-confidence threshold set at 0.6 (below the default 0.7) to flag only genuinely uncertain extractions
metrics:
  duration: ~5 min
  completed: 2026-02-24
---

# Phase 12 Plan 01: BA Schemas and Prompts Summary

**BA foundational Pydantic schemas (10 models) and LLM prompt templates (4 builders) with JSON schema embedding for structured output, plus requirements_analysis handoff type registered as STRICT.**

## Tasks Completed

### Task 1: Create BA Pydantic schemas and handoff payloads
- **Commit:** `5497034`
- **Files created:** `schemas.py` (10 models), `__init__.py` (package init)
- **Files modified:** `validators.py` (added requirements_analysis STRICT)
- **Models defined:**
  1. `ExtractedRequirement` -- multi-dimensional classification (functional/non-functional/constraint, MoSCoW, stakeholder domain) with auto-computed `is_low_confidence` flag via `model_validator`
  2. `CapabilityGap` -- gap severity + recommended action (build_it/find_partner/descope)
  3. `RequirementContradiction` -- min 2 conflicting requirement IDs enforced via `min_length=2`
  4. `UserStory` -- agile format with Fibonacci story points validated via `field_validator` (1,2,3,5,8,13)
  5. `ProcessDocumentation` -- current-state / future-state / delta with stakeholder tracking
  6. `GapAnalysisResult` -- composite result with coverage percentage and SA escalation flag
  7. `BATask` -- 4 task types (requirements_extraction, gap_analysis, user_story_generation, process_documentation)
  8. `BAResult` -- fail-open result envelope with confidence and partial flags
  9. `BAHandoffRequest` -- Sales Agent to BA request with analysis_scope
  10. `BAHandoffResponse` -- BA to Sales Agent response with all outputs

### Task 2: Create BA prompt templates with JSON schema embedding
- **Commit:** `0cfb49b`
- **Files created:** `prompts.py` (system prompt + 4 builders)
- **Prompt builders:**
  1. `build_requirements_extraction_prompt` -- embeds `ExtractedRequirement.model_json_schema()`, includes confidence scoring guidance
  2. `build_gap_analysis_prompt` -- embeds `GapAnalysisResult.model_json_schema()`, instructs coverage percentage calculation and SA escalation
  3. `build_user_story_generation_prompt` -- embeds `UserStory.model_json_schema()`, enforces Fibonacci points and low-confidence flagging
  4. `build_process_documentation_prompt` -- embeds `ProcessDocumentation.model_json_schema()`, extracts current/future/delta

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Prompt builders return `str` not `list[dict]` | BA handler will wrap in messages list; keeps prompts.py focused on content |
| `model_json_schema()` for schema embedding | Auto-updates when model changes; follows plan specification for key_links pattern |
| Low-confidence threshold at 0.6 | Default extraction_confidence is 0.7, so only genuinely uncertain items get flagged |

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

1. All 10 BA schemas import and validate correctly
2. ExtractedRequirement auto-flags `is_low_confidence=True` when `extraction_confidence < 0.6`
3. UserStory rejects non-Fibonacci story points (e.g., 4 raises ValueError)
4. RequirementContradiction rejects fewer than 2 requirement_ids
5. All 4 prompt builders embed JSON schemas (verified `model_json_schema()` output present)
6. `requirements_analysis` handoff type registered as STRICT in StrictnessConfig
7. All 1172 existing tests pass (1 pre-existing ordering-dependent failure excluded)

## Next Phase Readiness

Plan 12-02 (BA agent class + capability handlers) can proceed immediately -- all schemas and prompts are stable and importable.
