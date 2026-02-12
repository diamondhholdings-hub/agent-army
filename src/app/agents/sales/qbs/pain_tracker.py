"""Pain Depth Tracker for managing pain funnel state in ConversationState.

Tracks pain topics, depth progression, engagement signals, and resistance
detection across conversation turns. State persists in the conversation
metadata dict at ``metadata['qbs']['pain_state']`` as serialized JSON.

The tracker provides static/classmethod operations on PainFunnelState --
it does NOT call state_repository.save_state. The caller is responsible
for persisting the ConversationState after updates.

Exports:
    PainDepthTracker: Pain funnel state management for QBS methodology.
"""

from __future__ import annotations

import structlog

from src.app.agents.sales.qbs.schemas import (
    EngagementSignal,
    PainDepthLevel,
    PainFunnelState,
    PainTopic,
    QBSQuestionRecommendation,
)
from src.app.agents.sales.schemas import ConversationState

logger = structlog.get_logger(__name__)

# Depth ordering for comparison (lower index = shallower)
_DEPTH_ORDER: list[PainDepthLevel] = [
    PainDepthLevel.NOT_EXPLORED,
    PainDepthLevel.SURFACE,
    PainDepthLevel.BUSINESS_IMPACT,
    PainDepthLevel.EMOTIONAL,
]

# Maximum number of pain topics to track (RESEARCH.md Pitfall 6)
_MAX_PAIN_TOPICS: int = 10


