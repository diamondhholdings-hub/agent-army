"""Sales Agent: BaseAgent subclass for text-based sales interactions.

Composes all prior Sales Agent components (GSuite services, RAG pipeline,
conversation store, state repository, qualification extractor, next-action
engine, escalation manager, QBS engine, pain tracker, expansion detector)
into a working agent that can be invoked via the supervisor topology.

The execute() method routes tasks by type to specialized handlers:
- send_email: Generate and send persona-adapted email via Gmail
- send_chat: Generate and send persona-adapted chat message via Google Chat
- process_reply: Process incoming customer reply with qualification + escalation + QBS
- qualify: Force qualification extraction on conversation text
- recommend_action: Get next-action recommendations

Each handler follows the pattern:
1. Compile context (RAG + conversation history + state)
2. Run QBS engine analysis for dynamic guidance (email/chat handlers)
3. Generate content via LLM with QBS-enriched prompts
4. Send via GSuite
5. Update state (qualification, QBS pain state, interaction count, channel)
6. Detect expansion triggers (reply handler)
7. Check escalation triggers
8. Return structured result

Exports:
    SalesAgent: The core sales agent class.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from src.app.agents.base import AgentRegistration, BaseAgent
from src.app.agents.sales.actions import NextActionEngine
from src.app.agents.sales.escalation import EscalationManager
from src.app.agents.sales.qbs import (
    AccountExpansionDetector,
    PainDepthTracker,
    QBSQuestionEngine,
)
from src.app.agents.sales.qbs.prompts import build_qbs_prompt_section
from src.app.agents.sales.qualification import QualificationExtractor
from src.app.agents.sales.schemas import (
    Channel,
    ConversationState,
    DealStage,
    PersonaType,
)
from src.app.agents.sales.state_repository import ConversationStateRepository
from src.app.services.gsuite.models import ChatMessage, EmailMessage

logger = structlog.get_logger(__name__)


class SalesAgent(BaseAgent):
    """Enterprise sales agent conducting text-based interactions.

    Extends BaseAgent with specialized handlers for email outreach,
    chat messaging, reply processing, qualification, and action
    recommendation. Composes all Phase 4 plan outputs plus QBS
    methodology components into a single agent invocable by the
    supervisor.

    Args:
        registration: Agent registration metadata for the registry.
        llm_service: LLMService for generating content.
        gmail_service: GmailService for sending emails.
        chat_service: ChatService for sending chat messages.
        rag_pipeline: AgenticRAGPipeline for context compilation.
        conversation_store: ConversationStore for conversation history.
        session_manager: SessionManager for session lifecycle.
        state_repository: ConversationStateRepository for state persistence.
        qualification_extractor: QualificationExtractor for signal extraction.
        action_engine: NextActionEngine for next-action recommendations.
        escalation_manager: EscalationManager for escalation evaluation.
        qbs_engine: Optional QBSQuestionEngine for adaptive question selection.
            When None, QBS guidance is not injected (backward compatible).
        expansion_detector: Optional AccountExpansionDetector for multi-threading
            opportunity detection. When None, expansion detection is skipped.
    """

    def __init__(
        self,
        registration: AgentRegistration,
        llm_service: object,
        gmail_service: object,
        chat_service: object,
        rag_pipeline: object,
        conversation_store: object,
        session_manager: object,
        state_repository: ConversationStateRepository,
        qualification_extractor: QualificationExtractor,
        action_engine: NextActionEngine,
        escalation_manager: EscalationManager,
        qbs_engine: QBSQuestionEngine | None = None,
        expansion_detector: AccountExpansionDetector | None = None,
    ) -> None:
        super().__init__(registration)
        self._llm_service = llm_service
        self._gmail_service = gmail_service
        self._chat_service = chat_service
        self._rag_pipeline = rag_pipeline
        self._conversation_store = conversation_store
        self._session_manager = session_manager
        self._state_repository = state_repository
        self._qualification_extractor = qualification_extractor
        self._action_engine = action_engine
        self._escalation_manager = escalation_manager
        self._qbs_engine = qbs_engine
        self._expansion_detector = expansion_detector

    async def execute(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Route task to the appropriate handler by task type.

        Args:
            task: Task specification with 'type' key and handler-specific fields.
            context: Execution context with tenant_id and session data.

        Returns:
            Handler-specific result dictionary.

        Raises:
            ValueError: If task type is unknown.
        """
        task_type = task.get("type", "")

        handlers = {
            "send_email": self._handle_send_email,
            "send_chat": self._handle_send_chat,
            "process_reply": self._handle_process_reply,
            "qualify": self._handle_qualification,
            "recommend_action": self._handle_recommend_action,
        }

        handler = handlers.get(task_type)
        if handler is None:
            raise ValueError(
                f"Unknown task type: {task_type!r}. "
                f"Supported: {', '.join(handlers.keys())}"
            )

        return await handler(task, context)

    # ── Context Compilation ─────────────────────────────────────────────────

    async def _compile_sales_context(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Compile rich context from all sources.

        Gathers conversation state, history, and RAG knowledge to provide
        full context for message generation.

        Args:
            task: Task specification with account/contact identifiers.
            context: Execution context with tenant_id.

        Returns:
            Dict with conversation_state, conversation_history,
            rag_response, persona, deal_stage, and channel.
        """
        tenant_id = context.get("tenant_id", "")
        account_id = task.get("account_id", "")
        contact_id = task.get("contact_id", "")

        # Load or create conversation state
        conversation_state = await self._state_repository.get_state(
            tenant_id, account_id, contact_id
        )
        if conversation_state is None:
            conversation_state = ConversationState(
                state_id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                account_id=account_id,
                contact_id=contact_id,
                contact_email=task.get("contact_email", ""),
                contact_name=task.get("contact_name", ""),
                persona_type=PersonaType(task.get("persona_type", "manager")),
                deal_stage=DealStage(task.get("deal_stage", "prospecting")),
            )

        # Get conversation history
        conversation_history = []
        try:
            conversation_history = await self._conversation_store.search_conversations(
                tenant_id=tenant_id,
                query=f"account:{account_id}",
                top_k=10,
            )
        except Exception as exc:
            logger.warning(
                "conversation_history_fetch_failed",
                error=str(exc),
                account_id=account_id,
            )

        # Get product/methodology knowledge via RAG
        rag_response = None
        try:
            rag_response = await self._rag_pipeline.run(
                query=task.get("description", ""),
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.warning(
                "rag_context_fetch_failed",
                error=str(exc),
            )

        return {
            "conversation_state": conversation_state,
            "conversation_history": conversation_history,
            "rag_response": rag_response,
            "persona": conversation_state.persona_type,
            "deal_stage": conversation_state.deal_stage,
            "channel": task.get("channel", "email"),
        }

    # ── QBS Integration ──────────────────────────────────────────────────────

    async def _get_qbs_guidance(
        self, sales_ctx: dict[str, Any]
    ) -> str | None:
        """Run QBS engine analysis and return dynamic prompt guidance.

        Returns None if QBS engine is not configured or analysis fails.
        """
        if self._qbs_engine is None:
            return None

        state: ConversationState = sales_ctx["conversation_state"]
        history = sales_ctx.get("conversation_history", [])

        try:
            # Get latest message context
            latest_msg = ""
            if history:
                latest_msg = str(history[0]) if history else ""

            recommendation = await self._qbs_engine.analyze_and_recommend(
                conversation_state=state,
                latest_message=latest_msg,
                conversation_history=(
                    [str(h) for h in history[:5]] if history else None
                ),
            )

            # Load pain state (READ-ONLY here; updates happen in _handle_process_reply)
            pain_state = PainDepthTracker.load(state)

            # Load expansion triggers from prior interactions
            expansion_triggers = []
            expansion_data = state.metadata.get("qbs", {}).get("expansion", {})
            if expansion_data.get("detected_contacts"):
                from src.app.agents.sales.qbs.schemas import ExpansionTrigger

                expansion_triggers = [
                    ExpansionTrigger(**t)
                    for t in expansion_data["detected_contacts"][:3]
                ]

            # Build the dynamic QBS guidance section (no state mutation)
            return build_qbs_prompt_section(
                recommendation, pain_state, expansion_triggers
            )
        except Exception as exc:
            logger.warning("qbs_guidance_failed", error=str(exc))
            return None

    # ── Task Handlers ───────────────────────────────────────────────────────

    async def _handle_send_email(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate and send a persona-adapted email.

        Flow:
        1. Compile context from RAG + conversation history + state
        2. Build email prompt with persona/stage adaptation
        3. Call LLM to generate email content (subject + body_html)
        4. Send via gmail_service
        5. Update conversation state
        6. Extract qualification signals
        7. Check escalation triggers
        8. Return result with message_id, thread_id, and escalation status
        """
        from src.app.agents.sales.prompts import build_email_prompt

        sales_ctx = await self._compile_sales_context(task, context)
        state: ConversationState = sales_ctx["conversation_state"]

        # Build context summary for prompt
        context_summary = self._format_context_summary(sales_ctx)

        # Get QBS guidance for prompt injection
        qbs_guidance = await self._get_qbs_guidance(sales_ctx)

        # Generate email via LLM
        messages = build_email_prompt(
            persona=state.persona_type,
            deal_stage=state.deal_stage,
            context_summary=context_summary,
            task_description=task.get("description", "Send an outreach email"),
            qbs_guidance=qbs_guidance,
        )

        response = await self._llm_service.completion(
            messages=messages,
            model="reasoning",
            max_tokens=2048,
            temperature=0.7,
        )

        email_content = response.get("content", "")

        # Parse subject and body from LLM response
        subject, body_html = self._parse_email_content(
            email_content, task.get("subject", "")
        )

        # Send via Gmail
        email_msg = EmailMessage(
            to=state.contact_email,
            subject=subject,
            body_html=body_html,
            thread_id=task.get("thread_id"),
        )
        result = await self._gmail_service.send_email(email_msg)

        # Update conversation state
        state.interaction_count += 1
        state.last_channel = Channel.EMAIL
        state.last_interaction = datetime.now(timezone.utc)
        await self._state_repository.save_state(state)

        # Extract qualification signals
        await self._qualification_extractor.extract_signals(
            conversation_text=email_content,
            existing_state=state.qualification,
        )

        # Check escalation
        escalation_report = await self._escalation_manager.evaluate_escalation(
            state, email_content
        )
        if escalation_report:
            await self._escalation_manager.publish_escalation(escalation_report)

        return {
            "status": "sent",
            "message_id": result.message_id,
            "thread_id": result.thread_id,
            "escalation": escalation_report.model_dump() if escalation_report else None,
        }

    async def _handle_send_chat(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate and send a persona-adapted chat message.

        Same flow as _handle_send_email but uses build_chat_prompt()
        and sends via chat_service.
        """
        from src.app.agents.sales.prompts import build_chat_prompt

        sales_ctx = await self._compile_sales_context(task, context)
        state: ConversationState = sales_ctx["conversation_state"]

        context_summary = self._format_context_summary(sales_ctx)

        # Get QBS guidance for prompt injection
        qbs_guidance = await self._get_qbs_guidance(sales_ctx)

        # Generate chat message via LLM
        messages = build_chat_prompt(
            persona=state.persona_type,
            deal_stage=state.deal_stage,
            context_summary=context_summary,
            task_description=task.get("description", "Send a chat message"),
            qbs_guidance=qbs_guidance,
        )

        response = await self._llm_service.completion(
            messages=messages,
            model="reasoning",
            max_tokens=1024,
            temperature=0.7,
        )

        chat_text = response.get("content", "")

        # Send via Google Chat
        chat_msg = ChatMessage(
            space_name=task.get("space_name", ""),
            text=chat_text,
            thread_key=task.get("thread_key"),
        )
        result = await self._chat_service.send_message(chat_msg)

        # Update conversation state
        state.interaction_count += 1
        state.last_channel = Channel.CHAT
        state.last_interaction = datetime.now(timezone.utc)
        await self._state_repository.save_state(state)

        # Extract qualification signals
        await self._qualification_extractor.extract_signals(
            conversation_text=chat_text,
            existing_state=state.qualification,
        )

        # Check escalation
        escalation_report = await self._escalation_manager.evaluate_escalation(
            state, chat_text
        )
        if escalation_report:
            await self._escalation_manager.publish_escalation(escalation_report)

        return {
            "status": "sent",
            "message_name": result.message_name,
            "escalation": escalation_report.model_dump() if escalation_report else None,
        }

    async def _handle_process_reply(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Process an incoming customer reply.

        Flow:
        1. Compile context
        2. Extract qualification signals from reply text
        3. Merge signals into existing state
        4. Evaluate escalation on reply content
        5. Get recommended next actions
        6. Save updated state
        7. Return qualification update, next actions, and escalation status
        """
        sales_ctx = await self._compile_sales_context(task, context)
        state: ConversationState = sales_ctx["conversation_state"]
        reply_text = task.get("reply_text", "")

        # Extract and merge qualification signals from reply
        updated_qualification = await self._qualification_extractor.extract_signals(
            conversation_text=reply_text,
            existing_state=state.qualification,
        )
        state.qualification = updated_qualification

        # Update interaction tracking
        state.interaction_count += 1
        state.last_interaction = datetime.now(timezone.utc)
        state.last_channel = Channel(task.get("channel", "email"))

        # Evaluate escalation on reply content
        escalation_report = await self._escalation_manager.evaluate_escalation(
            state, reply_text
        )
        if escalation_report:
            state.escalated = True
            state.escalation_reason = escalation_report.escalation_trigger
            await self._escalation_manager.publish_escalation(escalation_report)

        # Update QBS pain state from reply content
        if self._qbs_engine is not None:
            try:
                qbs_recommendation = await self._qbs_engine.analyze_and_recommend(
                    conversation_state=state,
                    latest_message=reply_text,
                )
                pain_state = PainDepthTracker.load(state)
                updated_pain = PainDepthTracker.update_from_recommendation(
                    pain_state, qbs_recommendation, state.interaction_count
                )
                PainDepthTracker.save(state, updated_pain)
            except Exception as exc:
                logger.warning("qbs_reply_analysis_failed", error=str(exc))

        # Detect expansion triggers from reply
        if self._expansion_detector is not None:
            try:
                existing_contacts = [state.contact_name, state.contact_email]
                expansion_triggers = (
                    await self._expansion_detector.detect_expansion_triggers(
                        conversation_text=reply_text,
                        existing_contacts=[c for c in existing_contacts if c],
                        interaction_count=state.interaction_count,
                    )
                )
                if expansion_triggers:
                    AccountExpansionDetector.save_expansion_state(
                        state, expansion_triggers
                    )
            except Exception as exc:
                logger.warning(
                    "qbs_expansion_detection_failed", error=str(exc)
                )

        # Get recommended next actions
        actions = await self._action_engine.recommend_actions(
            state, recent_interactions=[reply_text]
        )

        # Save updated state (includes QBS metadata)
        await self._state_repository.save_state(state)

        return {
            "status": "processed",
            "qualification_update": updated_qualification.model_dump(),
            "next_actions": [a.model_dump() for a in actions],
            "escalation": escalation_report.model_dump() if escalation_report else None,
        }

    async def _handle_qualification(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Force qualification extraction on provided conversation text.

        Used when explicit qualification analysis is needed outside
        of normal interaction flow.
        """
        tenant_id = context.get("tenant_id", "")
        account_id = task.get("account_id", "")
        contact_id = task.get("contact_id", "")
        conversation_text = task.get("conversation_text", "")

        # Load state
        state = await self._state_repository.get_state(
            tenant_id, account_id, contact_id
        )
        if state is None:
            state = ConversationState(
                state_id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                account_id=account_id,
                contact_id=contact_id,
                contact_email=task.get("contact_email", ""),
            )

        # Extract and merge signals
        updated_qualification = await self._qualification_extractor.extract_signals(
            conversation_text=conversation_text,
            existing_state=state.qualification,
        )
        state.qualification = updated_qualification
        await self._state_repository.save_state(state)

        return {
            "status": "qualified",
            "qualification": updated_qualification.model_dump(),
        }

    async def _handle_recommend_action(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Get next-action recommendations for a conversation.

        Loads state and delegates to the NextActionEngine.
        """
        tenant_id = context.get("tenant_id", "")
        account_id = task.get("account_id", "")
        contact_id = task.get("contact_id", "")

        state = await self._state_repository.get_state(
            tenant_id, account_id, contact_id
        )
        if state is None:
            state = ConversationState(
                state_id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                account_id=account_id,
                contact_id=contact_id,
                contact_email=task.get("contact_email", ""),
            )

        actions = await self._action_engine.recommend_actions(state)

        return {
            "next_actions": [a.model_dump() for a in actions],
        }

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _format_context_summary(sales_ctx: dict[str, Any]) -> str:
        """Format compiled context into a summary string for LLM prompts."""
        state: ConversationState = sales_ctx["conversation_state"]
        rag_response = sales_ctx.get("rag_response")
        history = sales_ctx.get("conversation_history", [])

        parts = [
            f"Contact: {state.contact_name or state.contact_email}",
            f"Account: {state.account_id}",
            f"Deal Stage: {state.deal_stage.value}",
            f"Persona: {state.persona_type.value}",
            f"Interactions: {state.interaction_count}",
            f"BANT: {state.qualification.bant.completion_score:.0%}",
            f"MEDDIC: {state.qualification.meddic.completion_score:.0%}",
        ]

        # Add key insights
        if state.qualification.key_insights:
            parts.append(
                f"Key Insights: {'; '.join(state.qualification.key_insights[:3])}"
            )

        # Add RAG knowledge
        if rag_response and hasattr(rag_response, "answer"):
            parts.append(f"\nRelevant Knowledge:\n{rag_response.answer[:500]}")

        # Add recent conversation history
        if history:
            parts.append(f"\nConversation History: {len(history)} prior messages")

        # Add QBS pain state if present
        qbs_data = state.metadata.get("qbs", {})
        pain_data = qbs_data.get("pain_state", {})
        if pain_data:
            pain_topics = pain_data.get("pain_topics", [])
            if pain_topics:
                topic_summaries = []
                for topic in pain_topics[:3]:  # Top 3 most recent
                    summary = (
                        f"- {topic.get('topic', 'Unknown')} "
                        f"(depth: {topic.get('depth', 'unknown')})"
                    )
                    if topic.get("business_impact"):
                        summary += f" -- impact: {topic['business_impact']}"
                    topic_summaries.append(summary)
                parts.append(
                    "\nIdentified Pain Points:\n"
                    + "\n".join(topic_summaries)
                )

        # Add expansion opportunities if present
        expansion_data = qbs_data.get("expansion", {})
        detected = expansion_data.get("detected_contacts", [])
        if detected:
            parts.append(
                f"\nExpansion Opportunities: {len(detected)} contact(s) "
                f"detected for multi-threading"
            )

        return "\n".join(parts)

    @staticmethod
    def _parse_email_content(
        llm_content: str, fallback_subject: str = ""
    ) -> tuple[str, str]:
        """Parse subject and body from LLM-generated email content.

        Expects the LLM to include a Subject: line, but handles cases
        where it doesn't by using the fallback_subject.
        """
        subject = fallback_subject or "Follow-up"
        body_html = llm_content

        # Try to extract subject from content
        lines = llm_content.strip().split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.lower().startswith("subject:"):
                subject = stripped[len("subject:"):].strip()
                # Body is everything after the subject line
                body_html = "\n".join(lines[i + 1:]).strip()
                # Skip blank line after subject
                if body_html.startswith("\n"):
                    body_html = body_html[1:]
                break

        # Wrap plain text in basic HTML if not already HTML
        if "<" not in body_html:
            body_html = f"<p>{body_html.replace(chr(10) + chr(10), '</p><p>').replace(chr(10), '<br>')}</p>"

        return subject, body_html
