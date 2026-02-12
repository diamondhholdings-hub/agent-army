# Phase 5: Deal Management - Research

**Researched:** 2026-02-12
**Domain:** Deal lifecycle management -- opportunity detection from conversations, account/opportunity plan persistence, political mapping with quantitative scoring, pluggable CRM adapter pattern (PostgreSQL primary + Notion connector), and evidence-based deal stage progression
**Confidence:** HIGH

## Summary

Phase 5 builds the deal management layer on top of the existing Sales Agent (Phase 4) and Learning System (Phase 4.1). The core work spans five domains: (1) LLM-powered opportunity detection that analyzes conversation signals and autonomously creates/updates opportunities with >80% confidence threshold, (2) account and opportunity plan models as rich PostgreSQL-persisted documents with real-time updates after every conversation, (3) political mapping with structured roles and quantitative 0-10 scoring (decision power, influence, relationship strength), (4) a pluggable CRM adapter pattern with PostgreSQL as primary storage and Notion as the first external connector, and (5) automated deal stage progression driven by BANT/MEDDIC qualification evidence.

The standard approach is to extend the existing tenant-scoped database models (TenantBase pattern from Phase 1) with new tables for accounts, opportunities, stakeholders, account plans, and opportunity plans. The CRM adapter uses a Python ABC (abstract base class) defining a standard interface, with a PostgreSQL implementation as the primary backend and a Notion implementation as the first external connector. Opportunity detection and political scoring use the existing `instructor + litellm.acompletion` pattern from Phase 4 for structured LLM extraction. The existing ConversationStateModel and QualificationExtractor feed signals into the deal management system.

Key insight: This phase is heavily data-modeling and integration work. The new LLM-powered components (opportunity detection, political scoring, plan generation) follow the exact same `instructor.from_litellm(litellm.acompletion)` pattern already proven in Phase 4's QualificationExtractor. The genuinely new engineering challenge is the CRM adapter pattern and bidirectional sync with Notion.

**Primary recommendation:** Build five new SQLAlchemy models (Account, Opportunity, Stakeholder, AccountPlan, OpportunityPlan) in the tenant schema following TenantBase conventions, wire opportunity detection as a post-conversation hook in SalesAgent, implement a CRMAdapter ABC with PostgreSQL and Notion implementations, and extend the existing deal stage transition system with evidence-based auto-progression.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlalchemy[asyncio] | >=2.0.0 (already installed) | Account, Opportunity, Stakeholder, Plan models | Already in stack, TenantBase pattern established |
| pydantic | >=2.0.0 (already installed) | Schemas for plans, political maps, sync payloads | Already in stack, used throughout |
| instructor | >=1.7.0 (already installed) | Structured extraction for opportunity detection, political scoring, plan generation | Already proven in Phase 4 QualificationExtractor |
| litellm | >=1.60.0 (already installed) | LLM abstraction for all extraction/generation calls | Already in stack from Phase 1 |
| notion-client | 2.7.0 | Async Notion API client (first external CRM connector) | Official Python SDK, async support via AsyncClient, 2.7.0 is latest stable |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | >=9.0.0 (already installed) | Retry logic for Notion API rate limiting | Wrap Notion API calls with exponential backoff |
| structlog | >=24.0.0 (already installed) | Structured logging for sync operations, detection events | Already used project-wide |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| notion-client (async) | Raw httpx requests to Notion API | notion-client handles pagination, auth, API versioning; raw httpx requires manual handling |
| ABC-based adapter pattern | Protocol-based duck typing | ABCs provide explicit interface contracts and IDE support; Protocols are more Pythonic but less discoverable |
| PostgreSQL JSON columns for plans | Separate normalized tables for each plan section | JSON gives schema flexibility for plan evolution; normalized tables give query power but migration burden |

**Installation:**
```bash
pip install notion-client
```

## Architecture Patterns

