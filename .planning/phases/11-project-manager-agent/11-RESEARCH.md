# Phase 11: Project Manager Agent - Research

**Researched:** 2026-02-23
**Domain:** Agent cloning from SA template, PMBOK-compliant project planning, earned value management, Notion CRM integration, scheduled report generation
**Confidence:** HIGH

## Summary

Phase 11 introduces the Project Manager (PM) agent as the third agent built on the proven BaseAgent template. Like the SA agent before it, the PM agent extends `BaseAgent`, registers capabilities in the `AgentRegistry`, and communicates through the existing Redis Streams event bus and handoff protocol. The PM agent is structurally a clone of the SA agent pattern (task-type routing in `execute()`, domain-specific schemas, prompt builders, capability declarations, registration factory) but with a fundamentally different domain: project lifecycle management instead of technical pre-sales.

The PM agent's domain complexity is higher than the SA agent's because it must (1) produce structured 3-level WBS project plans from SA artifacts + CRM data, (2) detect schedule risks via milestone progress analysis, (3) auto-adjust plans on scope changes with delta reports, (4) generate two-version status reports (internal + customer-facing) with earned value metrics, (5) write project records back to Notion CRM, and (6) respond to trigger events from multiple sources (deal won, POC scoped, complex deal identified, manual HITL trigger). The PM agent also introduces a scheduled cadence (weekly reports) that requires a lightweight scheduler component.

The key architectural decision is the Notion data model for project records. After analyzing the existing NotionAdapter and Notion API capabilities, the recommendation is to use a **linked Projects database** rather than extending the deals database. This approach cleanly separates project lifecycle (PM-owned) from deal lifecycle (Sales-Agent-owned), avoids property bloat on the deals database, and leverages Notion's relation properties to link projects to deals. Sub-pages under the deal page are used for project plan content (WBS, status reports, risk logs) via the Notion blocks API.

**Primary recommendation:** Clone the SA agent structure at `src/app/agents/project_manager/`, define 6 PM capabilities (create_project_plan, detect_risks, adjust_plan, generate_status_report, write_crm_records, process_trigger), extend the NotionAdapter with PM-specific methods for sub-page and linked database operations, and add a lightweight scheduler (APScheduler or asyncio-based) for weekly report cadence. Use low temperature (0.2-0.3) for all JSON-output LLM calls per established pattern.

## Standard Stack

The PM agent uses the same core stack as the SA agent -- no new libraries needed except for scheduling.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | existing | Schema definitions for PM domain models (WBS, milestones, risks, reports) | Already used throughout; BaseModel for all data types |
| structlog | existing | Structured logging for PM agent | Already used by all agents |
| litellm (via LLMService) | existing | LLM calls for plan generation, risk detection, report generation | Already abstracted in `src/app/services/llm.py` |
| notion-client | >=2.7.0 (existing) | Notion API for sub-pages, blocks, database operations | Already in pyproject.toml, used by NotionAdapter |
| redis.asyncio | existing | Event bus communication | Already used by TenantEventBus |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| APScheduler | >=3.10.0 | Lightweight async scheduler for weekly report cadence | Weekly report generation trigger; use AsyncIOScheduler |
| pytest + AsyncMock | existing | Unit tests for PM agent | All PM test files |
| jinja2 | existing | HTML template rendering for email status reports | Already in pyproject.toml from Phase 4 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| APScheduler | asyncio.create_task + sleep loop | APScheduler provides cron expressions, job persistence, and misfire handling; raw asyncio loops are fragile and miss runs on restart |
| APScheduler | Celery Beat | Celery is vastly over-engineered for a single weekly report task; APScheduler is lightweight and already async-compatible |
| Linked Projects database | Extend deals DB with PM properties | Extending deals DB causes property bloat and mixes PM/Sales ownership; linked DB provides clean separation |
| Sub-pages for plan content | Separate Notion pages unlinked | Sub-pages keep project docs nested under the deal for navigability; unlinked pages scatter content |

**Installation:**
```bash
# One new package for scheduling
pip install apscheduler>=3.10.0
```

## Architecture Patterns

### Recommended Project Structure
```
src/app/agents/project_manager/
    __init__.py              # Module exports
    agent.py                 # ProjectManagerAgent(BaseAgent) with execute() routing
    schemas.py               # PM-specific Pydantic models (ProjectPlan, WBS, Milestone, Risk, StatusReport, etc.)
    prompts.py               # PM prompt builders for each capability
    capabilities.py          # PM_CAPABILITIES list + create_pm_registration() factory
    notion_pm.py             # PM-specific Notion operations (sub-pages, linked DB, blocks)
    scheduler.py             # Weekly report scheduler (APScheduler wrapper)
    earned_value.py          # ACWP/BCWP calculation logic (pure functions, no LLM)
```

### Pattern 1: BaseAgent Task-Type Router (Clone from SA Agent)
**What:** The `execute()` method routes to specialized handlers by `task["type"]`
**When to use:** Every task the PM agent handles
**Example:**
```python
# Source: src/app/agents/solution_architect/agent.py (proven pattern)
class ProjectManagerAgent(BaseAgent):
    async def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "create_project_plan": self._handle_create_project_plan,
            "detect_risks": self._handle_detect_risks,
            "adjust_plan": self._handle_adjust_plan,
            "generate_status_report": self._handle_generate_status_report,
            "write_crm_records": self._handle_write_crm_records,
            "process_trigger": self._handle_process_trigger,
        }
        handler = handlers.get(task.get("type", ""))
        if handler is None:
            raise ValueError(f"Unknown task type: {task.get('type')!r}")
        return await handler(task, context)
```

