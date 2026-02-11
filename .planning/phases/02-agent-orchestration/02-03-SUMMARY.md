---
phase: 02-agent-orchestration
plan: 03
subsystem: handoffs
tags: [pydantic, llm-validation, handoff-protocol, hallucination-prevention, semantic-validation]

# Dependency graph
requires:
  - phase: 01-infrastructure
    provides: "LLMService with LiteLLM Router, structlog logging, Pydantic BaseModel"
  - phase: 02-agent-orchestration
    provides: "AgentEvent schema with call chain validation (02-01), BaseAgent abstractions (02-02)"
provides:
  - "HandoffPayload Pydantic model with source attribution and call chain integrity validation"
  - "ValidationStrictness enum (STRICT/LENIENT) for configurable validation depth"
  - "StrictnessConfig mapping handoff types to strictness levels with STRICT fail-safe default"
  - "SemanticValidator using LLM to detect hallucinated claims (fail-open on LLM errors)"
  - "HandoffProtocol chaining structural then semantic validation"
  - "HandoffRejectedError with specific rejection reasons for debugging"
affects:
  - "02-agent-orchestration (supervisor routing, context management)"
  - "04-deal-workflows (deal data handoffs between agents)"
  - "05-sales-methodology (research result handoffs)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-layer validation: Pydantic structural then LLM semantic"
    - "Configurable strictness per handoff type (STRICT vs LENIENT)"
    - "Fail-open semantic validation to prevent LLM outages from blocking handoffs"
    - "Source attribution: source_agent_id must be in call_chain, target must NOT be"

key-files:
  created:
    - "src/app/handoffs/__init__.py"
    - "src/app/handoffs/validators.py"
    - "src/app/handoffs/semantic.py"
    - "src/app/handoffs/protocol.py"
    - "tests/test_handoffs.py"
  modified: []

key-decisions:
  - "Unknown handoff types default to STRICT validation (fail-safe over performance)"
  - "SemanticValidator uses model='fast' (Haiku) with temperature=0.0 for deterministic validation"
  - "LLM failure is fail-open: returns (True, ['semantic_validation_unavailable']) instead of blocking"
  - "HandoffPayload enforces target_agent_id NOT in call_chain (prevents circular handoffs)"
  - "Low confidence (<0.5) handoffs logged as warnings but not rejected structurally"

patterns-established:
  - "Handoff validation: structural first, semantic second (only for STRICT)"
  - "Strictness mapping: deal_data/customer_info/research_result=STRICT, status_update/notification=LENIENT"
  - "validate_or_reject() pattern: returns payload on success, raises HandoffRejectedError on failure"
  - "Lazy __getattr__ imports in __init__.py consistent with events package pattern"

# Metrics
duration: 4min
completed: 2026-02-11
---

# Phase 2 Plan 03: Handoff Validation Protocol Summary

**Two-layer handoff validation (Pydantic structural + LLM semantic) with configurable strictness per handoff type and fail-open semantics to prevent cascading hallucination**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-11T13:10:35Z
- **Completed:** 2026-02-11T13:14:30Z
- **Tasks:** 2
- **Files created:** 5

## Accomplishments
- HandoffPayload Pydantic model with source attribution validation (source must be in call_chain, target must NOT), confidence scoring, and tenant isolation context
- ValidationStrictness enum and StrictnessConfig with fail-safe defaults (unknown types get STRICT validation)
- SemanticValidator using LLM fast model (Claude Haiku, temp=0) to detect hallucinated claims, fabricated data, and logical inconsistencies -- fail-open when LLM is unavailable
- HandoffProtocol chaining structural then semantic validation based on configurable strictness per handoff type
- HandoffRejectedError carrying full validation result with specific, debuggable rejection reasons
- 26 tests covering structural validation, semantic validation, protocol chaining, fail-open behavior, and edge cases (557 lines)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create HandoffPayload structural validators** - `994a66c` (feat)
2. **Task 2: Build SemanticValidator, HandoffProtocol, and tests** - `e94aeaa` (feat)

## Files Created/Modified
- `src/app/handoffs/__init__.py` - Package exports with lazy __getattr__ for validators, semantic, and protocol
- `src/app/handoffs/validators.py` - HandoffPayload, ValidationStrictness, HandoffResult, StrictnessConfig
- `src/app/handoffs/semantic.py` - SemanticValidator with LLM-based claim verification and fail-open error handling
- `src/app/handoffs/protocol.py` - HandoffProtocol chaining structural + semantic validation, HandoffRejectedError
- `tests/test_handoffs.py` - 26 tests across 6 test classes (structural, strictness, result, semantic, protocol, error)

## Decisions Made
- Unknown handoff types default to STRICT validation as a fail-safe -- better to over-validate than to let hallucinated data cascade
- SemanticValidator uses the "fast" LLM model group (Claude Haiku) with temperature=0.0 for deterministic, low-latency validation
- LLM failure (RuntimeError, TimeoutError, parse errors) returns (True, ["semantic_validation_unavailable"]) -- fail-open prevents LLM outages from blocking all agent handoffs
- HandoffPayload enforces target_agent_id NOT in call_chain as a structural guard against circular handoffs
- Low confidence handoffs (<0.5) are logged as warnings but not rejected at the structural level -- the semantic layer handles data quality

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Handoff validation protocol ready for supervisor (02-05) to integrate when routing tasks between agents
- HandoffProtocol can be used standalone or injected into any agent coordination flow
- SemanticValidator requires LLMService instance -- works with any configured LLM provider from Phase 1
- StrictnessConfig is extensible via register_rule() for new handoff types added in later phases

---
*Phase: 02-agent-orchestration*
*Completed: 2026-02-11*
