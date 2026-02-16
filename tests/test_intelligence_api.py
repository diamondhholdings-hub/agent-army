"""Integration tests for Phase 7 intelligence API endpoints, main.py wiring, and prompt integration.

Tests cover:
1. API endpoint behavior with mocked services (10+ tests)
2. Integration wiring: router registration, persona prompt injection (5+ tests)

All tests use in-memory test doubles set on app.state. No database required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.api.v1.intelligence import router as intelligence_router
from src.app.agents.sales.prompts import (
    build_persona_prompt_section,
    build_system_prompt,
    VOSS_METHODOLOGY_PROMPT,
)
from src.app.agents.sales.schemas import Channel, DealStage, PersonaType


# ── Constants ────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
ACCOUNT_ID = str(uuid.uuid4())
CLONE_ID = str(uuid.uuid4())
GOAL_ID = str(uuid.uuid4())
INSIGHT_ID = str(uuid.uuid4())
ACTION_ID = str(uuid.uuid4())
NOW = datetime.now(timezone.utc)


# ── Test Doubles ─────────────────────────────────────────────────────────────


class FakeUser:
    """Minimal User stand-in for authentication dependency override."""

    id = "test-user-1"
    tenant_id = TENANT_ID
    is_active = True
    email = "test@example.com"


class FakeTenantContext:
    """Minimal TenantContext stand-in."""

    tenant_id = TENANT_ID
    slug = "test-tenant"


class FakeCustomerViewService:
    """In-memory customer view service."""

    async def get_unified_view(self, tenant_id: str, account_id: str) -> dict:
        return {
            "tenant_id": tenant_id,
            "account_id": account_id,
            "timeline": [],
            "summary_30d": None,
            "summary_90d": None,
            "summary_365d": None,
            "signals": {},
            "last_updated": NOW.isoformat(),
        }


class FakeIntelligenceRepository:
    """In-memory intelligence repository for API tests."""

    def __init__(self) -> None:
        self._insights: List[Dict[str, Any]] = []
        self._clones: List[Dict[str, Any]] = []
        self._goals: List[Dict[str, Any]] = []
        self._actions: List[Dict[str, Any]] = []

    async def list_insights(
        self,
        tenant_id: str,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return self._insights[:limit]

    async def create_insight(self, **kwargs: Any) -> Dict[str, Any]:
        data = {"id": str(uuid.uuid4()), "created_at": NOW, **kwargs}
        self._insights.append(data)
        return data


class FakeInsightGenerator:
    """In-memory insight generator."""

    async def process_feedback(
        self,
        tenant_id: str,
        insight_id: str,
        feedback: str,
        comment: Optional[str] = None,
    ) -> bool:
        return True

    async def generate_daily_digest(
        self,
        tenant_id: str,
        clone_id: Optional[str] = None,
    ) -> dict:
        return {
            "tenant_id": tenant_id,
            "clone_id": clone_id,
            "period_start": (NOW - timedelta(hours=24)).isoformat(),
            "period_end": NOW.isoformat(),
            "insights": [],
            "grouped_by_account": {},
        }

    async def get_feedback_summary(self, tenant_id: str) -> dict:
        return {
            "useful_count": 10,
            "false_alarm_count": 2,
            "total": 12,
            "accuracy_rate": 0.833,
        }


class FakeGoalTracker:
    """In-memory goal tracker."""

    def __init__(self) -> None:
        self._goals: List[Dict[str, Any]] = []

    async def create_goal(
        self,
        tenant_id: str,
        goal_type: Any,
        target_value: float,
        period_start: datetime,
        period_end: datetime,
        clone_id: Optional[str] = None,
    ) -> dict:
        goal = {
            "goal_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "clone_id": clone_id,
            "goal_type": goal_type.value if hasattr(goal_type, "value") else goal_type,
            "target_value": target_value,
            "current_value": 0.0,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "status": "active",
        }
        self._goals.append(goal)
        return goal

    async def get_active_goals(
        self,
        tenant_id: str,
        clone_id: Optional[str] = None,
    ) -> list:
        return self._goals

    async def get_goal_status(
        self,
        tenant_id: str,
        goal_id: str,
    ) -> Optional[dict]:
        for g in self._goals:
            if g["goal_id"] == goal_id:
                return {
                    "goal_id": goal_id,
                    "progress_pct": 0.0,
                    "on_track": True,
                    "status": "active",
                }
        return None

    async def compute_metrics(
        self,
        tenant_id: str,
        clone_id: Optional[str] = None,
    ) -> dict:
        return {
            "tenant_id": tenant_id,
            "clone_id": clone_id,
            "pipeline_value": 150000.0,
            "activity_count": 42,
            "quality_score": 0.78,
            "revenue_closed": 50000.0,
            "as_of": NOW.isoformat(),
        }


class FakeCloneManager:
    """In-memory clone manager."""

    def __init__(self) -> None:
        self._clones: Dict[str, Dict[str, Any]] = {}

    async def create_clone(
        self,
        tenant_id: str,
        clone_name: str,
        owner_id: str,
        persona_config: Any,
    ) -> dict:
        cid = str(uuid.uuid4())
        clone = {
            "clone_id": cid,
            "tenant_id": tenant_id,
            "clone_name": clone_name,
            "owner_id": owner_id,
            "persona": persona_config if isinstance(persona_config, dict) else {},
            "created_at": NOW.isoformat(),
            "active": True,
        }
        self._clones[cid] = clone
        return clone

    async def list_clones(self, tenant_id: str) -> list:
        return list(self._clones.values())

    async def get_clone(self, tenant_id: str, clone_id: str) -> Optional[dict]:
        return self._clones.get(clone_id)

    async def update_clone(self, tenant_id: str, clone_id: str, **updates: Any) -> Optional[dict]:
        clone = self._clones.get(clone_id)
        if clone is None:
            return None
        clone.update(updates)
        return clone

    async def deactivate_clone(self, tenant_id: str, clone_id: str) -> bool:
        return clone_id in self._clones


class FakeAutonomyEngine:
    """In-memory autonomy engine."""

    async def get_pending_approvals(self, tenant_id: str) -> list:
        return []

    async def resolve_approval(
        self, tenant_id: str, action_id: str, approved: bool, resolved_by: str
    ) -> bool:
        return True


class FakePatternEngine:
    """In-memory pattern engine."""

    async def scan_account(
        self, tenant_id: str, account_id: str, customer_view_service: Any
    ) -> list:
        return []


class FakePersonaBuilder:
    """In-memory persona builder."""

    def build_persona(
        self,
        clone_name: str = "",
        owner_id: str = "",
        dimensions: Optional[dict] = None,
        region: Optional[str] = None,
        custom_instructions: Optional[str] = None,
    ) -> Any:
        """Return a mock PersonaConfig."""
        config = MagicMock()
        config.tenant_id = ""
        config.clone_id = str(uuid.uuid4())
        config.owner_id = owner_id
        config.dimensions = dimensions or {}
        config.region = region
        config.custom_instructions = custom_instructions
        return config

    def get_dimension_options(self) -> list:
        return [
            {
                "dimension": "formal_casual",
                "label": "Communication Formality",
                "low": "Casual and friendly",
                "high": "Formal and professional",
                "description": "How formal should communication be?",
                "default": 0.5,
            },
            {
                "dimension": "concise_detailed",
                "label": "Response Detail",
                "low": "Concise",
                "high": "Detailed",
                "description": "How much detail?",
                "default": 0.5,
            },
            {
                "dimension": "technical_business",
                "label": "Technical Depth",
                "low": "Business-level",
                "high": "Technical",
                "description": "How technical?",
                "default": 0.5,
            },
            {
                "dimension": "proactive_reactive",
                "label": "Initiative Level",
                "low": "Reactive",
                "high": "Proactive",
                "description": "How proactive?",
                "default": 0.5,
            },
        ]

    async def generate_preview(self, config: Any) -> dict:
        return {
            "persona": {"clone_id": getattr(config, "clone_id", "preview")},
            "sample_email": "Hi, thanks for your interest in our product.",
            "sample_chat": "Thanks for the demo! Let's schedule a follow-up.",
            "persona_summary": "A balanced, professional sales agent.",
        }


# ── App Fixture ──────────────────────────────────────────────────────────────


def _create_test_app(
    services: Optional[Dict[str, Any]] = None,
    services_none: bool = False,
) -> FastAPI:
    """Create a minimal FastAPI app with intelligence router and mock deps."""
    from src.app.api.v1 import intelligence

    app = FastAPI()
    app.include_router(intelligence.router)

    # Override auth dependencies
    async def fake_get_user():
        return FakeUser()

    async def fake_get_tenant():
        return FakeTenantContext()

    from src.app.api.deps import get_current_user, get_tenant

    app.dependency_overrides[get_current_user] = fake_get_user
    app.dependency_overrides[get_tenant] = fake_get_tenant

    # Set services on app.state
    if services_none:
        # All services are None -- tests 503 behavior
        app.state.customer_view_service = None
        app.state.intelligence_repository = None
        app.state.insight_generator = None
        app.state.goal_tracker = None
        app.state.clone_manager = None
        app.state.persona_builder = None
        app.state.autonomy_engine = None
        app.state.pattern_engine = None
    elif services:
        for name, svc in services.items():
            setattr(app.state, name, svc)
    else:
        # Default: all fake services
        app.state.customer_view_service = FakeCustomerViewService()
        app.state.intelligence_repository = FakeIntelligenceRepository()
        app.state.insight_generator = FakeInsightGenerator()
        app.state.goal_tracker = FakeGoalTracker()
        app.state.clone_manager = FakeCloneManager()
        app.state.persona_builder = FakePersonaBuilder()
        app.state.autonomy_engine = FakeAutonomyEngine()
        app.state.pattern_engine = FakePatternEngine()

    return app


# ── API Endpoint Tests ───────────────────────────────────────────────────────


class TestCustomerViewEndpoints:
    """Tests for customer view API endpoints."""

    def test_get_customer_view_503_when_not_initialized(self):
        """Returns 503 if customer_view_service is None."""
        app = _create_test_app(services_none=True)
        client = TestClient(app)
        resp = client.get(f"/intelligence/customer-view/{ACCOUNT_ID}")
        assert resp.status_code == 503
        assert "customer_view_service" in resp.json()["detail"]

    def test_get_customer_view_success(self):
        """Returns unified view for a valid account."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get(f"/intelligence/customer-view/{ACCOUNT_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == ACCOUNT_ID


class TestInsightsEndpoints:
    """Tests for insights API endpoints."""

    def test_list_insights_empty(self):
        """Returns empty list when no insights exist."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/intelligence/insights")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_submit_feedback(self):
        """POST feedback returns 200."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post(
            f"/intelligence/insights/{INSIGHT_ID}/feedback",
            json={"feedback": "useful", "comment": "Great insight"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["feedback"] == "useful"

    def test_get_daily_digest(self):
        """GET digest returns digest structure."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/intelligence/insights/digest")
        assert resp.status_code == 200
        data = resp.json()
        assert "insights" in data
        assert "grouped_by_account" in data

    def test_get_feedback_stats(self):
        """GET feedback-stats returns statistics."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/intelligence/insights/feedback-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["useful_count"] == 10
        assert data["accuracy_rate"] == 0.833


class TestGoalsEndpoints:
    """Tests for goals API endpoints."""

    def test_create_goal(self):
        """POST creates goal, returns 201."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post(
            "/intelligence/goals",
            json={
                "goal_type": "revenue",
                "target_value": 100000.0,
                "period_start": NOW.isoformat(),
                "period_end": (NOW + timedelta(days=90)).isoformat(),
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["goal_type"] == "revenue"
        assert data["target_value"] == 100000.0

    def test_list_goals(self):
        """GET returns goals list."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/intelligence/goals")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_metrics(self):
        """GET metrics returns performance snapshot."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/intelligence/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pipeline_value"] == 150000.0


class TestCloneEndpoints:
    """Tests for clone/persona API endpoints."""

    def test_create_clone(self):
        """POST creates clone, returns 201."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post(
            "/intelligence/clones",
            json={
                "clone_name": "Sarah's Agent",
                "owner_id": "user-42",
                "dimensions": {"formal_casual": 0.8},
                "region": "emea",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["clone_name"] == "Sarah's Agent"
        assert data["owner_id"] == "user-42"

    def test_list_clones(self):
        """GET returns clones list."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/intelligence/clones")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_deactivate_clone(self):
        """DELETE returns 200."""
        # Pre-populate a clone
        clone_manager = FakeCloneManager()
        clone_manager._clones[CLONE_ID] = {
            "clone_id": CLONE_ID,
            "tenant_id": TENANT_ID,
            "clone_name": "Test Clone",
            "owner_id": "user-1",
            "active": True,
        }
        app = _create_test_app(services={"clone_manager": clone_manager})
        # Need remaining services too
        app.state.persona_builder = FakePersonaBuilder()
        app.state.customer_view_service = FakeCustomerViewService()
        app.state.intelligence_repository = FakeIntelligenceRepository()
        app.state.insight_generator = FakeInsightGenerator()
        app.state.goal_tracker = FakeGoalTracker()
        app.state.autonomy_engine = FakeAutonomyEngine()
        app.state.pattern_engine = FakePatternEngine()

        client = TestClient(app)
        resp = client.delete(f"/intelligence/clones/{CLONE_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deactivated"

    def test_persona_preview(self):
        """POST returns preview with sample_email and sample_chat."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post(
            "/intelligence/clones/preview",
            json={
                "clone_name": "Preview",
                "owner_id": "user-1",
                "dimensions": {"formal_casual": 0.3},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sample_email" in data
        assert "sample_chat" in data

    def test_dimension_options(self):
        """GET returns 4 dimensions."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/intelligence/persona/dimensions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        dimension_keys = {d["dimension"] for d in data}
        assert "formal_casual" in dimension_keys
        assert "concise_detailed" in dimension_keys


class TestAutonomyEndpoints:
    """Tests for autonomy API endpoints."""

    def test_pending_approvals_empty(self):
        """Returns empty list when no pending approvals."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/intelligence/autonomy/pending")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_approve_action(self):
        """POST approve returns 200."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post(
            f"/intelligence/autonomy/{ACTION_ID}/approve",
            json={"approved": True, "resolved_by": "user-42"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"

    def test_trigger_pattern_scan(self):
        """POST scan returns patterns count."""
        app = _create_test_app()
        client = TestClient(app)
        resp = client.post(f"/intelligence/autonomy/scan/{ACCOUNT_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == ACCOUNT_ID
        assert data["patterns_detected"] == 0


# ── Integration Wiring Tests ─────────────────────────────────────────────────


class TestIntegrationWiring:
    """Tests for router registration, prompt integration, and backward compatibility."""

    def test_intelligence_router_registered(self):
        """Intelligence routes are present in the v1 router."""
        from src.app.api.v1.router import router as v1_router

        route_paths = [route.path for route in v1_router.routes]
        # Check for at least one intelligence route
        assert any("/intelligence" in p for p in route_paths), (
            f"No intelligence routes found. Available paths: {route_paths}"
        )

    def test_build_persona_prompt_section_with_clone(self):
        """Persona section generated from clone config."""
        from src.app.intelligence.persona.schemas import PersonaConfig, PersonaDimension

        config = PersonaConfig(
            clone_id="clone-1",
            tenant_id="t-1",
            owner_id="user-1",
            dimensions={
                PersonaDimension.formal_casual: 0.8,
                PersonaDimension.concise_detailed: 0.5,
                PersonaDimension.technical_business: 0.3,
                PersonaDimension.proactive_reactive: 0.7,
            },
            region=None,
        )

        # Create a mock clone config with a persona attribute
        mock_clone = MagicMock()
        mock_clone.persona = config

        section = build_persona_prompt_section(clone_config=mock_clone)
        assert section, "Expected non-empty persona section"
        assert "Communication Style" in section
        assert "methodology" in section.lower() or "do not" in section.lower()

    def test_build_persona_prompt_section_empty_when_no_inputs(self):
        """Returns empty string when no clone config or geographic adapter."""
        section = build_persona_prompt_section()
        assert section == ""

    def test_build_system_prompt_with_persona(self):
        """Persona section appended after methodology in system prompt."""
        persona_section = "## Clone Persona\n- Formal and professional"
        prompt = build_system_prompt(
            persona=PersonaType.MANAGER,
            channel=Channel.EMAIL,
            deal_stage=DealStage.DISCOVERY,
            persona_section=persona_section,
        )
        # Persona section should appear in the prompt
        assert "## Clone Persona" in prompt
        # Rules should appear AFTER persona section
        rules_idx = prompt.index("**Critical Rules:**")
        persona_idx = prompt.index("## Clone Persona")
        assert persona_idx < rules_idx, (
            "Persona section should appear before Critical Rules"
        )

    def test_build_system_prompt_without_persona(self):
        """Backward compatible -- empty persona_section produces same prompt."""
        prompt_default = build_system_prompt(
            persona=PersonaType.IC,
            channel=Channel.CHAT,
            deal_stage=DealStage.PROSPECTING,
        )
        prompt_explicit = build_system_prompt(
            persona=PersonaType.IC,
            channel=Channel.CHAT,
            deal_stage=DealStage.PROSPECTING,
            persona_section="",
        )
        assert prompt_default == prompt_explicit

    def test_methodology_not_overridden(self):
        """BANT/MEDDIC/QBS methodology sections present even with persona."""
        persona_section = "## Custom Clone Style\n- Casual tone"
        prompt = build_system_prompt(
            persona=PersonaType.C_SUITE,
            channel=Channel.EMAIL,
            deal_stage=DealStage.QUALIFICATION,
            persona_section=persona_section,
        )
        # Core methodologies must be present
        assert "Chris Voss" in prompt or "tactical empathy" in prompt.lower()
        assert "BANT" in prompt
        assert "MEDDIC" in prompt
        # QBS should also be present
        assert "Question Based Selling" in prompt or "QBS" in prompt
        # The persona section should NOT replace methodology
        assert "Custom Clone Style" in prompt

    def test_intelligence_api_route_count(self):
        """Intelligence router has 18+ routes (20 defined)."""
        from src.app.api.v1.intelligence import router

        assert len(router.routes) >= 18, (
            f"Expected 18+ routes, got {len(router.routes)}"
        )
