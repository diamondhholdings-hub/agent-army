"""Pattern recognition engine -- orchestrates detectors for unified analysis.

The PatternRecognitionEngine runs all configured detectors in parallel against
a UnifiedCustomerView, filters results by confidence threshold and minimum
evidence count, and returns a severity-sorted list of PatternMatch objects.

Confidence threshold starts at 0.7 (per CONTEXT.md) and is tunable at runtime
based on feedback loop data. Minimum evidence count of 2 prevents false
positives from single data points (per RESEARCH.md Pitfall 2).
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional

import structlog

from src.app.intelligence.consolidation.schemas import UnifiedCustomerView
from src.app.intelligence.patterns.detectors import (
    BuyingSignalDetector,
    EngagementChangeDetector,
    RiskIndicatorDetector,
)
from src.app.intelligence.patterns.schemas import PatternMatch

logger = structlog.get_logger(__name__)

# Severity ordering for sort: lower index = higher priority
_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


class PatternRecognitionEngine:
    """Orchestrates pattern detectors for comprehensive signal detection.

    Runs all configured detectors in parallel against a customer view,
    merges results, and filters by confidence threshold and minimum
    evidence count.

    Args:
        detectors: List of detector instances (each must have an async
            ``detect(timeline, signals)`` method).
        confidence_threshold: Minimum confidence for returned patterns.
            Defaults to 0.7. Tunable via ``update_confidence_threshold``.
        min_evidence_count: Minimum evidence points per pattern.
            Defaults to 2 (per RESEARCH.md Pitfall 2).
    """

    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.7

    def __init__(
        self,
        detectors: List[Any],
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        min_evidence_count: int = 2,
    ) -> None:
        self._detectors = detectors
        self._confidence_threshold = confidence_threshold
        self._min_evidence_count = min_evidence_count

    @property
    def confidence_threshold(self) -> float:
        """Current confidence threshold."""
        return self._confidence_threshold

    async def detect_patterns(
        self, customer_view: UnifiedCustomerView
    ) -> List[PatternMatch]:
        """Run all detectors in parallel and return filtered, sorted results.

        Args:
            customer_view: Unified customer data assembled from all channels.

        Returns:
            List of PatternMatch objects sorted by severity (critical first),
            then by confidence (highest first). Only patterns meeting the
            confidence threshold and minimum evidence count are included.
        """
        timeline = customer_view.timeline
        signals = customer_view.signals

        # Run all detectors in parallel
        detector_tasks = [
            detector.detect(timeline, signals) for detector in self._detectors
        ]
        detector_results = await asyncio.gather(*detector_tasks, return_exceptions=True)

        # Merge all results, skipping failed detectors
        all_patterns: List[PatternMatch] = []
        for i, result in enumerate(detector_results):
            if isinstance(result, Exception):
                logger.warning(
                    "patterns.detector_failed",
                    detector_index=i,
                    error=str(result),
                )
                continue
            if isinstance(result, list):
                # Stamp account_id from customer view onto each pattern
                for pattern in result:
                    if not pattern.account_id:
                        pattern.account_id = customer_view.account_id
                all_patterns.extend(result)

        # Filter by confidence threshold
        filtered = [
            p for p in all_patterns if p.confidence >= self._confidence_threshold
        ]

        # Filter by minimum evidence count
        filtered = [
            p for p in filtered if len(p.evidence) >= self._min_evidence_count
        ]

        # Sort by severity (critical > high > medium > low), then confidence desc
        filtered.sort(
            key=lambda p: (
                _SEVERITY_ORDER.get(p.severity, 99),
                -p.confidence,
            )
        )

        logger.info(
            "patterns.detection_complete",
            account_id=customer_view.account_id,
            total_detected=len(all_patterns),
            after_filter=len(filtered),
            threshold=self._confidence_threshold,
        )

        return filtered

    async def scan_account(
        self,
        tenant_id: str,
        account_id: str,
        customer_view_service: Any,
    ) -> List[PatternMatch]:
        """Convenience method: fetch unified view then run detection.

        Args:
            tenant_id: Tenant identifier.
            account_id: Account to scan.
            customer_view_service: Service with ``get_unified_view(tenant_id, account_id)`` method.

        Returns:
            List of filtered, sorted PatternMatch objects.
        """
        try:
            view = await customer_view_service.get_unified_view(
                tenant_id, account_id
            )
            return await self.detect_patterns(view)
        except Exception:
            logger.warning(
                "patterns.account_scan_failed",
                tenant_id=tenant_id,
                account_id=account_id,
                exc_info=True,
            )
            return []

    def update_confidence_threshold(self, new_threshold: float) -> None:
        """Update the confidence threshold, clamped to [0.3, 0.95].

        Args:
            new_threshold: New threshold value. Will be clamped to
                valid range [0.3, 0.95].
        """
        old = self._confidence_threshold
        self._confidence_threshold = max(0.3, min(0.95, new_threshold))
        logger.info(
            "patterns.threshold_updated",
            old_threshold=old,
            new_threshold=self._confidence_threshold,
        )


def create_default_engine(
    llm_service: Optional[Any] = None,
) -> PatternRecognitionEngine:
    """Create a PatternRecognitionEngine with all 3 default detectors.

    Args:
        llm_service: Optional LLM service passed to each detector for
            enhanced detection. If None, detectors use rule-based only.

    Returns:
        Configured PatternRecognitionEngine ready for detection.
    """
    detectors = [
        BuyingSignalDetector(llm_service=llm_service),
        RiskIndicatorDetector(llm_service=llm_service),
        EngagementChangeDetector(llm_service=llm_service),
    ]
    return PatternRecognitionEngine(detectors=detectors)
