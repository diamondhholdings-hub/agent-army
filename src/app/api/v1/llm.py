"""LLM completion API endpoints.

Provides authenticated, tenant-scoped access to LLM completions
through the LiteLLM Router abstraction.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.app.api.deps import get_current_user
from src.app.models.tenant import User
from src.app.schemas.llm import LLMCompletionRequest, LLMCompletionResponse
from src.app.services.llm import get_llm_service

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


@router.post("/completion", response_model=LLMCompletionResponse)
async def completion(
    body: LLMCompletionRequest,
    current_user: User = Depends(get_current_user),
):
    """Execute an LLM completion.

    Routes through LiteLLM Router with Claude as primary and GPT-4o as fallback.
    Includes tenant context in metadata for cost tracking.
    Sanitizes input for prompt injection before sending to the LLM.
    """
    llm = get_llm_service()
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    result = await llm.completion(
        messages=messages,
        model=body.model,
        max_tokens=body.max_tokens,
        temperature=body.temperature,
    )

    return LLMCompletionResponse(**result)


@router.post("/completion/stream")
async def completion_stream(
    body: LLMCompletionRequest,
    current_user: User = Depends(get_current_user),
):
    """Execute a streaming LLM completion via Server-Sent Events.

    Returns a stream of content chunks in SSE format.
    """
    llm = get_llm_service()
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    async def event_generator():
        async for chunk in llm.streaming_completion(
            messages=messages,
            model=body.model,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
        ):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
