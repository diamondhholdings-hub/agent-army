"""LLM-based semantic validation for handoff payloads.

Detects hallucinated claims, ungrounded data, and logical inconsistencies
by asking a fast LLM model to verify payload data against available context.
This is the second layer of defense (after structural validation) in the
handoff validation protocol.

Key design decisions:
- Uses model="fast" (Claude Haiku) for speed -- semantic checks must not bottleneck handoffs
- Temperature=0.0 for deterministic validation results
- Fail-open on LLM errors to prevent blocking all handoffs when LLM is unavailable
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.app.handoffs.validators import HandoffPayload
    from src.app.services.llm import LLMService

logger = structlog.get_logger(__name__)

# ── Validation Prompt ───────────────────────────────────────────────────────

_VALIDATION_SYSTEM_PROMPT = """You are a data validation assistant. Your job is to check whether
handoff data between AI agents is grounded, consistent, and free of fabrication.

You will receive:
1. The handoff data being passed between agents
2. Available context that the data should be grounded in (if provided)

Check for:
- Claims in the data that are NOT supported by the available context
- Fabricated or hallucinated data points (specific numbers, dates, names without source)
- Internal contradictions within the data
- Data that appears plausible but has no grounding in the provided context

Respond with ONLY a JSON object (no markdown, no explanation):
{"valid": true, "issues": []}
OR
{"valid": false, "issues": ["specific issue 1", "specific issue 2"]}

Be strict: if data contains specific claims (dollar amounts, dates, company names)
that cannot be verified from the context, flag them."""

_VALIDATION_USER_TEMPLATE = """Validate this handoff data:

## Handoff Data
{handoff_data}

## Available Context
{context_data}

## Validation Task
Check whether the handoff data is grounded in the available context.
Flag any claims that appear fabricated, unverifiable, or contradictory.
Respond with ONLY the JSON validation result."""


class SemanticValidator:
    """LLM-based semantic validation for handoff payloads.

    Uses a fast LLM model to verify that handoff data is grounded in
    available context, free of hallucinated claims, and logically consistent.

    The validator is fail-open: if the LLM is unavailable or returns an
    unparseable response, validation passes with a warning. This prevents
    LLM outages from blocking all agent handoffs.

    Args:
        llm_service: The LLMService instance for making LLM calls.
    """

    def __init__(self, llm_service: LLMService) -> None:
        self._llm = llm_service

    async def validate(
        self,
        payload: HandoffPayload,
        available_context: dict | None = None,
    ) -> tuple[bool, list[str]]:
        """Validate handoff payload semantically using LLM.

        Constructs a validation prompt and asks the LLM to check:
        1. Are all claims in the data supported by available context?
        2. Are there fabricated/hallucinated data points?
        3. Is the data logically consistent?

        Args:
            payload: The handoff payload to validate.
            available_context: Optional context dict the data should be grounded in.
                If None, the LLM checks for internal consistency and obvious fabrication.

        Returns:
            Tuple of (is_valid, issues_list). On LLM failure, returns
            (True, ["semantic_validation_unavailable"]) to fail open.
        """
        context_str = (
            json.dumps(available_context, indent=2, default=str)
            if available_context
            else "No external context provided. Check for internal consistency and obvious fabrication only."
        )

        user_message = _VALIDATION_USER_TEMPLATE.format(
            handoff_data=json.dumps(payload.data, indent=2, default=str),
            context_data=context_str,
        )

        messages = [
            {"role": "system", "content": _VALIDATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        try:
            response = await self._llm.completion(
                messages=messages,
                model="fast",
                temperature=0.0,
                max_tokens=1024,
                metadata={"purpose": "handoff_semantic_validation", "handoff_id": payload.handoff_id},
            )

            content = response.get("content", "")
            result = json.loads(content)
            is_valid = result.get("valid", True)
            issues = result.get("issues", [])

            logger.info(
                "semantic_validation_complete",
                handoff_id=payload.handoff_id,
                valid=is_valid,
                issue_count=len(issues),
                model=response.get("model", "unknown"),
            )

            return is_valid, issues

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            # LLM returned unparseable response -- fail open with warning
            logger.warning(
                "semantic_validation_parse_error",
                handoff_id=payload.handoff_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return True, ["semantic_validation_unavailable"]

        except (RuntimeError, TimeoutError, Exception) as exc:
            # LLM unavailable -- fail open to prevent blocking all handoffs
            logger.warning(
                "semantic_validation_llm_error",
                handoff_id=payload.handoff_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return True, ["semantic_validation_unavailable"]
