"""Pydantic schemas for tenant API endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    """Request schema for creating a new tenant."""

    slug: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
        description="Unique tenant identifier (lowercase alphanumeric + hyphens)",
        examples=["skyvera", "jigtree"],
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable tenant name",
        examples=["Skyvera", "Jigtree"],
    )


class TenantResponse(BaseModel):
    """Response schema for tenant data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    schema_name: str
    is_active: bool = True
    created_at: datetime | None = None
