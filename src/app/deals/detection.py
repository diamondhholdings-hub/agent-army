"""Opportunity signal detection from conversation text.

Uses instructor + LiteLLM (matching QualificationExtractor pattern from Phase 4)
to extract structured OpportunitySignals from conversations. Includes existing
opportunities in the detection prompt to prevent duplicate creation (Pitfall 3).

Creation threshold is >0.80 for precision bias (CONTEXT.md locked decision):
better to miss marginal deals than create noise.

Exports:
    OpportunityDetector: LLM-powered opportunity signal extraction.
"""

from __future__ import annotations

import structlog

from src.app.agents.sales.schemas import ConversationState
from src.app.deals.schemas import OpportunityRead, OpportunitySignals

logger = structlog.get_logger(__name__)


class OpportunityDetector:
    """Detect opportunity signals from conversation text using instructor + LiteLLM.

    Analyzes conversation content to determine if a new opportunity should be
    created or an existing one updated. Uses structured LLM extraction with
    the instructor library for validated output.

    Thresholds (CONTEXT.md locked decisions):
    - CREATION_THRESHOLD = 0.80: High bar for new opportunity creation (precision bias)
    - UPDATE_THRESHOLD = 0.70: Lower bar for updating existing opportunities

    The detection prompt includes existing opportunities to prevent duplicate
    creation (RESEARCH.md Pitfall 3). A new opportunity is only signaled if
    the product line differs OR the timeline differs by >3 months.

    Args:
        model: LiteLLM model name to use (default: "reasoning" for router lookup).
    """

    CREATION_THRESHOLD = 0.80  # Locked decision: >80% for precision bias
    UPDATE_THRESHOLD = 0.70  # Lower bar for updating existing

    def __init__(self, model: str = "reasoning") -> None:
        self._model = model

    async def detect_signals(
        self,
        conversation_text: str,
        conversation_state: ConversationState,
        existing_opportunities: list[OpportunityRead],
    ) -> OpportunitySignals:
        """Extract opportunity signals from conversation text.

        Uses instructor.from_litellm(litellm.acompletion) for structured extraction
        of OpportunitySignals. The system prompt includes existing opportunities
        to prevent duplicate creation (Pitfall 3).

        Args:
            conversation_text: The conversation transcript to analyze.
            conversation_state: Current conversation state with deal stage,
                qualification, and interaction history.
            existing_opportunities: List of existing opportunities for this account
                (used to prevent duplicate creation).

        Returns:
            OpportunitySignals with deal_potential_confidence, product_line,
            is_new_opportunity flag, and optional matching_opportunity_id.
        """
        import instructor
        import litellm

        try:
            messages = self._build_detection_prompt(
                conversation_text=conversation_text,
                conversation_state=conversation_state,
                existing_opportunities=existing_opportunities,
            )

            client = instructor.from_litellm(litellm.acompletion)

            extracted = await client.chat.completions.create(
                model=self._model,
                response_model=OpportunitySignals,
                messages=messages,
                max_tokens=2048,
                temperature=0.1,  # Low temp for deterministic extraction
                max_retries=2,
            )

            logger.info(
                "opportunity_signals_detected",
                confidence=extracted.deal_potential_confidence,
                product_line=extracted.product_line,
                is_new=extracted.is_new_opportunity,
                matching_id=extracted.matching_opportunity_id,
            )

            return extracted

        except Exception as exc:
            # Fail-open: return low-confidence signals on any LLM error
            logger.warning(
                "opportunity_detection_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return OpportunitySignals(
                deal_potential_confidence=0.0,
                reasoning=f"Detection failed: {type(exc).__name__}",
            )

    def should_create_opportunity(self, signals: OpportunitySignals) -> bool:
        """Determine if a new opportunity should be created from detected signals.

        Returns True only if confidence exceeds CREATION_THRESHOLD AND the
        signals indicate this is a genuinely new opportunity (not an update
        to an existing one).

        Args:
            signals: Extracted OpportunitySignals from detect_signals().

        Returns:
            True if a new opportunity should be created.
        """
        return (
            signals.deal_potential_confidence >= self.CREATION_THRESHOLD
            and signals.is_new_opportunity
        )

    def should_update_opportunity(self, signals: OpportunitySignals) -> bool:
        """Determine if an existing opportunity should be updated from signals.

        Returns True if confidence exceeds UPDATE_THRESHOLD, this is NOT a
        new opportunity, and a matching existing opportunity was identified.

        Args:
            signals: Extracted OpportunitySignals from detect_signals().

        Returns:
            True if an existing opportunity should be updated.
        """
        return (
            signals.deal_potential_confidence >= self.UPDATE_THRESHOLD
            and not signals.is_new_opportunity
            and signals.matching_opportunity_id is not None
        )

    def _build_detection_prompt(
        self,
        conversation_text: str,
        conversation_state: ConversationState,
        existing_opportunities: list[OpportunityRead],
    ) -> list[dict[str, str]]:
        """Build the detection prompt with existing opportunities context.

        The system message includes:
        - Role and task description
        - List of existing opportunities (prevents duplicates per Pitfall 3)
        - Instructions for new vs update determination

        The user message includes:
        - Conversation text
        - Conversation state summary (deal_stage, qualification, interaction_count)

        Args:
            conversation_text: The conversation transcript.
            conversation_state: Current conversation state.
            existing_opportunities: Existing opportunities for context.

        Returns:
            List of message dicts for the LLM call.
        """
        # Build existing opportunities context for dedup
        existing_context = ""
        if existing_opportunities:
            opp_lines = []
            for opp in existing_opportunities:
                opp_lines.append(
                    f"- ID: {opp.id}, Name: {opp.name}, "
                    f"Product: {opp.product_line or 'N/A'}, "
                    f"Stage: {opp.deal_stage}, "
                    f"Value: {opp.estimated_value or 'N/A'}"
                )
            existing_context = (
                "\n\nEXISTING OPPORTUNITIES (do NOT create duplicates):\n"
                + "\n".join(opp_lines)
            )

        system_message = (
            "You are an expert sales opportunity detector. Analyze the conversation "
            "to identify deal potential and extract structured signals.\n\n"
            "RULES:\n"
            "1. Signal a NEW opportunity ONLY if it involves a different product line "
            "OR a significantly different timeline (>3 months apart) from existing opportunities.\n"
            "2. If the conversation discusses an existing opportunity, set is_new_opportunity=false "
            "and provide the matching_opportunity_id.\n"
            "3. Extract pain points, budget signals, and estimated value when mentioned.\n"
            "4. Set deal_potential_confidence based on how clearly the conversation "
            "indicates a real purchase intent (0.0 = no signal, 1.0 = explicit commitment).\n"
            "5. Be precise with confidence scores -- most conversations should score "
            "between 0.3 and 0.7 unless there are very clear signals."
            f"{existing_context}"
        )

        # Build conversation state summary
        qual_completion = conversation_state.qualification.combined_completion
        state_summary = (
            f"Deal Stage: {conversation_state.deal_stage.value}\n"
            f"Interaction Count: {conversation_state.interaction_count}\n"
            f"Qualification Completion: {qual_completion:.0%}\n"
            f"Current Confidence: {conversation_state.confidence_score:.2f}"
        )

        user_message = (
            f"CONVERSATION STATE:\n{state_summary}\n\n"
            f"CONVERSATION TEXT:\n{conversation_text}"
        )

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
