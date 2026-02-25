"""Deterministic scoring tests for CSMHealthScorer.

Verifies the 11-signal weighted health scoring algorithm, TAM correlation cap,
RAG derivation thresholds, and churn risk assessment with contract proximity
and behavioral triggers. Uses the real CSMHealthScorer (no mocking) since
scoring is pure deterministic Python.

Covers:
    - Healthy account -> GREEN
    - At-risk account -> RED
    - TAM RED cap reduces score to at most 0.85x
    - TAM AMBER cap reduces score to at most 0.95x but higher than RED cap
    - Contract proximity churn trigger fires when rag in RED/AMBER and days_to_renewal <= 60
    - Behavioral churn trigger fires when usage_trend=declining regardless of renewal date
    - Both triggers combined -> churn_risk_level=critical, churn_triggered_by=both
    - Healthy GREEN account -> churn_risk_level=low
"""

from __future__ import annotations

import pytest

from src.app.agents.customer_success.health_scorer import CSMHealthScorer
from src.app.agents.customer_success.schemas import CSMHealthSignals


# -- Fixtures ----------------------------------------------------------------


def _healthy_signals() -> CSMHealthSignals:
    """Healthy account: high adoption, growing, current payment, engaged."""
    return CSMHealthSignals(
        feature_adoption_rate=0.9,
        usage_trend="growing",
        login_frequency_days=5,
        days_since_last_interaction=10,
        stakeholder_engagement="high",
        nps_score=9,
        invoice_payment_status="current",
        days_to_renewal=200,
        seats_utilization_rate=0.85,
        open_ticket_count=0,
        avg_ticket_sentiment="positive",
        escalation_count_90_days=0,
        tam_health_rag=None,
    )


def _atrisk_signals() -> CSMHealthSignals:
    """At-risk account: low adoption, declining, overdue 90+, disengaged."""
    return CSMHealthSignals(
        feature_adoption_rate=0.1,
        usage_trend="declining",
        login_frequency_days=90,
        days_since_last_interaction=120,
        stakeholder_engagement="low",
        nps_score=2,
        invoice_payment_status="overdue_90_plus",
        days_to_renewal=30,
        seats_utilization_rate=0.3,
        open_ticket_count=5,
        avg_ticket_sentiment="negative",
        escalation_count_90_days=3,
        tam_health_rag=None,
    )


# -- Test Class: CSMHealthScorer Scoring ------------------------------------


