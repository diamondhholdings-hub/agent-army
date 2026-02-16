# Phase 7: Intelligence & Autonomy - Research

**Researched:** 2026-02-16
**Domain:** Cross-channel data consolidation, pattern recognition, autonomous goal pursuit, geographic adaptation, agent cloning
**Confidence:** HIGH (builds on established codebase patterns; no new external libraries needed)

## Summary

Phase 7 transforms the Sales Agent from a reactive executor into an autonomous operator. The codebase already has all the foundational infrastructure: conversation state (Phase 4), qualification signals and outcome tracking (Phase 4/4.1), deal management with CRM sync (Phase 5), and meeting data with transcripts (Phase 6). Phase 7 consolidates these data sources into a unified customer view, adds pattern recognition to detect buying signals and risk indicators, implements goal-directed autonomous behavior within guardrails, extends the existing regional nuances into geographic communication adaptation, and adds agent cloning with persona customization.

The key architectural insight is that Phase 7 is primarily a **composition and intelligence layer** -- it composes existing services rather than replacing them. The ConversationStore (Qdrant), DealRepository (PostgreSQL), MeetingRepository (PostgreSQL), and OutcomeTracker already store the data. Phase 7 adds: (1) a CustomerViewService that queries across these stores, (2) a PatternRecognitionEngine that detects signals across time, (3) an AutonomyEngine that decides and acts within guardrails, (4) geographic adaptation wired into the existing prompt system, and (5) a persona/clone configuration system.

**Primary recommendation:** Build as services that compose existing repositories and services. No new external libraries needed -- use instructor for structured LLM extraction (already in the project), the existing event bus for alerts, and the existing scheduler pattern for proactive outreach.

## Standard Stack

### Core (Already in Project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| instructor | >=1.7.0 | Structured LLM extraction for pattern recognition | Already used for qualification extraction (Phase 4) |
| structlog | >=24.0.0 | Structured logging for all services | Already used across all modules |
| pydantic | >=2.0.0 | Schema definitions for all new types | Already the data modeling standard |
| SQLAlchemy | >=2.0.0 | Database models for new tables | Already the ORM standard |
| Redis | >=5.0.0 | Caching, pub/sub for alerts | Already used for event bus and analytics cache |
| Qdrant | >=1.12.0 | Conversation search for customer view | Already used for conversation and knowledge search |

### Supporting (Already in Project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| litellm | >=1.60.0 | LLM calls for pattern analysis and summarization | All LLM operations via existing LLMService |
| tiktoken | >=0.7.0 | Token counting for progressive summarization | Context window management |
| asyncio | stdlib | Background task scheduling | Proactive outreach scheduler (extending Phase 4.1 pattern) |

### No New Dependencies Needed
| Instead of | Why Not Needed | Use Instead |
|------------|----------------|-------------|
| New scheduler library | Project already has asyncio background loop pattern | Extend Phase 4.1 scheduler |
| Entity resolution library | Decision locks "explicit domain/participant overlap only" | Simple email domain + participant matching |
| Notification library | Event bus already handles alerts | Redis pub/sub via existing TenantEventBus |
| Persona management library | Configuration-driven, no complex logic | Pydantic models + JSON storage |

**Installation:**
```bash
# No new packages needed -- all dependencies already in pyproject.toml
```

## Architecture Patterns

