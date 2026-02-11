"""Tenant context propagation via Python contextvars.

This module is the foundation of multi-tenant isolation. The TenantContext
is set by middleware at the start of each request and is accessible anywhere
in the call stack via get_current_tenant(). Every database query, Redis
operation, and LLM call uses this context to scope operations to the
correct tenant.
"""

from __future__ import annotations

import contextvars
import json
import logging
from dataclasses import dataclass

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

# ── Tenant Context ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TenantContext:
    """Immutable tenant context for the current request."""

    tenant_id: str
    tenant_slug: str
    schema_name: str  # e.g., "tenant_skyvera"


_tenant_context: contextvars.ContextVar[TenantContext] = contextvars.ContextVar("tenant_context")


def get_current_tenant() -> TenantContext:
    """Get the tenant context for the current request.

    Raises RuntimeError if no tenant context has been set (i.e., the call
    is not within a tenant-scoped request).
    """
    try:
        return _tenant_context.get()
    except LookupError:
        raise RuntimeError("No tenant context set -- request is not tenant-scoped")


def set_tenant_context(ctx: TenantContext) -> contextvars.Token[TenantContext]:
    """Set the tenant context for the current request. Returns a token for reset."""
    return _tenant_context.set(ctx)


# ── Paths that skip tenant resolution ───────────────────────────────────────

SKIP_TENANT_PATHS = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/v1/tenants",
)


# ── Tenant Middleware ───────────────────────────────────────────────────────


class TenantMiddleware(BaseHTTPMiddleware):
    """Middleware that resolves tenant from X-Tenant-ID header and sets context.

    Paths in SKIP_TENANT_PATHS are excluded from tenant resolution (health
    checks, docs, tenant provisioning endpoints).
    """

    def __init__(self, app, redis_client: aioredis.Redis | None = None):
        super().__init__(app)
        self._redis = redis_client

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip tenant resolution for excluded paths
        path = request.url.path
        if any(path.startswith(skip) for skip in SKIP_TENANT_PATHS):
            return await call_next(request)

        # Extract tenant ID from header
        tenant_id = request.headers.get("X-Tenant-ID")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing X-Tenant-ID header")

        # Resolve tenant (with Redis cache)
        tenant_ctx = await self._resolve_tenant(tenant_id)
        if not tenant_ctx:
            raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")

        # Set context and process request
        token = set_tenant_context(tenant_ctx)
        try:
            response = await call_next(request)
            return response
        finally:
            _tenant_context.reset(token)

    async def _resolve_tenant(self, tenant_id: str) -> TenantContext | None:
        """Resolve tenant by ID, using Redis cache when available."""
        # Try Redis cache first
        if self._redis:
            try:
                cached = await self._redis.get(f"tenant:lookup:{tenant_id}")
                if cached:
                    data = json.loads(cached)
                    return TenantContext(
                        tenant_id=data["tenant_id"],
                        tenant_slug=data["tenant_slug"],
                        schema_name=data["schema_name"],
                    )
            except Exception:
                logger.warning("Redis cache lookup failed for tenant %s", tenant_id)

        # Fall back to database lookup (imported here to avoid circular imports)
        from src.app.core.database import get_engine

        from sqlalchemy import text

        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT id, slug, schema_name FROM shared.tenants WHERE id::text = :tid AND is_active = true"),
                {"tid": tenant_id},
            )
            row = result.first()
            if not row:
                return None

            ctx = TenantContext(
                tenant_id=str(row.id),
                tenant_slug=row.slug,
                schema_name=row.schema_name,
            )

            # Cache in Redis for 5 minutes
            if self._redis:
                try:
                    await self._redis.set(
                        f"tenant:lookup:{tenant_id}",
                        json.dumps({"tenant_id": ctx.tenant_id, "tenant_slug": ctx.tenant_slug, "schema_name": ctx.schema_name}),
                        ex=300,
                    )
                except Exception:
                    logger.warning("Redis cache set failed for tenant %s", tenant_id)

            return ctx
