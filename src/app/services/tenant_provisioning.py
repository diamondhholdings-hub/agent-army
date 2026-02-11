"""Tenant provisioning service.

Handles creating new tenants with isolated PostgreSQL schemas,
RLS policies, and Redis namespaces. This is the core of the
multi-tenant onboarding flow.
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.database import get_engine
from src.app.core.redis import get_redis_pool

logger = logging.getLogger(__name__)

# Slug validation: lowercase alphanumeric + hyphens, 3-50 chars
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


async def provision_tenant(slug: str, name: str) -> dict:
    """Provision a new tenant with isolated schema, RLS, and Redis namespace.

    Steps:
    1. Validate slug format
    2. Compute schema_name
    3. Check for duplicate slug
    4. Create PostgreSQL schema
    5. Create tables and enable RLS
    6. Insert tenant record in shared.tenants
    7. Initialize Redis namespace
    8. Return tenant data

    Raises:
        HTTPException(400): Invalid slug format
        HTTPException(409): Tenant with slug already exists
    """
    # 1. Validate slug
    if not SLUG_PATTERN.match(slug):
        raise HTTPException(
            status_code=400,
            detail="Slug must be 3-50 chars, lowercase alphanumeric and hyphens only, "
                   "must start and end with alphanumeric character.",
        )

    # 2. Compute schema name
    schema_name = f"tenant_{slug.replace('-', '_')}"

    engine = get_engine()
    async with engine.begin() as conn:
        # 3. Check for duplicate
        result = await conn.execute(
            text("SELECT id FROM shared.tenants WHERE slug = :slug"),
            {"slug": slug},
        )
        if result.first():
            raise HTTPException(status_code=409, detail=f"Tenant with slug '{slug}' already exists")

        # 4. Create PostgreSQL schema
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))

        # 5. Create users table with RLS (inline DDL for reliability)
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS "{schema_name}".users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                email VARCHAR(255) NOT NULL,
                name VARCHAR(200),
                hashed_password VARCHAR(255),
                role VARCHAR(50) NOT NULL DEFAULT 'member',
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ
            )
        """))

        # Enable and FORCE RLS on users
        await conn.execute(text(f'ALTER TABLE "{schema_name}".users ENABLE ROW LEVEL SECURITY'))
        await conn.execute(text(f'ALTER TABLE "{schema_name}".users FORCE ROW LEVEL SECURITY'))

        # Create RLS policy on users
        await conn.execute(text(f"""
            CREATE POLICY tenant_isolation ON "{schema_name}".users
            FOR ALL
            USING (tenant_id::text = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
        """))

        # Create indexes on users
        await conn.execute(text(
            f'CREATE INDEX IF NOT EXISTS idx_users_tenant ON "{schema_name}".users(tenant_id)'
        ))
        await conn.execute(text(
            f'CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_tenant ON "{schema_name}".users(tenant_id, lower(email))'
        ))

        # 5b. Create api_keys table with RLS
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS "{schema_name}".api_keys (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                user_id UUID NOT NULL REFERENCES "{schema_name}".users(id) ON DELETE CASCADE,
                key_hash VARCHAR(255) NOT NULL,
                name VARCHAR(200) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT true,
                last_used_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """))

        # Enable and FORCE RLS on api_keys
        await conn.execute(text(f'ALTER TABLE "{schema_name}".api_keys ENABLE ROW LEVEL SECURITY'))
        await conn.execute(text(f'ALTER TABLE "{schema_name}".api_keys FORCE ROW LEVEL SECURITY'))

        # Create RLS policy on api_keys
        await conn.execute(text(f"""
            CREATE POLICY tenant_isolation ON "{schema_name}".api_keys
            FOR ALL
            USING (tenant_id::text = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
        """))

        # Create indexes on api_keys
        await conn.execute(text(
            f'CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON "{schema_name}".api_keys(tenant_id)'
        ))
        await conn.execute(text(
            f'CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_tenant_hash ON "{schema_name}".api_keys(tenant_id, key_hash)'
        ))

        # 6. Insert tenant record
        tenant_id = uuid.uuid4()
        await conn.execute(
            text("""
                INSERT INTO shared.tenants (id, slug, name, schema_name, is_active, created_at)
                VALUES (:id, :slug, :name, :schema_name, true, now())
            """),
            {"id": tenant_id, "slug": slug, "name": name, "schema_name": schema_name},
        )

    # 7. Initialize Redis namespace
    try:
        redis = get_redis_pool()
        await redis.set(f"t:{tenant_id}:initialized", "true")
    except Exception:
        logger.warning("Failed to initialize Redis namespace for tenant %s", slug)

    # 8. Return tenant data
    return {
        "tenant_id": str(tenant_id),
        "slug": slug,
        "name": name,
        "schema_name": schema_name,
    }


async def list_tenants() -> list[dict]:
    """List all active tenants."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, slug, name, schema_name, is_active, created_at FROM shared.tenants WHERE is_active = true ORDER BY created_at")
        )
        rows = result.fetchall()
        return [
            {
                "id": str(row.id),
                "slug": row.slug,
                "name": row.name,
                "schema_name": row.schema_name,
                "is_active": row.is_active,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]


async def get_tenant_by_slug(slug: str) -> dict | None:
    """Look up a tenant by slug. Caches result in Redis for 5 minutes."""
    redis = get_redis_pool()

    # Try cache first (global key, not tenant-prefixed)
    try:
        import json
        cached = await redis.get(f"tenant:slug:{slug}")
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    # Query database
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, slug, name, schema_name, is_active, created_at FROM shared.tenants WHERE slug = :slug AND is_active = true"),
            {"slug": slug},
        )
        row = result.first()
        if not row:
            return None

        tenant_data = {
            "id": str(row.id),
            "slug": row.slug,
            "name": row.name,
            "schema_name": row.schema_name,
            "is_active": row.is_active,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    # Cache for 5 minutes
    try:
        import json
        await redis.set(f"tenant:slug:{slug}", json.dumps(tenant_data), ex=300)
    except Exception:
        pass

    return tenant_data
