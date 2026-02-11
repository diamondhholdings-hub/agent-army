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
    import structlog

    log = structlog.get_logger(__name__)
    settings = get_settings()
    configure_structlog()
    await init_db()

    # Initialize Sentry if DSN is configured
    if settings.SENTRY_DSN:
        init_sentry(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT.value)

    # ── Phase 2: Agent Orchestration Module Initialization ──────────────
    # All Phase 2 init is additive and failure-tolerant. Each module is
    # wrapped in its own try/except so a single failure (e.g., pgvector
    # not installed) does not prevent the application from starting.

    # Langfuse tracing (instruments LiteLLM callbacks)
    try:
        from src.app.observability.tracer import init_langfuse

        init_langfuse(settings)
    except Exception:
        log.warning("phase2.langfuse_init_failed", exc_info=True)

    # Session store (LangGraph checkpointer)
    try:
        from src.app.context.session import SessionStore

        session_store = SessionStore(settings.DATABASE_URL)
        await session_store.setup()
        app.state.session_store = session_store
        log.info("phase2.session_store_initialized")
    except Exception:
        log.warning("phase2.session_store_init_failed", exc_info=True)
        app.state.session_store = None

    # Long-term memory (pgvector)
    try:
        from src.app.context.memory import LongTermMemory

        long_term_memory = LongTermMemory(settings.DATABASE_URL)
        await long_term_memory.setup()
        app.state.long_term_memory = long_term_memory
        log.info("phase2.long_term_memory_initialized")
    except Exception:
        log.warning(
            "phase2.long_term_memory_init_failed",
            exc_info=True,
            hint="pgvector extension may not be available",
        )
        app.state.long_term_memory = None

    # Agent registry (in-memory singleton)
    try:
        from src.app.agents.registry import get_agent_registry

        registry = get_agent_registry()
        app.state.agent_registry = registry
        log.info("phase2.agent_registry_initialized", agent_count=len(registry))
    except Exception:
        log.warning("phase2.agent_registry_init_failed", exc_info=True)
        app.state.agent_registry = None

    log.info("phase2.orchestration_modules_initialized")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    # Close long-term memory pool if it was initialized
    ltm = getattr(app.state, "long_term_memory", None)
    if ltm is not None:
        try:
            await ltm.close()
        except Exception:
            log.warning("phase2.long_term_memory_close_failed", exc_info=True)

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
