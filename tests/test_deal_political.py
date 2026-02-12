"""Unit tests for PoliticalMapper scoring and PlanManager lifecycle.

Tests title heuristics, human overrides, score clamping, and plan
list trimming. Does NOT test LLM integration (those are integration tests).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.agents.sales.schemas import (
    ConversationState,
    DealStage,
    QualificationState,
)
from src.app.deals.plans import PlanManager
from src.app.deals.political import PoliticalMapper
from src.app.deals.schemas import (
    AccountPlanData,
    InteractionSummary,
    OpportunityPlanData,
    OpportunityRead,
    RelationshipHistory,
    ScoreSource,
    StakeholderRead,
    StakeholderScores,
)


# ── PoliticalMapper Tests ────────────────────────────────────────────────────


class TestScoreFromTitle:
    """Tests for PoliticalMapper.score_from_title()."""

    def setup_method(self) -> None:
        self.mapper = PoliticalMapper()

    def test_score_from_title_ceo(self) -> None:
        """CEO title -> c-suite tier: decision_power=9, influence_level=8."""
        scores = self.mapper.score_from_title("CEO")
        assert scores.decision_power == 9
        assert scores.influence_level == 8
        assert scores.relationship_strength == 3

    def test_score_from_title_cto(self) -> None:
        """CTO title -> c-suite tier."""
        scores = self.mapper.score_from_title("CTO")
        assert scores.decision_power == 9
        assert scores.influence_level == 8

    def test_score_from_title_chief_technology_officer(self) -> None:
        """'Chief Technology Officer' -> c-suite tier via Chief keyword."""
        scores = self.mapper.score_from_title("Chief Technology Officer")
        assert scores.decision_power == 9

    def test_score_from_title_vp(self) -> None:
        """VP of Sales -> vp tier: decision_power=8, influence_level=7."""
        scores = self.mapper.score_from_title("VP of Sales")
        assert scores.decision_power == 8
        assert scores.influence_level == 7

    def test_score_from_title_vice_president(self) -> None:
        """'Vice President of Engineering' -> vp tier."""
        scores = self.mapper.score_from_title("Vice President of Engineering")
        assert scores.decision_power == 8

    def test_score_from_title_svp(self) -> None:
        """SVP -> vp tier."""
        scores = self.mapper.score_from_title("SVP of Marketing")
        assert scores.decision_power == 8

    def test_score_from_title_director(self) -> None:
        """Director of IT -> director tier: decision_power=6, influence_level=6."""
        scores = self.mapper.score_from_title("Director of IT")
        assert scores.decision_power == 6
        assert scores.influence_level == 6

    def test_score_from_title_manager(self) -> None:
        """Product Manager -> manager tier: decision_power=4, influence_level=5."""
        scores = self.mapper.score_from_title("Product Manager")
        assert scores.decision_power == 4
        assert scores.influence_level == 5

    def test_score_from_title_engineering_manager(self) -> None:
        """Engineering Manager -> manager tier."""
        scores = self.mapper.score_from_title("Engineering Manager")
        assert scores.decision_power == 4

    def test_score_from_title_none(self) -> None:
        """None title -> IC default: decision_power=2, influence_level=3."""
        scores = self.mapper.score_from_title(None)
        assert scores.decision_power == 2
        assert scores.influence_level == 3
        assert scores.relationship_strength == 3

    def test_score_from_title_unknown(self) -> None:
        """Unknown title 'Analyst' -> IC default."""
        scores = self.mapper.score_from_title("Senior Business Analyst")
        assert scores.decision_power == 2
        assert scores.influence_level == 3

    def test_score_from_title_empty_string(self) -> None:
        """Empty string -> IC default."""
        scores = self.mapper.score_from_title("")
        assert scores.decision_power == 2


class TestApplyOverride:
    """Tests for PoliticalMapper.apply_override()."""

    def setup_method(self) -> None:
        self.mapper = PoliticalMapper()

    def test_apply_override_wins(self) -> None:
        """Override decision_power=10 always wins over any existing value."""
        current = StakeholderScores(
            decision_power=5, influence_level=5, relationship_strength=3
        )
        result = self.mapper.apply_override(current, {"decision_power": 10})
        assert result.decision_power == 10
        # Other fields unchanged
        assert result.influence_level == 5
        assert result.relationship_strength == 3

    def test_apply_override_clamps_high(self) -> None:
        """Override with value 15 clamps to 10."""
        current = StakeholderScores(
            decision_power=5, influence_level=5, relationship_strength=3
        )
        result = self.mapper.apply_override(current, {"decision_power": 15})
        assert result.decision_power == 10

    def test_apply_override_clamps_low(self) -> None:
        """Override with value -5 clamps to 0."""
        current = StakeholderScores(
            decision_power=5, influence_level=5, relationship_strength=3
        )
        result = self.mapper.apply_override(current, {"influence_level": -5})
        assert result.influence_level == 0

    def test_apply_override_multiple_fields(self) -> None:
        """Multiple overrides applied simultaneously."""
        current = StakeholderScores(
            decision_power=3, influence_level=3, relationship_strength=3
        )
        result = self.mapper.apply_override(
            current,
            {"decision_power": 8, "influence_level": 7, "relationship_strength": 9},
        )
        assert result.decision_power == 8
        assert result.influence_level == 7
        assert result.relationship_strength == 9

    def test_apply_override_ignores_unknown_fields(self) -> None:
        """Unknown field names are ignored (no error)."""
        current = StakeholderScores(
            decision_power=5, influence_level=5, relationship_strength=3
        )
        result = self.mapper.apply_override(current, {"unknown_field": 10})
        assert result.decision_power == 5
        assert result.influence_level == 5
        assert result.relationship_strength == 3

    def test_apply_override_can_decrease(self) -> None:
        """Human overrides CAN decrease scores (unlike conversation signals)."""
        current = StakeholderScores(
            decision_power=9, influence_level=8, relationship_strength=7
        )
        result = self.mapper.apply_override(current, {"decision_power": 3})
        assert result.decision_power == 3


# ── PlanManager Tests ─────────────────────────────────────────────────────────


class TestTrimList:
    """Tests for PlanManager._trim_list()."""

    def test_trim_list_under_limit(self) -> None:
        """List of 5 with max 10 -> unchanged."""
        items = [1, 2, 3, 4, 5]
        result = PlanManager._trim_list(items, 10)
        assert result == [1, 2, 3, 4, 5]

    def test_trim_list_at_limit(self) -> None:
        """List exactly at max -> unchanged."""
        items = list(range(20))
        result = PlanManager._trim_list(items, 20)
        assert result == list(range(20))

    def test_trim_list_over_limit(self) -> None:
        """List of 25 with max 20 -> last 20 items (most recent)."""
        items = list(range(25))
        result = PlanManager._trim_list(items, 20)
        assert len(result) == 20
        assert result == list(range(5, 25))  # Last 20

    def test_trim_list_empty(self) -> None:
        """Empty list -> empty list."""
        result = PlanManager._trim_list([], 10)
        assert result == []


class TestPlanManagerConstants:
    """Verify Pitfall 4 growth caps are set correctly."""

    def test_max_key_events(self) -> None:
        assert PlanManager.MAX_KEY_EVENTS == 50

    def test_max_interactions(self) -> None:
        assert PlanManager.MAX_INTERACTIONS == 20

    def test_max_action_items(self) -> None:
        assert PlanManager.MAX_ACTION_ITEMS == 30


def _make_conversation_state(**overrides) -> ConversationState:
    """Helper to build a ConversationState with sensible defaults."""
    defaults = {
        "state_id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "account_id": str(uuid.uuid4()),
        "contact_id": str(uuid.uuid4()),
        "contact_email": "test@example.com",
        "contact_name": "Test User",
        "deal_stage": DealStage.DISCOVERY,
        "interaction_count": 3,
        "last_interaction": datetime.now(timezone.utc),
        "confidence_score": 0.65,
    }
    defaults.update(overrides)
    return ConversationState(**defaults)


def _make_mock_repository() -> MagicMock:
    """Create a mock DealRepository for testing."""
    repo = MagicMock()
    repo.get_account_plan = AsyncMock(return_value=None)
    repo.upsert_account_plan = AsyncMock(return_value=1)
    repo.list_opportunities = AsyncMock(return_value=[])
    repo.get_opportunity_plan = AsyncMock(return_value=None)
    repo.upsert_opportunity_plan = AsyncMock(return_value=1)
    return repo


class TestCreateAccountPlan:
    """Tests for PlanManager.create_or_update_account_plan()."""

    @pytest.mark.asyncio
    async def test_create_account_plan_new(self) -> None:
        """No existing plan -> creates fresh plan with interaction summary."""
        repo = _make_mock_repository()
        manager = PlanManager(repo)
        state = _make_conversation_state()

        plan = await manager.create_or_update_account_plan(
            tenant_id=state.tenant_id,
            account_id=state.account_id,
            conversation_state=state,
            stakeholders=[],
        )

        assert isinstance(plan, AccountPlanData)
        assert len(plan.relationship_history.interaction_summaries) == 1
        repo.upsert_account_plan.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_account_plan_appends_interaction(self) -> None:
        """Existing plan gets new interaction summary appended."""
        existing_plan = AccountPlanData(
            relationship_history=RelationshipHistory(
                interaction_summaries=[
                    InteractionSummary(
                        date=datetime.now(timezone.utc),
                        channel="email",
                        summary="Previous interaction",
                    )
                ]
            )
        )
        repo = _make_mock_repository()
        repo.get_account_plan = AsyncMock(return_value=existing_plan)
        manager = PlanManager(repo)
        state = _make_conversation_state()

        plan = await manager.create_or_update_account_plan(
            tenant_id=state.tenant_id,
            account_id=state.account_id,
            conversation_state=state,
            stakeholders=[],
        )

        # Should now have 2 interaction summaries
        assert len(plan.relationship_history.interaction_summaries) == 2
        assert plan.relationship_history.interaction_summaries[0].summary == "Previous interaction"

    @pytest.mark.asyncio
    async def test_account_plan_caps_interactions(self) -> None:
        """Interaction summaries capped at MAX_INTERACTIONS."""
        existing_summaries = [
            InteractionSummary(
                date=datetime.now(timezone.utc),
                channel="email",
                summary=f"Interaction {i}",
            )
            for i in range(PlanManager.MAX_INTERACTIONS)
        ]
        existing_plan = AccountPlanData(
            relationship_history=RelationshipHistory(
                interaction_summaries=existing_summaries
            )
        )
        repo = _make_mock_repository()
        repo.get_account_plan = AsyncMock(return_value=existing_plan)
        manager = PlanManager(repo)
        state = _make_conversation_state()

        plan = await manager.create_or_update_account_plan(
            tenant_id=state.tenant_id,
            account_id=state.account_id,
            conversation_state=state,
            stakeholders=[],
        )

        # Should be capped at MAX_INTERACTIONS
        assert len(plan.relationship_history.interaction_summaries) == PlanManager.MAX_INTERACTIONS


class TestBuildInteractionSummary:
    """Tests for PlanManager._build_interaction_summary()."""

    def test_builds_summary_with_channel(self) -> None:
        """Summary includes channel, stage, qualification, and confidence."""
        from src.app.agents.sales.schemas import Channel

        state = _make_conversation_state(last_channel=Channel.EMAIL)
        manager = PlanManager(_make_mock_repository())
        summary = manager._build_interaction_summary(state)

        assert summary.channel == "email"
        assert "email" in summary.summary
        assert "discovery" in summary.summary.lower()

    def test_builds_summary_without_channel(self) -> None:
        """No channel -> 'unknown' in summary."""
        state = _make_conversation_state(last_channel=None)
        manager = PlanManager(_make_mock_repository())
        summary = manager._build_interaction_summary(state)

        assert summary.channel == "unknown"
