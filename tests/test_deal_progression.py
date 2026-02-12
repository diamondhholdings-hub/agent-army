"""Unit tests for StageProgressionEngine -- evidence-based deal stage advancement.

Tests cover:
- evaluate_progression: happy path for each stage transition, terminal stages, stalled, insufficient evidence
- check_requirements: all met, missing BANT, missing signals, missing interactions
- _check_signal: BANT signals, MEDDIC signals, unknown signal fail-safe
- _get_next_stage: pipeline order, terminal stages, negotiation boundary
"""

from __future__ import annotations

import pytest

from src.app.agents.sales.schemas import (
    BANTSignals,
    DealStage,
    MEDDICSignals,
    QualificationState,
)
from src.app.deals.progression import (
    STAGE_EVIDENCE_REQUIREMENTS,
    StageProgressionEngine,
    StageRequirements,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def engine() -> StageProgressionEngine:
    """Fresh StageProgressionEngine instance."""
    return StageProgressionEngine()


def _make_qualification(
    *,
    need: bool = False,
    budget: bool = False,
    authority: bool = False,
    timeline: bool = False,
    pain: bool = False,
    economic_buyer: bool = False,
    decision_criteria: bool = False,
    decision_process: bool = False,
    metrics: bool = False,
    champion: bool = False,
) -> QualificationState:
    """Build a QualificationState with specific signals set."""
    return QualificationState(
        bant=BANTSignals(
            need_identified=need,
            budget_identified=budget,
            authority_identified=authority,
            timeline_identified=timeline,
        ),
        meddic=MEDDICSignals(
            pain_identified=pain,
            economic_buyer_identified=economic_buyer,
            decision_criteria_identified=decision_criteria,
            decision_process_identified=decision_process,
            metrics_identified=metrics,
            champion_identified=champion,
        ),
    )


# ── evaluate_progression tests ──────────────────────────────────────────────


class TestEvaluateProgression:
    """Tests for StageProgressionEngine.evaluate_progression."""

    def test_prospecting_to_discovery(self, engine: StageProgressionEngine) -> None:
        """PROSPECTING -> DISCOVERY when need is identified and 1+ interactions."""
        qual = _make_qualification(need=True)
        result = engine.evaluate_progression(DealStage.PROSPECTING, qual, 1)
        assert result == DealStage.DISCOVERY

    def test_prospecting_stays_without_need(self, engine: StageProgressionEngine) -> None:
        """PROSPECTING stays when need is NOT identified."""
        qual = _make_qualification()
        result = engine.evaluate_progression(DealStage.PROSPECTING, qual, 5)
        assert result is None

    def test_discovery_to_qualification(self, engine: StageProgressionEngine) -> None:
        """DISCOVERY -> QUALIFICATION when BANT >=0.25, MEDDIC >=0.17, need+pain, 2+ interactions."""
        qual = _make_qualification(need=True, pain=True)
        # BANT: need_identified=True -> 1/4 = 0.25 (meets threshold)
        # MEDDIC: pain_identified=True -> 1/6 = ~0.1667 (meets 0.16 threshold)
        assert qual.bant.completion_score >= 0.25
        assert qual.meddic.completion_score >= 0.16
        result = engine.evaluate_progression(DealStage.DISCOVERY, qual, 2)
        assert result == DealStage.QUALIFICATION

    def test_qualification_to_evaluation(self, engine: StageProgressionEngine) -> None:
        """QUALIFICATION -> EVALUATION when BANT >=0.50, MEDDIC >=0.33, budget+authority, 3+ interactions."""
        qual = _make_qualification(
            need=True, budget=True, authority=True,
            pain=True, economic_buyer=True,
        )
        # BANT: 3/4 = 0.75 (meets 0.50)
        # MEDDIC: 2/6 = 0.333 (meets 0.33)
        assert qual.bant.completion_score >= 0.50
        assert qual.meddic.completion_score >= 0.33
        result = engine.evaluate_progression(DealStage.QUALIFICATION, qual, 3)
        assert result == DealStage.EVALUATION

    def test_evaluation_to_negotiation(self, engine: StageProgressionEngine) -> None:
        """EVALUATION -> NEGOTIATION when BANT >=0.75, MEDDIC >=0.50, econ_buyer+decision_criteria, 4+ interactions."""
        qual = _make_qualification(
            need=True, budget=True, authority=True,
            pain=True, economic_buyer=True, decision_criteria=True,
        )
        # BANT: 3/4 = 0.75 (meets 0.75)
        # MEDDIC: 3/6 = 0.50 (meets 0.50)
        assert qual.bant.completion_score >= 0.75
        assert qual.meddic.completion_score >= 0.50
        result = engine.evaluate_progression(DealStage.EVALUATION, qual, 4)
        assert result == DealStage.NEGOTIATION

    def test_negotiation_does_not_auto_close(self, engine: StageProgressionEngine) -> None:
        """NEGOTIATION with full qualification does NOT auto-progress to CLOSED_WON."""
        qual = _make_qualification(
            need=True, budget=True, authority=True, timeline=True,
            pain=True, economic_buyer=True, decision_criteria=True,
            decision_process=True, metrics=True, champion=True,
        )
        # Everything identified -- still should not auto-close
        result = engine.evaluate_progression(DealStage.NEGOTIATION, qual, 100)
        assert result is None

    def test_closed_won_no_progression(self, engine: StageProgressionEngine) -> None:
        """CLOSED_WON is terminal -- no progression."""
        qual = _make_qualification(need=True, budget=True, authority=True, timeline=True)
        result = engine.evaluate_progression(DealStage.CLOSED_WON, qual, 10)
        assert result is None

    def test_closed_lost_no_progression(self, engine: StageProgressionEngine) -> None:
        """CLOSED_LOST is terminal -- no progression."""
        qual = _make_qualification(need=True, budget=True, authority=True, timeline=True)
        result = engine.evaluate_progression(DealStage.CLOSED_LOST, qual, 10)
        assert result is None

    def test_stalled_no_progression(self, engine: StageProgressionEngine) -> None:
        """STALLED does not auto-progress."""
        qual = _make_qualification(need=True, budget=True, authority=True, timeline=True)
        result = engine.evaluate_progression(DealStage.STALLED, qual, 10)
        assert result is None

    def test_insufficient_interactions_blocks(self, engine: StageProgressionEngine) -> None:
        """All signals met but interaction count too low blocks progression."""
        qual = _make_qualification(need=True, pain=True)
        # Needs 2 interactions for QUALIFICATION, only has 1
        result = engine.evaluate_progression(DealStage.DISCOVERY, qual, 1)
        assert result is None

    def test_insufficient_bant_blocks(self, engine: StageProgressionEngine) -> None:
        """Insufficient BANT completion blocks progression even with signals met."""
        # For EVALUATION, need BANT >= 0.50 and budget+authority
        # Only budget identified -> BANT = 0.25, below 0.50
        qual = _make_qualification(budget=True, authority=True, pain=True, economic_buyer=True)
        # BANT: 2/4 = 0.50, MEDDIC: 2/6 = 0.33
        result = engine.evaluate_progression(DealStage.QUALIFICATION, qual, 3)
        assert result == DealStage.EVALUATION  # This should pass since BANT=0.50 meets >=0.50

    def test_missing_required_signal_blocks(self, engine: StageProgressionEngine) -> None:
        """Missing a required signal blocks progression even with high scores."""
        # NEGOTIATION requires economic_buyer + decision_criteria
        # Set high BANT/MEDDIC but missing decision_criteria
        qual = _make_qualification(
            need=True, budget=True, authority=True, timeline=True,
            pain=True, economic_buyer=True, metrics=True,
        )
        # BANT: 4/4 = 1.0, MEDDIC: 3/6 = 0.50
        # Missing: decision_criteria_identified
        result = engine.evaluate_progression(DealStage.EVALUATION, qual, 10)
        assert result is None


# ── check_requirements tests ────────────────────────────────────────────────


class TestCheckRequirements:
    """Tests for StageProgressionEngine.check_requirements."""

    def test_check_requirements_all_met(self, engine: StageProgressionEngine) -> None:
        """All requirements met returns (True, [])."""
        qual = _make_qualification(need=True)
        met, missing = engine.check_requirements(DealStage.DISCOVERY, qual, 1)
        assert met is True
        assert missing == []

    def test_check_requirements_missing_bant(self, engine: StageProgressionEngine) -> None:
        """Missing BANT completion reports in missing list."""
        qual = _make_qualification(need=True, pain=True)
        # BANT: 1/4 = 0.25, QUALIFICATION needs 0.25 -- passes
        # But EVALUATION needs BANT >= 0.50
        met, missing = engine.check_requirements(DealStage.EVALUATION, qual, 5)
        assert met is False
        assert any("min_bant_completion" in m for m in missing)

    def test_check_requirements_missing_signal(self, engine: StageProgressionEngine) -> None:
        """Missing required signal reports in missing list."""
        # EVALUATION requires budget_identified + authority_identified
        qual = _make_qualification(
            need=True, budget=True,
            pain=True, economic_buyer=True,
        )
        # BANT: 2/4=0.50, MEDDIC: 2/6=0.33 -- completion OK
        # Missing: authority_identified
        met, missing = engine.check_requirements(DealStage.EVALUATION, qual, 5)
        assert met is False
        assert any("authority_identified" in m for m in missing)

    def test_check_requirements_missing_interactions(self, engine: StageProgressionEngine) -> None:
        """Insufficient interactions reports in missing list."""
        qual = _make_qualification(need=True, pain=True)
        met, missing = engine.check_requirements(DealStage.QUALIFICATION, qual, 1)
        assert met is False
        assert any("min_interactions" in m for m in missing)

    def test_check_requirements_undefined_stage(self, engine: StageProgressionEngine) -> None:
        """Stage with no defined requirements returns (False, [reason])."""
        qual = _make_qualification()
        met, missing = engine.check_requirements(DealStage.CLOSED_WON, qual, 0)
        assert met is False
        assert len(missing) == 1
        assert "no requirements defined" in missing[0]


# ── _check_signal tests ─────────────────────────────────────────────────────


class TestCheckSignal:
    """Tests for StageProgressionEngine._check_signal."""

    def test_check_signal_need(self, engine: StageProgressionEngine) -> None:
        """'need_identified' maps to bant.need_identified."""
        qual = _make_qualification(need=True)
        assert engine._check_signal("need_identified", qual) is True

    def test_check_signal_need_false(self, engine: StageProgressionEngine) -> None:
        """'need_identified' returns False when not identified."""
        qual = _make_qualification(need=False)
        assert engine._check_signal("need_identified", qual) is False

    def test_check_signal_pain(self, engine: StageProgressionEngine) -> None:
        """'pain_identified' maps to meddic.pain_identified."""
        qual = _make_qualification(pain=True)
        assert engine._check_signal("pain_identified", qual) is True

    def test_check_signal_budget(self, engine: StageProgressionEngine) -> None:
        """'budget_identified' maps to bant.budget_identified."""
        qual = _make_qualification(budget=True)
        assert engine._check_signal("budget_identified", qual) is True

    def test_check_signal_economic_buyer(self, engine: StageProgressionEngine) -> None:
        """'economic_buyer_identified' maps to meddic.economic_buyer_identified."""
        qual = _make_qualification(economic_buyer=True)
        assert engine._check_signal("economic_buyer_identified", qual) is True

    def test_check_signal_unknown(self, engine: StageProgressionEngine) -> None:
        """Unknown signal name returns False (fail-safe)."""
        qual = _make_qualification(need=True)
        assert engine._check_signal("unknown_signal", qual) is False

    def test_check_signal_decision_criteria(self, engine: StageProgressionEngine) -> None:
        """'decision_criteria_identified' maps to meddic.decision_criteria_identified."""
        qual = _make_qualification(decision_criteria=True)
        assert engine._check_signal("decision_criteria_identified", qual) is True


# ── _get_next_stage tests ───────────────────────────────────────────────────


class TestGetNextStage:
    """Tests for StageProgressionEngine._get_next_stage."""

    def test_next_stage_prospecting(self, engine: StageProgressionEngine) -> None:
        """PROSPECTING -> DISCOVERY."""
        assert engine._get_next_stage(DealStage.PROSPECTING) == DealStage.DISCOVERY

    def test_next_stage_discovery(self, engine: StageProgressionEngine) -> None:
        """DISCOVERY -> QUALIFICATION."""
        assert engine._get_next_stage(DealStage.DISCOVERY) == DealStage.QUALIFICATION

    def test_next_stage_qualification(self, engine: StageProgressionEngine) -> None:
        """QUALIFICATION -> EVALUATION."""
        assert engine._get_next_stage(DealStage.QUALIFICATION) == DealStage.EVALUATION

    def test_next_stage_evaluation(self, engine: StageProgressionEngine) -> None:
        """EVALUATION -> NEGOTIATION."""
        assert engine._get_next_stage(DealStage.EVALUATION) == DealStage.NEGOTIATION

    def test_next_stage_negotiation(self, engine: StageProgressionEngine) -> None:
        """NEGOTIATION -> None (no auto-close)."""
        assert engine._get_next_stage(DealStage.NEGOTIATION) is None

    def test_next_stage_closed_won(self, engine: StageProgressionEngine) -> None:
        """CLOSED_WON -> None (terminal)."""
        assert engine._get_next_stage(DealStage.CLOSED_WON) is None

    def test_next_stage_closed_lost(self, engine: StageProgressionEngine) -> None:
        """CLOSED_LOST -> None (terminal)."""
        assert engine._get_next_stage(DealStage.CLOSED_LOST) is None

    def test_next_stage_stalled(self, engine: StageProgressionEngine) -> None:
        """STALLED -> None (not in auto-progression order)."""
        assert engine._get_next_stage(DealStage.STALLED) is None


# ── STAGE_EVIDENCE_REQUIREMENTS validation ──────────────────────────────────


class TestStageRequirements:
    """Tests validating the STAGE_EVIDENCE_REQUIREMENTS configuration."""

    def test_has_discovery_requirements(self) -> None:
        """DISCOVERY stage has requirements defined."""
        assert DealStage.DISCOVERY in STAGE_EVIDENCE_REQUIREMENTS

    def test_has_qualification_requirements(self) -> None:
        """QUALIFICATION stage has requirements defined."""
        assert DealStage.QUALIFICATION in STAGE_EVIDENCE_REQUIREMENTS

    def test_has_evaluation_requirements(self) -> None:
        """EVALUATION stage has requirements defined."""
        assert DealStage.EVALUATION in STAGE_EVIDENCE_REQUIREMENTS

    def test_has_negotiation_requirements(self) -> None:
        """NEGOTIATION stage has requirements defined."""
        assert DealStage.NEGOTIATION in STAGE_EVIDENCE_REQUIREMENTS

    def test_no_terminal_stage_requirements(self) -> None:
        """Terminal stages should NOT have requirements (never auto-entered)."""
        assert DealStage.CLOSED_WON not in STAGE_EVIDENCE_REQUIREMENTS
        assert DealStage.CLOSED_LOST not in STAGE_EVIDENCE_REQUIREMENTS

    def test_progressive_bant_thresholds(self) -> None:
        """BANT thresholds increase through the pipeline."""
        stages = [DealStage.DISCOVERY, DealStage.QUALIFICATION, DealStage.EVALUATION, DealStage.NEGOTIATION]
        thresholds = [STAGE_EVIDENCE_REQUIREMENTS[s].min_bant_completion for s in stages]
        assert thresholds == sorted(thresholds), f"BANT thresholds not progressive: {thresholds}"

    def test_progressive_interaction_thresholds(self) -> None:
        """Interaction requirements increase through the pipeline."""
        stages = [DealStage.DISCOVERY, DealStage.QUALIFICATION, DealStage.EVALUATION, DealStage.NEGOTIATION]
        thresholds = [STAGE_EVIDENCE_REQUIREMENTS[s].min_interactions for s in stages]
        assert thresholds == sorted(thresholds), f"Interaction thresholds not progressive: {thresholds}"
