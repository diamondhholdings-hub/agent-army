# Phase 10: Solution Architect Agent - Research

**Researched:** 2026-02-22
**Domain:** Agent cloning from Sales Agent template, LLM-driven technical analysis, inter-agent handoff
**Confidence:** HIGH

## Summary

Phase 10 introduces the first new agent built on the proven Sales Agent template. The Solution Architect (SA) agent extends `BaseAgent`, registers 5 capabilities in the `AgentRegistry`, and communicates with the Sales Agent through the existing Redis Streams event bus and handoff protocol. The SA does not need GSuite services, QBS engines, or qualification extractors -- instead it needs LLM-powered technical analysis capabilities and its own knowledge domain (architecture templates, competitor data, POC templates) stored in the existing Qdrant `knowledge_base` collection with `content_type` filtering.

This is fundamentally a "clone and specialize" operation. The Sales Agent (`src/app/agents/sales/`) provides the exact structural pattern: a BaseAgent subclass with task-type routing in `execute()`, domain-specific schemas, prompt builders, capability declarations, and a registration factory. The SA agent replaces sales-domain logic with solution architecture logic while preserving all orchestration patterns (supervisor routing, handoff validation, event bus communication).

**Primary recommendation:** Mirror the Sales Agent directory structure at `src/app/agents/solution_architect/`, define 5 SA capabilities (requirements_mapping, architecture_narrative, poc_scoping, objection_response, technical_handoff), and reuse the existing Qdrant knowledge_base collection with new `content_type` values for SA-specific knowledge (competitor_analysis, architecture_template, poc_template). The inter-agent handoff for SA-05 uses the existing event bus with a new `technical_question`/`technical_answer` handoff type registered in the StrictnessConfig.

## Standard Stack

The SA agent uses the same stack as the Sales Agent -- no new libraries are needed.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | existing | Schema definitions for SA domain models | Already used throughout; BaseModel for all data types |
| structlog | existing | Structured logging for SA agent | Already used by all agents |
| litellm (via LLMService) | existing | LLM calls for technical analysis | Already abstracted in `src/app/services/llm.py` |
| qdrant-client | existing | Vector store for SA knowledge | Already used by knowledge base |
| redis.asyncio | existing | Event bus communication | Already used by TenantEventBus |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest + AsyncMock | existing | Unit tests for SA agent | All SA test files |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Shared knowledge_base collection | Separate SA Qdrant collection | Separate collection adds operational overhead for marginal benefit; payload filtering on content_type is sufficient and follows existing pattern |
| New event stream per agent | Shared "handoffs" stream | Shared stream with event_type filtering is simpler; per-agent streams add routing complexity |

**Installation:**
```bash
# No new packages needed -- SA uses existing dependencies
```

## Architecture Patterns

### Recommended Project Structure
```
src/app/agents/solution_architect/
    __init__.py              # Module exports
    agent.py                 # SolutionArchitectAgent(BaseAgent) with execute() routing
    schemas.py               # SA-specific Pydantic models (TechRequirement, ArchNarrative, POCPlan, etc.)
    prompts.py               # SA prompt builders for each capability
    capabilities.py          # SA_AGENT_CAPABILITIES list + create_sa_registration() factory
    knowledge.py             # SA knowledge ingestion helpers (competitor data, arch templates)
```

### Pattern 1: BaseAgent Task-Type Router (Clone from Sales Agent)
**What:** The `execute()` method routes to specialized handlers by `task["type"]`
**When to use:** Every task the SA agent handles
**Example:**
```python
# Source: src/app/agents/sales/agent.py (proven pattern)
class SolutionArchitectAgent(BaseAgent):
    async def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "map_requirements": self._handle_map_requirements,
            "generate_architecture": self._handle_generate_architecture,
            "scope_poc": self._handle_scope_poc,
            "respond_objection": self._handle_respond_objection,
            "technical_handoff": self._handle_technical_handoff,
        }
        handler = handlers.get(task.get("type", ""))
        if handler is None:
            raise ValueError(f"Unknown task type: {task.get('type')!r}")
        return await handler(task, context)
```

