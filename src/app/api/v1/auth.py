"""Authentication API endpoints.

Provides login, token refresh, current user info, and API key management.
All endpoints except login and refresh require a valid JWT token.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.deps import get_current_user, get_db
from src.app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from src.app.core.tenant import get_current_tenant
from src.app.models.tenant import ApiKey, User
from src.app.schemas.auth import (
    ApiKeyCreate,
    ApiKeyResponse,
    LoginRequest,
    TokenRefreshRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate a user and return JWT tokens.

    Requires X-Tenant-ID header (or tenant context from middleware) to scope
    the user lookup to the correct tenant.
    """
    tenant = get_current_tenant()

    # Look up user by email in the tenant's schema
    result = await db.execute(
        select(User).where(
            User.email == body.email,
            User.tenant_id == tenant.tenant_id,
            User.is_active == True,  # noqa: E712
        )
    )
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Create tokens with tenant-scoped claims
    token_data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "tenant_slug": tenant.tenant_slug,
        "email": user.email,
        "role": user.role,
    }

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: TokenRefreshRequest, db: AsyncSession = Depends(get_db)):
    """Refresh an expired access token using a valid refresh token."""
    payload = verify_token(body.refresh_token, token_type="refresh")

    # Verify user still exists and is active
    tenant = get_current_tenant()
    result = await db.execute(
        select(User).where(
            User.id == payload["sub"],
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

    # Issue new tokens
    token_data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "tenant_slug": tenant.tenant_slug,
        "email": user.email,
        "role": user.role,
    }

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return current user info from JWT claims."""
    tenant = get_current_tenant()
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.name,
        role=current_user.role,
        tenant_id=str(current_user.tenant_id),
        tenant_slug=tenant.tenant_slug,
    )


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key for the authenticated user.

    The raw key is returned only once at creation time. Store it securely.
    """
    tenant = get_current_tenant()

    # Generate a random API key
    raw_key = secrets.token_urlsafe(32)
    key_hash = hash_password(raw_key)

    api_key = ApiKey(
        tenant_id=tenant.tenant_id,
        user_id=current_user.id,
        key_hash=key_hash,
        name=body.name,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyResponse(
        id=str(api_key.id),
        name=api_key.name,
        key=raw_key,
        created_at=api_key.created_at,
    )
