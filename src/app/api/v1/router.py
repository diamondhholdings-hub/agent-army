"""V1 API router -- aggregates all v1 endpoint routers."""

from __future__ import annotations

from fastapi import APIRouter

from src.app.api.v1 import health, tenants

router = APIRouter()

router.include_router(health.router)
router.include_router(tenants.router)
