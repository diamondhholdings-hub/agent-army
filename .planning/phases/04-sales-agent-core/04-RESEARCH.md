# Phase 4: Sales Agent Core - Research

**Researched:** 2026-02-11
**Domain:** LLM-powered sales agent with GSuite integration (Gmail, Google Chat), persona adaptation, sales methodology execution (BANT/MEDDIC), conversation state tracking, and human escalation
**Confidence:** HIGH

## Summary

Phase 4 builds the first concrete specialist agent in the platform -- a Sales Agent that can conduct text-based sales conversations via Gmail and Google Chat, adapting its communication style to customer personas (IC, manager, C-suite), executing BANT and MEDDIC qualification frameworks conversationally using Chris Voss methodology, tracking conversation state across interactions, recommending next actions, and escalating to humans when confidence drops below 70%.

The standard approach is to implement the Sales Agent as a BaseAgent subclass using the existing orchestration infrastructure (Phase 2), with Google Workspace APIs for email/chat integration, the existing RAG pipeline and methodology library (Phase 3) for context compilation, Pydantic models for structured qualification signal extraction, and a state machine pattern for conversation lifecycle tracking. The LLM (Claude Sonnet 4 via LiteLLM) generates contextual messages and extracts qualification signals; structured outputs ensure reliable data extraction.

Key recommendations: Use `google-api-python-client` + `google-auth` for GSuite APIs (wrapped with `asyncio.to_thread` for async compatibility), Claude structured outputs via LiteLLM for qualification signal extraction, a PostgreSQL-backed conversation state model with deal stage tracking, and prompt engineering (not hard-coded rules) for Chris Voss methodology and persona adaptation.

**Primary recommendation:** Build the Sales Agent as a BaseAgent subclass with three composable capabilities -- GSuite communication, persona-adapted message generation with methodology execution, and conversation state tracking with escalation logic -- each independently testable and wired through the existing supervisor topology.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-api-python-client | >=2.0.0 | Gmail API and Google Chat API access | Official Google client library, discovery-based API |
| google-auth | >=2.0.0 | Service account auth with domain-wide delegation | Required by google-api-python-client for OAuth2 |
| litellm | >=1.60.0 (already installed) | LLM abstraction for Claude Sonnet 4 | Already in stack from Phase 1, provides structured output support |
| pydantic | >=2.0.0 (already installed) | Qualification signal schemas, conversation state models | Already in stack, native structured output support with Claude |
| instructor | >=1.7.0 | Structured LLM output extraction with validation and retry | 3M+ monthly downloads, works with LiteLLM, handles edge cases |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| google-auth-httplib2 | >=0.2.0 | HTTP transport for google-api-python-client | Required dependency for Google API calls |
| google-auth-oauthlib | >=1.2.0 | OAuth2 flow helpers | Needed for initial auth setup and token management |
| jinja2 | >=3.1.0 | Email template rendering | Structured email formatting with persona variables |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| google-api-python-client | aiogoogle (native async) | Newer, less battle-tested; google-api-python-client is official Google SDK with better support |
| instructor | Claude native structured outputs via LiteLLM | Instructor adds retry logic and validation; native Claude structured outputs lack automatic retry on schema violation |
| jinja2 | f-strings | Jinja2 better for complex multi-section email templates with conditional blocks |

**Installation:**
```bash
pip install google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib instructor jinja2
```

## Architecture Patterns

### Recommended Project Structure
```
src/
  app/
    agents/
      sales/                    # NEW: Sales agent module
        __init__.py
        agent.py                # SalesAgent(BaseAgent) - main agent class
        capabilities.py         # Capability declarations for registry
        prompts.py              # System prompts, persona templates, Voss methodology
        schemas.py              # Pydantic models: QualificationSignals, ConversationState, etc.
    services/
      gsuite/                   # NEW: GSuite integration service
        __init__.py
        auth.py                 # Service account auth + domain-wide delegation
        gmail.py                # Gmail send/read/thread operations
        chat.py                 # Google Chat send/read operations
        models.py               # Email/Chat message schemas
  knowledge/
    conversations/              # EXISTING: conversation store, session manager
    methodology/                # EXISTING: BANT/MEDDIC frameworks
    rag/                        # EXISTING: agentic RAG pipeline
```

