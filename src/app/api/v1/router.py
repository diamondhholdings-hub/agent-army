"""V1 API router -- aggregates all v1 endpoint routers."""

from __future__ import annotations

from fastapi import APIRouter

from src.app.api.v1 import auth, deals, health, learning, llm, meetings, sales, tenants

router = APIRouter()

router.include_router(health.router)
router.include_router(tenants.router)
router.include_router(auth.router)
router.include_router(llm.router)
router.include_router(sales.router)
router.include_router(learning.router)
router.include_router(deals.router)
router.include_router(meetings.router)
