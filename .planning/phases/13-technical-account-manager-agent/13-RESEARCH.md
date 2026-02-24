# Phase 13: Technical Account Manager Agent - Research

**Researched:** 2026-02-24
**Domain:** Agent architecture, health monitoring, escalation scoring, communication generation, Notion CRM, event bus integration
**Confidence:** HIGH

## Summary

The TAM agent follows the well-established agent pattern from Phases 10-12 (SA, PM, BA). The codebase has a mature template: `BaseAgent` subclass with `execute()` routing to typed handlers, Pydantic schemas, prompt builders, Notion adapters with tenacity retry, capabilities declarations, and `create_*_registration()` factories. APScheduler is already in production for the PM agent's weekly report scheduler, providing the exact pattern for the TAM's daily health scan + monthly health check-in scheduling.

The primary complexity in this phase is the health scoring algorithm (combining three signal types into a 0-100 score), the Kayako/Jira ticket integration decision, the Gmail draft creation (a new capability not yet on GmailService), and the four-channel escalation notification dispatch. All other patterns -- Notion adapter, event bus publishing, LLM-driven communication generation -- are well-precedented and can be directly cloned.

**Primary recommendation:** Build the TAM agent by cloning the PM agent pattern (closest analog: scheduled scans, Notion writes, email dispatch, multi-handler routing), adding a `create_draft` method to GmailService, pre-syncing Kayako/Jira tickets to a Notion database for pragmatic data access, and implementing a pure-Python health scoring algorithm (no LLM needed for numeric computation).

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | >=2.0 | Schema validation for all TAM models | Already used across all agents |
| structlog | * | Structured logging | Standard across codebase |
| litellm | * | LLM calls via Router | Already configured with Claude Sonnet 4 / GPT-4o |
| notion-client | >=2.7.0 | Notion API async client | Used by NotionPMAdapter, NotionBAAdapter, NotionAdapter |
| tenacity | * | Retry logic for Notion/external API calls | Used by all Notion adapters |
| apscheduler | * | Async scheduling for daily scan + monthly health check-ins | Already in production for PM weekly reports |
| redis.asyncio | * | Event bus (TenantEventBus via Redis Streams) | Already in production |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| jira | >=3.5 | Python Jira client for ticket fetching | If using direct Jira API polling |
| httpx/aiohttp | * | HTTP client for Kayako REST API | If using direct Kayako API polling |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct Kayako/Jira API polling | Pre-sync to Notion DB | Pre-sync is simpler, avoids new dependencies, but adds sync latency (daily is acceptable per decision) |
| Custom health scorer | LLM-based scoring | Pure Python is deterministic, faster, cheaper -- LLM adds no value for numeric threshold checks |

**Installation:**
```bash
# No new packages needed if using pre-sync approach
# If direct Jira polling:
pip install jira>=3.5
```

## Architecture Patterns

### Recommended Project Structure
```
src/app/agents/technical_account_manager/
    __init__.py          # Package exports
    agent.py             # TAMAgent (BaseAgent subclass with handlers)
    schemas.py           # Pydantic models (health score, relationship profile, comms)
    prompts.py           # TAM system prompt + 5 communication prompt builders
    capabilities.py      # TAM_CAPABILITIES + create_tam_registration()
    notion_tam.py        # NotionTAMAdapter (relationship profiles, health dashboard)
    health_scorer.py     # Pure Python health scoring algorithm (0-100 + RAG status)
    scheduler.py         # TAMScheduler (daily scan + monthly health check-in)
    ticket_client.py     # Kayako/Jira ticket data access (abstraction layer)
```

