"""Deterministic payment risk scoring and tone calibration for Collections Agent.

Computes a 0-100 payment risk score (higher = more risk, inverted from CSM
health scorer) from four weighted signal components: days overdue, payment
history streak, outstanding balance, and days to renewal. Derives a RAG status
and populates a per-dimension score breakdown.

IMPORTANT: Do NOT use LLM for score computation. The score is a deterministic
numeric calculation. LLM adds latency, cost, and non-determinism for zero benefit.

Exports:
    PaymentRiskScorer: 4-signal payment risk scoring engine with RAG derivation
        and escalation flag.
    compute_tone_modifier: Standalone function returning a float in [0.6, 1.4]
        that modulates collection message firmness based on ARR, tenure, and
        payment streak.
    STAGE_TIME_FLOORS: Minimum days each escalation stage must remain active
        before advancing. Used by handlers and scheduler for stage advancement
        logic.
"""

from __future__ import annotations

from src.app.agents.collections.schemas import PaymentRiskResult, PaymentRiskSignals

# Minimum days per escalation stage before advancing to the next stage.
# Stage 1: soft reminder (7d), Stage 2: firm notice (10d),
# Stage 3: escalation notice (7d), Stage 4: pre-legal warning (5d).
STAGE_TIME_FLOORS: dict[int, int] = {1: 7, 2: 10, 3: 7, 4: 5}


class PaymentRiskScorer:
    """Compute payment risk score (0-100, higher = more risk) from 4 signals.

    Component weights (max points per component, total = 100):
        days_overdue:                  0-40 pts  (primary signal)
        payment_history_streak:        0-25 pts
        total_outstanding_balance_usd: 0-20 pts
        days_to_renewal:               0-15 pts

    RAG derivation:
        score < 30  -> GREEN
        score < 60  -> AMBER
        score < 85  -> RED
        score >= 85 -> CRITICAL

    Escalation:
        should_escalate = score >= 60 (AMBER and above requires action)

    Note: arr_usd and tenure_years in PaymentRiskSignals are tone modifiers
    only — they do NOT affect the numeric risk score.
    """

    # ── Component Scorers (private static) ──────────────────────────────────

    @staticmethod
    def _score_days_overdue(days: int) -> float:
        """Days overdue component: 0-40 points.

        Tier mapping:
            0-29 days   -> 0 pts
            30-59 days  -> 12 pts
            60-89 days  -> 25 pts
            90-119 days -> 35 pts
            120+ days   -> 40 pts
        """
        if days >= 120:
            return 40.0
        if days >= 90:
            return 35.0
        if days >= 60:
            return 25.0
        if days >= 30:
            return 12.0
        return 0.0

    @staticmethod
    def _score_payment_streak(streak: int) -> float:
        """Payment history streak component: 0-25 points.

        Positive streak = consecutive on-time payments (reduces risk).
        Negative streak = consecutive late payments (increases risk).

        Tier mapping:
            streak >= 12  -> 0 pts   (12+ consecutive on-time, excellent)
            streak >= 6   -> 3 pts   (6-11 on-time, good)
            streak >= 1   -> 8 pts   (1-5 on-time, mixed)
            streak == 0   -> 12 pts  (neutral, no clear pattern)
            streak >= -2  -> 15 pts  (1-2 consecutive late)
            streak >= -5  -> 20 pts  (3-5 consecutive late)
            streak <= -6  -> 25 pts  (6+ consecutive late, chronic)
        """
        if streak >= 12:
            return 0.0
        if streak >= 6:
            return 3.0
        if streak >= 1:
            return 8.0
        if streak == 0:
            return 12.0
        if streak >= -2:
            return 15.0
        if streak >= -5:
            return 20.0
        return 25.0  # streak <= -6

    @staticmethod
    def _score_outstanding_balance(balance_usd: float) -> float:
        """Outstanding balance component: 0-20 points.

        Tier mapping:
            < $1,000    -> 0 pts
            $1-$9,999   -> 8 pts
            $10-$49,999 -> 14 pts
            $50,000+    -> 20 pts
        """
        if balance_usd >= 50_000.0:
            return 20.0
        if balance_usd >= 10_000.0:
            return 14.0
        if balance_usd >= 1_000.0:
            return 8.0
        return 0.0

    @staticmethod
    def _score_days_to_renewal(days: int) -> float:
        """Days to renewal component: 0-15 points.

        Closer to renewal = higher urgency = more risk points.

        Tier mapping:
            > 90 days -> 0 pts   (plenty of time)
            31-90 days -> 5 pts  (moderately urgent)
            8-30 days  -> 10 pts (urgent)
            0-7 days   -> 15 pts (renewal imminent, maximum pressure)
        """
        if days <= 7:
            return 15.0
        if days <= 30:
            return 10.0
        if days <= 90:
            return 5.0
        return 0.0

    @staticmethod
    def _derive_rag(score: float) -> str:
        """Derive RAG status from numeric risk score.

        Thresholds:
            score < 30  -> GREEN
            score < 60  -> AMBER
            score < 85  -> RED
            score >= 85 -> CRITICAL
        """
        if score >= 85.0:
            return "CRITICAL"
        if score >= 60.0:
            return "RED"
        if score >= 30.0:
            return "AMBER"
        return "GREEN"

    # ── Main Scoring Method ──────────────────────────────────────────────────

    def score(self, signals: PaymentRiskSignals) -> PaymentRiskResult:
        """Compute payment risk score from signals.

        Steps:
        1. Compute per-component contributions from the 4 risk signals.
        2. Sum components, clamp to [0, 100].
        3. Derive RAG status from score thresholds.
        4. Build score_breakdown dict.
        5. Return PaymentRiskResult (should_escalate auto-computed by model_validator).

        Args:
            signals: PaymentRiskSignals with 4 scoring fields + 2 tone modifier
                     fields (arr_usd, tenure_years) that are ignored here.

        Returns:
            PaymentRiskResult with score, rag, should_escalate, and score_breakdown.
        """
        # Step 1: Compute per-component scores
        breakdown: dict[str, float] = {
            "days_overdue": self._score_days_overdue(signals.days_overdue),
            "payment_history_streak": self._score_payment_streak(
                signals.payment_history_streak
            ),
            "total_outstanding_balance_usd": self._score_outstanding_balance(
                signals.total_outstanding_balance_usd
            ),
            "days_to_renewal": self._score_days_to_renewal(signals.days_to_renewal),
        }

        # Step 2: Sum and clamp
        raw_score = sum(breakdown.values())
        final_score = max(0.0, min(100.0, raw_score))

        # Step 3: Derive RAG
        rag = self._derive_rag(final_score)

        # Steps 4 & 5: Build and return result (should_escalate auto-computed)
        return PaymentRiskResult(
            account_id=signals.account_id,
            score=final_score,
            rag=rag,
            score_breakdown=breakdown,
        )


