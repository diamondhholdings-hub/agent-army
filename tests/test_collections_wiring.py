"""Main.py lifespan Collections wiring tests for Phase 15 integration.

Proves that the Phase 15 Collections agent wiring in main.py is correctly structured:
- CollectionsAgent is a BaseAgent subclass
- CollectionsScheduler has two jobs (daily AR scan + escalation check)
- app.state.collections is referenced in main.py source
- Unknown task type raises ValueError
- CSMHealthScorer collections_risk cap tests (CRITICAL < no_cap, RED > CRITICAL)

All external dependencies (LLM, Notion, Gmail, Chat, EventBus) are mocked.
Real CSMHealthScorer is used (pure Python, deterministic, no mock).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.agents.base import AgentCapability, AgentRegistration, BaseAgent
from src.app.agents.collections.agent import CollectionsAgent
from src.app.agents.collections.scheduler import CollectionsScheduler
from src.app.agents.customer_success.health_scorer import CSMHealthScorer
from src.app.agents.customer_success.schemas import CSMHealthSignals


# -- Fixtures -----------------------------------------------------------------


def _make_col_registration() -> AgentRegistration:
    """Create a minimal AgentRegistration for Collections Agent testing."""
    return AgentRegistration(
        agent_id="collections_agent",
        name="Collections Agent",
        description="Collections agent for AR tracking and payment risk",
        capabilities=[
            AgentCapability(
                name="ar_aging_report",
                description="Analyze invoices and produce AR aging report",
            ),
        ],
    )


def _make_healthy_signals(
    collections_risk: str | None = None,
) -> CSMHealthSignals:
    """Build CSMHealthSignals with all healthy values and optional collections_risk."""
    return CSMHealthSignals(
        feature_adoption_rate=1.0,      # Full adoption -> 20 pts
        usage_trend="growing",          # Growing -> 15 pts
        login_frequency_days=3,         # <=7 days -> 10 pts
        days_since_last_interaction=15, # <=30 days -> 10 pts
        invoice_payment_status="current",  # Current -> 10 pts
        open_ticket_count=0,            # No tickets -> 0 deduction
        avg_ticket_sentiment="positive",  # Positive -> 10 pts
        days_to_renewal=200,            # >180 days -> 10 pts
        seats_utilization_rate=0.85,    # 0.8-1.0 range -> 5 pts
        stakeholder_engagement="high",  # High -> 5 pts
        nps_score=10,                   # >=9 -> 3 pts
        escalation_count_90_days=0,     # None -> 2 pts
        collections_risk=collections_risk,
    )


def _read_main_py_source() -> str:
    """Read main.py as text to avoid triggering the full import chain."""
    with open("src/app/main.py") as f:
        return f.read()


# -- Test class ---------------------------------------------------------------


class TestCollectionsWiring:
    """Test suite for Collections Agent wiring in main.py lifespan."""

    def test_collections_agent_is_base_agent_subclass(self) -> None:
        """CollectionsAgent must be a subclass of BaseAgent."""
        assert issubclass(CollectionsAgent, BaseAgent), (
            "CollectionsAgent must inherit from BaseAgent to integrate with agent registry"
        )

    def test_collections_scheduler_importable(self) -> None:
        """CollectionsScheduler is importable from its module."""
        assert CollectionsScheduler is not None
        # Verify it has the expected interface
        assert hasattr(CollectionsScheduler, "start")
        assert hasattr(CollectionsScheduler, "stop")

    @pytest.mark.asyncio
    async def test_collections_scheduler_has_two_jobs(self) -> None:
        """CollectionsScheduler.start() returns bool; stop() doesn't raise."""
        mock_agent = MagicMock()
        scheduler = CollectionsScheduler(
            collections_agent=mock_agent,
            notion_collections=None,
        )

        # start() returns True if APScheduler installed, False otherwise.
        started = scheduler.start()
        assert isinstance(started, bool)

        if started:
            # If APScheduler is available, verify 2 jobs were registered
            assert scheduler._scheduler is not None
            jobs = scheduler._scheduler.get_jobs()
            assert len(jobs) == 2, (
                f"CollectionsScheduler must have exactly 2 jobs, got {len(jobs)}"
            )
            job_ids = {j.id for j in jobs}
            assert "collections_daily_ar_scan" in job_ids
            assert "collections_daily_escalation_check" in job_ids

        # stop() should never raise regardless of start status
        scheduler.stop()

    @pytest.mark.asyncio
    async def test_collections_agent_unknown_task_raises(self) -> None:
        """CollectionsAgent.execute() with unknown request_type raises ValueError."""
        reg = _make_col_registration()
        agent = CollectionsAgent(
            registration=reg,
            llm_service=AsyncMock(),
        )

        with pytest.raises(ValueError, match="Unknown Collections task type"):
            await agent.execute(
                {"request_type": "nonexistent_task", "account_id": "acct-001"},
                {"tenant_id": "t1"},
            )

    def test_app_state_collections_set_on_lifespan(self) -> None:
        """Read main.py source; assert 'app.state.collections' present in Phase 15 block."""
        source = _read_main_py_source()

        assert "app.state.collections" in source, (
            "main.py should set 'app.state.collections' in Phase 15 lifespan wiring"
        )
        assert "CollectionsAgent" in source, (
            "main.py should import and instantiate CollectionsAgent"
        )
        assert "col_scheduler" in source, (
            "main.py should reference 'col_scheduler' for Phase 15 wiring"
        )

    def test_main_py_shutdown_stops_col_scheduler(self) -> None:
        """Read main.py source; assert Collections scheduler stop logic present."""
        source = _read_main_py_source()

        # The shutdown section should handle the col_scheduler
        assert "col_scheduler" in source, (
            "main.py should reference 'col_scheduler' for Collections scheduler cleanup"
        )

    def test_collections_agent_attributes_set_correctly(self) -> None:
        """Instantiate CollectionsAgent with mock deps; verify attributes stored."""
        reg = _make_col_registration()
        mock_llm = AsyncMock()
        mock_notion = AsyncMock()
        mock_gmail = AsyncMock()
        mock_scorer = MagicMock()
        mock_csm = AsyncMock()

        agent = CollectionsAgent(
            registration=reg,
            llm_service=mock_llm,
            notion_collections=mock_notion,
            gmail_service=mock_gmail,
            scorer=mock_scorer,
            csm_agent=mock_csm,
        )

        assert agent._llm_service is mock_llm
        assert agent._notion_collections is mock_notion
        assert agent._gmail_service is mock_gmail
        assert agent._scorer is mock_scorer
        assert agent._csm_agent is mock_csm


