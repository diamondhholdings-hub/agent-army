"""Deterministic scoring tests for PaymentRiskScorer and compute_tone_modifier.

Verifies the 4-signal weighted payment risk scoring algorithm, RAG derivation
thresholds, escalation flag auto-computation, score_breakdown dict structure,
and tone modifier calibration. Uses the real PaymentRiskScorer (no mocking)
since scoring is pure deterministic Python — same pattern as CSMHealthScorer
tests.

Score direction: higher = MORE RISK (inverted from CSM health scorer where
higher = healthier).

Covers:
    - Clean account (0 overdue, great history, small balance, far renewal) -> GREEN, no escalate
    - Slightly late account (30d, neutral streak, small balance, 60d renewal) -> AMBER, no escalate (score=37 < 60)
    - Serious delinquent (90d, 3 consecutive late, mid balance, 14d renewal) -> RED, escalate
    - Critical account (120d+, chronic late, large balance, 5d renewal) -> CRITICAL, escalate
    - High ARR clean (60d, streak=6, tiny balance, 100d renewal) -> GREEN (score=28), no escalate
    - RAG boundary: score exactly 29 -> GREEN, score exactly 30 -> AMBER
    - RAG boundary: score exactly 59 -> AMBER, score exactly 60 -> RED (should_escalate=True)
    - RAG boundary: score exactly 84 -> RED, score exactly 85 -> CRITICAL
    - score_breakdown dict populated with 4 expected keys
    - score bounded [0, 100]
    - STAGE_TIME_FLOORS exported as dict with 4 stage keys
    - compute_tone_modifier: enterprise softening
    - compute_tone_modifier: mid-market discount
    - compute_tone_modifier: SMB chronic late hardening
    - compute_tone_modifier: combined modifiers (no extreme clamp)
    - compute_tone_modifier: default (no modifiers)
    - compute_tone_modifier result always in [0.6, 1.4]
"""

from __future__ import annotations

import pytest

from src.app.agents.collections.scorer import (
    STAGE_TIME_FLOORS,
    PaymentRiskScorer,
    compute_tone_modifier,
)
from src.app.agents.collections.schemas import PaymentRiskSignals


# -- Helpers / Fixtures -------------------------------------------------------


def _signals(
    *,
    account_id: str = "acc-test",
    days_overdue: int = 0,
    streak: int = 12,
    balance: float = 0.0,
    days_to_renewal: int = 120,
    arr_usd: float = 0.0,
    tenure_years: float = 0.0,
) -> PaymentRiskSignals:
    """Build a PaymentRiskSignals with keyword-only convenience args."""
    return PaymentRiskSignals(
        account_id=account_id,
        days_overdue=days_overdue,
        payment_history_streak=streak,
        total_outstanding_balance_usd=balance,
        days_to_renewal=days_to_renewal,
        arr_usd=arr_usd,
        tenure_years=tenure_years,
    )


# -- Test Class: PaymentRiskScorer Scoring ------------------------------------


