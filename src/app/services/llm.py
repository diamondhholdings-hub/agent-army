"""LLM provider abstraction via LiteLLM Router.

Provides a tenant-aware LLM service with:
- Claude Sonnet 4 as the primary reasoning model
- GPT-4o as fallback when Claude is unavailable
- Prompt injection detection and sanitization
- Tenant metadata in every LLM call for cost tracking
- Streaming support via async generators
"""

from __future__ import annotations

import re
from typing import AsyncGenerator

import structlog
from litellm import Router

from src.app.config import get_settings
from src.app.core.tenant import get_current_tenant

logger = structlog.get_logger(__name__)

# ── Prompt Injection Detection ────────────────────────────────────────────────

# Patterns that indicate prompt injection attempts
_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "instruction_override",
        re.compile(
            r"ignore\s+(all\s+)?previous\s+instructions|"
            r"disregard\s+(all\s+)?(your\s+)?instructions|"
            r"forget\s+(all\s+)?(your\s+)?instructions|"
            r"override\s+(all\s+)?(your\s+)?instructions",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_exfiltration",
        re.compile(
            r"(reveal|show|display|output|print|repeat)\s+(your\s+)?(system\s+prompt|instructions|prompt)|"
            r"system\s+prompt|"
            r"repeat\s+everything\s+above|"
            r"output\s+your\s+system|"
            r"what\s+are\s+your\s+instructions",
            re.IGNORECASE,
        ),
    ),
    (
        "role_hijacking",
        re.compile(
            r"you\s+are\s+now\s+|"
            r"act\s+as\s+(a\s+|an\s+)?|"
            r"pretend\s+(to\s+be|you\s+are)|"
            r"from\s+now\s+on\s+you\s+are|"
            r"assume\s+the\s+role\s+of",
            re.IGNORECASE,
        ),
    ),
    (
        "control_characters",
        re.compile(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f]{3,}",  # 3+ control chars in sequence
        ),
    ),
]


def detect_prompt_injection(text: str) -> tuple[bool, str | None]:
    """Check text for common prompt injection patterns.

    Args:
        text: The text to analyze.

    Returns:
        Tuple of (is_injection, pattern_name) where pattern_name identifies
        which pattern matched, or None if no injection detected.
    """
    for pattern_name, pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning(
                "prompt_injection_detected",
                pattern=pattern_name,
                text_preview=text[:100],
            )
            return True, pattern_name
    return False, None


def sanitize_messages(messages: list[dict]) -> list[dict]:
    """Sanitize messages for prompt injection before sending to LLM.

    - System messages are NEVER modified (they are trusted).
    - User messages are checked for injection patterns.
    - If injection is detected, the offending content is removed.

    This is a heuristic defense layer. The architectural defense is that
    LLM calls never mix tenant data.
    """
    sanitized = []
    for msg in messages:
        if msg.get("role") == "system":
            # System messages are trusted -- never modify
            sanitized.append(msg)
            continue

        content = msg.get("content", "")
        if not content:
            sanitized.append(msg)
            continue

        is_injection, pattern_name = detect_prompt_injection(content)
        if is_injection:
            # Strip the injection pattern from the content
            cleaned = content
            for _, pattern in _INJECTION_PATTERNS:
                cleaned = pattern.sub("[removed]", cleaned)
            logger.warning(
                "prompt_injection_sanitized",
                role=msg.get("role"),
                pattern=pattern_name,
                original_length=len(content),
                cleaned_length=len(cleaned),
            )
            sanitized.append({**msg, "content": cleaned})
        else:
            sanitized.append(msg)

    return sanitized


# ── LLM Service ──────────────────────────────────────────────────────────────


class LLMService:
    """LLM provider abstraction with LiteLLM Router.

    Configures Claude Sonnet 4 as primary reasoning model with GPT-4o as
    fallback. All calls include tenant metadata for cost tracking.
    """

    def __init__(self) -> None:
        settings = get_settings()

        model_list = []

        # Primary reasoning model: Claude Sonnet 4
        if settings.ANTHROPIC_API_KEY:
            model_list.append({
                "model_name": "reasoning",
                "litellm_params": {
                    "model": "anthropic/claude-sonnet-4-20250514",
                    "api_key": settings.ANTHROPIC_API_KEY,
                },
            })
            model_list.append({
                "model_name": "fast",
                "litellm_params": {
                    "model": "anthropic/claude-haiku-3-20240307",
                    "api_key": settings.ANTHROPIC_API_KEY,
                },
            })

        # Fallback reasoning model: GPT-4o
        if settings.OPENAI_API_KEY:
            model_list.append({
                "model_name": "reasoning",
                "litellm_params": {
                    "model": "openai/gpt-4o",
                    "api_key": settings.OPENAI_API_KEY,
                },
            })
            model_list.append({
                "model_name": "fast",
                "litellm_params": {
                    "model": "openai/gpt-4o-mini",
                    "api_key": settings.OPENAI_API_KEY,
                },
            })

        if not model_list:
            logger.warning("No LLM API keys configured -- LLM service will be unavailable")
            self.router = None
            return

        self.router = Router(
            model_list=model_list,
            num_retries=settings.LLM_MAX_RETRIES,
            timeout=settings.LLM_TIMEOUT,
            allowed_fails=3,
            cooldown_time=30,
        )

    async def completion(
        self,
        messages: list[dict],
        model: str = "reasoning",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict | None = None,
    ) -> dict:
        """Execute a completion call through the LiteLLM Router.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            model: Model group name ("reasoning" or "fast").
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature (0-2).
            metadata: Additional metadata to include in the call.

        Returns:
            Dict with content, model, usage, and tenant_id.

        Raises:
            RuntimeError: If no LLM API keys are configured.
        """
        if not self.router:
            raise RuntimeError("No LLM API keys configured")

        # Get tenant context for cost tracking
        try:
            tenant = get_current_tenant()
            tenant_metadata = {
                "tenant_id": tenant.tenant_id,
                "tenant_slug": tenant.tenant_slug,
            }
        except RuntimeError:
            tenant_metadata = {}

        # Merge caller metadata with tenant metadata
        call_metadata = {**tenant_metadata, **(metadata or {})}

        # Sanitize messages for prompt injection
        safe_messages = sanitize_messages(messages)

        # Call LiteLLM Router
        response = await self.router.acompletion(
            model=model,
            messages=safe_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            metadata=call_metadata,
        )

        # Extract usage info
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return {
            "content": response.choices[0].message.content,
            "model": response.model,
            "usage": usage,
            "tenant_id": tenant_metadata.get("tenant_id", ""),
        }

    async def streaming_completion(
        self,
        messages: list[dict],
        model: str = "reasoning",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict | None = None,
    ) -> AsyncGenerator[str, None]:
        """Execute a streaming completion call.

        Yields content chunks as strings for SSE streaming.
        """
        if not self.router:
            raise RuntimeError("No LLM API keys configured")

        # Get tenant context
        try:
            tenant = get_current_tenant()
            tenant_metadata = {
                "tenant_id": tenant.tenant_id,
                "tenant_slug": tenant.tenant_slug,
            }
        except RuntimeError:
            tenant_metadata = {}

        call_metadata = {**tenant_metadata, **(metadata or {})}

        # Sanitize messages
        safe_messages = sanitize_messages(messages)

        response = await self.router.acompletion(
            model=model,
            messages=safe_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            metadata=call_metadata,
            stream=True,
        )

        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


# ── Singleton ─────────────────────────────────────────────────────────────────

_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Get or create the LLM service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
