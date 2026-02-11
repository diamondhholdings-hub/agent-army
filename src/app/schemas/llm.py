"""Pydantic schemas for LLM API endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """A single message in a conversation."""

    role: Literal["system", "user", "assistant"] = Field(
        ..., description="Message role"
    )
    content: str = Field(..., description="Message content")


class LLMCompletionRequest(BaseModel):
    """Request schema for LLM completion."""

    messages: list[LLMMessage] = Field(
        ..., min_length=1, description="Conversation messages"
    )
    model: str = Field(
        default="reasoning",
        description="Model group: 'reasoning' (Claude/GPT-4o) or 'fast' (Haiku/GPT-4o-mini)",
    )
    max_tokens: int = Field(default=4096, ge=1, le=16384, description="Maximum tokens in response")
    temperature: float = Field(default=0.7, ge=0, le=2, description="Sampling temperature")


class LLMCompletionResponse(BaseModel):
    """Response schema for LLM completion."""

    content: str = Field(..., description="Generated content")
    model: str = Field(..., description="Model that generated the response")
    usage: dict = Field(default_factory=dict, description="Token usage statistics")
    tenant_id: str = Field(default="", description="Tenant ID for cost tracking")