### Recommended Project Structure
```
src/
  app/
    deals/                          # NEW: Deal management module
      __init__.py
      models.py                     # SQLAlchemy models: Account, Opportunity, Stakeholder, AccountPlan, OpportunityPlan
      schemas.py                    # Pydantic schemas: plan structures, political map, sync payloads
      repository.py                 # DealRepository: CRUD for all deal entities
      detection.py                  # OpportunityDetector: LLM-powered signal detection from conversations
      political.py                  # PoliticalMapper: stakeholder scoring and relationship mapping
      plans.py                      # PlanManager: account/opportunity plan generation and updates
      progression.py                # StageProgressionEngine: evidence-based auto-advancement
      crm/                          # CRM adapter subsystem
        __init__.py
        adapter.py                  # CRMAdapter ABC: interface for all CRM backends
        postgres.py                 # PostgresAdapter: primary storage (always available)
        notion.py                   # NotionAdapter: first external CRM connector
        sync.py                     # SyncEngine: bidirectional sync orchestration, conflict resolution
        field_mapping.py            # Field mapping definitions between internal schema and CRM schemas
    models/
      deals.py                      # NEW: SQLAlchemy model definitions (imported by deals/models.py)
    api/v1/
      deals.py                      # NEW: Deal management API endpoints
```

### Pattern 1: CRM Adapter Abstract Base Class
**What:** A Python ABC defining the interface all CRM backends must implement. PostgreSQL adapter is always-on primary storage. External adapters (Notion, future Salesforce/HubSpot) sync bidirectionally.
**When to use:** Every CRM read/write operation goes through the adapter.
**Example:**
```python
# Source: Python abc module + project adapter conventions
from abc import ABC, abstractmethod
from typing import Any

class CRMAdapter(ABC):
    """Abstract interface for CRM backend operations.

    All CRM backends (PostgreSQL, Notion, Salesforce, HubSpot) implement
    this interface. The SyncEngine orchestrates data flow between the
    primary PostgreSQL adapter and any configured external adapters.
    """

    @abstractmethod
    async def create_opportunity(self, opportunity: OpportunityCreate) -> str:
        """Create opportunity, return external ID."""
        ...

    @abstractmethod
    async def update_opportunity(self, external_id: str, data: OpportunityUpdate) -> None:
        """Update opportunity fields by external ID."""
        ...

    @abstractmethod
    async def get_opportunity(self, external_id: str) -> OpportunityRead | None:
        """Fetch opportunity by external ID."""
        ...

    @abstractmethod
    async def list_opportunities(self, filters: OpportunityFilter) -> list[OpportunityRead]:
        """List opportunities matching filter criteria."""
        ...

    @abstractmethod
    async def create_contact(self, contact: ContactCreate) -> str:
        """Create contact/stakeholder, return external ID."""
        ...

    @abstractmethod
    async def update_contact(self, external_id: str, data: ContactUpdate) -> None:
        """Update contact fields."""
        ...

    @abstractmethod
    async def create_activity(self, activity: ActivityCreate) -> str:
        """Log an activity (email, call, meeting)."""
        ...

    @abstractmethod
    async def get_changes_since(self, since: datetime) -> list[ChangeRecord]:
        """Fetch records changed since timestamp (for sync polling)."""
        ...
```

### Pattern 2: Opportunity Detection as Post-Conversation Hook
**What:** After every conversation interaction (process_reply, send_email, send_chat), run opportunity detection using the same `instructor.from_litellm(litellm.acompletion)` pattern. If confidence >80%, create or update opportunity autonomously.
**When to use:** Every conversation interaction in SalesAgent.
**Example:**
```python
# Source: Existing QualificationExtractor pattern from Phase 4
class OpportunityDetector:
    """LLM-powered opportunity signal detection from conversations."""

    CREATION_THRESHOLD = 0.80  # Locked decision: >80% for precision bias
    UPDATE_THRESHOLD = 0.70    # Lower bar for updating existing opportunities

    async def detect_signals(
        self,
        conversation_text: str,
        conversation_state: ConversationState,
        existing_opportunities: list[Opportunity],
    ) -> OpportunitySignals:
        """Extract opportunity signals from conversation text.

        Returns structured signals including:
        - deal_potential_confidence: float (0-1)
        - product_line: str | None
        - estimated_value: str | None
        - estimated_timeline: str | None
        - is_new_opportunity: bool (vs update to existing)
        - matching_opportunity_id: str | None
        """
        client = instructor.from_litellm(litellm.acompletion)
        return await client.chat.completions.create(
            model=self._model,
            response_model=OpportunitySignals,
            messages=self._build_detection_prompt(
                conversation_text, conversation_state, existing_opportunities
            ),
            max_tokens=2048,
            temperature=0.1,
        )
```

