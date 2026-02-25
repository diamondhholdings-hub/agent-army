"""Pydantic model validation tests for CSM schemas.

Tests CSMHealthScore model_validator (should_alert auto-computation),
CSMHealthSignals field validation (bounded nps_score, seats_utilization_rate),
CSMHandoffRequest Literal constraint, and ExpansionOpportunity Literal constraint.

Covers:
    - CSMHealthScore with rag=RED -> should_alert=True (model_validator)
    - CSMHealthScore with rag=GREEN, churn_risk_level=low -> should_alert=False
    - CSMHealthScore with rag=AMBER, churn_risk_level=critical -> should_alert=True (critical overrides)
    - CSMHealthSignals rejects nps_score=11 (>10 boundary)
    - CSMHealthSignals rejects negative seats_utilization_rate
    - CSMHandoffRequest rejects invalid task_type Literal
    - ExpansionOpportunity rejects invalid opportunity_type Literal
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.app.agents.customer_success.schemas import (
    CSMHandoffRequest,
    CSMHealthScore,
    CSMHealthSignals,
    ExpansionOpportunity,
)


# -- CSMHealthScore model_validator Tests -----------------------------------


class TestCSMHealthScore:
    """Tests for CSMHealthScore model_validator and field validation."""

    def test_red_rag_triggers_should_alert(self) -> None:
        """CSMHealthScore with rag=RED -> should_alert=True via model_validator."""
        score = CSMHealthScore(
            account_id="x",
            score=10.0,
            rag="RED",
            churn_risk_level="high",
        )
        assert score.should_alert is True

    def test_green_low_churn_no_alert(self) -> None:
        """CSMHealthScore with rag=GREEN, churn_risk_level=low -> should_alert=False."""
        score = CSMHealthScore(
            account_id="x",
            score=80.0,
            rag="GREEN",
            churn_risk_level="low",
        )
        assert score.should_alert is False

    def test_critical_churn_triggers_alert_even_amber(self) -> None:
        """CSMHealthScore with churn_risk_level=critical -> should_alert=True regardless of rag."""
        score = CSMHealthScore(
            account_id="x",
            score=50.0,
            rag="AMBER",
            churn_risk_level="critical",
        )
        assert score.should_alert is True

    def test_high_churn_triggers_alert(self) -> None:
        """CSMHealthScore with churn_risk_level=high -> should_alert=True."""
        score = CSMHealthScore(
            account_id="x",
            score=55.0,
            rag="AMBER",
            churn_risk_level="high",
        )
        assert score.should_alert is True

    def test_amber_medium_churn_no_alert(self) -> None:
        """CSMHealthScore with rag=AMBER, churn_risk_level=medium -> should_alert=False."""
        score = CSMHealthScore(
            account_id="x",
            score=50.0,
            rag="AMBER",
            churn_risk_level="medium",
        )
        assert score.should_alert is False

    def test_green_high_churn_triggers_alert(self) -> None:
        """Even GREEN rag, if churn_risk_level=high -> should_alert=True."""
        score = CSMHealthScore(
            account_id="x",
            score=75.0,
            rag="GREEN",
            churn_risk_level="high",
        )
        assert score.should_alert is True

    def test_score_bounds_enforced(self) -> None:
        """Score outside [0, 100] raises ValidationError."""
        with pytest.raises(ValidationError):
            CSMHealthScore(
                account_id="x",
                score=101.0,
                rag="GREEN",
                churn_risk_level="low",
            )
        with pytest.raises(ValidationError):
            CSMHealthScore(
                account_id="x",
                score=-1.0,
                rag="RED",
                churn_risk_level="high",
            )

    def test_signal_breakdown_defaults_empty(self) -> None:
        """signal_breakdown defaults to empty dict."""
        score = CSMHealthScore(
            account_id="x",
            score=50.0,
            rag="AMBER",
            churn_risk_level="medium",
        )
        assert score.signal_breakdown == {}

    def test_computed_at_auto_set(self) -> None:
        """computed_at is auto-set to a datetime."""
        score = CSMHealthScore(
            account_id="x",
            score=50.0,
            rag="AMBER",
            churn_risk_level="medium",
        )
        assert score.computed_at is not None


# -- CSMHealthSignals Validation Tests --------------------------------------


class TestCSMHealthSignals:
    """Tests for CSMHealthSignals field validation constraints."""

    def test_nps_score_above_10_rejected(self) -> None:
        """CSMHealthSignals with nps_score=11 raises ValidationError (max 10)."""
        with pytest.raises(ValidationError):
            CSMHealthSignals(
                feature_adoption_rate=0.5,
                usage_trend="stable",
                stakeholder_engagement="medium",
                invoice_payment_status="current",
                seats_utilization_rate=0.5,
                nps_score=11,
            )

    def test_nps_score_below_0_rejected(self) -> None:
        """CSMHealthSignals with nps_score=-1 raises ValidationError (min 0)."""
        with pytest.raises(ValidationError):
            CSMHealthSignals(
                feature_adoption_rate=0.5,
                usage_trend="stable",
                stakeholder_engagement="medium",
                invoice_payment_status="current",
                seats_utilization_rate=0.5,
                nps_score=-1,
            )

    def test_negative_seats_utilization_rejected(self) -> None:
        """CSMHealthSignals with seats_utilization_rate < 0 raises ValidationError."""
        with pytest.raises(ValidationError):
            CSMHealthSignals(
                feature_adoption_rate=0.5,
                usage_trend="stable",
                stakeholder_engagement="medium",
                invoice_payment_status="current",
                seats_utilization_rate=-0.1,
            )

    def test_feature_adoption_rate_above_1_rejected(self) -> None:
        """CSMHealthSignals with feature_adoption_rate > 1.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            CSMHealthSignals(
                feature_adoption_rate=1.1,
                usage_trend="stable",
                stakeholder_engagement="medium",
                invoice_payment_status="current",
                seats_utilization_rate=0.5,
            )

    def test_invalid_usage_trend_rejected(self) -> None:
        """CSMHealthSignals with invalid usage_trend raises ValidationError."""
        with pytest.raises(ValidationError):
            CSMHealthSignals(
                feature_adoption_rate=0.5,
                usage_trend="exploding",
                stakeholder_engagement="medium",
                invoice_payment_status="current",
                seats_utilization_rate=0.5,
            )

    def test_valid_signals_accepted(self) -> None:
        """CSMHealthSignals with all valid values constructs successfully."""
        signals = CSMHealthSignals(
            feature_adoption_rate=0.5,
            usage_trend="stable",
            stakeholder_engagement="medium",
            invoice_payment_status="current",
            seats_utilization_rate=0.8,
            nps_score=7,
        )
        assert signals.feature_adoption_rate == 0.5
        assert signals.nps_score == 7

    def test_optional_fields_default_none(self) -> None:
        """Optional fields default to None when not provided."""
        signals = CSMHealthSignals(
            feature_adoption_rate=0.5,
            usage_trend="stable",
            stakeholder_engagement="medium",
            invoice_payment_status="current",
            seats_utilization_rate=0.5,
        )
        assert signals.login_frequency_days is None
        assert signals.days_since_last_interaction is None
        assert signals.nps_score is None
        assert signals.days_to_renewal is None
        assert signals.tam_health_rag is None


