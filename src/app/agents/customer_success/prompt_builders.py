"""Prompt templates for the Customer Success Manager agent.

Provides the CSM system prompt and five prompt builder functions -- one per
CSM capability. Each builder embeds a JSON schema directly in the user
message so the LLM returns parseable, schema-compliant JSON.

CSM capabilities:
    1. Health score computation -- composite score from 13 health signals
    2. Churn narrative generation -- risk assessment with human-readable narrative
    3. QBR content generation -- quarterly business review materials
    4. Expansion opportunity detection -- upsell/cross-sell signal analysis
    5. Feature adoption analysis -- adoption rate and recommendations

All builders return ``str``. The CSM agent passes these prompts to
``LLMService.completion()`` alongside ``CSM_SYSTEM_PROMPT``.

Exports:
    CSM_SYSTEM_PROMPT: Base system prompt establishing CSM persona.
    build_health_score_prompt: Prompt for health score computation.
    build_churn_narrative_prompt: Prompt for churn risk narrative generation.
    build_qbr_prompt: Prompt for QBR content generation.
    build_expansion_prompt: Prompt for expansion opportunity detection.
    build_feature_adoption_prompt: Prompt for feature adoption analysis.
"""

from __future__ import annotations

import json

from src.app.agents.customer_success.schemas import (
    CSMHealthScore,
    ChurnRiskResult,
    ExpansionOpportunity,
    FeatureAdoptionReport,
    QBRContent,
)


# -- System Prompt ------------------------------------------------------------


CSM_SYSTEM_PROMPT: str = """\
You are a Customer Success Manager agent specializing in account health \
monitoring, churn prevention, expansion identification, and QBR preparation. \
You analyze health signals across usage, engagement, support, and financial \
dimensions to produce actionable insights. Your outputs drive proactive \
customer retention and growth strategies. Always return valid JSON matching \
the provided schema. Be data-driven and precise -- support every assessment \
with specific signal evidence.\
"""


# -- Output Schemas (embedded in prompts for LLM structured output) -----------


_HEALTH_SCORE_SCHEMA: dict = CSMHealthScore.model_json_schema()

_CHURN_NARRATIVE_SCHEMA: dict = ChurnRiskResult.model_json_schema()

_QBR_SCHEMA: dict = QBRContent.model_json_schema()

_EXPANSION_SCHEMA: dict = ExpansionOpportunity.model_json_schema()

_FEATURE_ADOPTION_SCHEMA: dict = FeatureAdoptionReport.model_json_schema()


# -- Prompt Builders ----------------------------------------------------------


