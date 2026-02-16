"""Unit tests for Phase 7 intelligence data layer: schemas, models, and repository.

Tests Pydantic schema construction and validation, SQLAlchemy model
field definitions, and IntelligenceRepository CRUD via InMemoryIntelligenceRepository
test double.

Covers all 4 sub-system schemas (consolidation, patterns, autonomy, persona),
all 5 SQLAlchemy models, and all 16+ repository methods.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import pytest

from src.app.intelligence.consolidation.schemas import (
    ChannelInteraction,
    UnifiedCustomerView,
)
from src.app.intelligence.patterns.schemas import (
    Alert,
    DailyDigest,
    Insight,
    PatternMatch,
    PatternType,
)
from src.app.intelligence.autonomy.schemas import (
    ActionCategory,
    ApprovalRequest,
    AutonomyAction,
    Goal,
    GoalType,
    GuardrailResult,
    PerformanceMetrics,
)
from src.app.intelligence.persona.schemas import (
    Clone,
    PersonaConfig,
    PersonaDimension,
    PersonaPreview,
)


# ── Constants ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
ACCOUNT_ID = str(uuid.uuid4())
CLONE_ID = str(uuid.uuid4())
OWNER_ID = str(uuid.uuid4())
NOW = datetime.now(timezone.utc)


# ── InMemoryIntelligenceRepository ────────────────────────────────────────────


class InMemoryIntelligenceRepository:
    """In-memory test double for IntelligenceRepository.

    Mirrors the IntelligenceRepository interface using dicts for storage.
    Used for fast unit testing without database dependency.
    """

    def __init__(self) -> None:
        self.clones: Dict[str, Dict[str, Any]] = {}
        self.insights: Dict[str, Dict[str, Any]] = {}
        self.goals: Dict[str, Dict[str, Any]] = {}
        self.actions: Dict[str, Dict[str, Any]] = {}
        self.feedback: Dict[str, Dict[str, Any]] = {}

    # ── Clone CRUD ──────────────────────────────────────────────────────────

    async def create_clone(
        self,
        tenant_id: str,
        clone_name: str,
        owner_id: str,
        persona_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        clone_id = str(uuid.uuid4())
        clone = {
            "id": clone_id,
            "tenant_id": tenant_id,
            "clone_name": clone_name,
            "owner_id": owner_id,
            "persona_config": persona_config or {},
            "active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": None,
        }
        self.clones[clone_id] = clone
        return clone

    async def get_clone(
        self, tenant_id: str, clone_id: str
    ) -> Optional[Dict[str, Any]]:
        clone = self.clones.get(clone_id)
        if clone and clone["tenant_id"] == tenant_id:
            return clone
        return None

    async def list_clones(
        self, tenant_id: str, active_only: bool = True
    ) -> List[Dict[str, Any]]:
        results = []
        for c in self.clones.values():
            if c["tenant_id"] == tenant_id:
                if active_only and not c["active"]:
                    continue
                results.append(c)
        return results

    async def update_clone(
        self, tenant_id: str, clone_id: str, **updates: Any
    ) -> Optional[Dict[str, Any]]:
        clone = self.clones.get(clone_id)
        if clone is None or clone["tenant_id"] != tenant_id:
            return None
        for key, value in updates.items():
            if key in clone:
                clone[key] = value
        clone["updated_at"] = datetime.now(timezone.utc)
        return clone

    async def deactivate_clone(
        self, tenant_id: str, clone_id: str
    ) -> Optional[Dict[str, Any]]:
        return await self.update_clone(tenant_id, clone_id, active=False)

    # ── Insight CRUD ────────────────────────────────────────────────────────

    async def create_insight(
        self,
        tenant_id: str,
        account_id: str,
        pattern_type: str,
        pattern_data: Dict[str, Any],
        confidence: float,
        severity: str = "medium",
    ) -> Dict[str, Any]:
        insight_id = str(uuid.uuid4())
        insight = {
            "id": insight_id,
            "tenant_id": tenant_id,
            "account_id": account_id,
            "pattern_type": pattern_type,
            "pattern_data": pattern_data,
            "confidence": confidence,
            "severity": severity,
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "acted_at": None,
        }
        self.insights[insight_id] = insight
        return insight

    async def get_insight(
        self, tenant_id: str, insight_id: str
    ) -> Optional[Dict[str, Any]]:
        insight = self.insights.get(insight_id)
        if insight and insight["tenant_id"] == tenant_id:
            return insight
        return None

    async def list_insights(
        self,
        tenant_id: str,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        results = []
        for i in self.insights.values():
            if i["tenant_id"] != tenant_id:
                continue
            if account_id is not None and i["account_id"] != account_id:
                continue
            if status is not None and i["status"] != status:
                continue
            results.append(i)
        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results[:limit]

    async def update_insight_status(
        self, tenant_id: str, insight_id: str, status: str
    ) -> Optional[Dict[str, Any]]:
        insight = self.insights.get(insight_id)
        if insight is None or insight["tenant_id"] != tenant_id:
            return None
        insight["status"] = status
        if status in ("acted", "dismissed"):
            insight["acted_at"] = datetime.now(timezone.utc)
        return insight

    # ── Goal CRUD ───────────────────────────────────────────────────────────

    async def create_goal(
        self,
        tenant_id: str,
        goal_type: str,
        target_value: float,
        period_start: datetime,
        period_end: datetime,
        clone_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        goal_id = str(uuid.uuid4())
        goal = {
            "id": goal_id,
            "tenant_id": tenant_id,
            "clone_id": clone_id,
            "goal_type": goal_type,
            "target_value": target_value,
            "current_value": 0.0,
            "period_start": period_start,
            "period_end": period_end,
            "status": "active",
            "created_at": datetime.now(timezone.utc),
        }
        self.goals[goal_id] = goal
        return goal

    async def get_goal(
        self, tenant_id: str, goal_id: str
    ) -> Optional[Dict[str, Any]]:
        goal = self.goals.get(goal_id)
        if goal and goal["tenant_id"] == tenant_id:
            return goal
        return None

    async def list_goals(
        self,
        tenant_id: str,
        clone_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results = []
        for g in self.goals.values():
            if g["tenant_id"] != tenant_id:
                continue
            if clone_id is not None and g["clone_id"] != clone_id:
                continue
            if status is not None and g["status"] != status:
                continue
            results.append(g)
        return results

    async def update_goal_progress(
        self, tenant_id: str, goal_id: str, current_value: float
    ) -> Optional[Dict[str, Any]]:
        goal = self.goals.get(goal_id)
        if goal is None or goal["tenant_id"] != tenant_id:
            return None
        goal["current_value"] = current_value
        if current_value >= goal["target_value"] and goal["status"] == "active":
            goal["status"] = "completed"
        return goal

    # ── Action Logging ──────────────────────────────────────────────────────

    async def log_autonomous_action(
        self,
        tenant_id: str,
        action_type: str,
        account_id: str,
        action_data: Optional[Dict[str, Any]] = None,
        approval_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        action_id = str(uuid.uuid4())
        action = {
            "id": action_id,
            "tenant_id": tenant_id,
            "action_type": action_type,
            "account_id": account_id,
            "action_data": action_data or {},
            "proposed_at": datetime.now(timezone.utc),
            "executed_at": None,
            "execution_result": None,
            "approval_status": approval_status,
            "approved_by": None,
            "approved_at": None,
        }
        self.actions[action_id] = action
        return action

    async def get_action(
        self, tenant_id: str, action_id: str
    ) -> Optional[Dict[str, Any]]:
        action = self.actions.get(action_id)
        if action and action["tenant_id"] == tenant_id:
            return action
        return None

    async def update_action_result(
        self,
        tenant_id: str,
        action_id: str,
        execution_result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        action = self.actions.get(action_id)
        if action is None or action["tenant_id"] != tenant_id:
            return None
        action["execution_result"] = execution_result
        action["executed_at"] = datetime.now(timezone.utc)
        return action

    # ── Feedback ────────────────────────────────────────────────────────────

    async def record_feedback(
        self,
        tenant_id: str,
        insight_id: str,
        feedback: str,
        submitted_by: str,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        feedback_id = str(uuid.uuid4())
        fb = {
            "id": feedback_id,
            "tenant_id": tenant_id,
            "insight_id": insight_id,
            "feedback": feedback,
            "submitted_by": submitted_by,
            "comment": comment,
            "submitted_at": datetime.now(timezone.utc),
        }
        self.feedback[feedback_id] = fb
        return fb

    async def get_feedback_stats(
        self, tenant_id: str
    ) -> Dict[str, int]:
        stats: Dict[str, int] = {"useful": 0, "false_alarm": 0, "total": 0}
        for fb in self.feedback.values():
            if fb["tenant_id"] == tenant_id:
                stats[fb["feedback"]] = stats.get(fb["feedback"], 0) + 1
                stats["total"] += 1
        return stats


# ── Schema Tests ──────────────────────────────────────────────────────────────


class TestConsolidationSchemas:
    """Test cross-channel data consolidation schemas."""

    def test_channel_interaction_constructs(self):
        interaction = ChannelInteraction(
            channel="email",
            timestamp=NOW,
            participants=["alice@example.com", "bob@acme.com"],
            content_summary="Discussed pricing for enterprise plan",
            sentiment="positive",
            key_points=["Budget approved at $500K", "Timeline is Q2"],
        )
        assert interaction.channel == "email"
        assert len(interaction.participants) == 2
        assert interaction.sentiment == "positive"
        assert len(interaction.key_points) == 2

    def test_channel_interaction_defaults(self):
        interaction = ChannelInteraction(
            channel="meeting",
            timestamp=NOW,
            content_summary="Discovery call",
        )
        assert interaction.participants == []
        assert interaction.sentiment is None
        assert interaction.key_points == []

    def test_unified_customer_view_schema(self):
        interaction = ChannelInteraction(
            channel="email",
            timestamp=NOW,
            content_summary="Initial outreach",
        )
        view = UnifiedCustomerView(
            tenant_id=TENANT_ID,
            account_id=ACCOUNT_ID,
            timeline=[interaction],
            summary_30d="Active engagement with budget signals",
            signals={"bant_budget": True, "risk": False},
            last_updated=NOW,
        )
        assert view.tenant_id == TENANT_ID
        assert len(view.timeline) == 1
        assert view.summary_30d is not None
        assert view.summary_90d is None
        assert view.summary_365d is None
        assert view.signals["bant_budget"] is True

    def test_unified_customer_view_empty_timeline(self):
        view = UnifiedCustomerView(
            tenant_id=TENANT_ID,
            account_id=ACCOUNT_ID,
            last_updated=NOW,
        )
        assert view.timeline == []
        assert view.signals == {}


class TestPatternSchemas:
    """Test pattern recognition and insight schemas."""

    def test_pattern_type_enum(self):
        assert PatternType.buying_signal.value == "buying_signal"
        assert PatternType.risk_indicator.value == "risk_indicator"
        assert PatternType.engagement_change.value == "engagement_change"
        assert PatternType.cross_account_pattern.value == "cross_account_pattern"

    def test_pattern_match_confidence_range(self):
        """Confidence must be between 0.0 and 1.0."""
        match = PatternMatch(
            pattern_type=PatternType.buying_signal,
            confidence=0.85,
            severity="high",
            evidence=["Budget mention in meeting", "Timeline urgency in email"],
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )
        assert match.confidence == 0.85
        assert match.severity == "high"
        assert len(match.evidence) == 2

    def test_pattern_match_confidence_too_high(self):
        with pytest.raises(Exception):
            PatternMatch(
                pattern_type=PatternType.buying_signal,
                confidence=1.5,
                detected_at=NOW,
                account_id=ACCOUNT_ID,
            )

    def test_pattern_match_confidence_too_low(self):
        with pytest.raises(Exception):
            PatternMatch(
                pattern_type=PatternType.buying_signal,
                confidence=-0.1,
                detected_at=NOW,
                account_id=ACCOUNT_ID,
            )

    def test_insight_schema(self):
        pattern = PatternMatch(
            pattern_type=PatternType.risk_indicator,
            confidence=0.72,
            detected_at=NOW,
            account_id=ACCOUNT_ID,
        )
        insight = Insight(
            id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            pattern=pattern,
            created_at=NOW,
        )
        assert insight.status == "pending"
        assert insight.acted_at is None

    def test_alert_schema(self):
        alert = Alert(
            insight_id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
        )
        assert alert.channel == "sse"
        assert alert.delivered_at is None

    def test_daily_digest_schema(self):
        digest = DailyDigest(
            tenant_id=TENANT_ID,
            period_start=NOW - timedelta(days=1),
            period_end=NOW,
        )
        assert digest.clone_id is None
        assert digest.insights == []
        assert digest.grouped_by_account == {}


class TestAutonomySchemas:
    """Test autonomy engine, guardrails, and goal schemas."""

    def test_action_category_enum(self):
        assert ActionCategory.autonomous.value == "autonomous"
        assert ActionCategory.approval_required.value == "approval_required"
        assert ActionCategory.hard_stop.value == "hard_stop"

    def test_autonomy_action_schema(self):
        action = AutonomyAction(
            action_id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            action_type="send_follow_up_email",
            account_id=ACCOUNT_ID,
            rationale="No response in 3 days",
            proposed_at=NOW,
        )
        assert action.deal_stage is None
        assert action.executed_at is None
        assert action.action_type == "send_follow_up_email"

    def test_guardrail_result_schema(self):
        action = AutonomyAction(
            action_id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            action_type="commit_pricing",
            account_id=ACCOUNT_ID,
            rationale="Customer asked for pricing",
            proposed_at=NOW,
        )
        result = GuardrailResult(
            allowed=False,
            reason="hard_stop",
            requires_human=True,
            action=action,
        )
        assert not result.allowed
        assert result.requires_human is True

    def test_approval_request_schema(self):
        action = AutonomyAction(
            action_id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            action_type="send_proposal",
            account_id=ACCOUNT_ID,
            rationale="Customer ready for proposal",
            proposed_at=NOW,
        )
        request = ApprovalRequest(
            action_id=action.action_id,
            tenant_id=TENANT_ID,
            action=action,
            requested_at=NOW,
        )
        assert request.approved is None
        assert request.resolved_at is None
        assert request.resolved_by is None

    def test_goal_schema_validation(self):
        """Goal target_value must be positive."""
        goal = Goal(
            goal_id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            goal_type=GoalType.revenue,
            target_value=100000.0,
            period_start=NOW,
            period_end=NOW + timedelta(days=90),
        )
        assert goal.current_value == 0.0
        assert goal.status == "active"
        assert goal.clone_id is None

    def test_goal_target_must_be_positive(self):
        with pytest.raises(Exception):
            Goal(
                goal_id=str(uuid.uuid4()),
                tenant_id=TENANT_ID,
                goal_type=GoalType.pipeline,
                target_value=0.0,
                period_start=NOW,
                period_end=NOW + timedelta(days=30),
            )

    def test_goal_type_enum(self):
        assert GoalType.pipeline.value == "pipeline"
        assert GoalType.activity.value == "activity"
        assert GoalType.quality.value == "quality"
        assert GoalType.revenue.value == "revenue"

    def test_performance_metrics_schema(self):
        metrics = PerformanceMetrics(
            tenant_id=TENANT_ID,
            pipeline_value=250000.0,
            activity_count=42,
            revenue_closed=75000.0,
            as_of=NOW,
        )
        assert metrics.quality_score is None
        assert metrics.clone_id is None


class TestPersonaSchemas:
    """Test persona and clone schemas."""

    def test_persona_dimension_enum(self):
        assert PersonaDimension.formal_casual.value == "formal_casual"
        assert PersonaDimension.concise_detailed.value == "concise_detailed"
        assert PersonaDimension.technical_business.value == "technical_business"
        assert PersonaDimension.proactive_reactive.value == "proactive_reactive"

    def test_persona_config_dimensions(self):
        """Persona dimensions should have valid keys."""
        config = PersonaConfig(
            clone_id=CLONE_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            dimensions={
                PersonaDimension.formal_casual: 0.8,
                PersonaDimension.concise_detailed: 0.3,
                PersonaDimension.technical_business: 0.6,
                PersonaDimension.proactive_reactive: 0.9,
            },
            region="apac",
        )
        assert config.dimensions[PersonaDimension.formal_casual] == 0.8
        assert config.region == "apac"
        assert config.custom_instructions is None

    def test_persona_config_defaults(self):
        config = PersonaConfig(
            clone_id=CLONE_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
        )
        assert len(config.dimensions) == 4
        assert config.dimensions[PersonaDimension.formal_casual] == 0.5
        assert config.region is None

    def test_persona_preview_schema(self):
        config = PersonaConfig(
            clone_id=CLONE_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
        )
        preview = PersonaPreview(
            persona=config,
            sample_email="Dear Mr. Smith, I hope this email finds you well.",
            sample_chat="Hi! Quick question about your timeline.",
            persona_summary="Balanced professional style with moderate formality.",
        )
        assert preview.sample_email.startswith("Dear")
        assert preview.persona_summary is not None

    def test_clone_schema(self):
        config = PersonaConfig(
            clone_id=CLONE_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
        )
        clone = Clone(
            clone_id=CLONE_ID,
            tenant_id=TENANT_ID,
            clone_name="West Coast Rep",
            owner_id=OWNER_ID,
            persona=config,
            created_at=NOW,
        )
        assert clone.active is True
        assert clone.clone_name == "West Coast Rep"


# ── Model Import Tests ────────────────────────────────────────────────────────


class TestModelImports:
    """Test that all 5 SQLAlchemy models import and have correct attributes."""

    def test_agent_clone_model(self):
        from src.app.intelligence.models import AgentCloneModel
        assert AgentCloneModel.__tablename__ == "agent_clones"
        assert hasattr(AgentCloneModel, "id")
        assert hasattr(AgentCloneModel, "tenant_id")
        assert hasattr(AgentCloneModel, "clone_name")
        assert hasattr(AgentCloneModel, "owner_id")
        assert hasattr(AgentCloneModel, "persona_config")
        assert hasattr(AgentCloneModel, "active")
        assert hasattr(AgentCloneModel, "created_at")
        assert hasattr(AgentCloneModel, "updated_at")

    def test_insight_model(self):
        from src.app.intelligence.models import InsightModel
        assert InsightModel.__tablename__ == "insights"
        assert hasattr(InsightModel, "id")
        assert hasattr(InsightModel, "tenant_id")
        assert hasattr(InsightModel, "account_id")
        assert hasattr(InsightModel, "pattern_type")
        assert hasattr(InsightModel, "pattern_data")
        assert hasattr(InsightModel, "confidence")
        assert hasattr(InsightModel, "severity")
        assert hasattr(InsightModel, "status")
        assert hasattr(InsightModel, "created_at")
        assert hasattr(InsightModel, "acted_at")

    def test_goal_model(self):
        from src.app.intelligence.models import GoalModel
        assert GoalModel.__tablename__ == "goals"
        assert hasattr(GoalModel, "id")
        assert hasattr(GoalModel, "tenant_id")
        assert hasattr(GoalModel, "clone_id")
        assert hasattr(GoalModel, "goal_type")
        assert hasattr(GoalModel, "target_value")
        assert hasattr(GoalModel, "current_value")
        assert hasattr(GoalModel, "period_start")
        assert hasattr(GoalModel, "period_end")
        assert hasattr(GoalModel, "status")

    def test_autonomous_action_model(self):
        from src.app.intelligence.models import AutonomousActionModel
        assert AutonomousActionModel.__tablename__ == "autonomous_actions"
        assert hasattr(AutonomousActionModel, "id")
        assert hasattr(AutonomousActionModel, "tenant_id")
        assert hasattr(AutonomousActionModel, "action_type")
        assert hasattr(AutonomousActionModel, "account_id")
        assert hasattr(AutonomousActionModel, "action_data")
        assert hasattr(AutonomousActionModel, "proposed_at")
        assert hasattr(AutonomousActionModel, "executed_at")
        assert hasattr(AutonomousActionModel, "execution_result")
        assert hasattr(AutonomousActionModel, "approval_status")
        assert hasattr(AutonomousActionModel, "approved_by")
        assert hasattr(AutonomousActionModel, "approved_at")

    def test_alert_feedback_model(self):
        from src.app.intelligence.models import AlertFeedbackModel
        assert AlertFeedbackModel.__tablename__ == "alert_feedback"
        assert hasattr(AlertFeedbackModel, "id")
        assert hasattr(AlertFeedbackModel, "tenant_id")
        assert hasattr(AlertFeedbackModel, "insight_id")
        assert hasattr(AlertFeedbackModel, "feedback")
        assert hasattr(AlertFeedbackModel, "comment")
        assert hasattr(AlertFeedbackModel, "submitted_at")
        assert hasattr(AlertFeedbackModel, "submitted_by")


# ── Repository Tests ──────────────────────────────────────────────────────────


@pytest.fixture
def repo() -> InMemoryIntelligenceRepository:
    """Fresh in-memory repository for each test."""
    return InMemoryIntelligenceRepository()


class TestCloneRepository:
    """Test clone CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_and_get_clone(self, repo):
        clone = await repo.create_clone(
            tenant_id=TENANT_ID,
            clone_name="East Coast Rep",
            owner_id=OWNER_ID,
            persona_config={"formality": 0.8},
        )
        assert clone["clone_name"] == "East Coast Rep"
        assert clone["active"] is True

        retrieved = await repo.get_clone(TENANT_ID, clone["id"])
        assert retrieved is not None
        assert retrieved["clone_name"] == "East Coast Rep"
        assert retrieved["persona_config"]["formality"] == 0.8

    @pytest.mark.asyncio
    async def test_list_clones_active_only(self, repo):
        clone1 = await repo.create_clone(TENANT_ID, "Clone A", OWNER_ID)
        clone2 = await repo.create_clone(TENANT_ID, "Clone B", OWNER_ID)

        await repo.deactivate_clone(TENANT_ID, clone2["id"])

        active = await repo.list_clones(TENANT_ID, active_only=True)
        assert len(active) == 1
        assert active[0]["clone_name"] == "Clone A"

        all_clones = await repo.list_clones(TENANT_ID, active_only=False)
        assert len(all_clones) == 2

    @pytest.mark.asyncio
    async def test_deactivate_clone(self, repo):
        clone = await repo.create_clone(TENANT_ID, "To Deactivate", OWNER_ID)
        assert clone["active"] is True

        result = await repo.deactivate_clone(TENANT_ID, clone["id"])
        assert result is not None
        assert result["active"] is False

    @pytest.mark.asyncio
    async def test_update_clone(self, repo):
        clone = await repo.create_clone(TENANT_ID, "Original Name", OWNER_ID)
        updated = await repo.update_clone(
            TENANT_ID, clone["id"], clone_name="New Name"
        )
        assert updated is not None
        assert updated["clone_name"] == "New Name"
        assert updated["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_get_clone_wrong_tenant(self, repo):
        clone = await repo.create_clone(TENANT_ID, "My Clone", OWNER_ID)
        other_tenant = str(uuid.uuid4())
        result = await repo.get_clone(other_tenant, clone["id"])
        assert result is None


class TestInsightRepository:
    """Test insight CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_insight(self, repo):
        insight = await repo.create_insight(
            tenant_id=TENANT_ID,
            account_id=ACCOUNT_ID,
            pattern_type="buying_signal",
            pattern_data={"signal": "budget_mentioned", "amount": 500000},
            confidence=0.85,
            severity="high",
        )
        assert insight["pattern_type"] == "buying_signal"
        assert insight["confidence"] == 0.85
        assert insight["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_insights_by_status(self, repo):
        await repo.create_insight(
            TENANT_ID, ACCOUNT_ID, "buying_signal", {}, 0.8, "high"
        )
        insight2 = await repo.create_insight(
            TENANT_ID, ACCOUNT_ID, "risk_indicator", {}, 0.6, "medium"
        )
        await repo.update_insight_status(TENANT_ID, insight2["id"], "dismissed")

        pending = await repo.list_insights(TENANT_ID, status="pending")
        assert len(pending) == 1

        dismissed = await repo.list_insights(TENANT_ID, status="dismissed")
        assert len(dismissed) == 1

    @pytest.mark.asyncio
    async def test_update_insight_status(self, repo):
        insight = await repo.create_insight(
            TENANT_ID, ACCOUNT_ID, "buying_signal", {}, 0.9, "critical"
        )
        updated = await repo.update_insight_status(TENANT_ID, insight["id"], "acted")
        assert updated is not None
        assert updated["status"] == "acted"
        assert updated["acted_at"] is not None

    @pytest.mark.asyncio
    async def test_list_insights_by_account(self, repo):
        other_account = str(uuid.uuid4())
        await repo.create_insight(
            TENANT_ID, ACCOUNT_ID, "buying_signal", {}, 0.8
        )
        await repo.create_insight(
            TENANT_ID, other_account, "risk_indicator", {}, 0.7
        )

        results = await repo.list_insights(TENANT_ID, account_id=ACCOUNT_ID)
        assert len(results) == 1
        assert results[0]["account_id"] == ACCOUNT_ID


class TestGoalRepository:
    """Test goal CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_goal(self, repo):
        goal = await repo.create_goal(
            tenant_id=TENANT_ID,
            goal_type="revenue",
            target_value=100000.0,
            period_start=NOW,
            period_end=NOW + timedelta(days=90),
        )
        assert goal["goal_type"] == "revenue"
        assert goal["target_value"] == 100000.0
        assert goal["current_value"] == 0.0
        assert goal["status"] == "active"

    @pytest.mark.asyncio
    async def test_update_goal_progress(self, repo):
        goal = await repo.create_goal(
            TENANT_ID, "pipeline", 50000.0, NOW, NOW + timedelta(days=30)
        )
        updated = await repo.update_goal_progress(TENANT_ID, goal["id"], 25000.0)
        assert updated is not None
        assert updated["current_value"] == 25000.0
        assert updated["status"] == "active"

    @pytest.mark.asyncio
    async def test_goal_auto_completes(self, repo):
        goal = await repo.create_goal(
            TENANT_ID, "activity", 100.0, NOW, NOW + timedelta(days=30)
        )
        updated = await repo.update_goal_progress(TENANT_ID, goal["id"], 100.0)
        assert updated is not None
        assert updated["status"] == "completed"

    @pytest.mark.asyncio
    async def test_list_goals_by_status(self, repo):
        goal1 = await repo.create_goal(
            TENANT_ID, "revenue", 100000.0, NOW, NOW + timedelta(days=90)
        )
        goal2 = await repo.create_goal(
            TENANT_ID, "activity", 50.0, NOW, NOW + timedelta(days=30)
        )
        await repo.update_goal_progress(TENANT_ID, goal2["id"], 50.0)

        active = await repo.list_goals(TENANT_ID, status="active")
        assert len(active) == 1
        assert active[0]["id"] == goal1["id"]

        completed = await repo.list_goals(TENANT_ID, status="completed")
        assert len(completed) == 1
        assert completed[0]["id"] == goal2["id"]


class TestActionRepository:
    """Test autonomous action logging operations."""

    @pytest.mark.asyncio
    async def test_log_autonomous_action(self, repo):
        action = await repo.log_autonomous_action(
            tenant_id=TENANT_ID,
            action_type="send_follow_up_email",
            account_id=ACCOUNT_ID,
            action_data={"subject": "Following up on our conversation"},
        )
        assert action["action_type"] == "send_follow_up_email"
        assert action["executed_at"] is None
        assert action["approval_status"] is None

    @pytest.mark.asyncio
    async def test_update_action_result(self, repo):
        action = await repo.log_autonomous_action(
            TENANT_ID, "schedule_meeting", ACCOUNT_ID
        )
        result = await repo.update_action_result(
            TENANT_ID,
            action["id"],
            {"meeting_id": str(uuid.uuid4()), "status": "scheduled"},
        )
        assert result is not None
        assert result["executed_at"] is not None
        assert result["execution_result"]["status"] == "scheduled"

    @pytest.mark.asyncio
    async def test_get_action(self, repo):
        action = await repo.log_autonomous_action(
            TENANT_ID, "send_follow_up_email", ACCOUNT_ID
        )
        retrieved = await repo.get_action(TENANT_ID, action["id"])
        assert retrieved is not None
        assert retrieved["action_type"] == "send_follow_up_email"


class TestFeedbackRepository:
    """Test alert feedback operations."""

    @pytest.mark.asyncio
    async def test_record_feedback(self, repo):
        insight = await repo.create_insight(
            TENANT_ID, ACCOUNT_ID, "buying_signal", {}, 0.8
        )
        feedback = await repo.record_feedback(
            tenant_id=TENANT_ID,
            insight_id=insight["id"],
            feedback="useful",
            submitted_by="user-123",
            comment="This alert was very helpful",
        )
        assert feedback["feedback"] == "useful"
        assert feedback["comment"] == "This alert was very helpful"
        assert feedback["submitted_by"] == "user-123"

    @pytest.mark.asyncio
    async def test_get_feedback_stats(self, repo):
        insight1 = await repo.create_insight(
            TENANT_ID, ACCOUNT_ID, "buying_signal", {}, 0.8
        )
        insight2 = await repo.create_insight(
            TENANT_ID, ACCOUNT_ID, "risk_indicator", {}, 0.6
        )
        insight3 = await repo.create_insight(
            TENANT_ID, ACCOUNT_ID, "engagement_change", {}, 0.7
        )

        await repo.record_feedback(TENANT_ID, insight1["id"], "useful", "user-1")
        await repo.record_feedback(TENANT_ID, insight2["id"], "useful", "user-1")
        await repo.record_feedback(TENANT_ID, insight3["id"], "false_alarm", "user-1")

        stats = await repo.get_feedback_stats(TENANT_ID)
        assert stats["useful"] == 2
        assert stats["false_alarm"] == 1
        assert stats["total"] == 3

    @pytest.mark.asyncio
    async def test_feedback_stats_empty(self, repo):
        stats = await repo.get_feedback_stats(TENANT_ID)
        assert stats["useful"] == 0
        assert stats["false_alarm"] == 0
        assert stats["total"] == 0


# ── Repository Import Test ────────────────────────────────────────────────────


class TestRepositoryImport:
    """Verify IntelligenceRepository imports and has all methods."""

    def test_repository_imports(self):
        from src.app.intelligence.repository import IntelligenceRepository
        assert IntelligenceRepository is not None

    def test_repository_has_clone_methods(self):
        from src.app.intelligence.repository import IntelligenceRepository
        repo = IntelligenceRepository.__new__(IntelligenceRepository)
        assert hasattr(repo, "create_clone")
        assert hasattr(repo, "get_clone")
        assert hasattr(repo, "list_clones")
        assert hasattr(repo, "update_clone")
        assert hasattr(repo, "deactivate_clone")

    def test_repository_has_insight_methods(self):
        from src.app.intelligence.repository import IntelligenceRepository
        repo = IntelligenceRepository.__new__(IntelligenceRepository)
        assert hasattr(repo, "create_insight")
        assert hasattr(repo, "get_insight")
        assert hasattr(repo, "list_insights")
        assert hasattr(repo, "update_insight_status")

    def test_repository_has_goal_methods(self):
        from src.app.intelligence.repository import IntelligenceRepository
        repo = IntelligenceRepository.__new__(IntelligenceRepository)
        assert hasattr(repo, "create_goal")
        assert hasattr(repo, "get_goal")
        assert hasattr(repo, "list_goals")
        assert hasattr(repo, "update_goal_progress")

    def test_repository_has_action_methods(self):
        from src.app.intelligence.repository import IntelligenceRepository
        repo = IntelligenceRepository.__new__(IntelligenceRepository)
        assert hasattr(repo, "log_autonomous_action")
        assert hasattr(repo, "get_action")
        assert hasattr(repo, "update_action_result")

    def test_repository_has_feedback_methods(self):
        from src.app.intelligence.repository import IntelligenceRepository
        repo = IntelligenceRepository.__new__(IntelligenceRepository)
        assert hasattr(repo, "record_feedback")
        assert hasattr(repo, "get_feedback_stats")

    def test_repository_method_count(self):
        """IntelligenceRepository should have at least 16 public methods."""
        from src.app.intelligence.repository import IntelligenceRepository
        public_methods = [
            m for m in dir(IntelligenceRepository)
            if not m.startswith("_") and callable(getattr(IntelligenceRepository, m))
        ]
        assert len(public_methods) >= 16, f"Expected >= 16 methods, found {len(public_methods)}: {public_methods}"


# ── Migration Import Test ─────────────────────────────────────────────────────


class TestMigration:
    """Verify migration file structure."""

    def _load_migration(self):
        """Load migration module via importlib to avoid local alembic shadow."""
        import importlib.util
        import pathlib

        migration_path = (
            pathlib.Path(__file__).parent.parent
            / "alembic"
            / "versions"
            / "add_intelligence_tables.py"
        )
        spec = importlib.util.spec_from_file_location(
            "add_intelligence_tables", str(migration_path)
        )
        mod = importlib.util.module_from_spec(spec)
        # Migration imports alembic.context and alembic.op which
        # are only available inside an Alembic runtime. We verify
        # file structure by inspecting source instead.
        return migration_path

    def test_migration_file_exists(self):
        path = self._load_migration()
        assert path.exists(), f"Migration file not found at {path}"

    def test_migration_has_revision_ids(self):
        path = self._load_migration()
        content = path.read_text()
        assert 'revision: str = "008_intelligence_tables"' in content
        assert 'down_revision: Union[str, None] = "007_meeting_tables"' in content

    def test_migration_creates_all_tables(self):
        path = self._load_migration()
        content = path.read_text()
        for table in ["agent_clones", "insights", "goals", "autonomous_actions", "alert_feedback"]:
            assert f'"{table}"' in content, f"Table {table} not found in migration"

    def test_migration_has_rls_policies(self):
        path = self._load_migration()
        content = path.read_text()
        assert content.count("ENABLE ROW LEVEL SECURITY") == 5
        assert content.count("FORCE ROW LEVEL SECURITY") == 5
        assert content.count("CREATE POLICY tenant_isolation") == 5

    def test_migration_has_indexes(self):
        path = self._load_migration()
        content = path.read_text()
        assert "idx_agent_clones_tenant_active" in content
        assert "idx_insights_tenant_status_created" in content
        assert "idx_goals_tenant_status" in content
        assert "idx_actions_tenant_approval_proposed" in content
        assert "idx_feedback_tenant_feedback" in content

    def test_migration_has_gin_indexes(self):
        path = self._load_migration()
        content = path.read_text()
        assert "USING gin (pattern_data)" in content
        assert "USING gin (action_data)" in content

    def test_migration_has_downgrade(self):
        path = self._load_migration()
        content = path.read_text()
        assert "def downgrade()" in content
        assert content.count("op.drop_table") == 5
