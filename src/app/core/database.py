"""Async SQLAlchemy engine with multi-tenant schema isolation.

Provides:
- SharedBase: Declarative base for shared schema tables (e.g., tenants)
- TenantBase: Declarative base for per-tenant schema tables (placeholder schema="tenant")
- get_shared_session(): Session for shared schema operations
- get_tenant_session(): Session with schema_translate_map for tenant isolation
- Pool checkout event that resets tenant context (RESET ALL) to prevent stale leaks
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import MetaData, event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncEngine
from sqlalchemy.orm import DeclarativeBase

from src.app.config import get_settings
from src.app.core.tenant import get_current_tenant

# ── Module-level engine (lazy init) ────────────────────────────────────────

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Get or create the async engine singleton."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=20,
            max_overflow=10,
            echo=False,
        )

        # Critical: Reset session variables on every connection checkout
        # to prevent stale tenant context from a previous request leaking
        @event.listens_for(_engine.sync_engine, "checkout")
        def reset_tenant_context(dbapi_conn: Any, connection_record: Any, connection_proxy: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("RESET ALL")
            cursor.close()

    return _engine


# ── Declarative Bases ───────────────────────────────────────────────────────

shared_metadata = MetaData(schema="shared")
tenant_metadata = MetaData(schema="tenant")


class SharedBase(DeclarativeBase):
    """Base class for shared schema models (e.g., tenants table)."""

    metadata = shared_metadata


class TenantBase(DeclarativeBase):
    """Base class for per-tenant schema models.

    Uses placeholder schema="tenant" which is remapped at runtime via
    schema_translate_map to the actual tenant schema (e.g., "tenant_skyvera").
    """

    metadata = tenant_metadata


# ── Session Factories ───────────────────────────────────────────────────────


async def get_shared_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession for the shared schema (no tenant scoping)."""
    engine = get_engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


async def get_tenant_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a tenant-scoped AsyncSession with schema_translate_map and RLS context.

    1. Gets the current tenant from contextvars
    2. Creates a connection with schema_translate_map={"tenant": tenant.schema_name}
    3. Sets RLS context via SET app.current_tenant_id
    4. Yields the session
    5. Closes connection in finally block
    """
    tenant = get_current_tenant()
    engine = get_engine()

    async with engine.connect() as conn:
        # Map placeholder "tenant" schema to actual tenant schema
        conn = await conn.execution_options(
            schema_translate_map={"tenant": tenant.schema_name}
        )
        # Set RLS session variable for defense-in-depth
        await conn.execute(text(f"SET app.current_tenant_id = '{tenant.tenant_id}'"))

        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            yield session


# ── Database Initialization ─────────────────────────────────────────────────


async def init_db() -> None:
    """Create the shared schema and shared tables if they don't exist."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS shared"))
        await conn.run_sync(SharedBase.metadata.create_all)


async def close_db() -> None:
    """Dispose of the engine and close all connections."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