### Pattern 1: Agent Structure (Clone PM Agent Pattern)
**What:** TAMAgent extends BaseAgent with execute() routing to typed handlers
**When to use:** Always -- this is the locked architecture decision
**Example:**
```python
# Source: src/app/agents/project_manager/agent.py (established pattern)
class TAMAgent(BaseAgent):
    def __init__(
        self,
        registration: AgentRegistration,
        llm_service: object,
        notion_tam: object | None = None,
        gmail_service: object | None = None,
        chat_service: object | None = None,
        event_bus: object | None = None,
        ticket_client: object | None = None,
        health_scorer: object | None = None,
    ) -> None:
        super().__init__(registration)
        self._llm_service = llm_service
        self._notion_tam = notion_tam
        self._gmail_service = gmail_service
        self._chat_service = chat_service
        self._event_bus = event_bus
        self._ticket_client = ticket_client
        self._health_scorer = health_scorer

    async def execute(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        task_type = task.get("type", "")
        handlers = {
            "health_scan": self._handle_health_scan,
            "escalation_outreach": self._handle_escalation_outreach,
            "release_notes": self._handle_release_notes,
            "roadmap_preview": self._handle_roadmap_preview,
            "health_checkin": self._handle_health_checkin,
            "customer_success_review": self._handle_customer_success_review,
            "update_relationship_profile": self._handle_update_relationship_profile,
        }
        handler = handlers.get(task_type)
        if handler is None:
            raise ValueError(
                f"Unknown task type: {task_type!r}. "
                f"Supported: {', '.join(handlers.keys())}"
            )
        return await handler(task, context)
```

### Pattern 2: Health Scoring (Pure Python, No LLM)
**What:** Deterministic 0-100 health score computed from three signal categories
**When to use:** Daily scan + on-demand refresh
**Example:**
```python
# Pure Python health scoring -- CRITICAL: do NOT use LLM for this
class HealthScorer:
    """Compute account health score (0-100, higher = healthier) from three signals."""

    # Configurable thresholds (Claude's discretion per CONTEXT.md)
    P1_P2_AGE_THRESHOLD_DAYS: int = 3    # P1/P2 tickets older than this = at risk
    OPEN_TICKET_COUNT_THRESHOLD: int = 5   # More than this = at risk
    HEARTBEAT_SILENCE_HOURS: int = 72      # No heartbeat for this long = at risk

    # RAG status thresholds (Claude's discretion)
    RED_THRESHOLD: int = 40
    AMBER_THRESHOLD: int = 70

    def compute_score(
        self,
        p1_p2_ticket_count: int,
        oldest_p1_p2_age_days: float,
        total_open_tickets: int,
        hours_since_heartbeat: float | None,
    ) -> tuple[int, str]:
        """Return (score_0_to_100, rag_status).

        Scoring formula:
        - Start at 100 (perfect health)
        - Deduct for P1/P2 aged tickets: -20 per ticket over threshold
        - Deduct for open ticket volume: -5 per ticket over threshold
        - Deduct for heartbeat silence: -15 if over threshold, -30 if > 2x threshold
        - Floor at 0
        """
        score = 100

        # P1/P2 ticket age penalty
        if oldest_p1_p2_age_days > self.P1_P2_AGE_THRESHOLD_DAYS:
            score -= p1_p2_ticket_count * 20

        # Open ticket volume penalty
        excess_tickets = max(0, total_open_tickets - self.OPEN_TICKET_COUNT_THRESHOLD)
        score -= excess_tickets * 5

        # Heartbeat silence penalty
        if hours_since_heartbeat is not None:
            if hours_since_heartbeat > self.HEARTBEAT_SILENCE_HOURS * 2:
                score -= 30
            elif hours_since_heartbeat > self.HEARTBEAT_SILENCE_HOURS:
                score -= 15

        score = max(0, min(100, score))

        # Derive RAG status
        if score < self.RED_THRESHOLD:
            rag = "Red"
        elif score < self.AMBER_THRESHOLD:
            rag = "Amber"
        else:
            rag = "Green"

        return score, rag
```

### Pattern 3: APScheduler (Clone PM Scheduler Pattern)
**What:** Async scheduler for daily health scans + configurable monthly health check-ins
**When to use:** Background operations
**Example:**
```python
# Source: src/app/agents/project_manager/scheduler.py (established pattern)
class TAMScheduler:
    def __init__(
        self,
        tam_agent: object,
        notion_tam: object | None = None,
    ) -> None:
        self._tam_agent = tam_agent
        self._notion_tam = notion_tam
        self._scheduler: AsyncIOScheduler | None = None

    def start(self) -> bool:
        if AsyncIOScheduler is None:
            return False
        self._scheduler = AsyncIOScheduler()

        # Daily health scan at 7:00 AM
        self._scheduler.add_job(
            self._daily_health_scan,
            trigger=CronTrigger(hour=7, minute=0),
            id="tam_daily_health_scan",
            misfire_grace_time=3600,
        )

        # Monthly health check-in on 1st of month at 10:00 AM
        self._scheduler.add_job(
            self._monthly_health_checkins,
            trigger=CronTrigger(day=1, hour=10, minute=0),
            id="tam_monthly_health_checkins",
            misfire_grace_time=7200,
        )

        self._scheduler.start()
        return True
```

