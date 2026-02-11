"""Prometheus metrics, Sentry integration, and LLM call tracking.

Provides:
- MetricsMiddleware: ASGI middleware for HTTP request metrics
- init_sentry(): Initialize Sentry with tenant-aware before_send callback
- track_llm_call(): Context manager for LLM call metrics
- get_metrics_endpoint(): FastAPI route handler for /metrics
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from prometheus_client import (
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# ── HTTP Metrics ─────────────────────────────────────────────────────────────

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code", "tenant_id"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint", "tenant_id"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ── LLM Metrics ──────────────────────────────────────────────────────────────

llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM API requests",
    ["model", "tenant_id", "status"],
)

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "LLM API request duration in seconds",
    ["model", "tenant_id"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

llm_tokens_used_total = Counter(
    "llm_tokens_used_total",
    "Total LLM tokens consumed",
    ["model", "tenant_id", "token_type"],
)

# ── Platform Metrics ─────────────────────────────────────────────────────────

active_tenants = Gauge(
    "active_tenants",
    "Number of active tenants",
)

db_pool_size = Gauge(
    "db_pool_size",
    "Current database connection pool size",
)


# ── Metrics Middleware ───────────────────────────────────────────────────────


class MetricsMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that records Prometheus metrics for every HTTP request.

    Extracts tenant_id from the request context (if available) and records
    request count and duration per method/endpoint/tenant.
    Skips the /metrics endpoint itself to avoid self-referential counting.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip metrics for the /metrics endpoint itself
        if request.url.path == "/metrics":
            return await call_next(request)

        # Extract tenant_id from context (if available)
        tenant_id = "unknown"
        try:
            from src.app.core.tenant import get_current_tenant

            ctx = get_current_tenant()
            tenant_id = ctx.tenant_id
        except (RuntimeError, LookupError):
            pass

        # Normalize endpoint for cardinality control:
        # Use the route path pattern if available, otherwise the raw path
        endpoint = request.url.path

        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time

        http_requests_total.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=str(response.status_code),
            tenant_id=tenant_id,
        ).inc()

        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=endpoint,
            tenant_id=tenant_id,
        ).observe(duration)

        return response


# ── LLM Metrics Helper ──────────────────────────────────────────────────────


@asynccontextmanager
async def track_llm_call(
    model: str,
    tenant_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """Context manager that tracks LLM call metrics.

    Usage:
        async with track_llm_call("gpt-4", tenant_id) as tracker:
            result = await call_llm(...)
            tracker["prompt_tokens"] = result.usage.prompt_tokens
            tracker["completion_tokens"] = result.usage.completion_tokens

    Automatically records:
    - Duration in histogram
    - Request count (success/error)
    - Token usage (if set in tracker dict)
    """
    tracker: dict[str, Any] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    start_time = time.perf_counter()
    status = "success"

    try:
        yield tracker
    except Exception:
        status = "error"
        raise
    finally:
        duration = time.perf_counter() - start_time

        llm_requests_total.labels(
            model=model,
            tenant_id=tenant_id,
            status=status,
        ).inc()

        llm_request_duration_seconds.labels(
            model=model,
            tenant_id=tenant_id,
        ).observe(duration)

        # Record token usage if provided
        if tracker.get("prompt_tokens"):
            llm_tokens_used_total.labels(
                model=model,
                tenant_id=tenant_id,
                token_type="prompt",
            ).inc(tracker["prompt_tokens"])

        if tracker.get("completion_tokens"):
            llm_tokens_used_total.labels(
                model=model,
                tenant_id=tenant_id,
                token_type="completion",
            ).inc(tracker["completion_tokens"])


# ── Sentry Integration ───────────────────────────────────────────────────────


def init_sentry(dsn: str, environment: str) -> None:
    """Initialize Sentry SDK with tenant-aware event tagging.

    Args:
        dsn: Sentry DSN string.
        environment: Deployment environment (development, staging, production).
    """
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        import logging

        logging.getLogger(__name__).warning("sentry-sdk not installed, skipping Sentry init")
        return

    # Set sample rate based on environment
    traces_sample_rate = 0.1 if environment == "production" else 1.0

    def before_send(event: dict, hint: dict) -> dict:
        """Add tenant and user context to Sentry events."""
        try:
            from src.app.core.tenant import get_current_tenant

            ctx = get_current_tenant()
            if "tags" not in event:
                event["tags"] = {}
            event["tags"]["tenant_id"] = ctx.tenant_id
            event["tags"]["tenant_slug"] = ctx.tenant_slug
        except (RuntimeError, LookupError):
            pass
        return event

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
        ],
        before_send=before_send,
    )


# ── Metrics Endpoint ─────────────────────────────────────────────────────────


def get_metrics_response() -> Response:
    """Generate Prometheus exposition format response."""
    from starlette.responses import Response

    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
