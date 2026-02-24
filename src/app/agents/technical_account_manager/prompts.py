"""Prompt templates for the Technical Account Manager agent.

Provides the TAM system prompt and five prompt builder functions -- one per
communication type. Each builder embeds a JSON schema directly in the user
message so the LLM returns parseable, schema-compliant JSON.

Communication types:
    1. Escalation outreach -- triggered by health score deterioration
    2. Tailored release notes -- relevant features for the account
    3. Technical roadmap preview -- QBR/strategic call preparation
    4. Periodic health check-in -- scheduled health status communication
    5. Customer Success Review -- comprehensive health/integration summary

All builders return ``str``. The TAM agent passes these prompts to
``LLMService.completion()`` alongside ``TAM_SYSTEM_PROMPT``.

Exports:
    TAM_SYSTEM_PROMPT: Base system prompt establishing TAM persona.
    build_escalation_outreach_prompt: Prompt for escalation outreach drafts.
    build_release_notes_prompt: Prompt for tailored release notes.
    build_roadmap_preview_prompt: Prompt for roadmap preview communications.
    build_health_checkin_prompt: Prompt for periodic health check-ins.
    build_customer_success_review_prompt: Prompt for Customer Success Reviews.
"""

from __future__ import annotations

import json


# ── System Prompt ──────────────────────────────────────────────────────────


TAM_SYSTEM_PROMPT: str = """\
You are a Technical Account Manager agent specializing in customer technical \
health monitoring and relationship management. You generate empathetic, \
technically accurate communications tailored to each account's specific \
context -- their integrations, stakeholder maturity levels, known environment, \
and communication history. Always return valid JSON matching the provided \
schema. Be proactive and customer-focused -- anticipate issues before they \
escalate.\
"""


# ── Output Schemas ─────────────────────────────────────────────────────────

# JSON schemas embedded in prompts so the LLM returns parseable structured
# output. Defined as plain dicts rather than Pydantic models because these
# are LLM output shapes, not internal domain models.

_ESCALATION_OUTREACH_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Email subject line"},
        "body_html": {"type": "string", "description": "Email body in HTML format"},
        "tone": {
            "type": "string",
            "description": "Communication tone (e.g., empathetic, urgent, reassuring)",
        },
        "key_issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of key issues being addressed",
        },
    },
    "required": ["subject", "body_html", "tone", "key_issues"],
}

_RELEASE_NOTES_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Email subject line"},
        "body_html": {"type": "string", "description": "Email body in HTML format"},
        "highlighted_features": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Features relevant to this account",
        },
        "relevance_notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Why each feature matters to this account",
        },
    },
    "required": ["subject", "body_html", "highlighted_features", "relevance_notes"],
}

_ROADMAP_PREVIEW_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Email subject line"},
        "body_html": {"type": "string", "description": "Email body in HTML format"},
        "aligned_items": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Roadmap items aligned with this account's needs",
        },
        "co_dev_opportunities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Co-development opportunities identified",
        },
    },
    "required": ["subject", "body_html", "aligned_items", "co_dev_opportunities"],
}

_HEALTH_CHECKIN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Email subject line"},
        "body_html": {"type": "string", "description": "Email body in HTML format"},
        "health_summary": {
            "type": "string",
            "description": "Brief summary of the account's current health status",
        },
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Actionable recommendations for the account",
        },
    },
    "required": ["subject", "body_html", "health_summary", "recommendations"],
}

_CUSTOMER_SUCCESS_REVIEW_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Email subject line"},
        "body_html": {"type": "string", "description": "Email body in HTML format"},
        "health_overview": {
            "type": "string",
            "description": "Overview of technical health status and trends",
        },
        "integration_summary": {
            "type": "string",
            "description": "Summary of active integrations and their status",
        },
        "open_items": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Open support tickets and outstanding issues",
        },
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Strategic recommendations for the account",
        },
    },
    "required": [
        "subject",
        "body_html",
        "health_overview",
        "integration_summary",
        "open_items",
        "recommendations",
    ],
}


# ── Prompt Builders ────────────────────────────────────────────────────────