### Pattern 3: Political Map with Quantitative Scoring
**What:** Stakeholder records with structured roles (enum) plus three 0-10 quantitative scores. Hybrid scoring: title heuristics as baseline, LLM refinement from conversation signals, human override capability.
**When to use:** Whenever a new stakeholder is identified or conversation reveals relationship dynamics.
**Example:**
```python
# Source: CONTEXT.md locked decisions on political mapping
class StakeholderRole(str, Enum):
    DECISION_MAKER = "decision_maker"
    INFLUENCER = "influencer"
    CHAMPION = "champion"
    BLOCKER = "blocker"
    USER = "user"
    GATEKEEPER = "gatekeeper"

class StakeholderScores(BaseModel):
    """Quantitative scoring for political mapping."""
    decision_power: int = Field(ge=0, le=10, default=5)
    influence_level: int = Field(ge=0, le=10, default=5)
    relationship_strength: int = Field(ge=0, le=10, default=3)

class Stakeholder(BaseModel):
    """Political map entry for an account."""
    id: str
    account_id: str
    contact_name: str
    contact_email: str
    title: str | None = None
    roles: list[StakeholderRole]  # Multiple roles allowed
    scores: StakeholderScores
    score_evidence: dict[str, str] = {}  # score_name -> evidence text
    relationships: list[StakeholderRelationship] = []  # Links to other stakeholders
    interaction_count: int = 0
    last_interaction: datetime | None = None
    notes: str = ""
```

### Pattern 4: Account Plan and Opportunity Plan as Rich JSON Documents
**What:** Plans stored as PostgreSQL JSON columns on dedicated plan tables. Each plan has defined sections (from CONTEXT.md decisions) stored as structured JSON. Updated after every conversation -- always current.
**When to use:** Account plans for strategic view, opportunity plans for tactical deal view.
**Example:**
```python
# Source: CONTEXT.md locked plan structures
class AccountPlanData(BaseModel):
    """Account plan JSON structure (stored in account_plans.plan_data)."""

    # Company Profile
    company_profile: CompanyProfile = Field(default_factory=CompanyProfile)
    # Relationship History
    relationship_history: RelationshipHistory = Field(default_factory=RelationshipHistory)
    # Strategic Positioning
    strategic_positioning: StrategicPositioning = Field(default_factory=StrategicPositioning)
    # Active Opportunities (list/links)
    active_opportunity_ids: list[str] = Field(default_factory=list)

class OpportunityPlanData(BaseModel):
    """Opportunity plan JSON structure (stored in opportunity_plans.plan_data)."""

    # Core Deal Info
    core_deal: CoreDealInfo = Field(default_factory=CoreDealInfo)
    # MEDDIC/BANT Tracking (with evidence and confidence scores)
    qualification_tracking: QualificationTracking = Field(default_factory=QualificationTracking)
    # Stakeholder Map
    stakeholder_map: list[StakeholderSummary] = Field(default_factory=list)
    # Action Items & Next Steps
    action_items: list[ActionItem] = Field(default_factory=list)
```

### Pattern 5: Bidirectional CRM Sync with Field-Level Conflict Resolution
**What:** SyncEngine orchestrates data flow between PostgreSQL (primary) and external CRM adapters. Uses polling-based change detection with configurable interval. Conflict resolution: agent-side wins by default for agent-owned fields, CRM-side wins for human-edited fields.
**When to use:** When external CRM adapter is configured for a tenant.
**Example:**
```python
# Source: Bidirectional CRM sync best practices
class SyncEngine:
    """Orchestrates bidirectional sync between primary and external CRM."""

    def __init__(
        self,
        primary: CRMAdapter,          # Always PostgreSQL
        external: CRMAdapter | None,  # Notion, Salesforce, etc.
        field_ownership: FieldOwnershipConfig,
    ) -> None:
        self._primary = primary
        self._external = external
        self._ownership = field_ownership
        self._last_sync: datetime | None = None

    async def sync_outbound(self, changes: list[ChangeRecord]) -> SyncResult:
        """Push changes from primary to external CRM."""
        ...

    async def sync_inbound(self) -> SyncResult:
        """Pull changes from external CRM to primary."""
        changes = await self._external.get_changes_since(self._last_sync)
        for change in changes:
            resolved = self._resolve_conflict(change)
            await self._primary.apply_change(resolved)
        ...

    def _resolve_conflict(self, change: ChangeRecord) -> ChangeRecord:
        """Field-level conflict resolution.

        Rules:
        - Agent-owned fields (qualification, scores, plan sections):
          agent wins unless human explicitly overrode in CRM
        - Human-owned fields (custom notes, manual overrides):
          CRM wins always
        - Shared fields (stage, value, close date):
          last-write-wins with timestamp comparison
        """
        ...
```