### Pattern 2: Capability Registration (Clone from SA Agent)
**What:** Declare typed capabilities and a registration factory
**When to use:** Registering PM agent in the AgentRegistry
**Example:**
```python
# Source: src/app/agents/solution_architect/capabilities.py (proven pattern)
PM_CAPABILITIES = [
    AgentCapability(
        name="create_project_plan",
        description="Generate a PMBOK-compliant 3-level WBS project plan from deal deliverables and SA artifacts",
    ),
    AgentCapability(
        name="detect_risks",
        description="Analyze milestone progress against plan and flag predicted schedule delays",
    ),
    AgentCapability(
        name="adjust_plan",
        description="Produce a delta report showing adjusted plan when scope changes are introduced",
    ),
    AgentCapability(
        name="generate_status_report",
        description="Generate internal and customer-facing status reports with RAG, risks, and earned value metrics",
    ),
    AgentCapability(
        name="write_crm_records",
        description="Write project plan, milestones, risk log, and status reports to Notion CRM",
    ),
    AgentCapability(
        name="process_trigger",
        description="Process trigger events (deal won, POC scoped, complex deal, manual) to initiate project planning",
    ),
]

def create_pm_registration() -> AgentRegistration:
    return AgentRegistration(
        agent_id="project_manager",
        name="Project Manager",
        description=(
            "Project lifecycle management agent that creates PMBOK-compliant project plans, "
            "detects schedule risks, auto-adjusts plans on scope changes, generates status "
            "reports with earned value metrics, and integrates with CRM"
        ),
        capabilities=PM_CAPABILITIES,
        backup_agent_id=None,
        tags=["project_management", "planning", "risk", "reporting", "crm"],
        max_concurrent_tasks=3,
    )
```

### Pattern 3: Notion Data Model -- Linked Projects Database
**What:** A separate Projects database in Notion linked to the Deals database via a relation property
**When to use:** Storing all PM-specific structured data (project lifecycle, milestones, etc.)
**Why this over extending deals DB:**
- Deals database is Sales-Agent-owned territory (per CONTEXT.md locked decision)
- PM agent tracks its own project lifecycle separately
- Clean separation avoids property bloat (PM needs ~15 additional properties)
- Notion relation property creates bidirectional link

**Data Model:**
```
Projects Database (new, PM-owned)
  Properties:
    - Name (title): Project name
    - Deal (relation): Link to Deals database
    - Status (select): Planning / Active / On Hold / Completed / Cancelled
    - Overall RAG (select): Red / Amber / Green
    - Start Date (date)
    - Target End Date (date)
    - Actual End Date (date)
    - Budget Days (number): Total planned effort in person-days
    - Actual Days (number): Actual effort expended (ACWP basis)
    - BCWP (number): Budgeted Cost of Work Performed (earned value)
    - ACWP (number): Actual Cost of Work Performed
    - Risk Count (number): Active risk count
    - Last Report Date (date)
    - PM Agent Version (rich_text): For auditing
    - Change Request Count (number)

Deal page sub-pages (content, appended as blocks):
    - Project Plan (sub-page): Full WBS with phases, milestones, tasks
    - Risk & Issues Log (sub-page): Active risks with severity and owner
    - Status Report History (blocks appended): Timestamped report entries
    - Change Request Log (blocks appended): Approvals and declines
```

**Notion API Approach:**
```python
# Create Projects database (one-time setup or lazy initialization)
projects_db = await client.databases.create(
    parent={"type": "page_id", "page_id": workspace_page_id},
    title=[{"type": "text", "text": {"content": "Projects"}}],
    properties={
        "Name": {"title": {}},
        "Deal": {"relation": {"database_id": deals_database_id}},
        "Status": {"select": {"options": [
            {"name": "Planning", "color": "gray"},
            {"name": "Active", "color": "green"},
            {"name": "On Hold", "color": "yellow"},
            {"name": "Completed", "color": "blue"},
            {"name": "Cancelled", "color": "red"},
        ]}},
        "Overall RAG": {"select": {"options": [
            {"name": "Green", "color": "green"},
            {"name": "Amber", "color": "yellow"},
            {"name": "Red", "color": "red"},
        ]}},
        "Start Date": {"date": {}},
        "Target End Date": {"date": {}},
        "Budget Days": {"number": {}},
        "Actual Days": {"number": {}},
        "BCWP": {"number": {}},
        "ACWP": {"number": {}},
    }
)

# Create project plan as sub-page of deal page
plan_page = await client.pages.create(
    parent={"page_id": deal_page_id},
    properties={"title": {"title": [{"text": {"content": "Project Plan"}}]}},
    children=[
        # WBS content as blocks (headings, bulleted lists, to-dos)
        {"heading_2": {"rich_text": [{"text": {"content": "Phase 1: Discovery"}}]}},
        {"to_do": {"rich_text": [{"text": {"content": "Milestone 1.1: Requirements confirmed"}}], "checked": False}},
    ]
)
```

