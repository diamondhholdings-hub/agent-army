# Phase 12: Business Analyst Agent - Research

**Researched:** 2026-02-23
**Domain:** Business requirements analysis, gap analysis, user story generation, cross-agent dispatch
**Confidence:** HIGH

## Summary

Phase 12 adds a Business Analyst (BA) agent that extracts structured requirements from free-form conversation text, performs gap analysis against product capabilities, detects contradictions, generates user stories, and produces process documentation. The BA agent follows the exact same architecture established by the Solution Architect (Phase 10) and Project Manager (Phase 11) agents: Pydantic schemas, prompt builders, capability handlers, a BaseAgent subclass with task-type routing, and Sales Agent dispatch integration via lazy imports.

The codebase is mature and the patterns are well-established. This phase does NOT require any new external libraries. All capabilities are LLM-driven through the existing litellm service, Qdrant RAG pipeline, and Notion adapter infrastructure. The primary implementation challenge is designing the BA-specific Pydantic schemas (requirements extraction with triple-categorization, gap analysis with recommendations, user story grouping) and crafting effective prompt builders for each capability.

**Primary recommendation:** Clone the SA/PM agent structure exactly. The BA agent needs 5 capability handlers (extract_requirements, analyze_gaps, generate_user_stories, produce_process_docs, requirements_handoff), a NotionBAAdapter following the NotionPMAdapter pattern (module-level block renderers), and dispatch integration in the Sales Agent using the established lazy import pattern.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | >=2.0.0 | Schema definitions for all BA domain models | Already used by every agent; SA/PM patterns proven |
| litellm | >=1.60.0 | LLM completions for requirements extraction, gap analysis, user stories | Existing LLM service across all agents |
| structlog | >=24.0.0 | Structured logging with agent_id binding | Established pattern in all agents |
| notion-client | >=2.7.0 | Notion CRM integration for BA output pages | Used by PM agent's NotionPMAdapter |
| tenacity | >=9.0.0 | Retry logic for Notion API calls | Used by NotionPMAdapter |
| qdrant-client | >=1.12.0 | RAG pipeline for product capability knowledge | Existing hybrid search infrastructure |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| apscheduler | >=3.10.0 | Scheduled BA tasks (if needed later) | Not needed for Phase 12 |

### Alternatives Considered

None. This phase uses only existing stack -- no new dependencies required.

**Installation:**
```bash
# No new dependencies needed -- all already in pyproject.toml
```

## Architecture Patterns

### Recommended Project Structure

```
src/app/agents/business_analyst/
    __init__.py          # Public API: BA agent, schemas, capabilities, adapter
    schemas.py           # Pydantic models: requirements, gaps, user stories, process docs, handoff payloads
    prompts.py           # BA_SYSTEM_PROMPT + 5 prompt builders (one per capability)
    capabilities.py      # BA_CAPABILITIES list + create_ba_registration() factory
    agent.py             # BusinessAnalystAgent(BaseAgent) with 5 handlers + _query_rag + _parse_llm_json
    notion_ba.py         # NotionBAAdapter + module-level block renderers
```

### Pattern 1: Agent Architecture (Clone SA/PM exactly)

**What:** Each agent follows the same 5-file structure with BaseAgent subclass, task-type routing via handlers dict, fail-open error handling, RAG context retrieval, prompt construction, LLM call, JSON parsing into Pydantic models.

**When to use:** Every capability handler.

**Example (from SA agent.py, lines 78-110):**
```python
async def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    task_type = task.get("type", "")
    handlers = {
        "extract_requirements": self._handle_extract_requirements,
        "analyze_gaps": self._handle_analyze_gaps,
        "generate_user_stories": self._handle_generate_user_stories,
        "produce_process_docs": self._handle_produce_process_docs,
        "requirements_handoff": self._handle_requirements_handoff,
    }
    handler = handlers.get(task_type)
    if handler is None:
        raise ValueError(f"Unknown task type: {task_type!r}. Supported: {', '.join(handlers.keys())}")
    return await handler(task, context)
```

### Pattern 2: Handler Implementation (RAG -> Prompt -> LLM -> Parse -> Return)

**What:** Each handler follows the identical 7-step pattern used in SA and PM agents.