### Pattern 2: Capability Registration (Clone from Sales Agent)
**What:** Declare typed capabilities and a registration factory
**When to use:** Registering SA agent in the AgentRegistry
**Example:**
```python
# Source: src/app/agents/sales/capabilities.py (proven pattern)
SA_AGENT_CAPABILITIES = [
    AgentCapability(
        name="requirements_mapping",
        description="Map technical requirements from sales conversations and meeting transcripts into structured requirement documents",
    ),
    AgentCapability(
        name="architecture_narrative",
        description="Generate architecture overview narratives for proposed solutions tailored to prospect technical stack",
    ),
    AgentCapability(
        name="poc_scoping",
        description="Scope POCs with deliverables, timeline, resource estimates, and success criteria",
    ),
    AgentCapability(
        name="objection_response",
        description="Prepare technical objection responses based on product knowledge and competitor weakness data",
    ),
    AgentCapability(
        name="technical_handoff",
        description="Receive technical questions from Sales Agent and return structured technical answers",
    ),
]

def create_sa_registration() -> AgentRegistration:
    return AgentRegistration(
        agent_id="solution_architect_agent",
        name="Solution Architect Agent",
        description="Technical guidance agent that maps requirements, generates architecture narratives, scopes POCs, and responds to technical objections",
        capabilities=SA_AGENT_CAPABILITIES,
        backup_agent_id=None,
        tags=["technical", "architecture", "poc", "objection_handling", "requirements"],
        max_concurrent_tasks=3,
    )
```

### Pattern 3: LLM-Powered Analysis with Single Call (Locked Decision)
**What:** Each SA handler makes a single LLM call with a comprehensive prompt, not multiple per-field calls
**When to use:** Every handler -- follows the locked architecture decision "single LLM call for all signals"
**Example:**
```python
async def _handle_map_requirements(self, task, context):
    # Single LLM call extracts ALL requirements from transcript
    prompt = build_requirements_mapping_prompt(
        transcript=task["transcript"],
        product_context=rag_context,
    )
    response = await self._llm_service.completion(
        messages=prompt, model="reasoning", temperature=0.2, max_tokens=4096,
    )
    # Parse structured output (JSON) from LLM response
    requirements = parse_requirements_response(response["content"])
    return {"status": "mapped", "requirements": requirements.model_dump()}
```

### Pattern 4: Event Bus Handoff (SA-05)
**What:** Sales Agent publishes a `technical_question` event; SA agent consumes it, processes, and publishes `technical_answer` back
**When to use:** SA-05 integration requirement
**Example:**
```python
# Sales Agent side (in router rules or supervisor decomposition):
# Deterministic routing rule: if task contains "technical" keywords -> route to SA agent
router.add_rule(
    lambda task: task.get("type") == "technical_question",
    "solution_architect_agent"
)

# OR via event bus for async handoff:
event = AgentEvent(
    event_type=EventType.HANDOFF_REQUEST,
    tenant_id=tenant_id,
    source_agent_id="sales_agent",
    call_chain=["user", "supervisor", "sales_agent"],
    data={"question": "...", "deal_context": {...}},
    correlation_id=correlation_id,
)
await bus.publish("handoffs", event)
```

### Pattern 5: SA Knowledge in Existing Qdrant Collection
**What:** SA-specific knowledge uses the existing `knowledge_base` Qdrant collection with `content_type` filtering
**When to use:** Storing and retrieving competitor data, architecture templates, POC templates
**Example:**
```python
# SA knowledge chunks use existing ChunkMetadata with new content_type values
# Current content_type Literal: "product", "methodology", "regional", "positioning", "pricing"
# Extend to include: "competitor_analysis", "architecture_template", "poc_template"
#
# Retrieval via existing hybrid_search with content_type filter:
chunks = await knowledge_store.hybrid_search(
    query_text="cloud-native microservices integration",
    tenant_id=tenant_id,
    filters={"content_type": "architecture_template"},
)
```

