"""Health check endpoints.

Provides liveness (/health) and readiness (/health/ready) checks.
Readiness verifies database and Redis connectivity.
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
    """Basic liveness check."""
    settings = get_settings()
    return {"status": "ok", "environment": settings.ENVIRONMENT.value}


@router.get("/health/ready")
async def readiness_check():
    """Readiness check: verifies DB and Redis connectivity.

    Returns 200 if both pass, 503 if either fails.
    """
    checks = {"database": False, "redis": False}

    # Check database
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        checks["database_error"] = str(e)

    # Check Redis
    try:
        redis = get_redis_pool()
        pong = await redis.ping()
        checks["redis"] = bool(pong)
    except Exception as e:
        checks["redis_error"] = str(e)

    # Return appropriate status
    all_healthy = checks.get("database", False) and checks.get("redis", False)
    return JSONResponse(
        status_code=status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ready" if all_healthy else "degraded", "checks": checks},
    )
