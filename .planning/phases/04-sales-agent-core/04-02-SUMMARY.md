---
phase: 04-sales-agent-core
plan: 02
subsystem: sales-agent
tags: [pydantic, schemas, prompts, bant, meddic, chris-voss, persona, qualification]

# Dependency graph
requires:
  - phase: 02-agent-orchestration
    provides: BaseAgent abstract class, agent registration types
  - phase: 03-knowledge-base
    provides: Methodology frameworks (BANT/MEDDIC) referenced in prompts
provides:
  - 9 Pydantic data models for Sales Agent domain (BANTSignals, MEDDICSignals, QualificationState, ConversationState, DealStage, PersonaType, Channel, EscalationReport, NextAction)
  - Persona-adapted prompt system with Chris Voss methodology (5 prompt builders)
  - PERSONA_CONFIGS for IC/Manager/C-Suite communication style adaptation
  - CHANNEL_CONFIGS for email vs chat differentiation
affects: [04-03, 04-04, 04-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Evidence-tracked qualification signals (quote + confidence per field)"
    - "Persona-adapted prompts affecting entire message generation"
    - "Conservative qualification extraction with state preservation"

key-files:
  created:
    - src/app/agents/sales/__init__.py
    - src/app/agents/sales/schemas.py
    - src/app/agents/sales/prompts.py
  modified: []

key-decisions:
  - "Completion score as property (computed, not stored) for BANT (4 dimensions) and MEDDIC (6 dimensions)"
  - "QualificationState combines both frameworks with combined_completion average"
  - "Qualification extraction preserves existing state -- only updates fields with new evidence (anti-overwrite pattern from research Pitfall 3)"
  - "Deal stage guidance for all 8 stages embedded in system prompts (not external lookup)"
  - "Channel configs keyed by string (not enum) for simpler CHANNEL_CONFIGS['email'] access in prompt builder"

patterns-established:
  - "Evidence pattern: each qualification field has _identified (bool), _description/contact (str), _evidence (str quote), _confidence (float 0-1)"
  - "Prompt composition: build_system_prompt(persona, channel, stage) -> str, then build_*_prompt wraps with user message"
  - "Messages list format: [{role: system, content: ...}, {role: user, content: ...}] for LLM calls"

# Metrics
duration: 5min
completed: 2026-02-12
---

# Phase 4 Plan 2: Schemas and Prompts Summary

**9 Pydantic models for BANT/MEDDIC qualification tracking plus persona-adapted Chris Voss prompt system for email and chat channels**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-12T03:32:10Z
- **Completed:** 2026-02-12T03:37:12Z
- **Tasks:** 2
- **Files created:** 3

## Accomplishments
- 9 Pydantic models covering full Sales Agent domain: enums (PersonaType, DealStage, Channel), qualification (BANTSignals, MEDDICSignals, QualificationState), state (ConversationState), escalation (EscalationReport), and actions (NextAction)
- Evidence-tracked qualification signals with per-field identification status, description, evidence quotes, and confidence scores
- Persona-adapted prompt system with 3 distinct configs (IC=conversational, Manager=balanced, C-Suite=executive-concise) affecting entire message generation
- Chris Voss methodology embedded in all prompts: tactical empathy, mirroring, labeling, calibrated questions, accusation audits, and anti-interrogation rules
- 5 prompt builders: system, email, chat, qualification extraction, and next-action recommendation

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Sales Agent data models and schemas** - `e3a35d8` (feat)
2. **Task 2: Create persona-adapted prompt system with Chris Voss methodology** - `7858493` (feat)

## Files Created/Modified
- `src/app/agents/sales/__init__.py` - Package init with Sales Agent docstring
- `src/app/agents/sales/schemas.py` - 9 Pydantic models: PersonaType, DealStage, Channel, BANTSignals, MEDDICSignals, QualificationState, ConversationState, EscalationReport, NextAction
- `src/app/agents/sales/prompts.py` - PERSONA_CONFIGS, VOSS_METHODOLOGY_PROMPT, CHANNEL_CONFIGS, build_system_prompt, build_email_prompt, build_chat_prompt, build_qualification_extraction_prompt, build_next_action_prompt

## Decisions Made
- Completion score implemented as computed property (not stored field) on BANTSignals (4 dimensions) and MEDDICSignals (6 dimensions) for always-accurate calculation
- QualificationState.combined_completion averages both framework scores for unified progress tracking
- Qualification extraction prompt explicitly instructs LLM to preserve existing state and only update with new evidence -- prevents Pitfall 3 (overwriting prior qualification data)
- Deal stage guidance for all 8 stages (prospecting through stalled) embedded directly in system prompts rather than separate lookup
- Channel configs keyed by string value (not Channel enum) for simpler dict access in prompt composition

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- psycopg-binary not installed in venv (required by langgraph checkpoint import chain from agents/__init__.py). Installed to unblock schema import verification. Not a plan deviation -- dependency was supposed to be installed per Phase 2 decisions.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All Sales Agent data models ready for consumption by Plans 03-05
- Prompt system ready for integration with LLM call pipeline (Plan 03: Sales Agent class)
- Qualification extraction prompt ready for Plan 04 (BANT/MEDDIC engine)
- No blockers

---
*Phase: 04-sales-agent-core*
*Completed: 2026-02-12*