### Recommended Project Structure
```
src/app/
  intelligence/           # New top-level module for Phase 7
    __init__.py
    # Sub-package: Cross-Channel Consolidation
    consolidation/
      __init__.py
      customer_view.py    # CustomerViewService -- unified customer data assembly
      entity_linker.py    # EntityLinker -- email domain + participant matching
      summarizer.py       # ContextSummarizer -- progressive summarization
      schemas.py          # UnifiedCustomerView, ChannelInteraction, etc.
    # Sub-package: Pattern Recognition
    patterns/
      __init__.py
      engine.py           # PatternRecognitionEngine -- orchestrates detectors
      detectors.py        # BuyingSignalDetector, RiskIndicatorDetector, etc.
      insights.py         # InsightGenerator -- alert and digest creation
      schemas.py          # PatternMatch, Insight, Alert, etc.
    # Sub-package: Autonomy
    autonomy/
      __init__.py
      engine.py           # AutonomyEngine -- goal pursuit and action planning
      guardrails.py       # GuardrailChecker -- approval routing
      goals.py            # GoalTracker -- revenue target tracking
      scheduler.py        # ProactiveScheduler -- background trigger evaluation
      schemas.py          # AutonomyAction, ApprovalRequest, Goal, etc.
    # Sub-package: Geographic & Persona
    persona/
      __init__.py
      geographic.py       # GeographicAdapter -- extends RegionalNuances
      cloning.py          # AgentCloneManager -- persona creation/management
      persona_builder.py  # PersonaBuilder -- guided persona configuration
      schemas.py          # PersonaConfig, CloneConfig, GeographicProfile
    models.py             # SQLAlchemy models for new tables
    repository.py         # IntelligenceRepository for DB operations
```

### Pattern 1: Service Composition (Customer View)
**What:** CustomerViewService queries across existing repositories and assembles a unified view.
**When to use:** Any time the agent needs full cross-channel context for a customer/account.
**Example:**
```python
# CustomerViewService composes existing services
class CustomerViewService:
    def __init__(
        self,
        conversation_store: ConversationStore,      # Phase 3 -- Qdrant
        state_repository: ConversationStateRepository,  # Phase 4 -- PostgreSQL
        deal_repository: DealRepository,             # Phase 5 -- PostgreSQL
        meeting_repository: MeetingRepository,       # Phase 6 -- PostgreSQL
        summarizer: ContextSummarizer,
    ):
        self._conversations = conversation_store
        self._states = state_repository
        self._deals = deal_repository
        self._meetings = meeting_repository
        self._summarizer = summarizer

    async def get_unified_view(
        self, tenant_id: str, account_id: str
    ) -> UnifiedCustomerView:
        """Assemble complete customer view across all channels."""
        # Parallel fetch from all data sources
        conversations, deals, meetings, stakeholders = await asyncio.gather(
            self._conversations.search_conversations(tenant_id, query=f"account:{account_id}"),
            self._deals.list_opportunities_by_account(tenant_id, account_id),
            self._meetings.list_by_account(tenant_id, account_id),
            self._deals.list_stakeholders(tenant_id, account_id),
        )
        # Merge, sort chronologically, tag by channel
        timeline = self._build_timeline(conversations, deals, meetings)
        # Progressive summarization for older content
        summarized = await self._summarizer.summarize_timeline(timeline)
        return UnifiedCustomerView(
            account_id=account_id,
            timeline=summarized,
            signals=self._extract_current_signals(deals, conversations),
            stakeholder_map=stakeholders,
            action_history=self._build_action_history(conversations, meetings),
        )
```

### Pattern 2: Guardrail-Gated Autonomy
**What:** AutonomyEngine proposes actions; GuardrailChecker gates them by approval level.
**When to use:** Every autonomous action goes through the guardrail check.
**Example:**
```python
class GuardrailChecker:
    """Determines if an action can proceed autonomously or needs approval."""

    # From CONTEXT.md locked decisions
    AUTONOMOUS_ACTIONS = {
        "send_follow_up_email", "send_routine_response", "schedule_meeting",
        "qualify_conversation", "progress_early_stage",
    }
    APPROVAL_REQUIRED = {
        "send_proposal", "discuss_pricing", "negotiate_terms",
        "progress_past_evaluation", "contact_c_suite",
    }
    HARD_STOPS = {
        "commit_pricing", "modify_contract", "strategic_decision",
        "initiate_executive_relationship",
    }

    def check(self, action: AutonomyAction) -> GuardrailResult:
        if action.action_type in self.HARD_STOPS:
            return GuardrailResult(allowed=False, reason="hard_stop", requires_human=True)
        if action.action_type in self.APPROVAL_REQUIRED:
            return GuardrailResult(allowed=False, reason="approval_required", requires_human=True)
        if action.action_type in self.AUTONOMOUS_ACTIONS:
            # Additional check: deal stage gate for early-stage-only autonomy
            if action.deal_stage and action.deal_stage in ("negotiation", "closed_won", "closed_lost"):
                return GuardrailResult(allowed=False, reason="stage_gate")
            return GuardrailResult(allowed=True)
        return GuardrailResult(allowed=False, reason="unknown_action")
```