### Pattern 4: Three-Level WBS Schema (PMBOK-Compliant)
**What:** Phases -> Milestones -> Tasks with required fields per CONTEXT.md
**When to use:** Project plan generation
```python
class WBSTask(BaseModel):
    """Lowest level: an actionable task."""
    task_id: str
    name: str
    owner: str
    duration_days: float = Field(ge=0)
    dependencies: list[str] = Field(default_factory=list)  # task_ids
    status: Literal["not_started", "in_progress", "completed", "blocked"]

class WBSMilestone(BaseModel):
    """Middle level: a milestone grouping tasks."""
    milestone_id: str
    name: str
    target_date: datetime
    tasks: list[WBSTask]
    success_criteria: str
    status: Literal["not_started", "in_progress", "completed", "at_risk", "overdue"]

class WBSPhase(BaseModel):
    """Top level: a project phase grouping milestones."""
    phase_id: str
    name: str
    milestones: list[WBSMilestone]
    resource_estimate_days: float = Field(ge=0)

class ProjectPlan(BaseModel):
    """Complete PMBOK-compliant project plan."""
    plan_id: str
    deal_id: str
    project_name: str
    phases: list[WBSPhase]
    created_at: datetime
    version: int = 1
    trigger_source: Literal["deal_won", "poc_scoped", "complex_deal", "manual"]
```

### Pattern 5: Risk Detection Signals
**What:** Four risk trigger signals per CONTEXT.md
**When to use:** Periodic risk detection (on plan check or event-driven)
```python
class RiskSignal(BaseModel):
    """A detected risk signal."""
    risk_id: str
    signal_type: Literal[
        "milestone_overdue",          # Milestone overdue by N days
        "critical_path_blocked",       # Dependent task blocked, critical path affected
        "resource_exceeded",           # Resource estimate exceeded beyond threshold
        "deal_stage_stalled",          # No CRM activity beyond plan schedule
    ]
    severity: Literal["low", "medium", "high", "critical"]
    description: str
    affected_milestone_id: str | None = None
    recommended_action: str
    auto_adjustment: dict[str, Any] | None = None  # Plan adjustment if auto-applied
```

### Pattern 6: Earned Value Calculation (Pure Functions, No LLM)
**What:** ACWP vs BCWP calculation for status reports
**When to use:** Every status report generation
**Why pure functions:** Earned value is arithmetic, not LLM territory
```python
# earned_value.py -- pure calculation, no LLM
def calculate_earned_value(
    planned_tasks: list[WBSTask],
    actual_progress: dict[str, float],  # task_id -> % complete
    planned_budget_days: float,
    actual_days_spent: float,
) -> EarnedValueMetrics:
    """Calculate ACWP, BCWP, BCWS, and derived metrics.

    BCWP (Earned Value) = sum of (budget for each task * % complete)
    ACWP = actual cost/effort expended
    BCWS (Planned Value) = budgeted cost for work scheduled to date
    CPI = BCWP / ACWP (cost performance index)
    SPI = BCWP / BCWS (schedule performance index)
    """
    bcwp = sum(
        task.duration_days * actual_progress.get(task.task_id, 0.0)
        for task in planned_tasks
    )
    acwp = actual_days_spent
    # BCWS = planned budget * (elapsed time / total planned time)
    cpi = bcwp / acwp if acwp > 0 else 1.0
    spi = bcwp / planned_budget_days if planned_budget_days > 0 else 1.0

    return EarnedValueMetrics(bcwp=bcwp, acwp=acwp, cpi=cpi, spi=spi)
```

### Pattern 7: Two-Version Status Reports
**What:** Internal (full detail) and external (customer-facing) status reports
**When to use:** Every report generation (weekly cadence + event triggers)
```python
class InternalStatusReport(BaseModel):
    """Full-detail report for account exec + SA summary."""
    report_id: str
    project_id: str
    report_date: datetime
    overall_rag: Literal["red", "amber", "green"]
    milestone_progress: list[MilestoneProgress]  # % complete, status per milestone
    risks_and_issues: list[RiskLogEntry]  # severity, owner, status
    next_actions: list[ActionItem]  # concrete steps, owners, due dates
    earned_value: EarnedValueMetrics  # ACWP vs BCWP
    # Internal-only fields:
    deal_context: dict[str, Any]  # Full deal data
    agent_notes: str  # PM agent internal analysis
    sa_summary: str  # SA agent context for technical state

class ExternalStatusReport(BaseModel):
    """Customer-facing polished summary (subset of internal)."""
    report_id: str
    project_name: str
    report_date: datetime
    overall_status: Literal["On Track", "At Risk", "Delayed"]
    milestone_summary: list[MilestoneSummary]  # name, status, ETA (no internal details)
    key_accomplishments: list[str]
    upcoming_activities: list[str]
    items_requiring_attention: list[str]  # Polished risk summary (no severity codes)
```