### Pattern 4: Gmail Draft Creation (New Capability on Existing Service)
**What:** Create email draft in rep's inbox instead of sending directly
**When to use:** All TAM communications -- TAM never sends autonomously
**Example:**
```python
# New method to add to GmailService (src/app/services/gsuite/gmail.py)
# Follows same pattern as send_email but uses drafts.create instead of messages.send
async def create_draft(
    self,
    email: EmailMessage,
    user_email: str | None = None,
) -> dict:
    """Create a Gmail draft in the user's inbox.

    Returns dict with draft_id and message dict.
    """
    sender = user_email or self._default_user_email
    service = self._auth.get_gmail_service(sender)
    raw = self._build_mime_message(email)

    body = {"message": {"raw": raw}}
    if email.thread_id:
        body["message"]["threadId"] = email.thread_id

    def _create() -> dict:
        return (
            service.users()
            .drafts()
            .create(userId="me", body=body)
            .execute()
        )

    result = await asyncio.to_thread(_create)
    return {
        "draft_id": result.get("id", ""),
        "message": result.get("message", {}),
    }
```

### Pattern 5: Event Bus Notification (Clone Escalation Manager Pattern)
**What:** Publish escalation events via TenantEventBus for Sales Agent notification
**When to use:** When health score drops below threshold or RAG worsens
**Example:**
```python
# Source: src/app/agents/sales/escalation.py (established pattern)
async def _notify_escalation(
    self,
    event_bus: TenantEventBus,
    tenant_id: str,
    account_id: str,
    health_score: int,
    rag_status: str,
    previous_rag: str,
) -> None:
    event = AgentEvent(
        event_type=EventType.AGENT_HEALTH,
        tenant_id=tenant_id,
        source_agent_id="technical_account_manager",
        call_chain=["technical_account_manager"],
        priority=EventPriority.HIGH,
        data={
            "alert_type": "tam_escalation",
            "account_id": account_id,
            "health_score": health_score,
            "rag_status": rag_status,
            "previous_rag": previous_rag,
            "action": "review_draft_outreach",
        },
    )
    await event_bus.publish("escalations", event)
```

### Pattern 6: Lazy Import for Cross-Agent Dispatch
**What:** Import schemas from other agents lazily inside handler methods
**When to use:** When TAM needs to notify Sales Agent of co-dev opportunities
**Example:**
```python
# Source: src/app/agents/sales/agent.py lines 718-719 (established pattern)
# Lazy import to avoid circular dependency
from src.app.agents.sales.schemas import ConversationState
```

### Anti-Patterns to Avoid
- **Using LLM for health score computation:** The score is a deterministic numeric calculation. LLM adds latency, cost, and non-determinism for zero benefit.
- **Sending emails directly:** CONTEXT.md is explicit: TAM creates Gmail drafts only. Never call `gmail_service.send_email()` -- always `gmail_service.create_draft()`.
- **Raising exceptions in handlers:** Follow fail-open pattern from PM/BA agents -- return `{"error": ..., "confidence": "low", "partial": True}` instead.
- **Direct Notion writes without retry:** All Notion adapter methods MUST use `@retry(stop=stop_after_attempt(3), wait=wait_exponential(...))` decorator.
- **Mixing ticket client concerns with agent logic:** Keep Kayako/Jira abstracted behind a `TicketClient` interface so the agent doesn't know which system provides tickets.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Scheduled background tasks | Custom cron/timer | APScheduler AsyncIOScheduler | Already in production (PM scheduler), handles misfire grace, async-native |
| Notion API calls with retry | Bare httpx with manual retry | tenacity + notion-client AsyncClient | Established pattern in NotionPMAdapter, NotionBAAdapter |
| Event bus publishing | Direct Redis XADD calls | TenantEventBus.publish() | Handles tenant scoping, serialization, stream trimming |
| LLM calls with injection protection | Raw API calls | LLMService.completion() | Includes prompt sanitization, tenant metadata, router fallback |
| Email MIME construction | Manual email assembly | GmailService._build_mime_message() | Handles HTML/text, threading headers, CC/BCC |
| JSON extraction from LLM responses | Manual string parsing | PM agent's _parse_llm_json / _parse_llm_json_raw | Handles code fences, validates with Pydantic |
| Agent registration | Manual registry setup | create_tam_registration() factory | Matches SA/PM/BA pattern exactly |