def compute_tone_modifier(
    days_overdue: int,
    arr_usd: float,
    payment_streak: int,
    tenure_years: float,
) -> float:
    """Compute tone modifier for collection message firmness.

    Returns a float in [0.6, 1.4] where:
        < 1.0 = softer tone (preserve relationship, avoid aggression)
        1.0   = neutral baseline
        > 1.0 = firmer tone (urgency, consequences)

    Modifier components:
        arr_mod:    arr >= $500k -> -0.2 (enterprise, relationship-critical)
                    arr >= $100k -> -0.1 (mid-market, value the relationship)
                    else         ->  0.0
        tenure_mod: tenure >= 3 years -> -0.1 (long-term customer, softer approach)
                    else               ->  0.0
        streak_mod: payment_streak <= -3 -> +0.2 (chronic late payer, firm)
                    else                  ->  0.0

    The days_overdue parameter is accepted for interface completeness and future
    extensibility but does not currently affect the modifier (overdue severity is
    already captured in the risk score itself).

    Args:
        days_overdue: Days the oldest invoice is past due (reserved for future use).
        arr_usd: Annual recurring revenue in USD.
        payment_streak: Consecutive payment behavior (positive=on-time, negative=late).
        tenure_years: Customer tenure in years.

    Returns:
        Float in [0.6, 1.4] representing tone firmness modifier.
    """
    base = 1.0

    # ARR modifier: high-value customers get softer tone
    if arr_usd >= 500_000.0:
        arr_mod = -0.2
    elif arr_usd >= 100_000.0:
        arr_mod = -0.1
    else:
        arr_mod = 0.0

    # Tenure modifier: long-term customers get softer tone
    tenure_mod = -0.1 if tenure_years >= 3.0 else 0.0

    # Streak modifier: chronic late payers get firmer tone
    streak_mod = 0.2 if payment_streak <= -3 else 0.0

    raw_modifier = base + arr_mod + tenure_mod + streak_mod
    return max(0.6, min(1.4, raw_modifier))


__all__ = ["PaymentRiskScorer", "compute_tone_modifier", "STAGE_TIME_FLOORS"]