**Example (from SA agent.py _handle_map_requirements, lines 114-157):**
```python
async def _handle_extract_requirements(self, task, context):
    try:
        tenant_id = context.get("tenant_id", "")
        transcript = task.get("transcript", "")
        deal_context = task.get("deal_context", {})

        rag_context = await self._query_rag(
            query=f"product capabilities features for: {transcript[:200]}",
            tenant_id=tenant_id,
            content_types=["product"],  # product docs for gap analysis grounding
        )

        messages = build_requirements_extraction_prompt(
            transcript=transcript,
            deal_context=deal_context,
            rag_context=rag_context,
        )

        response = await self._llm_service.completion(
            messages=messages,
            model="reasoning",
            max_tokens=4096,
            temperature=0.3,  # Low temp for structured JSON output
        )

        raw_content = response.get("content", "")
        result = self._parse_llm_json(raw_content, RequirementsDocument)
        return result.model_dump()
    except Exception as exc:
        self._log.warning("extract_requirements_failed", error=str(exc), error_type=type(exc).__name__)
        return {"error": str(exc), "confidence": "low", "partial": True}
```

### Pattern 3: Sales Agent Dispatch (Lazy Import)

**What:** The Sales Agent dispatches to the BA agent using a lazy import of BA schemas to avoid circular dependencies. This is the exact same pattern used for `dispatch_technical_question` (SA) and `dispatch_project_trigger` (PM).

**Example (from sales/agent.py lines 680-743, adapted for BA):**
```python
async def _handle_dispatch_requirements_analysis(self, task, context):
    # Lazy import to avoid circular dependency
    from src.app.agents.business_analyst.schemas import RequirementsAnalysisPayload

    payload = RequirementsAnalysisPayload(
        transcript=task.get("transcript", ""),
        deal_id=task.get("deal_id", ""),
        source=task.get("source", "conversation"),
        deal_context=task.get("deal_context", {}),
    )

    handoff_task = {
        "type": "extract_requirements",  # matches BA agent's execute() routing
        "transcript": payload.transcript,
        "deal_id": payload.deal_id,
        "deal_context": payload.deal_context,
    }

    return {
        "status": "dispatched",
        "handoff_task": handoff_task,
        "payload": payload.model_dump_json(),
        "target_agent_id": "business_analyst",
    }
```

### Pattern 4: Notion Block Renderers (Module-Level Functions)

**What:** Block renderers are module-level functions decoupled from the adapter class. The adapter handles CRUD; the renderers convert domain models to Notion block structures.

**Example (from PM notion_pm.py lines 448-511):**
```python
# Module-level function, NOT an adapter method
def render_requirements_to_notion_blocks(doc: RequirementsDocument) -> list[dict]:
    blocks = []
    blocks.append(_heading_block(1, f"Requirements Analysis -- {doc.deal_id}"))
    blocks.append(_paragraph_block(doc.summary))

    for req in doc.requirements:
        blocks.append(_heading_block(3, f"[{req.priority.upper()}] {req.category}"))
        blocks.append(_paragraph_block(req.description))
        if req.source_quote:
            blocks.append(_bulleted_block(f"Source: \"{req.source_quote}\""))
    # ... etc
    return blocks
```

### Pattern 5: Handoff Type Naming Convention

**What:** Handoff types follow a consistent naming pattern: `technical_question`, `technical_answer`, `project_plan`, `status_report`, `risk_alert`. For the BA agent, the handoff type should be `requirements_analysis` for the request and `requirements_analysis_result` for the response.

**Recommendation:** Use `requirements_analysis` as the handoff type name. This follows the `{domain}_{action}` pattern:
- `technical_question` / `technical_answer` (SA)
- `project_plan` / `status_report` / `risk_alert` (PM)
- `requirements_analysis` / `requirements_analysis_result` (BA)

Both should use STRICT validation, consistent with SA handoffs carrying data.

### Pattern 6: PM-to-BA Dispatch for Scope Change Impact Analysis

**What:** The PM agent can dispatch to the BA agent for scope change impact analysis, following the same lazy import pattern. The PM agent's `_handle_adjust_plan` can internally dispatch to the BA for requirements impact.

