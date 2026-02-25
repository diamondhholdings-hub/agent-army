"""Pure Python CSM health scoring algorithm with 11 weighted signals.

Computes a deterministic 0-100 health score from customer success signals
across adoption, usage, engagement, support, financial, and TAM health
dimensions. Applies TAM correlation cap and derives churn risk assessment.

IMPORTANT: Do NOT use LLM for score computation. The score is a deterministic
numeric calculation. LLM adds latency, cost, and non-determinism for zero benefit.

Exports:
    CSMHealthScorer: Configurable 11-signal health scoring engine with
        RAG derivation and churn risk assessment.
"""

from __future__ import annotations

from src.app.agents.customer_success.schemas import CSMHealthScore, CSMHealthSignals


class CSMHealthScorer:
    """Compute CSM health score (0-100, higher = healthier) from 11 weighted signals.

    Signal weights (total = 100):
        feature_adoption_rate:        20
        usage_trend:                  15
        login_frequency_days:         10
        days_since_last_interaction:  10
        invoice_payment_status:       10
        support (sentiment + tickets): 10
        days_to_renewal:              10
        seats_utilization_rate:         5
        stakeholder_engagement:         5
        nps_score:                      3
        escalation_count_90_days:       2

    TAM correlation cap (applied after raw score):
        RED   -> raw * 0.85
        AMBER -> raw * 0.95
        GREEN / None -> raw (no cap)

    RAG derivation:
        score >= green_threshold: GREEN
        score >= amber_threshold: AMBER
        score < amber_threshold:  RED

    Churn risk triggers:
        contract_proximity: RAG in (RED, AMBER) AND days_to_renewal <= churn_window_days
        behavioral: usage_trend in (declining, inactive) AND (login_frequency_days is None or > 30)

    All thresholds are configurable per-tenant via keyword-only constructor args.

    Args:
        green_threshold: Score at or above this is GREEN.
        amber_threshold: Score at or above this is AMBER (below green).
        churn_window_days: Days-to-renewal threshold for contract proximity churn trigger.
    """

    def __init__(
        self,
        *,
        green_threshold: float = 70.0,
        amber_threshold: float = 40.0,
        churn_window_days: int = 60,
    ) -> None:
        self._green_threshold = green_threshold
        self._amber_threshold = amber_threshold
        self._churn_window_days = churn_window_days

    # ── Signal Scorers (private) ─────────────────────────────────────────

    @staticmethod
    def _score_feature_adoption(rate: float) -> float:
        """Feature adoption rate: weight 20."""
        return rate * 20.0

    @staticmethod
    def _score_usage_trend(trend: str) -> float:
        """Usage trend: weight 15."""
        mapping = {"growing": 15.0, "stable": 10.0, "declining": 3.0, "inactive": 0.0}
        return mapping.get(trend, 0.0)

    @staticmethod
    def _score_login_frequency(days: int | None) -> float:
        """Login frequency days: weight 10. None = 5 (neutral)."""
        if days is None:
            return 5.0
        if days <= 7:
            return 10.0
        if days <= 30:
            return 7.0
        if days <= 60:
            return 4.0
        return 0.0

    @staticmethod
    def _score_days_since_interaction(days: int | None) -> float:
        """Days since last interaction: weight 10. None = 5 (neutral)."""
        if days is None:
            return 5.0
        if days <= 30:
            return 10.0
        if days <= 60:
            return 7.0
        if days <= 90:
            return 4.0
        return 0.0

    @staticmethod
    def _score_invoice_payment(status: str) -> float:
        """Invoice payment status: weight 10."""
        mapping = {
            "current": 10.0,
            "overdue_30": 6.0,
            "overdue_60": 3.0,
            "overdue_90_plus": 0.0,
        }
        return mapping.get(status, 0.0)

    @staticmethod
    def _score_support(sentiment: str, open_tickets: int) -> float:
        """Support (sentiment + open tickets): combined weight 10.

        Sentiment base: positive=10, neutral=7, negative=3, critical=0.
        Then deduct min(open_ticket_count, 5) * 1.
        Floor at 0.
        """
        sentiment_mapping = {
            "positive": 10.0,
            "neutral": 7.0,
            "negative": 3.0,
            "critical": 0.0,
        }
        base = sentiment_mapping.get(sentiment, 0.0)
        deduction = min(open_tickets, 5) * 1.0
        return max(0.0, base - deduction)

    @staticmethod
    def _score_days_to_renewal(days: int | None) -> float:
        """Days to renewal: weight 10. None = 7."""
        if days is None:
            return 7.0
        if days > 180:
            return 10.0
        if days > 90:
            return 8.0
        if days > 60:
            return 6.0
        if days > 30:
            return 3.0
        return 1.0

    @staticmethod
    def _score_seats_utilization(rate: float) -> float:
        """Seats utilization rate: weight 5."""
        if rate > 1.0:
            return 4.0
        if rate >= 0.8:
            return 5.0
        if rate >= 0.5:
            return 3.0
        return 1.0

    @staticmethod
    def _score_stakeholder_engagement(level: str) -> float:
        """Stakeholder engagement: weight 5."""
        mapping = {"high": 5.0, "medium": 3.0, "low": 1.0}
        return mapping.get(level, 1.0)

    @staticmethod
    def _score_nps(score: int | None) -> float:
        """NPS score: weight 3. None = 2."""
        if score is None:
            return 2.0
        if score >= 9:
            return 3.0
        if score >= 7:
            return 2.0
        if score >= 5:
            return 1.0
        return 0.0

    @staticmethod
    def _score_escalations(count: int) -> float:
        """Escalation count (90 days): weight 2."""
        if count == 0:
            return 2.0
        if count == 1:
            return 1.0
        return 0.0

    # ── TAM Correlation Cap ──────────────────────────────────────────────

    @staticmethod
    def _apply_tam_cap(raw_score: float, tam_rag: str | None) -> float:
        """Apply TAM health correlation cap to raw score.

        RED   -> raw * 0.85
        AMBER -> raw * 0.95
        GREEN / None -> raw (no cap)
        """
        if tam_rag == "RED":
            return raw_score * 0.85
        if tam_rag == "AMBER":
            return raw_score * 0.95
        return raw_score

    # ── Churn Risk Assessment ────────────────────────────────────────────

    def _assess_churn(
        self,
        rag: str,
        signals: CSMHealthSignals,
    ) -> tuple[str, str | None]:
        """Determine churn risk level and trigger.

        Returns:
            Tuple of (churn_risk_level, churn_triggered_by).
        """
        contract_proximity = (
            rag in ("RED", "AMBER")
            and signals.days_to_renewal is not None
            and signals.days_to_renewal <= self._churn_window_days
        )
        behavioral = (
            signals.usage_trend in ("declining", "inactive")
            and (
                signals.login_frequency_days is None
                or signals.login_frequency_days > 30
            )
        )

        if contract_proximity and behavioral:
            return "critical", "both"

        if contract_proximity:
            level = "critical" if rag == "RED" else "high"
            return level, "contract_proximity"

        if behavioral:
            level = "high" if rag in ("RED", "AMBER") else "medium"
            return level, "behavioral"

        # No triggers
        level = "low" if rag == "GREEN" else "medium"
        return level, None

    # ── Main Scoring Method ──────────────────────────────────────────────

    def score(
        self,
        signals: CSMHealthSignals,
        account_id: str = "",
    ) -> CSMHealthScore:
        """Compute CSM health score from signals.

        Steps:
        1. Compute raw 0-100 score from weighted signals.
        2. Apply TAM correlation cap if tam_health_rag is set.
        3. Derive RAG status from thresholds.
        4. Assess churn risk level and trigger.
        5. Build signal breakdown dict.
        6. Return CSMHealthScore.

        Args:
            signals: CSMHealthSignals with all 13 signal fields.
            account_id: Account identifier for the result.

        Returns:
            CSMHealthScore with score, rag, churn risk, and signal breakdown.
        """
        # Step 1: Compute per-signal contributions
        breakdown: dict[str, float] = {}

        breakdown["feature_adoption_rate"] = self._score_feature_adoption(
            signals.feature_adoption_rate
        )
        breakdown["usage_trend"] = self._score_usage_trend(signals.usage_trend)
        breakdown["login_frequency_days"] = self._score_login_frequency(
            signals.login_frequency_days
        )
        breakdown["days_since_last_interaction"] = self._score_days_since_interaction(
            signals.days_since_last_interaction
        )
        breakdown["invoice_payment_status"] = self._score_invoice_payment(
            signals.invoice_payment_status
        )
        breakdown["support"] = self._score_support(
            signals.avg_ticket_sentiment, signals.open_ticket_count
        )
        breakdown["days_to_renewal"] = self._score_days_to_renewal(
            signals.days_to_renewal
        )
        breakdown["seats_utilization_rate"] = self._score_seats_utilization(
            signals.seats_utilization_rate
        )
        breakdown["stakeholder_engagement"] = self._score_stakeholder_engagement(
            signals.stakeholder_engagement
        )
        breakdown["nps_score"] = self._score_nps(signals.nps_score)
        breakdown["escalation_count_90_days"] = self._score_escalations(
            signals.escalation_count_90_days
        )

        raw_score = sum(breakdown.values())
        raw_score = max(0.0, min(100.0, raw_score))

        # Step 2: Apply TAM correlation cap
        final_score = self._apply_tam_cap(raw_score, signals.tam_health_rag)
        final_score = max(0.0, min(100.0, final_score))

        # Step 3: Derive RAG
        if final_score >= self._green_threshold:
            rag = "GREEN"
        elif final_score >= self._amber_threshold:
            rag = "AMBER"
        else:
            rag = "RED"

        # Step 4: Assess churn risk
        churn_risk_level, churn_triggered_by = self._assess_churn(rag, signals)

        # Step 5 & 6: Build and return result
        return CSMHealthScore(
            account_id=account_id,
            score=final_score,
            rag=rag,
            churn_risk_level=churn_risk_level,
            churn_triggered_by=churn_triggered_by,
            signal_breakdown=breakdown,
        )


__all__ = ["CSMHealthScorer"]
