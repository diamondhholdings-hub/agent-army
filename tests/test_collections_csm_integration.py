"""Collections->CSM reverse handoff integration tests at the AGENT level.

Proves the Collections agent's cross-agent risk notification path:
- receive_collections_risk dispatches to csm_agent for RED and CRITICAL
- receive_collections_risk skips for GREEN and AMBER (verify call count == 0)
- receive_collections_risk fails gracefully when csm_agent=None
- _execute_task (execute()) post-checks rag after payment_risk_assessment and
  calls receive_collections_risk for RED/CRITICAL results
- _execute_task does NOT trigger notification for GREEN results
- CSMHealthScorer numerically verifies score reduction with CRITICAL collections_risk

All external dependencies (LLM, Gmail, Notion, Chat, EventBus) are mocked.
Real CSMHealthScorer is used (pure Python, deterministic).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.base import AgentCapability, AgentRegistration
from src.app.agents.collections.agent import CollectionsAgent
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
                name="payment_risk_assessment",
                description="Score payment risk deterministically",
            ),
        ],
    )


def _make_collections_agent(
    csm_agent: object | None = None,
    llm_service: object | None = None,
) -> CollectionsAgent:
    """Instantiate CollectionsAgent with all required services mocked."""
    reg = _make_col_registration()
    return CollectionsAgent(
        registration=reg,
        llm_service=llm_service or AsyncMock(),
        notion_collections=None,
        gmail_service=None,
        chat_service=None,
        event_bus=None,
        scorer=None,  # PaymentRiskScorer will be created inside handler
        csm_agent=csm_agent,
    )


def _make_healthy_signals(
    collections_risk: str | None = None,
) -> CSMHealthSignals:
    """Build CSMHealthSignals with healthy base values and optional collections_risk."""
    return CSMHealthSignals(
        feature_adoption_rate=1.0,
        usage_trend="growing",
        login_frequency_days=3,
        days_since_last_interaction=15,
        invoice_payment_status="current",
        open_ticket_count=0,
        avg_ticket_sentiment="positive",
        days_to_renewal=200,
        seats_utilization_rate=0.85,
        stakeholder_engagement="high",
        nps_score=10,
        escalation_count_90_days=0,
        collections_risk=collections_risk,
    )


# -- Test class ---------------------------------------------------------------


class TestReceiveCollectionsRisk:
    """Tests for CollectionsAgent.receive_collections_risk()."""

    @pytest.mark.asyncio
    async def test_receive_collections_risk_calls_csm_agent_red(self) -> None:
        """receive_collections_risk('acct1', 'RED') -> csm_agent.receive_collections_risk called."""
        mock_csm = AsyncMock()
        mock_csm.receive_collections_risk = AsyncMock()

        col_agent = _make_collections_agent(csm_agent=mock_csm)

        await col_agent.receive_collections_risk("acct1", "RED")

        mock_csm.receive_collections_risk.assert_called_once_with("acct1", "RED")

    @pytest.mark.asyncio
    async def test_receive_collections_risk_calls_csm_agent_critical(self) -> None:
        """receive_collections_risk('acct1', 'CRITICAL') -> csm_agent.receive_collections_risk called."""
        mock_csm = AsyncMock()
        mock_csm.receive_collections_risk = AsyncMock()

        col_agent = _make_collections_agent(csm_agent=mock_csm)

        await col_agent.receive_collections_risk("acct1", "CRITICAL")

        mock_csm.receive_collections_risk.assert_called_once_with("acct1", "CRITICAL")

    @pytest.mark.asyncio
    async def test_receive_collections_risk_skips_if_no_csm_agent(self) -> None:
        """receive_collections_risk with csm_agent=None -> no exception raised."""
        col_agent = _make_collections_agent(csm_agent=None)

        # Should not raise -- logs warning and returns gracefully
        await col_agent.receive_collections_risk("acct1", "RED")

    @pytest.mark.asyncio
    async def test_receive_collections_risk_green_amber_skipped(self) -> None:
        """GREEN and AMBER risk bands must NOT trigger csm_agent call (call count == 0)."""
        mock_csm = AsyncMock()
        mock_csm.receive_collections_risk = AsyncMock()

        col_agent = _make_collections_agent(csm_agent=mock_csm)

        # GREEN: should return immediately without calling csm_agent
        await col_agent.receive_collections_risk("acct1", "GREEN")
        # AMBER: should return immediately without calling csm_agent
        await col_agent.receive_collections_risk("acct1", "AMBER")

        assert mock_csm.receive_collections_risk.call_count == 0, (
            f"csm_agent must NOT be called for GREEN or AMBER risk bands. "
            f"Got {mock_csm.receive_collections_risk.call_count} calls."
        )

    @pytest.mark.asyncio
    async def test_receive_collections_risk_csm_agent_failure_is_swallowed(
        self,
    ) -> None:
        """csm_agent.receive_collections_risk raising exception -> swallowed gracefully."""
        mock_csm = AsyncMock()
        mock_csm.receive_collections_risk = AsyncMock(
            side_effect=Exception("CSM agent unavailable")
        )

        col_agent = _make_collections_agent(csm_agent=mock_csm)

        # Should not raise -- exception is caught internally
        await col_agent.receive_collections_risk("acct1", "RED")


class TestExecuteTaskPaymentRiskCSMIntegration:
    """Tests for CollectionsAgent.execute() post-check -> receive_collections_risk."""

    @pytest.mark.asyncio
    async def test_execute_task_payment_risk_red_triggers_csm_notification(
        self,
    ) -> None:
        """execute() with payment_risk_assessment returning RED rag -> csm_agent notified.

        Patches handle_payment_risk_assessment to return a RED result directly,
        then verifies that receive_collections_risk is called with the correct args.
        """
        mock_csm = AsyncMock()
        mock_csm.receive_collections_risk = AsyncMock()

        col_agent = _make_collections_agent(csm_agent=mock_csm)

        # Patch the handler to return a RED result
        mock_result = {
            "account_id": "acct-red-test",
            "rag": "RED",
            "score": 75.0,
            "should_escalate": True,
        }
        with patch(
            "src.app.agents.collections.handlers.handle_payment_risk_assessment",
            AsyncMock(return_value=mock_result),
        ):
            result = await col_agent.execute(
                {
                    "request_type": "payment_risk_assessment",
                    "account_id": "acct-red-test",
                    "days_overdue": 65,
                    "payment_history_streak": -5,
                    "total_outstanding_balance_usd": 8000.0,
                    "days_to_renewal": 90,
                },
                {"tenant_id": "t1"},
            )

        assert result["rag"] == "RED"
        mock_csm.receive_collections_risk.assert_called_once_with(
            "acct-red-test", "RED"
        )

    @pytest.mark.asyncio
    async def test_execute_task_payment_risk_critical_triggers_csm_notification(
        self,
    ) -> None:
        """execute() with payment_risk_assessment returning CRITICAL rag -> csm_agent notified."""
        mock_csm = AsyncMock()
        mock_csm.receive_collections_risk = AsyncMock()

        col_agent = _make_collections_agent(csm_agent=mock_csm)

        mock_result = {
            "account_id": "acct-critical-test",
            "rag": "CRITICAL",
            "score": 92.0,
            "should_escalate": True,
        }
        with patch(
            "src.app.agents.collections.handlers.handle_payment_risk_assessment",
            AsyncMock(return_value=mock_result),
        ):
            result = await col_agent.execute(
                {
                    "request_type": "payment_risk_assessment",
                    "account_id": "acct-critical-test",
                    "days_overdue": 150,
                    "payment_history_streak": -10,
                    "total_outstanding_balance_usd": 25000.0,
                    "days_to_renewal": 20,
                },
                {"tenant_id": "t1"},
            )

        assert result["rag"] == "CRITICAL"
        mock_csm.receive_collections_risk.assert_called_once_with(
            "acct-critical-test", "CRITICAL"
        )

    @pytest.mark.asyncio
    async def test_execute_task_payment_risk_green_no_csm_notification(
        self,
    ) -> None:
        """execute() with payment_risk_assessment returning GREEN rag -> csm_agent NOT notified."""
        mock_csm = AsyncMock()
        mock_csm.receive_collections_risk = AsyncMock()

        col_agent = _make_collections_agent(csm_agent=mock_csm)

        mock_result = {
            "account_id": "acct-green-test",
            "rag": "GREEN",
            "score": 10.0,
            "should_escalate": False,
        }
        with patch(
            "src.app.agents.collections.handlers.handle_payment_risk_assessment",
            AsyncMock(return_value=mock_result),
        ):
            result = await col_agent.execute(
                {
                    "request_type": "payment_risk_assessment",
                    "account_id": "acct-green-test",
                },
                {"tenant_id": "t1"},
            )

        assert result["rag"] == "GREEN"
        assert mock_csm.receive_collections_risk.call_count == 0, (
            "csm_agent must NOT be notified for GREEN payment risk result"
        )

    @pytest.mark.asyncio
    async def test_execute_task_payment_risk_with_error_no_csm_notification(
        self,
    ) -> None:
        """execute() with payment_risk_assessment returning error dict -> csm_agent NOT notified."""
        mock_csm = AsyncMock()
        mock_csm.receive_collections_risk = AsyncMock()

        col_agent = _make_collections_agent(csm_agent=mock_csm)

        # Error result: has 'error' key -> csm notification skipped even if rag is RED
        mock_result = {
            "error": "scorer failed",
            "confidence": "low",
            "partial": True,
        }
        with patch(
            "src.app.agents.collections.handlers.handle_payment_risk_assessment",
            AsyncMock(return_value=mock_result),
        ):
            result = await col_agent.execute(
                {
                    "request_type": "payment_risk_assessment",
                    "account_id": "acct-error-test",
                },
                {"tenant_id": "t1"},
            )

        assert "error" in result
        assert mock_csm.receive_collections_risk.call_count == 0, (
            "csm_agent must NOT be notified when result contains 'error' key"
        )


class TestCSMHealthScorerCollectionsRiskNumerical:
    """Numerical verification of CSMHealthScorer collections_risk cap integration."""

    def test_collections_risk_feeds_csm_health_score(self) -> None:
        """CRITICAL collections_risk reduces CSM health score by approximately 20%."""
        scorer = CSMHealthScorer()

        signals_no_risk = _make_healthy_signals(collections_risk=None)
        signals_critical = _make_healthy_signals(collections_risk="CRITICAL")

        score_no_risk = scorer.score(signals_no_risk, account_id="acct-norisk")
        score_critical = scorer.score(signals_critical, account_id="acct-critical")

        # Score with CRITICAL should be lower
        assert score_critical.score < score_no_risk.score, (
            "CRITICAL collections_risk must reduce CSM health score"
        )

        # Verify the reduction is approximately 20% (0.80x cap)
        reduction_pct = (
            (score_no_risk.score - score_critical.score) / score_no_risk.score
        )
        assert abs(reduction_pct - 0.20) < 0.01, (
            f"CRITICAL cap should reduce score by ~20%. "
            f"Got {reduction_pct:.3f} ({reduction_pct*100:.1f}%)"
        )

    def test_collections_risk_red_reduces_score_by_10_percent(self) -> None:
        """RED collections_risk reduces CSM health score by approximately 10%."""
        scorer = CSMHealthScorer()

        signals_no_risk = _make_healthy_signals(collections_risk=None)
        signals_red = _make_healthy_signals(collections_risk="RED")

        score_no_risk = scorer.score(signals_no_risk)
        score_red = scorer.score(signals_red)

        reduction_pct = (
            (score_no_risk.score - score_red.score) / score_no_risk.score
        )
        assert abs(reduction_pct - 0.10) < 0.01, (
            f"RED cap should reduce score by ~10%. "
            f"Got {reduction_pct:.3f} ({reduction_pct*100:.1f}%)"
        )