class TestPaymentRiskScorer:
    """Deterministic scoring tests for PaymentRiskScorer."""

    def test_clean_account_is_green_no_escalate(self) -> None:
        """Clean: 0d overdue, streak=12, $500, 120d renewal -> score=0, GREEN, no escalate."""
        scorer = PaymentRiskScorer()
        signals = _signals(
            account_id="acc-clean",
            days_overdue=0,
            streak=12,
            balance=500.0,
            days_to_renewal=120,
        )
        result = scorer.score(signals)

        assert result.account_id == "acc-clean"
        assert result.score == 0.0
        assert result.rag == "GREEN"
        assert result.should_escalate is False

    def test_slightly_late_is_amber_no_escalate(self) -> None:
        """Slightly late: 30d, streak=0, $5k, 60d renewal -> score=37, AMBER, no escalate.

        AMBER (score 30-59) does NOT trigger should_escalate.
        Escalation threshold is score >= 60. Score=37 is AMBER but below escalation threshold.
        """
        scorer = PaymentRiskScorer()
        signals = _signals(
            account_id="acc-late",
            days_overdue=30,
            streak=0,
            balance=5_000.0,
            days_to_renewal=60,
        )
        result = scorer.score(signals)

        # 12 + 12 + 8 + 5 = 37
        assert result.score == 37.0
        assert result.rag == "AMBER"
        assert result.should_escalate is False  # score < 60, escalation starts at 60

    def test_serious_delinquent_is_red(self) -> None:
        """Serious: 90d, streak=-3, $25k, 14d renewal -> score=79, RED, escalate."""
        scorer = PaymentRiskScorer()
        signals = _signals(
            account_id="acc-serious",
            days_overdue=90,
            streak=-3,
            balance=25_000.0,
            days_to_renewal=14,
        )
        result = scorer.score(signals)

        # 35 + 20 + 14 + 10 = 79
        assert result.score == 79.0
        assert result.rag == "RED"
        assert result.should_escalate is True

    def test_critical_account_is_critical(self) -> None:
        """Critical: 120d+, streak=-6, $75k, 5d renewal -> score=100, CRITICAL, escalate."""
        scorer = PaymentRiskScorer()
        signals = _signals(
            account_id="acc-critical",
            days_overdue=125,
            streak=-6,
            balance=75_000.0,
            days_to_renewal=5,
        )
        result = scorer.score(signals)

        # 40 + 25 + 20 + 15 = 100
        assert result.score == 100.0
        assert result.rag == "CRITICAL"
        assert result.should_escalate is True

    def test_high_arr_clean_is_green_score_28(self) -> None:
        """High ARR, mostly clean: 60d, streak=6, $500, 100d renewal -> score=28, GREEN."""
        scorer = PaymentRiskScorer()
        signals = _signals(
            account_id="acc-high-arr",
            days_overdue=60,
            streak=6,
            balance=500.0,
            days_to_renewal=100,
            arr_usd=600_000.0,
        )
        result = scorer.score(signals)

        # 25 + 3 + 0 + 0 = 28 (arr_usd doesn't affect risk score)
        assert result.score == 28.0
        assert result.rag == "GREEN"
        assert result.should_escalate is False

    # -- RAG Boundary Tests ---------------------------------------------------

    def test_score_29_is_green(self) -> None:
        """Score 29 -> GREEN (< 30 threshold)."""
        scorer = PaymentRiskScorer()
        # 25 (days_overdue=60) + 0 (streak=12) + 0 (bal<1k) + 0 (renewal>90) = 25 -> not 29
        # 25 (days_overdue=60) + 3 (streak=6) + 0 (bal<1k) + 0 (renewal>90d) = 28
        # Need 29: 12 (30d) + 12 (streak=0) + 0 (bal<1k) + 5 (31-90d renewal) = 29
        signals = _signals(
            days_overdue=30,
            streak=0,
            balance=500.0,
            days_to_renewal=50,
        )
        result = scorer.score(signals)

        assert result.score == 29.0
        assert result.rag == "GREEN"

    def test_score_30_is_amber(self) -> None:
        """Score 30 -> AMBER (>= 30, < 60 threshold)."""
        scorer = PaymentRiskScorer()
        # 12 (30d) + 12 (streak=0) + 8 (1-9999) + 0 (>90d) = 32 ... need exact 30
        # 12 (30d) + 0 (streak=12) + 8 ($5k) + 0 (renewal >90) = 20, not 30
        # 12 (30d) + 3 (streak=6) + 8 ($5k) + 0 (renewal >90d) = 23
        # 12 (30d) + 8 (streak=1) + 0 (<$1k) + 0 (>90d) = 20
        # 25 (60d) + 0 (streak=12) + 0 (<1k) + 5 (31-90d) = 30 ✓
        signals = _signals(
            days_overdue=60,
            streak=12,
            balance=500.0,
            days_to_renewal=60,
        )
        result = scorer.score(signals)

        assert result.score == 30.0
        assert result.rag == "AMBER"

    def test_score_59_is_amber(self) -> None:
        """Score 59 -> AMBER (< 60 threshold, no escalate)."""
        scorer = PaymentRiskScorer()
        # 35 (90d) + 0 (streak=12) + 14 ($25k) + 0 (>90d renewal) = 49 -> not 59
        # 35 (90d) + 15 (streak=-1, -2) + 0 (<1k) + 0 (>90d) = 50 ... streak=-2 -> 15
        # 35 (90d) + 8 (streak=1) + 8 ($5k) + 5 (31-90d) = 56 - not 59
        # 35 (90d) + 15 (streak=-2) + 0 (bal<1k) + 5 (31-90d) = 55
        # 35 (90d) + 15 (streak=-2) + 8 ($5k) + 0 (>90d renewal) = 58
        # 35 (90d) + 15 (streak=-2) + 8 ($5k) + 5 (31-90d) = 63 too high
        # 35 (90d) + 0 (streak=12) + 8 ($5k) + 5 (31-90d) = 48
        # 35 (90d) + 8 (streak=1) + 8 ($5k) + 5 (31-90d) = 56
        # 35 (90d) + 20 (streak=-3..-5) + 0 (<$1k) + 0 (>90d) = 55
        # 35 (90d) + 3 (streak=6) + 8 ($5k) + 10 (8-30d) = 56
        # 35 (90d) + 12 (streak=0) + 0 (<1k) + 5 (31-90d) = 52
        # 25 (60d) + 20 (streak=-3..-5) + 8 ($5k) + 5 (31-90d) = 58
        # 25 (60d) + 20 (streak=-3..-5) + 8 ($5k) + 5 (31-90d) = 58
        # 35 (90d) + 12 (streak=0) + 7... -> can't get to exactly 59 easily
        # Let's use: 25 (60d) + 25 (streak<=-6) + 0 (<1k) + 0 (>90d) = 50
        # 35 (90d) + 15 (streak=-2) + 8 ($5k) + 0 (>90d renewal) = 58
        # 35 (90d) + 20 (streak=-3..-5) + 0 (<$1k) + 0 (>90d) = 55
        # Need 59: 35 + 0 + 14 + 10 = 59 -> streak=12, $25k, 8-30d renewal
        signals = _signals(
            days_overdue=90,
            streak=12,
            balance=25_000.0,
            days_to_renewal=20,
        )
        result = scorer.score(signals)

        assert result.score == 59.0
        assert result.rag == "AMBER"
        assert result.should_escalate is False

    def test_score_60_is_red_and_escalates(self) -> None:
        """Score 60 -> RED (>= 60 threshold), should_escalate=True."""
        scorer = PaymentRiskScorer()
        # 35 (90d) + 0 (streak=12) + 14 ($25k) + 10 (8-30d) + 1 more needed
        # 35 (90d) + 8 (streak=1) + 14 ($25k) + 0 (>90d renewal) = 57 -- not 60
        # 35 (90d) + 12 (streak=0) + 8 ($5k) + 5 (31-90d) = 60 ✓
        signals = _signals(
            days_overdue=90,
            streak=0,
            balance=5_000.0,
            days_to_renewal=60,
        )
        result = scorer.score(signals)

        assert result.score == 60.0
        assert result.rag == "RED"
        assert result.should_escalate is True

    def test_score_84_is_red(self) -> None:
        """Score 84 -> RED (< 85 threshold)."""
        scorer = PaymentRiskScorer()
        # 40 (120d) + 25 (streak<=-6) + 14 ($25k) + 0 (>90d) = 79
        # 40 + 25 + 14 + 5 = 84 -> 31-90d renewal
        signals = _signals(
            days_overdue=120,
            streak=-6,
            balance=25_000.0,
            days_to_renewal=60,
        )
        result = scorer.score(signals)

        assert result.score == 84.0
        assert result.rag == "RED"
        assert result.should_escalate is True

    def test_score_85_is_critical(self) -> None:
        """Score 85 -> CRITICAL (>= 85 threshold)."""
        scorer = PaymentRiskScorer()
        # 40 + 25 + 14 + 0 = 79 -- not 85
        # 40 + 25 + 14 + 10 = 89 -- CRITICAL ✓ (8-30d renewal)
        # Need exactly 85: 40 + 25 + 20 + 0 = 85 -> $50k+ balance, >90d renewal
        signals = _signals(
            days_overdue=120,
            streak=-6,
            balance=50_000.0,
            days_to_renewal=100,
        )
        result = scorer.score(signals)

        assert result.score == 85.0
        assert result.rag == "CRITICAL"
        assert result.should_escalate is True

    # -- Score Breakdown Tests -------------------------------------------------

    def test_score_breakdown_has_four_keys(self) -> None:
        """score_breakdown dict has 4 expected dimension keys."""
        scorer = PaymentRiskScorer()
        signals = _signals(days_overdue=30, streak=0, balance=5_000.0, days_to_renewal=60)
        result = scorer.score(signals)

        expected_keys = {
            "days_overdue",
            "payment_history_streak",
            "total_outstanding_balance_usd",
            "days_to_renewal",
        }
        assert set(result.score_breakdown.keys()) == expected_keys

    def test_score_breakdown_values_sum_to_score(self) -> None:
        """Sum of score_breakdown values equals the total score."""
        scorer = PaymentRiskScorer()
        signals = _signals(days_overdue=90, streak=-3, balance=25_000.0, days_to_renewal=14)
        result = scorer.score(signals)

        breakdown_total = sum(result.score_breakdown.values())
        assert breakdown_total == pytest.approx(result.score, abs=0.01)

    def test_score_bounded_0_to_100(self) -> None:
        """Score is always in [0, 100] range."""
        scorer = PaymentRiskScorer()

        result_zero = scorer.score(_signals(days_overdue=0, streak=12, balance=0.0, days_to_renewal=200))
        assert 0.0 <= result_zero.score <= 100.0

        result_max = scorer.score(_signals(days_overdue=180, streak=-10, balance=100_000.0, days_to_renewal=1))
        assert 0.0 <= result_max.score <= 100.0
        assert result_max.score == 100.0  # capped at 100

    # -- Component Scoring Tests -----------------------------------------------

    def test_days_overdue_component_scoring(self) -> None:
        """Verify each days_overdue tier maps to correct points."""
        scorer = PaymentRiskScorer()

        # Use streak=12, balance<1k, renewal>90d to isolate days_overdue component
        def overdue_pts(days: int) -> float:
            r = scorer.score(_signals(days_overdue=days, streak=12, balance=500.0, days_to_renewal=100))
            return r.score_breakdown["days_overdue"]

        assert overdue_pts(0) == 0.0
        assert overdue_pts(15) == 0.0    # 1-29: 0 pts
        assert overdue_pts(30) == 12.0   # 30-59: 12 pts
        assert overdue_pts(45) == 12.0   # still in 30-59 tier
        assert overdue_pts(60) == 25.0   # 60-89: 25 pts
        assert overdue_pts(75) == 25.0
        assert overdue_pts(90) == 35.0   # 90-119: 35 pts
        assert overdue_pts(100) == 35.0
        assert overdue_pts(120) == 40.0  # 120+: 40 pts
        assert overdue_pts(200) == 40.0

    def test_payment_streak_component_scoring(self) -> None:
        """Verify each payment_streak tier maps to correct points."""
        scorer = PaymentRiskScorer()

        def streak_pts(streak: int) -> float:
            r = scorer.score(_signals(days_overdue=0, streak=streak, balance=500.0, days_to_renewal=100))
            return r.score_breakdown["payment_history_streak"]

        assert streak_pts(12) == 0.0    # >= 12: 0 pts
        assert streak_pts(15) == 0.0    # > 12: still 0
        assert streak_pts(6) == 3.0     # >= 6, < 12: 3 pts
        assert streak_pts(8) == 3.0
        assert streak_pts(1) == 8.0     # >= 1, < 6: 8 pts
        assert streak_pts(5) == 8.0
        assert streak_pts(0) == 12.0    # == 0: 12 pts
        assert streak_pts(-1) == 15.0   # >= -2: 15 pts
        assert streak_pts(-2) == 15.0
        assert streak_pts(-3) == 20.0   # >= -5: 20 pts
        assert streak_pts(-5) == 20.0
        assert streak_pts(-6) == 25.0   # <= -6: 25 pts
        assert streak_pts(-10) == 25.0

    def test_balance_component_scoring(self) -> None:
        """Verify each outstanding balance tier maps to correct points."""
        scorer = PaymentRiskScorer()

        def balance_pts(bal: float) -> float:
            r = scorer.score(_signals(days_overdue=0, streak=12, balance=bal, days_to_renewal=100))
            return r.score_breakdown["total_outstanding_balance_usd"]

        assert balance_pts(0.0) == 0.0       # < $1k: 0 pts
        assert balance_pts(999.0) == 0.0
        assert balance_pts(1_000.0) == 8.0   # $1-$9,999: 8 pts
        assert balance_pts(5_000.0) == 8.0
        assert balance_pts(9_999.0) == 8.0
        assert balance_pts(10_000.0) == 14.0  # $10k-$49,999: 14 pts
        assert balance_pts(25_000.0) == 14.0
        assert balance_pts(49_999.0) == 14.0
        assert balance_pts(50_000.0) == 20.0  # $50k+: 20 pts
        assert balance_pts(100_000.0) == 20.0

    def test_days_to_renewal_component_scoring(self) -> None:
        """Verify each days_to_renewal tier maps to correct points."""
        scorer = PaymentRiskScorer()

        def renewal_pts(days: int) -> float:
            r = scorer.score(_signals(days_overdue=0, streak=12, balance=500.0, days_to_renewal=days))
            return r.score_breakdown["days_to_renewal"]

        assert renewal_pts(91) == 0.0    # > 90: 0 pts
        assert renewal_pts(200) == 0.0
        assert renewal_pts(90) == 5.0    # 31-90: 5 pts
        assert renewal_pts(60) == 5.0
        assert renewal_pts(31) == 5.0
        assert renewal_pts(30) == 10.0   # 8-30: 10 pts
        assert renewal_pts(15) == 10.0
        assert renewal_pts(8) == 10.0
        assert renewal_pts(7) == 15.0    # 0-7: 15 pts
        assert renewal_pts(0) == 15.0

    # -- STAGE_TIME_FLOORS Export Test ----------------------------------------

    def test_stage_time_floors_exported(self) -> None:
        """STAGE_TIME_FLOORS is a dict with 4 stage keys: 1, 2, 3, 4."""
        assert isinstance(STAGE_TIME_FLOORS, dict)
        assert set(STAGE_TIME_FLOORS.keys()) == {1, 2, 3, 4}
        # Values are positive int days
        for _stage, days in STAGE_TIME_FLOORS.items():
            assert isinstance(days, int)
            assert days > 0


