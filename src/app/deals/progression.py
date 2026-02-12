"""Evidence-based deal stage progression engine.

Evaluates BANT/MEDDIC qualification signals against stage-specific thresholds
and recommends stage advancement when evidence accumulates sufficiently. This
is the automation that turns manual pipeline management into intelligent
auto-progression.

The engine CONSUMES existing QualificationState data (tracked by Phase 4) --
it does NOT rebuild qualification. Stage transitions respect VALID_TRANSITIONS
from state_repository to prevent illegal jumps.

IMPORTANT: Terminal stages (CLOSED_WON, CLOSED_LOST) and STALLED are never
auto-progressed. NEGOTIATION does not auto-advance to close -- close decisions
are human-only.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from src.app.agents.sales.schemas import (
    DealStage,
    QualificationState,
)
from src.app.agents.sales.state_repository import (
    InvalidStageTransitionError,
    VALID_TRANSITIONS,
    validate_stage_transition,
)

logger = structlog.get_logger(__name__)

# ── Stage Pipeline Order ────────────────────────────────────────────────────

# Natural progression order (auto-progression stops at NEGOTIATION).
_STAGE_ORDER: list[DealStage] = [
    DealStage.PROSPECTING,
    DealStage.DISCOVERY,
    DealStage.QUALIFICATION,
    DealStage.EVALUATION,
    DealStage.NEGOTIATION,
]


# ── Stage Requirements ──────────────────────────────────────────────────────


class StageRequirements(BaseModel):
    """Minimum evidence thresholds for entering a deal stage.

    Each stage defines what qualification signals must be present before
    a deal can advance to that stage. Thresholds are progressive --
    later stages require more evidence.
    """

    min_bant_completion: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Minimum BANT completion score (0.0-1.0)"
    )
    min_meddic_completion: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Minimum MEDDIC completion score (0.0-1.0)"
    )
    min_interactions: int = Field(
        default=1, ge=0, description="Minimum number of interactions before entering this stage"
    )
    required_signals: list[str] = Field(
        default_factory=list,
        description="Names of qualification signals that must be identified",
    )


# Evidence requirements per stage (RESEARCH.md Pattern 6).
# Only stages that can be auto-entered are listed (DISCOVERY through NEGOTIATION).
STAGE_EVIDENCE_REQUIREMENTS: dict[DealStage, StageRequirements] = {
    DealStage.DISCOVERY: StageRequirements(
        min_bant_completion=0.0,
        min_meddic_completion=0.0,
        min_interactions=1,
        required_signals=["need_identified"],
    ),
    DealStage.QUALIFICATION: StageRequirements(
        min_bant_completion=0.25,
        min_meddic_completion=0.16,  # 1/6 MEDDIC = 0.1667; threshold just below
        min_interactions=2,
        required_signals=["need_identified", "pain_identified"],
    ),
    DealStage.EVALUATION: StageRequirements(
        min_bant_completion=0.50,
        min_meddic_completion=0.33,
        min_interactions=3,
        required_signals=["budget_identified", "authority_identified"],
    ),
    DealStage.NEGOTIATION: StageRequirements(
        min_bant_completion=0.75,
        min_meddic_completion=0.50,
        min_interactions=4,
        required_signals=["economic_buyer_identified", "decision_criteria_identified"],
    ),
}

# ── Signal Mapping ──────────────────────────────────────────────────────────

# Maps signal names to (framework, field_name) for qualification state lookup.
_SIGNAL_MAP: dict[str, tuple[str, str]] = {
    "need_identified": ("bant", "need_identified"),
    "budget_identified": ("bant", "budget_identified"),
    "authority_identified": ("bant", "authority_identified"),
    "timeline_identified": ("bant", "timeline_identified"),
    "pain_identified": ("meddic", "pain_identified"),
    "economic_buyer_identified": ("meddic", "economic_buyer_identified"),
    "decision_criteria_identified": ("meddic", "decision_criteria_identified"),
    "decision_process_identified": ("meddic", "decision_process_identified"),
    "metrics_identified": ("meddic", "metrics_identified"),
    "champion_identified": ("meddic", "champion_identified"),
}


# ── Progression Engine ──────────────────────────────────────────────────────


class StageProgressionEngine:
    """Evidence-based deal stage progression engine.

    Evaluates qualification signals against stage-specific thresholds and
    determines when a deal should advance to the next stage. Progression
    is always one step at a time (no stage skipping) and respects
    VALID_TRANSITIONS from state_repository.

    The engine handles PROSPECTING through NEGOTIATION auto-progression.
    Terminal stages (CLOSED_WON, CLOSED_LOST) and STALLED are never
    auto-progressed. NEGOTIATION does not auto-advance because close
    decisions require human judgment.
    """

    def __init__(self) -> None:
        self._requirements = STAGE_EVIDENCE_REQUIREMENTS

    def evaluate_progression(
        self,
        current_stage: DealStage,
        qualification: QualificationState,
        interaction_count: int,
    ) -> DealStage | None:
        """Evaluate whether a deal should advance to the next stage.

        Returns the next stage if evidence meets thresholds and the
        transition is valid, or None if no progression is warranted.

        Args:
            current_stage: Current deal stage.
            qualification: Current qualification state with BANT/MEDDIC signals.
            interaction_count: Number of interactions on this deal.

        Returns:
            Next DealStage if progression is warranted, None otherwise.
        """
        # Terminal and stalled stages never auto-progress
        next_stage = self._get_next_stage(current_stage)
        if next_stage is None:
            logger.debug(
                "No auto-progression available",
                current_stage=current_stage.value,
                reason="terminal_or_no_next",
            )
            return None

        # Check if evidence meets the next stage's requirements
        requirements = self._requirements.get(next_stage)
        if requirements is None:
            # No requirements defined for this stage (should not happen for
            # DISCOVERY through NEGOTIATION, but fail-safe)
            logger.warning(
                "No requirements defined for stage",
                stage=next_stage.value,
            )
            return None

        met, missing = self.check_requirements(
            next_stage, qualification, interaction_count
        )
        if not met:
            logger.debug(
                "Requirements not met for progression",
                current_stage=current_stage.value,
                target_stage=next_stage.value,
                missing=missing,
            )
            return None

        # Validate transition is allowed per VALID_TRANSITIONS
        try:
            validate_stage_transition(current_stage, next_stage)
        except InvalidStageTransitionError:
            logger.warning(
                "Stage transition not allowed",
                from_stage=current_stage.value,
                to_stage=next_stage.value,
            )
            return None

        logger.info(
            "Stage progression recommended",
            from_stage=current_stage.value,
            to_stage=next_stage.value,
            bant_completion=qualification.bant.completion_score,
            meddic_completion=qualification.meddic.completion_score,
            interaction_count=interaction_count,
        )
        return next_stage

    def check_requirements(
        self,
        stage: DealStage,
        qualification: QualificationState,
        interaction_count: int,
    ) -> tuple[bool, list[str]]:
        """Check if evidence meets a specific stage's requirements.

        Args:
            stage: Target stage to check requirements for.
            qualification: Current qualification state.
            interaction_count: Number of interactions on this deal.

        Returns:
            Tuple of (met: bool, missing: list[str]) where missing lists
            what requirements are not yet satisfied.
        """
        requirements = self._requirements.get(stage)
        if requirements is None:
            return False, [f"no requirements defined for stage: {stage.value}"]

        missing: list[str] = []

        # Check BANT completion
        bant_score = qualification.bant.completion_score
        if bant_score < requirements.min_bant_completion:
            missing.append(
                f"min_bant_completion: {requirements.min_bant_completion} required, "
                f"{bant_score} actual"
            )

        # Check MEDDIC completion
        meddic_score = qualification.meddic.completion_score
        if meddic_score < requirements.min_meddic_completion:
            missing.append(
                f"min_meddic_completion: {requirements.min_meddic_completion} required, "
                f"{meddic_score} actual"
            )

        # Check interaction count
        if interaction_count < requirements.min_interactions:
            missing.append(
                f"min_interactions: {requirements.min_interactions} required, "
                f"{interaction_count} actual"
            )

        # Check required signals
        for signal_name in requirements.required_signals:
            if not self._check_signal(signal_name, qualification):
                missing.append(f"required signal: {signal_name}")

        met = len(missing) == 0
        return met, missing

    def _get_next_stage(self, current: DealStage) -> DealStage | None:
        """Get the natural next stage in the pipeline.

        Returns the next stage in the progression order, or None for
        stages that cannot auto-progress (NEGOTIATION, terminal, STALLED).

        Progression order:
        PROSPECTING -> DISCOVERY -> QUALIFICATION -> EVALUATION -> NEGOTIATION

        NEGOTIATION does not auto-progress (close decisions are human-only).
        CLOSED_WON, CLOSED_LOST, STALLED return None.

        Args:
            current: Current deal stage.

        Returns:
            Next DealStage or None if no auto-progression available.
        """
        try:
            idx = _STAGE_ORDER.index(current)
        except ValueError:
            # Stage not in the auto-progression order (CLOSED_WON, CLOSED_LOST, STALLED)
            return None

        # NEGOTIATION is the last auto-progressable stage
        if idx >= len(_STAGE_ORDER) - 1:
            return None

        return _STAGE_ORDER[idx + 1]

    def _check_signal(
        self, signal_name: str, qualification: QualificationState
    ) -> bool:
        """Check if a named qualification signal has been identified.

        Maps signal names to the appropriate field in BANT or MEDDIC
        qualification state. Returns False for unknown signal names
        (fail-safe behavior).

        Args:
            signal_name: Name of the signal to check (e.g., "need_identified").
            qualification: Current qualification state.

        Returns:
            True if signal is identified, False otherwise (including unknown signals).
        """
        mapping = _SIGNAL_MAP.get(signal_name)
        if mapping is None:
            logger.warning(
                "Unknown signal name in check",
                signal_name=signal_name,
            )
            return False

        framework, field_name = mapping
        if framework == "bant":
            return bool(getattr(qualification.bant, field_name, False))
        elif framework == "meddic":
            return bool(getattr(qualification.meddic, field_name, False))

        return False
