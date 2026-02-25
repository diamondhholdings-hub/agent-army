# Phase 15: Collections Agent - Research

**Researched:** 2026-02-25
**Domain:** AR aging tracking, payment risk scoring, escalation state machine, collection message generation, payment plan surfacing
**Confidence:** HIGH — based entirely on direct codebase inspection of CSM (Phase 14) and TAM (Phase 13) patterns

## Summary

Phase 15 implements the Collections Agent following the exact same dual-layer pattern established by CSM (Phase 14) and TAM (Phase 13): a deterministic pure-Python scorer produces the numeric risk score and RAG band; an LLM generates the human-readable narrative. All communications are Gmail drafts — nothing sends autonomously. The agent wires into main.py lifespan using the identical try/except pattern as every prior agent.

The Collections Agent is structurally identical to CSM: same BaseAgent subclass, same handler-based execute() dispatch, same fail-open semantics, same NotionAdapter with tenacity retry, same APScheduler-based scheduler. The primary novelty is the 5-stage escalation state machine (with time-floor and non-response tracking), the payment risk scorer (4 signals vs CSM's 11), and the payment plan surfacing logic via LLM inference.

The most important integration constraint: CSMHealthSignals currently lacks the `collections_risk` field noted in STATE.md decision 14-02. That field needs to be added to CSMHealthSignals before the Collections agent can feed risk into it. Collections risk feeds into CSM health scoring as a cap (same as TAM feeds CSM via `tam_health_rag`).

**Primary recommendation:** Build Collections Agent directly following the CSM pattern — copy the structural skeleton (agent.py, schemas.py, prompts.py, scorer.py, notion_adapter.py, scheduler.py) and replace domain logic. Do not deviate from established patterns without explicit reason.

## Standard Stack

### Core (already in project — no new installs needed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | v2 | Schema models, model_validators, model_json_schema() | Established project standard |
| notion-client | >=2.7.0 | Notion AsyncClient for AR aging + escalation records | Same as CSM/TAM adapters |
| tenacity | latest | Retry + exponential backoff on all Notion writes | Pattern: stop_after_attempt(3), wait_exponential(1,1,10) |
| apscheduler | latest | AsyncIOScheduler + CronTrigger for daily AR scan | Same as TAM/CSM schedulers |
| structlog | latest | Structured logging bound to agent_id | All agents use this |
| src.app.services.gsuite.gmail | project | GmailService.create_draft() | All notifications are drafts |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| src.app.agents.base | project | BaseAgent, AgentRegistration, AgentCapability | All agent implementations |
| src.app.events.schemas | project | AgentEvent, EventType, EventPriority | Event bus publishing |

**Installation:** No new dependencies needed. All required libraries are already installed in the project.

## Architecture Patterns

### File Structure (mirrors CSM exactly)
```
src/app/agents/collections/
├── __init__.py              # Export CollectionsAgent + create_collections_registration
├── schemas.py               # Pydantic models (ARAgingRecord, PaymentRiskSignals, etc.)
├── scorer.py                # Pure Python deterministic PaymentRiskScorer
├── prompts.py               # Prompt builders with embedded model_json_schema()
├── handlers.py              # 5 task handlers (ar_aging, risk_assessment, message_generation, escalation, payment_plan)
├── agent.py                 # BaseAgent subclass — execute() routing + handler registration
├── notion_adapter.py        # NotionCollectionsAdapter with tenacity retry
└── scheduler.py             # CollectionsScheduler with APScheduler
```

### Pattern 1: Deterministic Scorer (same as CSM + TAM)
**What:** Pure Python class with no LLM. Score is truth; LLM adds narrative.
**When to use:** All numeric risk scoring. Never use LLM in scorer.

```python
# Source: src/app/agents/customer_success/health_scorer.py (direct pattern copy)
class PaymentRiskScorer:
    """Compute payment risk score (0-100, higher = MORE risk) from 4 signals.

    NOTE: Inverted from CSM — higher score = WORSE for collections.

    Signal weights (total = 100):
        days_overdue:           40  (primary driver)
        payment_history_streak: 30  (consecutive late = higher risk)
        total_outstanding_balance: 20  (absolute dollar amount)
        days_to_contract_renewal: 10  (renewal proximity adds urgency)

    RAG derivation (inverted from CSM: high score = bad):
        score < green_threshold: GREEN (low risk)
        score < amber_threshold: AMBER (medium risk)
        score >= amber_threshold: RED (high risk)
        score >= critical_threshold AND critical breach: CRITICAL

    All thresholds configurable via constructor kwargs.
    """
    def __init__(
        self,
        *,
        green_threshold: float = 30.0,
        amber_threshold: float = 60.0,
        critical_threshold: float = 85.0,
    ) -> None: ...

    def score(
        self,
        signals: "PaymentRiskSignals",
        account_id: str = "",
    ) -> "PaymentRiskResult": ...
```

### Pattern 2: Schema Models with model_validator
**What:** Pydantic v2 models using model_validator(mode="after") for auto-computed fields.
**When to use:** Whenever a field can be derived from other fields (e.g., should_alert, risk_band).

```python
# Source: src/app/agents/customer_success/schemas.py (direct pattern)
from pydantic import BaseModel, Field, model_validator

class PaymentRiskResult(BaseModel):
    account_id: str
    score: float = Field(ge=0.0, le=100.0)
    risk_band: Literal["GREEN", "AMBER", "RED", "CRITICAL"]
    should_escalate: bool = False
    risk_narrative: str = ""
    signal_breakdown: dict[str, float] = Field(default_factory=dict)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _compute_escalate_flag(self) -> "PaymentRiskResult":
        self.should_escalate = self.risk_band in ("RED", "CRITICAL")
        return self
```

### Pattern 3: Agent execute() Router
**What:** dict-based handler dispatch, raises ValueError for unknown task types.
**When to use:** All agents. Never fail-open on unknown task type.

```python
# Source: src/app/agents/customer_success/agent.py
async def execute(self, task: dict, context: dict) -> dict:
    task_type = task.get("type", "")
    handlers = {
        "ar_aging_scan": self._handle_ar_aging_scan,
        "payment_risk_assessment": self._handle_payment_risk_assessment,
        "generate_collection_message": self._handle_generate_collection_message,
        "process_escalation": self._handle_process_escalation,
        "surface_payment_plan": self._handle_surface_payment_plan,
    }
    handler = handlers.get(task_type)
    if handler is None:
        raise ValueError(
            f"Unknown task type: {task_type!r}. "
            f"Supported: {', '.join(handlers.keys())}"
        )
    return await handler(task, context)
```

### Pattern 4: Notion Adapter with tenacity retry
**What:** All Notion API calls decorated with @retry using stop_after_attempt(3) + wait_exponential.
**When to use:** Every single Notion method without exception.

```python
# Source: src/app/agents/customer_success/notion_adapter.py
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

class NotionCollectionsAdapter:
    def __init__(self, notion_client: AsyncClient) -> None:
        self._client = notion_client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def create_ar_aging_record(self, record: "ARAgingRecord") -> str: ...

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def update_escalation_stage(self, page_id: str, stage: int, ...) -> None: ...
```

### Pattern 5: Prompt Builders with embedded model_json_schema()
**What:** Module-level prompt builder functions return str. Schema embedded via model_json_schema().
**When to use:** All LLM prompt construction. Never pass schema separately.

```python
# Source: src/app/agents/customer_success/prompt_builders.py
import json
from src.app.agents.collections.schemas import CollectionMessage, PaymentPlanOptions

_MESSAGE_SCHEMA = CollectionMessage.model_json_schema()

def build_collection_message_prompt(
    account_data: dict,
    ar_data: dict,
    stage: int,
    calibration_factors: dict,
) -> str:
    schema = json.dumps(_MESSAGE_SCHEMA, indent=2)
    # ... build prompt string with embedded schema
    return (
        "**Task:** Generate a collection message for Stage {stage}...\n\n"
        f"Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )
```

### Pattern 6: Scheduler with APScheduler
**What:** CollectionsScheduler wraps AsyncIOScheduler with graceful ImportError handling.
**When to use:** Daily AR scan (runs at 6:00 AM), daily escalation check (runs at 6:30 AM).

```python
# Source: src/app/agents/customer_success/scheduler.py
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    AsyncIOScheduler = None
    CronTrigger = None

class CollectionsScheduler:
    def start(self) -> bool:
        if AsyncIOScheduler is None:
            logger.warning("collections_scheduler_unavailable", reason="apscheduler not installed")
            return False
        self._scheduler = AsyncIOScheduler()
        # Job 1: Daily AR aging scan at 6:00 AM
        self._scheduler.add_job(
            self._daily_ar_scan,
            trigger=CronTrigger(hour=6, minute=0),
            id="collections_daily_ar_scan",
            misfire_grace_time=3600,
        )
        # Job 2: Daily escalation check at 6:30 AM
        self._scheduler.add_job(
            self._daily_escalation_check,
            trigger=CronTrigger(hour=6, minute=30),
            id="collections_daily_escalation_check",
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        self._started = True
        return True
```

### Pattern 7: main.py Lifespan Wiring
**What:** Each agent phase wires in lifespan with try/except, stores on app.state.
**When to use:** Required for all agents.

```python
# Source: src/app/main.py — Phase 14 CSM block (direct template)
try:
    from src.app.agents.collections import CollectionsAgent, create_collections_registration
    from src.app.agents.collections.scorer import PaymentRiskScorer
    from src.app.agents.collections.scheduler import CollectionsScheduler

    col_registration = create_collections_registration()
    payment_risk_scorer = PaymentRiskScorer()

    # Get CSM agent reference for cross-agent risk feed
    csm_agent_ref = getattr(app.state, "customer_success", None)

    collections_agent = CollectionsAgent(
        registration=col_registration,
        llm_service=getattr(app.state, "llm_service", None) or locals().get("llm_service"),
        notion_collections=None,
        gmail_service=getattr(app.state, "gmail_service", None) or locals().get("gmail_service"),
        event_bus=getattr(app.state, "event_bus", None) or locals().get("event_bus"),
        risk_scorer=payment_risk_scorer,
        csm_agent=csm_agent_ref,
    )

    agent_registry = getattr(app.state, "agent_registry", None)
    if agent_registry is not None:
        agent_registry.register(col_registration)
    app.state.collections_agent = collections_agent

    col_scheduler = CollectionsScheduler(
        collections_agent=collections_agent,
        notion_collections=None,
    )
    col_scheduler_started = col_scheduler.start()
    if col_scheduler_started:
        app.state.col_scheduler = col_scheduler
        log.info("phase15.col_scheduler_started")
    log.info("phase15.collections_agent_initialized")
except Exception as exc:
    log.warning("phase15.collections_agent_init_failed", error=str(exc))
    app.state.collections_agent = None
    app.state.col_scheduler = None
```

### Pattern 8: CSM Cross-Agent Integration
**What:** When Collections risk is HIGH or CRITICAL, update CSMHealthSignals.collections_risk field.
**When to use:** In _handle_payment_risk_assessment when risk_band in ("RED", "CRITICAL").

```python
# Lazy import pattern for cross-agent schemas (avoids circular deps)
async def _feed_csm_health_signal(self, account_id: str, risk_band: str) -> None:
    if self._csm_agent is None:
        return
    if risk_band not in ("RED", "CRITICAL"):
        return
    try:
        from src.app.agents.customer_success.schemas import CSMHealthSignals
        # Feed collections_risk as a field to CSM health scan
        await self._csm_agent.execute(
            {
                "type": "health_scan",
                "account_id": account_id,
                "signals": {"collections_risk": risk_band},
            },
            {},
        )
    except Exception as exc:
        self._log.warning("collections_csm_feed_failed", account_id=account_id, error=str(exc))
```

### Anti-Patterns to Avoid
- **LLM in scorer:** The PaymentRiskScorer must be pure Python. No LLM calls. The scorer comment in TAM says "Do NOT use LLM for score computation" — this applies equally to Collections.
- **Sending email directly:** `GmailService.send_email()` is forbidden. Only `create_draft()` is allowed. All 5 escalation stages produce drafts, including Stage 5 human handoff.
- **Raising on LLM error:** Handlers must fail-open. On LLM error return `{"error": ..., "confidence": "low", "partial": True}`.
- **Guessing Notion block limits:** Notion API has a 100-block limit per create. Use the pattern: create with blocks[:100], then loop appending remaining in 100-block batches.
- **Not using lazy import for cross-agent schemas:** `from src.app.agents.customer_success.schemas import CSMHealthSignals` must be inside the try block, not at module top-level.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP retry logic | Custom retry loops | tenacity @retry decorator | Edge cases: jitter, max backoff, exception matching |
| Async scheduling | asyncio.sleep loops | APScheduler AsyncIOScheduler + CronTrigger | Cron expressions, misfire handling, graceful start/stop |
| JSON extraction from LLM | Custom string parsing | `_extract_json_from_response()` from CSMAgent | Code fences, bracket finding — already solved in CSM |
| Notion 100-block pagination | Single create call | create-then-append pattern from CSM/TAM | Notion silently truncates at 100 blocks |
| Structured output prompts | Inline schema strings | model_json_schema() embedded in prompt | Schema stays in sync with model automatically |

**Key insight:** Every structural problem in this agent has already been solved in CSM (Phase 14). The entire implementation is a domain-specific instantiation of an existing proven pattern.

## Common Pitfalls

### Pitfall 1: Inverting the Risk Score Direction
**What goes wrong:** CSM health score is higher = healthier (good). Payment risk score is higher = more risk (bad). If you copy the CSM scorer thresholds directly, GREEN/RED bands will be backwards.
**Why it happens:** Naming convention mismatch between "health" (high = good) and "risk" (high = bad).
**How to avoid:** Define PaymentRiskScorer with inverted logic: `if score < green_threshold: GREEN; elif score < amber_threshold: AMBER; else: RED`. Default thresholds: green=30, amber=60, critical=85.
**Warning signs:** A high-overdue account shows GREEN; a current account shows RED.

### Pitfall 2: Escalation State Not Persisted
**What goes wrong:** Escalation stage and last-message timestamps are in-memory only. Server restart resets all state, causing accounts to restart at Stage 1.
**Why it happens:** State stored only in agent instance dict.
**How to avoid:** Persist escalation state in Notion. The notion_adapter must have a `get_escalation_state()` and `update_escalation_stage()` method. State includes: current_stage (int 1-5), stage_entered_at (datetime), last_message_sent_at (datetime), messages_unanswered (int).
**Warning signs:** Escalation resets after deployment. Accounts skip stages.

### Pitfall 3: CSMHealthSignals.collections_risk Field Missing
**What goes wrong:** Collections agent tries to feed risk into CSM but CSMHealthSignals has no `collections_risk` field. The task fails or is silently ignored.
**Why it happens:** CSMHealthSignals was defined in Phase 14 before the Collections agent existed. The field was noted in STATE.md but not yet implemented.
**How to avoid:** Add `collections_risk: Optional[Literal["GREEN", "AMBER", "RED", "CRITICAL"]] = None` to CSMHealthSignals in Phase 15 schemas task. Update CSMHealthScorer to apply a cap when collections_risk is RED or CRITICAL (same pattern as tam_health_rag cap: RED -> raw * 0.85, CRITICAL -> raw * 0.80).
**Warning signs:** KeyError or ValidationError when Collections tries to pass collections_risk to CSM health scan.

### Pitfall 4: Notion Config Env Vars Not Added
**What goes wrong:** Collections adapter raises ValueError: "NOTION_COLLECTIONS_DATABASE_ID not configured" at runtime.
**Why it happens:** config.py was not updated with the new env vars.
**How to avoid:** Add the following to Settings in config.py before implementing the adapter:
```python
NOTION_COLLECTIONS_AR_DATABASE_ID: str = ""
NOTION_COLLECTIONS_ESCALATION_DATABASE_ID: str = ""
NOTION_COLLECTIONS_PAYMENT_PLAN_DATABASE_ID: str = ""
```
**Warning signs:** ValueError on first adapter call, not at startup.

### Pitfall 5: Time-Floor Logic Bypassed
**What goes wrong:** Account escalates from Stage 1 to Stage 2 after 1 day instead of waiting the minimum floor (e.g., 7 days).
**Why it happens:** Escalation check only looks at `messages_unanswered`, ignoring `stage_entered_at`.
**How to avoid:** Escalation condition is: `(days_in_stage >= stage_floor[current_stage]) AND (messages_unanswered >= 1)`. Both conditions must be true. Days in stage = `(now - stage_entered_at).days`.
**Warning signs:** Accounts jumping from Stage 1 to Stage 5 within a week.

### Pitfall 6: Stage 5 Sends More Messages
**What goes wrong:** At Stage 5 (human handoff), the agent generates a new escalation draft on next daily scan.
**Why it happens:** Daily escalation check doesn't short-circuit at Stage 5.
**How to avoid:** At the start of `_process_escalation_for_account()`: if current_stage == 5, skip processing (already handed off). The check must happen before any new draft creation.
**Warning signs:** Rep receives multiple Stage 5 notifications for the same account.

### Pitfall 7: Message Calibration ARR Modifier Applied Wrong
**What goes wrong:** High-ARR accounts receive harsher tone than low-ARR accounts (reversed).
**Why it happens:** ARR modifier subtracted from urgency instead of used as a damping factor.
**How to avoid:** ARR and tenure are *softeners*. Formula: `urgency = base_urgency_from_days_overdue * (1.0 - arr_softening_factor)`. High ARR = lower urgency multiplier = softer tone.
**Warning signs:** Enterprise customers receive "FINAL WARNING" on Day 15 overdue.

## Code Examples

Verified patterns directly from the existing codebase:

### AR Aging Bucket Computation
```python
# Standard AR aging buckets — pure Python, no library needed
from datetime import datetime, timezone

def compute_aging_buckets(invoices: list[dict]) -> dict[str, list[dict]]:
    """Bucket invoices by days overdue: current, 1-30, 31-60, 61-90, 90+."""
    now = datetime.now(timezone.utc)
    buckets = {"current": [], "1_30": [], "31_60": [], "61_90": [], "90_plus": []}

    for invoice in invoices:
        due_date = invoice.get("due_date")
        if due_date is None:
            continue
        if isinstance(due_date, str):
            due_date = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
        days_overdue = (now - due_date).days
        if days_overdue <= 0:
            buckets["current"].append(invoice)
        elif days_overdue <= 30:
            buckets["1_30"].append(invoice)
        elif days_overdue <= 60:
            buckets["31_60"].append(invoice)
        elif days_overdue <= 90:
            buckets["61_90"].append(invoice)
        else:
            buckets["90_plus"].append(invoice)

    return buckets
```

### Payment Risk Scorer (4-signal weighted formula)
```python
# Source: CSMHealthScorer pattern (src/app/agents/customer_success/health_scorer.py)
# INVERTED: higher score = more risk

class PaymentRiskScorer:
    """Score: 0-100, higher = more risk.

    Signal weights (total = 100):
      days_overdue:              40 (primary)
      payment_history_streak:    30 (consecutive late payments)
      total_outstanding_balance: 20 (absolute dollar amount)
      days_to_renewal:           10 (proximity adds urgency)
    """

    def __init__(
        self,
        *,
        green_threshold: float = 30.0,
        amber_threshold: float = 60.0,
        critical_threshold: float = 85.0,
    ) -> None:
        self._green_threshold = green_threshold
        self._amber_threshold = amber_threshold
        self._critical_threshold = critical_threshold

    @staticmethod
    def _score_days_overdue(days: int) -> float:
        """Primary signal: weight 40."""
        if days <= 0:
            return 0.0
        if days <= 30:
            return 15.0
        if days <= 60:
            return 25.0
        if days <= 90:
            return 35.0
        return 40.0  # 90+ days: max contribution

    @staticmethod
    def _score_payment_history(consecutive_late: int) -> float:
        """Payment history streak: weight 30. 0 late = 0, 3+ = max."""
        if consecutive_late == 0:
            return 0.0
        if consecutive_late == 1:
            return 10.0
        if consecutive_late == 2:
            return 20.0
        return 30.0  # 3+ consecutive late

    @staticmethod
    def _score_outstanding_balance(amount_usd: float) -> float:
        """Total outstanding: weight 20. Scale based on dollar thresholds."""
        if amount_usd <= 0:
            return 0.0
        if amount_usd <= 5_000:
            return 5.0
        if amount_usd <= 25_000:
            return 10.0
        if amount_usd <= 100_000:
            return 15.0
        return 20.0  # >$100k: max contribution

    @staticmethod
    def _score_renewal_proximity(days_to_renewal: int | None) -> float:
        """Renewal proximity: weight 10. None = neutral (5)."""
        if days_to_renewal is None:
            return 5.0
        if days_to_renewal > 180:
            return 2.0
        if days_to_renewal > 90:
            return 5.0
        if days_to_renewal > 30:
            return 8.0
        return 10.0  # <=30 days: max contribution (renewal at risk)

    def score(self, signals: "PaymentRiskSignals", account_id: str = "") -> "PaymentRiskResult":
        breakdown: dict[str, float] = {}
        breakdown["days_overdue"] = self._score_days_overdue(signals.days_overdue)
        breakdown["payment_history_streak"] = self._score_payment_history(signals.consecutive_late_payments)
        breakdown["outstanding_balance"] = self._score_outstanding_balance(signals.total_outstanding_usd)
        breakdown["renewal_proximity"] = self._score_renewal_proximity(signals.days_to_renewal)

        raw_score = sum(breakdown.values())
        raw_score = max(0.0, min(100.0, raw_score))

        # Derive RAG (inverted: high score = bad)
        if raw_score < self._green_threshold:
            risk_band = "GREEN"
        elif raw_score < self._amber_threshold:
            risk_band = "AMBER"
        elif raw_score < self._critical_threshold:
            risk_band = "RED"
        else:
            risk_band = "CRITICAL"

        return PaymentRiskResult(
            account_id=account_id,
            score=raw_score,
            risk_band=risk_band,
            signal_breakdown=breakdown,
        )
```

### Escalation State Machine (5 stages with time-floor + non-response)
```python
# Stage configuration: (min_days_floor, label)
ESCALATION_STAGES = {
    1: {"floor_days": 7,  "label": "friendly_nudge"},
    2: {"floor_days": 5,  "label": "soft_reminder"},
    3: {"floor_days": 5,  "label": "firm_notice"},
    4: {"floor_days": 3,  "label": "final_warning"},
    5: {"floor_days": 0,  "label": "human_handoff"},
}

def should_advance_stage(
    current_stage: int,
    stage_entered_at: datetime,
    messages_unanswered: int,
) -> bool:
    """Advance when BOTH time-floor met AND non-response detected."""
    if current_stage >= 5:
        return False  # Stage 5 is terminal
    config = ESCALATION_STAGES[current_stage]
    days_in_stage = (datetime.now(timezone.utc) - stage_entered_at).days
    floor_met = days_in_stage >= config["floor_days"]
    non_response = messages_unanswered >= 1
    return floor_met and non_response
```

### Message Calibration Formula
```python
# Tone urgency: days_overdue is primary, ARR + tenure are softeners
def compute_message_urgency(
    days_overdue: int,
    arr_usd: float,
    payment_history_clean: bool,
    tenure_months: int,
    stage: int,
) -> dict:
    """Compute tone urgency factors for LLM message calibration.

    Returns dict passed into LLM prompt as calibration_factors.
    """
    # Base urgency 1-5 from days overdue (primary driver)
    if days_overdue <= 15:
        base_urgency = 1
    elif days_overdue <= 30:
        base_urgency = 2
    elif days_overdue <= 60:
        base_urgency = 3
    elif days_overdue <= 90:
        base_urgency = 4
    else:
        base_urgency = 5

    # ARR + tenure softening (reduce urgency for high-value longstanding accounts)
    arr_softener = 0.0
    if arr_usd >= 100_000:
        arr_softener += 0.8
    elif arr_usd >= 25_000:
        arr_softener += 0.4
    if tenure_months >= 24:
        arr_softener += 0.4
    elif tenure_months >= 12:
        arr_softener += 0.2

    # Payment history softening (clean payer = benefit of the doubt)
    history_softener = 0.3 if payment_history_clean else 0.0

    total_softener = min(arr_softener + history_softener, 1.2)  # cap at ~1 level reduction
    effective_urgency = max(1, round(base_urgency - total_softener))

    return {
        "stage": stage,
        "days_overdue": days_overdue,
        "base_urgency": base_urgency,
        "effective_urgency": effective_urgency,
        "arr_softened": arr_usd >= 25_000,
        "history_clean": payment_history_clean,
        "tone": ["relationship-preserving", "polite-urgency", "professional-firm", "explicit-consequences", "human-handoff"][stage - 1],
    }
```

### Notion Blocks for AR Aging Record
```python
# Source: NotionCSMAdapter / NotionTAMAdapter patterns
def render_ar_aging_blocks(record: "ARAgingRecord") -> list[dict]:
    blocks = []
    blocks.append(_heading_block("AR Aging Summary", level=2))
    blocks.append(_paragraph_block(f"Total Outstanding: ${record.total_outstanding_usd:,.2f}"))
    blocks.append(_paragraph_block(f"Days Overdue (Oldest Invoice): {record.oldest_invoice_days_overdue}"))
    blocks.append(_heading_block("Invoices by Aging Bucket", level=3))
    blocks.append(_bulleted_list_block(f"Current: ${record.current_amount:,.2f}"))
    blocks.append(_bulleted_list_block(f"1-30 days: ${record.overdue_1_30_usd:,.2f}"))
    blocks.append(_bulleted_list_block(f"31-60 days: ${record.overdue_31_60_usd:,.2f}"))
    blocks.append(_bulleted_list_block(f"61-90 days: ${record.overdue_61_90_usd:,.2f}"))
    blocks.append(_bulleted_list_block(f"90+ days: ${record.overdue_90_plus_usd:,.2f}"))
    blocks.append(_heading_block("Oldest Outstanding Invoice", level=3))
    blocks.append(_paragraph_block(
        f"Invoice #{record.oldest_invoice_number} | "
        f"Date: {record.oldest_invoice_date} | "
        f"Amount: ${record.oldest_invoice_amount:,.2f}"
    ))
    return blocks
```

### Gmail Draft for Human Handoff (Stage 5)
```python
# Source: CustomerSuccessAgent._dispatch_churn_alerts pattern
async def _dispatch_stage5_handoff(
    self,
    account_id: str,
    account_name: str,
    rep_email: str,
    finance_email: str,
    ar_summary: dict,
) -> list[str | None]:
    """Create Gmail drafts for both rep AND finance at Stage 5. Returns [rep_draft_id, finance_draft_id]."""
    draft_ids = []
    for recipient, label in [(rep_email, "Account Rep"), (finance_email, "Finance Team")]:
        if not recipient:
            draft_ids.append(None)
            continue
        try:
            from src.app.services.gsuite.models import EmailMessage
            subject = f"[COLLECTIONS ESCALATION] {account_name} — Human Intervention Required"
            body_html = (
                f"<p><strong>Collections Stage 5 Handoff</strong></p>"
                f"<p>Account <strong>{account_name}</strong> ({account_id}) has reached "
                f"Stage 5 after failing to respond through 4 automated escalation stages.</p>"
                f"<p>Total outstanding: <strong>${ar_summary.get('total_outstanding_usd', 0):,.2f}</strong></p>"
                f"<p><strong>No further automated messages will be sent.</strong> "
                f"Human intervention is required.</p>"
            )
            draft_email = EmailMessage(to=recipient, subject=subject, body_html=body_html)
            result = await self._gmail_service.create_draft(draft_email)
            draft_ids.append(result.draft_id if hasattr(result, "draft_id") else result.get("draft_id"))
        except Exception as exc:
            self._log.warning("stage5_handoff_draft_failed", recipient=label, error=str(exc))
            draft_ids.append(None)
    return draft_ids
```

### Cross-Agent Feed to CSM (lazy import pattern)
```python
# Source: CSMAgent._handle_check_expansion — lazy import for cross-agent
async def _feed_collections_risk_to_csm(
    self,
    account_id: str,
    risk_band: str,
    context: dict,
) -> None:
    """Feed HIGH/CRITICAL collections risk into CSM health scorer."""
    if self._csm_agent is None:
        return
    if risk_band not in ("RED", "CRITICAL"):
        return
    try:
        # Lazy import avoids circular dependency at module load time
        await self._csm_agent.execute(
            {
                "type": "health_scan",
                "account_id": account_id,
                "signals": {"collections_risk": risk_band},
            },
            context,
        )
        self._log.info("collections_risk_fed_to_csm", account_id=account_id, risk_band=risk_band)
    except Exception as exc:
        self._log.warning("collections_csm_feed_failed", account_id=account_id, error=str(exc))
```

## State of the Art

| Old Approach | Current Approach | Source | Impact |
|--------------|------------------|--------|--------|
| LLM for all scoring | Deterministic scorer + LLM narrative | TAM Phase 13, CSM Phase 14 | Deterministic, testable, no LLM cost for scoring |
| Single global try/except | Per-channel independent try/except | CSM _dispatch_churn_alerts | One channel failure doesn't block others |
| Sending emails directly | GmailService.create_draft() only | TAM Phase 13 decision | Humans review before any outreach |
| Static escalation | State machine with time-floor + non-response | Locked decision (CONTEXT.md) | Prevents premature escalation |
| Global config | Per-constructor threshold kwargs | CSMHealthScorer, HealthScorer | Configurable per tenant without code changes |

**Current standard in this codebase (HIGH confidence):**
- model_json_schema() embedded in prompts (not passed separately)
- All Notion writes use tenacity @retry(stop=stop_after_attempt(3))
- All prompt builders return str (not dict)
- Schedulers use misfire_grace_time=3600
- All adapters accept pre-authenticated AsyncClient (not token string)

## Key Design Decisions for Collections

### Escalation Stage Schema
The escalation state must be persisted in Notion (not memory). Fields required:
- `current_stage: int` (1-5)
- `stage_entered_at: datetime`
- `last_message_sent_at: Optional[datetime]`
- `messages_unanswered: int` (incremented each scan when no payment received and no customer reply detected)
- `stage5_notified: bool` (prevents duplicate Stage 5 handoff notifications)

### ARAgingRecord Schema
Based on CONTEXT.md requirements (oldest invoice reference, buckets):
- `account_id: str`
- `total_outstanding_usd: float`
- `oldest_invoice_number: str`
- `oldest_invoice_date: str`
- `oldest_invoice_amount: float`
- `oldest_invoice_days_overdue: int`
- `current_amount: float`
- `overdue_1_30_usd: float`
- `overdue_31_60_usd: float`
- `overdue_61_90_usd: float`
- `overdue_90_plus_usd: float`
- `computed_at: datetime`

### PaymentRiskSignals Schema
Four exact signals from CONTEXT.md:
- `days_overdue: int` (primary signal)
- `consecutive_late_payments: int` (payment history streak)
- `total_outstanding_usd: float` (absolute dollar amount)
- `days_to_renewal: Optional[int]` (renewal proximity)

### CollectionMessage Schema (LLM output)
- `account_id: str`
- `stage: int` (1-5)
- `subject: str`
- `body_text: str`
- `tone: str` (e.g., "friendly_nudge", "firm_notice")
- `invoice_reference: str` (oldest invoice #, date, amount)
- `total_balance_reference: str`
- `generated_at: datetime`

### PaymentPlanOptions Schema (LLM output for Notion page)
Three options per CONTEXT.md:
- `option_type: Literal["installment_schedule", "partial_payment", "pay_or_suspend"]`
- `description: str`
- `terms: str`
- `pros: list[str]`
- `cons: list[str]`

### Recommended Scoring Thresholds (Claude's Discretion)
Based on the signal weights and real-world AR norms:
- GREEN: score < 30 (0-2 weeks overdue, clean history)
- AMBER: 30 <= score < 60 (3-8 weeks overdue, some late history)
- RED: 60 <= score < 85 (2-3 months overdue or chronic late)
- CRITICAL: score >= 85 (90+ days + chronic + large balance)

### Recommended Stage Time-Floors (Claude's Discretion)
Derived from standard B2B collections practice:
- Stage 1 (friendly nudge): 7-day floor before Stage 2
- Stage 2 (soft reminder): 5-day floor before Stage 3
- Stage 3 (firm notice): 5-day floor before Stage 4
- Stage 4 (final warning): 3-day floor before Stage 5
- Stage 5 (human handoff): terminal — no further progression

### CSMHealthSignals Update Required
The `collections_risk` field must be added to CSMHealthSignals and CSMHealthScorer before the cross-agent integration can work. The scorer should apply an analogous cap:
- `collections_risk == "RED"` → raw_csm_score * 0.90 (moderate cap — less severe than TAM RED)
- `collections_risk == "CRITICAL"` → raw_csm_score * 0.80 (stronger cap)
- GREEN/AMBER/None → no cap

## Open Questions

1. **Payment Detection Source**
   - What we know: The agent generates drafts; reps send them; customers pay.
   - What's unclear: How does the agent know a payment was received to reset escalation state? The system likely needs a way to mark invoices as paid (manually by rep or via webhook from billing system).
   - Recommendation: For Phase 15, treat payment detection as manual. The Notion escalation page should have a "Mark Resolved" mechanism. The daily escalation check should skip accounts with stage "resolved". This is an external trigger, not automated detection.

2. **Customer Reply Detection for Non-Response Tracking**
   - What we know: Non-response drives escalation advancement (per CONTEXT.md decision).
   - What's unclear: How does the agent detect whether the customer replied? Gmail read receipts are unreliable. There's no inbox-monitoring capability established.
   - Recommendation: For Phase 15, treat "non-response" as "rep did not mark account as 'response received' within the time floor." The rep manually updates the Notion record. The agent advances stage if days_in_stage >= floor AND no_response_flag == True in Notion.

3. **Finance Team Email Configuration**
   - What we know: Stage 5 notifies both rep AND finance team (per CONTEXT.md decision).
   - What's unclear: How is the finance_email configured? Per-tenant? Global env var?
   - Recommendation: Add `FINANCE_TEAM_EMAIL: str = ""` to config.py Settings. This is simpler than per-tenant for v2.0.

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection: `src/app/agents/customer_success/` — CSMHealthScorer, CSMHealthSignals, CustomerSuccessAgent, NotionCSMAdapter, CSMScheduler, prompt_builders
- Direct codebase inspection: `src/app/agents/technical_account_manager/` — HealthScorer, NotionTAMAdapter, TAMScheduler
- Direct codebase inspection: `src/app/main.py` — Phase 13 and 14 lifespan wiring patterns
- Direct codebase inspection: `src/app/agents/base.py` — BaseAgent, AgentRegistration
- Direct codebase inspection: `src/app/config.py` — Settings env vars pattern
- Direct codebase inspection: `tests/test_csm_health_scorer.py` — test structure for deterministic scorer
- Phase 15 CONTEXT.md — All locked decisions, Claude's Discretion areas

### Secondary (MEDIUM confidence)
- Standard AR aging bucket definitions (0-30, 31-60, 61-90, 90+ days) — industry standard, consistent with CSM invoice_payment_status field values in existing schemas

### Tertiary (LOW confidence)
- Recommended numeric thresholds (green=30, amber=60, critical=85) — Claude's discretion, not from external source. Planner should accept these as reasonable defaults.
- Stage time-floor recommendations (7, 5, 5, 3 days) — Claude's discretion. Reasonable for B2B SaaS collections cadence.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in use, versions visible in existing code
- Architecture patterns: HIGH — directly copied from CSM (Phase 14) which is proven working code
- Scorer design: HIGH — direct extension of CSMHealthScorer pattern with inverted direction
- Escalation state machine: HIGH — design is specified in CONTEXT.md, implementation follows CSM handler pattern
- CSM integration: HIGH — pattern exists (TAM->CSM), needs field addition to CSMHealthSignals
- Pitfalls: HIGH — based on direct reading of existing code anti-patterns and CONTEXT.md constraints
- Numeric thresholds (Claude's Discretion): LOW — reasonable estimates, not externally validated

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable codebase, no fast-moving external dependencies)