### Pattern 6: Fail-Open Throughout (Locked Decision)
**What:** LLM errors return fallback responses, never 500
**When to use:** Every SA handler must have a fallback
**Example:**
```python
try:
    response = await self._llm_service.completion(...)
    requirements = parse_requirements_response(response["content"])
except Exception as exc:
    logger.warning("sa_requirements_mapping_failed", error=str(exc))
    requirements = TechRequirementsDoc(
        requirements=[],
        confidence=0.0,
        error="Analysis unavailable - LLM service error",
    )
return {"status": "mapped", "requirements": requirements.model_dump()}
```

### Anti-Patterns to Avoid
- **Multiple LLM calls per handler:** Locked decision says single LLM call for all signals. Don't call LLM once for "functional requirements" and again for "non-functional requirements" -- extract everything in one call.
- **New Qdrant collection for SA:** The existing `knowledge_base` collection already supports multi-content-type filtering. Adding a separate collection creates operational overhead without benefit.
- **Skipping handoff validation:** Every SA agent output that goes back to the supervisor or Sales Agent must go through the HandoffProtocol. Don't bypass it.
- **Auto-sending technical responses without human review:** SA generates responses; humans review before sending to prospects. Same pattern as Sales Agent's NEGOTIATION guardrail.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Agent registration | Custom agent registry | `AgentRegistry.register()` + `create_sa_registration()` | Registry handles discovery, backup routing, LLM context serialization |
| Event bus communication | Custom Redis pub/sub | `TenantEventBus` with `AgentEvent` schema | Existing bus handles tenant isolation, consumer groups, DLQ |
| Handoff validation | Custom payload checks | `HandoffProtocol.validate_or_reject()` | Two-layer validation (structural + semantic) already built and tested |
| LLM provider abstraction | Direct API calls | `LLMService.completion()` | Handles model routing, retries, tenant metadata, prompt injection detection |
| Knowledge retrieval | Direct Qdrant queries | `QdrantKnowledgeStore.hybrid_search()` | Handles tenant isolation, dense+sparse fusion, per-tenant HNSW indexes |
| Prompt injection detection | Custom filtering | `LLMService` built-in sanitization | Already detects instruction override, role hijacking, system prompt exfiltration |
| Task routing | Manual if/else dispatching | `HybridRouter.add_rule()` for deterministic SA routing | Rules-based for known patterns, LLM fallback for ambiguous |

**Key insight:** The entire orchestration infrastructure (registry, router, supervisor, handoff protocol, event bus, knowledge store, LLM service) is already built and tested. The SA agent only needs to provide domain-specific logic -- prompts, schemas, and handler implementations. Zero infrastructure work.

## Common Pitfalls

### Pitfall 1: Overcomplicating the Knowledge Model
**What goes wrong:** Building a separate Qdrant collection, custom embedding pipeline, or new storage layer for SA knowledge (competitor data, architecture templates, POC templates).
**Why it happens:** Feels like SA knowledge is "different" from sales knowledge. It isn't -- it's still text chunks with metadata filters in the same tenant-scoped collection.
**How to avoid:** Use the existing `knowledge_base` collection. Extend the `ChunkMetadata.content_type` Literal to include SA-specific types. Use the existing `IngestionPipeline` to load SA knowledge documents.
**Warning signs:** Any PR that creates a new Qdrant collection or new embedding configuration for SA.

### Pitfall 2: Coupling SA Agent Directly to Sales Agent Code
**What goes wrong:** Importing Sales Agent internals (QualificationExtractor, QBSEngine, ConversationState) into SA agent code.
**Why it happens:** SA needs deal context from the Sales Agent. Tempting to reach into Sales Agent's state repository directly.
**How to avoid:** SA receives context via handoff payload (task dict + context dict). The supervisor compiles working context before invoking the SA. SA never reads Sales Agent's ConversationStateRepository directly.
**Warning signs:** SA agent importing from `src.app.agents.sales.*` (except possibly `schemas.DealStage` for shared enums).

### Pitfall 3: Forgetting Fail-Open on LLM Errors
**What goes wrong:** SA handlers raise exceptions on LLM failures, causing 500 errors or agent status stuck in ERROR.
**Why it happens:** Happy path coding without error handling for each handler.
**How to avoid:** Every handler must wrap the LLM call in try/except and return a degraded but valid response. The `BaseAgent.invoke()` method catches exceptions and sets status to ERROR, but the supervisor then tries backup agents -- so it's better to return fallback than throw.
**Warning signs:** Any SA handler without try/except around LLM calls.