### Pattern 6: Evidence-Based Stage Progression
**What:** Extend the existing `VALID_TRANSITIONS` from Phase 4's `state_repository.py` with a progression engine that auto-advances deals when qualification evidence meets stage-specific thresholds.
**When to use:** After every qualification signal update.
**Example:**
```python
# Source: Existing state_repository.py VALID_TRANSITIONS + CONTEXT.md decisions
STAGE_EVIDENCE_REQUIREMENTS: dict[DealStage, StageRequirements] = {
    DealStage.DISCOVERY: StageRequirements(
        min_bant_completion=0.0,
        min_meddic_completion=0.0,
        min_interactions=1,
        required_signals=["need_identified"],
    ),
    DealStage.QUALIFICATION: StageRequirements(
        min_bant_completion=0.25,  # At least 1/4 BANT
        min_meddic_completion=0.17,  # At least 1/6 MEDDIC
        min_interactions=2,
        required_signals=["need_identified", "pain_identified"],
    ),
    DealStage.EVALUATION: StageRequirements(
        min_bant_completion=0.50,  # At least 2/4 BANT
        min_meddic_completion=0.33,  # At least 2/6 MEDDIC
        min_interactions=3,
        required_signals=["budget_identified", "authority_identified"],
    ),
    DealStage.NEGOTIATION: StageRequirements(
        min_bant_completion=0.75,  # At least 3/4 BANT
        min_meddic_completion=0.50,  # At least 3/6 MEDDIC
        min_interactions=4,
        required_signals=["economic_buyer_identified", "decision_criteria_identified"],
    ),
}
```

### Anti-Patterns to Avoid
- **Monolithic CRM class:** Do NOT put all CRM logic in one giant class. The adapter pattern exists so each backend is independently testable and replaceable. The SyncEngine coordinates, adapters implement.
- **Tight coupling between opportunity detection and CRM write:** Do NOT write to CRM directly in the detection code. Detection produces signals; a separate handler decides whether to create/update and routes through the adapter.
- **Storing plans as flat columns:** Do NOT create 30+ columns for plan sections. Use JSON columns with Pydantic validation -- plans evolve frequently and JSON gives schema flexibility without migrations.
- **Real-time sync on every write:** Do NOT call the external CRM API synchronously during every agent action. Batch outbound changes and sync on a configurable interval (e.g., every 30-60 seconds). This avoids Notion's 3 req/sec rate limit becoming a bottleneck.
- **Duplicating qualification logic:** Do NOT rebuild BANT/MEDDIC extraction. The existing `QualificationExtractor` and `ConversationState.qualification` already track this data. The opportunity detection and stage progression engines CONSUME this existing data.
- **Polling Notion for changes without tracking `last_edited_time`:** Do NOT fetch all records on every sync cycle. Use Notion's `last_edited_time` property to filter only changed records since last sync.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Notion API client | Custom HTTP client with auth | `notion-client` AsyncClient | Handles pagination, auth, API versioning, rate limit headers |
| BANT/MEDDIC extraction | New extraction pipeline | Existing `QualificationExtractor` from Phase 4 | Already built, tested, handles merge logic |
| Deal stage transitions | New state machine | Existing `VALID_TRANSITIONS` + `validate_stage_transition()` from Phase 4 | Already enforces valid transitions, STALLED handling |
| Conversation state persistence | New repository | Existing `ConversationStateRepository` from Phase 4 | Already handles upsert, stage validation, qualification merge |
| Event publishing for deal changes | Custom notification system | Existing `TenantEventBus` from Phase 2 | Tenant-scoped Redis Streams, consumer groups |
| Retry logic for external APIs | Custom retry loops | `tenacity` library (already installed) | Handles exponential backoff, jitter, max retries |
| Structured LLM extraction | Custom JSON parsing | `instructor.from_litellm(litellm.acompletion)` pattern from Phase 4 | Proven pattern with validation, retry on schema violation |