### Pattern 3: LLM-Based Pattern Detection with instructor
**What:** Use instructor for structured extraction of patterns from conversation data.
**When to use:** Pattern recognition engine analyzing account history for signals.
**Example:**
```python
class PatternMatch(BaseModel):
    """Structured pattern detection result from LLM analysis."""
    pattern_type: str  # "buying_signal", "risk_indicator", "engagement_change"
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]  # Quotes/references from source data
    severity: str = "medium"  # "low", "medium", "high", "critical"
    recommended_action: str
    reasoning: str

class PatternRecognitionEngine:
    async def detect_patterns(
        self, customer_view: UnifiedCustomerView, tenant_id: str
    ) -> list[PatternMatch]:
        """Run LLM-based pattern detection on unified customer data."""
        # Use instructor for structured extraction (matching Phase 4 pattern)
        patterns = await self._llm_service.completion(
            messages=self._build_pattern_prompt(customer_view),
            model="reasoning",
            response_model=list[PatternMatch],  # instructor structured output
        )
        # Filter by confidence threshold (starting at 0.7, tunable)
        return [p for p in patterns if p.confidence >= self._confidence_threshold]
```

### Pattern 4: Progressive Summarization
**What:** Tiered context management -- recent = full detail, older = progressively summarized.
**When to use:** Building customer view for accounts with long interaction history.
**Example:**
```python
class ContextSummarizer:
    """Progressive summarization for long-running account context."""
    RECENT_WINDOW_DAYS = 30      # Full detail
    MEDIUM_WINDOW_DAYS = 90      # Summarized per week
    OLD_WINDOW_DAYS = 365        # Summarized per month

    async def summarize_timeline(
        self, timeline: list[ChannelInteraction]
    ) -> SummarizedTimeline:
        now = datetime.now(timezone.utc)
        recent = [t for t in timeline if (now - t.timestamp).days <= self.RECENT_WINDOW_DAYS]
        medium = [t for t in timeline if self.RECENT_WINDOW_DAYS < (now - t.timestamp).days <= self.MEDIUM_WINDOW_DAYS]
        old = [t for t in timeline if (now - t.timestamp).days > self.MEDIUM_WINDOW_DAYS]

        # Recent: keep full detail
        # Medium: LLM-summarize per week
        medium_summaries = await self._summarize_by_period(medium, period="week")
        # Old: LLM-summarize per month
        old_summaries = await self._summarize_by_period(old, period="month")

        return SummarizedTimeline(
            recent_interactions=recent,
            medium_summaries=medium_summaries,
            historical_summaries=old_summaries,
        )
```