### Pattern 8: Event Bus Trigger Handling
**What:** PM agent listens for trigger events from Sales Agent and SA agent
**When to use:** Initiating project plan creation
```python
# Trigger event types for PM agent:
# 1. deal_stage_changed -> closed_won: Sales Agent publishes event
# 2. poc_scoped: SA agent publishes event after POC plan generation
# 3. complex_deal_identified: Sales Agent flags RFP/large expansion
# 4. manual_trigger: HITL or API call

# EventConsumer handler for PM:
async def handle_pm_trigger(event: AgentEvent) -> None:
    """Route trigger events to PM agent for project plan creation."""
    data = event.data
    trigger_type = data.get("trigger_type")

    if trigger_type == "deal_won":
        task = {"type": "process_trigger", "trigger": "deal_won", "deal_id": data["deal_id"]}
    elif trigger_type == "poc_scoped":
        task = {"type": "process_trigger", "trigger": "poc_scoped",
                "deal_id": data["deal_id"], "poc_plan": data.get("poc_plan")}
    elif trigger_type == "complex_deal":
        task = {"type": "process_trigger", "trigger": "complex_deal",
                "deal_id": data["deal_id"]}
    elif trigger_type == "manual":
        task = {"type": "process_trigger", "trigger": "manual", **data}

    # Route through supervisor or invoke directly
    await pm_agent.invoke(task, {"tenant_id": event.tenant_id})
```

### Pattern 9: Scope Change Delta Reports
**What:** Side-by-side comparison of original vs. revised plan
**When to use:** When scope change is detected (SA updated requirements or manual input)
```python
class ScopeChangeDelta(BaseModel):
    """Delta report showing impact of scope change."""
    change_request_id: str
    original_plan_version: int
    revised_plan_version: int
    trigger: Literal["sa_updated_requirements", "manual_input"]
    changes: list[PlanDelta]  # What changed
    timeline_impact_days: int  # Positive = delay, negative = acceleration
    resource_impact_days: float  # Additional effort needed
    affected_milestones: list[str]  # Milestone IDs impacted
    risk_assessment: str  # LLM-generated risk narrative
    recommendation: Literal["approve", "approve_with_conditions", "reject_recommend_descope"]

class PlanDelta(BaseModel):
    """A single change between original and revised plan."""
    element_type: Literal["phase", "milestone", "task"]
    element_id: str
    field: str
    original_value: str
    revised_value: str
    change_type: Literal["added", "removed", "modified"]
```

### Anti-Patterns to Avoid
- **Using LLM for earned value calculations:** ACWP/BCWP is pure arithmetic. LLMs will hallucinate numbers. Use deterministic Python functions in `earned_value.py`.
- **Regenerating full plan on scope changes:** CONTEXT.md explicitly says delta report (original vs. revised), not a regenerated full document. Preserve the original plan, generate changes only.
- **PM agent changing deal stages:** CONTEXT.md explicitly says deal stages remain Sales Agent territory. PM tracks its own project lifecycle separately.
- **Single status report template with redactions:** CONTEXT.md says structurally different reports, not the same doc with redactions. Internal and external reports should use different schemas and prompt templates.
- **Blocking on CRM writes:** CRM writes should be fire-and-forget with retry. Don't block plan generation on Notion API latency.
- **Storing project plan only in Notion:** Keep the canonical plan in local state (Redis/PostgreSQL) and sync to Notion. Notion is the presentation layer, not the source of truth.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Agent registration | Custom agent registry | `AgentRegistry.register()` + `create_pm_registration()` | Registry handles discovery, backup routing, LLM context serialization |
| Event bus communication | Custom Redis pub/sub | `TenantEventBus` with `AgentEvent` schema | Existing bus handles tenant isolation, consumer groups, DLQ |
| Handoff validation | Custom payload checks | `HandoffProtocol.validate_or_reject()` | Two-layer validation (structural + semantic) already built |
| LLM provider abstraction | Direct API calls | `LLMService.completion()` | Model routing, retries, tenant metadata, injection detection |
| Email sending | Custom SMTP client | `GmailService.send_email()` | Already handles RFC 2822 threading, async wrapping, delegation |
| CRM field mapping | Custom Notion property builders | `to_notion_properties()` / `from_notion_properties()` | Extend existing NOTION_PROPERTY_MAP for PM properties |
| Cron scheduling | Custom asyncio sleep loops | APScheduler `AsyncIOScheduler` | Handles cron expressions, job persistence, misfire policies |
| JSON parsing from LLM | Custom regex extraction | `_parse_llm_json()` from SA agent pattern | Already handles code fence stripping, Pydantic validation |
| Earned value math | LLM-generated calculations | Pure Python functions in `earned_value.py` | Deterministic arithmetic should never go through an LLM |

**Key insight:** The PM agent is the third agent in the system. All infrastructure is built and tested. The PM agent provides domain-specific logic (PMBOK planning, risk detection, earned value, report generation) and extends the existing NotionAdapter for PM-specific CRM operations. The only new dependency is APScheduler for scheduled report cadence.

## Common Pitfalls

### Pitfall 1: Trying to Fit PM Data Into the Deals Database
**What goes wrong:** Adding 15+ PM-specific properties (milestones, phases, risk counts, earned value metrics) to the existing Deals Notion database.
**Why it happens:** Seems simpler than creating a new database. The existing NotionAdapter already writes to the deals DB.
**How to avoid:** Create a separate Projects database with a `relation` property linking to Deals. This follows the CONTEXT.md principle that "deal stages remain Sales Agent territory." PM data lives in a PM-owned database.
**Warning signs:** PRs that add `pm_status`, `milestone_progress`, `bcwp`, etc. as new properties on the deals database. Any PR modifying `NOTION_PROPERTY_MAP` in `field_mapping.py` with PM-specific fields.