### Pattern 1: Sales Agent as BaseAgent Subclass
**What:** SalesAgent extends BaseAgent (from Phase 2), registers capabilities (email_outreach, chat_messaging, qualification, escalation), and implements execute() to handle different task types.
**When to use:** All sales interaction tasks routed through the supervisor.
**Example:**
```python
# Source: Existing BaseAgent pattern from src/app/agents/base.py
class SalesAgent(BaseAgent):
    """Sales Agent for text-based sales interactions."""

    def __init__(
        self,
        registration: AgentRegistration,
        llm_service: LLMService,
        gmail_service: GmailService,
        chat_service: ChatService,
        rag_pipeline: AgenticRAGPipeline,
        conversation_store: ConversationStore,
        session_manager: SessionManager,
    ) -> None:
        super().__init__(registration)
        self._llm = llm_service
        self._gmail = gmail_service
        self._chat = chat_service
        self._rag = rag_pipeline
        self._conversations = conversation_store
        self._sessions = session_manager

    async def execute(self, task: dict, context: dict) -> dict:
        """Route task to appropriate handler based on task type."""
        task_type = task.get("type")
        if task_type == "send_email":
            return await self._handle_email(task, context)
        elif task_type == "send_chat":
            return await self._handle_chat(task, context)
        elif task_type == "qualify_lead":
            return await self._handle_qualification(task, context)
        elif task_type == "recommend_action":
            return await self._handle_next_action(task, context)
        else:
            raise ValueError(f"Unknown task type: {task_type}")
```

### Pattern 2: Context Compilation Pipeline
**What:** Before generating any message, compile full context from: deal stage, account history (conversation store), product knowledge (RAG), methodology guidance (methodology library), and persona profile. Feed this compiled context to the LLM via the existing WorkingContextCompiler.
**When to use:** Every outbound message (email or chat).
**Example:**
```python
# Source: Existing ContextManager from src/app/context/manager.py
async def _compile_sales_context(
    self, task: dict, context: dict
) -> dict:
    """Compile rich sales context from all sources."""
    tenant_id = context["tenant_id"]
    account_id = task.get("account_id", "")
    deal_stage = task.get("deal_stage", "discovery")

    # 1. Get conversation history for this account
    history = await self._conversations.search_conversations(
        tenant_id=tenant_id,
        query=f"account:{account_id}",
        top_k=10,
    )

    # 2. Get relevant product/methodology knowledge via RAG
    rag_response = await self._rag.run(
        query=task.get("description", ""),
        tenant_id=tenant_id,
        conversation_context=history,
    )

    # 3. Get methodology guidance for current stage
    methodology_context = self._get_methodology_for_stage(deal_stage)

    return {
        "conversation_history": history,
        "product_knowledge": rag_response.answer,
        "methodology_guidance": methodology_context,
        "deal_stage": deal_stage,
        "persona": task.get("persona", "manager"),
        "sources": rag_response.sources,
    }
```

### Pattern 3: Structured Qualification Signal Extraction
**What:** After every conversation turn, use Claude structured outputs to extract qualification signals (BANT + MEDDIC fields) from the conversation, updating the qualification state incrementally.
**When to use:** After receiving any customer response (email reply, chat message).
**Example:**
```python
# Source: Claude structured outputs (platform.claude.com/docs)
from pydantic import BaseModel, Field
from typing import Optional

class BANTSignals(BaseModel):
    """BANT qualification signals extracted from conversation."""
    budget_identified: bool = False
    budget_range: Optional[str] = None
    budget_evidence: Optional[str] = None
    authority_identified: bool = False
    authority_contact: Optional[str] = None
    authority_evidence: Optional[str] = None
    need_identified: bool = False
    need_description: Optional[str] = None
    need_evidence: Optional[str] = None
    timeline_identified: bool = False
    timeline_description: Optional[str] = None
    timeline_evidence: Optional[str] = None

class MEDDICSignals(BaseModel):
    """MEDDIC qualification signals extracted from conversation."""
    metrics_identified: bool = False
    metrics_description: Optional[str] = None
    economic_buyer_identified: bool = False
    economic_buyer_contact: Optional[str] = None
    decision_criteria_identified: bool = False
    decision_criteria: list[str] = Field(default_factory=list)
    decision_process_identified: bool = False
    decision_process_description: Optional[str] = None
    pain_identified: bool = False
    pain_description: Optional[str] = None
    champion_identified: bool = False
    champion_contact: Optional[str] = None

class QualificationExtraction(BaseModel):
    """Combined qualification signals with confidence."""
    bant: BANTSignals = Field(default_factory=BANTSignals)
    meddic: MEDDICSignals = Field(default_factory=MEDDICSignals)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    key_insights: list[str] = Field(default_factory=list)
    recommended_next_questions: list[str] = Field(default_factory=list)
```