### Pattern 5: Agent Cloning via Configuration
**What:** Clones share code and knowledge; differ by persona configuration (stored as JSON).
**When to use:** Creating personalized agents for different sales reps.
**Example:**
```python
class PersonaConfig(BaseModel):
    """Configuration that makes each clone unique."""
    clone_id: str
    clone_name: str
    owner_id: str  # Sales rep who owns this clone
    formality: float = Field(default=0.5, ge=0.0, le=1.0)  # 0=casual, 1=formal
    aggressiveness: float = Field(default=0.5, ge=0.0, le=1.0)  # 0=consultative, 1=aggressive
    technical_depth: float = Field(default=0.5, ge=0.0, le=1.0)  # 0=business, 1=technical
    relationship_focus: float = Field(default=0.5, ge=0.0, le=1.0)  # 0=transactional, 1=relationship
    communication_examples: list[str] = Field(default_factory=list)  # Example messages for style
    geographic_region: str = "americas"
    custom_instructions: str = ""

class AgentCloneManager:
    async def create_clone(self, tenant_id: str, config: PersonaConfig) -> str:
        """Create a new agent clone with persona config."""
        # Store persona config in database
        # Clone shares: product knowledge, methodologies, pattern insights
        # Clone unique: persona config drives prompt adaptation
        ...

    def build_clone_prompt_section(self, config: PersonaConfig) -> str:
        """Generate prompt section from persona config for injection into system prompt."""
        return f"""
## Communication Style for {config.clone_name}
- Formality: {"formal" if config.formality > 0.7 else "casual" if config.formality < 0.3 else "balanced"}
- Approach: {"direct and results-focused" if config.aggressiveness > 0.7 else "consultative and patient" if config.aggressiveness < 0.3 else "balanced"}
- Technical depth: {"deep technical detail" if config.technical_depth > 0.7 else "business-level language" if config.technical_depth < 0.3 else "moderate technical detail"}
- Relationship style: {"relationship-first, invest in rapport" if config.relationship_focus > 0.7 else "efficient, get to business quickly" if config.relationship_focus < 0.3 else "balanced rapport and business"}
{f"Custom instructions: {config.custom_instructions}" if config.custom_instructions else ""}
"""
```

### Anti-Patterns to Avoid
- **Replacing existing repositories:** Phase 7 composes existing Phase 3/4/5/6 services -- it does NOT duplicate or replace their data stores.
- **Synchronous pattern detection:** Pattern analysis can be expensive. Never run it inline during conversation handling. Use background scheduling or post-conversation hooks.
- **Single monolithic autonomy service:** Split autonomy into distinct concerns: guardrail checking, goal tracking, action planning, and proactive scheduling.
- **Persona config in code:** Persona configurations must be database-stored and tenant-scoped, not hardcoded. The existing RegionalNuances hardcoded pattern is acceptable for shared regional knowledge but personas are per-clone and must be dynamic.
- **Autonomy without audit trail:** Every autonomous action must be logged with the decision reasoning, guardrail check result, and outcome tracking. Extend the existing OutcomeTracker pattern.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured pattern extraction | Custom regex/NLP pipeline | instructor + LLM (already in project) | Structured extraction from unstructured data is exactly what instructor does |
| Background task scheduling | Custom thread pool | asyncio background loops (Phase 4.1 pattern) | Already proven in the codebase, well-tested |
| Event-driven alerts | Custom WebSocket notification | Redis pub/sub via existing TenantEventBus + SSE (Phase 4.1) | Already built, tenant-scoped, with DLQ |
| Entity resolution | Fuzzy matching library | Email domain + participant exact match | CONTEXT.md locks "no fuzzy matching" |
| Progressive summarization | Token-counting manual truncation | LLM-based summarization with tiktoken budgeting | More intelligent than mechanical truncation |
| Persona adaptation in prompts | Custom template engine | Extend existing build_system_prompt() | Phase 4 prompt system already supports persona injection |
| Performance metrics computation | Custom aggregation | Extend Phase 4.1 AnalyticsService | Already handles outcome metrics, caching, dashboard views |

**Key insight:** Phase 7 is primarily a composition layer. Almost every building block already exists. The intelligence comes from how these blocks are composed, not from new infrastructure.

## Common Pitfalls

### Pitfall 1: Context Window Explosion
**What goes wrong:** Assembling a "unified customer view" by naively concatenating all data from all channels causes token limit blowout.
**Why it happens:** Long-running accounts may have hundreds of emails, dozens of meetings, and extensive CRM history.
**How to avoid:** Progressive summarization is mandatory. Recent (30 days) = full detail. Medium (30-90 days) = weekly summaries. Old (90+ days) = monthly summaries. Always compute total tokens before sending to LLM.
**Warning signs:** LLM calls timing out or returning truncated responses.