**Key insight:** The TAM agent has NO novel infrastructure requirements. Every foundational capability (scheduling, Notion writes, email creation, event publishing, LLM calls) already exists. The only genuinely new code is the health scoring algorithm and the communication prompt templates.

## Common Pitfalls

### Pitfall 1: Circular Import with Sales Agent Schemas
**What goes wrong:** Importing Sales Agent schemas at module level creates circular dependency
**Why it happens:** TAM needs to dispatch co-dev opportunities to Sales Agent
**How to avoid:** Use lazy imports inside handler methods (same pattern as SA -> PM dispatch on line 718 of sales agent.py)
**Warning signs:** ImportError at module load time

### Pitfall 2: Gmail Draft vs Send Confusion
**What goes wrong:** Using send_email() instead of create_draft() for TAM communications
**Why it happens:** Sales Agent uses send_email() and TAM is templated from it
**How to avoid:** GmailService needs a NEW create_draft() method; TAM handlers must call create_draft(), never send_email(). Add explicit docstring warnings.
**Warning signs:** Emails going out to customers without rep review

### Pitfall 3: Health Score Non-Determinism
**What goes wrong:** Using LLM to compute health scores produces inconsistent results across runs
**Why it happens:** Temptation to "let the LLM decide" severity weighting
**How to avoid:** Health scoring MUST be pure Python with configurable thresholds. The LLM's role is limited to generating COMMUNICATIONS about health issues, not computing the score.
**Warning signs:** Same account getting different scores on consecutive scans with identical data

### Pitfall 4: Notion API 100-Block Limit
**What goes wrong:** Page creation fails when TAM relationship profile has > 100 blocks
**Why it happens:** Notion API limits children to 100 blocks per create call
**How to avoid:** Follow NotionBAAdapter pattern -- create page with first 100 blocks, then append remaining in batches of 100
**Warning signs:** 400 errors from Notion API with "blocks limit" message

### Pitfall 5: Heartbeat Data Staleness
**What goes wrong:** Health score penalizes accounts for silent heartbeat when heartbeat field was never populated
**Why it happens:** Not all accounts have integration heartbeat data
**How to avoid:** Treat `None` / missing heartbeat as "not monitored" (no penalty), not "silent" (penalty). Only penalize when a previously active heartbeat goes silent.
**Warning signs:** New accounts immediately scored as at-risk

### Pitfall 6: Escalation Notification Storm
**What goes wrong:** A batch of accounts all trigger escalation on the same daily scan, flooding reps with notifications
**Why it happens:** Daily scan iterates all accounts; many may cross threshold simultaneously
**How to avoid:** Rate-limit notifications per rep per scan (e.g., max 5 escalation alerts per rep per scan run). Bundle remaining into a summary digest.
**Warning signs:** Reps complaining about notification overload

### Pitfall 7: Event Bus Tenant Mismatch
**What goes wrong:** AgentEvent rejected because tenant_id doesn't match bus
**Why it happens:** TenantEventBus validates event.tenant_id matches bus.tenant_id (see bus.py line 68)
**How to avoid:** Create TenantEventBus per-tenant during account iteration in daily scan
**Warning signs:** ValueError "Event tenant_id does not match bus tenant_id"

## Code Examples

