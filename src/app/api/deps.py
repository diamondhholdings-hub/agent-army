"""FastAPI dependency injection for tenant-scoped resources.

These dependencies are used in endpoint function signatures to inject
the correct tenant context, database session, and Redis client.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.database import get_shared_session, get_tenant_session
from src.app.core.redis import TenantRedis, get_tenant_redis
from src.app.core.tenant import TenantContext, get_current_tenant


async def get_tenant() -> TenantContext:
    """Get the current tenant context (set by TenantMiddleware)."""
    return get_current_tenant()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get a tenant-scoped database session."""
    async for session in get_tenant_session():
        yield session


async def get_shared_db() -> AsyncGenerator[AsyncSession, None]:
    """Get a shared-schema database session (for admin endpoints)."""
    async for session in get_shared_session():
        yield session


async def get_redis() -> TenantRedis:
    """Get a tenant-aware Redis client."""
    return get_tenant_redis()
