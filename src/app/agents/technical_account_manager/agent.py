"""Technical Account Manager Agent: BaseAgent subclass for health monitoring.

Routes tasks by type to seven specialized handlers -- health scan, escalation
outreach, release notes, roadmap preview, health check-in, customer success
review, and relationship profile update. Health scoring uses pure Python
(no LLM). All communications create Gmail DRAFTS for rep review -- the TAM
never calls send_email. Escalation dispatch fires all 4 notification channels
(Notion, event bus, email alert draft, chat alert) independently.

Exports:
    TAMAgent: The core technical account manager agent class.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from src.app.agents.base import AgentRegistration, BaseAgent
from src.app.agents.technical_account_manager.prompts import (
    TAM_SYSTEM_PROMPT,
    build_customer_success_review_prompt,
    build_escalation_outreach_prompt,
    build_health_checkin_prompt,
    build_release_notes_prompt,
    build_roadmap_preview_prompt,
)
from src.app.agents.technical_account_manager.schemas import (
    EscalationNotificationResult,
    HealthScoreResult,
    TAMResult,
)


class TAMAgent(BaseAgent):
    """Technical account management agent for health monitoring and escalation.

    Extends BaseAgent with 7 capability handlers:
    - health_scan: Compute health scores for one or all accounts
    - escalation_outreach: Generate escalation email drafts with 4-channel notify
    - release_notes: Generate account-tailored release notes drafts
    - roadmap_preview: Generate roadmap previews and surface co-dev opportunities
    - health_checkin: Generate periodic health check-in drafts
    - customer_success_review: Generate comprehensive CSR drafts
    - update_relationship_profile: Merge profile updates into Notion

    Each handler follows fail-open semantics: on LLM or service error, the
    handler returns a partial result dict with ``{"error": ..., "confidence":
    "low", "partial": True}`` instead of raising, keeping the workflow
    unblocked.

    CRITICAL: TAM never calls send_email. ALL communications (including
    escalation alert emails) are created as Gmail drafts for rep review.

    Args:
        registration: Agent registration metadata for the registry.
        llm_service: LLMService (or compatible) for generating content.
        notion_tam: NotionTAMAdapter (or compatible) for Notion operations.
            None is allowed -- Notion writes are skipped gracefully.
        gmail_service: GmailService (or compatible) for create_draft.
            None is allowed -- draft creation is skipped gracefully.
        chat_service: ChatService (or compatible) for chat alerts.
            None is allowed -- chat alerts are skipped gracefully.
        event_bus: TenantEventBus (or compatible) for event publishing.
            None is allowed -- event publishing is skipped gracefully.
        ticket_client: TicketClient (or compatible) for ticket data.
            None is allowed -- ticket data uses empty lists.
        health_scorer: HealthScorer (or compatible) for score computation.
            None is allowed -- health scan returns error dict.
    """

    def __init__(
        self,
        registration: AgentRegistration,
        llm_service: object,
        notion_tam: object | None = None,
        gmail_service: object | None = None,
        chat_service: object | None = None,
        event_bus: object | None = None,
        ticket_client: object | None = None,
        health_scorer: object | None = None,
    ) -> None:
        super().__init__(registration)
        self._llm_service = llm_service
        self._notion_tam = notion_tam
        self._gmail_service = gmail_service
        self._chat_service = chat_service
        self._event_bus = event_bus
        self._ticket_client = ticket_client
        self._health_scorer = health_scorer
        self._log = structlog.get_logger(__name__).bind(
            agent_id=registration.agent_id,
            agent_name=registration.name,
        )

    # -- Task Router ---------------------------------------------------------------

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
            "health_scan": self._handle_health_scan,
            "escalation_outreach": self._handle_escalation_outreach,
            "release_notes": self._handle_release_notes,
            "roadmap_preview": self._handle_roadmap_preview,
            "health_checkin": self._handle_health_checkin,
            "customer_success_review": self._handle_customer_success_review,
            "update_relationship_profile": self._handle_update_relationship_profile,
        }

        handler = handlers.get(task_type)
        if handler is None:
            raise ValueError(
                f"Unknown task type: {task_type!r}. "
                f"Supported: {', '.join(handlers.keys())}"
            )

        return await handler(task, context)

    # -- Capability Handlers -------------------------------------------------------

    async def _handle_health_scan(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute health score for one or all accounts.

        Uses pure Python HealthScorer (no LLM) for deterministic scoring.
        For each account: fetches tickets, computes score, triggers escalation
        if needed, and updates Notion.

        Rate-limits escalation alerts to max 5 per scan run.
        """
        try:
            if self._health_scorer is None:
                return {
                    "task_type": "health_scan",
                    "error": "HealthScorer not configured",
                    "confidence": "low",
                    "partial": True,
                }

            account_id = task.get("account_id")
            tenant_id = context.get("tenant_id", "")

            # Determine accounts to scan
            if account_id:
                accounts = [{"account_id": account_id}]
                if self._notion_tam is not None:
                    try:
                        account_page = await self._notion_tam.get_account(account_id)
                        if account_page:
                            accounts = [account_page]
                    except Exception as notion_err:
                        self._log.warning(
                            "health_scan_notion_fetch_failed",
                            account_id=account_id,
                            error=str(notion_err),
                        )
            else:
                if self._notion_tam is None:
                    return {
                        "task_type": "health_scan",
                        "error": "NotionTAM adapter not configured for batch scan",
                        "confidence": "low",
                        "partial": True,
                    }
                accounts = await self._notion_tam.query_all_accounts()

            health_scores: list[HealthScoreResult] = []
            escalation_count = 0
            max_escalations = 5

            for account in accounts:
                acct_id = (
                    account.get("account_id", "")
                    if isinstance(account, dict)
                    else str(account)
                )

                # Fetch ticket data
                open_tickets: list[Any] = []
                p1_p2_tickets: list[Any] = []
                if self._ticket_client is not None:
                    try:
                        open_tickets = await self._ticket_client.get_open_tickets(acct_id)
                        p1_p2_tickets = await self._ticket_client.get_p1_p2_tickets(acct_id)
                    except Exception as ticket_err:
                        self._log.warning(
                            "health_scan_ticket_fetch_failed",
                            account_id=acct_id,
                            error=str(ticket_err),
                        )
                else:
                    self._log.warning(
                        "health_scan_no_ticket_client",
                        account_id=acct_id,
                        msg="Using empty ticket lists",
                    )

                # Compute oldest P1/P2 age
                oldest_age_days = 0.0
                for ticket in p1_p2_tickets:
                    age = (
                        ticket.get("age_days", 0.0)
                        if isinstance(ticket, dict)
                        else getattr(ticket, "age_days", 0.0)
                    )
                    oldest_age_days = max(oldest_age_days, float(age))

                # Get heartbeat data from account metadata
                hours_since_heartbeat = None
                if isinstance(account, dict):
                    hb = account.get("hours_since_heartbeat")
                    if hb is not None:
                        hours_since_heartbeat = float(hb)

                # Compute health score via pure Python scorer
                score, rag_status = self._health_scorer.compute_score(
                    p1_p2_ticket_count=len(p1_p2_tickets),
                    oldest_p1_p2_age_days=oldest_age_days,
                    total_open_tickets=len(open_tickets),
                    hours_since_heartbeat=hours_since_heartbeat,
                )

                # Get previous score/RAG from account metadata
                previous_score = None
                previous_rag = None
                if isinstance(account, dict):
                    prev_s = account.get("health_score")
                    if prev_s is not None:
                        previous_score = int(prev_s)
                    previous_rag = account.get("health_rag")

                health_score_result = HealthScoreResult(
                    account_id=acct_id,
                    score=score,
                    rag_status=rag_status,
                    previous_score=previous_score,
                    previous_rag=previous_rag,
                    p1_p2_ticket_count=len(p1_p2_tickets),
                    oldest_p1_p2_age_days=oldest_age_days,
                    total_open_tickets=len(open_tickets),
                    hours_since_heartbeat=hours_since_heartbeat,
                )

                health_scores.append(health_score_result)

                # Trigger escalation if needed (rate-limited)
                if health_score_result.should_escalate:
                    if escalation_count < max_escalations:
                        try:
                            await self._dispatch_escalation_notifications(
                                account_id=acct_id,
                                health_score_result=health_score_result,
                                context=context,
                                account=account if isinstance(account, dict) else {},
                            )
                            escalation_count += 1
                        except Exception as esc_err:
                            self._log.warning(
                                "health_scan_escalation_failed",
                                account_id=acct_id,
                                error=str(esc_err),
                            )
                    else:
                        self._log.warning(
                            "health_scan_escalation_rate_limited",
                            account_id=acct_id,
                            escalation_count=escalation_count,
                            max_escalations=max_escalations,
                            msg="Max escalation alerts reached for this scan run",
                        )

                # Update Notion with new health score
                if self._notion_tam is not None:
                    try:
                        account_page_id = (
                            account.get("page_id", "")
                            if isinstance(account, dict)
                            else ""
                        )
                        if account_page_id:
                            await self._notion_tam.update_health_score(
                                account_page_id, score, rag_status
                            )
                    except Exception as notion_err:
                        self._log.warning(
                            "health_scan_notion_update_failed",
                            account_id=acct_id,
                            error=str(notion_err),
                        )

            result = TAMResult(
                task_type="health_scan",
                health_scores=health_scores,
                health_score=health_scores[0] if len(health_scores) == 1 else None,
                confidence="high",
            )
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "health_scan_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "health_scan",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_escalation_outreach(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate escalation outreach email draft and dispatch notifications.

        Gets relationship profile, tickets, and health score for the account,
        then uses LLM to generate a personalized escalation communication.
        Creates a Gmail DRAFT (never sends) and dispatches all 4 notification
        channels.
        """
        try:
            account_id = task.get("account_id", "")
            rep_email = task.get("rep_email", "")

            # Get relationship profile
            profile_dict: dict[str, Any] = {}
            if self._notion_tam is not None:
                try:
                    profile_dict = await self._notion_tam.get_relationship_profile(
                        account_id
                    )
                except Exception as prof_err:
                    self._log.warning(
                        "escalation_outreach_profile_failed",
                        account_id=account_id,
                        error=str(prof_err),
                    )

            # Get open tickets
            tickets_list: list[dict[str, Any]] = []
            if self._ticket_client is not None:
                try:
                    raw_tickets = await self._ticket_client.get_open_tickets(account_id)
                    tickets_list = [
                        t if isinstance(t, dict) else t.model_dump()
                        if hasattr(t, "model_dump")
                        else {"ticket_id": str(t)}
                        for t in raw_tickets
                    ]
                except Exception as ticket_err:
                    self._log.warning(
                        "escalation_outreach_tickets_failed",
                        account_id=account_id,
                        error=str(ticket_err),
                    )

            # Get health score
            health_score_dict: dict[str, Any] = task.get("health_score", {})

            # Build prompt and call LLM
            prompt = build_escalation_outreach_prompt(
                health_score=health_score_dict,
                relationship_profile=profile_dict,
                tickets=tickets_list,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": TAM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )

            raw_text = response.get("content", "") if isinstance(response, dict) else (
                response.content if hasattr(response, "content") else str(response)
            )
            cleaned = self._extract_json_from_response(raw_text)
            parsed = json.loads(cleaned)

            subject = parsed.get("subject", "Escalation Outreach")
            body_html = parsed.get("body_html", "")
            key_issues = parsed.get("key_issues", [])

            # Create Gmail DRAFT (NEVER send_email)
            draft_id: str | None = None
            if self._gmail_service is not None and rep_email:
                try:
                    from src.app.services.gsuite.models import EmailMessage

                    draft_email = EmailMessage(
                        to=rep_email,
                        subject=subject,
                        body_html=body_html,
                    )
                    draft_result = await self._gmail_service.create_draft(draft_email)
                    draft_id = (
                        draft_result.draft_id
                        if hasattr(draft_result, "draft_id")
                        else draft_result.get("draft_id", "")
                        if isinstance(draft_result, dict)
                        else None
                    )
                except Exception as draft_err:
                    self._log.warning(
                        "escalation_outreach_draft_failed",
                        account_id=account_id,
                        error=str(draft_err),
                    )
            elif self._gmail_service is None:
                self._log.warning(
                    "escalation_outreach_draft_skipped",
                    reason="gmail_service not configured",
                )

            # Dispatch all 4 notification channels
            escalation_result = await self._dispatch_escalation_notifications(
                account_id=account_id,
                health_score_result=HealthScoreResult(
                    account_id=account_id,
                    score=health_score_dict.get("score", 0),
                    rag_status=health_score_dict.get("rag_status", "Red"),
                    previous_score=health_score_dict.get("previous_score"),
                    previous_rag=health_score_dict.get("previous_rag"),
                ),
                context=context,
                account={"rep_email": rep_email},
            )

            result = TAMResult(
                task_type="escalation_outreach",
                communication_content=body_html,
                communication_type="escalation_outreach",
                draft_id=draft_id,
                escalation_result=escalation_result,
                confidence="high",
            )
            result_dict = result.model_dump()
            result_dict["key_issues"] = key_issues
            return result_dict

        except Exception as exc:
            self._log.warning(
                "escalation_outreach_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "escalation_outreach",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_release_notes(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate account-tailored release notes as a Gmail draft.

        Extracts release_info from task, gets the relationship profile,
        and uses LLM to produce personalized release notes.
        """
        try:
            account_id = task.get("account_id", "")
            release_info = task.get("release_info", {})
            rep_email = task.get("rep_email", "")

            # Get relationship profile
            profile_dict: dict[str, Any] = {}
            if self._notion_tam is not None:
                try:
                    profile_dict = await self._notion_tam.get_relationship_profile(
                        account_id
                    )
                except Exception as prof_err:
                    self._log.warning(
                        "release_notes_profile_failed",
                        account_id=account_id,
                        error=str(prof_err),
                    )

            # Build prompt and call LLM
            prompt = build_release_notes_prompt(
                release_info=release_info,
                relationship_profile=profile_dict,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": TAM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
            )

            raw_text = response.get("content", "") if isinstance(response, dict) else (
                response.content if hasattr(response, "content") else str(response)
            )
            cleaned = self._extract_json_from_response(raw_text)
            parsed = json.loads(cleaned)

            subject = parsed.get("subject", "Release Notes")
            body_html = parsed.get("body_html", "")

            # Create Gmail DRAFT
            draft_id: str | None = None
            if self._gmail_service is not None and rep_email:
                try:
                    from src.app.services.gsuite.models import EmailMessage

                    draft_email = EmailMessage(
                        to=rep_email,
                        subject=subject,
                        body_html=body_html,
                    )
                    draft_result = await self._gmail_service.create_draft(draft_email)
                    draft_id = (
                        draft_result.draft_id
                        if hasattr(draft_result, "draft_id")
                        else draft_result.get("draft_id", "")
                        if isinstance(draft_result, dict)
                        else None
                    )
                except Exception as draft_err:
                    self._log.warning(
                        "release_notes_draft_failed",
                        account_id=account_id,
                        error=str(draft_err),
                    )
            elif self._gmail_service is None:
                self._log.warning(
                    "release_notes_draft_skipped",
                    reason="gmail_service not configured",
                )

            result = TAMResult(
                task_type="release_notes",
                communication_content=body_html,
                communication_type="release_notes",
                draft_id=draft_id,
                confidence="high",
            )
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "release_notes_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "release_notes",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_roadmap_preview(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate roadmap preview and surface co-dev opportunities.

        Uses LLM to align roadmap items with the account's needs, creates
        a Gmail draft, and dispatches co-dev opportunities to the Sales Agent
        via event bus if any are found.
        """
        try:
            account_id = task.get("account_id", "")
            roadmap_items = task.get("roadmap_items", [])
            rep_email = task.get("rep_email", "")

            # Get relationship profile
            profile_dict: dict[str, Any] = {}
            if self._notion_tam is not None:
                try:
                    profile_dict = await self._notion_tam.get_relationship_profile(
                        account_id
                    )
                except Exception as prof_err:
                    self._log.warning(
                        "roadmap_preview_profile_failed",
                        account_id=account_id,
                        error=str(prof_err),
                    )

            # Build prompt and call LLM
            prompt = build_roadmap_preview_prompt(
                roadmap_items=roadmap_items,
                relationship_profile=profile_dict,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": TAM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
            )

            raw_text = response.get("content", "") if isinstance(response, dict) else (
                response.content if hasattr(response, "content") else str(response)
            )
            cleaned = self._extract_json_from_response(raw_text)
            parsed = json.loads(cleaned)

            subject = parsed.get("subject", "Roadmap Preview")
            body_html = parsed.get("body_html", "")
            co_dev_opportunities = parsed.get("co_dev_opportunities", [])

            # Create Gmail DRAFT
            draft_id: str | None = None
            if self._gmail_service is not None and rep_email:
                try:
                    from src.app.services.gsuite.models import EmailMessage

                    draft_email = EmailMessage(
                        to=rep_email,
                        subject=subject,
                        body_html=body_html,
                    )
                    draft_result = await self._gmail_service.create_draft(draft_email)
                    draft_id = (
                        draft_result.draft_id
                        if hasattr(draft_result, "draft_id")
                        else draft_result.get("draft_id", "")
                        if isinstance(draft_result, dict)
                        else None
                    )
                except Exception as draft_err:
                    self._log.warning(
                        "roadmap_preview_draft_failed",
                        account_id=account_id,
                        error=str(draft_err),
                    )
            elif self._gmail_service is None:
                self._log.warning(
                    "roadmap_preview_draft_skipped",
                    reason="gmail_service not configured",
                )

            # Dispatch co-dev opportunities to Sales Agent via event bus
            if co_dev_opportunities:
                try:
                    from src.app.events.schemas import (
                        AgentEvent,
                        EventPriority,
                        EventType,
                    )

                    event = AgentEvent(
                        event_type=EventType.CONTEXT_UPDATED,
                        tenant_id=context.get("tenant_id", ""),
                        source_agent_id="technical_account_manager",
                        call_chain=["technical_account_manager"],
                        priority=EventPriority.NORMAL,
                        data={
                            "alert_type": "co_dev_opportunity",
                            "account_id": account_id,
                            "opportunities": co_dev_opportunities,
                        },
                    )
                    if self._event_bus is not None:
                        await self._event_bus.publish("opportunities", event)
                        self._log.info(
                            "tam_co_dev_dispatched",
                            account_id=account_id,
                            opportunity_count=len(co_dev_opportunities),
                        )
                except Exception as opp_err:
                    self._log.warning(
                        "tam_co_dev_dispatch_failed",
                        error=str(opp_err),
                    )

            result = TAMResult(
                task_type="roadmap_preview",
                communication_content=body_html,
                communication_type="roadmap_preview",
                draft_id=draft_id,
                confidence="high",
            )
            result_dict = result.model_dump()
            result_dict["co_dev_opportunities"] = co_dev_opportunities
            return result_dict

        except Exception as exc:
            self._log.warning(
                "roadmap_preview_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "roadmap_preview",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_health_checkin(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate periodic health check-in as a Gmail draft.

        Gets the relationship profile, recent communications, and current
        health score, then uses LLM to produce a personalized check-in.
        Logs the communication to Notion for continuity tracking.
        """
        try:
            account_id = task.get("account_id", "")
            rep_email = task.get("rep_email", "")

            # Get relationship profile
            profile_dict: dict[str, Any] = {}
            recent_comms: list[dict[str, Any]] = []
            if self._notion_tam is not None:
                try:
                    profile_dict = await self._notion_tam.get_relationship_profile(
                        account_id
                    )
                    recent_comms = profile_dict.get("communication_history", [])[-5:]
                except Exception as prof_err:
                    self._log.warning(
                        "health_checkin_profile_failed",
                        account_id=account_id,
                        error=str(prof_err),
                    )

            # Get current health score
            health_dict: dict[str, Any] = task.get("health_score", {})

            # Build prompt and call LLM
            prompt = build_health_checkin_prompt(
                health_score=health_dict,
                relationship_profile=profile_dict,
                recent_communications=recent_comms,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": TAM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
            )

            raw_text = response.get("content", "") if isinstance(response, dict) else (
                response.content if hasattr(response, "content") else str(response)
            )
            cleaned = self._extract_json_from_response(raw_text)
            parsed = json.loads(cleaned)

            subject = parsed.get("subject", "Health Check-in")
            body_html = parsed.get("body_html", "")

            # Create Gmail DRAFT
            draft_id: str | None = None
            if self._gmail_service is not None and rep_email:
                try:
                    from src.app.services.gsuite.models import EmailMessage

                    draft_email = EmailMessage(
                        to=rep_email,
                        subject=subject,
                        body_html=body_html,
                    )
                    draft_result = await self._gmail_service.create_draft(draft_email)
                    draft_id = (
                        draft_result.draft_id
                        if hasattr(draft_result, "draft_id")
                        else draft_result.get("draft_id", "")
                        if isinstance(draft_result, dict)
                        else None
                    )
                except Exception as draft_err:
                    self._log.warning(
                        "health_checkin_draft_failed",
                        account_id=account_id,
                        error=str(draft_err),
                    )
            elif self._gmail_service is None:
                self._log.warning(
                    "health_checkin_draft_skipped",
                    reason="gmail_service not configured",
                )

            # Log communication to Notion relationship profile
            if self._notion_tam is not None:
                try:
                    from datetime import datetime, timezone

                    comm_record = {
                        "date": datetime.now(timezone.utc).isoformat(),
                        "communication_type": "health_checkin",
                        "subject": subject,
                        "outcome": "",
                    }
                    await self._notion_tam.log_communication(account_id, comm_record)
                except Exception as log_err:
                    self._log.warning(
                        "health_checkin_comm_log_failed",
                        account_id=account_id,
                        error=str(log_err),
                    )

            result = TAMResult(
                task_type="health_checkin",
                communication_content=body_html,
                communication_type="health_checkin",
                draft_id=draft_id,
                confidence="high",
            )
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "health_checkin_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "health_checkin",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_customer_success_review(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate comprehensive Customer Success Review as a Gmail draft.

        Gathers health score, full profile, and tickets for a comprehensive
        technical health and relationship review distinct from CSM QBR materials.
        """
        try:
            account_id = task.get("account_id", "")
            rep_email = task.get("rep_email", "")

            # Get relationship profile
            profile_dict: dict[str, Any] = {}
            if self._notion_tam is not None:
                try:
                    profile_dict = await self._notion_tam.get_relationship_profile(
                        account_id
                    )
                except Exception as prof_err:
                    self._log.warning(
                        "csr_profile_failed",
                        account_id=account_id,
                        error=str(prof_err),
                    )

            # Get health score
            health_dict: dict[str, Any] = task.get("health_score", {})

            # Get open tickets
            tickets_list: list[dict[str, Any]] = []
            if self._ticket_client is not None:
                try:
                    raw_tickets = await self._ticket_client.get_open_tickets(account_id)
                    tickets_list = [
                        t if isinstance(t, dict) else t.model_dump()
                        if hasattr(t, "model_dump")
                        else {"ticket_id": str(t)}
                        for t in raw_tickets
                    ]
                except Exception as ticket_err:
                    self._log.warning(
                        "csr_tickets_failed",
                        account_id=account_id,
                        error=str(ticket_err),
                    )

            # Build prompt and call LLM
            prompt = build_customer_success_review_prompt(
                health_score=health_dict,
                relationship_profile=profile_dict,
                tickets=tickets_list,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": TAM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )

            raw_text = response.get("content", "") if isinstance(response, dict) else (
                response.content if hasattr(response, "content") else str(response)
            )
            cleaned = self._extract_json_from_response(raw_text)
            parsed = json.loads(cleaned)

            subject = parsed.get("subject", "Customer Success Review")
            body_html = parsed.get("body_html", "")

            # Create Gmail DRAFT
            draft_id: str | None = None
            if self._gmail_service is not None and rep_email:
                try:
                    from src.app.services.gsuite.models import EmailMessage

                    draft_email = EmailMessage(
                        to=rep_email,
                        subject=subject,
                        body_html=body_html,
                    )
                    draft_result = await self._gmail_service.create_draft(draft_email)
                    draft_id = (
                        draft_result.draft_id
                        if hasattr(draft_result, "draft_id")
                        else draft_result.get("draft_id", "")
                        if isinstance(draft_result, dict)
                        else None
                    )
                except Exception as draft_err:
                    self._log.warning(
                        "csr_draft_failed",
                        account_id=account_id,
                        error=str(draft_err),
                    )
            elif self._gmail_service is None:
                self._log.warning(
                    "csr_draft_skipped",
                    reason="gmail_service not configured",
                )

            result = TAMResult(
                task_type="customer_success_review",
                communication_content=body_html,
                communication_type="customer_success_review",
                draft_id=draft_id,
                confidence="high",
            )
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "customer_success_review_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "customer_success_review",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_update_relationship_profile(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge profile updates into Notion relationship profile.

        Extracts profile_updates dict from task, gets existing profile,
        merges updates, and writes back to Notion.
        """
        try:
            account_id = task.get("account_id", "")
            profile_updates = task.get("profile_updates", {})

            if self._notion_tam is None:
                return {
                    "task_type": "update_relationship_profile",
                    "error": "NotionTAM adapter not configured",
                    "confidence": "low",
                    "partial": True,
                }

            # Get existing profile
            existing_profile: dict[str, Any] = {}
            try:
                existing_profile = await self._notion_tam.get_relationship_profile(
                    account_id
                )
            except Exception as prof_err:
                self._log.warning(
                    "update_profile_fetch_failed",
                    account_id=account_id,
                    error=str(prof_err),
                )

            # Merge updates into existing profile
            merged_profile = {**existing_profile, **profile_updates}
            merged_profile["account_id"] = account_id

            # Write updated profile to Notion
            try:
                if existing_profile.get("profile_page_id"):
                    await self._notion_tam.update_relationship_profile(
                        existing_profile["profile_page_id"],
                        merged_profile,
                    )
                else:
                    await self._notion_tam.create_relationship_profile(
                        merged_profile,
                    )
            except Exception as write_err:
                self._log.warning(
                    "update_profile_write_failed",
                    account_id=account_id,
                    error=str(write_err),
                )
                return {
                    "task_type": "update_relationship_profile",
                    "error": str(write_err),
                    "confidence": "low",
                    "partial": True,
                }

            from src.app.agents.technical_account_manager.schemas import (
                RelationshipProfile,
            )

            # Attempt to validate as RelationshipProfile
            try:
                validated_profile = RelationshipProfile.model_validate(merged_profile)
                profile_data = validated_profile
            except Exception:
                profile_data = None

            result = TAMResult(
                task_type="update_relationship_profile",
                relationship_profile=profile_data,
                confidence="high",
            )
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "update_relationship_profile_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "update_relationship_profile",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    # -- Private Helpers -----------------------------------------------------------

    async def _dispatch_escalation_notifications(
        self,
        account_id: str,
        health_score_result: HealthScoreResult,
        context: dict[str, Any],
        account: dict[str, Any] | None = None,
    ) -> EscalationNotificationResult:
        """Fire all 4 escalation notification channels independently.

        Each channel is independently try/except'd so one failure does not
        block others:
        1. Notion: update account page with health score + RAG status
        2. Event bus: publish AgentEvent with AGENT_HEALTH to notify Sales Agent
        3. Email alert draft: create_draft (NEVER send_email) -- alert says
           "check your drafts for outreach"
        4. Chat alert: send_message with link/note about the draft

        Args:
            account_id: Account the escalation was triggered for.
            health_score_result: The health score that triggered escalation.
            context: Execution context with tenant_id.
            account: Optional account metadata dict with rep_email, page_id, etc.

        Returns:
            EscalationNotificationResult with per-channel success booleans.
        """
        if account is None:
            account = {}
        channels: dict[str, bool] = {
            "notion": False,
            "event_bus": False,
            "email_alert": False,
            "chat_alert": False,
        }
        draft_id: str | None = None
        tenant_id = context.get("tenant_id", "")

        # Channel 1: Notion -- update account page with health score + RAG
        try:
            if self._notion_tam is not None:
                page_id = account.get("page_id", "")
                if page_id:
                    await self._notion_tam.update_health_score(
                        page_id,
                        health_score_result.score,
                        health_score_result.rag_status,
                    )
                    channels["notion"] = True
        except Exception as notion_err:
            self._log.warning(
                "escalation_notify_notion_failed",
                account_id=account_id,
                error=str(notion_err),
            )

        # Channel 2: Event bus -- publish AGENT_HEALTH event
        try:
            if self._event_bus is not None:
                from src.app.events.schemas import (
                    AgentEvent,
                    EventPriority,
                    EventType,
                )

                event = AgentEvent(
                    event_type=EventType.AGENT_HEALTH,
                    tenant_id=tenant_id,
                    source_agent_id="technical_account_manager",
                    call_chain=["technical_account_manager"],
                    priority=EventPriority.HIGH,
                    data={
                        "alert_type": "tam_escalation",
                        "account_id": account_id,
                        "health_score": health_score_result.score,
                        "rag_status": health_score_result.rag_status,
                        "previous_rag": health_score_result.previous_rag,
                        "action": "review_draft_outreach",
                    },
                )
                await self._event_bus.publish("escalations", event)
                channels["event_bus"] = True
        except Exception as bus_err:
            self._log.warning(
                "escalation_notify_event_bus_failed",
                account_id=account_id,
                error=str(bus_err),
            )

        # Channel 3: Email alert DRAFT (NEVER send_email)
        # The alert draft tells the rep to check their drafts for the outreach email
        try:
            rep_email = account.get("rep_email", "")
            if self._gmail_service is not None and rep_email:
                from src.app.services.gsuite.models import EmailMessage

                alert_subject = (
                    f"[TAM ALERT] Account {account_id} health: "
                    f"{health_score_result.rag_status} "
                    f"(score: {health_score_result.score})"
                )
                alert_body = (
                    f"<p><strong>Account health alert</strong></p>"
                    f"<p>Account <strong>{account_id}</strong> health has "
                    f"changed to <strong>{health_score_result.rag_status}</strong> "
                    f"(score: {health_score_result.score}).</p>"
                )
                if health_score_result.previous_rag:
                    alert_body += (
                        f"<p>Previous status: {health_score_result.previous_rag}</p>"
                    )
                alert_body += (
                    "<p><strong>Action required:</strong> Check your Gmail Drafts "
                    "folder for the escalation outreach email prepared for this "
                    "account. Review and send when ready.</p>"
                )

                alert_email = EmailMessage(
                    to=rep_email,
                    subject=alert_subject,
                    body_html=alert_body,
                )
                alert_draft_result = await self._gmail_service.create_draft(alert_email)
                draft_id = (
                    alert_draft_result.draft_id
                    if hasattr(alert_draft_result, "draft_id")
                    else alert_draft_result.get("draft_id", "")
                    if isinstance(alert_draft_result, dict)
                    else None
                )
                channels["email_alert"] = True
        except Exception as email_err:
            self._log.warning(
                "escalation_notify_email_failed",
                account_id=account_id,
                error=str(email_err),
            )

        # Channel 4: Chat alert -- send_message with link/note about the draft
        try:
            if self._chat_service is not None:
                from src.app.services.gsuite.models import ChatMessage

                space_name = account.get("chat_space", context.get("chat_space", ""))
                if space_name:
                    chat_text = (
                        f"TAM Alert: Account {account_id} health "
                        f"{health_score_result.rag_status} "
                        f"(score: {health_score_result.score}). "
                        f"Escalation outreach draft created in Gmail. "
                        f"Please review and send."
                    )
                    chat_msg = ChatMessage(
                        space_name=space_name,
                        text=chat_text,
                        thread_key=f"tam_escalation_{account_id}",
                    )
                    await self._chat_service.send_message(chat_msg)
                    channels["chat_alert"] = True
        except Exception as chat_err:
            self._log.warning(
                "escalation_notify_chat_failed",
                account_id=account_id,
                error=str(chat_err),
            )

        alerts_sent = sum(1 for v in channels.values() if v)
        self._log.info(
            "escalation_notifications_dispatched",
            account_id=account_id,
            channels=channels,
            alerts_sent=alerts_sent,
        )

        return EscalationNotificationResult(
            account_id=account_id,
            channels=channels,
            draft_id=draft_id,
            alerts_sent=alerts_sent,
        )

    @staticmethod
    def _extract_json_from_response(text: str) -> str:
        """Extract JSON content from an LLM response, stripping code fences.

        Handles markdown code fences (```json ... ```) and finds the first
        JSON array or object in the text.

        Args:
            text: Raw LLM response text (may contain code fences).

        Returns:
            Cleaned JSON string ready for json.loads().

        Raises:
            ValueError: If no JSON array or object is found in the text.
        """
        # Strip code fences
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())

        # Find first JSON array or object
        match = re.search(r"[\[{]", cleaned)
        if match:
            return cleaned[match.start():]

        raise ValueError(f"No JSON found in LLM response: {text[:200]!r}")
