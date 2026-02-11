"""Observability package for Langfuse tracing and cost tracking.

Provides:
- AgentTracer: Wraps Langfuse tracing with agent-scoped metadata propagation
- CostTracker: Per-tenant per-agent cost aggregation from Langfuse
- init_langfuse: Initialize Langfuse callbacks on LiteLLM

All components degrade gracefully when Langfuse is not configured.
"""

from __future__ import annotations


def __getattr__(name: str):
    if name == "AgentTracer":
        from src.app.observability.tracer import AgentTracer
        return AgentTracer
    if name == "init_langfuse":
        from src.app.observability.tracer import init_langfuse
        return init_langfuse
    if name == "CostTracker":
        from src.app.observability.cost import CostTracker
        return CostTracker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AgentTracer",
    "CostTracker",
    "init_langfuse",
]
