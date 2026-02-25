"""Pydantic model validation tests for the Collections Agent schemas.

Validates PaymentRiskResult.should_escalate auto-computation (boundary at 60.0),
EscalationState field defaults and datetime assignment, ARAgingReport construction,
PaymentPlanOptions, CollectionsHandoffRequest literals, and the CSMHealthSignals
collections_risk field (backward compatibility and new values).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from src.app.agents.collections.schemas import (
    ARAgingBucket,
    ARAgingReport,
    CollectionsHandoffRequest,
    EscalationState,
    PaymentPlanOption,
    PaymentPlanOptions,
    PaymentRiskResult,
)
from src.app.agents.customer_success.schemas import CSMHealthSignals


class TestPaymentRiskResultShouldEscalate:
    """PaymentRiskResult.should_escalate auto-computation tests."""

    def test_payment_risk_result_should_escalate_true(self) -> None:
        """score=65.0, rag='RED' -> should_escalate is True."""
        result = PaymentRiskResult(
            account_id="acct-001",
            score=65.0,
            rag="RED",
        )
        assert result.should_escalate is True

    def test_payment_risk_result_should_escalate_false(self) -> None:
        """score=25.0, rag='GREEN' -> should_escalate is False."""
        result = PaymentRiskResult(
            account_id="acct-002",
            score=25.0,
            rag="GREEN",
        )
        assert result.should_escalate is False

    def test_payment_risk_result_boundary(self) -> None:
        """score=60.0 -> should_escalate is True (boundary inclusive)."""
        result = PaymentRiskResult(
            account_id="acct-003",
            score=60.0,
            rag="AMBER",
        )
        # score >= 60.0 is True at exact boundary
        assert result.should_escalate is True

    def test_payment_risk_result_score_59(self) -> None:
        """score=59.9 -> should_escalate is False (just below threshold)."""
        result = PaymentRiskResult(
            account_id="acct-004",
            score=59.9,
            rag="AMBER",
        )
        assert result.should_escalate is False

    def test_payment_risk_result_critical_escalates(self) -> None:
        """score=90.0, rag='CRITICAL' -> should_escalate is True."""
        result = PaymentRiskResult(
            account_id="acct-005",
            score=90.0,
            rag="CRITICAL",
        )
        assert result.should_escalate is True

    def test_payment_risk_result_score_zero_no_escalate(self) -> None:
        """score=0.0 -> should_escalate is False."""
        result = PaymentRiskResult(
            account_id="acct-006",
            score=0.0,
            rag="GREEN",
        )
        assert result.should_escalate is False


class TestEscalationStateDefaults:
    """EscalationState field defaults and datetime assignment tests."""

    def test_escalation_state_defaults(self) -> None:
        """EscalationState(account_id='x') -> default field values."""
        state = EscalationState(account_id="x")

        assert state.account_id == "x"
        assert state.current_stage == 0
        assert state.messages_unanswered == 0
        assert state.stage5_notified is False
        assert state.payment_received_at is None
        assert state.response_received_at is None
        assert state.stage_entered_at is None
        assert state.last_message_sent_at is None

    def test_escalation_state_stage5(self) -> None:
        """EscalationState with stage=5 and stage5_notified=True -> verified."""
        state = EscalationState(
            account_id="x",
            current_stage=5,
            stage5_notified=True,
        )
        assert state.current_stage == 5
        assert state.stage5_notified is True

    def test_escalation_state_payment_received_at_datetime(self) -> None:
        """payment_received_at accepts a timezone-aware datetime."""
        now = datetime.now(timezone.utc)
        state = EscalationState(
            account_id="acct-001",
            payment_received_at=now,
        )
        assert state.payment_received_at == now

    def test_escalation_state_response_received_at_datetime(self) -> None:
        """response_received_at accepts a timezone-aware datetime."""
        now = datetime.now(timezone.utc)
        state = EscalationState(
            account_id="acct-002",
            response_received_at=now,
        )
        assert state.response_received_at == now

    def test_escalation_state_messages_unanswered(self) -> None:
        """messages_unanswered can be set to positive int."""
        state = EscalationState(account_id="acct-003", messages_unanswered=3)
        assert state.messages_unanswered == 3


class TestARAgingReportConstruction:
    """ARAgingReport and ARAgingBucket construction tests."""

    def test_ar_aging_report_construction(self) -> None:
        """Build ARAgingReport with 2 buckets; verify total_outstanding sums correctly."""
        bucket1 = ARAgingBucket(
            bucket_label="0-30",
            invoice_count=2,
            total_amount_usd=1000.0,
            oldest_invoice_date=date(2026, 1, 15),
            oldest_invoice_number="INV-001",
        )
        bucket2 = ARAgingBucket(
            bucket_label="31-60",
            invoice_count=1,
            total_amount_usd=2500.0,
            oldest_invoice_date=date(2025, 12, 20),
            oldest_invoice_number="INV-002",
        )

        report = ARAgingReport(
            account_id="acct-001",
            account_name="Acme Corp",
            total_outstanding_usd=3500.0,
            buckets=[bucket1, bucket2],
            oldest_invoice_number="INV-002",
            oldest_invoice_amount_usd=2500.0,
            oldest_invoice_date=date(2025, 12, 20),
        )

        assert report.account_id == "acct-001"
        assert report.total_outstanding_usd == 3500.0
        assert len(report.buckets) == 2
        # Verify bucket totals sum to total_outstanding
        bucket_sum = sum(b.total_amount_usd for b in report.buckets)
        assert bucket_sum == report.total_outstanding_usd


class TestPaymentPlanOptions:
    """PaymentPlanOptions and PaymentPlanOption construction tests."""

    def test_payment_plan_options(self) -> None:
        """Build PaymentPlanOptions with 3 options; verify option_type Literals."""
        opt1 = PaymentPlanOption(
            option_type="installment_schedule",
            description="3 monthly payments",
            proposed_amounts=[1000.0, 1000.0, 1000.0],
            proposed_dates=[
                date(2026, 3, 1),
                date(2026, 4, 1),
                date(2026, 5, 1),
            ],
            total_usd=3000.0,
        )
        opt2 = PaymentPlanOption(
            option_type="partial_payment",
            description="Pay 50% now, rest in 60 days",
            proposed_amounts=[1500.0, 1500.0],
            proposed_dates=[date(2026, 3, 1), date(2026, 4, 30)],
            total_usd=3000.0,
        )
        opt3 = PaymentPlanOption(
            option_type="pay_or_suspend",
            description="Pay in full or service suspended",
            proposed_amounts=[3000.0],
            proposed_dates=[date(2026, 3, 15)],
            total_usd=3000.0,
        )

        options = PaymentPlanOptions(
            account_id="acct-001",
            total_outstanding_usd=3000.0,
            options=[opt1, opt2, opt3],
            llm_rationale="Three options representing progressive firmness.",
        )

        assert len(options.options) == 3
        assert options.options[0].option_type == "installment_schedule"
        assert options.options[1].option_type == "partial_payment"
        assert options.options[2].option_type == "pay_or_suspend"

    def test_payment_plan_option_invalid_type_rejected(self) -> None:
        """PaymentPlanOption with invalid option_type raises ValidationError."""
        with pytest.raises(ValidationError):
            PaymentPlanOption(
                option_type="free_pass",  # Invalid
                description="Give them a free pass",
                proposed_amounts=[0.0],
                proposed_dates=[date(2026, 3, 1)],
                total_usd=0.0,
            )


class TestCollectionsHandoffRequestLiterals:
    """CollectionsHandoffRequest request_type Literal validation tests."""

    def test_collections_handoff_request_literals(self) -> None:
        """Verify all 5 request_type values are valid."""
        valid_types = [
            "ar_aging_report",
            "payment_risk_assessment",
            "generate_collection_message",
            "run_escalation_check",
            "surface_payment_plan",
        ]

        for request_type in valid_types:
            req = CollectionsHandoffRequest(
                request_type=request_type,
                account_id="acct-001",
            )
            assert req.request_type == request_type

    def test_collections_handoff_request_invalid_type_rejected(self) -> None:
        """Invalid request_type raises ValidationError."""
        with pytest.raises(ValidationError):
            CollectionsHandoffRequest(
                request_type="send_lawyers",  # Invalid
                account_id="acct-001",
            )


class TestCSMHealthSignalsCollectionsRisk:
    """CSMHealthSignals.collections_risk field tests for backward compatibility."""

    def test_csm_health_signals_collections_risk_none(self) -> None:
        """CSMHealthSignals without collections_risk -> collections_risk is None."""
        signals = CSMHealthSignals(
            feature_adoption_rate=0.8,
            usage_trend="stable",
            stakeholder_engagement="medium",
            invoice_payment_status="current",
            seats_utilization_rate=0.75,
        )
        # Backward compatible: collections_risk defaults to None
        assert signals.collections_risk is None

    def test_csm_health_signals_collections_risk_critical(self) -> None:
        """CSMHealthSignals with collections_risk='CRITICAL' -> accepted correctly."""
        signals = CSMHealthSignals(
            feature_adoption_rate=0.5,
            usage_trend="declining",
            stakeholder_engagement="low",
            invoice_payment_status="overdue_90_plus",
            seats_utilization_rate=0.3,
            collections_risk="CRITICAL",
        )
        assert signals.collections_risk == "CRITICAL"

    def test_csm_health_signals_collections_risk_all_values(self) -> None:
        """All four collections_risk values (GREEN, AMBER, RED, CRITICAL) are valid."""
        for risk_value in ("GREEN", "AMBER", "RED", "CRITICAL"):
            signals = CSMHealthSignals(
                feature_adoption_rate=0.7,
                usage_trend="stable",
                stakeholder_engagement="medium",
                invoice_payment_status="current",
                seats_utilization_rate=0.7,
                collections_risk=risk_value,
            )
            assert signals.collections_risk == risk_value

    def test_csm_health_signals_collections_risk_invalid_rejected(self) -> None:
        """Invalid collections_risk value raises ValidationError."""
        with pytest.raises(ValidationError):
            CSMHealthSignals(
                feature_adoption_rate=0.7,
                usage_trend="stable",
                stakeholder_engagement="medium",
                invoice_payment_status="current",
                seats_utilization_rate=0.7,
                collections_risk="EXTREME",  # Invalid
            )
