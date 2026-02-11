"""Test fixtures for multi-tenant isolation tests.

Provides:
- FastAPI test app with initialized database
- Async HTTP client for API testing
- Two test tenants (test-alpha, test-beta) with isolated schemas
- Tenant-scoped database sessions
- Cleanup of test data after all tests
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.database import get_engine, init_db, close_db, close_db as _close_db
from src.app.core.redis import get_redis_pool, close_redis
from src.app.core.tenant import TenantContext, set_tenant_context, _tenant_context
from src.app.main import create_app


@pytest_asyncio.fixture(scope="session")
async def app():
    """Create the FastAPI app and initialize the database."""
    application = create_app()

    # Initialize database (creates shared schema + tables)
    await init_db()

    yield application

    # Cleanup: drop test tenant schemas
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS tenant_test_alpha CASCADE"))
        await conn.execute(text("DROP SCHEMA IF EXISTS tenant_test_beta CASCADE"))
        await conn.execute(text("DELETE FROM shared.tenants WHERE slug IN ('test-alpha', 'test-beta')"))

    await close_db()
    await close_redis()


@pytest_asyncio.fixture(scope="session")
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing the API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="session")
async def tenant_alpha(client) -> dict:
    """Provision test-alpha tenant."""
    response = await client.post(
        "/api/v1/tenants",
        json={"slug": "test-alpha", "name": "Test Alpha"},
    )
    assert response.status_code == 201, f"Failed to create test-alpha: {response.text}"
    return response.json()


@pytest_asyncio.fixture(scope="session")
async def tenant_beta(client, tenant_alpha) -> dict:
    """Provision test-beta tenant (after alpha to ensure ordering)."""
    response = await client.post(
        "/api/v1/tenants",
        json={"slug": "test-beta", "name": "Test Beta"},
    )
    assert response.status_code == 201, f"Failed to create test-beta: {response.text}"
    return response.json()


@pytest_asyncio.fixture
async def alpha_session(tenant_alpha) -> AsyncGenerator[AsyncSession, None]:
    """Database session scoped to tenant alpha."""
    engine = get_engine()
    tenant = TenantContext(
        tenant_id=tenant_alpha["id"],
        tenant_slug="test-alpha",
        schema_name="tenant_test_alpha",
    )
    token = set_tenant_context(tenant)
    try:
        async with engine.connect() as conn:
            conn = await conn.execution_options(
                schema_translate_map={"tenant": "tenant_test_alpha"}
            )
            await conn.execute(text(f"SET app.current_tenant_id = '{tenant_alpha['id']}'"))
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                yield session
    finally:
        _tenant_context.reset(token)


@pytest_asyncio.fixture
async def beta_session(tenant_beta) -> AsyncGenerator[AsyncSession, None]:
    """Database session scoped to tenant beta."""
    engine = get_engine()
    tenant = TenantContext(
        tenant_id=tenant_beta["id"],
        tenant_slug="test-beta",
        schema_name="tenant_test_beta",
    )
    token = set_tenant_context(tenant)
    try:
        async with engine.connect() as conn:
            conn = await conn.execution_options(
                schema_translate_map={"tenant": "tenant_test_beta"}
            )
            await conn.execute(text(f"SET app.current_tenant_id = '{tenant_beta['id']}'"))
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                yield session
    finally:
        _tenant_context.reset(token)