### TAM Capabilities Registration
```python
# Source: established pattern from src/app/agents/project_manager/capabilities.py
TAM_CAPABILITIES: list[AgentCapability] = [
    AgentCapability(
        name="health_monitoring",
        description="Monitor technical health per account from tickets, CRM, and heartbeat signals",
    ),
    AgentCapability(
        name="escalation_risk_scoring",
        description="Predict escalation risk and trigger proactive outreach when health deteriorates",
    ),
    AgentCapability(
        name="technical_communication",
        description=(
            "Generate technical communications: escalation outreach, release notes, "
            "roadmap previews, health check-ins, and Customer Success Reviews"
        ),
    ),
    AgentCapability(
        name="relationship_profiling",
        description=(
            "Track technical relationship status: stakeholder maturity, "
            "integration depth, feature adoption, and communication history"
        ),
    ),
    AgentCapability(
        name="opportunity_surfacing",
        description="Identify co-development and integration opportunities for Sales Agent",
    ),
]

def create_tam_registration() -> AgentRegistration:
    return AgentRegistration(
        agent_id="technical_account_manager",
        name="Technical Account Manager",
        description=(
            "Technical account management agent that monitors health metrics, "
            "predicts escalation risk, generates technical advocacy communications, "
            "tracks technical relationships, and surfaces co-dev opportunities"
        ),
        capabilities=TAM_CAPABILITIES,
        backup_agent_id=None,
        tags=["tam", "health", "escalation", "technical", "account_management"],
        max_concurrent_tasks=3,
    )
```

### Notion TAM Adapter Structure
```python
# Source: NotionPMAdapter / NotionBAAdapter patterns
class NotionTAMAdapter:
    """Notion adapter for TAM relationship profiles and health dashboards.

    Recommended Notion structure: sub-page under each deal/account page.

    Account Page (existing)
      |-- Technical Relationship Profile (sub-page, created by TAM)
            |-- Stakeholder Map (section)
            |-- Integration Depth (section)
            |-- Feature Adoption (section)
            |-- Communication History (section)
            |-- Health Dashboard (section with score + RAG)
            |-- Co-Dev Opportunities (section)
    """

    def __init__(
        self,
        client: AsyncClient,
        accounts_database_id: str | None = None,
    ) -> None:
        self._client = client
        self._accounts_db_id = accounts_database_id

    @retry(...)
    async def create_relationship_profile(
        self, account_page_id: str, profile_data: dict
    ) -> str:
        """Create a Technical Relationship Profile sub-page under an account."""
        ...

    @retry(...)
    async def update_health_score(
        self, account_page_id: str, score: int, rag_status: str
    ) -> None:
        """Update health score and RAG status on account page properties."""
        ...

    @retry(...)
    async def append_communication_log(
        self, profile_page_id: str, communication_blocks: list[dict]
    ) -> None:
        """Append a communication record to the relationship profile."""
        ...

    @retry(...)
    async def query_all_accounts(self) -> list[dict]:
        """Query all active accounts for the daily health scan."""
        ...
```

### Ticket Client Abstraction
```python
# Abstraction layer for Kayako/Jira ticket data
# RECOMMENDATION: Pre-sync approach -- tickets synced to Notion DB via scheduled job
# This avoids new external API dependencies and keeps all data in Notion

from pydantic import BaseModel

class TicketSummary(BaseModel):
    """Normalized ticket data from any support system."""
    ticket_id: str
    account_id: str
    priority: str  # "P1", "P2", "P3", "P4"
    status: str    # "open", "pending", "resolved", "closed"
    created_at: datetime
    age_days: float
    subject: str

class TicketClient:
    """Abstract ticket data access. Reads from Notion DB (pre-synced)."""

    def __init__(self, notion_client: AsyncClient, tickets_database_id: str):
        self._client = notion_client
        self._db_id = tickets_database_id

    async def get_open_tickets(self, account_id: str) -> list[TicketSummary]:
        """Get all open tickets for an account from the tickets Notion DB."""
        ...

    async def get_p1_p2_tickets(self, account_id: str) -> list[TicketSummary]:
        """Get P1/P2 priority open tickets for an account."""
        ...
```

