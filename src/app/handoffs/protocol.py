"""Handoff validation protocol chaining structural and semantic validation.

HandoffProtocol is the primary entry point for validating handoff payloads.
It chains structural validation (Pydantic) with optional semantic validation
(LLM-based) based on configurable strictness per handoff type.

Validation flow:
1. Structural validation (always): re-validate payload via Pydantic
2. Strictness check: determine if semantic validation is needed
3. Semantic validation (STRICT only): LLM checks for hallucinated claims
4. Result: HandoffResult with all collected issues

A handoff is valid only if structural passes AND (if STRICT, semantic also passes).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from src.app.handoffs.validators import (
    HandoffPayload,
    HandoffResult,
    StrictnessConfig,
    ValidationStrictness,
)

if TYPE_CHECKING:
    from src.app.handoffs.semantic import SemanticValidator

logger = structlog.get_logger(__name__)


class HandoffRejectedError(Exception):
    """Raised when a handoff fails validation.

    Carries the full HandoffResult with specific rejection reasons
    and the payload that was rejected, enabling debugging and logging.

    Attributes:
        result: The HandoffResult containing validation details.
        payload: The HandoffPayload that was rejected.
    """

    def __init__(self, result: HandoffResult, payload: HandoffPayload) -> None:
        self.result = result
        self.payload = payload
        super().__init__(str(self))

    def __str__(self) -> str:
        all_issues = self.result.structural_issues + self.result.semantic_issues
        issues_str = "; ".join(all_issues) if all_issues else "unknown reason"
        return (
            f"Handoff rejected [{self.result.strictness.value}]: "
            f"handoff_id={self.payload.handoff_id}, "
            f"source={self.payload.source_agent_id} -> target={self.payload.target_agent_id}, "
            f"type={self.payload.handoff_type}, "
            f"reasons=[{issues_str}]"
        )


class HandoffProtocol:
    """Two-layer handoff validation protocol.

    Chains structural validation (Pydantic) with optional LLM semantic
    validation based on configurable strictness per handoff type.

    Args:
        strictness_config: Maps handoff types to validation strictness levels.
        semantic_validator: Optional SemanticValidator for STRICT handoffs.
            If None, STRICT handoffs skip semantic validation with a warning.
    """

    def __init__(
        self,
        strictness_config: StrictnessConfig,
        semantic_validator: SemanticValidator | None = None,
    ) -> None:
        self._config = strictness_config
        self._semantic = semantic_validator

    async def validate(
        self,
        payload: HandoffPayload,
        available_context: dict | None = None,
    ) -> HandoffResult:
        """Validate a handoff payload through structural and optional semantic checks.

        Args:
            payload: The handoff payload to validate.
            available_context: Optional context dict for semantic validation.

        Returns:
            HandoffResult with validation outcome and any issues found.
        """
        structural_issues: list[str] = []
        semantic_issues: list[str] = []
        validator_model: str | None = None

        # Step 1: Structural validation -- re-validate the payload
        try:
            HandoffPayload.model_validate(payload.model_dump())
        except ValidationError as exc:
            for error in exc.errors():
                loc = ".".join(str(part) for part in error["loc"])
                structural_issues.append(f"{loc}: {error['msg']}")

        # Step 2: Determine strictness
        strictness = self._config.get_strictness(payload.handoff_type)

        # Step 3: Semantic validation (STRICT only)
        if strictness == ValidationStrictness.STRICT and self._semantic is not None:
            is_valid, issues = await self._semantic.validate(payload, available_context)
            if not is_valid:
                semantic_issues.extend(issues)
            # Track which model did the check even if valid
            validator_model = "fast"
        elif strictness == ValidationStrictness.STRICT and self._semantic is None:
            logger.warning(
                "semantic_validator_unavailable",
                handoff_id=payload.handoff_id,
                handoff_type=payload.handoff_type,
                strictness=strictness.value,
            )

        # Step 4: Determine overall validity
        is_valid = len(structural_issues) == 0 and len(semantic_issues) == 0

        result = HandoffResult(
            valid=is_valid,
            strictness=strictness,
            structural_issues=structural_issues,
            semantic_issues=semantic_issues,
            validator_model=validator_model,
        )

        logger.info(
            "handoff_validated",
            handoff_id=payload.handoff_id,
            valid=result.valid,
            strictness=result.strictness.value,
            structural_issue_count=len(structural_issues),
            semantic_issue_count=len(semantic_issues),
        )

        return result

    async def validate_or_reject(
        self,
        payload: HandoffPayload,
        context: dict | None = None,
    ) -> HandoffPayload:
        """Validate a handoff payload, raising on failure.

        Convenience method that calls validate() and raises HandoffRejectedError
        if the handoff is invalid. Returns the payload unchanged on success.

        Args:
            payload: The handoff payload to validate.
            context: Optional context dict for semantic validation.

        Returns:
            The validated HandoffPayload (pass-through on success).

        Raises:
            HandoffRejectedError: If validation fails, with full result details.
        """
        result = await self.validate(payload, context)
        if not result.valid:
            logger.warning(
                "handoff_rejected",
                handoff_id=payload.handoff_id,
                source=payload.source_agent_id,
                target=payload.target_agent_id,
                handoff_type=payload.handoff_type,
                structural_issues=result.structural_issues,
                semantic_issues=result.semantic_issues,
            )
            raise HandoffRejectedError(result=result, payload=payload)
        return payload
