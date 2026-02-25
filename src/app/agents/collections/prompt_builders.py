"""Prompt templates for the Collections Agent.

Provides the Collections system prompt and five prompt builder functions --
one per Collections capability. Each builder embeds a JSON schema directly in
the user message so the LLM returns parseable, schema-compliant JSON.

Collections capabilities:
    1. AR aging report -- analyze invoices, compute aging buckets
    2. Risk narrative -- enrich deterministic score with human-readable context
    3. Collection message -- stage-appropriate email drafts (stages 1-4 only)
    4. Escalation check notification -- Stage 5 human-handoff email body
    5. Payment plan -- three structured payment plan options

All builders return ``str``. The Collections agent passes these prompts to
``LLMService.completion()`` alongside ``COLLECTIONS_SYSTEM_PROMPT``.

NOTE: The escalation stage advancement decision is DETERMINISTIC (not LLM).
``build_escalation_check_prompt`` generates Stage 5 notification EMAIL CONTENT
only -- it is never used for stage advancement logic.

Exports:
    COLLECTIONS_SYSTEM_PROMPT: Base system prompt establishing Collections persona.
    build_ar_report_prompt: Prompt for AR aging bucket computation.
    build_risk_narrative_prompt: Prompt for risk narrative enrichment.
    build_collection_message_prompt: Prompt for stage-appropriate collection email.
    build_escalation_check_prompt: Prompt for Stage 5 human-handoff notification body.
    build_payment_plan_prompt: Prompt for structured payment plan options.
"""

from __future__ import annotations

import json

from src.app.agents.collections.schemas import (
    ARAgingReport,
    CollectionMessageStage,
    PaymentPlanOptions,
    PaymentRiskResult,
)


# -- System Prompt ------------------------------------------------------------


COLLECTIONS_SYSTEM_PROMPT: str = """\
You are a collections specialist for an enterprise SaaS company. Your role \
is to help recover outstanding payments while preserving customer \
relationships. You analyze AR aging, predict payment risk, generate \
appropriately calibrated collection messages, evaluate escalation readiness, \
and structure payment plan options. All communications are DRAFT ONLY — you \
never send emails autonomously. Human reps review and approve all outreach \
before sending.\
"""


# -- Output Schemas (embedded in prompts for LLM structured output) -----------


_AR_REPORT_SCHEMA: dict = ARAgingReport.model_json_schema()

_PAYMENT_RISK_SCHEMA: dict = PaymentRiskResult.model_json_schema()

_COLLECTION_MESSAGE_SCHEMA: dict = CollectionMessageStage.model_json_schema()

_PAYMENT_PLAN_SCHEMA: dict = PaymentPlanOptions.model_json_schema()

# Inline schema for escalation check — not a Pydantic model, plain dict shape
_ESCALATION_CHECK_SCHEMA: dict = {
    "subject": "str — subject line for the Stage 5 human-handoff notification email",
    "body": "str — full email body for the rep explaining why the account reached human handoff",
    "summary_for_finance": "str — concise finance-team summary of the AR situation and recommended action",
    "key_facts": ["str — one key fact per entry, e.g. '90+ days overdue: $12,500'"],
}

# Inline schema for risk narrative — plain dict shape
_RISK_NARRATIVE_SCHEMA: dict = {
    "narrative": "str — 2-3 sentence human-readable risk narrative for the rep",
    "key_risk_factors": ["str — one primary risk driver per entry"],
    "recommended_action": "str — single recommended next action for the rep",
}


# -- Prompt Builders ----------------------------------------------------------


