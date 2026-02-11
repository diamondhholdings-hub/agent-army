"""Pydantic schemas for authentication API endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Request schema for user login."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=1, description="User password")


class TokenResponse(BaseModel):
    """Response schema with access and refresh tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefreshRequest(BaseModel):
    """Request schema to refresh an access token."""

    refresh_token: str = Field(..., description="Valid refresh token")


class ApiKeyCreate(BaseModel):
    """Request schema for creating a new API key."""

    name: str = Field(..., min_length=1, max_length=200, description="Human-readable name for the API key")


class ApiKeyResponse(BaseModel):
    """Response schema for a newly created API key.

    The `key` field is only returned at creation time; it cannot be
    retrieved later.
    """

    id: str
    name: str
    key: str  # Only returned on creation
    created_at: datetime | None = None


class UserResponse(BaseModel):
    """Response schema for current user info."""

    id: str
    email: str
    name: str | None = None
    role: str
    tenant_id: str
    tenant_slug: str
