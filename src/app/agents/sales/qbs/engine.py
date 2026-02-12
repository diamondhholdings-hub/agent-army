"""QBS Question Engine with adaptive signal-driven question selection.

Analyzes conversation context through three sensing modes (information gap,
engagement signals, natural flow) and recommends the optimal QBS question
blended with MEDDIC/BANT targeting and Chris Voss empathy delivery.

Uses the 'fast' LLM model for low-latency signal analysis (~500ms target).
Falls back to rule-based recommendation on any LLM failure (fail-open).

Exports:
    QBSQuestionEngine: Adaptive QBS question selection based on conversation signals.
"""

from __future__ import annotations

import structlog

from src.app.agents.sales.qbs.schemas import (
    EngagementSignal,
    PainDepthLevel,
    PainFunnelState,
    QBSQuestionRecommendation,
    QBSQuestionType,
)
from src.app.agents.sales.schemas import (
    ConversationState,
    QualificationState,
)

logger = structlog.get_logger(__name__)


class QBSQuestionEngine:
    """Adaptive QBS question selection based on conversation signals.

    Analyzes conversation context through three sensing modes:
    1. Information gap sensing: What BANT/MEDDIC data is missing?
    2. Customer engagement signals: Where is the customer's energy?
    3. Natural conversation flow: What logically follows?

    Uses the 'fast' model for low-latency signal analysis.
    Falls back to rule-based recommendation on LLM failure.

    Args:
        llm_service: LLMService instance (typed as object to avoid import
            cycle; only needs .router attribute for model config).
    """

    # Depth ordering for comparison (lower index = shallower)
    _DEPTH_ORDER: list[PainDepthLevel] = [
        PainDepthLevel.NOT_EXPLORED,
        PainDepthLevel.SURFACE,
        PainDepthLevel.BUSINESS_IMPACT,
        PainDepthLevel.EMOTIONAL,
    ]

    def __init__(self, llm_service: object) -> None:
        """Initialize with LLM service reference.

        Args:
            llm_service: LLMService instance (used to get model config).
                Typed as object to avoid import cycle; only needs .router attribute.
        """
        self._llm_service = llm_service

    async def analyze_and_recommend(
        self,
        conversation_state: ConversationState,
        latest_message: str,
        conversation_history: list[str] | None = None,
    ) -> QBSQuestionRecommendation:
        """Analyze conversation signals and recommend the optimal QBS question.

        Performs LLM-powered signal analysis using three sensing modes:
        information gap sensing, engagement signal detection, and natural
        conversation flow assessment. Falls back to rule-based recommendation
        on any error.

        Args:
            conversation_state: Current conversation state with qualification data.
            latest_message: The customer's most recent message text.
            conversation_history: Optional list of prior conversation turns.

        Returns:
            QBSQuestionRecommendation with blended question type, MEDDIC/BANT
            target, and Voss delivery technique.
        """
        import instructor
        import litellm

        from src.app.agents.sales.qbs.prompts import build_qbs_analysis_prompt

        # Load pain state from conversation metadata
        pain_state = self._load_pain_state(conversation_state)

        try:
            # Build context summaries
            qualification_gaps = self._build_qualification_gaps(
                conversation_state.qualification
            )
            conversation_state_summary = (
                f"Deal Stage: {conversation_state.deal_stage.value}\n"
                f"Persona: {conversation_state.persona_type.value}\n"
                f"Interaction Count: {conversation_state.interaction_count}\n"
                f"Confidence: {conversation_state.confidence_score}\n"
                f"Last Channel: {conversation_state.last_channel.value if conversation_state.last_channel else 'none'}"
            )
            pain_state_summary = self._build_pain_summary(pain_state)
            conversation_history_summary = (
                "\n".join(conversation_history)
                if conversation_history
                else "No prior conversation history available."
            )

            # Build prompt messages
            messages = build_qbs_analysis_prompt(
                conversation_state_summary=conversation_state_summary,
                latest_message=latest_message,
                conversation_history_summary=conversation_history_summary,
                pain_state_summary=pain_state_summary,
                qualification_gaps=qualification_gaps,
            )

            # Create instructor client with LiteLLM async completion
            client = instructor.from_litellm(litellm.acompletion)

            # Resolve fast model for low-latency analysis
            model = self._resolve_model("fast")

            # Single LLM call for signal analysis and question recommendation
            recommendation = await client.chat.completions.create(
                model=model,
                response_model=QBSQuestionRecommendation,
                messages=messages,
                max_tokens=512,
                temperature=0.3,
                max_retries=2,
            )

            logger.info(
                "qbs_recommendation_generated",
                question_type=recommendation.question_type.value,
                target=recommendation.meddic_bant_target,
                delivery=recommendation.voss_delivery,
                engagement_signal=recommendation.engagement_signal.value,
                pain_depth=recommendation.pain_depth.value,
                should_probe_deeper=recommendation.should_probe_deeper,
            )

            return recommendation

        except Exception as exc:
            # Fail-open: return rule-based fallback on any LLM error
            logger.warning(
                "qbs_recommendation_llm_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                state_id=conversation_state.state_id,
            )
            return self._fallback_recommendation(conversation_state, pain_state)

    def _fallback_recommendation(
        self,
        state: ConversationState,
        pain_state: PainFunnelState,
    ) -> QBSQuestionRecommendation:
        """Generate rule-based fallback recommendation when LLM fails.

        Selects question type and target based on interaction count and
        pain depth level, matching NextActionEngine's rule-based approach.

        Args:
            state: Current conversation state.
            pain_state: Current pain funnel state.

        Returns:
            Rule-based QBSQuestionRecommendation.
        """
        # First interaction: generic pain discovery
        if state.interaction_count == 0:
            return QBSQuestionRecommendation(
                question_type=QBSQuestionType.PAIN_FUNNEL,
                meddic_bant_target="need",
                voss_delivery="calibrated_question",
                suggested_question=(
                    "What challenges are you currently facing with your "
                    "existing approach?"
                ),
                rationale=(
                    "First interaction -- need to discover pain points and "
                    "understand their current situation."
                ),
                information_gaps=self._build_qualification_gaps(
                    state.qualification
                ).split(", "),
                engagement_signal=EngagementSignal.FACTUAL,
                pain_depth=PainDepthLevel.NOT_EXPLORED,
                should_probe_deeper=False,
            )

        # Route by pain depth level
        if pain_state.depth_level == PainDepthLevel.NOT_EXPLORED:
            return QBSQuestionRecommendation(
                question_type=QBSQuestionType.PAIN_FUNNEL,
                meddic_bant_target="pain",
                voss_delivery="label",
                suggested_question=(
                    "It sounds like this has been a real challenge for your "
                    "team. Can you tell me more about what that looks like "
                    "day-to-day?"
                ),
                rationale=(
                    "Pain not yet explored -- use pain funnel to surface "
                    "problems with empathetic labeling."
                ),
                information_gaps=self._build_qualification_gaps(
                    state.qualification
                ).split(", "),
                engagement_signal=EngagementSignal.FACTUAL,
                pain_depth=PainDepthLevel.NOT_EXPLORED,
                should_probe_deeper=False,
            )

        if pain_state.depth_level == PainDepthLevel.SURFACE:
            return QBSQuestionRecommendation(
                question_type=QBSQuestionType.IMPACT,
                meddic_bant_target="metrics",
                voss_delivery="calibrated_question",
                suggested_question=(
                    "What impact does this have on your team's goals and "
                    "the broader business?"
                ),
                rationale=(
                    "Surface pain identified -- probe business impact to "
                    "deepen understanding and fill metrics gap."
                ),
                information_gaps=self._build_qualification_gaps(
                    state.qualification
                ).split(", "),
                engagement_signal=EngagementSignal.FACTUAL,
                pain_depth=PainDepthLevel.SURFACE,
                should_probe_deeper=False,
            )

        if pain_state.depth_level == PainDepthLevel.BUSINESS_IMPACT:
            return QBSQuestionRecommendation(
                question_type=QBSQuestionType.SOLUTION,
                meddic_bant_target="decision_criteria",
                voss_delivery="calibrated_question",
                suggested_question=(
                    "If you could solve this, what would the ideal outcome "
                    "look like for your team?"
                ),
                rationale=(
                    "Business impact established -- connect pain to solution "
                    "capabilities and explore decision criteria."
                ),
                information_gaps=self._build_qualification_gaps(
                    state.qualification
                ).split(", "),
                engagement_signal=EngagementSignal.FACTUAL,
                pain_depth=PainDepthLevel.BUSINESS_IMPACT,
                should_probe_deeper=False,
            )

        if pain_state.depth_level == PainDepthLevel.EMOTIONAL:
            return QBSQuestionRecommendation(
                question_type=QBSQuestionType.CONFIRMATION,
                meddic_bant_target="champion",
                voss_delivery="mirror",
                suggested_question=(
                    "So if I'm hearing you correctly, this is something that "
                    "really matters to you personally as well as the business?"
                ),
                rationale=(
                    "Emotional depth reached -- validate understanding and "
                    "build champion commitment through mirroring."
                ),
                information_gaps=self._build_qualification_gaps(
                    state.qualification
                ).split(", "),
                engagement_signal=EngagementSignal.FACTUAL,
                pain_depth=PainDepthLevel.EMOTIONAL,
                should_probe_deeper=False,
            )

        # Default fallback (should not reach here, but defensive)
        return QBSQuestionRecommendation(
            question_type=QBSQuestionType.PAIN_FUNNEL,
            meddic_bant_target="need",
            voss_delivery="calibrated_question",
            suggested_question=(
                "What challenges are you currently facing with your "
                "existing approach?"
            ),
            rationale="Default fallback -- starting with pain discovery.",
            information_gaps=self._build_qualification_gaps(
                state.qualification
            ).split(", "),
            engagement_signal=EngagementSignal.FACTUAL,
            pain_depth=pain_state.depth_level,
            should_probe_deeper=False,
        )

    @staticmethod
    def _load_pain_state(state: ConversationState) -> PainFunnelState:
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

    def _resolve_model(self, model_name: str) -> str:
        """Resolve model name to LiteLLM model identifier.

        Looks up the model name in the LLM service router config.
        Defaults to claude-sonnet-4-20250514 if not found.

        Args:
            model_name: Logical model name (e.g. "fast", "reasoning").

        Returns:
            LiteLLM model identifier string.
        """
        default = "anthropic/claude-sonnet-4-20250514"
        if hasattr(self._llm_service, "router") and self._llm_service.router:
            for m in self._llm_service.router.model_list:
                if m.get("model_name") == model_name:
                    return m["litellm_params"]["model"]
        return default

    @staticmethod
    def _build_qualification_gaps(qualification: QualificationState) -> str:
        """Build a comma-separated string of unidentified qualification dimensions.

        Checks all 4 BANT dimensions and all 6 MEDDIC dimensions for
        identification status.

        Args:
            qualification: Current qualification state.

        Returns:
            Comma-separated string of gap names, or empty string if all identified.
        """
        gaps: list[str] = []

        # BANT dimensions
        bant = qualification.bant
        if not bant.budget_identified:
            gaps.append("budget")
        if not bant.authority_identified:
            gaps.append("authority")
        if not bant.need_identified:
            gaps.append("need")
        if not bant.timeline_identified:
            gaps.append("timeline")

        # MEDDIC dimensions
        meddic = qualification.meddic
        if not meddic.metrics_identified:
            gaps.append("metrics")
        if not meddic.economic_buyer_identified:
            gaps.append("economic_buyer")
        if not meddic.decision_criteria_identified:
            gaps.append("decision_criteria")
        if not meddic.decision_process_identified:
            gaps.append("decision_process")
        if not meddic.pain_identified:
            gaps.append("pain")
        if not meddic.champion_identified:
            gaps.append("champion")

        return ", ".join(gaps)

    @staticmethod
    def _build_pain_summary(pain_state: PainFunnelState) -> str:
        """Build a human-readable summary of pain funnel state.

        Formats depth level, topic count, resistance status, and probe
        count into a readable string for LLM context.

        Args:
            pain_state: Current pain funnel state.

        Returns:
            Formatted pain state summary string.
        """
        summary = (
            f"Depth Level: {pain_state.depth_level.value}\n"
            f"Pain Topics: {len(pain_state.pain_topics)}\n"
            f"Resistance Detected: {pain_state.resistance_detected}\n"
            f"Emotional Recognition: {pain_state.emotional_recognition_detected}\n"
            f"Self-Elaboration Count: {pain_state.self_elaboration_count}\n"
            f"Current Topic Probe Count: {pain_state.probe_count_current_topic}"
        )

        if pain_state.pain_topics:
            summary += "\nActive Topics:"
            for topic in pain_state.pain_topics[:5]:
                summary += (
                    f"\n  - \"{topic.topic}\" "
                    f"(depth: {topic.depth.value})"
                )

        if pain_state.last_probed_topic:
            summary += f"\nLast Probed: {pain_state.last_probed_topic}"

        return summary