**Implementation:** Add a `dispatch_requirements_analysis` handler to the PM agent (or call the BA directly within the PM's `_handle_adjust_plan` handler) using the same lazy import pattern.

### Anti-Patterns to Avoid

- **Separate contradiction handler:** Contradiction detection is part of gap analysis, NOT a separate handler. The gap analysis output includes contradictions in the same response.
- **Excluding low-confidence items:** Low-confidence requirements are included but flagged with `confidence_flagged: true`, not excluded.
- **Hand-rolling JSON parsing:** Use `_parse_llm_json()` from BaseAgent pattern (regex strip code fences -> json.loads -> model_validate). Both SA and PM agents have this as a static method.
- **Circular imports at module level:** Always use lazy imports (inside the handler function body) for cross-agent schema references.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM JSON output parsing | Custom JSON parser | `_parse_llm_json()` static method (regex + json.loads + model_validate) | Handles code fences, validated by Pydantic |
| Retry logic for Notion API | Custom retry | `tenacity @retry` decorator (same as NotionPMAdapter) | Exponential backoff, configurable attempts |
| RAG context retrieval | Custom search | `_query_rag()` helper method with fail-open semantics | Returns empty string on failure, no crash |
| Product capability lookup | New vector collection | Existing Qdrant knowledge_base with content_type="product" filter | Product docs already have feature/capability data |
| Block rendering for Notion | Inline block construction | Module-level `_heading_block()`, `_paragraph_block()`, `_bulleted_block()`, `_todo_block()` helpers | Proven pattern from PM's notion_pm.py |
| Agent registration | Manual registration | `create_ba_registration()` factory -> `AgentRegistry.register()` | Consistent with SA/PM pattern |

**Key insight:** The BA agent adds NO new infrastructure. Every supporting pattern (RAG queries, LLM calls, Notion writes, handoff dispatch, fail-open error handling) already exists. The work is purely in designing BA-domain schemas and prompts.

## Common Pitfalls

### Pitfall 1: Over-Splitting Capabilities

**What goes wrong:** Creating separate handlers for requirements extraction, contradiction detection, and gap analysis when they should be combined. The CONTEXT.md explicitly states "Contradiction detection is part of gap analysis -- same output, not a separate handler."
**Why it happens:** BA domain has many outputs; tempting to give each its own handler.
**How to avoid:** Follow the locked decision: gap analysis handler produces gaps + contradictions + recommended actions in a single output schema. Keep to 5 handlers maximum matching the 5 BA requirements (BA-01 through BA-05).
**Warning signs:** More than 5 capability handlers in the BA agent.

### Pitfall 2: Missing Triple Categorization in Requirements Schema

**What goes wrong:** Defining requirements with only one categorization scheme when the CONTEXT.md requires three simultaneous schemes: Functional/Non-functional/Constraint, MoSCoW, and Stakeholder domain.
**Why it happens:** SA agent's TechRequirement uses a simpler two-scheme (category + priority) approach. Tempting to copy directly.
**How to avoid:** Design the BA Requirement schema with all three classification fields from the start: `requirement_type: Literal["functional", "non_functional", "constraint"]`, `moscow: Literal["must_have", "should_have", "could_have", "wont_have"]`, `stakeholder_domain: Literal["sales", "tech", "ops", "finance"]`.
**Warning signs:** Requirements output missing one of the three categorization dimensions.

### Pitfall 3: Forgetting Dual Output (Schema + Notion)

**What goes wrong:** Implementing only the Pydantic schema output and forgetting that each BA output must also render as a Notion page linked to the deal.
**Why it happens:** The SA agent only returns structured data; the PM agent has both. Easy to forget BA needs both.
**How to avoid:** Every handler that produces BA output should: (1) return model_dump() for agent consumption, AND (2) optionally render to Notion blocks via NotionBAAdapter (like PM's write_crm_records pattern). Plan both outputs from the start.
**Warning signs:** BA returns data but no Notion page is created/updated.

### Pitfall 4: Not Using Low Temperature for JSON Output

**What goes wrong:** Using high temperature (e.g., 0.7) for structured JSON output, causing parsing failures.
**Why it happens:** Default temperature might be higher than needed for structured output.
**How to avoid:** Use temperature=0.3-0.4 for all BA handlers that expect JSON output, consistent with SA (0.3-0.4) and PM (0.2-0.3) handlers.
**Warning signs:** Frequent `_parse_llm_json` failures, Pydantic validation errors.

### Pitfall 5: Product Capability Source of Truth

**What goes wrong:** Building a separate dedicated capabilities registry when the existing Qdrant knowledge base already contains product documentation with feature/capability data.
**Why it happens:** The term "capabilities registry" suggests a new data store.
**How to avoid:** Use the existing Qdrant knowledge base with `content_type="product"` filter. The product markdown files (billing.md, charging.md, monetization-platform.md) already document "Key Capabilities" per module with detailed feature lists. The BA agent's gap analysis handler should query RAG with content_type=["product"] to retrieve relevant capability documentation.
**Warning signs:** Creating new Qdrant collections or data structures for product capabilities.

### Pitfall 6: Circular Import Between BA and SA for Gap Escalation

**What goes wrong:** Importing SA schemas at module level in the BA agent for gap escalation.
**Why it happens:** BA needs to dispatch to SA when a gap has no workaround. Module-level import creates circular dependency.
**How to avoid:** Use the same lazy import pattern inside the handler function body, exactly as Sales Agent does for SA dispatch. Import `TechnicalQuestionPayload` only inside `_handle_escalate_to_sa()`.
**Warning signs:** ImportError at module import time mentioning circular dependency.

## Code Examples

### Example 1: BA Requirements Schema (with Triple Categorization)

```python
# Source: Adapted from SA schemas.py TechRequirement pattern
class BARequirement(BaseModel):
    """A single business requirement extracted from conversation input."""
    description: str
    requirement_type: Literal["functional", "non_functional", "constraint"]
    moscow: Literal["must_have", "should_have", "could_have", "wont_have"]
    stakeholder_domain: Literal["sales", "tech", "ops", "finance"]
    priority_score: Literal["high", "medium", "low"]
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    source_quote: str = ""
    confidence_flagged: bool = False  # True when below threshold


class RequirementsDocument(BaseModel):
    """Structured requirements document from BA extraction."""
    requirements: list[BARequirement]
    summary: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    source_hash: str = ""
    deal_id: str = ""
```

### Example 2: Gap Analysis Schema (with Contradiction Detection)

```python
# Source: BA domain design, follows SA ObjectionResponse pattern
class GapItem(BaseModel):
    """A single gap between stated requirements and product capabilities."""
    requirement_description: str
    gap_description: str
    recommended_action: Literal["build_it", "find_partner", "descope"]
    workaround: str | None = None
    severity: Literal["critical", "major", "minor"]


class Contradiction(BaseModel):
    """A contradiction detected between requirements."""
    requirement_a: str
    requirement_b: str
    conflict_description: str
    resolution_suggestion: str


class GapAnalysisResult(BaseModel):
    """Combined gap analysis and contradiction detection output."""
    gaps: list[GapItem]
    contradictions: list[Contradiction]
    coverage_percentage: float = Field(ge=0.0, le=100.0)
    overall_assessment: str
    escalate_to_sa: bool = False  # True if gap needs SA resolution
    escalation_reason: str = ""
```

### Example 3: User Story Schema (Dual-Grouped)

```python
# Source: BA domain design per CONTEXT.md agile card format
class UserStory(BaseModel):
    """Full agile card format user story."""
    story_id: str
    as_a: str       # Role
    i_want: str     # Capability
    so_that: str    # Benefit
    acceptance_criteria: list[str]
    story_points: int = Field(ge=1, le=21)  # Fibonacci: 1,2,3,5,8,13,21
    priority: Literal["must_have", "should_have", "could_have", "wont_have"]
    epic: str
    stakeholder_domain: Literal["sales", "tech", "ops", "finance"]
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    confidence_flagged: bool = False


class UserStoryCollection(BaseModel):
    """User stories grouped by epic AND stakeholder domain."""
    stories: list[UserStory]
    epics: list[str]                      # Grouped by theme/epic
    stakeholder_groups: list[str]         # Grouped by domain
    total_story_points: int
    flagged_count: int  # Number of low-confidence stories
```

### Example 4: Process Documentation Schema

```python
class ProcessState(BaseModel):
    """A state in a process flow."""
    state_name: str
    description: str
    actors: list[str]
    systems: list[str] = Field(default_factory=list)

class ProcessDocumentation(BaseModel):
    """Current state, future state, and delta process documentation."""
    current_state: list[ProcessState]
    future_state: list[ProcessState]
    delta: list[str]  # Specific changes between current and future
    summary: str
    assumptions: list[str] = Field(default_factory=list)
```

### Example 5: Handoff Payload Schemas

```python
# Request: Sales/PM -> BA
class RequirementsAnalysisPayload(BaseModel):
    """Payload from Sales/PM Agent to BA requesting requirements analysis."""
    transcript: str
    deal_id: str
    source: Literal["meeting_transcript", "email_thread", "chat_log", "notes"] = "notes"
    deal_context: dict[str, Any] = Field(default_factory=dict)

# Response: BA -> Sales Agent
class RequirementsAnalysisResultPayload(BaseModel):
    """Payload from BA back to calling agent with analysis results."""
    gap_list: list[dict[str, Any]]
    recommended_next_action: str  # What the Sales Agent should do
    contradiction_count: int
    coverage_percentage: float
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
```

### Example 6: NotionBAAdapter Block Renderer

```python
# Source: Follows PM notion_pm.py render_wbs_to_notion_blocks pattern
def render_requirements_to_notion_blocks(doc: RequirementsDocument) -> list[dict]:
    """Convert a RequirementsDocument into Notion block objects."""
    blocks: list[dict] = []

    blocks.append(_heading_block(1, f"Requirements Analysis"))
    blocks.append(_paragraph_block(f"Summary: {doc.summary}"))
    blocks.append(_paragraph_block(f"Confidence: {doc.confidence:.0%}"))
    blocks.append({"type": "divider", "divider": {}})

    for req in doc.requirements:
        flag = " [LOW CONFIDENCE]" if req.confidence_flagged else ""
        blocks.append(_heading_block(3, f"[{req.moscow.upper()}] {req.description[:60]}{flag}"))
        blocks.append(_bulleted_block(f"Type: {req.requirement_type}"))
        blocks.append(_bulleted_block(f"Domain: {req.stakeholder_domain}"))
        blocks.append(_bulleted_block(f"Priority: {req.priority_score}"))
        if req.source_quote:
            blocks.append(_paragraph_block(f'Source: "{req.source_quote}"'))

    return blocks
```

### Example 7: Sales Agent Dispatch Trigger Detection

```python
# Keyword signals for BA dispatch (per CONTEXT.md decisions)
BA_TRIGGER_KEYWORDS = {
    "we need", "our process requires", "does it support",
    "our requirement", "must have", "can it handle",
    "we currently use", "our workflow", "business requirement",
}

# Stage threshold for BA dispatch
BA_TRIGGER_STAGES = {"evaluation", "technical_evaluation"}

@staticmethod
def _should_dispatch_to_ba(text: str, deal_stage: str) -> bool:
    """Heuristic: should this conversation trigger BA dispatch?"""
    text_lower = text.lower()
    keyword_match = any(kw in text_lower for kw in BA_TRIGGER_KEYWORDS)
    stage_match = deal_stage.lower().replace(" ", "_") in BA_TRIGGER_STAGES
    return keyword_match or stage_match
```

## Discretion Recommendations

### Handoff Type Name: `requirements_analysis`

**Recommendation:** Use `requirements_analysis` for the BA request handoff type and `requirements_analysis_result` for the response.

**Rationale:** The existing naming convention uses `{domain}_{action}`:
- SA: `technical_question` / `technical_answer`
- PM: `project_plan` / `status_report` / `risk_alert`

`requirements_analysis` follows this pattern and clearly describes the BA's purpose. Both types should use STRICT validation (consistent with SA's technical_question/answer being STRICT, since they carry structured data that downstream agents depend on).

Register in StrictnessConfig:
```python
"requirements_analysis": ValidationStrictness.STRICT,
"requirements_analysis_result": ValidationStrictness.STRICT,
```

### Product Capability Source: Existing Qdrant Knowledge Base

**Recommendation:** Use the existing Qdrant knowledge base with `content_type="product"` filter. Do NOT create a dedicated capabilities registry.

**Rationale:**
1. The product markdown files (`monetization-platform.md`, `charging.md`, `billing.md`) already contain detailed "Key Capabilities" sections with specific features listed per module.
2. The RAG pipeline already supports `content_type` filtering -- SA and PM agents already query with `content_types=["product"]`.
3. The hybrid search (dense + BM25 + RRF fusion) provides semantic matching that a simple structured registry would not.
4. Adding a new data store increases complexity with no clear benefit -- the BA agent needs to match stated requirements against what the product CAN do, which is exactly what the product docs describe.
5. If coverage is insufficient, the solution is to add more product documentation to the existing knowledge base (additive), not build a new system.

**Gap Analysis RAG Query Pattern:**
```python
rag_context = await self._query_rag(
    query=f"product capabilities features: {requirement_description}",
    tenant_id=tenant_id,
    content_types=["product"],
)
```

### Confidence Score Threshold: 0.6

**Recommendation:** Use 0.6 as the low-confidence threshold for flagging requirements and user stories.

**Rationale:** The SA agent uses 0.5/0.8 thresholds in its confidence protocol (system prompt). The 0.6 threshold for BA flagging sits between "uncertain" (0.5) and "confident" (0.8), catching items where the LLM is not highly confident but not guessing either. Requirements below 0.6 confidence get `confidence_flagged: True` and are included in output but visually marked in Notion rendering.

### Story Points: Fibonacci Numeric

**Recommendation:** Use Fibonacci numeric values (1, 2, 3, 5, 8, 13, 21) for story point estimation.

**Rationale:**
1. Fibonacci is the most widely used estimation scale in agile teams -- it communicates naturally to development teams.
2. Numeric values enable arithmetic (total story points per epic, per sprint).
3. T-shirt sizes (XS/S/M/L/XL) would require a mapping table for calculation and lose precision.
4. The Pydantic schema can enforce valid values with `Field(ge=1, le=21)` and the prompt can list the valid values explicitly.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate contradiction handler | Part of gap analysis output | CONTEXT.md decision | Simpler architecture, single handler |
| Product capability registry | Existing Qdrant KB with product filter | Research decision | No new infrastructure needed |
| T-shirt sizing | Fibonacci story points | Research decision | Enables arithmetic, standard agile |
| Single categorization | Triple categorization (type + MoSCoW + domain) | CONTEXT.md decision | Richer requirement classification |

## Open Questions

1. **PM-to-BA Dispatch Mechanism**
   - What we know: CONTEXT.md confirms PM can dispatch to BA for scope change impact analysis. The dispatch pattern (lazy import) is well-established.
   - What's unclear: Whether this should be a new handler in the PM agent (`dispatch_requirements_analysis`) or integrated into `_handle_adjust_plan` as an internal call.
   - Recommendation: Add a new `dispatch_requirements_analysis` handler in the PM agent, matching the Sales Agent pattern. This keeps handlers single-responsibility and the dispatch is explicit.

2. **Content Type for BA Outputs in Qdrant**
   - What we know: ChunkMetadata.content_type is a Literal with fixed values. SA added `competitor_analysis`, `architecture_template`, `poc_template`.
   - What's unclear: Whether BA outputs (requirements docs, user stories) should be stored in Qdrant for future retrieval. If so, a new content_type value (e.g., `requirements_document`) would need to be added to the Literal.
   - Recommendation: Defer storing BA outputs in Qdrant to a future phase. For now, BA outputs go to Notion (persistent) and as handoff payloads (transient). This avoids expanding the ChunkMetadata Literal for this phase.

## Sources

### Primary (HIGH confidence)

- `src/app/agents/solution_architect/` -- Full SA agent implementation (schemas, prompts, capabilities, agent, __init__)
- `src/app/agents/project_manager/` -- Full PM agent implementation (schemas, prompts, capabilities, agent, notion_pm, earned_value, scheduler, __init__)
- `src/app/agents/sales/agent.py` -- Sales Agent with `dispatch_technical_question` (lines 592-678) and `dispatch_project_trigger` (lines 680-743)
- `src/app/agents/base.py` -- BaseAgent, AgentRegistration, AgentCapability abstractions
- `src/app/handoffs/validators.py` -- StrictnessConfig with existing handoff type -> strictness mappings
- `src/knowledge/models.py` -- ChunkMetadata with content_type Literal values
- `src/knowledge/qdrant_client.py` -- QdrantKnowledgeStore with hybrid search and content_type filtering
- `data/products/` -- Product documentation (monetization, charging, billing) with "Key Capabilities" sections
- `tests/test_sales_sa_handoff.py` -- Round-trip test pattern for Sales->SA dispatch
- `tests/test_sales_pm_handoff.py` -- Round-trip test pattern for Sales->PM dispatch
- `src/app/main.py` -- Agent wiring pattern (lines 231-295) for SA and PM agents

### Secondary (MEDIUM confidence)

- `.planning/STATE.md` -- Architecture decisions carried forward (SA/PM patterns, lazy imports, handoff naming)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- No new dependencies; existing stack fully sufficient
- Architecture: HIGH -- Cloning proven SA/PM patterns; 5-file agent structure verified in codebase
- Pitfalls: HIGH -- All pitfalls derived from direct observation of existing code patterns
- Discretion items: HIGH -- Recommendations grounded in codebase evidence

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (30 days -- stable internal architecture)
