"""Health check endpoints.

Provides liveness (/health), readiness (/health/ready), and startup
(/health/startup) checks. Cloud Run uses these to determine if the
container is alive, ready to serve traffic, and has completed startup.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.app.config import get_settings
from src.app.core.database import get_engine
from src.app.core.redis import get_redis_pool

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Basic liveness check.

    Cloud Run uses this to verify the process is alive.
    No external dependencies are checked -- just that the server is running.
    """
    settings = get_settings()
    return {"status": "ok", "environment": settings.ENVIRONMENT.value}


async def _check_dependencies() -> dict:
    """Check database, Redis, Qdrant, and LiteLLM connectivity. Returns check results dict."""
    checks: dict = {"database": "ok", "redis": "ok", "qdrant": "ok", "litellm": "ok"}

    # Check database
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        checks["database"] = "error"
        checks["database_error"] = str(e)

    # Check Redis
    try:
        redis = get_redis_pool()
        pong = await redis.ping()
        if not pong:
            checks["redis"] = "error"
            checks["redis_error"] = "PING did not return PONG"
    except Exception as e:
        checks["redis"] = "error"
        checks["redis_error"] = str(e)

    # Check Qdrant
    try:
        from src.knowledge.config import KnowledgeBaseConfig

        kb_config = KnowledgeBaseConfig()
        if kb_config.qdrant_url:
            from qdrant_client import QdrantClient

            client = QdrantClient(url=kb_config.qdrant_url, api_key=kb_config.qdrant_api_key)
            try:
                client.get_collections()
                checks["qdrant"] = "ok"
            finally:
                client.close()
        else:
            checks["qdrant"] = "local"
    except Exception as e:
        checks["qdrant"] = "error"
        checks["qdrant_error"] = str(e)

    # Check LiteLLM (verify at least one LLM provider key is configured)
    try:
        settings = get_settings()
        if settings.ANTHROPIC_API_KEY or settings.OPENAI_API_KEY:
            checks["litellm"] = "ok"
        else:
            checks["litellm"] = "no_keys"
    except Exception as e:
        checks["litellm"] = "error"
        checks["litellm_error"] = str(e)

    return checks


@router.get("/health/ready")
async def readiness_check():
    """Readiness check: verifies DB, Redis, Qdrant, and LiteLLM connectivity.

    Returns 200 if all pass, 503 if any critical dependency fails.
    Cloud Run uses this to determine if the container can serve traffic.
    """
    checks = await _check_dependencies()
    all_healthy = (
        checks.get("database") == "ok"
        and checks.get("redis") == "ok"
        and checks.get("qdrant") in ("ok", "local")
        and checks.get("litellm") in ("ok", "no_keys")
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "ready" if all_healthy else "degraded",
            "checks": checks,
        },
    )


@router.get("/health/startup")
async def startup_check():
    """Startup check: same as readiness but used during initial container startup.

    Cloud Run gives more time for this probe. Used to verify the app
    has finished initializing (database connections established, etc.).
    """
    checks = await _check_dependencies()
    all_healthy = (
        checks.get("database") == "ok"
        and checks.get("redis") == "ok"
        and checks.get("qdrant") in ("ok", "local")
        and checks.get("litellm") in ("ok", "no_keys")
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "started" if all_healthy else "starting",
            "checks": checks,
        },
    )