### Pitfall 2: LLM-Generated Earned Value Numbers
**What goes wrong:** Asking the LLM to calculate ACWP, BCWP, CPI, SPI. The LLM halluccinates numbers or makes arithmetic errors.
**Why it happens:** Tempting to include EV calculations in the same prompt that generates the status report narrative.
**How to avoid:** Calculate earned value metrics in pure Python functions (`earned_value.py`) FIRST, then pass the computed metrics into the status report prompt as structured input. The LLM only narrates the implications of the metrics; it never computes them.
**Warning signs:** Any prompt that asks the LLM to "calculate BCWP" or "compute CPI."

### Pitfall 3: Notion API Rate Limiting on Bulk Writes
**What goes wrong:** Writing project plan (multiple blocks), risk log entries, and status report in rapid succession hits Notion's rate limit (3 requests/second per integration).
**Why it happens:** Eager CRM sync writing everything at once.
**How to avoid:** Use the existing tenacity retry decorator pattern from `NotionAdapter` (already configured: 3 attempts, exponential backoff 1-10s). Batch block writes using a single `blocks.children.append()` call with multiple children. Sequence writes with small delays between distinct API calls.
**Warning signs:** `APIResponseError: rate_limited` in logs during plan creation.

### Pitfall 4: Forgetting to Version Project Plans
**What goes wrong:** Scope changes overwrite the original plan, losing the baseline for delta comparison.
**Why it happens:** Treating the plan as mutable state rather than versioned artifacts.
**How to avoid:** Each plan has a `version` field. Scope changes create a new version. The delta report compares version N with version N+1. Store plan versions in local state (PostgreSQL or Redis). The Notion sub-page shows the current version, but previous versions are recoverable.
**Warning signs:** No `version` field in the ProjectPlan schema. Scope change handler modifying plan in-place rather than creating a new version.

### Pitfall 5: Same Status Report Template with Redactions
**What goes wrong:** Using one template and hiding fields for external reports, producing awkward gaps or placeholder text.
**Why it happens:** Seems DRY to have one template.
**How to avoid:** CONTEXT.md is explicit: "Two-version status reports must be structurally different, not just the same doc with redactions." Use separate Pydantic schemas (`InternalStatusReport` and `ExternalStatusReport`) and separate prompt templates. Internal includes deal context, agent notes, SA summary, full risk details. External uses polished language, milestone summary, accomplishments, and "items requiring attention" instead of risk severity codes.
**Warning signs:** A single `StatusReport` model with `is_internal: bool` flags on fields.

### Pitfall 6: Not Registering PM Handoff Types in StrictnessConfig
**What goes wrong:** PM handoffs (project_plan, status_report, risk_alert) use default STRICT validation which may add unnecessary latency for routine reports.
**Why it happens:** StrictnessConfig defaults to STRICT for unknown types.
**How to avoid:** Register PM-specific handoff types during startup: `project_plan` -> STRICT (carries structured data), `status_report` -> LENIENT (informational), `risk_alert` -> STRICT (triggers actions).
**Warning signs:** PM handoffs consistently going through semantic LLM validation when they don't need to.

### Pitfall 7: Milestone Overdue Threshold Too Aggressive
**What goes wrong:** Setting the overdue threshold to 1 day triggers constant false-positive risk alerts, flooding stakeholders with noise.
**Why it happens:** Wanting to be proactive about delays.
**How to avoid:** Use a tiered threshold based on milestone duration. Recommendation: milestone overdue alert triggers at **3 business days** for milestones of 2+ weeks duration, or **1 business day** for milestones under 1 week. This balances early warning with noise reduction. The threshold should be configurable per project.
**Warning signs:** Risk detection producing more than 5 alerts per week on a healthy project.

### Pitfall 8: Blocking Plan Generation on SA Artifact Availability
**What goes wrong:** PM agent cannot create a plan because the SA agent hasn't completed its TechnicalRequirementsDoc or POCPlan yet.
**Why it happens:** Hard dependency on SA outputs that may not exist for all trigger types.
**How to avoid:** SA artifacts are optional enrichment, not hard requirements. The PM agent can create a plan from deal data alone (deliverables, timeline, stakeholders from CRM). SA artifacts improve plan quality but their absence should not block plan creation. Use fail-open: if SA artifacts are unavailable, generate a basic plan and flag for enrichment when SA outputs arrive.
**Warning signs:** `process_trigger` handler raising errors when SA artifacts are not found.

## Code Examples

Verified patterns from the existing codebase and Notion API documentation:

### PM Agent Directory Structure (mirrors SA Agent)
```python
# src/app/agents/project_manager/__init__.py
from src.app.agents.project_manager.agent import ProjectManagerAgent
from src.app.agents.project_manager.capabilities import (
    PM_CAPABILITIES,
    create_pm_registration,
)

__all__ = [
    "ProjectManagerAgent",
    "PM_CAPABILITIES",
    "create_pm_registration",
]
```