class TestCSMHealthScorer:
    """Deterministic scoring tests for CSMHealthScorer."""

    def test_healthy_account_is_green(self) -> None:
        """Healthy account with high adoption, growing usage, current payment -> GREEN."""
        scorer = CSMHealthScorer()
        signals = _healthy_signals()
        result = scorer.score(signals, account_id="acc-healthy")

        assert result.rag == "GREEN"
        assert result.score >= 70.0
        assert result.account_id == "acc-healthy"

    def test_atrisk_account_is_red(self) -> None:
        """At-risk account with low adoption, declining, overdue 90+ -> RED."""
        scorer = CSMHealthScorer()
        signals = _atrisk_signals()
        result = scorer.score(signals, account_id="acc-atrisk")

        assert result.rag == "RED"
        assert result.score < 40.0
        assert result.account_id == "acc-atrisk"

    def test_tam_red_cap_reduces_score(self) -> None:
        """TAM RED correlation cap reduces healthy score to at most 0.85x raw."""
        scorer = CSMHealthScorer()

        # Score without TAM cap
        signals_no_cap = _healthy_signals()
        result_no_cap = scorer.score(signals_no_cap, account_id="no-cap")

        # Score with TAM RED cap
        signals_red_cap = _healthy_signals()
        signals_red_cap.tam_health_rag = "RED"
        # Need to reconstruct since tam_health_rag may be frozen; use model_copy
        signals_red = _healthy_signals().model_copy(
            update={"tam_health_rag": "RED"}
        )
        result_red = scorer.score(signals_red, account_id="red-cap")

        # Score with RED cap should be lower
        assert result_red.score < result_no_cap.score
        # Specifically, should be at most 85% of uncapped
        assert result_red.score <= result_no_cap.score * 0.85 + 0.01  # tolerance

    def test_tam_amber_cap_reduces_score_less_than_red(self) -> None:
        """TAM AMBER cap (0.95x) is less severe than RED cap (0.85x)."""
        scorer = CSMHealthScorer()

        signals_amber = _healthy_signals().model_copy(
            update={"tam_health_rag": "AMBER"}
        )
        signals_red = _healthy_signals().model_copy(
            update={"tam_health_rag": "RED"}
        )
        signals_none = _healthy_signals()

        result_amber = scorer.score(signals_amber, account_id="amber-cap")
        result_red = scorer.score(signals_red, account_id="red-cap")
        result_none = scorer.score(signals_none, account_id="no-cap")

        # AMBER cap less severe than RED cap
        assert result_amber.score > result_red.score
        # AMBER cap still lower than no cap
        assert result_amber.score < result_none.score

    def test_contract_proximity_churn_trigger(self) -> None:
        """Contract proximity trigger fires when rag=RED and days_to_renewal <= 60."""
        scorer = CSMHealthScorer()
        # Build an at-risk account with imminent renewal
        signals = _atrisk_signals().model_copy(
            update={"days_to_renewal": 45, "usage_trend": "stable", "login_frequency_days": 5}
        )
        result = scorer.score(signals, account_id="contract-churn")

        # Should be RED or AMBER (low signals), triggering contract proximity
        assert result.rag in ("RED", "AMBER")
        assert result.churn_triggered_by is not None
        # Contract proximity should be a trigger
        assert result.churn_triggered_by in ("contract_proximity", "both")

    def test_behavioral_churn_trigger(self) -> None:
        """Behavioral trigger fires when usage_trend=declining and login_frequency > 30."""
        scorer = CSMHealthScorer()
        # Account with declining usage and infrequent login, but far from renewal
        signals = _healthy_signals().model_copy(
            update={
                "usage_trend": "declining",
                "login_frequency_days": 60,
                "days_to_renewal": 365,
            }
        )
        result = scorer.score(signals, account_id="behavioral-churn")

        assert result.churn_triggered_by is not None
        assert result.churn_triggered_by in ("behavioral", "both")

    def test_both_churn_triggers_critical(self) -> None:
        """Both triggers combined -> churn_triggered_by=both, churn_risk_level=critical."""
        scorer = CSMHealthScorer()
        # At-risk: low scores (will be RED/AMBER), near renewal, declining usage
        signals = _atrisk_signals().model_copy(
            update={"days_to_renewal": 30, "usage_trend": "declining"}
        )
        result = scorer.score(signals, account_id="both-churn")

        assert result.rag in ("RED", "AMBER")
        assert result.churn_triggered_by == "both"
        assert result.churn_risk_level == "critical"

    def test_healthy_green_low_churn(self) -> None:
        """Healthy GREEN account -> churn_risk_level=low."""
        scorer = CSMHealthScorer()
        signals = _healthy_signals()
        result = scorer.score(signals, account_id="healthy-low-churn")

        assert result.rag == "GREEN"
        assert result.churn_risk_level == "low"
        assert result.churn_triggered_by is None

    def test_score_bounded_0_to_100(self) -> None:
        """Score is always in [0, 100] range."""
        scorer = CSMHealthScorer()

        # Test with healthy signals
        result_high = scorer.score(_healthy_signals(), account_id="bounded-high")
        assert 0.0 <= result_high.score <= 100.0

        # Test with at-risk signals
        result_low = scorer.score(_atrisk_signals(), account_id="bounded-low")
        assert 0.0 <= result_low.score <= 100.0

    def test_signal_breakdown_has_all_signals(self) -> None:
        """Signal breakdown dict contains all 11 signal keys."""
        scorer = CSMHealthScorer()
        result = scorer.score(_healthy_signals(), account_id="breakdown")

        expected_keys = {
            "feature_adoption_rate",
            "usage_trend",
            "login_frequency_days",
            "days_since_last_interaction",
            "invoice_payment_status",
            "support",
            "days_to_renewal",
            "seats_utilization_rate",
            "stakeholder_engagement",
            "nps_score",
            "escalation_count_90_days",
        }
        assert set(result.signal_breakdown.keys()) == expected_keys

    def test_custom_thresholds(self) -> None:
        """Custom thresholds change RAG derivation boundaries."""
        # With higher green_threshold, a previously GREEN account may become AMBER
        scorer_strict = CSMHealthScorer(green_threshold=95.0, amber_threshold=70.0)
        signals = _healthy_signals()
        result = scorer_strict.score(signals, account_id="strict-threshold")

        # The healthy account scores high but likely below 95
        # Should be AMBER instead of GREEN with stricter threshold
        assert result.rag in ("GREEN", "AMBER")
        # If score < 95 it would be AMBER
        if result.score < 95.0:
            assert result.rag == "AMBER"
