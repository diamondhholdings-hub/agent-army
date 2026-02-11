"""FastAPI application factory.

Creates the app with tenant middleware, lifespan events for database
initialization, and the v1 API router.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from src.app.config import get_settings
from src.app.core.database import close_db, init_db
from src.app.core.redis import close_redis, get_redis_pool
from src.app.core.tenant import TenantMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: init DB on startup, close on shutdown."""
    await init_db()
    yield
    await close_db()
    await close_redis()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Agent Army API",
        version="0.1.0",
        description="Enterprise Sales Organization Platform with Multi-Agent AI Crew",
        lifespan=lifespan,
    )

    # Add tenant middleware with Redis for caching
    redis_client = get_redis_pool()
    app.add_middleware(TenantMiddleware, redis_client=redis_client)

    # Health endpoint (skips tenant middleware)
    @app.get("/health")
    async def health_check():
        return {"status": "ok", "environment": settings.ENVIRONMENT.value}

    return app


# Module-level app for uvicorn
app = create_app()
