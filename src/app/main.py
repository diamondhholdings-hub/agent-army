"""FastAPI application factory.

Creates the app with tenant middleware, logging middleware, metrics middleware,
CORS, Sentry, lifespan events for database initialization, and the v1 API router.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import Response

from src.app.config import get_settings
from src.app.core.database import close_db, init_db
from src.app.core.monitoring import MetricsMiddleware, get_metrics_response, init_sentry
from src.app.core.redis import close_redis, get_redis_pool
from src.app.api.middleware.tenant import TenantAuthMiddleware
from src.app.api.middleware.logging import LoggingMiddleware, configure_structlog
from src.app.api.v1.router import router as v1_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: init DB and Sentry on startup, close on shutdown."""
    settings = get_settings()
    configure_structlog()
    await init_db()

    # Initialize Sentry if DSN is configured
    if settings.SENTRY_DSN:
        init_sentry(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT.value)

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

    # Middleware is added in reverse order (last added = outermost)

    # Tenant middleware (inner -- resolves tenant context from JWT/header)
    redis_client = get_redis_pool()
    app.add_middleware(TenantAuthMiddleware, redis_client=redis_client)

    # CORS middleware
    if settings.CORS_ALLOWED_ORIGINS == "*":
        origins = ["*"]
    else:
        origins = [o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Logging middleware (logs every request with timing)
    app.add_middleware(LoggingMiddleware)

    # Metrics middleware (outermost -- records Prometheus metrics for all requests)
    app.add_middleware(MetricsMiddleware)

    # Include v1 API router (health, tenants, auth, etc.)
    app.include_router(v1_router)

    # Prometheus metrics endpoint (infrastructure route, outside v1 router)
    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        """Prometheus metrics endpoint."""
        return get_metrics_response()

    return app


# Module-level app for uvicorn
app = create_app()