### Pitfall 4: Missing Handoff Type Registration
**What goes wrong:** SA handoffs use type strings like `"technical_question"` or `"technical_answer"` but these aren't registered in `StrictnessConfig`, defaulting to STRICT validation which may be unnecessary overhead for routine technical Q&A.
**Why it happens:** StrictnessConfig defaults to STRICT for unknown types (correct fail-safe), but explicit registration allows intentional configuration.
**How to avoid:** Register SA-specific handoff types in StrictnessConfig during startup: `technical_question` -> STRICT, `technical_answer` -> STRICT (these carry technical data that should be validated).
**Warning signs:** SA handoffs being validated at unexpected strictness levels.

### Pitfall 5: Not Adding Deterministic Routing Rules
**What goes wrong:** All SA tasks go through the LLM router instead of fast deterministic routing.
**Why it happens:** Forgetting to register rules in the HybridRouter for known SA task types.
**How to avoid:** Register deterministic routing rules for SA task types (e.g., `task["type"] == "map_requirements"` -> `solution_architect_agent`). LLM routing should only be for ambiguous cases.
**Warning signs:** SA tasks consistently showing `routed_by: "llm"` instead of `routed_by: "rules"`.

### Pitfall 6: content_type Literal Not Extended
**What goes wrong:** Trying to store SA knowledge chunks with content_type="competitor_analysis" fails Pydantic validation because the Literal type only allows existing values.
**Why it happens:** The `ChunkMetadata.content_type` field is a `Literal["product", "methodology", "regional", "positioning", "pricing"]`. SA needs additional types.
**How to avoid:** Extend the Literal union in `src/knowledge/models.py` to include SA-specific content types BEFORE ingesting SA knowledge. This is a shared model change that affects all agents.
**Warning signs:** Pydantic ValidationError when upserting SA knowledge chunks.

## Code Examples

Verified patterns from the existing codebase:

### SA Agent Directory Structure (mirrors Sales Agent)
```python
# src/app/agents/solution_architect/__init__.py
from src.app.agents.solution_architect.agent import SolutionArchitectAgent
from src.app.agents.solution_architect.capabilities import (
    SA_AGENT_CAPABILITIES,
    create_sa_registration,
)

__all__ = [
    "SolutionArchitectAgent",
    "SA_AGENT_CAPABILITIES",
    "create_sa_registration",
]
```

### SA Domain Schemas
```python
# src/app/agents/solution_architect/schemas.py
from pydantic import BaseModel, Field
from enum import Enum

class RequirementCategory(str, Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    INTEGRATION = "integration"
    SECURITY = "security"
    PERFORMANCE = "performance"
    SCALABILITY = "scalability"
    COMPLIANCE = "compliance"

class TechRequirement(BaseModel):
    """A single technical requirement extracted from conversation."""
    requirement_id: str
    category: RequirementCategory
    description: str
    priority: str = "medium"  # "low", "medium", "high", "critical"
    source_quote: str = ""  # Evidence from transcript
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)

class TechRequirementsDoc(BaseModel):
    """Structured requirements document output."""
    requirements: list[TechRequirement]
    prospect_stack: list[str] = Field(default_factory=list)
    integration_points: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)

class ArchitectureNarrative(BaseModel):
    """Architecture overview narrative output."""
    executive_summary: str
    current_state: str  # Prospect's current architecture
    proposed_integration: str  # How Skyvera integrates
    data_flow: str  # Data flow description
    deployment_model: str  # Cloud, on-prem, hybrid
    security_considerations: str
    scalability_notes: str
    diagrams_suggested: list[str] = Field(default_factory=list)

class POCPlan(BaseModel):
    """Proof of concept plan output."""
    objective: str
    deliverables: list[str]
    timeline_weeks: int
    milestones: list[dict]  # {"name": str, "week": int, "deliverable": str}
    resource_estimates: dict  # {"role": "count"} e.g. {"sa": 1, "developer": 2}
    success_criteria: list[str]
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

class TechObjectionResponse(BaseModel):
    """Technical objection response output."""
    objection: str
    response: str
    evidence: list[str]  # Product facts supporting the response
    competitor_comparison: dict = Field(default_factory=dict)  # {"competitor": "weakness"}
    follow_up_questions: list[str] = Field(default_factory=list)
```