### Pattern 4: Conversation State Machine
**What:** Track deal progression through states (prospecting -> discovery -> qualification -> evaluation -> negotiation -> closed_won/closed_lost) with transition rules based on qualification signal completeness and engagement signals.
**When to use:** State persisted per deal/account, updated after each interaction.
**Example:**
```python
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime

class DealStage(str, Enum):
    PROSPECTING = "prospecting"
    DISCOVERY = "discovery"
    QUALIFICATION = "qualification"
    EVALUATION = "evaluation"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"
    STALLED = "stalled"

class ConversationState(BaseModel):
    """Persistent state for a sales conversation/deal."""
    state_id: str
    tenant_id: str
    account_id: str
    contact_id: str
    deal_stage: DealStage = DealStage.PROSPECTING
    persona_type: str = "manager"  # ic, manager, c_suite
    bant_signals: BANTSignals = Field(default_factory=BANTSignals)
    meddic_signals: MEDDICSignals = Field(default_factory=MEDDICSignals)
    interaction_count: int = 0
    last_interaction: datetime | None = None
    last_channel: str = ""
    escalated: bool = False
    escalation_reason: str | None = None
    confidence_score: float = 0.5
    next_actions: list[str] = Field(default_factory=list)
    follow_up_scheduled: datetime | None = None
    metadata: dict = Field(default_factory=dict)
```

### Pattern 5: GSuite Async Wrapper
**What:** The google-api-python-client is synchronous. Wrap all API calls with `asyncio.to_thread()` to avoid blocking the event loop, while keeping one service instance per user delegation.
**When to use:** Every Gmail and Google Chat API call.
**Example:**
```python
import asyncio
from google.oauth2 import service_account
from googleapiclient.discovery import build

class GmailService:
    """Async wrapper around Gmail API."""

    def __init__(self, service_account_file: str, scopes: list[str]) -> None:
        self._sa_file = service_account_file
        self._scopes = scopes

    def _get_service(self, user_email: str):
        """Build Gmail service impersonating a user."""
        creds = service_account.Credentials.from_service_account_file(
            self._sa_file, scopes=self._scopes
        )
        delegated = creds.with_subject(user_email)
        return build("gmail", "v1", credentials=delegated)

    async def send_email(
        self, user_email: str, to: str, subject: str, body: str,
        thread_id: str | None = None,
    ) -> dict:
        """Send an email via Gmail API (async wrapped)."""
        service = self._get_service(user_email)

        def _send():
            import base64
            from email.message import EmailMessage
            msg = EmailMessage()
            msg.set_content(body)
            msg["To"] = to
            msg["Subject"] = subject
            encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            body_payload = {"raw": encoded}
            if thread_id:
                body_payload["threadId"] = thread_id
            return service.users().messages().send(
                userId="me", body=body_payload
            ).execute()

        return await asyncio.to_thread(_send)
```