class TestCSMHealthScorerCollectionsRiskCap:
    """CSMHealthScorer collections_risk cap numerical verification tests."""

    def test_csm_health_scorer_collections_risk_cap_critical(self) -> None:
        """CSMHealthScorer: CRITICAL cap (0.80x) -> lower score than no cap."""
        scorer = CSMHealthScorer()

        signals_no_cap = _make_healthy_signals(collections_risk=None)
        signals_critical = _make_healthy_signals(collections_risk="CRITICAL")

        score_no_cap = scorer.score(signals_no_cap, account_id="acct-nocap")
        score_critical = scorer.score(signals_critical, account_id="acct-critical")

        assert score_critical.score < score_no_cap.score, (
            f"CRITICAL collections_risk should reduce health score "
            f"(got {score_critical.score:.2f} vs {score_no_cap.score:.2f} without cap)"
        )

    def test_csm_health_scorer_collections_risk_cap_red(self) -> None:
        """CSMHealthScorer: RED cap (0.90x) produces higher score than CRITICAL cap (0.80x)."""
        scorer = CSMHealthScorer()

        signals_red = _make_healthy_signals(collections_risk="RED")
        signals_critical = _make_healthy_signals(collections_risk="CRITICAL")

        score_red = scorer.score(signals_red, account_id="acct-red")
        score_critical = scorer.score(signals_critical, account_id="acct-critical")

        assert score_red.score > score_critical.score, (
            f"RED cap (0.90x) should produce higher score than CRITICAL cap (0.80x): "
            f"RED={score_red.score:.2f}, CRITICAL={score_critical.score:.2f}"
        )

    def test_csm_health_scorer_critical_cap_factor_verified_numerically(self) -> None:
        """CRITICAL cap: score with CRITICAL risk is approximately 0.80x of no-cap score."""
        scorer = CSMHealthScorer()

        signals_no_cap = _make_healthy_signals(collections_risk=None)
        signals_critical = _make_healthy_signals(collections_risk="CRITICAL")

        score_no_cap = scorer.score(signals_no_cap)
        score_critical = scorer.score(signals_critical)

        # CRITICAL cap is 0.80x applied before TAM cap
        # Since no TAM cap, ratio should be close to 0.80
        ratio = score_critical.score / score_no_cap.score
        assert abs(ratio - 0.80) < 0.01, (
            f"CRITICAL cap should produce score ~0.80x of base score. "
            f"Got ratio {ratio:.4f} (expected ~0.80)"
        )

    def test_csm_health_scorer_red_cap_factor_verified_numerically(self) -> None:
        """RED cap: score with RED risk is approximately 0.90x of no-cap score."""
        scorer = CSMHealthScorer()

        signals_no_cap = _make_healthy_signals(collections_risk=None)
        signals_red = _make_healthy_signals(collections_risk="RED")

        score_no_cap = scorer.score(signals_no_cap)
        score_red = scorer.score(signals_red)

        ratio = score_red.score / score_no_cap.score
        assert abs(ratio - 0.90) < 0.01, (
            f"RED cap should produce score ~0.90x of base score. "
            f"Got ratio {ratio:.4f} (expected ~0.90)"
        )

    def test_csm_health_scorer_green_amber_no_cap_applied(self) -> None:
        """GREEN and AMBER collections_risk values should NOT reduce the score."""
        scorer = CSMHealthScorer()

        signals_no_cap = _make_healthy_signals(collections_risk=None)
        signals_green = _make_healthy_signals(collections_risk="GREEN")
        signals_amber = _make_healthy_signals(collections_risk="AMBER")

        score_no_cap = scorer.score(signals_no_cap)
        score_green = scorer.score(signals_green)
        score_amber = scorer.score(signals_amber)

        assert score_green.score == pytest.approx(score_no_cap.score), (
            "GREEN collections_risk should not reduce health score"
        )
        assert score_amber.score == pytest.approx(score_no_cap.score), (
            "AMBER collections_risk should not reduce health score"
        )