### Four-Channel Escalation Notification
```python
# All four channels must fire for escalation (LOCKED DECISION)
async def _dispatch_escalation_notifications(
    self,
    account_id: str,
    tenant_id: str,
    health_score: int,
    rag_status: str,
    draft_id: str,
    rep_email: str,
    chat_space: str,
) -> dict[str, bool]:
    """Dispatch escalation across all 4 channels. Returns success per channel."""
    results = {}

    # 1. Notion: Update account page with escalation flag
    try:
        await self._notion_tam.update_health_score(account_page_id, health_score, rag_status)
        results["notion"] = True
    except Exception as exc:
        logger.warning("tam_escalation_notion_failed", error=str(exc))
        results["notion"] = False

    # 2. Event bus: Notify Sales Agent
    try:
        event = AgentEvent(
            event_type=EventType.AGENT_HEALTH,
            tenant_id=tenant_id,
            source_agent_id="technical_account_manager",
            call_chain=["technical_account_manager"],
            priority=EventPriority.HIGH,
            data={"alert_type": "tam_escalation", "account_id": account_id, ...},
        )
        await self._event_bus.publish("escalations", event)
        results["event_bus"] = True
    except Exception as exc:
        logger.warning("tam_escalation_event_bus_failed", error=str(exc))
        results["event_bus"] = False

    # 3. Email alert to rep
    try:
        alert_email = EmailMessage(to=rep_email, subject=f"[TAM ALERT] ...", body_html="...")
        await self._gmail_service.send_email(alert_email)  # Alert is sent directly (not draft)
        results["email"] = True
    except Exception as exc:
        logger.warning("tam_escalation_email_failed", error=str(exc))
        results["email"] = False

    # 4. Chat alert to rep
    try:
        chat_msg = ChatMessage(space_name=chat_space, text=f"[TAM ALERT] ...")
        await self._chat_service.send_message(chat_msg)
        results["chat"] = True
    except Exception as exc:
        logger.warning("tam_escalation_chat_failed", error=str(exc))
        results["chat"] = False

    return results
```

## Kayako/Jira Integration Decision (Claude's Discretion)

### Recommendation: Pre-Sync to Notion Database

**Decision:** Pre-sync Kayako/Jira ticket data to a Notion "Support Tickets" database rather than polling APIs directly.

**Rationale:**
1. **No new external API dependencies** -- avoids Kayako XML API complexity and Jira auth setup
2. **Unified data layer** -- all TAM data lives in Notion, matching the existing CRM pattern
3. **Daily refresh is acceptable** -- CONTEXT.md specifies daily scheduled scan; ticket data refreshed on the same cadence is sufficient
4. **Existing infrastructure** -- NotionAdapter pattern with tenacity retry is battle-tested
5. **Operational simplicity** -- a separate sync script (or Zapier/Make integration) pushes tickets to Notion; TAM reads from Notion only
6. **Pragmatic for v1** -- direct API polling can be added later if real-time ticket awareness is needed

**Implementation:**
- Create a "Support Tickets" Notion database with properties: Ticket ID, Account, Priority (P1/P2/P3/P4), Status, Created Date, Subject
- A lightweight sync script (outside TAM agent scope) periodically pushes ticket data from Kayako/Jira to this database
- TAM's `TicketClient` queries this Notion database using the existing `notion-client` AsyncClient
- If an organization uses Jira, the `jira` Python library + a cron job handles sync
- If an organization uses Kayako, the Kayako REST API (XML format) + a cron job handles sync

**For reference -- Kayako API:**
- REST endpoint: `/Tickets/Ticket/ListAll/{departmentid}/{ticketstatusid}/{ownerstaffid}/{userid}` (XML response)
- Auth: API key + secret + salt + HMAC signature per request
- Python wrapper available: `kayako` package on PyPI (unmaintained, LOW confidence)
- Confidence: MEDIUM -- API documentation exists but library ecosystem is sparse

**For reference -- Jira API:**
- REST endpoint: `POST /rest/api/3/search/jql` with JQL query
- Auth: Basic auth (email + API token) or OAuth 2.0
- Python library: `jira>=3.5` -- well-maintained, mature
- JQL example: `project = PROJ AND priority in (Highest, High) AND status != Done AND assignee = currentUser()`
- Confidence: HIGH -- `jira` library is actively maintained with good docs