class PainDepthTracker:
    """Manages pain funnel state in ConversationState.metadata.

    Tracks pain topics, depth progression, engagement signals,
    and resistance detection across conversation turns.
    State persists in metadata['qbs']['pain_state'] JSON.

    All methods are static or classmethods -- no instance state needed.
    """

    @staticmethod
    def load(state: ConversationState) -> PainFunnelState:
        """Load pain funnel state from conversation metadata.

        Reads from ``state.metadata["qbs"]["pain_state"]``.
        Returns default PainFunnelState if not present.

        Args:
            state: Conversation state with metadata dict.

        Returns:
            PainFunnelState loaded from metadata or fresh default.
        """
        data = state.metadata.get("qbs", {}).get("pain_state", {})
        if data:
            return PainFunnelState(**data)
        return PainFunnelState()

    @staticmethod
    def save(state: ConversationState, pain_state: PainFunnelState) -> None:
        """Save pain funnel state to conversation metadata.

        Writes to ``state.metadata["qbs"]["pain_state"]``.
        Does NOT call state_repository.save_state -- caller handles
        persistence.

        Args:
            state: Conversation state to update.
            pain_state: Pain funnel state to serialize.
        """
        state.metadata.setdefault("qbs", {})
        state.metadata["qbs"]["pain_state"] = pain_state.model_dump(
            mode="json"
        )

    @staticmethod
    def update_from_recommendation(
        pain_state: PainFunnelState,
        recommendation: QBSQuestionRecommendation,
        interaction_count: int,
    ) -> PainFunnelState:
        """Update pain state based on a QBS recommendation.

        Advances depth level if recommendation indicates deeper pain.
        Detects engagement signals (emotional recognition, self-elaboration,
        resistance). Updates probe tracking for current topic.

        Args:
            pain_state: Current pain funnel state to update.
            recommendation: QBS engine recommendation with signals.
            interaction_count: Current interaction number.

        Returns:
            Updated PainFunnelState (same object, mutated).
        """
        # Advance depth only if recommendation indicates deeper pain
        rec_depth_idx = _DEPTH_ORDER.index(recommendation.pain_depth)
        current_depth_idx = _DEPTH_ORDER.index(pain_state.depth_level)
        if rec_depth_idx > current_depth_idx:
            pain_state.depth_level = recommendation.pain_depth

        # Detect engagement signals
        if (
            recommendation.engagement_signal
            == EngagementSignal.EMOTIONAL_LANGUAGE
        ):
            pain_state.emotional_recognition_detected = True

        if recommendation.engagement_signal == EngagementSignal.HIGH_ENERGY:
            pain_state.self_elaboration_count += 1

        if recommendation.engagement_signal == EngagementSignal.RESISTANT:
            pain_state.resistance_detected = True

        # Update probe tracking
        topic_key = (
            f"{recommendation.question_type.value}:"
            f"{recommendation.meddic_bant_target}"
        )
        if pain_state.last_probed_topic == topic_key:
            pain_state.probe_count_current_topic += 1
        else:
            pain_state.last_probed_topic = topic_key
            pain_state.probe_count_current_topic = 1

        return pain_state

    @staticmethod
    def add_pain_topic(
        pain_state: PainFunnelState,
        topic: str,
        depth: PainDepthLevel,
        evidence: str,
        interaction_count: int,
        business_impact: str | None = None,
        emotional_indicator: str | None = None,
    ) -> PainFunnelState:
        """Add or update a pain topic in the funnel state.

        If the topic already exists (matched by topic string), updates its
        depth, appends evidence, and refreshes last_probed_at.
        If new, appends to the topic list.

        Enforces max 10 topics (RESEARCH.md Pitfall 6) by evicting the
        topic with the oldest ``last_probed_at`` when the limit is exceeded.

        Args:
            pain_state: Current pain funnel state.
            topic: Brief description of the pain point.
            depth: Current exploration depth for this topic.
            evidence: Quote or summary from conversation.
            interaction_count: Current interaction number.
            business_impact: Articulated business cost (optional).
            emotional_indicator: Emotional language detected (optional).

        Returns:
            Updated PainFunnelState (same object, mutated).
        """
        # Check for existing topic by topic string
        existing = next(
            (t for t in pain_state.pain_topics if t.topic == topic), None
        )

        if existing is not None:
            # Update existing topic
            existing_depth_idx = _DEPTH_ORDER.index(existing.depth)
            new_depth_idx = _DEPTH_ORDER.index(depth)
            if new_depth_idx > existing_depth_idx:
                existing.depth = depth
            existing.evidence = f"{existing.evidence} | {evidence}"
            existing.last_probed_at = interaction_count
            if business_impact is not None:
                existing.business_impact = business_impact
            if emotional_indicator is not None:
                existing.emotional_indicator = emotional_indicator
        else:
            # Add new topic
            new_topic = PainTopic(
                topic=topic,
                depth=depth,
                evidence=evidence,
                business_impact=business_impact,
                emotional_indicator=emotional_indicator,
                first_mentioned_at=interaction_count,
                last_probed_at=interaction_count,
            )
            pain_state.pain_topics.append(new_topic)

        # Enforce max topics limit
        while len(pain_state.pain_topics) > _MAX_PAIN_TOPICS:
            # Evict oldest by last_probed_at
            oldest = min(
                pain_state.pain_topics, key=lambda t: t.last_probed_at
            )
            pain_state.pain_topics.remove(oldest)
            logger.info(
                "pain_topic_evicted",
                topic=oldest.topic,
                last_probed_at=oldest.last_probed_at,
                total_topics=len(pain_state.pain_topics),
            )

        return pain_state

    @staticmethod
    def should_back_off(pain_state: PainFunnelState) -> bool:
        """Determine whether to back off from current probing direction.

        Returns True if:
        - Resistance has been detected, OR
        - Current topic has been probed 3+ times without customer
          elaboration (self_elaboration_count == 0) and without
          emotional recognition.

        Per CONTEXT.md: "Not every customer goes deep on first
        conversation. Note the gap, revisit later when trust builds."

        Args:
            pain_state: Current pain funnel state.

        Returns:
            True if probing should back off.
        """
        if pain_state.resistance_detected:
            return True

        if (
            pain_state.probe_count_current_topic >= 3
            and not pain_state.emotional_recognition_detected
            and pain_state.self_elaboration_count == 0
        ):
            return True

        return False
