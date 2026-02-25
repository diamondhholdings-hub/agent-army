"""Task handlers for the Collections Agent.

Five async handler functions — one per CollectionsHandoffRequest.request_type.
Each handler orchestrates the full task lifecycle for its capability:
score → prompt → LLM → persist → draft.

All handlers follow fail-open semantics: any exception returns a partial result
dict with ``{"error": ..., "confidence": "low", "partial": True}`` instead of
raising, keeping the workflow unblocked under LLM or service failures.

Key design constraints:
- ALL handlers are ``async def``
- NO ``csm_agent`` reference in any handler (CSM notification path is handled
  by CollectionsAgent._execute_task() in agent.py after inspecting the returned
  result)
- ALL communications use ``gmail_service.create_draft()``, NEVER ``send_email``
- Escalation stage ADVANCEMENT is DETERMINISTIC (not LLM). LLM is used only
  to generate Stage 5 notification EMAIL CONTENT after advancement.
- ``handle_run_escalation_check`` calls ``handle_generate_collection_message``
  internally after advancing to stages 1-4, producing a ready-to-send draft.

Exports:
    handle_ar_aging_report: Analyze invoices and produce ARAgingReport.
    handle_payment_risk_assessment: Score risk + enrich with LLM narrative.
    handle_generate_collection_message: Generate stage-appropriate email draft.
    handle_run_escalation_check: Deterministic stage advancement + draft creation.
    handle_surface_payment_plan: Generate 3 payment plan options.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from src.app.agents.collections.prompt_builders import (
    COLLECTIONS_SYSTEM_PROMPT,
    build_ar_report_prompt,
    build_collection_message_prompt,
    build_escalation_check_prompt,
    build_payment_plan_prompt,
    build_risk_narrative_prompt,
)
from src.app.agents.collections.schemas import (
    ARAgingReport,
    CollectionMessageStage,
    CollectionsAlertResult,
    EscalationState,
    PaymentPlanOptions,
    PaymentRiskResult,
    PaymentRiskSignals,
)
from src.app.agents.collections.scorer import (
    STAGE_TIME_FLOORS,
    PaymentRiskScorer,
    compute_tone_modifier,
)

log = logging.getLogger(__name__)

__all__ = [
    "handle_ar_aging_report",
    "handle_payment_risk_assessment",
    "handle_generate_collection_message",
    "handle_run_escalation_check",
    "handle_surface_payment_plan",
]


# -- Private helpers ----------------------------------------------------------


def _extract_json(text: str) -> str:
    """Extract JSON from an LLM response, stripping markdown code fences.

    Handles triple-backtick fenced JSON and finds the first JSON object or
    array in the remaining text.

    Args:
        text: Raw LLM response text.

    Returns:
        Cleaned JSON string ready for json.loads().

    Raises:
        ValueError: If no JSON object or array is found.
    """
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())
    match = re.search(r"[\[{]", cleaned)
    if match:
        return cleaned[match.start():]
    raise ValueError(f"No JSON found in LLM response: {text[:200]!r}")


def _get_llm_text(response: Any) -> str:
    """Extract text content from an LLM service response.

    Handles both dict responses (``{"content": "..."}`` shape) and objects
    with a ``.content`` attribute.

    Args:
        response: LLM service response object or dict.

    Returns:
        Raw text content string.
    """
    if isinstance(response, dict):
        return response.get("content", "")
    if hasattr(response, "content"):
        return response.content
    return str(response)


# -- Handlers -----------------------------------------------------------------


async def handle_ar_aging_report(
    task: dict,
    llm_service: Any,
    notion_collections: Any,
    gmail_service: Any,
    scorer: Any,
    **kwargs: Any,
) -> dict:
    """Analyze invoice data and produce a structured AR aging report.

    Fetches raw invoices from Notion (if adapter provided), builds the AR aging
    prompt, calls LLM to compute bucket totals, and returns a serialized
    ARAgingReport dict.

    Args:
        task: Task dict with ``account_id`` and optional raw invoice data.
        llm_service: LLMService for LLM completion calls.
        notion_collections: NotionCollectionsAdapter for fetching AR data.
            None is allowed — falls back to task-provided invoice data.
        gmail_service: Not used by this handler (accepted for uniform signature).
        scorer: Not used by this handler (accepted for uniform signature).
        **kwargs: Additional context (ignored).

    Returns:
        ARAgingReport model_dump() dict, or fail-open error dict on failure.
    """
    try:
        account_id: str = task.get("account_id", "")

        # Fetch raw invoices from Notion or task payload
        raw_invoices: list[dict] = task.get("raw_invoices", [])
        if notion_collections is not None:
            try:
                fetched = await notion_collections.get_ar_aging(account_id)
                if fetched:
                    raw_invoices = fetched
            except Exception as fetch_err:
                log.warning(
                    "ar_aging_notion_fetch_failed",
                    extra={"account_id": account_id, "error": str(fetch_err)},
                )

        # Short-circuit: no outstanding invoices
        if not raw_invoices:
            return {
                "account_id": account_id,
                "total_outstanding_usd": 0.0,
                "buckets": [],
                "message": "No outstanding invoices",
            }

        # LLM required to compute aging report
        if llm_service is None:
            return {
                "account_id": account_id,
                "error": "llm_service not configured",
                "confidence": "low",
                "partial": True,
            }

        prompt = build_ar_report_prompt(account_id, raw_invoices)
        response = await llm_service.completion(
            messages=[
                {"role": "system", "content": COLLECTIONS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        raw_text = _get_llm_text(response)
        parsed = json.loads(_extract_json(raw_text))

        # Validate via model (partial parse on failure)
        try:
            report = ARAgingReport(
                account_id=account_id,
                account_name=parsed.get("account_name", account_id),
                total_outstanding_usd=float(parsed.get("total_outstanding_usd", 0.0)),
                buckets=parsed.get("buckets", []),
                oldest_invoice_number=parsed.get("oldest_invoice_number", ""),
                oldest_invoice_amount_usd=float(
                    parsed.get("oldest_invoice_amount_usd", 0.0)
                ),
                oldest_invoice_date=parsed.get("oldest_invoice_date", "2000-01-01"),
            )
            return report.model_dump()
        except Exception:
            # Return raw parsed dict if model validation fails
            parsed["account_id"] = account_id
            return parsed

    except Exception as exc:
        log.warning(
            "handle_ar_aging_report_failed",
            extra={"account_id": task.get("account_id", ""), "error": str(exc)},
        )
        return {"error": str(exc), "confidence": "low", "partial": True}


async def handle_payment_risk_assessment(
    task: dict,
    llm_service: Any,
    notion_collections: Any,
    gmail_service: Any,
    scorer: Any,
    **kwargs: Any,
) -> dict:
    """Score payment risk deterministically, then enrich with LLM narrative.

    Extracts PaymentRiskSignals from the task dict, calls PaymentRiskScorer.score()
    for the deterministic base, then uses LLM to generate a human-readable
    narrative enrichment. Returns a PaymentRiskResult.model_dump() dict.

    NOTE: This handler does NOT call csm_agent. The agent's _execute_task()
    checks the returned result's ``rag`` field and calls
    self.receive_collections_risk() directly.

    Args:
        task: Task dict with ``account_id`` and payment signal fields.
        llm_service: LLMService for narrative enrichment.
        notion_collections: Not used directly (accepted for uniform signature).
        gmail_service: Not used by this handler (accepted for uniform signature).
        scorer: PaymentRiskScorer instance. If None, a default scorer is created.
        **kwargs: Additional context (ignored).

    Returns:
        PaymentRiskResult model_dump() dict, or fail-open error dict on failure.
    """
    try:
        account_id: str = task.get("account_id", "")
        account_context: dict = task.get("account_context", {})

        # Build PaymentRiskSignals from task data
        signals = PaymentRiskSignals(
            account_id=account_id,
            days_overdue=int(task.get("days_overdue", 0)),
            payment_history_streak=int(task.get("payment_history_streak", 0)),
            total_outstanding_balance_usd=float(
                task.get("total_outstanding_balance_usd", 0.0)
            ),
            days_to_renewal=int(task.get("days_to_renewal", 365)),
            arr_usd=float(task.get("arr_usd", 0.0)),
            tenure_years=float(task.get("tenure_years", 0.0)),
        )

        # Deterministic base score (no LLM)
        active_scorer: PaymentRiskScorer = scorer if scorer is not None else PaymentRiskScorer()
        result: PaymentRiskResult = active_scorer.score(signals)

        # LLM narrative enrichment
        if llm_service is not None:
            try:
                score_result_dict = result.model_dump()
                prompt = build_risk_narrative_prompt(
                    account_id, score_result_dict, account_context
                )
                response = await llm_service.completion(
                    messages=[
                        {"role": "system", "content": COLLECTIONS_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                )
                raw_text = _get_llm_text(response)
                parsed = json.loads(_extract_json(raw_text))
                narrative: str = parsed.get("narrative", "")
                if narrative:
                    result = result.model_copy(update={"narrative": narrative})
            except Exception as narrative_err:
                log.warning(
                    "payment_risk_narrative_failed",
                    extra={"account_id": account_id, "error": str(narrative_err)},
                )
                # Fail-open: return score result without narrative

        return result.model_dump()

    except Exception as exc:
        log.warning(
            "handle_payment_risk_assessment_failed",
            extra={"account_id": task.get("account_id", ""), "error": str(exc)},
        )
        return {"error": str(exc), "confidence": "low", "partial": True}


async def handle_generate_collection_message(
    task: dict,
    llm_service: Any,
    notion_collections: Any,
    gmail_service: Any,
    scorer: Any,
    **kwargs: Any,
) -> dict:
    """Generate a stage-appropriate collection email draft.

    Computes tone modifier from account signals, builds the stage-specific
    prompt, calls LLM, and optionally creates a Gmail draft and logs the event
    to Notion.

    Stage 5 is the human handoff stage — no automated message is generated for
    stage 5. This handler returns an error dict if stage==5.

    Args:
        task: Task dict with ``account_id``, ``stage`` (1-4), ``ar_report``,
            ``account_context``, and optional tone modifier inputs.
        llm_service: LLMService for message generation.
        notion_collections: NotionCollectionsAdapter for event logging.
            None is allowed — Notion logging is skipped.
        gmail_service: GmailService for creating email drafts.
            None is allowed — draft creation is skipped.
        scorer: Not used directly (accepted for uniform signature).
        **kwargs: Additional context (ignored).

    Returns:
        CollectionMessageStage model_dump() dict, or fail-open error dict.
    """
    try:
        account_id: str = task.get("account_id", "")
        stage: int = int(task.get("stage", 1))

        # Stage 5 is human handoff — no automated message
        if stage == 5:
            return {
                "account_id": account_id,
                "error": "Stage 5 is human handoff — no automated collection message generated",
                "stage": 5,
                "confidence": "low",
                "partial": True,
            }

        ar_report: dict = task.get("ar_report", {})
        account_context: dict = task.get("account_context", {})

        # Compute tone modifier from available signals
        days_overdue: int = int(task.get("days_overdue", ar_report.get("days_overdue", 0)))
        arr_usd: float = float(
            task.get("arr_usd", account_context.get("arr_usd", 0.0))
        )
        payment_streak: int = int(
            task.get("payment_history_streak", account_context.get("payment_history_streak", 0))
        )
        tenure_years: float = float(
            task.get("tenure_years", account_context.get("tenure_years", 0.0))
        )

        tone_modifier: float = compute_tone_modifier(
            days_overdue=days_overdue,
            arr_usd=arr_usd,
            payment_streak=payment_streak,
            tenure_years=tenure_years,
        )

        # Build prompt and call LLM
        if llm_service is None:
            return {
                "account_id": account_id,
                "error": "llm_service not configured",
                "confidence": "low",
                "partial": True,
            }

        prompt = build_collection_message_prompt(
            account_id=account_id,
            stage=stage,
            ar_report=ar_report,
            tone_modifier=tone_modifier,
            account_context=account_context,
        )

        response = await llm_service.completion(
            messages=[
                {"role": "system", "content": COLLECTIONS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        raw_text = _get_llm_text(response)
        parsed = json.loads(_extract_json(raw_text))

        subject: str = parsed.get("subject", "")
        body: str = parsed.get("body", "")
        key_refs: dict = parsed.get("key_references", {})
        references_invoice: str = key_refs.get(
            "invoice_number", ar_report.get("oldest_invoice_number", "")
        )
        references_balance: float = float(
            key_refs.get(
                "balance_usd", ar_report.get("total_outstanding_usd", 0.0)
            )
        )

        # Create Gmail draft
        draft_id: str | None = None
        if gmail_service is not None:
            try:
                from src.app.services.gsuite.models import EmailMessage

                draft_email = EmailMessage(
                    subject=subject,
                    body_html=body,
                )
                draft_result = await gmail_service.create_draft(draft_email)
                draft_id = (
                    draft_result.draft_id
                    if hasattr(draft_result, "draft_id")
                    else draft_result.get("draft_id", "")
                    if isinstance(draft_result, dict)
                    else None
                )
            except Exception as draft_err:
                log.warning(
                    "collection_message_draft_failed",
                    extra={"account_id": account_id, "error": str(draft_err)},
                )

        # Log event to Notion
        if notion_collections is not None:
            try:
                await notion_collections.log_collection_event(
                    account_id,
                    "message_generated",
                    {
                        "stage": stage,
                        "tone_modifier": tone_modifier,
                        "subject": subject,
                        "draft_id": draft_id,
                    },
                )
            except Exception as log_err:
                log.warning(
                    "collection_message_notion_log_failed",
                    extra={"account_id": account_id, "error": str(log_err)},
                )

        # Build result model
        message_stage = CollectionMessageStage(
            account_id=account_id,
            stage=stage,
            subject=subject,
            body=body,
            tone_modifier=tone_modifier,
            references_invoice=references_invoice,
            references_balance_usd=references_balance,
            gmail_draft_id=draft_id,
        )
        return message_stage.model_dump()

    except Exception as exc:
        log.warning(
            "handle_generate_collection_message_failed",
            extra={"account_id": task.get("account_id", ""), "error": str(exc)},
        )
        return {"error": str(exc), "confidence": "low", "partial": True}


async def handle_run_escalation_check(
    task: dict,
    llm_service: Any,
    notion_collections: Any,
    gmail_service: Any,
    scorer: Any,
    **kwargs: Any,
) -> dict:
    """Run deterministic escalation check and advance stage if criteria are met.

    Escalation advancement is DETERMINISTIC — not driven by LLM. LLM is used
    only to generate Stage 5 notification email content after the deterministic
    advancement decision.

    Stage advancement criteria (BOTH must be met):
    - time_floor_met: ``(now - stage_entered_at).days >= STAGE_TIME_FLOORS[current_stage]``
    - non_response: ``messages_unanswered >= 1``

    After advancing to stages 1-4, ``handle_generate_collection_message`` is
    called internally to produce a ready-to-send Gmail draft for the rep.

    After advancing to stage 5, ``build_escalation_check_prompt`` + LLM generates
    notification body for TWO drafts: rep notification and finance team summary.

    Args:
        task: Task dict with ``account_id``, optional ``escalation_state``,
            ``ar_report``, ``risk_result``, and ``finance_team_email``.
        llm_service: LLMService for stage 5 notification content generation.
        notion_collections: NotionCollectionsAdapter for escalation state I/O.
            None is allowed — state from task dict is used.
        gmail_service: GmailService for creating email drafts.
            None is allowed — draft creation is skipped.
        scorer: Not used directly (accepted for uniform signature).
        **kwargs: Additional context (ignored).

    Returns:
        CollectionsAlertResult model_dump() dict, or fail-open error dict.
    """
    try:
        account_id: str = task.get("account_id", "")
        now = datetime.now(timezone.utc)

        # -- Step 1: Fetch escalation state --
        escalation_state_dict: dict = task.get("escalation_state", {})
        if notion_collections is not None and not escalation_state_dict:
            try:
                fetched = await notion_collections.get_escalation_state(account_id)
                if fetched is not None:
                    escalation_state_dict = (
                        fetched.model_dump()
                        if hasattr(fetched, "model_dump")
                        else fetched
                        if isinstance(fetched, dict)
                        else {}
                    )
            except Exception as fetch_err:
                log.warning(
                    "escalation_state_fetch_failed",
                    extra={"account_id": account_id, "error": str(fetch_err)},
                )

        # Build EscalationState from dict (or default stage 0)
        if escalation_state_dict:
            try:
                state = EscalationState(**escalation_state_dict)
            except Exception:
                state = EscalationState(account_id=account_id)
        else:
            state = EscalationState(account_id=account_id)

        current_stage: int = state.current_stage

        # -- Step 2: Fetch AR and risk data --
        ar_report_dict: dict = task.get("ar_report", {})
        risk_result_dict: dict = task.get("risk_result", {})

        if notion_collections is not None and not ar_report_dict:
            try:
                raw_invoices = await notion_collections.get_ar_aging(account_id)
                if raw_invoices:
                    ar_report_dict = {"account_id": account_id, "raw_invoices": raw_invoices}
            except Exception:
                pass  # Fail-open: proceed without AR data

        # -- Step 3: Terminal check (stage 5) --
        if current_stage == 5:
            return CollectionsAlertResult(
                account_id=account_id,
                action_taken="already_at_stage_5_terminal",
                stage_after=5,
                draft_created=False,
                notion_updated=False,
            ).model_dump()

        # -- Step 4: Payment received reset --
        if state.payment_received_at is not None:
            reset_state = EscalationState(account_id=account_id)
            if notion_collections is not None:
                try:
                    await notion_collections.update_escalation_state(
                        account_id, reset_state
                    )
                except Exception as reset_err:
                    log.warning(
                        "escalation_reset_notion_failed",
                        extra={"account_id": account_id, "error": str(reset_err)},
                    )
            return CollectionsAlertResult(
                account_id=account_id,
                action_taken="reset_payment_received",
                stage_after=0,
                draft_created=False,
                notion_updated=notion_collections is not None,
            ).model_dump()

        # -- Step 5: Deterministic advancement check --
        time_floor_met: bool = False
        if state.stage_entered_at is not None:
            floor_days = STAGE_TIME_FLOORS.get(current_stage, 999)
            days_in_stage = (now - state.stage_entered_at).days
            time_floor_met = days_in_stage >= floor_days
        elif current_stage == 0:
            # Stage 0 has no floor — advance immediately if unanswered
            time_floor_met = True

        non_response: bool = state.messages_unanswered >= 1

        # Both conditions required for advancement
        if not (time_floor_met and non_response):
            return CollectionsAlertResult(
                account_id=account_id,
                action_taken="no_advancement_criteria_not_met",
                stage_after=current_stage,
                draft_created=False,
                notion_updated=False,
            ).model_dump()

        # -- Step 6: Advance stage --
        new_stage: int = min(current_stage + 1, 5)
        updated_state = EscalationState(
            account_id=account_id,
            current_stage=new_stage,
            stage_entered_at=now,
            messages_unanswered=0,
            stage5_notified=state.stage5_notified,
        )

        draft_created: bool = False

        # -- Step 7: Draft on advance (stages 1-4) --
        if new_stage in (1, 2, 3, 4):
            try:
                msg_task = {
                    "account_id": account_id,
                    "stage": new_stage,
                    "ar_report": ar_report_dict,
                    "account_context": task.get("account_context", {}),
                    "days_overdue": task.get("days_overdue", 0),
                    "arr_usd": task.get("arr_usd", 0.0),
                    "payment_history_streak": task.get("payment_history_streak", 0),
                    "tenure_years": task.get("tenure_years", 0.0),
                }
                msg_result = await handle_generate_collection_message(
                    msg_task,
                    llm_service,
                    notion_collections,
                    gmail_service,
                    scorer,
                )
                if "error" not in msg_result:
                    draft_created = True
                    updated_state = updated_state.model_copy(
                        update={"last_message_sent_at": now}
                    )
            except Exception as draft_err:
                # Fail-open: draft failure does NOT block stage advancement
                log.warning(
                    "escalation_draft_failed_stage_1_4",
                    extra={
                        "account_id": account_id,
                        "new_stage": new_stage,
                        "error": str(draft_err),
                    },
                )

        # -- Step 8: Stage 5 human handoff notification --
        elif new_stage == 5:
            updated_state = updated_state.model_copy(
                update={"stage5_notified": False}
            )
            try:
                if llm_service is not None:
                    prompt = build_escalation_check_prompt(
                        account_id=account_id,
                        escalation_state=escalation_state_dict,
                        ar_report=ar_report_dict,
                        risk_result=risk_result_dict,
                    )
                    response = await llm_service.completion(
                        messages=[
                            {"role": "system", "content": COLLECTIONS_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.3,
                    )
                    raw_text = _get_llm_text(response)
                    parsed = json.loads(_extract_json(raw_text))

                    subject: str = parsed.get("subject", f"Collections Escalation: {account_id}")
                    body: str = parsed.get("body", "")
                    summary_for_finance: str = parsed.get("summary_for_finance", "")

                    # Finance team email from task or kwargs
                    finance_team_email: str = (
                        task.get("finance_team_email", "")
                        or kwargs.get("finance_team_email", "")
                    )

                    # Try to get from settings if not provided
                    if not finance_team_email:
                        try:
                            from src.app.core.config import settings
                            finance_team_email = getattr(settings, "FINANCE_TEAM_EMAIL", "")
                        except Exception:
                            pass

                    if gmail_service is not None:
                        try:
                            from src.app.services.gsuite.models import EmailMessage

                            # Rep notification draft
                            rep_email = EmailMessage(
                                subject=subject,
                                body_html=body,
                            )
                            rep_draft = await gmail_service.create_draft(rep_email)
                            draft_created = True
                            log.info(
                                "stage5_rep_draft_created",
                                extra={"account_id": account_id},
                            )

                            # Finance team draft
                            if finance_team_email:
                                finance_email = EmailMessage(
                                    to=finance_team_email,
                                    subject=f"[Finance Handoff] {subject}",
                                    body_html=summary_for_finance,
                                )
                                await gmail_service.create_draft(finance_email)
                                log.info(
                                    "stage5_finance_draft_created",
                                    extra={
                                        "account_id": account_id,
                                        "to": finance_team_email,
                                    },
                                )
                            else:
                                log.warning(
                                    "stage5_finance_draft_skipped",
                                    extra={
                                        "account_id": account_id,
                                        "reason": "finance_team_email not configured",
                                    },
                                )

                        except Exception as draft_err:
                            # Fail-open: draft failure doesn't block stage advancement
                            log.warning(
                                "stage5_draft_failed",
                                extra={
                                    "account_id": account_id,
                                    "error": str(draft_err),
                                },
                            )

                    updated_state = updated_state.model_copy(
                        update={"stage5_notified": True}
                    )

            except Exception as stage5_err:
                # Fail-open: stage 5 notification failure doesn't block advancement
                log.warning(
                    "stage5_notification_failed",
                    extra={"account_id": account_id, "error": str(stage5_err)},
                )

        # -- Step 9: Persist updated escalation state --
        notion_updated: bool = False
        if notion_collections is not None:
            try:
                await notion_collections.update_escalation_state(
                    account_id, updated_state
                )
                notion_updated = True
            except Exception as update_err:
                log.warning(
                    "escalation_state_update_failed",
                    extra={"account_id": account_id, "error": str(update_err)},
                )

        return CollectionsAlertResult(
            account_id=account_id,
            action_taken=f"advanced_to_stage_{new_stage}",
            stage_after=new_stage,
            draft_created=draft_created,
            notion_updated=notion_updated,
        ).model_dump()

    except Exception as exc:
        log.warning(
            "handle_run_escalation_check_failed",
            extra={"account_id": task.get("account_id", ""), "error": str(exc)},
        )
        return {"error": str(exc), "confidence": "low", "partial": True}


async def handle_surface_payment_plan(
    task: dict,
    llm_service: Any,
    notion_collections: Any,
    gmail_service: Any,
    scorer: Any,
    **kwargs: Any,
) -> dict:
    """Generate structured payment plan options and surface to rep.

    Produces three payment plan options (installment_schedule, partial_payment,
    pay_or_suspend), optionally writes them to a Notion page, and creates a
    Gmail draft summarizing the options for rep review.

    Args:
        task: Task dict with ``account_id``, ``ar_report``, and
            ``account_context``.
        llm_service: LLMService for plan generation.
        notion_collections: NotionCollectionsAdapter for plan persistence.
            None is allowed — Notion write is skipped.
        gmail_service: GmailService for rep review draft.
            None is allowed — draft creation is skipped.
        scorer: Not used by this handler (accepted for uniform signature).
        **kwargs: Additional context (ignored).

    Returns:
        PaymentPlanOptions model_dump() dict, or fail-open error dict.
    """
    try:
        account_id: str = task.get("account_id", "")
        ar_report: dict = task.get("ar_report", {})
        account_context: dict = task.get("account_context", {})

        # LLM required for plan generation
        if llm_service is None:
            return {
                "account_id": account_id,
                "error": "llm_service not configured",
                "confidence": "low",
                "partial": True,
            }

        prompt = build_payment_plan_prompt(
            account_id=account_id,
            ar_report=ar_report,
            account_context=account_context,
        )
        response = await llm_service.completion(
            messages=[
                {"role": "system", "content": COLLECTIONS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        raw_text = _get_llm_text(response)
        parsed = json.loads(_extract_json(raw_text))

        # Build PaymentPlanOptions
        try:
            options = PaymentPlanOptions(
                account_id=account_id,
                total_outstanding_usd=float(
                    parsed.get("total_outstanding_usd", ar_report.get("total_outstanding_usd", 0.0))
                ),
                options=parsed.get("options", []),
                llm_rationale=parsed.get("llm_rationale", ""),
            )
        except Exception as model_err:
            # Partial result if model validation fails
            log.warning(
                "payment_plan_model_failed",
                extra={"account_id": account_id, "error": str(model_err)},
            )
            parsed["account_id"] = account_id
            return parsed

        # Persist to Notion
        notion_page_id: str | None = None
        if notion_collections is not None:
            try:
                notion_page_id = await notion_collections.create_payment_plan_page(
                    account_id, options.model_dump()
                )
                options = options.model_copy(update={"notion_page_id": notion_page_id})
            except Exception as notion_err:
                log.warning(
                    "payment_plan_notion_failed",
                    extra={"account_id": account_id, "error": str(notion_err)},
                )

        # Create Gmail draft for rep review
        draft_id: str | None = None
        if gmail_service is not None:
            try:
                from src.app.services.gsuite.models import EmailMessage

                options_summary = "\n".join(
                    f"- {opt.get('option_type', 'Option')}: {opt.get('description', '')[:120]}"
                    for opt in (parsed.get("options") or [])
                )
                total = options.total_outstanding_usd
                subject = (
                    f"Payment Plan Options: {account_id} "
                    f"(${total:,.2f} outstanding)"
                )
                body_html = (
                    f"<p>Payment plan options for <strong>{account_id}</strong> "
                    f"with <strong>${total:,.2f}</strong> outstanding:</p>"
                    f"<pre>{options_summary}</pre>"
                    f"<p><em>Rationale: {options.llm_rationale[:300]}</em></p>"
                    "<p>Review and present the most appropriate option to the "
                    "customer in your next outreach.</p>"
                )

                draft_email = EmailMessage(
                    subject=subject,
                    body_html=body_html,
                )
                draft_result = await gmail_service.create_draft(draft_email)
                draft_id = (
                    draft_result.draft_id
                    if hasattr(draft_result, "draft_id")
                    else draft_result.get("draft_id", "")
                    if isinstance(draft_result, dict)
                    else None
                )
                options = options.model_copy(update={"gmail_draft_id": draft_id})
            except Exception as draft_err:
                log.warning(
                    "payment_plan_draft_failed",
                    extra={"account_id": account_id, "error": str(draft_err)},
                )

        return options.model_dump()

    except Exception as exc:
        log.warning(
            "handle_surface_payment_plan_failed",
            extra={"account_id": task.get("account_id", ""), "error": str(exc)},
        )
        return {"error": str(exc), "confidence": "low", "partial": True}
