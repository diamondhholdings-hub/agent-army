"""Escalation trigger evaluation and structured report generation.

Evaluates 4 escalation triggers (locked decisions from CONTEXT.md) and
produces structured EscalationReport objects. Publishes escalation events
via TenantEventBus for notification routing.

Escalation triggers:
1. Confidence < 0.7 (conservative threshold for Phase 4)
2. High-stakes keywords in negotiation/evaluation stages
3. Customer explicitly requests human contact
4. Complexity threshold (3+ decision criteria + multiple stakeholders)

Exports:
    EscalationManager: Evaluates triggers and publishes escalation events.
"""

from __future__ import annotations

import uuid

import structlog

from src.app.agents.sales.schemas import (
    ConversationState,
    DealStage,
    EscalationReport,
)
from src.app.events.schemas import AgentEvent, EventPriority, EventType

logger = structlog.get_logger(__name__)


class EscalationManager:
    """Evaluates escalation triggers and publishes structured reports.

    Checks all 4 escalation triggers from CONTEXT.md against conversation
    state and latest message content. When triggered, builds a detailed
    EscalationReport and optionally publishes it via TenantEventBus.

    Args:
        event_bus: TenantEventBus for publishing escalation notifications.
        llm_service: LLMService for generating recommended next actions.
    """

    CONFIDENCE_THRESHOLD: float = 0.7
    """Locked decision from CONTEXT.md: conservative 70% for Phase 4."""

    HIGH_STAKES_KEYWORDS: list[str] = [
        "pricing",
        "contract",
        "negotiate",
        "competitor",
        "budget approval",
        "executive",
        "legal",
        "procurement",
        "discount",
        "renewal",
    ]
    """Keywords indicating high-stakes moments in sales conversations."""

    CUSTOMER_REQUEST_PHRASES: list[str] = [
        "speak to someone",
        "talk to a human",
        "call me",
        "schedule a call",
        "real person",
        "speak with someone",
        "talk to someone",
        "can someone call",
        "want to speak",
        "need to talk",
    ]
    """Phrases indicating the customer wants human contact."""

    def __init__(self, event_bus: object, llm_service: object) -> None:
        """Initialize with event bus and LLM service.

        Args:
            event_bus: TenantEventBus instance (typed as object to avoid
                import cycle; needs .publish() method).
            llm_service: LLMService instance (typed as object to avoid
                import cycle; needs .completion() method).
        """
        self._event_bus = event_bus
        self._llm_service = llm_service

    async def evaluate_escalation(
        self,
        state: ConversationState,
        latest_message: str = "",
    ) -> EscalationReport | None:
        """Check all escalation triggers against state and message.

        Evaluates triggers in priority order:
        1. Customer request (highest priority -- explicit ask)
        2. High-stakes detection (stage + keyword match)
        3. Confidence threshold (below 0.7)
        4. Complexity threshold (3+ criteria + stakeholders)

        Returns None if no triggers are met. Returns EscalationReport
        if any trigger fires (first match wins).

        Args:
            state: Current conversation state.
            latest_message: Latest message content to check for triggers.

        Returns:
            EscalationReport if escalation is triggered, None otherwise.
        """
        latest_lower = latest_message.lower()

        # 1. Customer request: explicit ask for human contact
        if self._check_customer_request(latest_lower):
            return await self._build_escalation_report(
                state, "customer_request", latest_message
            )

        # 2. High-stakes: keywords in negotiation/evaluation stages
        if self._check_high_stakes(state, latest_lower):
            return await self._build_escalation_report(
                state, "high_stakes", latest_message
            )

        # 3. Confidence threshold: below 0.7
        if state.confidence_score < self.CONFIDENCE_THRESHOLD:
            return await self._build_escalation_report(
                state, "confidence_low", latest_message
            )

        # 4. Complexity: 3+ decision criteria AND multiple stakeholders
        if self._check_complexity(state):
            return await self._build_escalation_report(
                state, "complexity", latest_message
            )

        return None

    def _check_customer_request(self, message_lower: str) -> bool:
        """Check if customer explicitly requests human contact."""
        return any(
            phrase in message_lower for phrase in self.CUSTOMER_REQUEST_PHRASES
        )

    def _check_high_stakes(
        self, state: ConversationState, message_lower: str
    ) -> bool:
        """Check for high-stakes keywords in negotiation/evaluation stages."""
        if state.deal_stage not in (DealStage.NEGOTIATION, DealStage.EVALUATION):
            return False
        return any(
            keyword in message_lower for keyword in self.HIGH_STAKES_KEYWORDS
        )

    def _check_complexity(self, state: ConversationState) -> bool:
        """Check if deal complexity exceeds threshold.

        Triggers when decision_criteria has 3+ items AND evidence suggests
        multiple stakeholders (authority + economic buyer + champion).
        """
        meddic = state.qualification.meddic
        has_many_criteria = len(meddic.decision_criteria) >= 3

        # Count identified stakeholder signals in evidence
        stakeholder_count = sum([
            meddic.economic_buyer_identified,
            meddic.champion_identified,
            state.qualification.bant.authority_identified,
        ])
        has_multiple_stakeholders = stakeholder_count >= 2

        return has_many_criteria and has_multiple_stakeholders

    async def _build_escalation_report(
        self,
        state: ConversationState,
        trigger: str,
        latest_message: str,
    ) -> EscalationReport:
        """Construct a full escalation report with context and recommendations.

        Args:
            state: Current conversation state.
            trigger: The trigger type that fired.
            latest_message: Latest message that contributed to escalation.

        Returns:
            Complete EscalationReport.
        """
        # Account context summary
        account_context = (
            f"Deal Stage: {state.deal_stage.value}, "
            f"Qualification: BANT {state.qualification.bant.completion_score:.0%} / "
            f"MEDDIC {state.qualification.meddic.completion_score:.0%}, "
            f"Interactions: {state.interaction_count}, "
            f"Confidence: {state.confidence_score:.2f}"
        )

        # What agent tried
        channel_desc = state.last_channel.value if state.last_channel else "none"
        what_tried = (
            f"Conducted {state.interaction_count} interaction(s) via {channel_desc}. "
            f"Current deal stage: {state.deal_stage.value}."
        )

        # Why escalating (specific to trigger type)
        why_escalating = self._explain_trigger(state, trigger, latest_message)

        # LLM-generated recommended next action (fast model for speed)
        recommended = await self._generate_recommendation(state, trigger)

        # Extract relevant excerpts from evidence fields
        excerpts = self._extract_excerpts(state)

        # Notification targets from metadata
        targets = []
        if state.metadata.get("rep_email"):
            targets.append(state.metadata["rep_email"])
        if state.metadata.get("manager_email"):
            targets.append(state.metadata["manager_email"])

        return EscalationReport(
            escalation_id=str(uuid.uuid4()),
            tenant_id=state.tenant_id,
            account_id=state.account_id,
            contact_id=state.contact_id,
            contact_name=state.contact_name,
            deal_stage=state.deal_stage,
            escalation_trigger=trigger,
            confidence_score=state.confidence_score,
            account_context=account_context,
            what_agent_tried=what_tried,
            why_escalating=why_escalating,
            recommended_next_action=recommended,
            relevant_conversation_excerpts=excerpts,
            notification_targets=targets,
        )

    def _explain_trigger(
        self, state: ConversationState, trigger: str, latest_message: str
    ) -> str:
        """Generate human-readable explanation for the escalation trigger."""
        explanations = {
            "confidence_low": (
                f"Agent confidence score ({state.confidence_score:.2f}) is below "
                f"the {self.CONFIDENCE_THRESHOLD} threshold. The agent is not "
                f"confident enough to handle this conversation autonomously."
            ),
            "high_stakes": (
                f"High-stakes language detected in {state.deal_stage.value} stage. "
                f"Topics like pricing, contracts, or competitive positioning require "
                f"human judgment and authority."
            ),
            "customer_request": (
                "Customer explicitly requested to speak with a human representative. "
                "Honoring this request is critical for trust and experience."
            ),
            "complexity": (
                f"Deal complexity exceeds threshold: "
                f"{len(state.qualification.meddic.decision_criteria)} decision criteria "
                f"identified with multiple stakeholders involved. Complex multi-stakeholder "
                f"deals benefit from human relationship management."
            ),
        }
        return explanations.get(trigger, f"Escalation triggered by: {trigger}")

    async def _generate_recommendation(
        self, state: ConversationState, trigger: str
    ) -> str:
        """Generate recommended next action via LLM (fast model).

        Falls back to rule-based recommendation on LLM failure.
        """
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a sales manager advisor. Given a deal that needs "
                        "human escalation, recommend the single best next action "
                        "for the human sales rep to take. Be specific and actionable. "
                        "Reply in 1-2 sentences."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Deal Stage: {state.deal_stage.value}\n"
                        f"Escalation Trigger: {trigger}\n"
                        f"Qualification: BANT {state.qualification.bant.completion_score:.0%}, "
                        f"MEDDIC {state.qualification.meddic.completion_score:.0%}\n"
                        f"Interactions: {state.interaction_count}\n"
                        f"Contact: {state.contact_name or 'Unknown'}\n"
                        f"What should the human sales rep do next?"
                    ),
                },
            ]

            response = await self._llm_service.completion(
                messages=messages,
                model="fast",
                max_tokens=256,
                temperature=0.3,
            )
            return response.get("content", "").strip()
        except Exception as exc:
            logger.warning(
                "escalation_recommendation_llm_failed",
                error=str(exc),
                trigger=trigger,
            )
            # Rule-based fallback
            return self._fallback_recommendation(trigger)

    @staticmethod
    def _fallback_recommendation(trigger: str) -> str:
        """Rule-based fallback recommendation when LLM is unavailable."""
        recommendations = {
            "confidence_low": (
                "Review the conversation history and assess the deal situation. "
                "Consider scheduling a direct call with the prospect."
            ),
            "high_stakes": (
                "Prepare a tailored proposal addressing the high-stakes topics. "
                "Schedule a call to discuss terms directly."
            ),
            "customer_request": (
                "Reach out to the prospect within 4 hours to honor their request. "
                "Review conversation context before the call."
            ),
            "complexity": (
                "Map all stakeholders and their concerns. Develop a multi-threaded "
                "engagement strategy addressing each decision-maker."
            ),
        }
        return recommendations.get(trigger, "Review the deal and take appropriate action.")

    @staticmethod
    def _extract_excerpts(state: ConversationState) -> list[str]:
        """Extract relevant conversation excerpts from qualification evidence."""
        excerpts = []

        # Gather evidence from BANT
        bant = state.qualification.bant
        for evidence in [
            bant.budget_evidence,
            bant.authority_evidence,
            bant.need_evidence,
            bant.timeline_evidence,
        ]:
            if evidence:
                excerpts.append(evidence)

        # Gather evidence from MEDDIC
        meddic = state.qualification.meddic
        for evidence in [
            meddic.metrics_evidence,
            meddic.economic_buyer_evidence,
            meddic.decision_criteria_evidence,
            meddic.pain_evidence,
            meddic.champion_evidence,
        ]:
            if evidence:
                excerpts.append(evidence)

        return excerpts[:5]  # Limit to 5 most relevant

    async def publish_escalation(self, report: EscalationReport) -> None:
        """Publish escalation event via TenantEventBus.

        Creates an AgentEvent with the serialized EscalationReport and
        publishes it to the 'escalations' stream for notification routing.

        Args:
            report: The escalation report to publish.
        """
        event = AgentEvent(
            event_type=EventType.AGENT_HEALTH,
            tenant_id=report.tenant_id,
            source_agent_id="sales_agent",
            call_chain=["sales_agent"],
            priority=EventPriority.HIGH,
            data={
                "escalation_id": report.escalation_id,
                "escalation_trigger": report.escalation_trigger,
                "account_id": report.account_id,
                "contact_id": report.contact_id,
                "contact_name": report.contact_name,
                "deal_stage": report.deal_stage.value,
                "confidence_score": report.confidence_score,
                "account_context": report.account_context,
                "what_agent_tried": report.what_agent_tried,
                "why_escalating": report.why_escalating,
                "recommended_next_action": report.recommended_next_action,
                "notification_targets": report.notification_targets,
            },
        )

        try:
            await self._event_bus.publish("escalations", event)
            logger.info(
                "escalation_published",
                escalation_id=report.escalation_id,
                trigger=report.escalation_trigger,
                account_id=report.account_id,
            )
        except Exception as exc:
            logger.error(
                "escalation_publish_failed",
                escalation_id=report.escalation_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
