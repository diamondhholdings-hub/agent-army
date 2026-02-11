"""Handoff validation protocol for inter-agent communication.

Provides two-layer validation to prevent cascading hallucination between agents:
1. Structural validation (Pydantic) -- catches missing fields, type errors, attribution issues
2. Semantic validation (LLM-based) -- detects hallucinated claims not grounded in context

Configurable strictness per handoff type:
- STRICT: structural + semantic validation (deal data, customer info, research results)
- LENIENT: structural only (status updates, notifications)

Usage:
    from src.app.handoffs import HandoffProtocol, HandoffPayload, SemanticValidator

    protocol = HandoffProtocol(StrictnessConfig(), SemanticValidator(llm_service))
    result = await protocol.validate(payload, available_context)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Lazy imports to avoid circular dependencies during incremental development


def __getattr__(name: str):  # noqa: N807
    if name in ("HandoffPayload", "ValidationStrictness", "HandoffResult", "StrictnessConfig"):
        from src.app.handoffs.validators import (
            HandoffPayload,
            HandoffResult,
            StrictnessConfig,
            ValidationStrictness,
        )

        _map = {
            "HandoffPayload": HandoffPayload,
            "ValidationStrictness": ValidationStrictness,
            "HandoffResult": HandoffResult,
            "StrictnessConfig": StrictnessConfig,
        }
        return _map[name]

    if name == "SemanticValidator":
        from src.app.handoffs.semantic import SemanticValidator

        return SemanticValidator

    if name in ("HandoffProtocol", "HandoffRejectedError"):
        from src.app.handoffs.protocol import HandoffProtocol, HandoffRejectedError

        _map = {
            "HandoffProtocol": HandoffProtocol,
            "HandoffRejectedError": HandoffRejectedError,
        }
        return _map[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "HandoffPayload",
    "HandoffProtocol",
    "HandoffRejectedError",
    "HandoffResult",
    "SemanticValidator",
    "StrictnessConfig",
    "ValidationStrictness",
]
