"""Tenant resolution middleware with JWT and header-based modes.

Resolves tenant context from:
1. JWT claims in Authorization header (preferred for user requests)
2. X-Tenant-ID header (fallback for service-to-service / API key auth)
3. API key in X-API-Key header (resolves tenant from key lookup)

After resolution, sets TenantContext in contextvars for the request scope.
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, Response
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.app.config import get_settings
from src.app.core.tenant import (
    SKIP_TENANT_PATHS,
    TenantContext,
    _tenant_context,
    set_tenant_context,
)

logger = logging.getLogger(__name__)


class TenantAuthMiddleware(BaseHTTPMiddleware):
    """Middleware that resolves tenant from JWT claims or X-Tenant-ID header.

    Supports two modes:
    1. JWT mode: Extract tenant_id and tenant_slug from JWT claims.
    2. Header mode: Use X-Tenant-ID header for service-to-service / API key auth.

    Paths in SKIP_TENANT_PATHS are excluded from tenant resolution.
    """

    def __init__(self, app, redis_client: aioredis.Redis | None = None):
        super().__init__(app)
        self._redis = redis_client

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip tenant resolution for excluded paths
        path = request.url.path
        if any(path.startswith(skip) for skip in SKIP_TENANT_PATHS):
            return await call_next(request)

        # Try to resolve tenant from JWT first, then from header
        tenant_ctx = await self._resolve_from_jwt(request)

        if not tenant_ctx:
            tenant_ctx = await self._resolve_from_api_key(request)

        if not tenant_ctx:
            tenant_ctx = await self._resolve_from_header(request)

        if not tenant_ctx:
            raise HTTPException(
                status_code=400,
                detail="Missing tenant context. Provide Authorization header with JWT, X-API-Key, or X-Tenant-ID header.",
            )

        # Set context and process request
        token = set_tenant_context(tenant_ctx)
        try:
            response = await call_next(request)
            return response
        finally:
            _tenant_context.reset(token)

    async def _resolve_from_jwt(self, request: Request) -> TenantContext | None:
        """Extract tenant context from JWT claims in Authorization header."""
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token_str = auth_header[7:]  # Strip "Bearer "
        settings = get_settings()

        try:
            payload = jwt.decode(
                token_str,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError:
            return None

        tenant_id = payload.get("tenant_id")
        tenant_slug = payload.get("tenant_slug")

        if not tenant_id or not tenant_slug:
            return None

        schema_name = f"tenant_{tenant_slug.replace('-', '_')}"

        # Verify tenant exists and is active
        if not await self._verify_tenant_active(tenant_id):
            return None

        return TenantContext(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            schema_name=schema_name,
        )

    async def _resolve_from_api_key(self, request: Request) -> TenantContext | None:
        """Resolve tenant from X-API-Key header."""
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return None

        from src.app.core.security import validate_api_key

        try:
            result = await validate_api_key(api_key)
        except Exception as e:
            logger.warning("API key validation error: %s", e)
            return None

        if not result:
            return None

        schema_name = f"tenant_{result['tenant_slug'].replace('-', '_')}"
        return TenantContext(
            tenant_id=result["tenant_id"],
            tenant_slug=result["tenant_slug"],
            schema_name=schema_name,
        )

    async def _resolve_from_header(self, request: Request) -> TenantContext | None:
        """Resolve tenant from X-Tenant-ID header (fallback for login, etc.)."""
        tenant_id = request.headers.get("X-Tenant-ID")
        if not tenant_id:
            return None

        return await self._resolve_tenant_by_id(tenant_id)

    async def _verify_tenant_active(self, tenant_id: str) -> bool:
        """Check if tenant exists and is active (uses cache)."""
        # Try Redis cache
        if self._redis:
            try:
                cached = await self._redis.get(f"tenant:lookup:{tenant_id}")
                if cached:
                    return True
            except Exception:
                pass

        # Database check
        from sqlalchemy import text

        from src.app.core.database import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM shared.tenants WHERE id::text = :tid AND is_active = true"),
                {"tid": tenant_id},
            )
            return result.first() is not None

    async def _resolve_tenant_by_id(self, tenant_id: str) -> TenantContext | None:
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

        # Fall back to database lookup
        from sqlalchemy import text

        from src.app.core.database import get_engine

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