## Escalation Score Algorithm Detail

### Scoring Formula (Recommended)

```
Starting score: 100 (perfect health)

Deductions:
1. P1/P2 tickets over age threshold:
   - Each P1/P2 ticket older than P1_P2_AGE_THRESHOLD_DAYS: -20 points
   - Cap: minimum -60 (3 aged tickets max impact before score is already critical)

2. Open ticket volume over threshold:
   - Each open ticket beyond OPEN_TICKET_COUNT_THRESHOLD: -5 points
   - Cap: minimum -25 (5 excess tickets max impact)

3. Heartbeat silence:
   - Over HEARTBEAT_SILENCE_HOURS: -15 points
   - Over 2x HEARTBEAT_SILENCE_HOURS: -30 points (replaces -15)
   - Missing/null heartbeat: 0 points (not monitored, no penalty)

Floor: 0
Ceiling: 100

RAG derivation:
- Score >= 70: Green (healthy)
- Score 40-69: Amber (needs attention)
- Score < 40: Red (at risk, triggers escalation)
```

### Escalation Trigger Logic
```python
should_escalate = (
    current_score < ESCALATION_THRESHOLD  # e.g., 40
    or (previous_rag != "Red" and current_rag == "Red")  # worsened to Red
    or (previous_rag == "Green" and current_rag == "Amber")  # green -> amber
)
```

Note: The worsening check (Green->Amber) catches early warning even when score hasn't crossed the hard threshold. This matches the CONTEXT.md decision: "status worsens (e.g., Amber -> Red) -- whichever happens first."

## Notion Relationship Profile Structure (Claude's Discretion)

### Recommendation: Sub-Page Under Account

**Decision:** Create a "Technical Relationship Profile" sub-page under each account's Notion page.

**Rationale:**
1. Sub-pages keep the main account page clean while allowing rich content
2. Sub-pages can hold unlimited blocks (vs. embedded sections cluttering the account page)
3. Matches the PM pattern where Project Plan is a sub-page under deal pages
4. Allows the profile to grow organically as more data accumulates

**Page Structure:**
```
Technical Relationship Profile - {Account Name}
  H2: Stakeholder Map
    - {Name}: {Role} | Maturity: {low/medium/high} | Notes: ...
  H2: Integration Depth
    - {Integration Name}: Active/Inactive | Since: {date}
  H2: Feature Adoption
    - {Feature}: In Use / Not Adopted | Source: heartbeat/ticket
  H2: Customer Environment
    - {App/System}: {version/notes}
  H2: Communication History
    - {Date} | {Type} | {Subject} | Outcome: {rep notes}
  H2: Health Dashboard
    - Current Score: {0-100} | Status: {RAG}
    - Last Scan: {date} | Trend: improving/stable/declining
  H2: Co-Development Opportunities
    - {Opportunity}: {description} | Status: surfaced/discussed/in-progress
```

**Properties on Account Page (not sub-page):**
- "Health Score" (number): 0-100
- "Health Status" (select): Green/Amber/Red
- "Last Health Scan" (date): ISO date
- "TAM Profile" (relation): link to sub-page

## Communication Scheduling (Claude's Discretion)

### Recommendation: Configurable Monthly with Override

- **Health check-ins:** Default monthly (1st of month), configurable per account via a "Check-in Interval" property on the account's Notion page
- **Release notes:** Triggered on-demand when a release is tagged (not scheduled)
- **Roadmap previews:** Purely on-demand
- **Escalation outreach:** Triggered by health score change (not scheduled)
- **Customer Success Reviews:** Quarterly by default, triggered on schedule or on-demand

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| PM sends emails directly | PM sends emails directly (no draft) | Current | TAM needs NEW draft capability |
| No ticket system integration | TAM reads from Notion (pre-synced) | Phase 13 | First external support data integration |
| Agent health = internal only | TAM monitors customer-facing health | Phase 13 | New category of health monitoring |

**Deprecated/outdated:**
- None -- this phase introduces new capabilities rather than replacing old ones

## Open Questions

