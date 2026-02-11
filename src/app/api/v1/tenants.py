"""Tenant management API endpoints.

These endpoints skip tenant middleware (no X-Tenant-ID needed)
since they are admin/provisioning endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from src.app.schemas.tenant import TenantCreate, TenantResponse
from src.app.services.tenant_provisioning import list_tenants, provision_tenant

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: TenantCreate):
    """Provision a new tenant with isolated schema and RLS policies."""
    result = await provision_tenant(slug=body.slug, name=body.name)
    return TenantResponse(
        id=result["tenant_id"],
        slug=result["slug"],
        name=result["name"],
        schema_name=result["schema_name"],
    )


@router.get("", response_model=list[TenantResponse])
async def get_tenants():
    """List all active tenants."""
    tenants = await list_tenants()
    return [TenantResponse(**t) for t in tenants]
