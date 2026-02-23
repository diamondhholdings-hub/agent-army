"""Structural validation for inter-agent handoff payloads.

Provides Pydantic-based validation ensuring handoff payloads have correct
structure, source attribution, call chain integrity, and type safety.
Validation strictness is configurable per handoff type via StrictnessConfig.

Key models:
- HandoffPayload: The data envelope passed between agents at handoff points
- HandoffResult: Validation outcome with structural and semantic issue lists
- ValidationStrictness: STRICT (structural + semantic) or LENIENT (structural only)
- StrictnessConfig: Maps handoff types to validation strictness levels
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field, model_validator

logger = structlog.get_logger(__name__)


# ── Strictness Configuration ────────────────────────────────────────────────


class ValidationStrictness(str, Enum):
    """Validation depth applied to a handoff.

    STRICT: Structural validation + LLM semantic validation.
        Used for critical handoffs (deal data, customer info, research results)
        where hallucinated data could cascade to downstream agents.

    LENIENT: Structural validation only.
        Used for routine handoffs (status updates, notifications) where
        semantic verification is unnecessary overhead.
    """

    STRICT = "strict"
    LENIENT = "lenient"


class StrictnessConfig:
    """Maps handoff types to validation strictness levels.

    Default rules enforce STRICT validation for data-carrying handoffs
    and LENIENT for informational ones. Unknown handoff types default
    to STRICT as a fail-safe -- better to over-validate than to let
    hallucinated data pass through.

    Usage:
        config = StrictnessConfig()
        config.get_strictness("deal_data")       # -> STRICT
        config.get_strictness("status_update")    # -> LENIENT
        config.get_strictness("unknown_type")     # -> STRICT (fail-safe)
    """

    def __init__(self) -> None:
        self._rules: dict[str, ValidationStrictness] = {
            "deal_data": ValidationStrictness.STRICT,
            "customer_info": ValidationStrictness.STRICT,
            "research_result": ValidationStrictness.STRICT,
            "status_update": ValidationStrictness.LENIENT,
            "notification": ValidationStrictness.LENIENT,
            "technical_question": ValidationStrictness.STRICT,
            "technical_answer": ValidationStrictness.STRICT,
        }

    def get_strictness(self, handoff_type: str) -> ValidationStrictness:
        """Return the strictness level for a handoff type.

        Args:
            handoff_type: The type of handoff (e.g., "deal_data", "status_update").

        Returns:
            ValidationStrictness for this type. Defaults to STRICT for unknown types.
        """
        return self._rules.get(handoff_type, ValidationStrictness.STRICT)

    def register_rule(self, handoff_type: str, strictness: ValidationStrictness) -> None:
        """Register or override a strictness rule for a handoff type.

        Args:
            handoff_type: The handoff type to configure.
            strictness: The validation strictness to apply.
        """
        self._rules[handoff_type] = strictness
        logger.info(
            "strictness_rule_registered",
            handoff_type=handoff_type,
            strictness=strictness.value,
        )


# ── Handoff Result ──────────────────────────────────────────────────────────


class HandoffResult(BaseModel):
    """Outcome of handoff validation.

    Contains both structural and semantic issue lists so rejected handoffs
    include specific, debuggable rejection reasons.

    Attributes:
        valid: Whether the handoff passed all applicable validation checks.
        strictness: Which validation strictness was applied.
        structural_issues: List of structural validation failures (field errors,
            missing attribution, type mismatches).
        semantic_issues: List of semantic validation failures (hallucinated claims,
            ungrounded data, logical inconsistencies).
        validated_at: UTC timestamp of when validation occurred.
        validator_model: Which LLM model performed semantic validation, if any.
    """

    valid: bool
    strictness: ValidationStrictness
    structural_issues: list[str] = Field(default_factory=list)
    semantic_issues: list[str] = Field(default_factory=list)
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    validator_model: str | None = None


# ── Handoff Payload ─────────────────────────────────────────────────────────


class HandoffPayload(BaseModel):
    """Data envelope passed between agents at handoff points.

    Every handoff carries source attribution (which agent produced the data
    and the full call chain), tenant isolation context, and configurable
    confidence scoring. The payload structure is validated by Pydantic on
    construction, and additional semantic validation can be applied via
    HandoffProtocol.

    Attributes:
        handoff_id: Unique identifier for this handoff (auto-generated UUID4).
        source_agent_id: Agent that produced this handoff data (must be in call_chain).
        target_agent_id: Agent that will receive this handoff data (must NOT be in call_chain).
        call_chain: Ordered list of agents involved up to this point (min 1 entry).
        tenant_id: Tenant context for data isolation.
        handoff_type: Classification of the handoff for strictness routing
            (e.g., "deal_data", "status_update").
        data: The actual payload being handed off.
        context_refs: References to shared context entries for semantic validation.
        confidence: Source agent's confidence in the data (0.0 to 1.0).
        timestamp: UTC creation time.
    """

    handoff_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_agent_id: str = Field(min_length=1)
    target_agent_id: str = Field(min_length=1)
    call_chain: list[str] = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    handoff_type: str
    data: dict[str, Any]
    context_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _validate_attribution(self) -> HandoffPayload:
        """Ensure source attribution and call chain integrity.

        Rules:
        1. source_agent_id must appear in call_chain (it produced the data)
        2. target_agent_id must NOT appear in call_chain (it hasn't processed yet)
        3. Low confidence (< 0.5) is logged as a warning
        """
        if self.source_agent_id not in self.call_chain:
            msg = (
                f"source_agent_id '{self.source_agent_id}' must appear in "
                f"call_chain {self.call_chain}"
            )
            raise ValueError(msg)

        if self.target_agent_id in self.call_chain:
            msg = (
                f"target_agent_id '{self.target_agent_id}' must NOT appear in "
                f"call_chain {self.call_chain} (target hasn't processed data yet)"
            )
            raise ValueError(msg)

        if self.confidence < 0.5:
            logger.warning(
                "low_confidence_handoff",
                handoff_id=self.handoff_id,
                source_agent_id=self.source_agent_id,
                target_agent_id=self.target_agent_id,
                confidence=self.confidence,
                handoff_type=self.handoff_type,
            )

        return self
