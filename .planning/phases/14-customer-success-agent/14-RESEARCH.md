# Phase 14: Customer Success Agent - Research

**Researched:** 2026-02-25
**Domain:** Multi-agent Python / LangGraph / Notion-first CSM agent, extending TAM template
**Confidence:** HIGH

## Summary

Phase 14 builds a Customer Success (CSM) agent that closely mirrors the Technical Account Manager agent from Phase 13. The TAM is the direct, most-recent template — every file, pattern, and naming convention in CSM should trace back to it. The codebase is inspected directly (source of truth), so findings here are HIGH confidence derived from the actual implementation rather than from third-party documentation.

The CSM differs from the TAM in three key ways: (1) it scores commercial/business health rather than technical health, combining many more signals (11 inputs vs TAM's 3); (2) it dispatches outward to the Sales Agent rather than receiving from it — introducing the first reverse handoff in the system; (3) it produces QBR pages as structured Notion documents rather than email drafts. Every other pattern — fail-open handlers, draft-only communications, scheduler structure, block renderers, tenacity retry, graceful imports, `app.state` wiring — is identical to TAM.

The expansion dispatch to Sales Agent is architecturally notable: CSM calls `dispatch_expansion_opportunity` on the Sales Agent, following the same `dispatch_*` naming convention as all existing dispatchers. The Sales Agent needs a new `dispatch_expansion_opportunity` handler and a `_is_csm_trigger` heuristic method. The QBR output is a Notion sub-page created under the account page (same structure as TAM's relationship profile sub-page pattern).

**Primary recommendation:** Clone TAM exactly, then replace health scoring formula with the 11-signal CSM scorer, add QBR generation as a Notion page (not email draft), add expansion dispatch handler, add CSMScheduler with quarterly + contract-proximity jobs, wire in main.py after Phase 13 TAM block.

## Standard Stack

All libraries are already in pyproject.toml. No new dependencies needed.

### Core (all already installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | >=2.0.0 | Domain models, `model_validator` for auto-computed flags | Established pattern in TAM (13 Pydantic models) |
| notion-client | >=2.7.0 | Notion API for all CSM data reads and QBR page writes | Notion-first architecture decision |
| apscheduler | >=3.10.0 | `AsyncIOScheduler` + `CronTrigger` for quarterly/contract-triggered jobs | Same as TAMScheduler |
| tenacity | >=9.0.0 | Retry with exponential backoff on all Notion API calls | Same as NotionTAMAdapter |
| structlog | >=24.0.0 | Structured logging throughout | Established project-wide |
| litellm (via llm_service) | >=1.60.0 | LLM for churn narrative + QBR + expansion recommendations | Same as TAM |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| google-api-python-client | >=2.0.0 | GmailService.create_draft for churn alert emails | All agent communications |
| langfuse | >=3.14.1 | LLM call tracing | Already instrumented via LiteLLM callbacks |

### Alternatives Considered
No alternatives — locked decisions require Notion-first, APScheduler, existing stack.

**Installation:** No new packages needed. All dependencies already in pyproject.toml.

## Architecture Patterns

### Recommended Project Structure

```
src/app/agents/customer_success/
├── __init__.py              # Exports: CSMAgent, create_csm_registration, all schemas
├── agent.py                 # CSMAgent(BaseAgent) with execute() router and handlers
├── capabilities.py          # CSM_CAPABILITIES list + create_csm_registration()
├── schemas.py               # All Pydantic models (CSMTask, CSMResult, CSMHandoffRequest, etc.)
├── health_scorer.py         # CSMHealthScorer - deterministic, no LLM, 11 signals
├── scheduler.py             # CSMScheduler - quarterly QBRs + contract-proximity jobs
├── notion_csm.py            # NotionCSMAdapter - account reads + QBR page writes
└── prompts.py               # CSM system prompt + 4 prompt builders
```

### Pattern 1: Agent File Layout (clone from TAM)

Each agent file follows a strict pattern established by TAM:

**`schemas.py`** — All Pydantic models. CSM needs:
- `CSMHealthSignals` — all 11 input signals as a model
- `CSMHealthScoreResult` — score + RAG + `should_alert` (auto-computed via `model_validator`)
- `ChurnRiskResult` — churn_level + narrative (LLM-generated) + trigger_type (contract_proximity | behavioral)
- `ExpansionOpportunity` — opportunity_type, evidence, estimated_arr_impact, talk_track
- `QBRPage` — structured QBR sections
- `CSMTask` — task envelope with `task_type` Literal
- `CSMResult` — result envelope, fail-open pattern
- `CSMHandoffRequest` / `CSMHandoffResponse` — for Sales Agent receiving expansion dispatches

```python
# Source: src/app/agents/technical_account_manager/schemas.py (TAM template)

class CSMHealthScoreResult(BaseModel):
    account_id: str
    score: int = Field(ge=0, le=100)
    rag_status: Literal["Green", "Amber", "Red"]
    previous_score: int | None = None
    previous_rag: str | None = None
    should_alert: bool = False  # auto-computed
    scan_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _compute_alert_flag(self) -> CSMHealthScoreResult:
        self.should_alert = (
            self.score < 40
            or (self.previous_rag is not None and self.previous_rag != "Red" and self.rag_status == "Red")
            or (self.previous_rag == "Green" and self.rag_status == "Amber")
        )
        return self
```

**`health_scorer.py`** — Pure Python, NO LLM, deterministic. TAM's docstring explicitly states: "Do NOT use LLM for score computation. The score is a deterministic numeric calculation." CSM must follow this same principle. All constructor args keyword-only for per-tenant threshold customization.

**`agent.py`** — `CSMAgent(BaseAgent)` with `execute()` dict-router. Raises `ValueError` for unknown task type (TAM pattern, not BA fail-open). All handlers fail-open on exception, returning `{"error": ..., "confidence": "low", "partial": True}`.

**`capabilities.py`** — List of `AgentCapability` + `create_csm_registration()` factory.

**`notion_csm.py`** — `NotionCSMAdapter(client, accounts_database_id)`. Takes pre-authenticated `AsyncClient`. Block renderers are module-level functions, not methods. Tenacity `@retry` on all async methods.

**`scheduler.py`** — `CSMScheduler(csm_agent, notion_csm)`. Separate class (not reusing TAMScheduler — different job logic). APScheduler optional import pattern identical to TAMScheduler.

**`prompts.py`** — `CSM_SYSTEM_PROMPT` + builders returning `str` with embedded JSON schema. Same prompt structure as TAM's 5 builders.

### Pattern 2: CSM Health Scorer — 11-Signal Weighted Formula

The CONTEXT.md marks the exact formula as "Claude's Discretion". Based on the 11 locked signals and the TAM HealthScorer pattern (start at 100, subtract penalties), the recommended approach:

```python
# Source: pattern derived from TAM health_scorer.py
# All thresholds keyword-only constructor args for per-tenant customization

class CSMHealthScorer:
    def __init__(
        self,
        *,
        # RAG thresholds
        red_threshold: int = 40,
        amber_threshold: int = 70,
        # Renewal proximity penalty triggers
        renewal_days_amber: int = 90,
        renewal_days_red: int = 60,
        # Engagement decay
        interaction_staleness_days: int = 30,
        # Usage trend
        usage_decline_penalty: int = 20,
    ) -> None: ...

    def compute_score(
        self,
        feature_adoption_rate: float,       # 0.0-1.0
        support_ticket_volume: int,          # open ticket count
        support_sentiment: str,              # "positive" | "neutral" | "negative"
        last_interaction_days: float,        # days since last meaningful interaction
        login_frequency_score: float,        # 0.0-1.0 (normalized usage)
        usage_trend: str,                    # "growing" | "stable" | "declining"
        payment_current: bool,               # invoice/payment status
        stakeholder_engagement_score: float, # 0.0-1.0
        nps_score: float | None,             # 0-10 or None if not available
        renewal_days_out: float | None,      # days until contract renewal
        seats_utilization: float,            # seats_used / seats_purchased
        escalation_history_count: int,       # number of past escalations
        tam_health_rag: str | None,          # from TAM's health_rag field on Notion
    ) -> tuple[int, str]:
        """Returns (score, rag_status)."""
```

**Recommended weighting approach:** Start at 100, apply signal-specific penalties. Heavier penalties for binary signals (payment delinquent = -30, severe usage decline = -20) vs graduated penalties for continuous signals (adoption rate below threshold scales with shortfall). TAM_health_rag input: if TAM is "Red" → apply -15 penalty; if TAM is "Amber" → apply -8 penalty; Green → no penalty.

### Pattern 3: CSMScheduler — Quarterly + Contract-Proximity Jobs

Two new job types differ from TAM's daily/monthly pattern:

```python
# Source: src/app/agents/technical_account_manager/scheduler.py (TAM template)

class CSMScheduler:
    def __init__(self, csm_agent: object, notion_csm: object | None = None) -> None: ...

    def start(self) -> bool:
        if AsyncIOScheduler is None:
            # graceful degradation -- same as TAMScheduler
            return False
        self._scheduler = AsyncIOScheduler()

        # Job 1: Daily health scan (same as TAM)
        self._scheduler.add_job(
            self._daily_health_scan,
            trigger=CronTrigger(hour=7, minute=0),
            id="csm_daily_health_scan",
            misfire_grace_time=3600,
        )

        # Job 2: Quarterly QBR generation on 1st of quarter start months
        self._scheduler.add_job(
            self._quarterly_qbr_generation,
            trigger=CronTrigger(month="1,4,7,10", day=1, hour=6, minute=0),
            id="csm_quarterly_qbr",
            name="CSM quarterly QBR generation for all active accounts",
            misfire_grace_time=7200,
        )

        # Job 3: Contract-proximity QBR check (daily, check 90-day window)
        self._scheduler.add_job(
            self._contract_proximity_qbr_check,
            trigger=CronTrigger(hour=8, minute=0),
            id="csm_contract_proximity_qbr",
            name="CSM contract-proximity QBR trigger check",
            misfire_grace_time=3600,
        )
        ...
```

The quarterly trigger uses `CronTrigger(month="1,4,7,10", day=1)` — APScheduler supports comma-separated month values for cron expressions. This is the idiomatic way to trigger on Q1/Q2/Q3/Q4 first days.

### Pattern 4: QBR Notion Page — Sub-page under Account

QBR pages are created as Notion sub-pages under the account page, exactly like TAM's relationship profiles. The PM agent (notion_pm.py) provides the pattern for richly structured pages:

```python
# Source: src/app/agents/technical_account_manager/notion_tam.py (sub-page creation)
# Pattern: create with first 100 blocks, append remainder in batches

async def create_qbr_page(
    self,
    account_page_id: str,
    account_name: str,
    qbr_data: dict,
    quarter: str,  # e.g., "Q1 2026"
) -> str:
    """Creates a QBR Notion sub-page. Returns the page_id."""
    blocks = render_qbr_blocks(qbr_data, account_name, quarter)

    page = await self._client.pages.create(
        parent={"page_id": account_page_id},
        properties={
            "title": [{"type": "text", "text": {"content": f"QBR - {account_name} - {quarter}"}}]
        },
        children=blocks[:100],  # Notion 100-block API limit
    )
    page_id = page["id"]

    # Append remaining blocks in batches of 100
    remaining = blocks[100:]
    while remaining:
        batch = remaining[:100]
        remaining = remaining[100:]
        await self._client.blocks.children.append(block_id=page_id, children=batch)

    return page_id
```

The QBR needs a dedicated Notion database (`csm_qbr_database_id`) — separate from the accounts database. This is where the QBR pages are stored as database entries, not just sub-pages. Alternatively, the CONTEXT.md says "Notion page in a CSM QBR database" which means the page IS a database entry. The NotionCSMAdapter constructor should accept both `accounts_database_id` and `qbr_database_id`.

### Pattern 5: CSM → Sales Agent Expansion Dispatch (Reverse Handoff)

This is the first reverse-direction cross-agent handoff. The pattern mirrors SA's `dispatch_tam_health_check` but CSM dispatches to Sales Agent:

**CSM side** (new handler in CSMAgent):
```python
# Source: pattern from src/app/agents/sales/agent.py _handle_dispatch_tam_health_check

async def _handle_dispatch_expansion_opportunity(
    self, task: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    account_id = task.get("account_id", "")

    # Lazy import to avoid circular dependency
    from src.app.agents.customer_success.schemas import CSMHandoffRequest

    request = CSMHandoffRequest(
        account_id=account_id,
        tenant_id=context.get("tenant_id", ""),
        opportunity_type=task.get("opportunity_type", "expansion"),
        evidence=task.get("evidence", ""),
        estimated_arr_impact=task.get("estimated_arr_impact", 0.0),
        talk_track=task.get("talk_track", ""),
    )

    return {
        "status": "dispatched",
        "handoff_task": {
            "type": "dispatch_expansion_opportunity",  # task type Sales Agent handles
            "account_id": account_id,
            "opportunity_type": request.opportunity_type,
            "evidence": request.evidence,
            "estimated_arr_impact": request.estimated_arr_impact,
            "talk_track": request.talk_track,
        },
        "target_agent_id": "sales_agent",
    }
```

**Sales Agent side** — needs a new handler `_handle_dispatch_expansion_opportunity` and new entry in its `handlers` dict, and a new `_is_csm_trigger` static method (though CSM-to-SA is push not pull, so trigger detection may not be needed — the handler is invoked directly by CSM). The Sales Agent's `execute()` `handlers` dict needs `"dispatch_expansion_opportunity"` added.

**Task type naming:** Based on the `dispatch_*` convention (`dispatch_tam_health_check`, `dispatch_ba_analysis`, `dispatch_project_trigger`, `dispatch_technical_question`), the expansion dispatch task type should be `dispatch_expansion_opportunity`.

### Pattern 6: TAM Health RAG as CSM Input

The CONTEXT.md specifies: "CSM health score should incorporate TAM's latest health_rag field from the Notion account page (read Notion, don't call TAM directly)."

This means `NotionCSMAdapter.get_account()` must read the `health_rag` Notion property that TAM writes (TAM writes "Health Status" select property via `update_health_score()`). The CSM reads this field back. No direct TAM agent method call — just a Notion property read.

```python
# Source: src/app/agents/technical_account_manager/notion_tam.py query_all_accounts()
# The TAM writes "Health Status" select property; CSM reads it

health_status_prop = props.get("Health Status", {}).get("select")
tam_health_rag = health_status_prop["name"] if health_status_prop else None
# Pass tam_health_rag into CSMHealthScorer.compute_score()
```

### Pattern 7: Churn Alert — 4-Channel Notification (Same as TAM Escalation)

The churn alert follows TAM's `_dispatch_escalation_notifications` exactly:
1. Notion: update account page with CSM health score + churn risk level
2. Event bus: publish `AgentEvent` (EventType.AGENT_HEALTH or CONTEXT_UPDATED)
3. Gmail: `create_draft` alert email for rep (NEVER `send_email`)
4. Chat: `send_message` via ChatService

Rate-limit: same max 5 alerts per daily scan run.

### Pattern 8: main.py Wiring

```python
# Source: src/app/main.py Phase 13 block (lines 329-382)
# Insert Phase 14 block after Phase 13 TAM block, before Phase 5 deals block

# -- Phase 14: Customer Success Agent ----------------------------
try:
    from src.app.agents.customer_success import (
        CSMAgent,
        create_csm_registration,
    )
    from src.app.agents.customer_success.health_scorer import CSMHealthScorer
    from src.app.agents.customer_success.scheduler import CSMScheduler

    csm_registration = create_csm_registration()
    csm_health_scorer = CSMHealthScorer()

    csm_agent = CSMAgent(
        registration=csm_registration,
        llm_service=getattr(app.state, "llm_service", None) or locals().get("llm_service"),
        gmail_service=getattr(app.state, "gmail_service", None) or locals().get("gmail_service"),
        chat_service=getattr(app.state, "chat_service", None) or locals().get("chat_service"),
        event_bus=getattr(app.state, "event_bus", None) or locals().get("event_bus"),
        health_scorer=csm_health_scorer,
        # notion_csm=None -- configured when CSM DBs initialized
    )

    agent_registry = getattr(app.state, "agent_registry", None)
    if agent_registry is not None:
        agent_registry.register(csm_registration)
    app.state.customer_success = csm_agent

    csm_scheduler = CSMScheduler(csm_agent=csm_agent, notion_csm=getattr(csm_agent, "_notion_csm", None))
    csm_scheduler_started = csm_scheduler.start()
    if csm_scheduler_started:
        app.state.csm_scheduler = csm_scheduler

    log.info("phase14.customer_success_agent_initialized")
except Exception as exc:
    log.warning("phase14.customer_success_agent_init_failed", error=str(exc))
```

Shutdown section: add `csm_scheduler_ref = getattr(app.state, "csm_scheduler", None); if csm_scheduler_ref: csm_scheduler_ref.stop()` before `await close_db()`.

### Anti-Patterns to Avoid

- **Using LLM for health score computation:** TAM's health_scorer.py explicitly forbids it. CSM must follow the same principle — the 11-signal score is deterministic pure Python.
- **Calling TAM agent directly to get health data:** CONTEXT.md specifies "read Notion, don't call TAM directly." Read `health_rag` from the Notion account page property.
- **send_email instead of create_draft:** All communications are Gmail drafts. CSM never calls `send_email`.
- **Raising exceptions in handlers instead of fail-open:** Only `execute()` raises `ValueError` for unknown task type. Individual handlers return `{"error": ..., "partial": True}` on exception.
- **Creating a QBR as email body HTML:** The QBR is a Notion page, not an email draft. Only the churn alert notification is a Gmail draft.
- **Reusing TAMScheduler with different configs:** Implement a dedicated `CSMScheduler` class. The quarterly/contract-proximity job logic is different enough to warrant a separate class (and it avoids coupling TAM and CSM lifecycle).
- **Forgetting the 100-block Notion API limit:** Notion API rejects pages with >100 blocks in creation call. Must create with `blocks[:100]` then append remainder in batches.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Notion API retry logic | Custom backoff | tenacity `@retry(stop=stop_after_attempt(3), wait=wait_exponential(...))` | Transient failures handled; same pattern as all existing adapters |
| Quarterly cron scheduling | Custom asyncio timer loop | APScheduler `CronTrigger(month="1,4,7,10", day=1)` | Already in pyproject.toml; TAMScheduler template exists |
| JSON extraction from LLM response | Custom regex | `_extract_json_from_response()` static method (clone from TAMAgent) | Handles code fences, finds first `[{` — already battle-tested |
| Notion block construction | Inline dict literals | Module-level `_heading_block`, `_paragraph_block`, `_bulleted_list_block`, `_callout_block` helpers | Pattern established in notion_tam.py |
| Agent wiring | Manual dependency injection | `getattr(app.state, "X", None) or locals().get("X")` | Established fallback pattern for optional services in main.py |

**Key insight:** Every CSM implementation detail has a TAM equivalent. Before building anything, check if TAM has the same problem solved.

## Common Pitfalls

### Pitfall 1: Circular Import Between CSM and Sales Agent
**What goes wrong:** CSM imports from `sales.schemas` to build the handoff request; Sales imports from `customer_success.schemas` to handle the expansion task. Python circular import error at startup.
**Why it happens:** The reverse handoff creates bidirectional dependency between two agent modules.
**How to avoid:** Use lazy import inside the handler method body: `from src.app.agents.customer_success.schemas import CSMHandoffRequest` inside `_handle_dispatch_expansion_opportunity`. Exactly like TAM's `from src.app.agents.technical_account_manager.schemas import TAMHandoffRequest` inside `_handle_dispatch_tam_health_check`.
**Warning signs:** `ImportError: cannot import name` at startup.

### Pitfall 2: Sales Agent Missing `dispatch_expansion_opportunity` Handler
**What goes wrong:** CSM dispatches to Sales Agent with `task_type="dispatch_expansion_opportunity"`, but Sales Agent's `handlers` dict doesn't have this key. Sales Agent raises `ValueError: Unknown task type`.
**Why it happens:** Adding a reverse handoff requires updating BOTH agents — the sender (CSM) AND the receiver (Sales Agent).
**How to avoid:** Phase 14 must include: (1) CSMAgent with dispatch handler, (2) Sales Agent update adding `dispatch_expansion_opportunity` to its `handlers` dict and implementing the handler, (3) `CSM_REQUEST_TO_TASK_TYPE` mapping dict in sales/agent.py.
**Warning signs:** Failing tests on Sales Agent with `ValueError: Unknown task type: 'dispatch_expansion_opportunity'`.

### Pitfall 3: QBR Database vs Sub-Page Confusion
**What goes wrong:** Creating QBR pages as sub-pages under the account page (like TAM relationship profiles) instead of as database entries in a dedicated QBR database.
**Why it happens:** CONTEXT.md says "Notion page in a CSM QBR database" — this means a Notion database entry, not just a child page.
**How to avoid:** `NotionCSMAdapter` needs `qbr_database_id` parameter. QBR creation uses `client.pages.create(parent={"database_id": qbr_database_id}, ...)` not `parent={"page_id": account_page_id}`. The QBR database must have appropriate properties (Account, Quarter, Health Score, Created Date) as database columns.
**Warning signs:** QBR pages can't be queried as a database; no filtering by account or quarter.

### Pitfall 4: APScheduler Quarterly Cron Expression
**What goes wrong:** Using wrong `CronTrigger` parameters for quarterly execution, causing jobs to run monthly or annually instead of on Q1/Q2/Q3/Q4 first days.
**Why it happens:** APScheduler cron syntax is not identical to Unix cron. The `month` parameter accepts comma-separated values as a string.
**How to avoid:** `CronTrigger(month="1,4,7,10", day=1, hour=6, minute=0)` — tested pattern. Month values 1, 4, 7, 10 correspond to January (Q1), April (Q2), July (Q3), October (Q4).
**Warning signs:** QBR jobs run at wrong cadence; check APScheduler job list in logs.

### Pitfall 5: CSM Health Scorer Receiving None for Optional Signals
**What goes wrong:** `compute_score()` crashes when `nps_score=None` or `renewal_days_out=None` because arithmetic is applied to None values.
**Why it happens:** Not all accounts have NPS scores or known renewal dates. These must be treated as "no data available" (like TAM's `heartbeat None = not monitored, no penalty`).
**How to avoid:** All optional signals (`nps_score`, `renewal_days_out`) must accept `None` with explicit no-penalty behavior. Mirror TAM's pattern: `if hours_since_heartbeat is not None: ...` — only apply penalty when data is present.
**Warning signs:** `TypeError: unsupported operand type(s) for <: 'NoneType' and 'int'` in health scoring.

### Pitfall 6: Missing `account_id` and `id` Keys from NotionCSMAdapter.get_account()
**What goes wrong:** CSMAgent's health scan handler accesses `account.get("account_id", "")` but `get_account()` only returns `{"id": ...}`.
**Why it happens:** TAM had this same bug and fixed it: `NotionTAMAdapter.get_account()` returns both `id` and `account_id` keys (see STATE.md: "NotionTAMAdapter.get_account returns both `id` and `account_id` keys for agent.py compatibility").
**How to avoid:** `NotionCSMAdapter.get_account()` must return `{"id": page["id"], "account_id": page["id"], ...}` — both keys, same value.
**Warning signs:** `account_id = account.get("account_id", "")` silently returns empty string; health scores logged with empty `account_id`.

### Pitfall 7: Config Settings for CSM Notion Databases
**What goes wrong:** CSM needs Notion database IDs for accounts (already in NOTION_DATABASE_ID) and a new QBR database (new setting). The config.py only has `NOTION_DATABASE_ID` and `NOTION_TOKEN`.
**Why it happens:** No `NOTION_CSM_QBR_DATABASE_ID` setting exists yet.
**How to avoid:** Add `NOTION_CSM_QBR_DATABASE_ID: str = ""` and `NOTION_CSM_ACCOUNTS_DATABASE_ID: str = ""` to `config.py Settings`. Pass these into `NotionCSMAdapter` constructor in main.py. Default to existing `NOTION_DATABASE_ID` for accounts if CSM-specific setting not set.
**Warning signs:** `ValueError: qbr_database_id not configured` at runtime.

## Code Examples

### CSMTask Literal with all 7 task types
```python
# Source: TAM pattern from src/app/agents/technical_account_manager/schemas.py

class CSMTask(BaseModel):
    task_type: Literal[
        "health_scan",           # compute health scores for one or all accounts
        "churn_risk_assessment", # assess churn risk with LLM narrative
        "qbr_generation",        # generate QBR Notion page
        "expansion_dispatch",    # identify and dispatch expansion to Sales Agent
        "adoption_coaching",     # generate feature adoption improvement recommendations
        "churn_alert",           # fire 4-channel churn alert notifications
        "update_csm_profile",    # merge CSM profile updates into Notion
    ]
    account_id: str | None = None
    tenant_id: str
    ...
```

### Block Renderers for QBR Sections
```python
# Source: src/app/agents/technical_account_manager/notion_tam.py (block helper pattern)

def render_qbr_blocks(qbr_data: dict, account_name: str, quarter: str) -> list[dict]:
    blocks: list[dict] = []

    # Section 1: Account Health Summary
    blocks.append(_heading_block(f"QBR - {account_name} - {quarter}", level=2))
    blocks.append(_heading_block("Account Health Summary", level=3))
    blocks.append(_paragraph_block(qbr_data.get("health_summary_narrative", "")))
    # ... score history bullets, RAG trend callout ...

    # Section 2: ROI & Business Impact
    blocks.append(_heading_block("ROI & Business Impact", level=3))
    blocks.append(_paragraph_block(qbr_data.get("roi_narrative", "")))
    for metric in qbr_data.get("roi_metrics", []):
        blocks.append(_bulleted_list_block(metric))

    # Section 3: Feature Adoption Scorecard
    blocks.append(_heading_block("Feature Adoption Scorecard", level=3))
    # ... adoption rate vs benchmark, underutilized features ...

    # Section 4: Expansion & Next Steps
    blocks.append(_heading_block("Expansion & Next Steps", level=3))
    # ... recommended next steps bullets ...

    return blocks
```

### CSMScheduler Quarterly Job
```python
# Source: src/app/agents/technical_account_manager/scheduler.py (TAMScheduler template)

# Quarterly QBR generation: Q1 (Jan 1), Q2 (Apr 1), Q3 (Jul 1), Q4 (Oct 1)
self._scheduler.add_job(
    self._quarterly_qbr_generation,
    trigger=CronTrigger(month="1,4,7,10", day=1, hour=6, minute=0),
    id="csm_quarterly_qbr",
    name="CSM quarterly QBR generation for all active accounts",
    misfire_grace_time=7200,  # 2-hour grace window
)

# Contract-proximity check: daily at 8 AM, checks 90-day renewal window
self._scheduler.add_job(
    self._contract_proximity_qbr_check,
    trigger=CronTrigger(hour=8, minute=0),
    id="csm_contract_proximity_qbr",
    name="CSM contract-proximity QBR trigger check (90-day window)",
    misfire_grace_time=3600,
)
```

### Churn Risk Assessment Prompt Builder Pattern
```python
# Source: src/app/agents/technical_account_manager/prompts.py (TAM prompt builder)

_CHURN_RISK_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "churn_risk_level": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
        },
        "risk_narrative": {
            "type": "string",
            "description": "2-3 sentence explanation of why this account is at risk",
        },
        "trigger_type": {
            "type": "string",
            "enum": ["contract_proximity", "behavioral", "combined"],
        },
        "recommended_actions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["churn_risk_level", "risk_narrative", "trigger_type", "recommended_actions"],
}

def build_churn_risk_assessment_prompt(
    health_score: dict,
    account_signals: dict,
    contract_info: dict,
) -> str:
    schema = json.dumps(_CHURN_RISK_SCHEMA, indent=2)
    # ... embed all signals and return prompt str with schema at end
    return (
        "**Task:** Assess churn risk for this account...\n\n"
        f"**Health score:**\n{json.dumps(health_score, indent=2)}\n\n"
        # ...
        f"Respond with ONLY a JSON object matching this schema:\n```json\n{schema}\n```"
    )
```

### Sales Agent Addition for Expansion Handler
```python
# Source: src/app/agents/sales/agent.py handlers dict (existing pattern)

# In SalesAgent.execute() handlers dict -- ADDITIONAL entry:
"dispatch_expansion_opportunity": self._handle_dispatch_expansion_opportunity,

# New static trigger dict (if needed for supervisor routing):
CSM_REQUEST_TO_TASK_TYPE = {
    "expansion_seats": "dispatch_expansion_opportunity",
    "expansion_module": "dispatch_expansion_opportunity",
    "expansion_integration": "dispatch_expansion_opportunity",
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hub-and-spoke dispatch only | Bidirectional: Sales→TAM and CSM→Sales | Phase 14 introduces | First reverse handoff; system is now fully bidirectional |
| TAM owns all account health scoring | TAM = technical layer, CSM = commercial layer | Phase 14 | Correlated but separate health tracks |
| QBR as email | QBR as structured Notion page | Phase 14 | Machine-queryable, persistent, linked to account |

**No deprecations:** All existing patterns remain valid. CSM adds to the system without replacing anything.

## Open Questions

1. **QBR Database Schema (Notion DB columns)**
   - What we know: QBR pages go into a dedicated Notion database with sections for health, ROI, adoption, expansion
   - What's unclear: The exact Notion database property columns needed (Account relation, Quarter select, Health Score number, etc.)
   - Recommendation: Define during planning. Minimum viable: Title (QBR name), Account (relation to Accounts DB), Quarter (select), Status (select: Draft/Ready), Created Date (date). The QBR content goes in the page body, not properties.

2. **Expansion Dispatch Rate Limiting**
   - What we know: TAM rate-limits escalation alerts to max 5 per scan run
   - What's unclear: CONTEXT.md doesn't specify a rate limit for expansion dispatches. These are not urgent alerts, so rate limiting may be less critical.
   - Recommendation: Apply same max-5-per-scan pattern as TAM to prevent overwhelming Sales Agent with expansion opportunities from a single daily scan.

3. **Sales Agent `_is_csm_trigger` Heuristic**
   - What we know: All trigger heuristics are static methods on the supervisor or agent class (STATE.md: "All trigger heuristics are supervisor-level static methods by established pattern")
   - What's unclear: The reverse handoff CSM→Sales is agent-to-agent direct dispatch, not conversation-triggered. A trigger heuristic may not be needed since CSM calls the Sales Agent task type directly.
   - Recommendation: No `_is_csm_trigger` needed for Phase 14. The expansion dispatch is push-based (CSM calls Sales Agent directly), not pull-based (supervisor detecting CSM intent). The Sales Agent just needs the new handler in its `execute()` dict.

4. **CSM Profile Notion Structure (sub-page vs separate database)**
   - What we know: TAM stores relationship profiles as sub-pages under account pages. CSM has different data (commercial signals, churn history, QBR history).
   - What's unclear: Whether CSM should store a "CSM Profile" sub-page under the account page (like TAM's "Technical Relationship Profile") or just use existing account page properties.
   - Recommendation: Create a "CSM Profile" sub-page under account pages for commercial relationship data (mirrors TAM sub-page pattern). This keeps commercial and technical profiles separate but both attached to the account page.

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection: `src/app/agents/technical_account_manager/` — all 7 files read in full
- Direct codebase inspection: `src/app/main.py` — Phase 13 wiring block lines 329-382
- Direct codebase inspection: `src/app/agents/sales/agent.py` — dispatch_tam_health_check handler lines 1026-1085
- Direct codebase inspection: `src/app/events/schemas.py` — AgentEvent, EventType, EventPriority
- Direct codebase inspection: `src/app/config.py` — Settings model
- Direct codebase inspection: `pyproject.toml` — all dependencies with versions

### Secondary (MEDIUM confidence)
- APScheduler CronTrigger month parameter syntax — verified from codebase usage patterns in `src/app/agents/technical_account_manager/scheduler.py` and knowledge of APScheduler 3.x API

### Tertiary (LOW confidence)
- None — all findings are from direct codebase inspection

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified from pyproject.toml, all libraries present
- Architecture: HIGH — verified from TAM source code read in full
- Pitfalls: HIGH — derived from STATE.md decisions and direct code inspection of known issues
- Scheduler cron expression: MEDIUM — derived from APScheduler pattern in TAMScheduler + knowledge of APScheduler 3.x

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable internal codebase; architecture decisions locked)