### SA Handoff from Sales Agent (SA-05)
```python
# Deterministic routing rule added during agent setup:
router.add_rule(
    lambda task: task.get("type") in (
        "map_requirements", "generate_architecture",
        "scope_poc", "respond_objection", "technical_handoff",
    ),
    "solution_architect_agent",
)

# Handoff type registration in StrictnessConfig:
strictness_config.register_rule("technical_question", ValidationStrictness.STRICT)
strictness_config.register_rule("technical_answer", ValidationStrictness.STRICT)

# Sales Agent escalation to SA (via supervisor):
# When Sales Agent encounters a technical question beyond its scope:
# 1. Sales Agent returns a result indicating "needs_sa_review"
# 2. Supervisor decomposes and routes to SA agent
# 3. SA processes and returns structured answer
# 4. Supervisor synthesizes or passes through to Sales Agent
```

### SA Knowledge Integration
```python
# Extend content_type in src/knowledge/models.py:
content_type: Literal[
    "product", "methodology", "regional", "positioning", "pricing",
    "competitor_analysis", "architecture_template", "poc_template",
]

# SA knowledge documents go in data/sa_knowledge/ directory
# Ingested via existing IngestionPipeline:
results = await pipeline.ingest_directory(
    dir_path=Path("data/sa_knowledge"),
    tenant_id="esw-default",
    recursive=True,
)

# Retrieved with content_type filter during SA analysis:
competitor_chunks = await store.hybrid_search(
    query_text="competitor cloud billing scalability",
    tenant_id=tenant_id,
    filters={"content_type": "competitor_analysis"},
)
```