### Pitfall 2: Pattern Detection False Positives
**What goes wrong:** Aggressive pattern detection floods humans with alerts, causing alert fatigue.
**Why it happens:** Low confidence thresholds or detecting patterns in insufficient data.
**How to avoid:** Start with high confidence threshold (0.7). Require minimum evidence (at least 2 supporting data points). Implement "This was useful" / "False alarm" feedback loop to tune thresholds. Track alert-to-action ratio.
**Warning signs:** Human dismissal rate exceeding 50% of alerts.

### Pitfall 3: Autonomy Scope Creep
**What goes wrong:** The agent takes actions that should require human approval, leading to customer trust damage.
**Why it happens:** Guardrail conditions are too loose or edge cases aren't covered.
**How to avoid:** Fail-safe: unknown action types default to APPROVAL_REQUIRED, not AUTONOMOUS. Test guardrails with every conceivable action type. Hard stops are implemented as a deny list that cannot be overridden.
**Warning signs:** Escalation reports showing the agent took actions beyond its scope.

### Pitfall 4: Cross-Channel Data Staleness
**What goes wrong:** The unified customer view shows outdated information because data sources are queried with stale caches.
**Why it happens:** Over-caching or not invalidating after new interactions.
**How to avoid:** Customer view assembly always queries fresh data (no caching on the view itself). Individual data sources can cache (e.g., conversation search), but the composition is always real-time. Use event bus to trigger view refresh when new data arrives.
**Warning signs:** Agent referring to outdated budget figures or contact information.

### Pitfall 5: Clone Persona Interference with Methodology
**What goes wrong:** Aggressive persona settings override the sales methodology, leading to poor qualification or skipped discovery.
**Why it happens:** Persona prompt injection overrides the BANT/MEDDIC/QBS methodology prompts.
**How to avoid:** Persona affects communication STYLE only. Methodology sections in prompts are marked as non-overridable. Persona config explicitly states: "Core sales methodology is consistent regardless of persona settings."
**Warning signs:** Qualification completion rates dropping for specific clones.

### Pitfall 6: Goal Tracking Without Baseline
**What goes wrong:** Self-directed goal pursuit starts with no historical data, making targets meaningless.
**Why it happens:** The system launches with revenue targets but no pipeline history to benchmark against.
**How to avoid:** Cold-start phase: first 30 days, the system observes and establishes baselines. Goals are set relative to observed activity, not absolute targets. Admin can override with manual targets.
**Warning signs:** Goal achievement appearing either 0% or 100% with no middle ground.

### Pitfall 7: Geographic Adaptation Over-Engineering
**What goes wrong:** Building complex per-country communication rules that are hard to maintain.
**Why it happens:** Trying to handle every cultural nuance programmatically.
**How to avoid:** CONTEXT.md locks "communication style only." Use the existing RegionalNuances system (Phase 3) as the data source. Add a geographic profile to persona config that injects region-appropriate tone guidance into prompts. Don't build a rules engine.
**Warning signs:** Regional config becoming larger than the actual service code.

## Code Examples

