"""Pattern detectors for buying signals, risk indicators, and engagement changes.

Each detector analyzes customer timeline data for specific signal types using
a hybrid approach: rule-based checks for obvious patterns + optional LLM-enhanced
detection for nuanced signals.

All detectors return empty lists on errors (fail-open pattern, consistent with
02-03/04-04 approach). LLM failures are logged as warnings.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

from src.app.intelligence.consolidation.schemas import ChannelInteraction
from src.app.intelligence.patterns.schemas import PatternMatch, PatternType

logger = structlog.get_logger(__name__)


class BuyingSignalDetector:
    """Detects buying signals from customer interaction timeline.

    Analyzes content summaries and key points for indicators of purchase
    intent: budget mentions, timeline urgency, competitive evaluation,
    and stakeholder expansion.

    Args:
        llm_service: Optional LLM service for enhanced detection via
            instructor structured extraction. If None, only rule-based
            detection is used.
    """

    # Rule-based pattern definitions
    BUDGET_PATTERNS = re.compile(
        r"\b(budget|funding|approved|allocated)\b|"
        r"\$\d",
        re.IGNORECASE,
    )
    TIMELINE_PATTERNS = re.compile(
        r"\b(this quarter|by end of|deadline|urgent|asap|time.?sensitive|"
        r"q[1-4]\b|before \w+ ends)",
        re.IGNORECASE,
    )
    COMPETITIVE_PATTERNS = re.compile(
        r"\b(comparing|alternative|other vendor|shortlist|"
        r"competitor|evaluation|bake.?off|rfi|rfp)\b",
        re.IGNORECASE,
    )

    def __init__(self, llm_service: Optional[Any] = None) -> None:
        self._llm_service = llm_service

    async def detect(
        self,
        timeline: List[ChannelInteraction],
        signals: Dict[str, Any],
    ) -> List[PatternMatch]:
        """Detect buying signals from timeline and extracted signals.

        Args:
            timeline: Chronological list of customer interactions.
            signals: Extracted signals dict from UnifiedCustomerView.

        Returns:
            List of PatternMatch objects for detected buying signals.
        """
        try:
            return await self._detect_internal(timeline, signals)
        except Exception:
            logger.warning(
                "patterns.buying_signal_detection_failed",
                exc_info=True,
            )
            return []

    async def _detect_internal(
        self,
        timeline: List[ChannelInteraction],
        signals: Dict[str, Any],
    ) -> List[PatternMatch]:
        """Internal detection logic."""
        if not timeline:
            return []

        now = datetime.now(timezone.utc)
        results: List[PatternMatch] = []

        # Collect all text content for scanning
        for interaction in timeline:
            text = interaction.content_summary
            key_points_text = " ".join(interaction.key_points)
            combined = f"{text} {key_points_text}"

            # Budget mention detection
            if self.BUDGET_PATTERNS.search(combined):
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.buying_signal,
                        confidence=0.8,
                        severity="high",
                        evidence=[
                            f"Budget-related content in {interaction.channel}: "
                            f'"{text[:120]}"'
                        ],
                        detected_at=now,
                        account_id="",  # Set by engine
                    )
                )

            # Timeline urgency detection
            if self.TIMELINE_PATTERNS.search(combined):
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.buying_signal,
                        confidence=0.75,
                        severity="medium",
                        evidence=[
                            f"Timeline urgency in {interaction.channel}: "
                            f'"{text[:120]}"'
                        ],
                        detected_at=now,
                        account_id="",
                    )
                )

            # Competitive evaluation detection
            if self.COMPETITIVE_PATTERNS.search(combined):
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.buying_signal,
                        confidence=0.7,
                        severity="medium",
                        evidence=[
                            f"Competitive evaluation in {interaction.channel}: "
                            f'"{text[:120]}"'
                        ],
                        detected_at=now,
                        account_id="",
                    )
                )

        # Stakeholder expansion detection
        if len(timeline) >= 2:
            # Compare unique participant counts in first vs second half
            midpoint = len(timeline) // 2
            early_participants = set()
            for interaction in timeline[:midpoint]:
                early_participants.update(interaction.participants)

            late_participants = set()
            for interaction in timeline[midpoint:]:
                late_participants.update(interaction.participants)

            new_stakeholders = late_participants - early_participants
            if len(new_stakeholders) >= 2:
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.buying_signal,
                        confidence=0.65,
                        severity="medium",
                        evidence=[
                            f"Stakeholder expansion: {len(new_stakeholders)} new "
                            f"participants joined ({', '.join(list(new_stakeholders)[:3])})"
                        ],
                        detected_at=now,
                        account_id="",
                    )
                )

        # LLM-enhanced detection (if service available)
        if self._llm_service is not None:
            llm_patterns = await self._llm_detect(timeline)
            results = self._merge_patterns(results, llm_patterns)

        return results

    async def _llm_detect(
        self, timeline: List[ChannelInteraction]
    ) -> List[PatternMatch]:
        """Use LLM for nuanced buying signal detection on recent interactions."""
        try:
            recent = timeline[-10:]  # Last 10 interactions
            summaries = [
                f"[{i.channel} {i.timestamp.isoformat()[:10]}] {i.content_summary}"
                for i in recent
            ]
            text_block = "\n".join(summaries)

            response = await self._llm_service.completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a sales intelligence analyst. Analyze the "
                            "following customer interactions for buying signals "
                            "that rule-based detection might miss. Return only "
                            "clear, high-confidence signals."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Analyze for buying signals:\n\n{text_block}",
                    },
                ],
                model="fast",
                response_model=List[PatternMatch],
            )
            return response if isinstance(response, list) else []
        except Exception:
            logger.warning(
                "patterns.buying_signal_llm_detection_failed",
                exc_info=True,
            )
            return []

    @staticmethod
    def _merge_patterns(
        rule_based: List[PatternMatch],
        llm_based: List[PatternMatch],
    ) -> List[PatternMatch]:
        """Merge rule-based and LLM results, deduplicating by evidence overlap."""
        if not llm_based:
            return rule_based

        # Simple dedup: if LLM pattern's evidence overlaps with existing, skip
        existing_evidence = set()
        for p in rule_based:
            for e in p.evidence:
                existing_evidence.add(e[:50].lower())

        for p in llm_based:
            is_dup = False
            for e in p.evidence:
                if e[:50].lower() in existing_evidence:
                    is_dup = True
                    break
            if not is_dup:
                rule_based.append(p)

        return rule_based


class RiskIndicatorDetector:
    """Detects risk indicators from customer interaction timeline.

    Analyzes for warning signs: radio silence, delayed responses, budget
    freezes, champion departure, and competitor preference.

    Args:
        llm_service: Optional LLM service for enhanced detection.
    """

    BUDGET_FREEZE_PATTERNS = re.compile(
        r"\b(freeze|frozen|cut|hold|postpone|pause|defer|"
        r"budget.?constraint|no.?budget)\b",
        re.IGNORECASE,
    )
    CHAMPION_DEPARTURE_PATTERNS = re.compile(
        r"\b(leaving|left the company|new role|transition|"
        r"moving on|departing|resigned|replaced)\b",
        re.IGNORECASE,
    )
    COMPETITOR_PREFERENCE_PATTERNS = re.compile(
        r"\b(prefer|leaning toward|better fit|went with|"
        r"chose|selected|deciding on)\b",
        re.IGNORECASE,
    )

    RADIO_SILENCE_DAYS = 14
    RESPONSE_TIME_INCREASE_THRESHOLD = 0.5  # 50% increase

    def __init__(self, llm_service: Optional[Any] = None) -> None:
        self._llm_service = llm_service

    async def detect(
        self,
        timeline: List[ChannelInteraction],
        signals: Dict[str, Any],
    ) -> List[PatternMatch]:
        """Detect risk indicators from timeline and signals.

        Args:
            timeline: Chronological list of customer interactions.
            signals: Extracted signals dict from UnifiedCustomerView.

        Returns:
            List of PatternMatch objects for detected risk indicators.
        """
        try:
            return await self._detect_internal(timeline, signals)
        except Exception:
            logger.warning(
                "patterns.risk_indicator_detection_failed",
                exc_info=True,
            )
            return []

    async def _detect_internal(
        self,
        timeline: List[ChannelInteraction],
        signals: Dict[str, Any],
    ) -> List[PatternMatch]:
        """Internal detection logic."""
        if not timeline:
            return []

        now = datetime.now(timezone.utc)
        results: List[PatternMatch] = []

        # Radio silence detection: no interactions in last 14 days
        most_recent = max(timeline, key=lambda x: x.timestamp)
        days_since_last = (now - most_recent.timestamp).days
        if days_since_last >= self.RADIO_SILENCE_DAYS:
            results.append(
                PatternMatch(
                    pattern_type=PatternType.risk_indicator,
                    confidence=0.8,
                    severity="high",
                    evidence=[
                        f"No interactions in {days_since_last} days "
                        f"(last: {most_recent.timestamp.isoformat()[:10]} "
                        f"via {most_recent.channel})",
                        f"Silence threshold: {self.RADIO_SILENCE_DAYS} days",
                    ],
                    detected_at=now,
                    account_id="",
                )
            )

        # Content-based risk scanning
        for interaction in timeline:
            text = interaction.content_summary
            key_points_text = " ".join(interaction.key_points)
            combined = f"{text} {key_points_text}"

            # Budget freeze detection
            if self.BUDGET_FREEZE_PATTERNS.search(combined):
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.risk_indicator,
                        confidence=0.75,
                        severity="high",
                        evidence=[
                            f"Budget freeze indicator in {interaction.channel}: "
                            f'"{text[:120]}"',
                            f"Detected at {interaction.timestamp.isoformat()[:10]}",
                        ],
                        detected_at=now,
                        account_id="",
                    )
                )

            # Champion departure detection
            if self.CHAMPION_DEPARTURE_PATTERNS.search(combined):
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.risk_indicator,
                        confidence=0.7,
                        severity="critical",
                        evidence=[
                            f"Possible champion departure in {interaction.channel}: "
                            f'"{text[:120]}"',
                            f"Detected at {interaction.timestamp.isoformat()[:10]}",
                        ],
                        detected_at=now,
                        account_id="",
                    )
                )

            # Competitor preference detection
            if self.COMPETITOR_PREFERENCE_PATTERNS.search(combined):
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.risk_indicator,
                        confidence=0.75,
                        severity="high",
                        evidence=[
                            f"Competitor preference in {interaction.channel}: "
                            f'"{text[:120]}"',
                            f"Detected at {interaction.timestamp.isoformat()[:10]}",
                        ],
                        detected_at=now,
                        account_id="",
                    )
                )

        # Delayed response detection: average response time increasing >50%
        if len(timeline) >= 4:
            midpoint = len(timeline) // 2
            early_gaps = self._calculate_avg_gap(timeline[:midpoint])
            late_gaps = self._calculate_avg_gap(timeline[midpoint:])

            if (
                early_gaps > 0
                and late_gaps > 0
                and late_gaps > early_gaps * (1 + self.RESPONSE_TIME_INCREASE_THRESHOLD)
            ):
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.risk_indicator,
                        confidence=0.7,
                        severity="medium",
                        evidence=[
                            f"Response time increased from {early_gaps:.1f}h "
                            f"to {late_gaps:.1f}h average gap",
                            f"Increase of {((late_gaps / early_gaps) - 1) * 100:.0f}%",
                        ],
                        detected_at=now,
                        account_id="",
                    )
                )

        # LLM-enhanced detection
        if self._llm_service is not None:
            llm_patterns = await self._llm_detect(timeline)
            results = self._merge_patterns(results, llm_patterns)

        return results

    @staticmethod
    def _calculate_avg_gap(interactions: List[ChannelInteraction]) -> float:
        """Calculate average time gap between interactions in hours."""
        if len(interactions) < 2:
            return 0.0

        sorted_interactions = sorted(interactions, key=lambda x: x.timestamp)
        gaps = []
        for i in range(1, len(sorted_interactions)):
            gap = (
                sorted_interactions[i].timestamp
                - sorted_interactions[i - 1].timestamp
            )
            gaps.append(gap.total_seconds() / 3600)  # Convert to hours

        return sum(gaps) / len(gaps) if gaps else 0.0

    async def _llm_detect(
        self, timeline: List[ChannelInteraction]
    ) -> List[PatternMatch]:
        """Use LLM for nuanced risk detection."""
        try:
            recent = timeline[-10:]
            summaries = [
                f"[{i.channel} {i.timestamp.isoformat()[:10]}] {i.content_summary}"
                for i in recent
            ]
            text_block = "\n".join(summaries)

            response = await self._llm_service.completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a sales intelligence analyst. Analyze the "
                            "following customer interactions for risk indicators "
                            "(deal at risk, churn risk, competitor threat). "
                            "Return only clear, evidence-backed signals."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Analyze for risk indicators:\n\n{text_block}",
                    },
                ],
                model="fast",
                response_model=List[PatternMatch],
            )
            return response if isinstance(response, list) else []
        except Exception:
            logger.warning(
                "patterns.risk_indicator_llm_detection_failed",
                exc_info=True,
            )
            return []

    @staticmethod
    def _merge_patterns(
        rule_based: List[PatternMatch],
        llm_based: List[PatternMatch],
    ) -> List[PatternMatch]:
        """Merge rule-based and LLM results."""
        if not llm_based:
            return rule_based

        existing_evidence = set()
        for p in rule_based:
            for e in p.evidence:
                existing_evidence.add(e[:50].lower())

        for p in llm_based:
            is_dup = False
            for e in p.evidence:
                if e[:50].lower() in existing_evidence:
                    is_dup = True
                    break
            if not is_dup:
                rule_based.append(p)

        return rule_based


class EngagementChangeDetector:
    """Detects engagement pattern changes over time.

    Analyzes response rate changes, meeting attendance trends, and
    engagement depth (response length and question frequency) to
    identify positive or negative engagement shifts.
    """

    RECENT_WINDOW_DAYS = 7
    BASELINE_WINDOW_DAYS = 30
    SIGNIFICANT_CHANGE_THRESHOLD = 0.3  # 30% change is significant

    def __init__(self, llm_service: Optional[Any] = None) -> None:
        self._llm_service = llm_service

    async def detect(
        self,
        timeline: List[ChannelInteraction],
        signals: Dict[str, Any],
    ) -> List[PatternMatch]:
        """Detect engagement changes from timeline.

        Args:
            timeline: Chronological list of customer interactions.
            signals: Extracted signals dict from UnifiedCustomerView.

        Returns:
            List of PatternMatch objects for detected engagement changes.
        """
        try:
            return await self._detect_internal(timeline, signals)
        except Exception:
            logger.warning(
                "patterns.engagement_change_detection_failed",
                exc_info=True,
            )
            return []

    async def _detect_internal(
        self,
        timeline: List[ChannelInteraction],
        signals: Dict[str, Any],
    ) -> List[PatternMatch]:
        """Internal detection logic."""
        if not timeline:
            return []

        now = datetime.now(timezone.utc)
        results: List[PatternMatch] = []

        # Split timeline into recent vs baseline
        recent_cutoff = now - timedelta(days=self.RECENT_WINDOW_DAYS)
        baseline_cutoff = now - timedelta(days=self.BASELINE_WINDOW_DAYS)

        recent = [i for i in timeline if i.timestamp >= recent_cutoff]
        baseline = [
            i
            for i in timeline
            if baseline_cutoff <= i.timestamp < recent_cutoff
        ]

        if not baseline:
            # Not enough history for comparison
            return []

        # Response rate change: interactions per day
        baseline_days = max(
            (self.BASELINE_WINDOW_DAYS - self.RECENT_WINDOW_DAYS), 1
        )
        recent_days = max(self.RECENT_WINDOW_DAYS, 1)

        baseline_rate = len(baseline) / baseline_days
        recent_rate = len(recent) / recent_days

        if baseline_rate > 0:
            rate_change = (recent_rate - baseline_rate) / baseline_rate

            if rate_change > self.SIGNIFICANT_CHANGE_THRESHOLD:
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.engagement_change,
                        confidence=min(0.6 + abs(rate_change) * 0.2, 0.95),
                        severity="medium",
                        evidence=[
                            f"Interaction rate increased by {rate_change * 100:.0f}%",
                            f"Recent: {recent_rate:.2f}/day vs baseline: {baseline_rate:.2f}/day",
                        ],
                        detected_at=now,
                        account_id="",
                    )
                )
            elif rate_change < -self.SIGNIFICANT_CHANGE_THRESHOLD:
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.engagement_change,
                        confidence=min(0.6 + abs(rate_change) * 0.2, 0.95),
                        severity="high",
                        evidence=[
                            f"Interaction rate decreased by {abs(rate_change) * 100:.0f}%",
                            f"Recent: {recent_rate:.2f}/day vs baseline: {baseline_rate:.2f}/day",
                        ],
                        detected_at=now,
                        account_id="",
                    )
                )

        # Meeting attendance trend
        recent_meetings = [i for i in recent if i.channel == "meeting"]
        baseline_meetings = [i for i in baseline if i.channel == "meeting"]

        if recent_meetings and baseline_meetings:
            recent_attendees = sum(
                len(m.participants) for m in recent_meetings
            ) / len(recent_meetings)
            baseline_attendees = sum(
                len(m.participants) for m in baseline_meetings
            ) / len(baseline_meetings)

            if baseline_attendees > 0:
                attendee_change = (
                    (recent_attendees - baseline_attendees) / baseline_attendees
                )
                if abs(attendee_change) > self.SIGNIFICANT_CHANGE_THRESHOLD:
                    direction = "increasing" if attendee_change > 0 else "decreasing"
                    severity = "medium" if attendee_change > 0 else "high"
                    results.append(
                        PatternMatch(
                            pattern_type=PatternType.engagement_change,
                            confidence=0.7,
                            severity=severity,
                            evidence=[
                                f"Meeting attendance {direction}: "
                                f"{recent_attendees:.1f} avg vs {baseline_attendees:.1f} baseline",
                                f"Change: {attendee_change * 100:+.0f}%",
                            ],
                            detected_at=now,
                            account_id="",
                        )
                    )

        # Engagement depth: average content length change
        recent_avg_length = (
            sum(len(i.content_summary) for i in recent) / len(recent)
            if recent
            else 0
        )
        baseline_avg_length = (
            sum(len(i.content_summary) for i in baseline) / len(baseline)
            if baseline
            else 0
        )

        if baseline_avg_length > 0:
            depth_change = (
                (recent_avg_length - baseline_avg_length) / baseline_avg_length
            )
            if depth_change > self.SIGNIFICANT_CHANGE_THRESHOLD:
                results.append(
                    PatternMatch(
                        pattern_type=PatternType.engagement_change,
                        confidence=0.65,
                        severity="low",
                        evidence=[
                            f"Engagement depth increasing: responses {depth_change * 100:.0f}% longer",
                            f"Recent avg: {recent_avg_length:.0f} chars vs baseline: {baseline_avg_length:.0f} chars",
                        ],
                        detected_at=now,
                        account_id="",
                    )
                )

        return results