**Key insight:** Phase 5 extends Phase 4's data model and adds the CRM integration layer. The LLM extraction patterns are identical to Phase 4. The genuinely new work is: (a) new database models/migrations for accounts, opportunities, stakeholders, and plans, (b) the CRM adapter abstraction with Notion implementation, (c) sync engine with conflict resolution, and (d) wiring opportunity detection as a hook into the existing SalesAgent flow.

## Common Pitfalls

### Pitfall 1: Notion API Rate Limiting (3 req/sec)
**What goes wrong:** Agent creates opportunity in PostgreSQL, immediately tries to sync to Notion, hits 429 rate limit, sync fails silently or blocks the agent response.
**Why it happens:** Notion's rate limit is 3 requests/second average per integration. A single opportunity create + stakeholder creates + activity log can easily exceed this.
**How to avoid:** Batch outbound sync on a timer (30-60 second intervals). Queue changes in a Redis list or PostgreSQL sync_queue table. Use tenacity with exponential backoff (respect Retry-After header). Never make Notion calls synchronously in the agent's response path.
**Warning signs:** HTTP 429 errors in logs, sync operations taking >5 seconds, agent response latency spikes.

### Pitfall 2: Notion API Version Breaking Changes (2025-09-03)
**What goes wrong:** Code works in development but breaks when Notion users have multi-source databases. The 2025-09-03 API version replaced `database_id` with `data_source_id` for most operations.
**Why it happens:** Notion's API version 2025-09-03 introduced multi-source databases as a non-backward-compatible change. Existing integrations fail when users add additional data sources.
**How to avoid:** Use API version 2025-09-03 from the start. Always resolve `data_source_id` from database before making queries. Use the `data_sources.query()` endpoint instead of `databases.query()`. The `notion-client` 2.7.0 SDK supports this.
**Warning signs:** "validation_error" responses from Notion API, missing data in query results.

### Pitfall 3: Opportunity Duplication on High-Volume Conversations
**What goes wrong:** Multiple rapid conversation turns each trigger opportunity detection independently, creating duplicate opportunities for the same deal.
**Why it happens:** Race condition -- two replies processed concurrently both detect the same opportunity signal, both pass the >80% threshold, both create new opportunities.
**How to avoid:** Use a mutex/lock per (tenant_id, account_id) when creating opportunities. Before creating, always check existing opportunities for the same account with similar product line and timeline. The detection prompt should include existing opportunities to enable the LLM to identify matches.
**Warning signs:** Multiple identical opportunities for the same account, opportunity count grows faster than actual deals.

### Pitfall 4: Plan Documents Growing Without Bounds
**What goes wrong:** Account and opportunity plans accumulate historical data (relationship history, past interactions) without pruning, making them too large for LLM context windows.
**Why it happens:** "Real-time updates after every conversation" means plans grow linearly with interaction count.
**How to avoid:** Set maximum sizes for list fields (e.g., relationship_history.key_events capped at 50, interaction_summaries at 20). Use summarization for older entries. When plan JSON exceeds a threshold (e.g., 50KB), trigger a consolidation that summarizes old entries and archives detail.
**Warning signs:** Plan JSON exceeding 100KB, LLM context compilation failing due to token limits, slow plan read/write operations.

### Pitfall 5: Political Score Drift Without Evidence
**What goes wrong:** Title-based heuristic scores never get updated from conversation evidence, or conversation signals overwrite legitimate manual overrides.
**Why it happens:** The hybrid scoring system (title heuristics -> LLM refinement -> human override) needs clear precedence rules and evidence tracking.
**How to avoid:** Track score source for each dimension: "heuristic", "conversation_signal", "human_override". Human overrides always win. Conversation signals can only increase confidence, never decrease without strong counter-evidence. Store evidence text alongside each score so transparency is maintained.
**Warning signs:** Scores staying at initial heuristic values indefinitely, human overrides being reverted by the next conversation.

### Pitfall 6: Sync Conflict Resolution Ambiguity
**What goes wrong:** A human updates opportunity stage in Notion to "Closed Won" while the agent's qualification data shows the deal is still in Evaluation. Which wins?
**Why it happens:** Bidirectional sync without clear field ownership rules.
**How to avoid:** Define explicit field ownership categories:
- **Agent-owned:** qualification_data, confidence_score, political_scores, plan_sections (agent wins)
- **Human-owned:** custom_notes, manual_tags, override_stage (CRM wins)
- **Shared:** deal_stage, estimated_value, close_date (last-write-wins with timestamp)
Record every sync conflict in a sync_log table for audit and debugging.
**Warning signs:** Stage oscillating between two values, data "resetting" after sync cycles.