### PM-Specific Notion Operations
```python
# src/app/agents/project_manager/notion_pm.py
# Extends NotionAdapter pattern for PM-specific CRM writes

from notion_client import AsyncClient
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

class NotionPMAdapter:
    """PM-specific Notion operations for project records.

    Operates on a linked Projects database and creates sub-pages
    under deal pages for project plan content.
    """

    def __init__(self, client: AsyncClient, projects_database_id: str) -> None:
        self._client = client
        self._projects_db_id = projects_database_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def create_project_record(self, project_data: dict) -> str:
        """Create a project record in the Projects database."""
        properties = {
            "Name": {"title": [{"text": {"content": project_data["name"]}}]},
            "Deal": {"relation": [{"id": project_data["deal_page_id"]}]},
            "Status": {"select": {"name": "Planning"}},
            "Overall RAG": {"select": {"name": "Green"}},
            "Start Date": {"date": {"start": project_data["start_date"]}},
            "Target End Date": {"date": {"start": project_data["target_end_date"]}},
            "Budget Days": {"number": project_data.get("budget_days", 0)},
        }
        page = await self._client.pages.create(
            parent={"database_id": self._projects_db_id},
            properties=properties,
        )
        return page["id"]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def create_plan_subpage(self, deal_page_id: str, plan_blocks: list[dict]) -> str:
        """Create project plan as a sub-page of the deal page."""
        page = await self._client.pages.create(
            parent={"page_id": deal_page_id},
            properties={"title": {"title": [{"text": {"content": "Project Plan"}}]}},
            children=plan_blocks,  # WBS rendered as Notion blocks
        )
        return page["id"]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def append_status_report(self, plan_page_id: str, report_blocks: list[dict]) -> None:
        """Append a status report entry to the plan page."""
        await self._client.blocks.children.append(
            block_id=plan_page_id,
            children=report_blocks,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def update_project_metrics(self, project_page_id: str, metrics: dict) -> None:
        """Update earned value and RAG status on the project record."""
        properties = {}
        if "overall_rag" in metrics:
            properties["Overall RAG"] = {"select": {"name": metrics["overall_rag"]}}
        if "acwp" in metrics:
            properties["ACWP"] = {"number": metrics["acwp"]}
        if "bcwp" in metrics:
            properties["BCWP"] = {"number": metrics["bcwp"]}
        if "actual_days" in metrics:
            properties["Actual Days"] = {"number": metrics["actual_days"]}

        if properties:
            await self._client.pages.update(
                page_id=project_page_id,
                properties=properties,
            )
```

### WBS to Notion Blocks Renderer
```python
# Converts a WBS ProjectPlan into Notion block children for sub-page creation
def render_wbs_to_notion_blocks(plan: ProjectPlan) -> list[dict]:
    """Convert a 3-level WBS into Notion blocks."""
    blocks = []
    for phase in plan.phases:
        # Phase heading
        blocks.append({
            "heading_1": {
                "rich_text": [{"text": {"content": f"Phase: {phase.name}"}}]
            }
        })
        blocks.append({
            "paragraph": {
                "rich_text": [{"text": {"content": f"Resource estimate: {phase.resource_estimate_days} days"}}]
            }
        })
        for milestone in phase.milestones:
            # Milestone heading
            blocks.append({
                "heading_2": {
                    "rich_text": [{"text": {"content": f"Milestone: {milestone.name}"}}]
                }
            })
            blocks.append({
                "paragraph": {
                    "rich_text": [{"text": {"content": f"Target: {milestone.target_date.strftime('%Y-%m-%d')} | Success: {milestone.success_criteria}"}}]
                }
            })
            for task in milestone.tasks:
                # Task as to-do item
                blocks.append({
                    "to_do": {
                        "rich_text": [{"text": {"content": f"{task.name} ({task.owner}, {task.duration_days}d)"}}],
                        "checked": task.status == "completed",
                    }
                })
    return blocks
```

### Scheduler for Weekly Reports
```python
# src/app/agents/project_manager/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

class PMScheduler:
    """Lightweight scheduler for weekly PM status reports."""

    def __init__(self, pm_agent, notion_adapter, gmail_service):
        self._scheduler = AsyncIOScheduler()
        self._pm_agent = pm_agent
        self._notion = notion_adapter
        self._gmail = gmail_service

    def start(self):
        """Start the scheduler with weekly report job."""
        self._scheduler.add_job(
            self._generate_weekly_reports,
            trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),  # Every Monday 9 AM
            id="pm_weekly_reports",
            name="Generate weekly PM status reports",
            misfire_grace_time=3600,  # 1 hour grace period
        )
        self._scheduler.start()

    async def _generate_weekly_reports(self):
        """Generate status reports for all active projects."""
        # Query active projects from Notion
        # For each project, invoke PM agent with generate_status_report task
        # Send reports via Gmail
        pass  # Implementation in agent handler

    def stop(self):
        self._scheduler.shutdown(wait=False)
```

### Email Distribution with Existing Gmail Service
```python
# Using existing GmailService and EmailMessage models
from src.app.services.gsuite.models import EmailMessage
from src.app.services.gsuite.gmail import GmailService

async def send_status_report_email(
    gmail: GmailService,
    report: InternalStatusReport | ExternalStatusReport,
    recipients: list[str],
    is_internal: bool,
) -> None:
    """Send status report via Gmail using existing integration."""
    subject_prefix = "[Internal] " if is_internal else ""
    email = EmailMessage(
        to=recipients[0],
        cc=recipients[1:] if len(recipients) > 1 else [],
        subject=f"{subject_prefix}Project Status: {report.project_name} - {report.report_date.strftime('%Y-%m-%d')}",
        body_html=render_report_html(report, is_internal),
        body_text=render_report_text(report, is_internal),
    )
    await gmail.send_email(email)
```

