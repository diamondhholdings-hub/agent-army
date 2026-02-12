"""CalibrationEngine for per-action-type confidence calibration.

Maintains 10 calibration bins per action type, tracking predicted
confidence vs actual success rate. Computes Brier score for overall
calibration quality. Auto-adjusts agent behavior when miscalibration
is detected with damped corrections and hard bounds.

LOCKED decisions from CONTEXT.md:
- Per-action-type calibration (separate curves for each action type)
- Continuous updates (every outcome updates calibration)
- Auto-adjust behavior when miscalibration detected

Uses the session_factory callable pattern from ConversationStateRepository
for testable async database access with tenant isolation.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.learning.models import CalibrationBinModel
from src.app.learning.schemas import CalibrationAdjustment, CalibrationCurve

logger = structlog.get_logger(__name__)


class CalibrationEngine:
    """Per-action-type confidence calibration using binned averages.

    Maintains 10 calibration bins per action type, tracking predicted
    confidence vs actual success rate. Computes Brier score for
    overall calibration quality. Auto-adjusts agent behavior when
    miscalibration detected.
    """

    N_BINS = 10
    BIN_EDGES = np.linspace(0.0, 1.0, 11)  # 11 edges = 10 bins
    MIN_SAMPLES_PER_BIN = 10  # Pitfall 2: cold start protection
    MISCALIBRATION_THRESHOLD = 0.15  # >15% gap triggers adjustment
    MAX_ADJUSTMENT_RATE = 0.10  # Pitfall 5: max 10% correction per cycle
    SCALING_BOUNDS = (0.5, 1.5)  # Hard bounds on confidence scaling
    ESCALATION_BOUNDS = (0.3, 0.9)  # Hard bounds on escalation thresholds

    def __init__(
        self,
        session_factory: Callable[..., AsyncGenerator[AsyncSession, None]],
    ) -> None:
        """Accept session_factory callable."""
        self._session_factory = session_factory

    async def initialize_bins(self, tenant_id: str, action_type: str) -> None:
        """Create initial 10 calibration bins for an action type if they don't exist.

        Idempotent -- checks for existing bins before creating.
        Creates bins with bin_lower/bin_upper from BIN_EDGES.

        Args:
            tenant_id: Tenant UUID string.
            action_type: Action type to initialize bins for.
        """
        async for session in self._session_factory():
            # Check if bins already exist
            stmt = select(CalibrationBinModel).where(
                CalibrationBinModel.tenant_id == uuid.UUID(tenant_id),
                CalibrationBinModel.action_type == action_type,
            )
            result = await session.execute(stmt)
            existing = result.scalars().all()

            if len(existing) >= self.N_BINS:
                logger.debug(
                    "calibration.bins_already_exist",
                    tenant_id=tenant_id,
                    action_type=action_type,
                    count=len(existing),
                )
                return

            # Create bins
            for i in range(self.N_BINS):
                bin_lower = float(self.BIN_EDGES[i])
                bin_upper = float(self.BIN_EDGES[i + 1])

                model = CalibrationBinModel(
                    id=uuid.uuid4(),
                    tenant_id=uuid.UUID(tenant_id),
                    action_type=action_type,
                    bin_index=i,
                    bin_lower=bin_lower,
                    bin_upper=bin_upper,
                    sample_count=0,
                    outcome_sum=0.0,
                    actual_rate=None,
                    brier_contribution=None,
                )
                session.add(model)

            await session.commit()

            logger.info(
                "calibration.bins_initialized",
                tenant_id=tenant_id,
                action_type=action_type,
                bin_count=self.N_BINS,
            )

    async def update_calibration(
        self,
        tenant_id: str,
        action_type: str,
        predicted_confidence: float,
        actual_outcome: bool,
    ) -> None:
        """Update calibration bin for this action type (continuous update).

        1. Find the correct bin for predicted_confidence using np.digitize
        2. Increment sample_count
        3. Add to outcome_sum (1.0 if positive, 0.0 if negative)
        4. Recompute actual_rate = outcome_sum / sample_count
        5. Recompute brier_contribution = (predicted_midpoint - actual_rate)^2
        6. Persist to database

        Uses SELECT ... FOR UPDATE to prevent concurrent bin updates.

        Args:
            tenant_id: Tenant UUID string.
            action_type: Action type to update calibration for.
            predicted_confidence: The predicted confidence value (0.0-1.0).
            actual_outcome: True for positive outcome, False for negative.
        """
        # Clamp to valid range
        confidence = max(0.0, min(1.0, predicted_confidence))

        # Find bin index using np.digitize (returns 1-based, so subtract 1)
        # np.digitize with right=False: bin i contains [edge_i, edge_i+1)
        bin_idx = int(np.digitize(confidence, self.BIN_EDGES[1:]))
        # Clamp to valid range [0, N_BINS-1]
        bin_idx = max(0, min(self.N_BINS - 1, bin_idx))

        outcome_value = 1.0 if actual_outcome else 0.0

        async for session in self._session_factory():
            # Ensure bins exist
            await self.initialize_bins(tenant_id, action_type)

            # SELECT FOR UPDATE to prevent concurrent modification
            stmt = (
                select(CalibrationBinModel)
                .where(
                    CalibrationBinModel.tenant_id == uuid.UUID(tenant_id),
                    CalibrationBinModel.action_type == action_type,
                    CalibrationBinModel.bin_index == bin_idx,
                )
                .with_for_update()
            )
            result = await session.execute(stmt)
            bin_model = result.scalar_one_or_none()

            if bin_model is None:
                logger.warning(
                    "calibration.bin_not_found",
                    tenant_id=tenant_id,
                    action_type=action_type,
                    bin_index=bin_idx,
                )
                return

            # Update bin statistics
            bin_model.sample_count += 1
            bin_model.outcome_sum += outcome_value
            bin_model.actual_rate = bin_model.outcome_sum / bin_model.sample_count

            # Compute Brier contribution using bin midpoint
            midpoint = (bin_model.bin_lower + bin_model.bin_upper) / 2.0
            bin_model.brier_contribution = (midpoint - bin_model.actual_rate) ** 2
            bin_model.last_updated = datetime.now(timezone.utc)

            await session.commit()

            logger.debug(
                "calibration.bin_updated",
                tenant_id=tenant_id,
                action_type=action_type,
                bin_index=bin_idx,
                sample_count=bin_model.sample_count,
                actual_rate=bin_model.actual_rate,
            )

    async def get_calibration_curve(
        self, tenant_id: str, action_type: str
    ) -> CalibrationCurve:
        """Return calibration curve data for an action type.

        Loads all bins, filters to those with sample_count >= MIN_SAMPLES_PER_BIN.
        Returns CalibrationCurve with midpoints, actual_rates, counts, brier_score.

        Args:
            tenant_id: Tenant UUID string.
            action_type: Action type to get calibration curve for.

        Returns:
            CalibrationCurve schema with curve data.
        """
        async for session in self._session_factory():
            stmt = (
                select(CalibrationBinModel)
                .where(
                    CalibrationBinModel.tenant_id == uuid.UUID(tenant_id),
                    CalibrationBinModel.action_type == action_type,
                )
                .order_by(CalibrationBinModel.bin_index)
            )
            result = await session.execute(stmt)
            bins = result.scalars().all()

            midpoints = []
            actual_rates = []
            counts = []

            for b in bins:
                if b.sample_count >= self.MIN_SAMPLES_PER_BIN:
                    midpoint = (b.bin_lower + b.bin_upper) / 2.0
                    midpoints.append(midpoint)
                    actual_rates.append(b.actual_rate or 0.0)
                    counts.append(b.sample_count)

            # Compute Brier score from qualifying bins
            brier = 0.0
            if midpoints:
                predicted = np.array(midpoints)
                actual = np.array(actual_rates)
                weights = np.array(counts, dtype=float)
                gaps_sq = (predicted - actual) ** 2
                brier = float(np.average(gaps_sq, weights=weights))

            return CalibrationCurve(
                action_type=action_type,
                midpoints=midpoints,
                actual_rates=actual_rates,
                counts=counts,
                brier_score=round(brier, 6),
            )

        # Should not reach here
        return CalibrationCurve(action_type=action_type)  # pragma: no cover

    async def compute_brier_score(
        self, tenant_id: str, action_type: str
    ) -> float:
        """Compute overall Brier score from calibration bins.

        Brier = weighted mean of per-bin (midpoint - actual_rate)^2,
        weighted by sample_count. Returns 0.25 (random guessing baseline)
        if no data.

        Uses numpy: np.average(gaps**2, weights=counts)

        Args:
            tenant_id: Tenant UUID string.
            action_type: Action type to compute Brier score for.

        Returns:
            Brier score float. 0.0 is perfect, 0.25 is random guessing.
        """
        curve = await self.get_calibration_curve(tenant_id, action_type)

        if not curve.midpoints:
            return 0.25  # No data baseline

        return curve.brier_score

    async def check_and_adjust(
        self, tenant_id: str, action_type: str
    ) -> CalibrationAdjustment | None:
        """Check calibration and recommend/apply damped adjustment.

        For each bin with enough samples:
        - gap = predicted_midpoint - actual_rate
        - If |gap| > MISCALIBRATION_THRESHOLD: flag

        If overconfident (predicted > actual): reduce confidence scaling
        If underconfident (predicted < actual): increase confidence scaling

        Apply damped adjustment: adjust by min(gap, MAX_ADJUSTMENT_RATE).
        Clamp to SCALING_BOUNDS and ESCALATION_BOUNDS.

        Args:
            tenant_id: Tenant UUID string.
            action_type: Action type to check calibration for.

        Returns:
            CalibrationAdjustment if adjustment applied, None if calibrated.
        """
        async for session in self._session_factory():
            stmt = (
                select(CalibrationBinModel)
                .where(
                    CalibrationBinModel.tenant_id == uuid.UUID(tenant_id),
                    CalibrationBinModel.action_type == action_type,
                )
                .order_by(CalibrationBinModel.bin_index)
            )
            result = await session.execute(stmt)
            bins = result.scalars().all()

            # Only use bins with sufficient samples (cold start protection)
            qualifying_bins = [
                b for b in bins if b.sample_count >= self.MIN_SAMPLES_PER_BIN
            ]

            if not qualifying_bins:
                return None

            # Compute weighted average gap
            total_gap = 0.0
            total_weight = 0
            for b in qualifying_bins:
                midpoint = (b.bin_lower + b.bin_upper) / 2.0
                actual = b.actual_rate or 0.0
                gap = midpoint - actual
                total_gap += gap * b.sample_count
                total_weight += b.sample_count

            if total_weight == 0:
                return None

            avg_gap = total_gap / total_weight

            # Check if miscalibration exceeds threshold
            if abs(avg_gap) <= self.MISCALIBRATION_THRESHOLD:
                return None

            # Determine direction and apply damped adjustment
            if avg_gap > 0:
                # Overconfident: predicted > actual, need to decrease
                direction = "decrease"
                magnitude = min(abs(avg_gap), self.MAX_ADJUSTMENT_RATE)
                old_threshold = 1.0  # Baseline scaling factor
                new_threshold = max(
                    self.SCALING_BOUNDS[0],
                    old_threshold - magnitude,
                )
            else:
                # Underconfident: predicted < actual, need to increase
                direction = "increase"
                magnitude = min(abs(avg_gap), self.MAX_ADJUSTMENT_RATE)
                old_threshold = 1.0
                new_threshold = min(
                    self.SCALING_BOUNDS[1],
                    old_threshold + magnitude,
                )

            # Clamp to bounds
            new_threshold = max(
                self.SCALING_BOUNDS[0],
                min(self.SCALING_BOUNDS[1], new_threshold),
            )

            reason = (
                f"Average gap of {avg_gap:.3f} across {len(qualifying_bins)} bins "
                f"({total_weight} samples) exceeds threshold of "
                f"{self.MISCALIBRATION_THRESHOLD}. Agent is "
                f"{'overconfident' if avg_gap > 0 else 'underconfident'}."
            )

            logger.info(
                "calibration.adjustment_applied",
                tenant_id=tenant_id,
                action_type=action_type,
                direction=direction,
                magnitude=magnitude,
                avg_gap=avg_gap,
                qualifying_bins=len(qualifying_bins),
            )

            return CalibrationAdjustment(
                action_type=action_type,
                direction=direction,
                magnitude=round(magnitude, 4),
                old_threshold=old_threshold,
                new_threshold=round(new_threshold, 4),
                reason=reason,
            )

        return None  # pragma: no cover

    async def get_all_action_types(self, tenant_id: str) -> list[str]:
        """Get all action types that have calibration bins for this tenant.

        Args:
            tenant_id: Tenant UUID string.

        Returns:
            List of distinct action type strings.
        """
        async for session in self._session_factory():
            stmt = (
                select(CalibrationBinModel.action_type)
                .where(
                    CalibrationBinModel.tenant_id == uuid.UUID(tenant_id),
                )
                .distinct()
            )
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

        return []  # pragma: no cover

    @staticmethod
    def brier_score(predicted: np.ndarray, actual: np.ndarray) -> float:
        """Compute Brier score from arrays. Lower is better. 0.0=perfect, 0.25=random.

        Args:
            predicted: Array of predicted probabilities.
            actual: Array of actual outcomes (0 or 1).

        Returns:
            Brier score float.
        """
        if len(predicted) == 0:
            return 0.25
        return float(np.mean((predicted - actual) ** 2))

    @staticmethod
    def calibration_curve_from_arrays(
        predicted: np.ndarray, actual: np.ndarray, n_bins: int = 10
    ) -> dict:
        """Compute calibration curve from raw prediction/outcome arrays.

        Returns dict with midpoints, actual_rates, counts, brier_score.
        Used for bulk computation (e.g., from outcome records directly).

        Args:
            predicted: Array of predicted probabilities.
            actual: Array of actual outcomes (0 or 1).
            n_bins: Number of bins (default 10).

        Returns:
            Dict with keys: midpoints, actual_rates, counts, brier_score.
        """
        if len(predicted) == 0:
            return {
                "midpoints": [],
                "actual_rates": [],
                "counts": [],
                "brier_score": 0.25,
            }

        edges = np.linspace(0.0, 1.0, n_bins + 1)
        midpoints = []
        actual_rates = []
        counts = []

        for i in range(n_bins):
            mask = (predicted >= edges[i]) & (predicted < edges[i + 1])
            # Include right edge for last bin
            if i == n_bins - 1:
                mask = (predicted >= edges[i]) & (predicted <= edges[i + 1])

            count = int(np.sum(mask))
            if count > 0:
                midpoints.append(float((edges[i] + edges[i + 1]) / 2.0))
                actual_rates.append(float(np.mean(actual[mask])))
                counts.append(count)

        brier = float(np.mean((predicted - actual) ** 2))

        return {
            "midpoints": midpoints,
            "actual_rates": actual_rates,
            "counts": counts,
            "brier_score": round(brier, 6),
        }