### Pattern 6: Persona-Adapted Prompt System
**What:** System prompts that dynamically adjust tone, formality, message length, and question style based on the target persona. Uses the locked Chris Voss methodology for all personas.
**When to use:** Every message generation call.
**Example:**
```python
PERSONA_CONFIGS = {
    "ic": {
        "tone": "conversational, friendly, peer-to-peer",
        "formality": "low",
        "message_length": "moderate, get to the point but be warm",
        "question_style": "direct but curious, show genuine interest",
        "voss_emphasis": "mirroring, labels ('It sounds like...')",
    },
    "manager": {
        "tone": "balanced, strategic yet approachable",
        "formality": "medium",
        "message_length": "contextual, thorough when needed",
        "question_style": "calibrated questions ('How are you thinking about...')",
        "voss_emphasis": "calibrated questions, tactical empathy",
    },
    "c_suite": {
        "tone": "formal, business-case focused, concise",
        "formality": "high",
        "message_length": "concise, lead with business impact",
        "question_style": "strategic, focus on outcomes and ROI",
        "voss_emphasis": "accusation audits, late-night FM DJ voice",
    },
}
```

### Pattern 7: Human Escalation with Structured Handoff
**What:** When confidence drops below 70% or trigger conditions are met, generate a structured escalation report and notify via event bus.
**When to use:** After confidence evaluation on each interaction.
**Example:**
```python
class EscalationReport(BaseModel):
    """Structured handoff report for human escalation."""
    escalation_id: str
    tenant_id: str
    account_id: str
    contact_id: str
    deal_stage: str
    escalation_trigger: str  # confidence_low, high_stakes, customer_request, complexity
    confidence_score: float
    account_context: str
    what_agent_tried: str
    why_escalating: str
    recommended_next_action: str
    relevant_conversation_excerpts: list[str]
    notification_targets: list[str]  # [rep_email, manager_email]
```

### Anti-Patterns to Avoid
- **Hard-coded conversation scripts:** Do NOT create rigid decision trees for sales conversations. Use LLM with strong system prompts and methodology context instead. Sales conversations are too varied for if/else trees.
- **Storing full conversation in agent state:** Do NOT keep entire conversation history in working memory. Use the existing ConversationStore + RAG pipeline for retrieval. The WorkingContextCompiler handles token budgeting.
- **Separate LLM calls for each qualification field:** Do NOT make 10+ LLM calls to extract each BANT/MEDDIC field individually. Use a single structured extraction call that returns all signals at once.
- **Synchronous Google API calls on event loop:** Do NOT call google-api-python-client directly in async handlers. Always wrap with asyncio.to_thread().
- **Building new conversation storage:** Do NOT create a new storage layer. Phase 3 already built ConversationStore and SessionManager -- use them.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Email MIME encoding | Custom email builder | Python stdlib `email.message.EmailMessage` | RFC 2822 compliance, handles attachments, encoding edge cases |
| Google auth | Custom OAuth2 flow | `google-auth` + service account with domain-wide delegation | Token refresh, caching, impersonation all handled |
| Structured LLM output parsing | Regex/JSON parsing of LLM text | `instructor` library or Claude native structured outputs | Handles validation, retry on schema violation, edge cases |
| Conversation memory | New database/storage layer | Existing `ConversationStore` + `SessionManager` from Phase 3 | Already built, tenant-scoped, semantic search ready |
| Methodology guidance | Hard-coded framework prompts | Existing `MethodologyLibrary` + RAG from Phase 3 | Already loaded into Qdrant with full BANT/MEDDIC/SPIN content |
| Token budgeting | Manual context truncation | Existing `WorkingContextCompiler` from Phase 2 | Already handles 4-section budget allocation |
| Event bus notifications | Custom webhook/notification system | Existing `TenantEventBus` from Phase 2 | Tenant-scoped Redis Streams, consumer groups, DLQ |

**Key insight:** Phase 4 is primarily a composition layer -- it composes existing Phase 2 (orchestration, context, events) and Phase 3 (knowledge, conversations, RAG) infrastructure into a sales-specific agent. The new code is mostly prompt engineering, GSuite integration, and qualification state management. Avoid rebuilding existing capabilities.

## Common Pitfalls

### Pitfall 1: Google API Service Instance Reuse
**What goes wrong:** Creating a new `build("gmail", "v1", ...)` instance for every API call causes excessive HTTP connection overhead and credential refresh.
**Why it happens:** Developers treat it like a stateless function call.
**How to avoid:** Cache service instances per user delegation. Use a dictionary keyed by user_email, with TTL for credential refresh.
**Warning signs:** Slow email sending, excessive auth token requests in logs.