### Pitfall 7: Missing Alembic Migration for New Tables
**What goes wrong:** New deal management tables exist in code but not in the database. Tests pass with create_all() but production breaks.
**Why it happens:** Forgetting to create Alembic migrations for new TenantBase models, or not running them across all tenant schemas.
**How to avoid:** Create a new Alembic migration for each batch of new tables. Follow the exact pattern from `add_sales_conversation_state.py` -- use `context.get_x_argument` for schema name, enable RLS, create policies, add indexes. Use `migrate_all_tenants()` from `alembic/tenant.py` to apply to all tenants.
**Warning signs:** "relation does not exist" errors in production, tables missing from specific tenant schemas.

## Code Examples

Verified patterns from official sources and existing codebase:

### SQLAlchemy Model for Opportunities (TenantBase Pattern)
```python
# Source: Existing src/app/models/sales.py pattern
from src.app.core.database import TenantBase

class OpportunityModel(TenantBase):
    """Opportunity/deal record in tenant schema."""

    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "account_id", "external_id",
            name="uq_opportunity_tenant_account_external",
        ),
        Index("idx_opportunities_tenant_stage", "tenant_id", "deal_stage"),
        Index("idx_opportunities_tenant_account", "tenant_id", "account_id"),
        {"schema": "tenant"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)  # Notion page ID, etc.
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    product_line: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deal_stage: Mapped[str] = mapped_column(
        String(50), default="prospecting", server_default=text("'prospecting'")
    )
    estimated_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability: Mapped[float] = mapped_column(Float, default=0.1, server_default=text("0.1"))
    close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detection_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(50), default="agent_detected")  # agent_detected, manual, imported
    qualification_snapshot: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'::json")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True,
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,  # Last sync with external CRM
    )
```

### Notion Adapter Implementation
```python
# Source: notion-client 2.7.0 AsyncClient + Notion API 2025-09-03
from notion_client import AsyncClient
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class NotionAdapter(CRMAdapter):
    """Notion database adapter for CRM operations."""

    def __init__(self, token: str, database_id: str) -> None:
        self._client = AsyncClient(auth=token)
        self._database_id = database_id
        self._data_source_id: str | None = None  # Resolved lazily

    async def _ensure_data_source(self) -> str:
        """Resolve data_source_id from database (API 2025-09-03 requirement)."""
        if self._data_source_id is None:
            db = await self._client.databases.retrieve(self._database_id)
            # Get first data source from database
            sources = db.get("data_sources", [])
            if sources:
                self._data_source_id = sources[0]["id"]
            else:
                self._data_source_id = self._database_id  # Fallback for simple DBs
        return self._data_source_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),  # Refine to APIResponseError
    )
    async def create_opportunity(self, opportunity: OpportunityCreate) -> str:
        """Create a page in the Notion deals database."""
        ds_id = await self._ensure_data_source()
        page = await self._client.pages.create(
            parent={"data_source_id": ds_id},
            properties=self._map_opportunity_to_notion_properties(opportunity),
        )
        return page["id"]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def get_changes_since(self, since: datetime) -> list[ChangeRecord]:
        """Query Notion for records modified since timestamp."""
        ds_id = await self._ensure_data_source()
        results = await self._client.data_sources.query(
            data_source_id=ds_id,
            filter={
                "property": "Last edited time",
                "last_edited_time": {"after": since.isoformat()},
            },
        )
        return [self._notion_page_to_change_record(page) for page in results["results"]]
```