def build_health_score_prompt(signals: dict, account_data: dict) -> str:
    """Build a prompt for computing a composite health score from signals.

    Takes raw health signal data and account context, then instructs the LLM
    to produce a scored health assessment with RAG status and churn risk level.

    Args:
        signals: Dict of health signal values (maps to CSMHealthSignals fields).
        account_data: Account context dict with account_id, name, contract info,
            and any additional metadata.

    Returns:
        Prompt string with embedded JSON schema and health scoring instructions.
    """
    schema = json.dumps(_HEALTH_SCORE_SCHEMA, indent=2)
    signals_json = json.dumps(signals, indent=2, default=str)
    account_json = json.dumps(account_data, indent=2, default=str)

    return (
        "**Task:** Compute a composite health score for this account based on "
        "the provided health signals. Assess churn risk and determine RAG "
        "status.\n\n"
        f"**Health signals:**\n{signals_json}\n\n"
        f"**Account context:**\n{account_json}\n\n"
        "**Instructions:**\n"
        "1. Analyze all 13 health signal dimensions holistically.\n"
        "2. Compute a score from 0 to 100 (higher = healthier) based on "
        "weighted signal contributions.\n"
        "3. Assign RAG status: GREEN (70-100), AMBER (40-69), RED (0-39).\n"
        "4. Assess churn_risk_level: low, medium, high, or critical.\n"
        "5. Determine churn_triggered_by: contract_proximity (renewal within "
        "90 days + declining signals), behavioral (usage/engagement decline), "
        "both, or null if low risk.\n"
        "6. Provide signal_breakdown as a dict mapping each signal name to its "
        "contribution weight (0.0 to 1.0, summing to ~1.0).\n"
        "7. Be precise and evidence-based -- cite specific signal values in "
        "your assessment.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_churn_narrative_prompt(
    health_score: dict, account_data: dict
) -> str:
    """Build a prompt for generating a churn risk narrative.

    Takes a computed health score and account context, then instructs the LLM
    to produce a human-readable narrative explaining the churn risk factors
    and recommended retention actions.

    Args:
        health_score: Serialized CSMHealthScore dict with score, rag, and
            signal_breakdown.
        account_data: Account context dict with contract details, stakeholder
            info, and interaction history.

    Returns:
        Prompt string with embedded JSON schema and churn narrative
        instructions.
    """
    schema = json.dumps(_CHURN_NARRATIVE_SCHEMA, indent=2)
    health_json = json.dumps(health_score, indent=2, default=str)
    account_json = json.dumps(account_data, indent=2, default=str)

    return (
        "**Task:** Generate a churn risk narrative for this account. Explain "
        "the risk factors in human-readable language and recommend retention "
        "actions.\n\n"
        f"**Health score assessment:**\n{health_json}\n\n"
        f"**Account context:**\n{account_json}\n\n"
        "**Instructions:**\n"
        "1. Analyze the health score, RAG status, and signal breakdown.\n"
        "2. Identify the primary churn risk drivers (contract proximity, "
        "behavioral signals, or both).\n"
        "3. Write a clear, actionable churn_narrative that a CSM or account "
        "rep can use to understand the situation and take action.\n"
        "4. Include specific data points from the signals to support the "
        "assessment.\n"
        "5. Recommend concrete retention steps appropriate to the risk level.\n"
        "6. If days_to_renewal is known, factor contract timing into the "
        "urgency assessment.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_qbr_prompt(
    account_data: dict, health_history: dict, period: str
) -> str:
    """Build a prompt for generating QBR (Quarterly Business Review) content.

    Takes account data, historical health trends, and the review period to
    produce structured QBR materials including health summary, ROI metrics,
    feature adoption scorecard, and expansion recommendations.

    Args:
        account_data: Account context dict with contract details, usage data,
            stakeholder info, and product configuration.
        health_history: Dict of historical health data including score trends,
            RAG status changes, and signal evolution over the period.
        period: Review period label (e.g., "Q1 2026").

    Returns:
        Prompt string with embedded JSON schema and QBR generation
        instructions.
    """
    schema = json.dumps(_QBR_SCHEMA, indent=2)
    account_json = json.dumps(account_data, indent=2, default=str)
    history_json = json.dumps(health_history, indent=2, default=str)

    return (
        "**Task:** Generate Quarterly Business Review (QBR) content for this "
        f"account covering the period: {period}.\n\n"
        f"**Account context:**\n{account_json}\n\n"
        f"**Health history for period:**\n{history_json}\n\n"
        "**Instructions:**\n"
        "1. Write a health_summary covering health trends over the period -- "
        "improvements, concerns, and overall trajectory.\n"
        "2. Compile roi_metrics as a dict of measurable outcomes "
        "(e.g., time_saved_hours, tickets_resolved, adoption_increase).\n"
        "3. Build feature_adoption_scorecard as a dict mapping each feature "
        "to its adoption status and usage percentage.\n"
        "4. List expansion_next_steps as ordered recommendations for growing "
        "the account (new modules, seat expansion, integration additions).\n"
        "5. Structure content for executive presentation -- clear, concise, "
        "and data-backed.\n"
        "6. Match the set period and account_id from the account context.\n"
        "7. Set trigger to 'quarterly' unless contract renewal is within "
        "90 days (then 'contract_proximity').\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_expansion_prompt(
    account_data: dict, usage_signals: dict
) -> str:
    """Build a prompt for detecting expansion opportunities.

    Takes account data and usage signals to identify upsell and cross-sell
    opportunities based on seat utilization, feature adoption patterns, and
    integration potential.

    Args:
        account_data: Account context dict with contract details, current
            product configuration, and seat allocations.
        usage_signals: Dict of usage data including seat utilization rate,
            feature usage patterns, API call volumes, and integration activity.

    Returns:
        Prompt string with embedded JSON schema and expansion detection
        instructions.
    """
    schema = json.dumps(_EXPANSION_SCHEMA, indent=2)
    account_json = json.dumps(account_data, indent=2, default=str)
    usage_json = json.dumps(usage_signals, indent=2, default=str)

    return (
        "**Task:** Analyze this account's usage patterns and identify "
        "expansion opportunities (seat expansion, new modules, or additional "
        "integrations).\n\n"
        f"**Account context:**\n{account_json}\n\n"
        f"**Usage signals:**\n{usage_json}\n\n"
        "**Instructions:**\n"
        "1. Analyze seat utilization -- if above 80%, recommend seat "
        "expansion.\n"
        "2. Identify modules or features not yet adopted that align with the "
        "account's use patterns.\n"
        "3. Look for integration opportunities based on the account's tech "
        "stack and current integrations.\n"
        "4. For each opportunity, provide specific evidence from the usage "
        "signals.\n"
        "5. Estimate ARR impact if data is sufficient (otherwise set to "
        "null).\n"
        "6. Write a recommended_talk_track that the account rep can use in "
        "their next conversation.\n"
        "7. Set confidence based on signal strength: high (strong data "
        "support), medium (moderate signals), low (early indicators).\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_feature_adoption_prompt(
    account_data: dict, feature_usage: dict
) -> str:
    """Build a prompt for analyzing feature adoption and generating a report.

    Takes account data and per-feature usage metrics to produce an adoption
    report with underutilized feature identification and improvement
    recommendations.

    Args:
        account_data: Account context dict with product configuration,
            stakeholder info, and training history.
        feature_usage: Dict mapping feature names to usage metrics
            (e.g., {"feature_x": {"active": True, "usage_pct": 0.65}}).

    Returns:
        Prompt string with embedded JSON schema and feature adoption analysis
        instructions.
    """
    schema = json.dumps(_FEATURE_ADOPTION_SCHEMA, indent=2)
    account_json = json.dumps(account_data, indent=2, default=str)
    usage_json = json.dumps(feature_usage, indent=2, default=str)

    return (
        "**Task:** Analyze feature adoption for this account and produce an "
        "adoption report with recommendations for improving utilization.\n\n"
        f"**Account context:**\n{account_json}\n\n"
        f"**Feature usage data:**\n{usage_json}\n\n"
        "**Instructions:**\n"
        "1. List all features_used (features with active usage).\n"
        "2. Calculate the overall adoption_rate as the fraction of available "
        "features actively used (0.0 to 1.0).\n"
        "3. Identify underutilized_features -- features available but with "
        "low or no usage.\n"
        "4. For each underutilized feature, generate a specific recommendation "
        "for improving adoption (training, configuration change, use case "
        "demo).\n"
        "5. If benchmark data is available, include benchmark_comparison as a "
        "dict mapping feature names to percentile scores. Otherwise set to "
        "null.\n"
        "6. Prioritize recommendations by potential impact on the account's "
        "success metrics.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


__all__ = [
    "CSM_SYSTEM_PROMPT",
    "build_health_score_prompt",
    "build_churn_narrative_prompt",
    "build_qbr_prompt",
    "build_expansion_prompt",
    "build_feature_adoption_prompt",
]
