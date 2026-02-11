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
    """Check database and Redis connectivity. Returns check results dict."""
    checks: dict = {"database": "ok", "redis": "ok"}

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

    return checks


@router.get("/health/ready")
async def readiness_check():
    """Readiness check: verifies DB and Redis connectivity.

    Returns 200 if both pass, 503 if either fails.
    Cloud Run uses this to determine if the container can serve traffic.
    """
    checks = await _check_dependencies()
    all_healthy = checks.get("database") == "ok" and checks.get("redis") == "ok"

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
    all_healthy = checks.get("database") == "ok" and checks.get("redis") == "ok"

    return JSONResponse(
        status_code=status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "started" if all_healthy else "starting",
            "checks": checks,
        },
    )