### Database Migration for Phase 7 Tables
```python
# New tables needed:
# 1. agent_clones -- persona configuration per clone
# 2. insights -- detected patterns and alerts
# 3. goals -- revenue targets and metrics
# 4. autonomous_actions -- audit trail of autonomous decisions
# 5. alert_feedback -- "useful" / "false alarm" feedback on alerts

# Pattern: matches Phase 5/6 migration style (TenantBase, JSON columns)
class AgentCloneModel(TenantBase):
    __tablename__ = "agent_clones"
    __table_args__ = (
        UniqueConstraint("tenant_id", "clone_name", name="uq_clone_tenant_name"),
        {"schema": "tenant"},
    )
    id = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id = mapped_column(UUID(as_uuid=True), nullable=False)
    clone_name = mapped_column(String(200), nullable=False)
    owner_id = mapped_column(String(100), nullable=False)
    persona_config = mapped_column(JSON, default=dict, server_default=text("'{}'::json"))
    is_active = mapped_column(Boolean, default=True, server_default=text("true"))
    performance_metrics = mapped_column(JSON, default=dict, server_default=text("'{}'::json"))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

class InsightModel(TenantBase):
    __tablename__ = "insights"
    __table_args__ = ({"schema": "tenant"},)
    id = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id = mapped_column(UUID(as_uuid=True), nullable=False)
    pattern_type = mapped_column(String(50), nullable=False)
    severity = mapped_column(String(20), default="medium")
    confidence = mapped_column(Float, nullable=False)
    evidence = mapped_column(JSON, default=list)
    recommended_action = mapped_column(Text, nullable=True)
    reasoning = mapped_column(Text, nullable=True)
    status = mapped_column(String(20), default="pending")  # pending, acted, dismissed
    feedback = mapped_column(String(20), nullable=True)  # useful, false_alarm
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())

class GoalModel(TenantBase):
    __tablename__ = "goals"
    __table_args__ = ({"schema": "tenant"},)
    id = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id = mapped_column(UUID(as_uuid=True), nullable=False)
    clone_id = mapped_column(UUID(as_uuid=True), nullable=True)  # NULL = tenant-wide
    goal_type = mapped_column(String(50), nullable=False)  # revenue, pipeline, activity
    target_value = mapped_column(Float, nullable=False)
    current_value = mapped_column(Float, default=0.0)
    period_start = mapped_column(DateTime(timezone=True), nullable=False)
    period_end = mapped_column(DateTime(timezone=True), nullable=False)
    status = mapped_column(String(20), default="active")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())

class AutonomousActionModel(TenantBase):
    __tablename__ = "autonomous_actions"
    __table_args__ = ({"schema": "tenant"},)
    id = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id = mapped_column(UUID(as_uuid=True), nullable=False)
    clone_id = mapped_column(UUID(as_uuid=True), nullable=True)
    action_type = mapped_column(String(50), nullable=False)
    target_account_id = mapped_column(UUID(as_uuid=True), nullable=True)
    target_contact_id = mapped_column(String(100), nullable=True)
    trigger_reason = mapped_column(Text, nullable=False)
    guardrail_result = mapped_column(String(20), nullable=False)  # allowed, blocked, approval_required
    approval_status = mapped_column(String(20), nullable=True)  # pending, approved, rejected
    execution_result = mapped_column(JSON, default=dict)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### Proactive Outreach Scheduler (Extending Phase 4.1 Pattern)
```python
# Extends the asyncio background loop pattern from Phase 4.1 scheduler
INTELLIGENCE_TASK_INTERVALS = {
    "pattern_scan": 6 * 60 * 60,            # Every 6 hours: scan for patterns
    "proactive_outreach_check": 60 * 60,     # Every hour: check for triggered outreach
    "goal_progress_update": 24 * 60 * 60,    # Daily: update goal progress
    "daily_digest_generation": 24 * 60 * 60, # Daily: generate insight digests
    "context_summarization": 24 * 60 * 60,   # Daily: progressively summarize old context
}

async def setup_intelligence_scheduler(
    pattern_engine: PatternRecognitionEngine,
    autonomy_engine: AutonomyEngine,
    goal_tracker: GoalTracker,
    customer_view_service: CustomerViewService,
) -> dict:
    """Configure Phase 7 background tasks, following Phase 4.1 setup_learning_scheduler pattern."""
    async def pattern_scan_task():
        try:
            # Scan active accounts for pattern changes
            # Uses the same tenant iteration pattern as calibration_check_task
            ...
        except Exception:
            logger.warning("intelligence.pattern_scan_failed", exc_info=True)

    async def proactive_outreach_check_task():
        try:
            # Check for triggered outreach (follow-ups, silence break, buying signals)
            # Each proposed action goes through GuardrailChecker
            ...
        except Exception:
            logger.warning("intelligence.proactive_outreach_failed", exc_info=True)

    return {
        "pattern_scan": pattern_scan_task,
        "proactive_outreach_check": proactive_outreach_check_task,
        "goal_progress_update": goal_progress_update_task,
        "daily_digest_generation": daily_digest_task,
        "context_summarization": summarization_task,
    }
