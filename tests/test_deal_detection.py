"""Unit tests for OpportunityDetector signal analysis and thresholds.

Tests the should_create_opportunity() and should_update_opportunity() methods
with various confidence levels and signal combinations. Does NOT test LLM
integration (those are integration tests).
"""

from __future__ import annotations

import pytest

from src.app.deals.detection import OpportunityDetector
from src.app.deals.schemas import OpportunitySignals


class TestShouldCreateOpportunity:
    """Tests for OpportunityDetector.should_create_opportunity()."""

    def setup_method(self) -> None:
        self.detector = OpportunityDetector()

    def test_should_create_opportunity_above_threshold(self) -> None:
        """Signals with confidence=0.85, is_new=True -> should create."""
        signals = OpportunitySignals(
            deal_potential_confidence=0.85,
            product_line="Enterprise Platform",
            is_new_opportunity=True,
            reasoning="Clear purchase intent for new product line",
        )
        assert self.detector.should_create_opportunity(signals) is True

    def test_should_not_create_below_threshold(self) -> None:
        """Signals with confidence=0.75, is_new=True -> should NOT create (below 0.80)."""
        signals = OpportunitySignals(
            deal_potential_confidence=0.75,
            product_line="Enterprise Platform",
            is_new_opportunity=True,
            reasoning="Some interest but not confirmed",
        )
        assert self.detector.should_create_opportunity(signals) is False

    def test_should_not_create_at_exact_threshold(self) -> None:
        """Signals with confidence=0.80 (exactly at threshold) -> should create."""
        signals = OpportunitySignals(
            deal_potential_confidence=0.80,
            is_new_opportunity=True,
        )
        assert self.detector.should_create_opportunity(signals) is True

    def test_should_not_create_when_not_new(self) -> None:
        """High confidence but is_new_opportunity=False -> should NOT create."""
        signals = OpportunitySignals(
            deal_potential_confidence=0.95,
            is_new_opportunity=False,
            matching_opportunity_id="existing-123",
        )
        assert self.detector.should_create_opportunity(signals) is False

    def test_should_not_create_zero_confidence(self) -> None:
        """Zero confidence -> should NOT create."""
        signals = OpportunitySignals(
            deal_potential_confidence=0.0,
            is_new_opportunity=True,
        )
        assert self.detector.should_create_opportunity(signals) is False


class TestShouldUpdateOpportunity:
    """Tests for OpportunityDetector.should_update_opportunity()."""

    def setup_method(self) -> None:
        self.detector = OpportunityDetector()

    def test_should_update_existing(self) -> None:
        """Signals with confidence=0.72, is_new=False, matching_id set -> should update."""
        signals = OpportunitySignals(
            deal_potential_confidence=0.72,
            is_new_opportunity=False,
            matching_opportunity_id="opp-456",
            reasoning="Continued discussion about existing deal",
        )
        assert self.detector.should_update_opportunity(signals) is True

    def test_should_not_update_below_threshold(self) -> None:
        """Signals with confidence=0.60, is_new=False -> should NOT update (below 0.70)."""
        signals = OpportunitySignals(
            deal_potential_confidence=0.60,
            is_new_opportunity=False,
            matching_opportunity_id="opp-456",
        )
        assert self.detector.should_update_opportunity(signals) is False

    def test_should_not_update_new_opportunity(self) -> None:
        """Signals for new opportunity -> should NOT update."""
        signals = OpportunitySignals(
            deal_potential_confidence=0.85,
            is_new_opportunity=True,
        )
        assert self.detector.should_update_opportunity(signals) is False

    def test_should_not_update_without_matching_id(self) -> None:
        """Not new but no matching_id -> should NOT update."""
        signals = OpportunitySignals(
            deal_potential_confidence=0.80,
            is_new_opportunity=False,
            matching_opportunity_id=None,
        )
        assert self.detector.should_update_opportunity(signals) is False

    def test_should_update_at_exact_threshold(self) -> None:
        """Signals at exactly 0.70 -> should update."""
        signals = OpportunitySignals(
            deal_potential_confidence=0.70,
            is_new_opportunity=False,
            matching_opportunity_id="opp-789",
        )
        assert self.detector.should_update_opportunity(signals) is True


class TestThresholdConstants:
    """Verify locked decision thresholds are set correctly."""

    def test_creation_threshold_is_080(self) -> None:
        """CREATION_THRESHOLD must be 0.80 (CONTEXT.md locked decision)."""
        assert OpportunityDetector.CREATION_THRESHOLD == 0.80

    def test_update_threshold_is_070(self) -> None:
        """UPDATE_THRESHOLD must be 0.70."""
        assert OpportunityDetector.UPDATE_THRESHOLD == 0.70

    def test_creation_threshold_higher_than_update(self) -> None:
        """Creation threshold must be higher than update threshold."""
        assert OpportunityDetector.CREATION_THRESHOLD > OpportunityDetector.UPDATE_THRESHOLD