1. **Kayako/Jira sync script ownership**
   - What we know: TAM reads ticket data from Notion; something must put it there
   - What's unclear: Is the sync script part of Phase 13 scope, or a prerequisite?
   - Recommendation: Include a minimal sync script skeleton in Phase 13 that demonstrates the Notion DB schema and sync pattern. The actual production sync (Zapier/Make/cron) is operational setup.

2. **Integration heartbeat data source**
   - What we know: CONTEXT.md says "manually updated or posted by integration"
   - What's unclear: What field/property on the Notion account page holds heartbeat data?
   - Recommendation: Add "Last Heartbeat" (date) and "API Call Count" (number) properties to the account page. TAM reads these during health scan.

3. **Gmail draft notification to rep**
   - What we know: TAM creates draft in rep's inbox. Rep reviews and sends.
   - What's unclear: How does the rep know a draft was created? The 4-channel notification (email alert + chat alert) presumably tells them.
   - Recommendation: The email alert and chat alert should include a link to the Gmail draft or mention "Check your drafts for the outreach email."

4. **Release note trigger mechanism**
   - What we know: "auto-generated when new release ships"
   - What's unclear: What event signals a new release? Manual trigger? Git tag? Notion page?
   - Recommendation: For v1, make it an on-demand task type (`type: "release_notes"` with `release_info` in the task payload). A webhook or manual trigger calls the TAM agent when a release ships.

## Sources

### Primary (HIGH confidence)
- `src/app/agents/base.py` -- BaseAgent pattern, AgentCapability, AgentRegistration
- `src/app/agents/project_manager/agent.py` -- PM agent handler pattern (closest analog)
- `src/app/agents/project_manager/scheduler.py` -- APScheduler async pattern
- `src/app/agents/project_manager/notion_pm.py` -- NotionPMAdapter with retry pattern
- `src/app/agents/project_manager/capabilities.py` -- Registration factory pattern
- `src/app/agents/project_manager/schemas.py` -- Pydantic schema pattern
- `src/app/agents/project_manager/prompts.py` -- Prompt builder pattern
- `src/app/agents/sales/agent.py` -- SalesAgent handler pattern, lazy import pattern
- `src/app/agents/sales/escalation.py` -- EscalationManager + event bus publishing
- `src/app/agents/business_analyst/agent.py` -- BA fail-open handler pattern
- `src/app/agents/business_analyst/notion_ba.py` -- NotionBAAdapter + block renderers
- `src/app/events/bus.py` -- TenantEventBus publish/subscribe
- `src/app/events/schemas.py` -- AgentEvent, EventType, EventPriority
- `src/app/services/gsuite/gmail.py` -- GmailService (needs create_draft addition)
- `src/app/services/gsuite/models.py` -- EmailMessage, ChatMessage models
- `src/app/services/llm.py` -- LLMService.completion() pattern
- `src/app/deals/crm/notion.py` -- NotionAdapter for CRM data

### Secondary (MEDIUM confidence)
- Kayako REST API docs (https://developer.kayako.com/api/v1/reference/introduction/) -- API structure verified
- Jira REST API docs (https://developer.atlassian.com/cloud/jira/platform/rest/v3/) -- JQL search verified
- Python `jira` library docs (https://jira.readthedocs.io/api.html) -- API verified

### Tertiary (LOW confidence)
- Python `kayako` library on GitHub -- unmaintained, may not work with current Kayako versions
- Kayako Classic support docs -- may not reflect current Kayako product version

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in use, no new dependencies for pre-sync approach
- Architecture: HIGH -- direct clone of PM/BA agent patterns with well-understood modifications
- Health scoring: HIGH -- pure Python algorithm with configurable thresholds, fully deterministic
- Gmail draft: MEDIUM -- new method on existing service, follows Gmail API pattern but needs implementation + testing
- Kayako/Jira integration: MEDIUM -- pre-sync recommended to avoid complexity; direct API patterns documented for reference
- Pitfalls: HIGH -- identified from real patterns in codebase (circular imports, Notion 100-block limit, tenant mismatch)

**Research date:** 2026-02-24
**Valid until:** 2026-03-24 (30 days -- stable domain, no fast-moving dependencies)