```

### Entity Linking (Cross-Channel)
```python
class EntityLinker:
    """Links conversations to accounts/deals via email domain + participant overlap.

    Per CONTEXT.md: No fuzzy matching. Explicit domain/participant overlap only.
    """

    async def link_to_account(
        self,
        tenant_id: str,
        participants: list[str],  # Email addresses
        deal_repository: DealRepository,
    ) -> str | None:
        """Find matching account by email domain overlap."""
        # Extract domains from participant emails
        domains = {email.split("@")[1].lower() for email in participants if "@" in email}

        # Query accounts by stakeholder email domains
        accounts = await deal_repository.list_accounts(tenant_id)
        for account in accounts:
            stakeholders = await deal_repository.list_stakeholders(tenant_id, account.id)
            account_domains = {
                s.contact_email.split("@")[1].lower()
                for s in stakeholders
                if s.contact_email and "@" in s.contact_email
            }
            if domains & account_domains:  # Set intersection
                return account.id
        return None
```

### Conflict Resolution (Most Recent Wins)
```python
class ConflictResolver:
    """Resolves data conflicts across channels per CONTEXT.md: most recent wins."""

    def resolve_signal(
        self, signals: list[ChannelSignal]
    ) -> ChannelSignal:
        """Given conflicting signals from different channels, return the most recent."""
        if not signals:
            raise ValueError("No signals to resolve")
        # Sort by timestamp descending, return most recent
        return sorted(signals, key=lambda s: s.timestamp, reverse=True)[0]
```

### Geographic Adaptation in Prompts
```python
class GeographicAdapter:
    """Extends RegionalNuances into prompt-ready geographic guidance."""

    def __init__(self):
        self._nuances = RegionalNuances()  # Existing Phase 3 service

    def build_geographic_prompt_section(self, region: str) -> str:
        """Generate prompt section for geographic communication adaptation."""
        try:
            context = self._nuances.get_regional_context(region)
        except KeyError:
            return ""  # Unknown region: no adaptation

        return f"""
## Geographic Communication Adaptation ({context['name']})
Communication style: {context['communication_style']}
Cultural awareness:
{chr(10).join(f"- {note}" for note in context['cultural_notes'][:3])}

IMPORTANT: Adapt your TONE and COMMUNICATION STYLE per the above guidance.
Do NOT change the sales methodology, qualification process, or deal progression approach.
The core methodology is consistent across all regions.
"""
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual pipeline review | Autonomous pattern detection with LLM | 2024-2025 | Patterns caught earlier, proactive vs reactive |
| Separate per-channel views | Unified customer 360 views | 2024-2025 | Complete context for every interaction |
| Static agent personas | Configuration-driven persona adaptation | 2025-2026 | Personalization without code changes |
| Rule-based trigger systems | LLM-based signal detection with confidence | 2025 | Better handling of nuanced buying/risk signals |
| Manual CRM updates for goals | Self-directed goal tracking with metrics | 2025 | Agent accountability without human monitoring |

**Current in this codebase:**
- Progressive summarization uses LLM (not keyword extraction) for intelligent compression
- instructor library for structured LLM output (already proven in Phases 4, 5)
- asyncio background loops for scheduling (proven in Phase 4.1)
- Redis pub/sub for real-time alerts (proven in Phase 4.1 SSE)

## Open Questions

1. **Tenant iteration for background tasks**
   - What we know: Phase 4.1 scheduler calibration_check_task notes "tenant-scoped placeholder" because iterating all tenants is not yet implemented.
   - What's unclear: How to efficiently iterate tenants for pattern scans and proactive outreach.
   - Recommendation: Add a TenantIterator helper that queries the shared schema's tenants table. Reuse for both Phase 4.1 and Phase 7 scheduled tasks.

2. **LLM cost for pattern scanning**
   - What we know: Pattern detection uses LLM calls (instructor) per account.
   - What's unclear: Cost impact of scanning all active accounts every 6 hours.
   - Recommendation: Scan only accounts with recent activity (interaction in last 7 days). Track LLM cost per pattern scan via existing Langfuse integration. Set cost budget alerts.

