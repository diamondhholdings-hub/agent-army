"""REST API endpoints for Sales Agent operations.

Provides endpoints for sending emails, sending chat messages, processing
customer replies, getting next-action recommendations, retrieving
conversation state, and listing the sales pipeline. All endpoints require
authentication and tenant context.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.app.api.deps import get_current_user, get_tenant
from src.app.core.tenant import TenantContext
from src.app.models.tenant import User

router = APIRouter(prefix="/sales", tags=["sales"])


# ── Request Schemas ──────────────────────────────────────────────────────────


class SendEmailRequest(BaseModel):
    """Request body for sending a sales email."""

    account_id: str
    contact_id: str
    contact_email: str
    contact_name: str = ""
    persona: str = "manager"
    deal_stage: str = "discovery"
    description: str
    thread_id: str | None = None
    in_reply_to: str | None = None


class SendChatRequest(BaseModel):
    """Request body for sending a sales chat message."""

    account_id: str
    contact_id: str
    contact_name: str = ""
    persona: str = "manager"
    deal_stage: str = "discovery"
    description: str
    space_name: str
    thread_key: str | None = None


class ProcessReplyRequest(BaseModel):
    """Request body for processing a customer reply."""

    account_id: str
    contact_id: str
    contact_email: str
    reply_text: str
    channel: str = "email"


class GetRecommendationsRequest(BaseModel):
    """Request body for getting next-action recommendations."""

    account_id: str
    contact_id: str


# ── Response Schemas ─────────────────────────────────────────────────────────


class SendEmailResponse(BaseModel):
    """Response from sending a sales email."""

    status: str
    message_id: str
    thread_id: str
    escalation: dict | None = None


class SendChatResponse(BaseModel):
    """Response from sending a sales chat message."""

    status: str
    message_name: str
    escalation: dict | None = None


class ProcessReplyResponse(BaseModel):
    """Response from processing a customer reply."""

    status: str
    qualification_update: dict
    next_actions: list[dict]
    escalation: dict | None = None


class RecommendationsResponse(BaseModel):
    """Response with next-action recommendations."""

    next_actions: list[dict]


class ConversationStateResponse(BaseModel):
    """Response mirroring ConversationState schema fields."""

    state_id: str
    tenant_id: str
    account_id: str
    contact_id: str
    contact_email: str
    contact_name: str = ""
    deal_stage: str
    persona_type: str
    qualification: dict = Field(default_factory=dict)
    interaction_count: int = 0
    last_interaction: str | None = None
    last_channel: str | None = None
    escalated: bool = False
    escalation_reason: str | None = None
    confidence_score: float = 0.5
    next_actions: list[str] = Field(default_factory=list)
    follow_up_scheduled: str | None = None
    created_at: str | None = None


# ── Dependency: Sales Agent Instance ─────────────────────────────────────────


def _get_sales_agent() -> Any:
    """Retrieve the registered SalesAgent instance from the AgentRegistry.

    Returns:
        SalesAgent instance.

    Raises:
        HTTPException(503): If the Sales Agent is not registered or not initialized.
    """
    from src.app.agents.registry import get_agent_registry

    registry = get_agent_registry()
    registration = registry.get("sales_agent")
    if registration is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sales Agent is not registered. The agent may not have initialized successfully.",
        )

    agent_instance = getattr(registration, "_agent_instance", None)
    if agent_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sales Agent instance is not available. GSuite credentials may not be configured.",
        )

    return agent_instance


def _get_state_repository() -> Any:
    """Retrieve the state repository from the Sales Agent instance.

    Returns:
        ConversationStateRepository instance.

    Raises:
        HTTPException(503): If the repository is not available.
    """
    agent = _get_sales_agent()
    repo = getattr(agent, "_state_repository", None)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation state repository is not available.",
        )
    return repo


# ── Helper: Convert ConversationState to Response ────────────────────────────


def _state_to_response(state: Any) -> ConversationStateResponse:
    """Convert a ConversationState Pydantic model to a ConversationStateResponse."""
    return ConversationStateResponse(
        state_id=state.state_id,
        tenant_id=state.tenant_id,
        account_id=state.account_id,
        contact_id=state.contact_id,
        contact_email=state.contact_email,
        contact_name=state.contact_name,
        deal_stage=state.deal_stage.value,
        persona_type=state.persona_type.value,
        qualification=state.qualification.model_dump(mode="json"),
        interaction_count=state.interaction_count,
        last_interaction=(
            state.last_interaction.isoformat() if state.last_interaction else None
        ),
        last_channel=(
            state.last_channel.value if state.last_channel else None
        ),
        escalated=state.escalated,
        escalation_reason=state.escalation_reason,
        confidence_score=state.confidence_score,
        next_actions=state.next_actions,
        follow_up_scheduled=(
            state.follow_up_scheduled.isoformat()
            if state.follow_up_scheduled
            else None
        ),
        created_at=(
            state.created_at.isoformat() if state.created_at else None
        ),
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/send-email", response_model=SendEmailResponse)
async def send_email(
    body: SendEmailRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> SendEmailResponse:
    """Send a persona-adapted sales email via Gmail.

    Builds a task for the Sales Agent and invokes it. The agent generates
    email content via LLM, sends it via Gmail, updates conversation state,
    and checks escalation triggers.
    """
    agent = _get_sales_agent()

    task = {
        "type": "send_email",
        "account_id": body.account_id,
        "contact_id": body.contact_id,
        "contact_email": body.contact_email,
        "contact_name": body.contact_name,
        "persona_type": body.persona,
        "deal_stage": body.deal_stage,
        "description": body.description,
        "thread_id": body.thread_id,
        "in_reply_to": body.in_reply_to,
    }
    context = {"tenant_id": tenant.tenant_id}

    result = await agent.invoke(task, context)
    return SendEmailResponse(**result)


@router.post("/send-chat", response_model=SendChatResponse)
async def send_chat(
    body: SendChatRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> SendChatResponse:
    """Send a persona-adapted sales chat message via Google Chat.

    Builds a task for the Sales Agent and invokes it. The agent generates
    chat content via LLM, sends it via Google Chat, updates conversation
    state, and checks escalation triggers.
    """
    agent = _get_sales_agent()

    task = {
        "type": "send_chat",
        "account_id": body.account_id,
        "contact_id": body.contact_id,
        "contact_name": body.contact_name,
        "persona_type": body.persona,
        "deal_stage": body.deal_stage,
        "description": body.description,
        "space_name": body.space_name,
        "thread_key": body.thread_key,
    }
    context = {"tenant_id": tenant.tenant_id}

    result = await agent.invoke(task, context)
    return SendChatResponse(**result)


@router.post("/process-reply", response_model=ProcessReplyResponse)
async def process_reply(
    body: ProcessReplyRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> ProcessReplyResponse:
    """Process an incoming customer reply.

    Extracts qualification signals from the reply text, updates conversation
    state, evaluates escalation triggers, and generates next-action
    recommendations.
    """
    agent = _get_sales_agent()

    task = {
        "type": "process_reply",
        "account_id": body.account_id,
        "contact_id": body.contact_id,
        "contact_email": body.contact_email,
        "reply_text": body.reply_text,
        "channel": body.channel,
    }
    context = {"tenant_id": tenant.tenant_id}

    result = await agent.invoke(task, context)
    return ProcessReplyResponse(**result)


@router.post("/recommend-actions", response_model=RecommendationsResponse)
async def recommend_actions(
    body: GetRecommendationsRequest,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> RecommendationsResponse:
    """Get next-action recommendations for a sales conversation.

    Analyzes the current conversation state and generates prioritized
    next-action recommendations using the hybrid rule-based + LLM engine.
    """
    agent = _get_sales_agent()

    task = {
        "type": "recommend_action",
        "account_id": body.account_id,
        "contact_id": body.contact_id,
    }
    context = {"tenant_id": tenant.tenant_id}

    result = await agent.invoke(task, context)
    return RecommendationsResponse(**result)


@router.get(
    "/conversation-state/{account_id}/{contact_id}",
    response_model=ConversationStateResponse,
)
async def get_conversation_state(
    account_id: str,
    contact_id: str,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> ConversationStateResponse:
    """Retrieve conversation state for a specific account/contact.

    Returns the full conversation state including qualification progress,
    interaction history, and escalation status.
    """
    repo = _get_state_repository()

    state = await repo.get_state(tenant.tenant_id, account_id, contact_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conversation state found for account={account_id}, contact={contact_id}",
        )

    return _state_to_response(state)


@router.get("/pipeline", response_model=list[ConversationStateResponse])
async def list_pipeline(
    deal_stage: str | None = Query(
        default=None,
        description="Filter by deal stage (e.g., 'discovery', 'negotiation')",
    ),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_tenant),
) -> list[ConversationStateResponse]:
    """List all conversation states for the tenant's sales pipeline.

    Optionally filter by deal stage. Returns all active conversations
    with their qualification progress and status.
    """
    repo = _get_state_repository()

    states = await repo.list_states_by_tenant(
        tenant_id=tenant.tenant_id,
        deal_stage=deal_stage,
    )

    return [_state_to_response(s) for s in states]
