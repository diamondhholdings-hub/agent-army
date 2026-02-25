"""Collections Agent: BaseAgent subclass for AR tracking, payment risk, and collection message generation.

Routes tasks by request_type to five specialized handlers -- AR aging report,
payment risk assessment, collection message generation, escalation check, and
payment plan surfacing.

All draft creation uses gmail_service.create_draft() -- never send_email().

The agent is the single owner of the csm_agent reference and the CSM risk
notification path. After a payment_risk_assessment returns RED or CRITICAL,
_execute_task (implemented as execute()) calls receive_collections_risk()
directly. Handlers never touch csm_agent.

Exports:
    CollectionsAgent: The core collections agent class.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

import structlog

from src.app.agents.base import AgentRegistration, BaseAgent
from src.app.agents.collections.prompt_builders import COLLECTIONS_SYSTEM_PROMPT
from src.app.agents.collections.schemas import CollectionsHandoffRequest

log = structlog.get_logger(__name__)

_TASK_HANDLERS = {
    "ar_aging_report": "handle_ar_aging_report",
    "payment_risk_assessment": "handle_payment_risk_assessment",
    "generate_collection_message": "handle_generate_collection_message",
    "run_escalation_check": "handle_run_escalation_check",
    "surface_payment_plan": "handle_surface_payment_plan",
}


class CollectionsAgent(BaseAgent):
    """Collections agent for AR tracking, payment risk, and escalation management.

    Extends BaseAgent with 5 capability handlers:
    - ar_aging_report: Analyze invoices and produce AR aging buckets
    - payment_risk_assessment: Score payment risk deterministically + LLM narrative
    - generate_collection_message: Generate stage-appropriate email draft
    - run_escalation_check: Deterministic stage advancement + draft creation
    - surface_payment_plan: Generate 3 structured payment plan options

    After payment_risk_assessment returns RED or CRITICAL, the execute()
    method calls self.receive_collections_risk() to notify the CSM agent.
    This is the only call site for CSM notification -- handlers never call
    csm_agent directly.

    CRITICAL: Collections never calls send_email. ALL communications are
    created as Gmail drafts for rep review via gmail_service.create_draft().

    Args:
        registration: Agent registration metadata for the registry.
        llm_service: LLMService (or compatible) for generating content.
        notion_collections: NotionCollectionsAdapter (or compatible).
            None is allowed -- Notion writes are skipped gracefully.
        gmail_service: GmailService (or compatible) for create_draft.
            None is allowed -- draft creation is skipped gracefully.
        chat_service: ChatService (or compatible) for chat alerts.
            None is allowed -- chat alerts are skipped gracefully.
        event_bus: TenantEventBus (or compatible) for event publishing.
            None is allowed -- event publishing is skipped gracefully.
        scorer: PaymentRiskScorer (or compatible) for deterministic scoring.
            None is allowed -- a default scorer is created inside the handler.
        csm_agent: CustomerSuccessAgent (or compatible) for reverse cross-agent
            risk notification. None is allowed -- notification is skipped with
            a warning log.
    """

    def __init__(
        self,
        registration: AgentRegistration,
        llm_service: object,
        notion_collections: object | None = None,
        gmail_service: object | None = None,
        chat_service: object | None = None,
        event_bus: object | None = None,
        scorer: object | None = None,
        csm_agent: object | None = None,  # For reverse cross-agent risk notification
    ) -> None:
        super().__init__(registration)
        self._llm_service = llm_service
        self._notion_collections = notion_collections
        self._gmail_service = gmail_service
        self._chat_service = chat_service
        self._event_bus = event_bus
        self._scorer = scorer
        self._csm_agent = csm_agent
        self._log = structlog.get_logger(__name__).bind(
            agent_id=registration.agent_id,
            agent_name=registration.name,
        )

    # -- Task Router ---------------------------------------------------------------

    async def execute(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Route task to the appropriate handler by request_type.

        After payment_risk_assessment, post-checks the returned result's rag
        field and calls self.receive_collections_risk() when rag is RED or
        CRITICAL.

        Args:
            task: Task specification with 'request_type' key and handler-specific
                fields.
            context: Execution context with tenant_id and session data.

        Returns:
            Handler-specific result dictionary.

        Raises:
            ValueError: If request_type is unknown.
        """
        request_type = task.get("request_type", "")

        if request_type not in _TASK_HANDLERS:
            raise ValueError(
                f"Unknown Collections task type: {request_type!r}. "
                f"Supported: {', '.join(_TASK_HANDLERS.keys())}"
            )

        # Lazy import handlers to avoid circular deps
        from src.app.agents.collections import handlers

        handler_name = _TASK_HANDLERS[request_type]
        handler_fn = getattr(handlers, handler_name)

        result = await handler_fn(
            task,
            self._llm_service,
            self._notion_collections,
            self._gmail_service,
            self._scorer,
        )

        # Post-check: notify CSM agent when payment risk is RED or CRITICAL
        if (
            request_type == "payment_risk_assessment"
            and isinstance(result, dict)
            and result.get("rag") in ("RED", "CRITICAL")
            and "error" not in result
        ):
            account_id = task.get("account_id", result.get("account_id", ""))
            await self.receive_collections_risk(account_id, result["rag"])

        return result

    # -- Cross-Agent Notification --------------------------------------------------

    async def receive_collections_risk(
        self,
        account_id: str,
        risk_band: Literal["GREEN", "AMBER", "RED", "CRITICAL"],
    ) -> None:
        """Notify CSM agent of collections risk for an account.

        Called by execute() after payment_risk_assessment produces RED or
        CRITICAL. GREEN and AMBER do not trigger CSM notification.

        This method is the single cross-agent notification path. Handlers
        never call csm_agent directly.

        Args:
            account_id: The account with elevated payment risk.
            risk_band: The RAG risk classification from PaymentRiskResult.
                Only RED and CRITICAL trigger CSM notification.
        """
        if risk_band not in ("RED", "CRITICAL"):
            return  # Only RED/CRITICAL escalates to CSM

        if self._csm_agent is None:
            self._log.warning(
                "collections.csm_agent_not_configured",
                account_id=account_id,
                risk_band=risk_band,
            )
            return

        try:
            # Try direct method if CSM agent exposes receive_collections_risk
            if hasattr(self._csm_agent, "receive_collections_risk"):
                await self._csm_agent.receive_collections_risk(account_id, risk_band)
            else:
                # Fall back to task dispatch
                await self._csm_agent.process_task({
                    "task_type": "update_health_signal",
                    "account_id": account_id,
                    "signal": "collections_risk",
                    "value": risk_band,
                })
            self._log.info(
                "collections.csm_risk_notified",
                account_id=account_id,
                risk_band=risk_band,
            )
        except Exception as exc:
            self._log.warning(
                "collections.csm_notify_failed",
                account_id=account_id,
                error=str(exc),
            )


__all__ = ["CollectionsAgent"]