### Pitfall 2: Losing Email Thread Context
**What goes wrong:** Emails sent by the agent don't thread properly in Gmail, appearing as separate conversations.
**Why it happens:** Missing `threadId` in send request, or not matching `Subject`, `In-Reply-To`, and `References` headers.
**How to avoid:** Always store and pass `threadId` when replying. Set `In-Reply-To` and `References` headers per RFC 2822. Keep `Subject` consistent (add `Re:` prefix for replies).
**Warning signs:** Customer receives each email as separate conversation in their inbox.

### Pitfall 3: Qualification Signal Overwriting
**What goes wrong:** New qualification extraction replaces previous signals instead of merging incrementally.
**Why it happens:** Each extraction returns the full schema; naive storage replaces the old state.
**How to avoid:** Implement merge logic: only update fields that have new non-null values. Keep evidence/source attribution per field so conflicting signals can be resolved.
**Warning signs:** Known qualification data disappears after new interactions.

### Pitfall 4: Persona Adaptation Being Superficial
**What goes wrong:** Persona adaptation only changes greeting/sign-off but the body reads identically for IC vs C-suite.
**Why it happens:** Persona config only in the greeting template, not in the core message generation prompt.
**How to avoid:** The persona config must be part of the system prompt that generates the entire message body. Include guidance on: what to lead with (features vs business impact), how much detail to include, what questions to ask, and how to frame the ask.
**Warning signs:** Swap personas and the middle 80% of the message is identical.

### Pitfall 5: Escalation Without Context
**What goes wrong:** Human gets escalation notification but lacks context to act on it, requiring them to reconstruct the situation from scratch.
**Why it happens:** Escalation fires a bare "low confidence" alert without compiled context.
**How to avoid:** Use the EscalationReport schema that includes full account context, deal stage, what was tried, why escalating, and recommended next action. Include actual conversation excerpts (not just IDs).
**Warning signs:** Sales reps ignore escalation notifications because they're too sparse to be actionable.

### Pitfall 6: Gmail API Watch Expiry
**What goes wrong:** Agent stops receiving incoming email notifications after 7 days.
**Why it happens:** Gmail push notification watches expire every 7 days and must be renewed.
**How to avoid:** Implement a periodic renewal task (e.g., every 6 days) that calls `users().watch()` for all monitored mailboxes. Store watch expiry timestamps and alert on renewal failures.
**Warning signs:** Agent stops responding to incoming emails, but can still send.

### Pitfall 7: Blocking Event Loop with Google API Calls
**What goes wrong:** FastAPI request handling becomes sluggish, timeouts increase.
**Why it happens:** google-api-python-client is synchronous; calling it directly in async handlers blocks the event loop.
**How to avoid:** Always use `asyncio.to_thread()` for all Google API calls. Consider a dedicated thread pool if volume is high.
**Warning signs:** High latency on all API endpoints, not just GSuite-related ones.

## Code Examples

Verified patterns from official sources:

### Gmail API: Send Email with Thread
```python
# Source: https://developers.google.com/gmail/api/guides/sending
import base64
from email.message import EmailMessage

def create_gmail_message(
    to: str,
    subject: str,
    body_html: str,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
) -> dict:
    """Create a Gmail API message payload."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body_html, subtype="html")

    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    payload = {"raw": encoded}
    if thread_id:
        payload["threadId"] = thread_id
    return payload
```

### Google Chat API: Send Message to Space
```python
# Source: https://developers.google.com/workspace/chat/create-messages
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/chat.bot"]

def send_chat_message(
    service_account_file: str,
    space_name: str,
    text: str,
    thread_key: str | None = None,
) -> dict:
    """Send a message to a Google Chat space."""
    creds = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES
    )
    chat = build("chat", "v1", credentials=creds)

    message_body = {"text": text}
    kwargs = {"parent": space_name, "body": message_body}
    if thread_key:
        kwargs["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
        message_body["thread"] = {"threadKey": thread_key}

    return chat.spaces().messages().create(**kwargs).execute()
```