### Test Pattern (mirrors SA agent tests)
```python
# tests/test_project_manager.py
import pytest
from unittest.mock import AsyncMock
from src.app.agents.project_manager.agent import ProjectManagerAgent
from src.app.agents.project_manager.capabilities import create_pm_registration

@pytest.fixture
def pm_agent():
    registration = create_pm_registration()
    return ProjectManagerAgent(
        registration=registration,
        llm_service=AsyncMock(),
        notion_pm=AsyncMock(),
        gmail_service=AsyncMock(),
    )

class TestCreateProjectPlan:
    async def test_creates_plan_from_deal_data(self, pm_agent):
        pm_agent._llm_service.completion.return_value = {
            "content": '{"phases": [...], "plan_id": "plan-1"}'
        }
        result = await pm_agent.invoke(
            {"type": "create_project_plan", "deal_id": "deal-1",
             "deliverables": ["API integration", "SSO setup"]},
            {"tenant_id": "test"},
        )
        assert "phases" in result

    async def test_fail_open_on_llm_error(self, pm_agent):
        pm_agent._llm_service.completion.side_effect = RuntimeError("LLM down")
        result = await pm_agent.invoke(
            {"type": "create_project_plan", "deal_id": "deal-1"},
            {"tenant_id": "test"},
        )
        assert result.get("error") is not None
        assert result.get("partial") is True
```

## Claude's Discretion Recommendations

### 1. Overdue Threshold: 3 Business Days (Configurable)
**Recommendation:** Set the default milestone overdue threshold to **3 business days** for milestones 2+ weeks in duration, and **1 business day** for milestones under 1 week. Make this configurable per project via a `risk_thresholds` field on the ProjectPlan.
**Rationale:** 1 day is too noisy (false positives on normal variance). 5 days is too late (defeats early warning purpose). 3 days balances signal-to-noise and aligns with typical weekly reporting cadence -- stakeholders learn about risks within the same reporting week.

### 2. Notion Data Model: Linked Projects Database
**Recommendation:** Create a new **Projects database** linked to the Deals database via a Notion relation property. Do NOT extend the deals database with PM properties.
**Rationale:**
- Deals DB is Sales-Agent-owned territory (CONTEXT.md: "deal stages remain Sales Agent territory")
- PM needs ~15 additional properties that would bloat the deals DB
- A linked Projects DB provides clean ownership separation
- Notion relation property creates a bidirectional navigable link
- Sub-pages under deal pages provide project plan content (WBS, reports, risk logs)
- This is the standard Notion pattern for related-but-distinct data domains

### 3. Project Plan Notion Page Structure
**Recommendation:** The project plan is rendered as a Notion sub-page under the deal page with content organized as:
- **H1:** Project name and summary
- **H2 per phase:** Phase name with resource estimate callout
- **H3 per milestone:** Milestone name with target date, success criteria
- **To-do items per task:** Task name, owner, duration, dependency info
- **Divider** between phases
- **Status Report History section:** Appended as blocks after the WBS
- **Risk & Issues Log section:** Appended as blocks below status reports
- **Change Request Log section:** At the bottom with approval/decline status

### 4. Earned Value Calculation Method
**Recommendation:** Use the **0/100 rule** for task-level EV (tasks are either 0% or 100% complete -- no partial credit) for simplicity and auditability. This avoids the subjectivity of estimating partial task completion. Milestone-level progress is derived from the proportion of completed tasks within that milestone.
**Rationale:** The 0/100 rule is the simplest PMBOK-compliant EV method, avoids "90% complete for weeks" syndrome, and works well for the task granularity expected in this system (tasks measured in days, not months). For longer-running tasks (>5 days), consider adding a "50/50 rule" option (50% credit when started, 100% when complete) as a future enhancement.

**EV Formulas:**
- BCWP (Earned Value) = sum of planned duration for completed tasks
- ACWP (Actual Cost) = actual effort days spent across all tasks
- BCWS (Planned Value) = sum of planned duration for tasks scheduled to be complete by now
- CPI = BCWP / ACWP (>1 = under budget, <1 = over budget)
- SPI = BCWP / BCWS (>1 = ahead of schedule, <1 = behind schedule)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate agent infrastructure per role | Clone from SA/Sales Agent template | Phase 10 design decision | Zero infrastructure work per new agent |
| CRM writes blocking agent logic | Fire-and-forget with retry (tenacity) | NotionAdapter pattern (Phase 5) | Agent logic not blocked by API latency |
| Manual project status reporting | LLM-generated reports with deterministic EV metrics | This phase | Combines narrative quality with arithmetic accuracy |
| Single-version status reports | Structurally different internal vs. external reports | This phase (CONTEXT.md decision) | Appropriate detail level per audience |

**Deprecated/outdated:**
- Nothing deprecated. This is the first PM agent in the system. All infrastructure being extended is current (< 30 days old).

## Open Questions

