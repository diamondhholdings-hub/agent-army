"""Integration tests for PostConversationHook lifecycle.

Uses mock/patch for OpportunityDetector, PoliticalMapper, PlanManager,
StageProgressionEngine to test hook orchestration without real LLM calls.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.sales.schemas import (
    BANTSignals,
    ConversationState,
    DealStage,
    MEDDICSignals,
    QualificationState,
)
from src.app.deals.hooks import HookResult, PostConversationHook
from src.app.deals.schemas import (
    AccountCreate,
    AccountRead,
    OpportunityCreate,
    OpportunityRead,
    OpportunitySignals,
    OpportunityUpdate,
    StakeholderRead,
    StakeholderScores,
)


# ── Test Fixtures ────────────────────────────────────────────────────────────


TENANT_ID = str(uuid.uuid4())
ACCOUNT_ID = str(uuid.uuid4())
OPP_ID = str(uuid.uuid4())


def _make_conversation_state(**overrides) -> ConversationState:
    """Create a ConversationState with sensible defaults."""
    defaults = {
        "state_id": str(uuid.uuid4()),
        "tenant_id": TENANT_ID,
        "account_id": ACCOUNT_ID,
        "contact_id": str(uuid.uuid4()),
        "contact_email": "alice@example.com",
        "contact_name": "Alice Johnson",
        "deal_stage": DealStage.DISCOVERY,
        "interaction_count": 3,
        "confidence_score": 0.7,
    }
    defaults.update(overrides)
    return ConversationState(**defaults)


def _make_account_read() -> AccountRead:
    """Create a test AccountRead."""
    return AccountRead(
        id=ACCOUNT_ID,
        tenant_id=TENANT_ID,
        account_name="Acme Corp",
        created_at=datetime.now(timezone.utc),
    )


def _make_opportunity_read(**overrides) -> OpportunityRead:
    """Create a test OpportunityRead."""
    defaults = {
        "id": OPP_ID,
        "tenant_id": TENANT_ID,
        "account_id": ACCOUNT_ID,
        "name": "Enterprise Deal",
        "deal_stage": "discovery",
        "detection_confidence": 0.85,
        "source": "agent_detected",
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return OpportunityRead(**defaults)


def _make_stakeholder_read() -> StakeholderRead:
    """Create a test StakeholderRead."""
    return StakeholderRead(
        id=str(uuid.uuid4()),
        account_id=ACCOUNT_ID,
        contact_name="Bob VP",
        title="VP Engineering",
        scores=StakeholderScores(
            decision_power=8, influence_level=7, relationship_strength=5
        ),
    )


def _make_hook(
    detector=None,
    mapper=None,
    plan_manager=None,
    progression=None,
    repo=None,
) -> PostConversationHook:
    """Create a PostConversationHook with mock dependencies."""
    return PostConversationHook(
        detector=detector or MagicMock(),
        political_mapper=mapper or MagicMock(),
        plan_manager=plan_manager or MagicMock(),
        progression_engine=progression or MagicMock(),
        repository=repo or MagicMock(),
    )


# ── Tests ────────────────────────────────────────────────────────────────────


class TestHookCreatesOpportunity:
    """Tests for opportunity creation above threshold."""

    @pytest.mark.asyncio
    async def test_hook_creates_opportunity_above_threshold(self) -> None:
        """Detector returns confidence=0.85 -> opportunity created."""
        repo = MagicMock()
        repo.get_account = AsyncMock(return_value=_make_account_read())
        repo.list_opportunities = AsyncMock(return_value=[])
        repo.list_stakeholders = AsyncMock(return_value=[])

        new_opp = _make_opportunity_read()
        repo.create_opportunity = AsyncMock(return_value=new_opp)

        detector = MagicMock()
        signals = OpportunitySignals(
            deal_potential_confidence=0.85,
            product_line="Platform",
            is_new_opportunity=True,
            estimated_value=50000.0,
        )
        detector.detect_signals = AsyncMock(return_value=signals)
        detector.should_create_opportunity = MagicMock(return_value=True)
        detector.should_update_opportunity = MagicMock(return_value=False)

        mapper = MagicMock()
        plan_manager = MagicMock()
        plan_manager.create_or_update_opportunity_plan = AsyncMock()
        plan_manager.create_or_update_account_plan = AsyncMock()

        progression = MagicMock()
        progression.evaluate_progression = MagicMock(return_value=None)

        hook = _make_hook(
            detector=detector,
            mapper=mapper,
            plan_manager=plan_manager,
            progression=progression,
            repo=repo,
        )

        state = _make_conversation_state()
        result = await hook.run(TENANT_ID, "We want to buy your platform", state)

        assert isinstance(result, HookResult)
        assert result.opportunities_created == 1
        repo.create_opportunity.assert_called_once()


class TestHookUpdatesOpportunity:
    """Tests for updating existing opportunity."""

    @pytest.mark.asyncio
    async def test_hook_updates_existing_opportunity(self) -> None:
        """Detector returns matching_opportunity_id -> opportunity updated."""
        existing_opp = _make_opportunity_read()
        repo = MagicMock()
        repo.get_account = AsyncMock(return_value=_make_account_read())
        repo.list_opportunities = AsyncMock(return_value=[existing_opp])
        repo.list_stakeholders = AsyncMock(return_value=[])
        repo.update_opportunity = AsyncMock(return_value=existing_opp)

        detector = MagicMock()
        signals = OpportunitySignals(
            deal_potential_confidence=0.75,
            product_line="Platform",
            is_new_opportunity=False,
            matching_opportunity_id=OPP_ID,
        )
        detector.detect_signals = AsyncMock(return_value=signals)
        detector.should_create_opportunity = MagicMock(return_value=False)
        detector.should_update_opportunity = MagicMock(return_value=True)

        plan_manager = MagicMock()
        plan_manager.create_or_update_account_plan = AsyncMock()
        plan_manager.create_or_update_opportunity_plan = AsyncMock()

        progression = MagicMock()
        progression.evaluate_progression = MagicMock(return_value=None)

        hook = _make_hook(
            detector=detector,
            plan_manager=plan_manager,
            progression=progression,
            repo=repo,
        )

        state = _make_conversation_state()
        result = await hook.run(TENANT_ID, "Still interested in platform", state)

        assert result.opportunities_updated == 1
        repo.update_opportunity.assert_called_once()


class TestHookBelowThreshold:
    """Tests for no action below threshold."""

    @pytest.mark.asyncio
    async def test_hook_no_opportunity_below_threshold(self) -> None:
        """Detector returns confidence=0.50 -> nothing created."""
        repo = MagicMock()
        repo.get_account = AsyncMock(return_value=_make_account_read())
        repo.list_opportunities = AsyncMock(return_value=[])
        repo.list_stakeholders = AsyncMock(return_value=[])

        detector = MagicMock()
        signals = OpportunitySignals(
            deal_potential_confidence=0.50,
            reasoning="Low confidence signal",
        )
        detector.detect_signals = AsyncMock(return_value=signals)
        detector.should_create_opportunity = MagicMock(return_value=False)
        detector.should_update_opportunity = MagicMock(return_value=False)

        plan_manager = MagicMock()
        plan_manager.create_or_update_account_plan = AsyncMock()
        plan_manager.create_or_update_opportunity_plan = AsyncMock()

        progression = MagicMock()
        progression.evaluate_progression = MagicMock(return_value=None)

        hook = _make_hook(
            detector=detector,
            plan_manager=plan_manager,
            progression=progression,
            repo=repo,
        )

        state = _make_conversation_state()
        result = await hook.run(TENANT_ID, "Just exploring options", state)

        assert result.opportunities_created == 0
        assert result.opportunities_updated == 0


class TestHookErrorDoesNotRaise:
    """Tests for fire-and-forget error handling."""

    @pytest.mark.asyncio
    async def test_hook_error_does_not_raise(self) -> None:
        """Detector raises exception -> HookResult still returned, error logged."""
        repo = MagicMock()
        repo.get_account = AsyncMock(return_value=_make_account_read())
        repo.list_opportunities = AsyncMock(
            side_effect=RuntimeError("Database connection lost")
        )
        repo.list_stakeholders = AsyncMock(return_value=[])

        detector = MagicMock()

        plan_manager = MagicMock()
        plan_manager.create_or_update_account_plan = AsyncMock()
        plan_manager.create_or_update_opportunity_plan = AsyncMock()

        progression = MagicMock()
        progression.evaluate_progression = MagicMock(return_value=None)

        hook = _make_hook(
            detector=detector,
            plan_manager=plan_manager,
            progression=progression,
            repo=repo,
        )

        state = _make_conversation_state()

        # Should NOT raise
        result = await hook.run(TENANT_ID, "test conversation", state)

        assert isinstance(result, HookResult)
        assert len(result.errors) > 0


class TestHookStageProgression:
    """Tests for stage progression application."""

    @pytest.mark.asyncio
    async def test_hook_stage_progression_applied(self) -> None:
        """Progression engine returns QUALIFICATION -> opportunity stage updated."""
        opp = _make_opportunity_read(deal_stage="discovery")
        repo = MagicMock()
        repo.get_account = AsyncMock(return_value=_make_account_read())
        repo.list_opportunities = AsyncMock(return_value=[opp])
        repo.list_stakeholders = AsyncMock(return_value=[])
        repo.update_opportunity = AsyncMock(return_value=opp)

        detector = MagicMock()
        signals = OpportunitySignals(deal_potential_confidence=0.50)
        detector.detect_signals = AsyncMock(return_value=signals)
        detector.should_create_opportunity = MagicMock(return_value=False)
        detector.should_update_opportunity = MagicMock(return_value=False)

        plan_manager = MagicMock()
        plan_manager.create_or_update_account_plan = AsyncMock()
        plan_manager.create_or_update_opportunity_plan = AsyncMock()

        progression = MagicMock()
        progression.evaluate_progression = MagicMock(
            return_value=DealStage.QUALIFICATION
        )

        hook = _make_hook(
            detector=detector,
            plan_manager=plan_manager,
            progression=progression,
            repo=repo,
        )

        state = _make_conversation_state(
            qualification=QualificationState(
                bant=BANTSignals(need_identified=True, budget_identified=True),
                meddic=MEDDICSignals(pain_identified=True),
            ),
            interaction_count=3,
        )
        result = await hook.run(TENANT_ID, "Budget is $100k, need is clear", state)

        assert len(result.stage_progressions) == 1
        assert "qualification" in result.stage_progressions[0].lower()


# ── Sales Endpoint Hook Wiring Tests ────────────────────────────────────────


class TestSendEmailFiresHook:
    """Verify POST /sales/send-email calls PostConversationHook."""

    @pytest.mark.asyncio
    async def test_send_email_fires_deal_hook(self) -> None:
        """send_email endpoint source contains _fire_deal_hook call."""
        import inspect
        from src.app.api.v1 import sales as sales_module

        src_code = inspect.getsource(sales_module.send_email)
        assert "_fire_deal_hook" in src_code, (
            "send_email endpoint must call _fire_deal_hook"
        )


class TestSendChatFiresHook:
    """Verify POST /sales/send-chat calls PostConversationHook."""

    @pytest.mark.asyncio
    async def test_send_chat_fires_deal_hook(self) -> None:
        """send_chat endpoint source contains _fire_deal_hook call."""
        import inspect
        from src.app.api.v1 import sales as sales_module

        src_code = inspect.getsource(sales_module.send_chat)
        assert "_fire_deal_hook" in src_code, (
            "send_chat endpoint must call _fire_deal_hook"
        )


class TestProcessReplyFiresHook:
    """Verify POST /sales/process-reply calls PostConversationHook."""

    @pytest.mark.asyncio
    async def test_process_reply_fires_deal_hook(self) -> None:
        """process_reply endpoint source contains _fire_deal_hook call."""
        import inspect
        from src.app.api.v1 import sales as sales_module

        src_code = inspect.getsource(sales_module.process_reply)
        assert "_fire_deal_hook" in src_code, (
            "process_reply endpoint must call _fire_deal_hook"
        )


class TestFireDealHookHelper:
    """Tests for the _fire_deal_hook helper function itself."""

    @pytest.mark.asyncio
    async def test_fire_deal_hook_calls_hook_run(self) -> None:
        """_fire_deal_hook invokes deal_hook.run() with correct args."""
        from src.app.api.v1.sales import _fire_deal_hook

        mock_request = MagicMock()
        mock_hook = MagicMock()
        mock_hook.run = AsyncMock(return_value=HookResult())
        mock_request.app.state.deal_hook = mock_hook

        state = _make_conversation_state()
        await _fire_deal_hook(mock_request, TENANT_ID, "test conversation", state)

        mock_hook.run.assert_called_once_with(
            tenant_id=TENANT_ID,
            conversation_text="test conversation",
            conversation_state=state,
        )

    @pytest.mark.asyncio
    async def test_fire_deal_hook_skips_when_no_hook(self) -> None:
        """_fire_deal_hook returns silently when deal_hook is None."""
        from src.app.api.v1.sales import _fire_deal_hook

        mock_request = MagicMock()
        mock_request.app.state.deal_hook = None

        state = _make_conversation_state()
        # Should NOT raise
        await _fire_deal_hook(mock_request, TENANT_ID, "test", state)

    @pytest.mark.asyncio
    async def test_fire_deal_hook_swallows_errors(self) -> None:
        """_fire_deal_hook catches exceptions from hook.run() and does not raise."""
        from src.app.api.v1.sales import _fire_deal_hook

        mock_request = MagicMock()
        mock_hook = MagicMock()
        mock_hook.run = AsyncMock(side_effect=RuntimeError("Database exploded"))
        mock_request.app.state.deal_hook = mock_hook

        state = _make_conversation_state()
        # Should NOT raise despite hook failure
        await _fire_deal_hook(mock_request, TENANT_ID, "test", state)

    @pytest.mark.asyncio
    async def test_fire_deal_hook_no_attr(self) -> None:
        """_fire_deal_hook handles missing deal_hook attribute gracefully."""
        from src.app.api.v1.sales import _fire_deal_hook

        mock_request = MagicMock()
        del mock_request.app.state.deal_hook  # Remove the attr

        state = _make_conversation_state()
        # getattr returns None -> should skip
        await _fire_deal_hook(mock_request, TENANT_ID, "test", state)