### Domain-Wide Delegation for User Impersonation
```python
# Source: https://developers.google.com/identity/protocols/oauth2/service-account
from google.oauth2 import service_account

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

def get_delegated_credentials(
    service_account_file: str,
    user_email: str,
    scopes: list[str],
) -> service_account.Credentials:
    """Get credentials for impersonating a user via domain-wide delegation."""
    credentials = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=scopes
    )
    return credentials.with_subject(user_email)
```

### Structured Qualification Extraction with Instructor + LiteLLM
```python
# Source: https://python.useinstructor.com/integrations/litellm/
import instructor
from pydantic import BaseModel, Field
from typing import Optional

class QualificationSignals(BaseModel):
    """Qualification signals extracted from conversation."""
    budget_mentioned: bool = False
    budget_range: Optional[str] = None
    authority_level: Optional[str] = None
    need_description: Optional[str] = None
    timeline_mentioned: bool = False
    timeline_description: Optional[str] = None
    pain_points: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    next_questions: list[str] = Field(default_factory=list)

# Initialize with LiteLLM
client = instructor.from_provider("litellm/anthropic/claude-sonnet-4-20250514", async_client=True)

async def extract_qualification(conversation_text: str) -> QualificationSignals:
    """Extract qualification signals from conversation text."""
    return await client.create(
        response_model=QualificationSignals,
        messages=[
            {"role": "system", "content": "Extract BANT/MEDDIC qualification signals from this sales conversation. Be conservative -- only mark signals as identified if there is clear evidence."},
            {"role": "user", "content": conversation_text},
        ],
    )
```

