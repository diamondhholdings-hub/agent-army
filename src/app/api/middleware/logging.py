"""Structured request logging middleware.

Logs every request with:
- method, path, status_code, duration_ms
- tenant_id and user_id (from context if available)
- request_id (UUID generated per request, added to response as X-Request-ID)

Uses structlog for structured JSON logging in production and
human-readable console output in development.
"""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import Request, Response
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.app.config import Environment, get_settings
from src.app.core.tenant import get_current_tenant

logger = structlog.get_logger(__name__)


def configure_structlog() -> None:
    """Configure structlog processors based on environment."""
    settings = get_settings()

    shared_processors: list = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.ENVIRONMENT == Environment.production:
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs every request with tenant context and timing.

    Generates a unique X-Request-ID for each request and includes it in
    both the log entry and the response headers.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        start_time = time.monotonic()

        # Extract user_id from JWT if present (best effort, don't fail)
        user_id = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            try:
                settings = get_settings()
                payload = jwt.decode(
                    auth_header[7:],
                    settings.JWT_SECRET_KEY,
                    algorithms=[settings.JWT_ALGORITHM],
                )
                user_id = payload.get("sub")
            except JWTError:
                pass

        # Process request
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            # Try to get tenant context
            tenant_id = None
            try:
                tenant_ctx = get_current_tenant()
                tenant_id = tenant_ctx.tenant_id
            except RuntimeError:
                pass

            logger.error(
                "request_error",
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration_ms,
                tenant_id=tenant_id,
                user_id=user_id,
                request_id=request_id,
            )
            raise

        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        # Try to get tenant context (may not be set for health/docs endpoints)
        tenant_id = None
        try:
            tenant_ctx = get_current_tenant()
            tenant_id = tenant_ctx.tenant_id
        except RuntimeError:
            pass

        # Add X-Request-ID to response
        response.headers["X-Request-ID"] = request_id

        # Log the request
        log_method = logger.info if response.status_code < 400 else logger.warning
        if response.status_code >= 500:
            log_method = logger.error

        log_method(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            tenant_id=tenant_id,
            user_id=user_id,
            request_id=request_id,
        )

        return response