# -- Test Class: compute_tone_modifier ----------------------------------------


class TestComputeToneModifier:
    """Tests for the compute_tone_modifier function."""

    def test_enterprise_softening(self) -> None:
        """Enterprise ($600k ARR, 5yr tenure, clean history) -> 1.0 - 0.2 - 0.1 = 0.7."""
        result = compute_tone_modifier(
            days_overdue=0,
            arr_usd=600_000.0,
            payment_streak=10,
            tenure_years=5.0,
        )
        assert result == pytest.approx(0.7, abs=0.001)

    def test_mid_market_small_discount(self) -> None:
        """Mid-market ($150k ARR, 1yr, clean) -> 1.0 - 0.1 = 0.9."""
        result = compute_tone_modifier(
            days_overdue=0,
            arr_usd=150_000.0,
            payment_streak=5,
            tenure_years=1.0,
        )
        assert result == pytest.approx(0.9, abs=0.001)

    def test_smb_chronic_late_hardening(self) -> None:
        """SMB chronic late ($50k ARR, 2yr, streak=-4) -> 1.0 + 0.2 = 1.2."""
        result = compute_tone_modifier(
            days_overdue=60,
            arr_usd=50_000.0,
            payment_streak=-4,
            tenure_years=2.0,
        )
        assert result == pytest.approx(1.2, abs=0.001)

    def test_combined_enterprise_chronic_late(self) -> None:
        """Enterprise + chronic late: 1.0 - 0.2 - 0.1 + 0.2 = 0.9 (no extreme clamp)."""
        result = compute_tone_modifier(
            days_overdue=90,
            arr_usd=600_000.0,
            payment_streak=-5,
            tenure_years=4.0,
        )
        assert result == pytest.approx(0.9, abs=0.001)

    def test_default_no_modifiers(self) -> None:
        """Default (no modifiers: small ARR, short tenure, good streak) -> 1.0."""
        result = compute_tone_modifier(
            days_overdue=0,
            arr_usd=10_000.0,
            payment_streak=6,
            tenure_years=0.5,
        )
        assert result == pytest.approx(1.0, abs=0.001)

    def test_arr_threshold_500k_gives_minus_02(self) -> None:
        """ARR exactly $500k -> -0.2 (enterprise tier)."""
        result_500k = compute_tone_modifier(
            days_overdue=0, arr_usd=500_000.0, payment_streak=5, tenure_years=0.0
        )
        # 1.0 - 0.2 = 0.8
        assert result_500k == pytest.approx(0.8, abs=0.001)

    def test_arr_threshold_100k_gives_minus_01(self) -> None:
        """ARR exactly $100k -> -0.1 (mid-market tier)."""
        result_100k = compute_tone_modifier(
            days_overdue=0, arr_usd=100_000.0, payment_streak=5, tenure_years=0.0
        )
        # 1.0 - 0.1 = 0.9
        assert result_100k == pytest.approx(0.9, abs=0.001)

    def test_streak_threshold_minus_3_gives_plus_02(self) -> None:
        """Payment streak exactly -3 -> +0.2 (chronic late tier)."""
        result = compute_tone_modifier(
            days_overdue=0, arr_usd=0.0, payment_streak=-3, tenure_years=0.0
        )
        # 1.0 + 0.2 = 1.2
        assert result == pytest.approx(1.2, abs=0.001)

    def test_tone_modifier_result_always_in_range(self) -> None:
        """Tone modifier is always clamped to [0.6, 1.4]."""
        # Even with all possible discounts (enterprise + long tenure), floor = 0.6
        result_floor = compute_tone_modifier(
            days_overdue=0, arr_usd=1_000_000.0, payment_streak=12, tenure_years=10.0
        )
        # 1.0 - 0.2 - 0.1 = 0.7 (well above 0.6 floor)
        assert result_floor >= 0.6

        # Even with all hardening modifiers, ceiling = 1.4
        result_ceiling = compute_tone_modifier(
            days_overdue=180, arr_usd=0.0, payment_streak=-12, tenure_years=0.0
        )
        # 1.0 + 0.2 = 1.2 (well below 1.4 ceiling)
        assert result_ceiling <= 1.4

    def test_tenure_3_years_gives_minus_01(self) -> None:
        """Tenure exactly 3 years -> -0.1 (long-tenure modifier)."""
        result = compute_tone_modifier(
            days_overdue=0, arr_usd=0.0, payment_streak=5, tenure_years=3.0
        )
        # 1.0 - 0.1 = 0.9
        assert result == pytest.approx(0.9, abs=0.001)

    def test_tenure_below_3_years_no_modifier(self) -> None:
        """Tenure 2.9 years -> no tenure modifier."""
        result = compute_tone_modifier(
            days_overdue=0, arr_usd=0.0, payment_streak=5, tenure_years=2.9
        )
        assert result == pytest.approx(1.0, abs=0.001)