3. **Persona preview before deployment**
   - What we know: CONTEXT.md wants "preview before deployment" for persona builder.
   - What's unclear: What "preview" means technically.
   - Recommendation: Generate a sample email and chat message using the persona config and return them in the API response. User reviews samples before activating the clone.

4. **Alert delivery channel**
   - What we know: Critical alerts need real-time delivery; daily digest for lower-priority.
   - What's unclear: Whether to use email, in-app notification, or both.
   - Recommendation: Use existing SSE endpoint (Phase 4.1) for real-time in-app alerts. Use existing Gmail service for daily digest emails. Both channels are already built.

5. **Shared learning across clones**
   - What we know: CONTEXT.md states patterns should be shared across clones within a tenant.
   - What's unclear: Exact mechanism for pattern sharing.
   - Recommendation: Insights are stored at the tenant level (not clone level). Pattern recognition runs at tenant scope. Per-clone metrics are tracked in the agent_clones.performance_metrics JSON column. This means all clones within a tenant automatically share pattern insights.

## Sources

### Primary (HIGH confidence)
- Codebase analysis: src/app/agents/sales/ (agent.py, schemas.py, prompts.py, qbs/)
- Codebase analysis: src/app/deals/ (repository.py, hooks.py, schemas.py, models.py, progression.py)
- Codebase analysis: src/app/learning/ (outcomes.py, analytics.py, schemas.py, scheduler.py)
- Codebase analysis: src/app/meetings/ (schemas.py, repository.py, all subdirectories)
- Codebase analysis: src/app/events/schemas.py (event bus and event types)
- Codebase analysis: src/knowledge/conversations/store.py (conversation search)
- Codebase analysis: src/knowledge/regional/nuances.py (geographic data)
- Codebase analysis: src/app/main.py (service wiring patterns)
- Codebase analysis: src/app/config.py (settings and dependencies)
- CONTEXT.md decisions (user-locked choices for Phase 7)

### Secondary (MEDIUM confidence)
- [Context Window Management Strategies](https://www.getmaxim.ai/articles/context-window-management-strategies-for-long-context-ai-agents-and-chatbots/) -- progressive summarization patterns
- [LLM Chat History Summarization Guide](https://mem0.ai/blog/llm-chat-history-summarization-guide-2025) -- ConversationSummaryBufferMemory hybrid approach
- [Human-in-the-Loop Middleware in Python](https://www.flowhunt.io/blog/human-in-the-loop-middleware-python-safe-ai-agents/) -- approval workflow patterns
- [Building AI Agents with Personas, Goals, and Dynamic Memory](https://medium.com/@leviexraspk/building-ai-agents-with-personas-goals-and-dynamic-memory-6253acacdc0a) -- persona architecture
- [Building a Multi-Tenant Production-Grade AI Agent](https://ingenimax.ai/blog/building-multi-tenant-ai-agent) -- multi-tenant agent patterns

### Tertiary (LOW confidence)
- [Agent Control Plane Architecture](https://www.cio.com/article/4130922/the-agent-control-plane-architecting-guardrails-for-a-new-digital-workforce.html) -- guardrail framework concepts (general, not specific to this stack)
- [Entity Resolution in Noisy Data](https://medium.com/data-science/entity-resolution-identifying-real-world-entities-in-noisy-data-3e8c59f4f41c) -- entity resolution concepts (not directly used due to "no fuzzy matching" decision)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies needed; all libraries already proven in codebase
- Architecture: HIGH -- service composition pattern well-established in Phases 4-6; new modules follow identical patterns
- Pitfalls: HIGH -- pitfalls derived from concrete codebase constraints and CONTEXT.md decisions
- Code examples: HIGH -- based on actual codebase patterns (repository, scheduler, prompt builder, instructor)
- Pattern recognition approach: MEDIUM -- LLM-based detection is well-established but tuning thresholds will require iteration
- Progressive summarization: MEDIUM -- approach is sound but optimal window sizes (30/90/365 days) need validation with real data

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (30 days -- stable stack, no fast-moving dependencies)
