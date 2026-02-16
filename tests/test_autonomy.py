"""Comprehensive tests for Phase 7 autonomy system.

Tests GuardrailChecker (three-tier action classification, stage gating,
fail-safe defaults), GoalTracker (creation, progress, completion, suggestions),
AutonomyEngine (propose, plan proactive, guardrail routing), and
ProactiveScheduler (task definitions, intervals).

All tests use in-memory test doubles. No database dependency.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from src.app.intelligence.autonomy.guardrails import GuardrailChecker
from src.app.intelligence.autonomy.goals import GoalTracker
from src.app.intelligence.autonomy.engine import AutonomyEngine
from src.app.intelligence.autonomy.scheduler import (
    INTELLIGENCE_TASK_INTERVALS,
    setup_intelligence_scheduler,
)
from src.app.intelligence.autonomy.schemas import (
    ActionCategory,
    AutonomyAction,
    Goal,
    GoalType,
    GuardrailResult,
    PerformanceMetrics,
)
from src.app.intelligence.patterns.schemas import PatternMatch, PatternType


# ── Constants ────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
ACCOUNT_ID = str(uuid.uuid4())
NOW = datetime.now(timezone.utc)


# ── Test Doubles ─────────────────────────────────────────────────────────────


class InMemoryAutonomyRepository:
    """In-memory test double for IntelligenceRepository.

    Supports goal CRUD, action logging, and basic queries
    needed by GoalTracker and AutonomyEngine tests.
    """

    def __init__(self) -> None:
        self._goals: Dict[str, Dict[str, Any]] = {}
        self._actions: Dict[str, Dict[str, Any]] = {}

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
        data = {
            "id": goal_id,
            "tenant_id": tenant_id,
            "clone_id": clone_id,
            "goal_type": goal_type,
            "target_value": target_value,
            "current_value": 0.0,
            "period_start": period_start,
            "period_end": period_end,
            "status": "active",
            "created_at": NOW,
        }
        self._goals[goal_id] = data
        return dict(data)

    async def get_goal(
        self, tenant_id: str, goal_id: str
    ) -> Optional[Dict[str, Any]]:
        data = self._goals.get(goal_id)
        if data and data["tenant_id"] == tenant_id:
            return dict(data)
        return None

    async def list_goals(
        self,
        tenant_id: str,
        clone_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results = []
        for data in self._goals.values():
            if data["tenant_id"] != tenant_id:
                continue
            if clone_id is not None and data.get("clone_id") != clone_id:
                continue
            if status is not None and data.get("status") != status:
                continue
            results.append(dict(data))
        return results

    async def update_goal_progress(
        self, tenant_id: str, goal_id: str, current_value: float
    ) -> Optional[Dict[str, Any]]:
        data = self._goals.get(goal_id)
        if data is None or data["tenant_id"] != tenant_id:
            return None
        data["current_value"] = current_value
        if current_value >= data["target_value"] and data["status"] == "active":
            data["status"] = "completed"
        return dict(data)

    async def log_autonomous_action(
        self,
        tenant_id: str,
        action_type: str,
        account_id: str,
        action_data: Optional[Dict[str, Any]] = None,
        approval_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        action_id = str(uuid.uuid4())
        data = {
            "id": action_id,
            "tenant_id": tenant_id,
            "action_type": action_type,
            "account_id": account_id,
            "action_data": action_data or {},
            "approval_status": approval_status,
            "proposed_at": NOW,
            "executed_at": None,
            "execution_result": None,
            "approved_by": None,
            "approved_at": None,
        }
        self._actions[action_id] = data
        return dict(data)

    async def get_action(
        self, tenant_id: str, action_id: str
    ) -> Optional[Dict[str, Any]]:
        data = self._actions.get(action_id)
        if data and data["tenant_id"] == tenant_id:
            return dict(data)
        return None

    async def update_action_result(
        self,
        tenant_id: str,
        action_id: str,
        execution_result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        data = self._actions.get(action_id)
        if data is None or data["tenant_id"] != tenant_id:
            return None
        data["execution_result"] = execution_result
        data["executed_at"] = NOW
        return dict(data)


class MockPatternEngine:
    """Mock pattern recognition engine for AutonomyEngine tests."""

    def __init__(self, patterns: Optional[List[PatternMatch]] = None) -> None:
        self._patterns = patterns or []

    async def detect_patterns(self, customer_view: Any) -> List[PatternMatch]:
        return list(self._patterns)


class MockCustomerView:
    """Simple mock for UnifiedCustomerView."""

    def __init__(self, account_id: str = ACCOUNT_ID) -> None:
        self.account_id = account_id
        self.tenant_id = TENANT_ID
        self.timeline: List[Any] = []
        self.signals: Dict[str, Any] = {}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_action(
    action_type: str,
    deal_stage: Optional[str] = None,
    account_id: str = ACCOUNT_ID,
) -> AutonomyAction:
    """Create an AutonomyAction for testing."""
    return AutonomyAction(
        action_id=str(uuid.uuid4()),
        tenant_id=TENANT_ID,
        action_type=action_type,
        account_id=account_id,
        deal_stage=deal_stage,
        rationale="Test action",
        proposed_at=NOW,
    )


def _make_pattern(
    pattern_type: PatternType = PatternType.buying_signal,
    confidence: float = 0.85,
    severity: str = "medium",
    evidence: Optional[List[str]] = None,
) -> PatternMatch:
    """Create a PatternMatch for testing."""
    return PatternMatch(
        pattern_type=pattern_type,
        confidence=confidence,
        severity=severity,
        evidence=evidence or ["Evidence 1", "Evidence 2"],
        detected_at=NOW,
        account_id=ACCOUNT_ID,
    )


# ══════════════════════════════════════════════════════════════════════════════
# GUARDRAIL CHECKER TESTS (8 tests)
# ══════════════════════════════════════════════════════════════════════════════


class TestGuardrailChecker:
    """Tests for GuardrailChecker three-tier action classification."""

    def setup_method(self) -> None:
        self.checker = GuardrailChecker()

    def test_autonomous_action_allowed(self) -> None:
        """Autonomous action (send_follow_up_email) should be allowed."""
        action = _make_action("send_follow_up_email")
        result = self.checker.check(action)
        assert result.allowed is True
        assert result.reason == "autonomous"
        assert result.requires_human is False

    def test_approval_required(self) -> None:
        """Approval-required action (send_proposal) should be blocked."""
        action = _make_action("send_proposal")
        result = self.checker.check(action)
        assert result.allowed is False
        assert result.reason == "approval_required"
        assert result.requires_human is True

    def test_hard_stop_blocked(self) -> None:
        """Hard-stop action (commit_pricing) should always be blocked."""
        action = _make_action("commit_pricing")
        result = self.checker.check(action)
        assert result.allowed is False
        assert result.reason == "hard_stop"

    def test_hard_stop_requires_human(self) -> None:
        """Hard-stop actions must require human involvement."""
        action = _make_action("modify_contract")
        result = self.checker.check(action)
        assert result.requires_human is True
        assert result.allowed is False

    def test_unknown_action_fails_safe(self) -> None:
        """Unknown action type should fail-safe to approval_required."""
        action = _make_action("some_random_action")
        result = self.checker.check(action)
        assert result.allowed is False
        assert result.reason == "unknown_action_type"
        assert result.requires_human is True

    def test_stage_gate_negotiation(self) -> None:
        """Autonomous action should be blocked in negotiation stage."""
        action = _make_action("send_follow_up_email", deal_stage="negotiation")
        result = self.checker.check(action)
        assert result.allowed is False
        assert result.reason == "stage_gate"
        assert result.requires_human is True

    def test_stage_gate_discovery(self) -> None:
        """Autonomous action should be allowed in discovery stage."""
        action = _make_action("send_follow_up_email", deal_stage="discovery")
        result = self.checker.check(action)
        assert result.allowed is True
        assert result.reason == "autonomous"

    def test_classify_action(self) -> None:
        """classify_action should return correct ActionCategory."""
        assert self.checker.classify_action("send_follow_up_email") == ActionCategory.autonomous
        assert self.checker.classify_action("send_proposal") == ActionCategory.approval_required
        assert self.checker.classify_action("commit_pricing") == ActionCategory.hard_stop
        assert self.checker.classify_action("unknown_action") == ActionCategory.approval_required

    def test_all_hard_stops_blocked(self) -> None:
        """ALL 7 hard-stop action types must NEVER be allowed."""
        for action_type in GuardrailChecker.HARD_STOPS:
            action = _make_action(action_type)
            result = self.checker.check(action)
            assert result.allowed is False, f"{action_type} should be blocked"
            assert result.reason == "hard_stop", f"{action_type} reason should be hard_stop"
            assert result.requires_human is True, f"{action_type} must require human"

    def test_get_allowed_actions(self) -> None:
        """get_allowed_actions should return the full AUTONOMOUS_ACTIONS set."""
        allowed = self.checker.get_allowed_actions()
        assert allowed == GuardrailChecker.AUTONOMOUS_ACTIONS
        assert "send_follow_up_email" in allowed
        assert "commit_pricing" not in allowed

    def test_get_restricted_actions(self) -> None:
        """get_restricted_actions should include all non-autonomous actions."""
        restricted = self.checker.get_restricted_actions()
        assert "send_proposal" in restricted
        assert restricted["send_proposal"] == "approval_required"
        assert "commit_pricing" in restricted
        assert restricted["commit_pricing"] == "hard_stop"
        assert "send_follow_up_email" not in restricted

    def test_stage_gate_evaluation(self) -> None:
        """Autonomous action should be blocked in evaluation stage."""
        action = _make_action("schedule_meeting", deal_stage="evaluation")
        result = self.checker.check(action)
        assert result.allowed is False
        assert result.reason == "stage_gate"

    def test_stage_gate_closed_won(self) -> None:
        """Autonomous action should be blocked in closed_won stage."""
        action = _make_action("qualify_conversation", deal_stage="closed_won")
        result = self.checker.check(action)
        assert result.allowed is False
        assert result.reason == "stage_gate"

    def test_stage_gate_closed_lost(self) -> None:
        """Autonomous action should be blocked in closed_lost stage."""
        action = _make_action("log_interaction", deal_stage="closed_lost")
        result = self.checker.check(action)
        assert result.allowed is False
        assert result.reason == "stage_gate"

    def test_autonomous_action_no_stage(self) -> None:
        """Autonomous action with no deal_stage should be allowed."""
        action = _make_action("create_briefing", deal_stage=None)
        result = self.checker.check(action)
        assert result.allowed is True

    def test_all_autonomous_actions_allowed_in_qualification(self) -> None:
        """All autonomous actions should be allowed in qualification stage."""
        for action_type in GuardrailChecker.AUTONOMOUS_ACTIONS:
            action = _make_action(action_type, deal_stage="qualification")
            result = self.checker.check(action)
            assert result.allowed is True, f"{action_type} should be allowed in qualification"


# ══════════════════════════════════════════════════════════════════════════════
# GOAL TRACKER TESTS (7 tests)
# ══════════════════════════════════════════════════════════════════════════════


class TestGoalTracker:
    """Tests for GoalTracker creation, progress, and suggestions."""

    def setup_method(self) -> None:
        self.repo = InMemoryAutonomyRepository()
        self.tracker = GoalTracker(repository=self.repo)

    @pytest.mark.asyncio
    async def test_create_goal(self) -> None:
        """Valid goal should be created with correct fields."""
        goal = await self.tracker.create_goal(
            tenant_id=TENANT_ID,
            goal_type=GoalType.revenue,
            target_value=100000.0,
            period_start=NOW,
            period_end=NOW + timedelta(days=90),
        )
        assert goal.tenant_id == TENANT_ID
        assert goal.goal_type == GoalType.revenue
        assert goal.target_value == 100000.0
        assert goal.current_value == 0.0
        assert goal.status == "active"

    @pytest.mark.asyncio
    async def test_create_goal_invalid_target(self) -> None:
        """Goal creation with target <= 0 should raise ValueError."""
        with pytest.raises(ValueError, match="target_value must be positive"):
            await self.tracker.create_goal(
                tenant_id=TENANT_ID,
                goal_type=GoalType.revenue,
                target_value=-100.0,
                period_start=NOW,
                period_end=NOW + timedelta(days=90),
            )

    @pytest.mark.asyncio
    async def test_create_goal_invalid_period(self) -> None:
        """Goal creation with period_end <= period_start should raise ValueError."""
        with pytest.raises(ValueError, match="period_end must be after period_start"):
            await self.tracker.create_goal(
                tenant_id=TENANT_ID,
                goal_type=GoalType.pipeline,
                target_value=50000.0,
                period_start=NOW,
                period_end=NOW - timedelta(days=1),
            )

    @pytest.mark.asyncio
    async def test_update_progress_completed(self) -> None:
        """Status should change to completed when target is met."""
        goal = await self.tracker.create_goal(
            tenant_id=TENANT_ID,
            goal_type=GoalType.revenue,
            target_value=100000.0,
            period_start=NOW,
            period_end=NOW + timedelta(days=90),
        )
        updated = await self.tracker.update_progress(
            tenant_id=TENANT_ID,
            goal_id=goal.goal_id,
            current_value=100000.0,
        )
        assert updated.status == "completed"
        assert updated.current_value == 100000.0

    @pytest.mark.asyncio
    async def test_update_progress_partial(self) -> None:
        """Partial progress should keep status as active."""
        goal = await self.tracker.create_goal(
            tenant_id=TENANT_ID,
            goal_type=GoalType.pipeline,
            target_value=500000.0,
            period_start=NOW,
            period_end=NOW + timedelta(days=90),
        )
        updated = await self.tracker.update_progress(
            tenant_id=TENANT_ID,
            goal_id=goal.goal_id,
            current_value=250000.0,
        )
        assert updated.status == "active"
        assert updated.current_value == 250000.0

    @pytest.mark.asyncio
    async def test_check_goal_on_track(self) -> None:
        """Goal with progress exceeding elapsed time should be on_track=True."""
        # Goal started 45 days ago, ends in 45 days (total 90 days)
        # Use fresh now to avoid timing drift between import and execution
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=45)
        end = now + timedelta(days=45)
        goal = await self.tracker.create_goal(
            tenant_id=TENANT_ID,
            goal_type=GoalType.revenue,
            target_value=100000.0,
            period_start=start,
            period_end=end,
        )
        # Update to 55% progress (comfortably ahead of 50% elapsed time)
        await self.tracker.update_progress(
            tenant_id=TENANT_ID,
            goal_id=goal.goal_id,
            current_value=55000.0,
        )

        statuses = await self.tracker.check_goal_status(TENANT_ID)
        assert len(statuses) == 1
        assert statuses[0]["on_track"] is True
        assert statuses[0]["progress_pct"] == 55.0

    @pytest.mark.asyncio
    async def test_suggest_actions_revenue_behind(self) -> None:
        """Revenue goal behind target should suggest closing activities."""
        # Goal started 60 days ago with only 10% progress (should be ~67%)
        start = NOW - timedelta(days=60)
        end = NOW + timedelta(days=30)
        goal = await self.tracker.create_goal(
            tenant_id=TENANT_ID,
            goal_type=GoalType.revenue,
            target_value=100000.0,
            period_start=start,
            period_end=end,
        )
        await self.tracker.update_progress(
            tenant_id=TENANT_ID,
            goal_id=goal.goal_id,
            current_value=10000.0,
        )

        # Rebuild goal with current data
        updated_goal = Goal(
            goal_id=goal.goal_id,
            tenant_id=TENANT_ID,
            goal_type=GoalType.revenue,
            target_value=100000.0,
            current_value=10000.0,
            period_start=start,
            period_end=end,
            status="active",
        )

        suggestions = await self.tracker.suggest_actions(TENANT_ID, updated_goal)
        assert len(suggestions) > 0
        assert any("closing" in s.lower() for s in suggestions)

    @pytest.mark.asyncio
    async def test_compute_metrics_defaults(self) -> None:
        """compute_metrics should return default zeros when repo has no metric methods."""
        metrics = await self.tracker.compute_metrics(TENANT_ID)
        assert isinstance(metrics, PerformanceMetrics)
        assert metrics.pipeline_value == 0.0
        assert metrics.activity_count == 0
        assert metrics.quality_score is None
        assert metrics.revenue_closed == 0.0

    @pytest.mark.asyncio
    async def test_get_active_goals(self) -> None:
        """get_active_goals should return only active goals."""
        # Create 2 goals, complete one
        goal1 = await self.tracker.create_goal(
            tenant_id=TENANT_ID,
            goal_type=GoalType.revenue,
            target_value=100000.0,
            period_start=NOW,
            period_end=NOW + timedelta(days=90),
        )
        await self.tracker.create_goal(
            tenant_id=TENANT_ID,
            goal_type=GoalType.pipeline,
            target_value=50000.0,
            period_start=NOW,
            period_end=NOW + timedelta(days=90),
        )
        # Complete goal1
        await self.tracker.update_progress(
            TENANT_ID, goal1.goal_id, 100000.0
        )

        active = await self.tracker.get_active_goals(TENANT_ID)
        assert len(active) == 1
        assert active[0].goal_type == GoalType.pipeline


# ══════════════════════════════════════════════════════════════════════════════
# AUTONOMY ENGINE TESTS (6 tests)
# ══════════════════════════════════════════════════════════════════════════════


class TestAutonomyEngine:
    """Tests for AutonomyEngine action routing and proactive planning."""

    def setup_method(self) -> None:
        self.repo = InMemoryAutonomyRepository()
        self.checker = GuardrailChecker()
        self.tracker = GoalTracker(repository=self.repo)
        self.pattern_engine = MockPatternEngine()
        self.engine = AutonomyEngine(
            guardrail_checker=self.checker,
            goal_tracker=self.tracker,
            pattern_engine=self.pattern_engine,
            repository=self.repo,
        )

    @pytest.mark.asyncio
    async def test_propose_autonomous_action(self) -> None:
        """Allowed action should return allowed=True and be logged."""
        action = _make_action("send_follow_up_email")
        result = await self.engine.propose_action(TENANT_ID, action)
        assert result.allowed is True
        assert result.reason == "autonomous"

    @pytest.mark.asyncio
    async def test_propose_hard_stop(self) -> None:
        """Hard-stop action should be blocked and logged."""
        action = _make_action("commit_pricing")
        result = await self.engine.propose_action(TENANT_ID, action)
        assert result.allowed is False
        assert result.reason == "hard_stop"
        assert result.requires_human is True

    @pytest.mark.asyncio
    async def test_propose_approval_required(self) -> None:
        """Approval-required action should create pending approval."""
        action = _make_action("send_proposal")
        result = await self.engine.propose_action(TENANT_ID, action)
        assert result.allowed is False
        assert result.reason == "approval_required"

    @pytest.mark.asyncio
    async def test_plan_proactive_actions_buying_signal(self) -> None:
        """Buying signal pattern should generate follow-up action."""
        buying_pattern = _make_pattern(
            pattern_type=PatternType.buying_signal,
            confidence=0.85,
        )
        self.engine._pattern_engine = MockPatternEngine(patterns=[buying_pattern])

        view = MockCustomerView()
        actions = await self.engine.plan_proactive_actions(TENANT_ID, view)

        assert len(actions) >= 1
        follow_up = [a for a in actions if a.action_type == "send_follow_up_email"]
        assert len(follow_up) >= 1
        assert "buying signal" in follow_up[0].rationale.lower()

    @pytest.mark.asyncio
    async def test_plan_proactive_actions_no_patterns(self) -> None:
        """No patterns and no behind-goals should produce empty action list."""
        self.engine._pattern_engine = MockPatternEngine(patterns=[])
        view = MockCustomerView()
        actions = await self.engine.plan_proactive_actions(TENANT_ID, view)
        assert len(actions) == 0

    @pytest.mark.asyncio
    async def test_plan_proactive_actions_risk_escalation(self) -> None:
        """Critical risk pattern should generate escalation action."""
        risk_pattern = _make_pattern(
            pattern_type=PatternType.risk_indicator,
            confidence=0.9,
            severity="critical",
        )
        self.engine._pattern_engine = MockPatternEngine(patterns=[risk_pattern])

        view = MockCustomerView()
        actions = await self.engine.plan_proactive_actions(TENANT_ID, view)

        escalation = [a for a in actions if a.action_type == "escalate_to_management"]
        assert len(escalation) >= 1

    @pytest.mark.asyncio
    async def test_execute_approved_action_not_found(self) -> None:
        """Executing a non-existent action should raise ValueError."""
        with pytest.raises(ValueError, match="Action not found"):
            await self.engine.execute_approved_action(
                TENANT_ID, str(uuid.uuid4())
            )

    @pytest.mark.asyncio
    async def test_resolve_approval(self) -> None:
        """resolve_approval should update action status."""
        # First propose an action that requires approval
        action = _make_action("send_proposal")
        await self.engine.propose_action(TENANT_ID, action)

        # Get the logged action from repo
        for action_id, data in self.repo._actions.items():
            if data["action_type"] == "send_proposal":
                resolved = await self.engine.resolve_approval(
                    TENANT_ID, action_id, approved=True, resolved_by="user-1"
                )
                assert resolved is True
                break


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER TESTS (3 tests)
# ══════════════════════════════════════════════════════════════════════════════


class TestProactiveScheduler:
    """Tests for ProactiveScheduler task definitions and intervals."""

    def test_task_intervals_defined(self) -> None:
        """All 5 intelligence task intervals should be defined."""
        expected_tasks = {
            "pattern_scan",
            "proactive_outreach_check",
            "goal_progress_update",
            "daily_digest_generation",
            "context_summarization",
        }
        assert set(INTELLIGENCE_TASK_INTERVALS.keys()) == expected_tasks

    def test_task_interval_values(self) -> None:
        """Task intervals should match specified values."""
        assert INTELLIGENCE_TASK_INTERVALS["pattern_scan"] == 6 * 60 * 60
        assert INTELLIGENCE_TASK_INTERVALS["proactive_outreach_check"] == 60 * 60
        assert INTELLIGENCE_TASK_INTERVALS["goal_progress_update"] == 24 * 60 * 60
        assert INTELLIGENCE_TASK_INTERVALS["daily_digest_generation"] == 24 * 60 * 60
        assert INTELLIGENCE_TASK_INTERVALS["context_summarization"] == 24 * 60 * 60

    @pytest.mark.asyncio
    async def test_setup_intelligence_scheduler_returns_all_tasks(self) -> None:
        """setup_intelligence_scheduler should return 5 named tasks."""
        tasks = await setup_intelligence_scheduler(
            pattern_engine=MockPatternEngine(),
            autonomy_engine=None,
            goal_tracker=None,
            insight_generator=None,
            customer_view_service=None,
        )
        assert len(tasks) == 5
        assert set(tasks.keys()) == {
            "pattern_scan",
            "proactive_outreach_check",
            "goal_progress_update",
            "daily_digest_generation",
            "context_summarization",
        }
        # Each value should be callable
        for name, fn in tasks.items():
            assert callable(fn), f"Task {name} should be callable"

    @pytest.mark.asyncio
    async def test_scheduler_tasks_are_resilient(self) -> None:
        """Each scheduler task should handle exceptions gracefully."""
        tasks = await setup_intelligence_scheduler(
            pattern_engine=MockPatternEngine(),
            autonomy_engine=None,
            goal_tracker=None,
            insight_generator=None,
            customer_view_service=None,
        )
        # Each task should run without raising
        for name, fn in tasks.items():
            result = await fn()
            assert isinstance(result, int), f"Task {name} should return int"