# -- CSMHandoffRequest Literal Constraint Tests -----------------------------


class TestCSMHandoffRequest:
    """Tests for CSMHandoffRequest Literal field validation."""

    def test_invalid_task_type_rejected(self) -> None:
        """CSMHandoffRequest with task_type='unknown_type' raises ValidationError."""
        with pytest.raises(ValidationError):
            CSMHandoffRequest(
                task_type="unknown_type",
                account_id="acc-1",
                tenant_id="t-1",
            )

    def test_valid_task_types_accepted(self) -> None:
        """All valid task_type values are accepted."""
        valid_types = [
            "health_scan",
            "generate_qbr",
            "check_expansion",
            "track_feature_adoption",
        ]
        for task_type in valid_types:
            request = CSMHandoffRequest(
                task_type=task_type,
                account_id="acc-1",
                tenant_id="t-1",
            )
            assert request.task_type == task_type

    def test_invalid_priority_rejected(self) -> None:
        """CSMHandoffRequest with invalid priority raises ValidationError."""
        with pytest.raises(ValidationError):
            CSMHandoffRequest(
                task_type="health_scan",
                account_id="acc-1",
                tenant_id="t-1",
                priority="super_urgent",
            )


# -- ExpansionOpportunity Literal Constraint Tests --------------------------


class TestExpansionOpportunity:
    """Tests for ExpansionOpportunity Literal field validation."""

    def test_invalid_opportunity_type_rejected(self) -> None:
        """ExpansionOpportunity with opportunity_type='enterprise' raises ValidationError."""
        with pytest.raises(ValidationError):
            ExpansionOpportunity(
                account_id="acc-1",
                opportunity_type="enterprise",
                evidence="High usage signals",
                recommended_talk_track="Discuss enterprise tier",
            )

    def test_valid_opportunity_types_accepted(self) -> None:
        """All valid opportunity_type values are accepted."""
        valid_types = ["seats", "module", "integration"]
        for opp_type in valid_types:
            opp = ExpansionOpportunity(
                account_id="acc-1",
                opportunity_type=opp_type,
                evidence="Usage signals",
                recommended_talk_track="Talk track",
            )
            assert opp.opportunity_type == opp_type

    def test_invalid_confidence_rejected(self) -> None:
        """ExpansionOpportunity with invalid confidence raises ValidationError."""
        with pytest.raises(ValidationError):
            ExpansionOpportunity(
                account_id="acc-1",
                opportunity_type="seats",
                evidence="Usage signals",
                recommended_talk_track="Talk track",
                confidence="very_high",
            )