1. **Notion Projects Database Initial Setup**
   - What we know: A Projects database needs to be created with specific properties and a relation to the Deals database
   - What's unclear: Should this be auto-created by the PM agent on first run (lazy initialization) or manually provisioned as part of deployment setup?
   - Recommendation: Lazy initialization -- the PM agent checks if the Projects database exists on first invocation and creates it if not. Store the Projects database ID in config/environment once created. This avoids manual setup steps.

2. **Project Plan Persistence Layer**
   - What we know: Plans need versioning, and Notion is the presentation layer, not the source of truth
   - What's unclear: Should plan versions be stored in PostgreSQL (new table) or Redis (JSON hash)?
   - Recommendation: PostgreSQL with a `project_plans` table (id, deal_id, version, plan_json JSONB, created_at). This matches the existing pattern of PostgreSQL as primary storage with Notion as external sync target. The SyncEngine pattern from `crm/sync.py` can be extended.

3. **APScheduler Job Persistence**
   - What we know: APScheduler supports job stores (memory, SQLAlchemy, Redis)
   - What's unclear: Does the scheduler need persistent jobs across restarts?
   - Recommendation: Start with in-memory job store (simplest). The weekly report job is re-registered on startup. If restarts during the scheduled window cause missed reports, upgrade to Redis job store later. This is a low-risk starting point.

4. **SA Artifact Retrieval**
   - What we know: PM agent needs TechnicalRequirementsDoc and POCPlan from SA agent as inputs for plan generation
   - What's unclear: How does PM find SA artifacts for a specific deal? Direct database query, event bus data, or API call?
   - Recommendation: SA artifacts should be stored in the deal's context (PostgreSQL JSONB on the opportunity record or a related table). PM agent reads them via the existing CRM/deal data path. No direct coupling to SA agent internals.

5. **Change Request Approval Workflow**
   - What we know: Change request log must track both approvals and declines (audit trail)
   - What's unclear: Who approves/declines change requests? Is there a HITL step, or does PM auto-approve within thresholds?
   - Recommendation: Auto-adjust for changes within a threshold (e.g., <10% timeline impact). Changes exceeding the threshold are flagged for HITL approval. All changes (auto and HITL) are logged with status. This aligns with the "no human approval gate for adjustments" decision in CONTEXT.md while maintaining audit trail.

## Sources

### Primary (HIGH confidence)
- `src/app/agents/base.py` -- BaseAgent abstract class, AgentCapability, AgentRegistration
- `src/app/agents/solution_architect/agent.py` -- SA agent implementation (clone template)
- `src/app/agents/solution_architect/schemas.py` -- SA domain schema patterns
- `src/app/agents/solution_architect/capabilities.py` -- Capability declaration pattern
- `src/app/agents/solution_architect/prompts.py` -- Prompt builder pattern
- `src/app/agents/supervisor.py` -- SupervisorOrchestrator (routing, decomposition, synthesis)
- `src/app/agents/registry.py` -- AgentRegistry (discovery, backup routing)
- `src/app/deals/crm/notion.py` -- NotionAdapter (CRM write patterns, retry decorators)
- `src/app/deals/crm/adapter.py` -- CRMAdapter ABC
- `src/app/deals/crm/field_mapping.py` -- Notion property mapping patterns
- `src/app/deals/schemas.py` -- Deal schemas (OpportunityRead, ChangeRecord, etc.)
- `src/app/events/bus.py` -- TenantEventBus (Redis Streams)
- `src/app/events/schemas.py` -- AgentEvent, EventType
- `src/app/events/consumer.py` -- EventConsumer with retry/DLQ
- `src/app/handoffs/protocol.py` -- HandoffProtocol (validation chain)
- `src/app/handoffs/validators.py` -- HandoffPayload, StrictnessConfig
- `src/app/services/gsuite/gmail.py` -- GmailService (email sending pattern)
- `src/app/services/gsuite/models.py` -- EmailMessage schema
- `src/app/services/llm.py` -- LLMService (completion API, model routing)
- `src/app/config.py` -- Settings (NOTION_TOKEN, NOTION_DATABASE_ID, Gmail config)
- `src/app/agents/sales/schemas.py` -- DealStage enum (shared reference)
- Context7: `/ramnes/notion-sdk-py` -- Notion API: pages.create with children, blocks.children.append, databases.create with relation property

### Secondary (MEDIUM confidence)
- `.planning/phases/10-solution-architect-agent/10-RESEARCH.md` -- Prior agent clone research (validated pattern)

### Tertiary (LOW confidence)
- APScheduler AsyncIOScheduler usage pattern -- based on training knowledge, not Context7-verified. Validated that APScheduler exists in PyPI and supports asyncio schedulers.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new core libraries; APScheduler is the only addition and it's a well-established library
- Architecture: HIGH - Direct clone of proven SA agent pattern with PM domain specialization
- Notion CRM integration: HIGH - Verified via Context7 that notion-client supports pages.create with children, databases.create with relation, blocks.children.append
- Earned value: HIGH - PMBOK EV formulas are deterministic math, verified against standard definitions
- Pitfalls: HIGH - Based on actual codebase analysis of NotionAdapter rate limiting, handoff validation, and field ownership patterns
- Scheduler: MEDIUM - APScheduler recommendation based on training knowledge; API details should be verified during implementation

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable - the template pattern and Notion API are unlikely to change)