def build_escalation_outreach_prompt(
    health_score: dict,
    relationship_profile: dict,
    tickets: list[dict],
) -> str:
    """Build a prompt for generating an escalation outreach draft.

    Creates a communication draft for rep review when a health score drop
    or RAG status change triggers escalation. Personalizes with stakeholder
    names, technical maturity, known integrations, and specific ticket issues.

    NOTE: The output is always a DRAFT for rep review. TAM never sends
    email autonomously.

    Args:
        health_score: Serialized HealthScoreResult dict with score, rag_status,
            previous_score, previous_rag.
        relationship_profile: Serialized RelationshipProfile dict with
            stakeholders, integrations, communication_history.
        tickets: List of serialized TicketSummary dicts for open tickets.

    Returns:
        Prompt string with embedded JSON schema and escalation outreach
        instructions.
    """
    schema = json.dumps(_ESCALATION_OUTREACH_SCHEMA, indent=2)
    health_json = json.dumps(health_score, indent=2, default=str)
    profile_json = json.dumps(relationship_profile, indent=2, default=str)
    tickets_json = json.dumps(tickets, indent=2, default=str)

    return (
        "**Task:** Generate an escalation outreach email DRAFT for rep review. "
        "This account's health has deteriorated and needs proactive engagement.\n\n"
        f"**Health score:**\n{health_json}\n\n"
        f"**Relationship profile:**\n{profile_json}\n\n"
        f"**Open support tickets:**\n{tickets_json}\n\n"
        "**Instructions:**\n"
        "1. Write an empathetic, technically accurate outreach email.\n"
        "2. Address the specific issues causing health deterioration.\n"
        "3. Personalize with stakeholder names and their technical maturity "
        "levels -- adjust technical depth accordingly.\n"
        "4. Reference known integrations and environment details for context.\n"
        "5. Propose concrete next steps (call, review, fix timeline).\n"
        "6. Tone should be proactive and supportive, not alarming.\n"
        "7. This is a DRAFT for the account rep to review before sending.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_release_notes_prompt(
    release_info: dict,
    relationship_profile: dict,
) -> str:
    """Build a prompt for generating tailored release notes.

    Creates account-specific release notes that highlight only the features
    relevant to this account's known use cases, integrations, and environment.

    Args:
        release_info: Release data dict containing version, features list,
            changelog, and any migration notes.
        relationship_profile: Serialized RelationshipProfile dict with
            integrations, feature_adoption, customer_environment.

    Returns:
        Prompt string with embedded JSON schema and release notes instructions.
    """
    schema = json.dumps(_RELEASE_NOTES_SCHEMA, indent=2)
    release_json = json.dumps(release_info, indent=2, default=str)
    profile_json = json.dumps(relationship_profile, indent=2, default=str)

    return (
        "**Task:** Generate tailored release notes for this account. Highlight "
        "only the features and changes relevant to their specific use cases.\n\n"
        f"**Release information:**\n{release_json}\n\n"
        f"**Relationship profile:**\n{profile_json}\n\n"
        "**Instructions:**\n"
        "1. Filter the release to features relevant to this account's "
        "integrations, adopted features, and environment.\n"
        "2. For each highlighted feature, explain why it matters to THIS "
        "account specifically.\n"
        "3. If the release includes migration steps or breaking changes "
        "affecting their integrations, call them out prominently.\n"
        "4. Match the communication depth to the stakeholders' technical "
        "maturity levels.\n"
        "5. Keep the tone informative and positive.\n"
        "6. This is a DRAFT for the account rep to review before sending.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_roadmap_preview_prompt(
    roadmap_items: list[dict],
    relationship_profile: dict,
) -> str:
    """Build a prompt for generating a technical roadmap preview.

    Creates a roadmap preview communication for QBR or strategic call
    preparation, framing upcoming features in the context of the account's
    needs and identifying co-development opportunities.

    Args:
        roadmap_items: List of roadmap item dicts with item name, description,
            estimated timeline, and category.
        relationship_profile: Serialized RelationshipProfile dict with
            integrations, feature_adoption, co_dev_opportunities.

    Returns:
        Prompt string with embedded JSON schema and roadmap preview
        instructions.
    """
    schema = json.dumps(_ROADMAP_PREVIEW_SCHEMA, indent=2)
    roadmap_json = json.dumps(roadmap_items, indent=2, default=str)
    profile_json = json.dumps(relationship_profile, indent=2, default=str)

    return (
        "**Task:** Generate a technical roadmap preview communication for QBR "
        "or strategic call preparation.\n\n"
        f"**Roadmap items:**\n{roadmap_json}\n\n"
        f"**Relationship profile:**\n{profile_json}\n\n"
        "**Instructions:**\n"
        "1. Identify roadmap items aligned with this account's active "
        "integrations and feature usage.\n"
        "2. Frame each aligned item in terms of business value for THIS "
        "account.\n"
        "3. Identify co-development opportunities where the account could "
        "participate in shaping the feature.\n"
        "4. Structure for QBR-ready presentation: clear, executive-friendly "
        "but technically substantive.\n"
        "5. Note existing co-dev opportunities from the profile and link "
        "to relevant roadmap items.\n"
        "6. This is a DRAFT for the account rep to review before sharing.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_health_checkin_prompt(
    health_score: dict,
    relationship_profile: dict,
    recent_communications: list[dict],
) -> str:
    """Build a prompt for generating a periodic health check-in.

    Creates a health check-in communication even when all is well,
    referencing past communications for continuity and maintaining the
    relationship cadence.

    Args:
        health_score: Serialized HealthScoreResult dict with current score
            and RAG status.
        relationship_profile: Serialized RelationshipProfile dict with full
            account context.
        recent_communications: List of recent CommunicationRecord dicts
            for continuity and context.

    Returns:
        Prompt string with embedded JSON schema and health check-in
        instructions.
    """
    schema = json.dumps(_HEALTH_CHECKIN_SCHEMA, indent=2)
    health_json = json.dumps(health_score, indent=2, default=str)
    profile_json = json.dumps(relationship_profile, indent=2, default=str)
    comms_json = json.dumps(recent_communications, indent=2, default=str)

    return (
        "**Task:** Generate a periodic health check-in communication for "
        "this account.\n\n"
        f"**Current health score:**\n{health_json}\n\n"
        f"**Relationship profile:**\n{profile_json}\n\n"
        f"**Recent communications:**\n{comms_json}\n\n"
        "**Instructions:**\n"
        "1. Summarize the current health status in plain language.\n"
        "2. Reference any recent communications for continuity (e.g., "
        "\"Following up on our discussion about...\").\n"
        "3. Even if health is good (Green), provide value by noting positive "
        "trends, feature adoption progress, or upcoming opportunities.\n"
        "4. If health is Amber or Red, acknowledge specific issues and "
        "outline steps being taken.\n"
        "5. Include actionable recommendations appropriate to the account's "
        "technical maturity.\n"
        "6. Keep the tone warm, professional, and relationship-building.\n"
        "7. This is a DRAFT for the account rep to review before sending.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_customer_success_review_prompt(
    health_score: dict,
    relationship_profile: dict,
    tickets: list[dict],
) -> str:
    """Build a prompt for generating a Customer Success Review (CSR).

    Creates a structured CSR covering health status, integration summary,
    open items, and strategic recommendations. Distinct from CSM QBR
    materials (Phase 14) -- this is a technical health and relationship review.

    Args:
        health_score: Serialized HealthScoreResult dict with score, RAG,
            and scan metadata.
        relationship_profile: Serialized RelationshipProfile dict with full
            account context including integrations and feature adoption.
        tickets: List of serialized TicketSummary dicts for open tickets.

    Returns:
        Prompt string with embedded JSON schema and CSR instructions.
    """
    schema = json.dumps(_CUSTOMER_SUCCESS_REVIEW_SCHEMA, indent=2)
    health_json = json.dumps(health_score, indent=2, default=str)
    profile_json = json.dumps(relationship_profile, indent=2, default=str)
    tickets_json = json.dumps(tickets, indent=2, default=str)

    return (
        "**Task:** Generate a Customer Success Review (CSR) -- a structured "
        "summary of technical health, integrations, open items, and "
        "recommendations.\n\n"
        f"**Health score:**\n{health_json}\n\n"
        f"**Relationship profile:**\n{profile_json}\n\n"
        f"**Open support tickets:**\n{tickets_json}\n\n"
        "**Instructions:**\n"
        "1. Provide a health overview covering the current score, trend "
        "(improving/stable/declining), and contributing factors.\n"
        "2. Summarize active integrations -- their status, any recent "
        "issues, and adoption depth.\n"
        "3. List all open support items with priority and age context.\n"
        "4. Provide strategic recommendations: feature adoption opportunities, "
        "integration improvements, training needs, or proactive steps.\n"
        "5. Structure as a professional review document suitable for sharing "
        "with account stakeholders.\n"
        "6. Match technical depth to the stakeholders' maturity levels.\n"
        "7. This is a DRAFT for the account rep to review before sharing.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


# ── Internal Helpers ───────────────────────────────────────────────────────


def _format_context(context: dict) -> str:
    """Format a context dict as a readable string for prompt injection.

    Args:
        context: Dict of metadata to format.

    Returns:
        Formatted string, or "No context provided." if empty.
    """
    if not context:
        return "No context provided."

    parts: list[str] = []
    for key, value in context.items():
        label = key.replace("_", " ").title()
        parts.append(f"- {label}: {value}")
    return "\n".join(parts)


__all__ = [
    "TAM_SYSTEM_PROMPT",
    "build_escalation_outreach_prompt",
    "build_release_notes_prompt",
    "build_roadmap_preview_prompt",
    "build_health_checkin_prompt",
    "build_customer_success_review_prompt",
]