### Async-Wrapped Google API Call Pattern
```python
# Source: Pattern derived from google-api-python-client thread safety docs
import asyncio
from functools import lru_cache
from google.oauth2 import service_account
from googleapiclient.discovery import build

class AsyncGSuiteService:
    """Base class for async-wrapped Google API services."""

    def __init__(self, service_account_file: str, scopes: list[str]) -> None:
        self._sa_file = service_account_file
        self._scopes = scopes
        self._service_cache: dict[str, tuple] = {}  # user_email -> (service, expiry)

    def _build_service(self, api: str, version: str, user_email: str):
        """Build a Google API service with user impersonation."""
        creds = service_account.Credentials.from_service_account_file(
            self._sa_file, scopes=self._scopes
        )
        delegated = creds.with_subject(user_email)
        return build(api, version, credentials=delegated)

    async def _run_sync(self, fn):
        """Run a synchronous Google API call on a thread."""
        return await asyncio.to_thread(fn)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw JSON prompting for structured extraction | Claude native structured outputs with json_schema | Late 2025 (GA) | Guaranteed schema-compliant responses, no retry needed for format issues |
| Separate BANT/MEDDIC scoring | Parallel BANT+MEDDIC with single extraction | 2025+ | One LLM call extracts both frameworks simultaneously |
| google-api-python-client only sync | asyncio.to_thread wrapper (or aiogoogle for native) | 2024+ | Non-blocking API calls in async frameworks |
| Polling Gmail for new messages | Gmail push notifications via Cloud Pub/Sub | 2015+ (stable) | Real-time notification, must renew every 7 days |
| output_format parameter for structured outputs | output_config.format parameter | Late 2025 | Old parameter deprecated, new `output_config` is the standard |

**Deprecated/outdated:**
- `output_format` parameter in Claude API: Moved to `output_config.format`. Old parameter still works temporarily but will be removed.
- `gmail-api-push@system.gserviceaccount.com` permissions pattern: Still required for Gmail push notifications, but domain-restricted sharing policies may need exceptions configured.

## Open Questions

Things that couldn't be fully resolved:

1. **Google Workspace Setup for Development**
   - What we know: Domain-wide delegation requires a Google Workspace admin to grant the service account access to user mailboxes. The project mentions INF-05 (Google Workspace domain-wide delegation) as complete in Phase 1.
   - What's unclear: Whether the actual GCP service account and domain delegation are configured, or just the code scaffolding.
   - Recommendation: Plan should include a verification step that tests Gmail/Chat API access before building agent logic. If not configured, create mock GSuite services for development.

2. **Gmail Push Notifications vs Polling**
   - What we know: Gmail API supports push notifications via Cloud Pub/Sub (watch API). Requires GCP Pub/Sub setup and periodic renewal every 7 days.
   - What's unclear: Whether Pub/Sub is available in the current GCP setup. STATE.md notes "GCP services not yet configured."
   - Recommendation: For Phase 4, start with polling-based email checking (simpler). Add push notifications as enhancement. The agent can initially be triggered by API calls rather than incoming email events.

3. **Instructor vs Native Claude Structured Outputs via LiteLLM**
   - What we know: Claude now has GA structured outputs. LiteLLM supports passing structured output configs. Instructor adds retry logic and works with LiteLLM.
   - What's unclear: Whether LiteLLM's latest version fully supports Claude's new `output_config.format` parameter, or if it only supports the older approach.
   - Recommendation: Use instructor for Phase 4 (proven, handles edge cases). Can migrate to native structured outputs later if instructor adds overhead.

4. **Google Chat App vs Webhook**
   - What we know: Google Chat API supports both Chat app (with `chat.bot` scope) and webhook-based messaging. Chat apps need to be members of spaces.
   - What's unclear: Which approach is better for the sales agent use case where the agent sends messages to both customers and internal team.
   - Recommendation: Use Chat app with service account for internal team messaging. For external customer messaging, this likely happens via email (Gmail) since external customers may not have Google Chat. The plan should clarify the Chat use case.

## Sources

### Primary (HIGH confidence)
- [Gmail API Sending Guide](https://developers.google.com/gmail/api/guides/sending) - Email format, MIME encoding, threading
- [Google Chat API Create Messages](https://developers.google.com/workspace/chat/create-messages) - Message creation, authentication, thread support
- [Google Chat Service Account Auth](https://developers.google.com/chat/api/guides/auth/service-accounts) - Domain-wide delegation, scopes
- [Gmail Push Notifications](https://developers.google.com/gmail/api/guides/push) - Watch API, Pub/Sub, renewal
- [Claude Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) - JSON schema, Pydantic integration, output_config.format
- [google-api-python-client Thread Safety](https://googleapis.github.io/google-api-python-client/docs/thread_safety.html) - httplib2 not thread-safe, per-thread instances
- Existing codebase: `src/app/agents/base.py`, `src/app/services/llm.py`, `src/knowledge/conversations/`, `src/knowledge/methodology/`, `src/knowledge/rag/`

### Secondary (MEDIUM confidence)
- [Instructor + LiteLLM Integration](https://python.useinstructor.com/integrations/litellm/) - Structured output extraction with validation
- [Instructor Library](https://python.useinstructor.com/) - 3M+ monthly downloads, v1.7+, MIT license
- [aiogoogle](https://pypi.org/project/aiogoogle/) - v5.17.0, async Google API alternative (not recommended for primary use)
- Chris Voss calibrated questions methodology -- well-documented in sales literature

### Tertiary (LOW confidence)
- LangGraph state machine patterns for sales agents -- no specific sales agent examples found in official docs, but the state machine pattern is well-established and already used in Phase 3 RAG pipeline
- Instructor compatibility with Claude's new `output_config.format` via LiteLLM -- needs validation during implementation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official Google API docs verified, existing codebase patterns well-understood, instructor library well-documented
- Architecture: HIGH - Follows established BaseAgent pattern from Phase 2, composes existing Phase 3 services
- GSuite integration: HIGH - Official Google documentation, well-documented Python SDK
- Qualification extraction: MEDIUM - Instructor + LiteLLM combination verified in docs, but specific qualification schema design is application-specific
- Persona adaptation: MEDIUM - Chris Voss methodology is well-documented, but prompt engineering effectiveness requires iteration
- Pitfalls: HIGH - Based on official documentation warnings (thread safety, watch renewal) and common async/sync integration issues

**Research date:** 2026-02-11
**Valid until:** 2026-03-11 (30 days -- Google APIs and core libraries are stable)
