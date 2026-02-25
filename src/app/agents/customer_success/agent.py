"""Customer Success Manager Agent: BaseAgent subclass for account health and growth.

Routes tasks by type to four specialized handlers -- health scan, QBR
generation, expansion check, and feature adoption tracking. Health scoring
uses pure Python CSMHealthScorer (no LLM). All communications create Gmail
DRAFTS for rep review -- the CSM never calls send_email. Expansion
opportunities are dispatched to the Sales Agent for cross-agent handoff.

Exports:
    CustomerSuccessAgent: The core customer success manager agent class.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from src.app.agents.base import AgentRegistration, BaseAgent
from src.app.agents.customer_success.prompt_builders import (
    CSM_SYSTEM_PROMPT,
    build_expansion_prompt,
    build_feature_adoption_prompt,
    build_qbr_prompt,
)
from src.app.agents.customer_success.schemas import (
    CSMAlertResult,
    CSMHealthScore,
    ExpansionOpportunity,
    FeatureAdoptionReport,
    QBRContent,
)


class CustomerSuccessAgent(BaseAgent):
    """Customer success management agent for health monitoring and growth.

    Extends BaseAgent with 4 capability handlers:
    - health_scan: Compute health scores using CSMHealthScorer (no LLM)
    - generate_qbr: Generate Quarterly Business Review content via LLM
    - check_expansion: Detect expansion opportunities and dispatch to Sales Agent
    - track_feature_adoption: Analyze feature adoption and produce reports

    Each handler follows fail-open semantics: on LLM or service error, the
    handler returns a partial result dict with ``{"error": ..., "confidence":
    "low", "partial": True}`` instead of raising, keeping the workflow
    unblocked.

    CRITICAL: CSM never calls send_email. ALL communications are created as
    Gmail drafts for rep review.

    Args:
        registration: Agent registration metadata for the registry.
        llm_service: LLMService (or compatible) for generating content.
        notion_csm: NotionCSMAdapter (or compatible) for Notion operations.
            None is allowed -- Notion writes are skipped gracefully.
        gmail_service: GmailService (or compatible) for create_draft.
            None is allowed -- draft creation is skipped gracefully.
        chat_service: ChatService (or compatible) for chat alerts.
            None is allowed -- chat alerts are skipped gracefully.
        event_bus: TenantEventBus (or compatible) for event publishing.
            None is allowed -- event publishing is skipped gracefully.
        health_scorer: CSMHealthScorer (or compatible) for score computation.
            None is allowed -- health scan returns error dict.
        sales_agent: Sales Agent instance for expansion opportunity dispatch.
            None is allowed -- expansion dispatch is skipped with a warning.
    """

    def __init__(
        self,
        registration: AgentRegistration,
        llm_service: object,
        notion_csm: object | None = None,
        gmail_service: object | None = None,
        chat_service: object | None = None,
        event_bus: object | None = None,
        health_scorer: object | None = None,
        sales_agent: object | None = None,
    ) -> None:
        super().__init__(registration)
        self._llm_service = llm_service
        self._notion_csm = notion_csm
        self._gmail_service = gmail_service
        self._chat_service = chat_service
        self._event_bus = event_bus
        self._health_scorer = health_scorer
        self._sales_agent = sales_agent
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
            "generate_qbr": self._handle_generate_qbr,
            "check_expansion": self._handle_check_expansion,
            "track_feature_adoption": self._handle_track_feature_adoption,
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
        """Compute health score for one or all accounts using CSMHealthScorer.

        Uses pure Python CSMHealthScorer (no LLM) for deterministic scoring.
        For each account: fetches signals, computes score, triggers churn
        alerts if needed, and updates Notion.
        """
        try:
            if self._health_scorer is None:
                return {
                    "task_type": "health_scan",
                    "error": "CSMHealthScorer not configured",
                    "confidence": "low",
                    "partial": True,
                }

            account_id = task.get("account_id")
            tenant_id = context.get("tenant_id", "")

            # Determine accounts to scan
            if account_id:
                accounts = [{"account_id": account_id}]
                if self._notion_csm is not None:
                    try:
                        account_page = await self._notion_csm.get_account(account_id)
                        if account_page:
                            accounts = [account_page]
                    except Exception as notion_err:
                        self._log.warning(
                            "health_scan_notion_fetch_failed",
                            account_id=account_id,
                            error=str(notion_err),
                        )
            else:
                if self._notion_csm is None:
                    return {
                        "task_type": "health_scan",
                        "error": "NotionCSM adapter not configured for batch scan",
                        "confidence": "low",
                        "partial": True,
                    }
                accounts = await self._notion_csm.query_all_accounts()

            health_scores: list[CSMHealthScore] = []

            for account in accounts:
                acct_id = (
                    account.get("account_id", "")
                    if isinstance(account, dict)
                    else str(account)
                )

                # Build CSMHealthSignals from account data or task-provided signals
                signals_data = task.get("signals", {})
                if isinstance(account, dict):
                    # Merge account-level signal data
                    for key in (
                        "feature_adoption_rate", "usage_trend",
                        "login_frequency_days", "days_since_last_interaction",
                        "stakeholder_engagement", "nps_score",
                        "invoice_payment_status", "days_to_renewal",
                        "seats_utilization_rate", "open_ticket_count",
                        "avg_ticket_sentiment", "escalation_count_90_days",
                        "tam_health_rag",
                    ):
                        if key in account and key not in signals_data:
                            signals_data[key] = account[key]

                # Compute health score via pure Python scorer
                try:
                    from src.app.agents.customer_success.schemas import CSMHealthSignals

                    signals = CSMHealthSignals(**signals_data)
                    health_score = self._health_scorer.score(
                        signals=signals, account_id=acct_id
                    )
                except Exception as score_err:
                    self._log.warning(
                        "health_scan_score_failed",
                        account_id=acct_id,
                        error=str(score_err),
                    )
                    continue

                health_scores.append(health_score)

                # Trigger churn alerts if should_alert
                if health_score.should_alert:
                    try:
                        await self._dispatch_churn_alerts(
                            account_id=acct_id,
                            health_score=health_score,
                            context=context,
                            account=account if isinstance(account, dict) else {},
                        )
                    except Exception as alert_err:
                        self._log.warning(
                            "health_scan_alert_failed",
                            account_id=acct_id,
                            error=str(alert_err),
                        )

                # Update Notion with new health score
                if self._notion_csm is not None:
                    try:
                        page_id = (
                            account.get("id", "")
                            if isinstance(account, dict)
                            else ""
                        )
                        if page_id:
                            await self._notion_csm.update_health_score(
                                page_id, health_score.score, health_score.rag
                            )
                    except Exception as notion_err:
                        self._log.warning(
                            "health_scan_notion_update_failed",
                            account_id=acct_id,
                            error=str(notion_err),
                        )

            return {
                "task_type": "health_scan",
                "health_scores": [hs.model_dump() for hs in health_scores],
                "health_score": (
                    health_scores[0].model_dump()
                    if len(health_scores) == 1
                    else None
                ),
                "confidence": "high",
                "scanned_count": len(health_scores),
            }

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

    async def _handle_generate_qbr(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate Quarterly Business Review content via LLM.

        Gathers account data and health history, uses LLM to produce QBR
        content, creates a Notion QBR page, and drafts a notification email
        to the account rep.
        """
        try:
            account_id = task.get("account_id", "")
            account_data = task.get("account_data", {})
            health_history = task.get("health_history", {})
            period = task.get("period", "")
            rep_email = task.get("rep_email", "")
            account_name = task.get("account_name", account_data.get("name", ""))

            # Build prompt and call LLM
            prompt = build_qbr_prompt(
                account_data=account_data,
                health_history=health_history,
                period=period,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": CSM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )

            raw_text = (
                response.get("content", "")
                if isinstance(response, dict)
                else (
                    response.content
                    if hasattr(response, "content")
                    else str(response)
                )
            )
            cleaned = self._extract_json_from_response(raw_text)
            parsed = json.loads(cleaned)

            # Create QBRContent model
            qbr = QBRContent(
                account_id=account_id,
                period=parsed.get("period", period),
                health_summary=parsed.get("health_summary", ""),
                roi_metrics=parsed.get("roi_metrics", {}),
                feature_adoption_scorecard=parsed.get(
                    "feature_adoption_scorecard", {}
                ),
                expansion_next_steps=parsed.get("expansion_next_steps", []),
                trigger=parsed.get("trigger", "quarterly"),
            )

            # Create QBR page in Notion
            qbr_page_id: str | None = None
            if self._notion_csm is not None:
                try:
                    qbr_page_id = await self._notion_csm.create_qbr_page(
                        qbr, account_name=account_name
                    )
                except Exception as notion_err:
                    self._log.warning(
                        "generate_qbr_notion_failed",
                        account_id=account_id,
                        error=str(notion_err),
                    )

            # Create Gmail DRAFT for rep notification (NEVER send_email)
            draft_id: str | None = None
            if self._gmail_service is not None and rep_email:
                try:
                    from src.app.services.gsuite.models import EmailMessage

                    subject = f"QBR Ready: {account_name} — {period}"
                    body_html = (
                        f"<p>Your Quarterly Business Review for "
                        f"<strong>{account_name}</strong> ({period}) has been "
                        f"generated.</p>"
                        f"<p><strong>Health Summary:</strong> "
                        f"{qbr.health_summary[:500]}</p>"
                        f"<p>Review the full QBR in Notion and prepare for the "
                        f"customer meeting.</p>"
                    )

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
                        "generate_qbr_draft_failed",
                        account_id=account_id,
                        error=str(draft_err),
                    )
            elif self._gmail_service is None:
                self._log.warning(
                    "generate_qbr_draft_skipped",
                    reason="gmail_service not configured",
                )

            return {
                "task_type": "generate_qbr",
                "qbr": qbr.model_dump(),
                "qbr_page_id": qbr_page_id,
                "draft_id": draft_id,
                "confidence": "high",
            }

        except Exception as exc:
            self._log.warning(
                "generate_qbr_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "generate_qbr",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_check_expansion(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Detect expansion opportunities via LLM and dispatch to Sales Agent.

        Analyzes account usage signals to identify upsell/cross-sell
        opportunities. Creates Notion records, dispatches to Sales Agent
        via self._sales_agent.execute(), and drafts notification email.

        NOTE: CSM -> Sales expansion dispatch is the first reverse-direction
        cross-agent handoff. If _sales_agent is None, skip gracefully.
        """
        try:
            account_id = task.get("account_id", "")
            account_data = task.get("account_data", {})
            usage_signals = task.get("usage_signals", {})
            rep_email = task.get("rep_email", "")

            # Build prompt and call LLM
            prompt = build_expansion_prompt(
                account_data=account_data,
                usage_signals=usage_signals,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": CSM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )

            raw_text = (
                response.get("content", "")
                if isinstance(response, dict)
                else (
                    response.content
                    if hasattr(response, "content")
                    else str(response)
                )
            )
            cleaned = self._extract_json_from_response(raw_text)
            parsed = json.loads(cleaned)

            # Handle single opportunity or list
            opportunities_data = (
                [parsed] if isinstance(parsed, dict) else parsed
            )

            opportunities: list[ExpansionOpportunity] = []
            for opp_data in opportunities_data:
                try:
                    opp = ExpansionOpportunity(
                        account_id=account_id,
                        opportunity_type=opp_data.get("opportunity_type", "module"),
                        evidence=opp_data.get("evidence", ""),
                        estimated_arr_impact=opp_data.get("estimated_arr_impact"),
                        recommended_talk_track=opp_data.get(
                            "recommended_talk_track", ""
                        ),
                        confidence=opp_data.get("confidence", "medium"),
                    )
                    opportunities.append(opp)
                except Exception as model_err:
                    self._log.warning(
                        "check_expansion_model_failed",
                        account_id=account_id,
                        error=str(model_err),
                    )

            # Save to Notion
            notion_page_ids: list[str] = []
            if self._notion_csm is not None:
                for opp in opportunities:
                    try:
                        page_id = await self._notion_csm.create_expansion_record(opp)
                        notion_page_ids.append(page_id)
                    except Exception as notion_err:
                        self._log.warning(
                            "check_expansion_notion_failed",
                            account_id=account_id,
                            error=str(notion_err),
                        )

            # Dispatch to Sales Agent (reverse cross-agent handoff)
            sales_dispatch_result: dict[str, Any] | None = None
            if self._sales_agent is not None:
                for opp in opportunities:
                    try:
                        sales_dispatch_result = await self._sales_agent.execute(
                            {
                                "type": "handle_expansion_opportunity",
                                "account_id": account_id,
                                "opportunity_type": opp.opportunity_type,
                                "evidence": opp.evidence,
                                "estimated_arr_impact": opp.estimated_arr_impact,
                                "recommended_talk_track": opp.recommended_talk_track,
                                "confidence": opp.confidence,
                            },
                            context,
                        )
                        self._log.info(
                            "expansion_dispatched_to_sales",
                            account_id=account_id,
                            opportunity_type=opp.opportunity_type,
                        )
                    except Exception as sales_err:
                        self._log.warning(
                            "expansion_sales_dispatch_failed",
                            account_id=account_id,
                            error=str(sales_err),
                        )
            else:
                self._log.warning(
                    "expansion_sales_dispatch_skipped",
                    account_id=account_id,
                    reason="sales_agent not configured",
                )

            # Create Gmail DRAFT for rep notification (NEVER send_email)
            draft_id: str | None = None
            if self._gmail_service is not None and rep_email and opportunities:
                try:
                    from src.app.services.gsuite.models import EmailMessage

                    opp_summary = "; ".join(
                        f"{o.opportunity_type} ({o.confidence})"
                        for o in opportunities
                    )
                    subject = f"Expansion Opportunities: {account_id}"
                    body_html = (
                        f"<p><strong>Expansion opportunities detected</strong> "
                        f"for account <strong>{account_id}</strong>:</p>"
                        f"<p>{opp_summary}</p>"
                        f"<p>Review details in Notion and coordinate with the "
                        f"sales team.</p>"
                    )

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
                        "check_expansion_draft_failed",
                        account_id=account_id,
                        error=str(draft_err),
                    )
            elif self._gmail_service is None:
                self._log.warning(
                    "check_expansion_draft_skipped",
                    reason="gmail_service not configured",
                )

            return {
                "task_type": "check_expansion",
                "opportunities": [o.model_dump() for o in opportunities],
                "notion_page_ids": notion_page_ids,
                "sales_dispatch_result": sales_dispatch_result,
                "draft_id": draft_id,
                "confidence": "high",
            }

        except Exception as exc:
            self._log.warning(
                "check_expansion_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "check_expansion",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_track_feature_adoption(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Analyze feature adoption via LLM and produce a report.

        Examines per-feature usage data for an account, generates adoption
        recommendations, and drafts a notification email to the rep.
        """
        try:
            account_id = task.get("account_id", "")
            account_data = task.get("account_data", {})
            feature_usage = task.get("feature_usage", {})
            rep_email = task.get("rep_email", "")

            # Build prompt and call LLM
            prompt = build_feature_adoption_prompt(
                account_data=account_data,
                feature_usage=feature_usage,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": CSM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )

            raw_text = (
                response.get("content", "")
                if isinstance(response, dict)
                else (
                    response.content
                    if hasattr(response, "content")
                    else str(response)
                )
            )
            cleaned = self._extract_json_from_response(raw_text)
            parsed = json.loads(cleaned)

            # Create FeatureAdoptionReport model
            report = FeatureAdoptionReport(
                account_id=account_id,
                features_used=parsed.get("features_used", []),
                adoption_rate=parsed.get("adoption_rate", 0.0),
                underutilized_features=parsed.get("underutilized_features", []),
                recommendations=parsed.get("recommendations", []),
                benchmark_comparison=parsed.get("benchmark_comparison"),
            )

            # Create Gmail DRAFT for rep notification (NEVER send_email)
            draft_id: str | None = None
            if self._gmail_service is not None and rep_email:
                try:
                    from src.app.services.gsuite.models import EmailMessage

                    subject = (
                        f"Feature Adoption Report: {account_id} "
                        f"({report.adoption_rate:.0%})"
                    )
                    recs_html = "".join(
                        f"<li>{r}</li>" for r in report.recommendations[:5]
                    )
                    body_html = (
                        f"<p>Feature adoption report for "
                        f"<strong>{account_id}</strong>:</p>"
                        f"<p>Adoption rate: <strong>"
                        f"{report.adoption_rate:.0%}</strong></p>"
                        f"<p>Underutilized features: "
                        f"{', '.join(report.underutilized_features) or 'None'}</p>"
                        f"<p><strong>Recommendations:</strong></p>"
                        f"<ul>{recs_html}</ul>"
                    )

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
                        "track_adoption_draft_failed",
                        account_id=account_id,
                        error=str(draft_err),
                    )
            elif self._gmail_service is None:
                self._log.warning(
                    "track_adoption_draft_skipped",
                    reason="gmail_service not configured",
                )

            return {
                "task_type": "track_feature_adoption",
                "report": report.model_dump(),
                "draft_id": draft_id,
                "confidence": "high",
            }

        except Exception as exc:
            self._log.warning(
                "track_feature_adoption_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "track_feature_adoption",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    # -- Private Helpers -----------------------------------------------------------

    async def _dispatch_churn_alerts(
        self,
        account_id: str,
        health_score: CSMHealthScore,
        context: dict[str, Any],
        account: dict[str, Any] | None = None,
    ) -> CSMAlertResult:
        """Fire all 4 churn alert notification channels independently.

        Each channel is independently try/except'd so one failure does not
        block others:
        1. Notion: update_health_score() on account page
        2. Event bus: publish AGENT_HEALTH event
        3. Gmail: create_draft() ONLY (NEVER send_email)
        4. Chat: send_message() alert

        Args:
            account_id: Account the alert was triggered for.
            health_score: The CSMHealthScore that triggered the alert.
            context: Execution context with tenant_id.
            account: Optional account metadata dict with rep_email, id, etc.

        Returns:
            CSMAlertResult with per-channel success booleans.
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
            if self._notion_csm is not None:
                page_id = account.get("id", "")
                if page_id:
                    await self._notion_csm.update_health_score(
                        page_id,
                        health_score.score,
                        health_score.rag,
                    )
                    channels["notion"] = True
        except Exception as notion_err:
            self._log.warning(
                "churn_alert_notion_failed",
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
                    source_agent_id="customer_success_manager",
                    call_chain=["customer_success_manager"],
                    priority=EventPriority.HIGH,
                    data={
                        "alert_type": "csm_churn_alert",
                        "account_id": account_id,
                        "health_score": health_score.score,
                        "rag_status": health_score.rag,
                        "churn_risk_level": health_score.churn_risk_level,
                        "churn_triggered_by": health_score.churn_triggered_by,
                        "action": "review_account_health",
                    },
                )
                await self._event_bus.publish("churn_alerts", event)
                channels["event_bus"] = True
        except Exception as bus_err:
            self._log.warning(
                "churn_alert_event_bus_failed",
                account_id=account_id,
                error=str(bus_err),
            )

        # Channel 3: Email alert DRAFT (NEVER send_email)
        try:
            rep_email = account.get("rep_email", "")
            if self._gmail_service is not None and rep_email:
                from src.app.services.gsuite.models import EmailMessage

                alert_subject = (
                    f"[CSM ALERT] Account {account_id} health: "
                    f"{health_score.rag} "
                    f"(score: {health_score.score:.0f})"
                )
                alert_body = (
                    f"<p><strong>CSM Account Health Alert</strong></p>"
                    f"<p>Account <strong>{account_id}</strong> health has "
                    f"reached <strong>{health_score.rag}</strong> "
                    f"(score: {health_score.score:.0f}).</p>"
                    f"<p>Churn risk: <strong>"
                    f"{health_score.churn_risk_level}</strong></p>"
                )
                if health_score.churn_triggered_by:
                    alert_body += (
                        f"<p>Triggered by: {health_score.churn_triggered_by}</p>"
                    )
                alert_body += (
                    "<p><strong>Action required:</strong> Review account health "
                    "and initiate retention outreach.</p>"
                )

                alert_email = EmailMessage(
                    to=rep_email,
                    subject=alert_subject,
                    body_html=alert_body,
                )
                alert_draft_result = await self._gmail_service.create_draft(
                    alert_email
                )
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
                "churn_alert_email_failed",
                account_id=account_id,
                error=str(email_err),
            )

        # Channel 4: Chat alert -- send_message with alert note
        try:
            if self._chat_service is not None:
                from src.app.services.gsuite.models import ChatMessage

                space_name = account.get(
                    "chat_space", context.get("chat_space", "")
                )
                if space_name:
                    chat_text = (
                        f"CSM Alert: Account {account_id} health "
                        f"{health_score.rag} "
                        f"(score: {health_score.score:.0f}). "
                        f"Churn risk: {health_score.churn_risk_level}. "
                        f"Please review and take action."
                    )
                    chat_msg = ChatMessage(
                        space_name=space_name,
                        text=chat_text,
                        thread_key=f"csm_churn_alert_{account_id}",
                    )
                    await self._chat_service.send_message(chat_msg)
                    channels["chat_alert"] = True
        except Exception as chat_err:
            self._log.warning(
                "churn_alert_chat_failed",
                account_id=account_id,
                error=str(chat_err),
            )

        alerts_sent = sum(1 for v in channels.values() if v)
        self._log.info(
            "churn_alerts_dispatched",
            account_id=account_id,
            channels=channels,
            alerts_sent=alerts_sent,
        )

        return CSMAlertResult(
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