### Test Pattern (mirrors existing test structure)
```python
# tests/test_solution_architect.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.app.agents.solution_architect.agent import SolutionArchitectAgent
from src.app.agents.solution_architect.capabilities import create_sa_registration

@pytest.fixture
def sa_agent():
    registration = create_sa_registration()
    return SolutionArchitectAgent(
        registration=registration,
        llm_service=AsyncMock(),
        rag_pipeline=AsyncMock(),
    )

class TestRequirementsMapping:
    async def test_maps_requirements_from_transcript(self, sa_agent):
        sa_agent._llm_service.completion.return_value = {
            "content": '{"requirements": [...], "confidence": 0.9}'
        }
        result = await sa_agent.invoke(
            {"type": "map_requirements", "transcript": "We need API integration..."},
            {"tenant_id": "test"},
        )
        assert result["status"] == "mapped"
        assert "requirements" in result

    async def test_fail_open_on_llm_error(self, sa_agent):
        sa_agent._llm_service.completion.side_effect = RuntimeError("LLM down")
        result = await sa_agent.invoke(
            {"type": "map_requirements", "transcript": "..."},
            {"tenant_id": "test"},
        )
        assert result["status"] == "mapped"
        assert result["requirements"]["confidence"] == 0.0
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate agent infrastructure per role | Clone from Sales Agent template | v2.0 design decision | Zero infrastructure work per new agent |
| Per-agent Qdrant collections | Shared collection with content_type filtering | Knowledge base design (Phase 3) | One collection, payload-based isolation |
| Custom inter-agent communication | Redis Streams event bus with handoff protocol | Agent Orchestration (Phase 2) | Standard handoff validation for all agents |

**Deprecated/outdated:**
- Nothing deprecated. This is the first time the agent cloning pattern is being used. The Sales Agent template is 10 days old and current.

## Open Questions

Things that couldn't be fully resolved:

1. **SA Knowledge Data Sources**
   - What we know: SA needs competitor analysis data, architecture templates, and POC templates in Qdrant
   - What's unclear: Where does the actual content come from? Are there existing Skyvera competitor analysis documents? Architecture reference documents?
   - Recommendation: Create seed data templates with placeholder content that matches the schema. Real content can be ingested later through the existing pipeline. Do not block phase execution on content availability.

2. **Shared Enums Between Agents**
   - What we know: SA needs to reference `DealStage` enum from Sales Agent schemas for context
   - What's unclear: Should shared enums live in a common module, or should SA import from Sales Agent?
   - Recommendation: For now, import `DealStage` from `src.app.agents.sales.schemas`. If more agents need it, refactor to a shared module (e.g., `src/app/agents/shared/schemas.py`) in a later phase. Avoid premature abstraction.

3. **content_type Literal Extension Impact**
   - What we know: Extending `ChunkMetadata.content_type` Literal affects a shared model used by all agents
   - What's unclear: Will existing tests break if the Literal is extended? (They shouldn't -- adding values to a Literal doesn't invalidate existing values)
   - Recommendation: Extend the Literal, run existing tests to verify no breakage. This is a safe, additive change.

4. **SA Agent Constructor Dependencies**
   - What we know: Sales Agent constructor takes 12+ dependencies (LLM service, Gmail, Chat, RAG, state repo, qualification, etc.)
   - What's unclear: SA agent needs fewer dependencies (no GSuite, no qualification, no QBS) -- how minimal should the constructor be?
   - Recommendation: SA agent constructor needs only: `registration`, `llm_service`, `rag_pipeline` (for knowledge retrieval), and optionally `state_repository` (for persisting SA analysis results per deal). Keep it lean.

## Sources

### Primary (HIGH confidence)
- `src/app/agents/base.py` -- BaseAgent abstract class, AgentCapability, AgentRegistration
- `src/app/agents/sales/agent.py` -- SalesAgent implementation (template pattern)
- `src/app/agents/sales/capabilities.py` -- Capability declaration and registration factory
- `src/app/agents/sales/schemas.py` -- Domain schema patterns (Pydantic models)
- `src/app/agents/sales/prompts.py` -- Prompt builder pattern
- `src/app/agents/supervisor.py` -- SupervisorOrchestrator (routing, decomposition, synthesis)
- `src/app/agents/registry.py` -- AgentRegistry (discovery, backup routing)
- `src/app/agents/router.py` -- HybridRouter (rules + LLM routing)
- `src/app/events/bus.py` -- TenantEventBus (Redis Streams)
- `src/app/events/schemas.py` -- AgentEvent, EventType
- `src/app/events/consumer.py` -- EventConsumer with retry/DLQ
- `src/app/handoffs/protocol.py` -- HandoffProtocol (validation chain)
- `src/app/handoffs/validators.py` -- HandoffPayload, StrictnessConfig
- `src/knowledge/qdrant_client.py` -- QdrantKnowledgeStore (hybrid search, tenant isolation)
- `src/knowledge/models.py` -- KnowledgeChunk, ChunkMetadata (content_type Literal)
- `src/knowledge/config.py` -- KnowledgeBaseConfig
- `.planning/REQUIREMENTS.md` -- SA-01 through SA-05 requirement definitions
- `.planning/ROADMAP.md` -- Phase 10 success criteria
- `.planning/STATE.md` -- Architecture decisions carried forward

### Secondary (MEDIUM confidence)
- `tests/test_handoffs.py` -- Test patterns for handoff validation
- `src/knowledge/products/esw_data.py` -- Knowledge ingestion helper pattern

### Tertiary (LOW confidence)
- None. All findings are from direct codebase analysis.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new libraries; entire stack is existing and verified
- Architecture: HIGH - Direct clone of proven Sales Agent pattern with domain specialization
- Pitfalls: HIGH - Based on actual codebase analysis of shared models, routing, and handoff patterns
- Knowledge model: HIGH - Existing Qdrant collection with content_type filtering is documented and tested
- Inter-agent handoff (SA-05): HIGH - Event bus, handoff protocol, and routing all exist and are tested

**Research date:** 2026-02-22
**Valid until:** 2026-03-22 (stable - the template pattern is unlikely to change)
