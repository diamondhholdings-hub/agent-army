"""FastAPI dependency injection for tenant-scoped resources and authentication.

These dependencies are used in endpoint function signatures to inject
the correct tenant context, database session, Redis client, and authenticated user.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.database import get_shared_session, get_tenant_session
from src.app.core.redis import TenantRedis, get_tenant_redis
from src.app.core.security import validate_api_key, verify_token
from src.app.core.tenant import TenantContext, get_current_tenant
from src.app.models.tenant import User


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


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the current user from JWT or API key.

    Checks Authorization header for Bearer JWT first, then X-API-Key header.
    Returns the User object from the database.

    Raises:
        HTTPException(401): If no valid authentication is provided.
        HTTPException(403): If user's tenant doesn't match the current tenant context.
    """
    tenant = get_current_tenant()

    # Try JWT authentication first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token_str = auth_header[7:]
        payload = verify_token(token_str, token_type="access")

        user_id = payload.get("sub")
        token_tenant_id = payload.get("tenant_id")

        # Verify tenant context matches JWT claims
        if token_tenant_id and token_tenant_id != tenant.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token tenant does not match request tenant context",
            )

        # Load user from database
        result = await db.execute(
            select(User).where(
                User.id == user_id,
                User.tenant_id == tenant.tenant_id,
                User.is_active == True,  # noqa: E712
            )
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )
        return user

    # Try API key authentication
    api_key = request.headers.get("X-API-Key")
    if api_key:
        key_info = await validate_api_key(api_key)
        if not key_info:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        # Verify tenant matches
        if key_info["tenant_id"] != tenant.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key tenant does not match request tenant context",
            )

        # Load user
        result = await db.execute(
            select(User).where(
                User.id == key_info["user_id"],
                User.tenant_id == tenant.tenant_id,
                User.is_active == True,  # noqa: E712
            )
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key user not found or inactive",
            )
        return user

    # No authentication provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Alias for cleaner endpoint signatures
require_auth = Depends(get_current_user)