### Opportunity Detection Prompt Pattern
```python
# Source: Existing QualificationExtractor prompt pattern from Phase 4
def build_opportunity_detection_prompt(
    conversation_text: str,
    conversation_state_summary: str,
    existing_opportunities: list[dict],
) -> list[dict]:
    """Build prompt for opportunity signal extraction."""
    existing_opps_text = "\n".join(
        f"- {opp['name']} (Stage: {opp['deal_stage']}, Product: {opp.get('product_line', 'unknown')}, "
        f"Timeline: {opp.get('close_date', 'unknown')})"
        for opp in existing_opportunities
    ) or "No existing opportunities for this account."

    return [
        {
            "role": "system",
            "content": (
                "You are analyzing a sales conversation to detect opportunity signals. "
                "Look for: budget mentions, specific product interest, timeline urgency, "
                "pain points with quantifiable impact, buying process indicators, "
                "competitive evaluation mentions.\n\n"
                "IMPORTANT: Only flag a new opportunity if confidence is HIGH (>0.8). "
                "Prefer updating existing opportunities over creating new ones.\n\n"
                "A NEW opportunity should only be created if:\n"
                "1. Different product line from existing opportunities, OR\n"
                "2. Significantly different timeline (>3 months apart)\n\n"
                f"Existing opportunities for this account:\n{existing_opps_text}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Conversation State:\n{conversation_state_summary}\n\n"
                f"Latest Conversation:\n{conversation_text}\n\n"
                "Extract opportunity signals with confidence scores."
            ),
        },
    ]
```

### Repository Pattern with session_factory
```python
# Source: Existing ConversationStateRepository pattern from Phase 4
class DealRepository:
    """Async CRUD for deal management entities."""

    def __init__(
        self, session_factory: Callable[..., AsyncGenerator[AsyncSession, None]]
    ) -> None:
        self._session_factory = session_factory

    async def create_opportunity(
        self, tenant_id: str, data: OpportunityCreate
    ) -> Opportunity:
        async for session in self._session_factory():
            model = OpportunityModel(
                tenant_id=uuid.UUID(tenant_id),
                account_id=data.account_id,
                name=data.name,
                product_line=data.product_line,
                deal_stage=data.deal_stage,
                estimated_value=data.estimated_value,
                detection_confidence=data.detection_confidence,
                source=data.source,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _model_to_opportunity(model)

    async def find_matching_opportunity(
        self,
        tenant_id: str,
        account_id: str,
        product_line: str | None,
        timeline_months: int | None,
    ) -> Opportunity | None:
        """Find existing opportunity that matches for dedup."""
        async for session in self._session_factory():
            stmt = select(OpportunityModel).where(
                OpportunityModel.tenant_id == uuid.UUID(tenant_id),
                OpportunityModel.account_id == account_id,
                OpportunityModel.deal_stage.notin_(["closed_won", "closed_lost"]),
            )
            if product_line:
                stmt = stmt.where(OpportunityModel.product_line == product_line)
            result = await session.execute(stmt)
            return _model_to_opportunity(result.scalar_one_or_none())
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Notion `database_id` for queries | `data_source_id` required (API 2025-09-03) | Sep 2025 | Must resolve data_source_id before queries; non-backward-compatible |
| Notion `databases.query()` endpoint | `data_sources.query()` endpoint | Sep 2025 | Different endpoint namespace for querying |
| Manual CRM data entry | LLM-powered auto-detection from conversations | 2024-2025 | Qualification signals extracted in real-time, no human data entry needed |
| Record-level sync conflict resolution | Field-level conflict resolution with ownership rules | 2024+ | Different fields can have different "winner" rules |
| Single BANT or MEDDIC framework | Combined BANT + MEDDIC with confidence scores | Already in Phase 4 | Already implemented in QualificationExtractor |

**Deprecated/outdated:**
- Notion API `databases/{id}/query` endpoint: Still works on older API versions but will break when users adopt multi-source databases. Use `data_sources/{id}/query` instead.
- Single-source-of-truth CRM pattern: Modern approach is primary storage (PostgreSQL) + sync to external CRM, not treating external CRM as sole source of truth. This ensures agent always has data access even if external CRM is down.

## Open Questions

Things that couldn't be fully resolved:

1. **Notion API Version in notion-client 2.7.0**
   - What we know: notion-client 2.7.0 was released Oct 2025. Notion API 2025-09-03 was released Sep 2025. The SDK should support the new API version.
   - What's unclear: Whether notion-client 2.7.0 defaults to the 2025-09-03 API version or requires explicit version header. The `data_sources` namespace appeared in search results for the SDK.
   - Recommendation: During implementation, verify by initializing `AsyncClient(auth=token, notion_version="2025-09-03")` and testing `data_sources.query()`. If the SDK doesn't support it yet, fall back to raw httpx calls for data_source operations.

2. **Notion Database Schema Setup**
   - What we know: The Notion adapter needs a pre-configured database with specific property columns (Deal Name, Stage, Value, Close Date, etc.).
   - What's unclear: Whether we should auto-create the Notion database via API or require manual setup. The Notion API does support database creation.
   - Recommendation: Provide a setup utility that creates the Notion database with correct schema, but also support connecting to an existing database. Include a schema validation step that checks required properties exist.

3. **Sync Frequency vs Rate Limits**
   - What we know: Notion allows 3 req/sec average. A full sync cycle (query changes + push updates) can require multiple requests.
   - What's unclear: Optimal polling interval that balances freshness with rate limit headroom.
   - Recommendation: Start with 60-second polling interval. Each cycle: 1 query for changes + N updates. With 3 req/sec, a 60-second window allows ~180 requests. Monitor actual usage and adjust. For real-time needs, consider longer intervals with event-driven triggers for high-priority changes.

4. **Plan Generation Quality**
   - What we know: Account and opportunity plans need to be generated from accumulated conversation data and qualification signals.
   - What's unclear: How much plan content should be LLM-generated vs structured data assembly. Heavy LLM use means higher cost and latency per conversation.
   - Recommendation: Use structured data assembly for core fields (deal info, qualification tracking, stakeholder list). Use LLM only for narrative sections (strategic positioning, relationship insights). Cache generated narratives and only regenerate when underlying data changes significantly.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/app/models/sales.py`, `src/app/agents/sales/schemas.py`, `src/app/agents/sales/qualification.py`, `src/app/agents/sales/state_repository.py`, `src/app/agents/sales/agent.py` -- established patterns for TenantBase models, Pydantic schemas, instructor extraction, session_factory repositories
