"""Next-action recommendation engine for sales conversations.

Provides a hybrid rule-based + LLM recommendation engine that suggests
1-3 next actions based on conversation state analysis. Fast-path rules
handle obvious situations (no interactions, stale deals, closed deals)
without requiring an LLM call. Nuanced situations fall through to
LLM-powered analysis.

Exports:
    NextActionEngine: Hybrid rule-based + LLM next-action recommender.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog

from src.app.agents.sales.schemas import (
    ConversationState,
    DealStage,
    NextAction,
    QualificationState,
)

logger = structlog.get_logger(__name__)


class NextActionEngine:
    """Hybrid rule-based + LLM next-action recommendation engine.

    Uses fast-path rules for obvious situations and falls back to
    LLM-powered analysis for nuanced cases. Always returns 1-3
    recommended actions ordered by priority.

    Args:
        llm_service: LLMService instance for LLM-powered recommendations.
    """

    def __init__(self, llm_service: object) -> None:
        """Initialize with LLM service reference.

        Args:
            llm_service: LLMService instance (typed as object to avoid
                import cycle; needs .completion() method).
        """
        self._llm_service = llm_service

    async def recommend_actions(
        self,
        state: ConversationState,
        recent_interactions: list[str] | None = None,
    ) -> list[NextAction]:
        """Recommend 1-3 next actions based on conversation state.

        Tries rule-based fast path first. If no clear rule applies,
        falls through to LLM-powered nuanced recommendation.

        Args:
            state: Current conversation state.
            recent_interactions: Optional list of recent interaction
                summaries for additional LLM context.

        Returns:
            List of 1-3 NextAction recommendations ordered by priority.
        """
        # Rule-based fast path (no LLM call needed)
        fast_actions = self._rule_based_actions(state)
        if fast_actions:
            logger.info(
                "next_action_rule_based",
                state_id=state.state_id,
                deal_stage=state.deal_stage.value,
                action_count=len(fast_actions),
            )
            return fast_actions

        # LLM-powered nuanced recommendation
        try:
            actions = await self._llm_recommend(state, recent_interactions)
            logger.info(
                "next_action_llm",
                state_id=state.state_id,
                deal_stage=state.deal_stage.value,
                action_count=len(actions),
            )
            return actions
        except Exception as exc:
            logger.warning(
                "next_action_llm_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                state_id=state.state_id,
            )
            # Fallback: generic follow-up based on deal stage
            return self._fallback_actions(state)

    def _rule_based_actions(self, state: ConversationState) -> list[NextAction]:
        """Apply rule-based fast path for obvious situations.

        Returns a list of actions if rules match, or empty list to
        signal that LLM analysis is needed.
        """
        # Escalated: pending human action
        if state.escalated:
            return [
                NextAction(
                    action_type="escalate",
                    description="Pending human escalation",
                    priority="urgent",
                    context="Deal has been escalated to human sales rep.",
                )
            ]

        # Terminal stages: no further action
        if state.deal_stage in (DealStage.CLOSED_WON, DealStage.CLOSED_LOST):
            return [
                NextAction(
                    action_type="wait",
                    description="Deal closed",
                    priority="low",
                    context=f"Deal is {state.deal_stage.value}. No further sales actions.",
                )
            ]

        # No interactions yet: initial outreach
        if state.interaction_count == 0:
            return [
                NextAction(
                    action_type="send_email",
                    description="Initial outreach email",
                    priority="high",
                    suggested_timing="within 24 hours",
                    context="No interactions yet. Start with a persona-adapted outreach email.",
                )
            ]

        # Stale deal: re-engage after 7+ days
        days_since = self._days_since_last_interaction(state)
        if (
            days_since is not None
            and days_since > 7
            and state.deal_stage != DealStage.STALLED
        ):
            return [
                NextAction(
                    action_type="follow_up",
                    description=f"Re-engage - no activity in {days_since} days",
                    priority="high",
                    suggested_timing="within 24 hours",
                    context="Deal has gone quiet. Send a value-driven re-engagement.",
                )
            ]

        # Low qualification in early stages: discovery email
        if (
            state.qualification.combined_completion < 0.3
            and state.deal_stage
            in (DealStage.DISCOVERY, DealStage.QUALIFICATION)
        ):
            gaps = self._biggest_gaps(state.qualification)
            return [
                NextAction(
                    action_type="send_email",
                    description=f"Discovery email focusing on {gaps}",
                    priority="medium",
                    suggested_timing="next business day",
                    context="Qualification completion is low. Focus on filling gaps.",
                )
            ]

        # No rule matched -- need LLM analysis
        return []

    async def _llm_recommend(
        self,
        state: ConversationState,
        recent_interactions: list[str] | None = None,
    ) -> list[NextAction]:
        """Use LLM for nuanced next-action recommendation.

        Builds a prompt with serialized conversation state and recent
        interactions, then extracts structured NextAction list.
        """
        from src.app.agents.sales.prompts import build_next_action_prompt

        # Build state summary
        state_summary = (
            f"Deal Stage: {state.deal_stage.value}\n"
            f"Persona: {state.persona_type.value}\n"
            f"Interaction Count: {state.interaction_count}\n"
            f"Last Channel: {state.last_channel.value if state.last_channel else 'none'}\n"
            f"Last Interaction: {state.last_interaction.isoformat() if state.last_interaction else 'never'}\n"
            f"Confidence Score: {state.confidence_score}\n"
            f"Escalated: {state.escalated}\n"
            f"BANT Completion: {state.qualification.bant.completion_score:.0%}\n"
            f"MEDDIC Completion: {state.qualification.meddic.completion_score:.0%}\n"
            f"Overall Qualification: {state.qualification.combined_completion:.0%}\n"
            f"Key Insights: {', '.join(state.qualification.key_insights) if state.qualification.key_insights else 'none'}"
        )

        interactions_text = "\n".join(recent_interactions) if recent_interactions else "No recent interactions available."

        messages = build_next_action_prompt(state_summary, interactions_text)

        response = await self._llm_service.completion(
            messages=messages,
            model="fast",
            max_tokens=1024,
            temperature=0.3,
        )

        # Parse JSON response into NextAction list
        content = response.get("content", "[]")
        try:
            actions_data = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON array from response
            import re

            match = re.search(r"\[.*\]", content, re.DOTALL)
            if match:
                actions_data = json.loads(match.group())
            else:
                raise ValueError(f"Could not parse next actions from LLM response: {content[:200]}")

        actions = []
        for item in actions_data[:3]:  # Limit to 3 actions
            actions.append(
                NextAction(
                    action_type=item.get("action_type", "follow_up"),
                    description=item.get("description", ""),
                    priority=item.get("priority", "medium"),
                    suggested_timing=item.get("suggested_timing"),
                    context=item.get("context", ""),
                )
            )

        return actions if actions else self._fallback_actions(state)

    def _fallback_actions(self, state: ConversationState) -> list[NextAction]:
        """Generate generic fallback actions based on deal stage."""
        stage_actions = {
            DealStage.PROSPECTING: NextAction(
                action_type="send_email",
                description="Send prospecting outreach email",
                priority="medium",
                context="Fallback: continue prospecting efforts.",
            ),
            DealStage.DISCOVERY: NextAction(
                action_type="send_email",
                description="Send discovery follow-up email",
                priority="medium",
                context="Fallback: continue discovery process.",
            ),
            DealStage.QUALIFICATION: NextAction(
                action_type="send_email",
                description="Send qualification-focused email",
                priority="medium",
                context="Fallback: advance qualification.",
            ),
            DealStage.EVALUATION: NextAction(
                action_type="follow_up",
                description="Follow up on evaluation progress",
                priority="medium",
                context="Fallback: check evaluation status.",
            ),
            DealStage.NEGOTIATION: NextAction(
                action_type="follow_up",
                description="Follow up on negotiation status",
                priority="high",
                context="Fallback: advance negotiation.",
            ),
            DealStage.STALLED: NextAction(
                action_type="follow_up",
                description="Re-engage stalled deal with value insight",
                priority="medium",
                context="Fallback: attempt to revive stalled deal.",
            ),
        }

        action = stage_actions.get(
            state.deal_stage,
            NextAction(
                action_type="follow_up",
                description="General follow-up",
                priority="medium",
                context="Fallback: generic follow-up.",
            ),
        )
        return [action]

    @staticmethod
    def _biggest_gaps(qualification: QualificationState) -> str:
        """Return human-readable string of the biggest qualification gaps.

        Examines BANT and MEDDIC signals to find unidentified dimensions,
        returning a natural language description of what is missing.
        """
        gaps = []

        # BANT gaps
        bant = qualification.bant
        if not bant.budget_identified:
            gaps.append("budget")
        if not bant.authority_identified:
            gaps.append("authority")
        if not bant.need_identified:
            gaps.append("need")
        if not bant.timeline_identified:
            gaps.append("timeline")

        # MEDDIC gaps (only include if BANT gaps are few, to keep concise)
        meddic = qualification.meddic
        if len(gaps) < 3:
            if not meddic.pain_identified:
                gaps.append("pain points")
            if not meddic.metrics_identified:
                gaps.append("success metrics")
            if not meddic.champion_identified:
                gaps.append("champion")

        if not gaps:
            return "deepening existing qualification signals"

        if len(gaps) == 1:
            return f"{gaps[0]} not yet identified"

        return f"{', '.join(gaps[:-1])} and {gaps[-1]} not yet identified"

    @staticmethod
    def _days_since_last_interaction(state: ConversationState) -> int | None:
        """Return days since last interaction, or None if no interactions."""
        if state.last_interaction is None:
            return None
        now = datetime.now(timezone.utc)
        delta = now - state.last_interaction
        return delta.days