def build_ar_report_prompt(account_id: str, raw_invoices: list[dict]) -> str:
    """Build a prompt for computing AR aging buckets from raw invoice data.

    Instructs the LLM to analyze all invoices, group them into the four
    standard aging buckets (0-30, 31-60, 61-90, 90+), compute bucket totals,
    and identify the oldest outstanding invoice.

    Args:
        account_id: Account identifier for the AR aging report.
        raw_invoices: List of raw invoice dicts with at least ``invoice_number``,
            ``amount_usd``, ``due_date``, and ``status`` fields.

    Returns:
        Prompt string with embedded ARAgingReport JSON schema and analysis
        instructions.
    """
    schema = json.dumps(_AR_REPORT_SCHEMA, indent=2)
    invoices_json = json.dumps(raw_invoices, indent=2, default=str)

    return (
        f"**Task:** Compute an AR aging report for account ``{account_id}`` "
        "from the provided raw invoice data.\n\n"
        f"**Raw invoices:**\n{invoices_json}\n\n"
        "**Instructions:**\n"
        "1. Filter to only UNPAID or OVERDUE invoices.\n"
        "2. Group invoices into four aging buckets based on days past due:\n"
        "   - 0-30 days overdue\n"
        "   - 31-60 days overdue\n"
        "   - 61-90 days overdue\n"
        "   - 90+ days overdue\n"
        "3. For each bucket: count invoices, sum total_amount_usd, and "
        "identify the oldest_invoice_date and oldest_invoice_number.\n"
        "4. Sum all buckets for total_outstanding_usd.\n"
        "5. Identify the single oldest unpaid invoice across ALL buckets "
        "(oldest_invoice_number, oldest_invoice_amount_usd, oldest_invoice_date).\n"
        "6. Set account_id to the provided account ID.\n"
        "7. Set account_name from invoice data if available, else use the "
        "account_id.\n"
        "8. Use today's UTC date for computed_at.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_risk_narrative_prompt(
    account_id: str, score_result: dict, account_context: dict
) -> str:
    """Build a prompt for generating a human-readable payment risk narrative.

    Takes a deterministic score result and account context, then instructs the
    LLM to produce a 2-3 sentence narrative explaining what is driving the risk
    score and what the rep should do next.

    Args:
        account_id: Account identifier.
        score_result: Serialized PaymentRiskResult dict with score, rag, and
            score_breakdown.
        account_context: Additional account metadata (name, ARR, tenure, etc.).

    Returns:
        Prompt string with embedded risk narrative JSON schema and enrichment
        instructions.
    """
    schema = json.dumps(_RISK_NARRATIVE_SCHEMA, indent=2)
    score_json = json.dumps(score_result, indent=2, default=str)
    context_json = json.dumps(account_context, indent=2, default=str)

    return (
        f"**Task:** Generate a human-readable payment risk narrative for "
        f"account ``{account_id}``.\n\n"
        f"**Risk score result:**\n{score_json}\n\n"
        f"**Account context:**\n{context_json}\n\n"
        "**Instructions:**\n"
        "1. Write a 2-3 sentence ``narrative`` explaining what is driving the "
        "risk score in plain English that a sales rep can read and understand "
        "immediately.\n"
        "2. Identify the 2-3 most significant ``key_risk_factors`` from the "
        "score_breakdown (e.g., 'Invoice 90+ days overdue', "
        "'Chronic late payment streak', 'Renewal in 7 days').\n"
        "3. Provide a single ``recommended_action`` — the most important step "
        "the rep should take right now (e.g., 'Schedule urgent call to "
        "discuss payment arrangement').\n"
        "4. Be specific — reference actual values from the score and context "
        "(days overdue, amounts, RAG status).\n"
        "5. Keep tone professional and solution-oriented.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_collection_message_prompt(
    account_id: str,
    stage: int,
    ar_report: dict,
    tone_modifier: float,
    account_context: dict,
) -> str:
    """Build a prompt for generating a stage-appropriate collection email.

    Maps escalation stages 1-4 to distinct communication personas. Stage 5
    is human handoff and does NOT use this builder. The tone_modifier float
    calibrates firmness (< 1.0 = softer for high-value accounts, > 1.0 =
    firmer for chronic late payers). Every message MUST reference the oldest
    outstanding invoice and total balance.

    Args:
        account_id: Account identifier.
        stage: Escalation stage (1-4 only; stage 5 is human handoff).
        ar_report: AR aging report dict with oldest_invoice_number and
            total_outstanding_usd.
        tone_modifier: Float in [0.6, 1.4]; 1.0=baseline, <1.0=softer,
            >1.0=more urgent.
        account_context: Additional account metadata (name, ARR, tenure, etc.).

    Returns:
        Prompt string with embedded collection message JSON schema and
        stage-specific generation instructions.
    """
    schema = json.dumps(_COLLECTION_MESSAGE_SCHEMA, indent=2)
    ar_json = json.dumps(ar_report, indent=2, default=str)
    context_json = json.dumps(account_context, indent=2, default=str)

    stage_personas = {
        1: (
            "Stage 1 — Friendly Nudge: Assume this is an oversight or "
            "administrative error. Tone is warm, relationship-preserving, "
            "and helpful. No mention of consequences. Goal: prompt payment "
            "with minimal friction."
        ),
        2: (
            "Stage 2 — Soft Reminder: Polite urgency. Acknowledge that "
            "previous communication may not have been received. Reference "
            "invoice specifics. Gently request immediate attention. "
            "Relationship still primary."
        ),
        3: (
            "Stage 3 — Firm Notice: Professional and direct. Clearly state "
            "that the account is past due and consequences (service impact, "
            "credit hold) are approaching. Request payment by a specific "
            "deadline. Tone shifts from relationship-preserving to "
            "consequence-aware."
        ),
        4: (
            "Stage 4 — Final Warning: Explicit escalation timeline. This is "
            "the last automated outreach before human intervention. State "
            "clearly that failure to respond will result in account escalation "
            "to a collections team. Final chance to resolve without senior "
            "involvement."
        ),
    }

    persona = stage_personas.get(
        stage,
        f"Stage {stage}: Standard collection communication.",
    )

    tone_guidance = (
        "softer and more relationship-preserving than baseline"
        if tone_modifier < 1.0
        else (
            "firmer and more urgent than baseline"
            if tone_modifier > 1.0
            else "at baseline firmness"
        )
    )

    oldest_invoice = ar_report.get("oldest_invoice_number", "N/A")
    total_outstanding = ar_report.get("total_outstanding_usd", 0.0)

    return (
        f"**Task:** Generate a Stage {stage} collection email for account "
        f"``{account_id}``.\n\n"
        f"**Stage persona:** {persona}\n\n"
        f"**Tone modifier:** {tone_modifier:.2f} (message should be {tone_guidance})\n\n"
        f"**AR aging report:**\n{ar_json}\n\n"
        f"**Account context:**\n{context_json}\n\n"
        "**Instructions:**\n"
        f"1. Write a ``subject`` line appropriate for Stage {stage}.\n"
        "2. Write a ``body`` following the stage persona and tone modifier. "
        "The message MUST explicitly reference:\n"
        f"   - Invoice number: ``{oldest_invoice}``\n"
        f"   - Outstanding balance: ``${total_outstanding:,.2f}`` USD\n"
        "3. In ``key_references``, set ``invoice_number`` to the oldest "
        "outstanding invoice number and ``balance_usd`` to the total "
        "outstanding balance.\n"
        "4. Set ``account_id`` and ``stage`` from the provided values.\n"
        "5. Set ``tone_modifier`` to the provided float.\n"
        "6. Set ``references_invoice`` and ``references_balance_usd`` from "
        "the AR report values.\n"
        "7. Leave ``gmail_draft_id`` as null (handled by the handler).\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_escalation_check_prompt(
    account_id: str,
    escalation_state: dict,
    ar_report: dict,
    risk_result: dict,
) -> str:
    """Build a prompt for generating Stage 5 human-handoff notification content.

    This builder is used EXCLUSIVELY to generate the email body content for
    the Stage 5 notification drafts (rep draft and finance team draft). It
    does NOT drive stage advancement decisions — those are deterministic and
    handled entirely by the handler logic before this builder is called.

    The prompt instructs the LLM to produce a clear, professional summary
    explaining why the account has reached human handoff, the AR history,
    and recommended next steps for both the rep and the finance team.

    Args:
        account_id: Account identifier.
        escalation_state: Current escalation state dict (current_stage,
            stage_entered_at, messages_unanswered, etc.).
        ar_report: AR aging report dict with outstanding balance and bucket
            breakdown.
        risk_result: Payment risk result dict with score, rag, and narrative.

    Returns:
        Prompt string with embedded escalation check JSON schema for generating
        Stage 5 notification email content.
    """
    schema = json.dumps(_ESCALATION_CHECK_SCHEMA, indent=2)
    state_json = json.dumps(escalation_state, indent=2, default=str)
    ar_json = json.dumps(ar_report, indent=2, default=str)
    risk_json = json.dumps(risk_result, indent=2, default=str)

    return (
        f"**Task:** Generate Stage 5 human-handoff notification email content "
        f"for account ``{account_id}``.\n\n"
        "**Context:** This account has reached Stage 5 (human handoff) after "
        "exhausting automated collection stages 1-4 without resolution. A "
        "human rep must now take over. Two email drafts are needed:\n"
        "1. A rep notification explaining the situation and recommended actions\n"
        "2. A finance team summary for internal escalation tracking\n\n"
        f"**Escalation state:**\n{state_json}\n\n"
        f"**AR aging report:**\n{ar_json}\n\n"
        f"**Payment risk assessment:**\n{risk_json}\n\n"
        "**Instructions:**\n"
        "1. Write a ``subject`` line for the rep notification (e.g., "
        "'[Collections Escalation] Account {account_id} — Human Handoff "
        "Required').\n"
        "2. Write a ``body`` for the rep: explain the escalation history "
        "(stages attempted, messages unanswered), the AR position (total "
        "outstanding, oldest invoice), the risk assessment, and clear "
        "recommended next steps for the rep to take.\n"
        "3. Write a ``summary_for_finance`` — a concise 3-5 sentence internal "
        "summary suitable for finance team records: AR balance, escalation "
        "timeline, risk score, and recommended action (e.g., legal review, "
        "credit hold, payment plan negotiation).\n"
        "4. List 3-5 ``key_facts`` as short bullet statements (e.g., "
        "'Total outstanding: $12,500', '4 collection messages unanswered', "
        "'Risk score: 85/100 CRITICAL', 'Oldest invoice: 95 days overdue').\n"
        "5. Be factual, professional, and solution-oriented. This content will "
        "be reviewed by humans before any action is taken.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_payment_plan_prompt(
    account_id: str, ar_report: dict, account_context: dict
) -> str:
    """Build a prompt for generating structured payment plan options.

    Instructs the LLM to propose three realistic payment plan options
    (installment schedule, partial payment, and pay-or-suspend) based on
    the account's AR position, ARR, and relationship tenure. Each option
    must include proposed amounts, dates, and rationale.

    Args:
        account_id: Account identifier.
        ar_report: AR aging report dict with total_outstanding_usd and
            bucket breakdown.
        account_context: Additional account metadata including ARR,
            tenure_years, and relationship details.

    Returns:
        Prompt string with embedded PaymentPlanOptions JSON schema and
        payment plan generation instructions.
    """
    schema = json.dumps(_PAYMENT_PLAN_SCHEMA, indent=2)
    ar_json = json.dumps(ar_report, indent=2, default=str)
    context_json = json.dumps(account_context, indent=2, default=str)

    arr_usd = account_context.get("arr_usd", 0.0)
    tenure_years = account_context.get("tenure_years", 0.0)
    total_outstanding = ar_report.get("total_outstanding_usd", 0.0)

    return (
        f"**Task:** Generate three payment plan options for account "
        f"``{account_id}`` with ${total_outstanding:,.2f} USD outstanding.\n\n"
        f"**AR aging report:**\n{ar_json}\n\n"
        f"**Account context:**\n{context_json}\n\n"
        f"**Account metrics:** ARR = ${arr_usd:,.2f}, "
        f"Tenure = {tenure_years:.1f} years\n\n"
        "**Instructions:**\n"
        "1. Propose exactly 3 options covering these types:\n"
        "   - ``installment_schedule``: Split the outstanding balance into "
        "2-4 equal payments over 30-90 days. Propose realistic dates.\n"
        "   - ``partial_payment``: Immediate partial payment (40-60% now) "
        "with the remainder due in 30 days. This shows good faith.\n"
        "   - ``pay_or_suspend``: Full payment by a firm deadline, otherwise "
        "service suspension. Use for high-risk accounts.\n"
        "2. For each option: write a ``description`` explaining the terms, "
        "list ``proposed_amounts`` (ordered payment amounts in USD), list "
        "``proposed_dates`` (ISO date strings, starting from today), and "
        "set ``total_usd`` to the sum of proposed_amounts.\n"
        "3. Set ``total_outstanding_usd`` to the total outstanding balance.\n"
        "4. Write an ``llm_rationale`` (2-3 sentences) explaining why these "
        "three options were structured this way given the account's ARR, "
        "tenure, and risk profile.\n"
        "5. Set ``account_id`` from the provided value.\n"
        "6. Leave ``notion_page_id`` and ``gmail_draft_id`` as null.\n"
        "7. Base installment amounts on the actual outstanding balance — be "
        "mathematically precise (proposed_amounts must sum to total_usd).\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


__all__ = [
    "COLLECTIONS_SYSTEM_PROMPT",
    "build_ar_report_prompt",
    "build_risk_narrative_prompt",
    "build_collection_message_prompt",
    "build_escalation_check_prompt",
    "build_payment_plan_prompt",
]