- Existing codebase: `src/app/events/bus.py`, `src/app/events/schemas.py` -- TenantEventBus for deal change events
- Existing codebase: `src/app/core/database.py` -- TenantBase, get_tenant_session, schema_translate_map pattern
- Existing codebase: `alembic/versions/add_sales_conversation_state.py` -- migration template with RLS and indexes
- [Notion API Request Limits](https://developers.notion.com/reference/request-limits) -- 3 req/sec, 429 + Retry-After, 500KB payload limit
- [Notion API 2025-09-03 Upgrade Guide](https://developers.notion.com/docs/upgrade-guide-2025-09-03) -- data_source_id replaces database_id

### Secondary (MEDIUM confidence)
- [notion-client PyPI](https://pypi.org/project/notion-client/) -- v2.7.0, Oct 2025, async support via AsyncClient
- [notion-sdk-py GitHub](https://github.com/ramnes/notion-sdk-py) -- data_sources.query() method, pagination utilities
- [Stacksync CRM Conflict Resolution](https://www.stacksync.com/blog/deep-dive-stacksyncs-conflict-resolution-engine-for-bidirectional-crm-integration) -- field-level conflict resolution patterns, ownership rules
- [Instructor Library](https://python.useinstructor.com/) -- 3M+ monthly downloads, from_litellm integration pattern

### Tertiary (LOW confidence)
- Notion API 2025-09-03 `data_sources` namespace support in notion-client 2.7.0 -- needs validation during implementation (SDK released 1 month after API version)
- Optimal sync polling interval (60s recommendation) -- theoretical, needs tuning based on actual Notion API usage patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All core libraries already installed except notion-client. Patterns directly extend existing Phase 4 code.
- Architecture: HIGH -- CRM adapter pattern is well-established (ABC + implementations). Data models follow proven TenantBase conventions.
- Opportunity detection: HIGH -- Uses identical instructor + litellm pattern from Phase 4 QualificationExtractor, just different prompt/schema.
- Political mapping: HIGH -- Straightforward Pydantic models + SQLAlchemy persistence. Scoring heuristics well-documented in sales methodology literature.
- CRM sync: MEDIUM -- Notion adapter pattern is clear, but 2025-09-03 API version support in SDK needs validation. Conflict resolution rules are sound in principle but need iteration in practice.
- Pitfalls: HIGH -- Notion rate limits officially documented, opportunity dedup is a known CRM integration challenge, migration patterns established.

**Research date:** 2026-02-12
**Valid until:** 2026-03-14 (30 days -- core libraries stable, Notion API may evolve)
