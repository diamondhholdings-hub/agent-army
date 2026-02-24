"""Prompt templates for the Business Analyst agent.

Provides the BA system prompt and four prompt builder functions -- one per
BA capability. Each builder embeds the target Pydantic model's JSON schema
directly in the user message so the LLM returns parseable, schema-compliant
JSON.

Capabilities:
    1. Requirements extraction from stakeholder conversations
    2. Gap analysis against product capabilities
    3. User story generation from extracted requirements
    4. Process documentation (current-state / future-state)

Exports:
    BA_SYSTEM_PROMPT: Base system prompt establishing BA persona.
    build_requirements_extraction_prompt: Prompt for requirements extraction.
    build_gap_analysis_prompt: Prompt for gap analysis.
    build_user_story_generation_prompt: Prompt for user story generation.
    build_process_documentation_prompt: Prompt for process documentation.
"""

from __future__ import annotations

import json

from src.app.agents.business_analyst.schemas import (
    ExtractedRequirement,
    GapAnalysisResult,
    ProcessDocumentation,
    UserStory,
)


# ── System Prompt ──────────────────────────────────────────────────────────


BA_SYSTEM_PROMPT: str = """\
You are a Business Analyst agent specializing in requirements engineering. \
You extract structured requirements from conversations, perform gap analysis \
against product capabilities, detect contradictions, generate user stories, \
and produce process documentation. Always return valid JSON matching the \
provided schema. Be thorough but precise -- extract only what the conversation \
evidence supports.\
"""


# ── Prompt Builders ────────────────────────────────────────────────────────


def build_requirements_extraction_prompt(
    conversation_text: str,
    deal_context: dict | None = None,
) -> str:
    """Build a prompt for extracting structured requirements from a conversation.

    Embeds the ExtractedRequirement JSON schema so the LLM returns parseable
    JSON matching the model.

    Args:
        conversation_text: The source conversation or transcript to analyze.
        deal_context: Optional deal metadata for additional context.

    Returns:
        Prompt string with embedded JSON schema and extraction instructions.
    """
    schema = json.dumps(ExtractedRequirement.model_json_schema(), indent=2)

    deal_section = ""
    if deal_context:
        deal_summary = _format_deal_context(deal_context)
        deal_section = f"\n**Deal context:**\n{deal_summary}\n"

    return (
        "**Task:** Extract ALL requirements from the following conversation. "
        "Categorize each requirement using all three classification schemes "
        "simultaneously.\n\n"
        f"**Conversation:**\n{conversation_text}\n"
        f"{deal_section}\n"
        "**Instructions:**\n"
        "1. Identify every requirement mentioned or implied in the conversation.\n"
        "2. Classify each by category: functional, non_functional, or constraint.\n"
        "3. Assign MoSCoW priority: must_have, should_have, could_have, or wont_have.\n"
        "4. Identify the stakeholder_domain: sales, tech, ops, or finance.\n"
        "5. Assign a priority_score: high, med, or low.\n"
        "6. Include the source_quote from the conversation when available.\n"
        "7. Assign unique requirement_ids (e.g., REQ-001, REQ-002).\n\n"
        "**Confidence scoring guidance:**\n"
        "- 0.9+ for explicit statements (stakeholder directly states the requirement)\n"
        "- 0.6-0.9 for implied requirements (strongly suggested by context)\n"
        "- Below 0.6 for inferred/uncertain requirements (loosely implied, "
        "needs confirmation)\n\n"
        "Respond with ONLY a JSON array of objects matching this schema:\n"
        f"```json\n{schema}\n```\n\n"
        "Return the requirements as a JSON array: [{...}, {...}, ...]"
    )


def build_gap_analysis_prompt(
    requirements: list[dict],
    capability_chunks: list[str],
) -> str:
    """Build a prompt for gap analysis comparing requirements against capabilities.

    Embeds the GapAnalysisResult JSON schema (which includes CapabilityGap
    and RequirementContradiction sub-schemas) so the LLM returns a complete,
    parseable gap analysis.

    Args:
        requirements: List of requirement dicts (serialized ExtractedRequirement).
        capability_chunks: Pre-retrieved product capability text chunks from
            the knowledge base.

    Returns:
        Prompt string with embedded JSON schema and gap analysis instructions.
    """
    schema = json.dumps(GapAnalysisResult.model_json_schema(), indent=2)
    requirements_json = json.dumps(requirements, indent=2)
    capabilities_text = "\n---\n".join(capability_chunks)

    return (
        "**Task:** Perform a gap analysis comparing the extracted requirements "
        "against current product capabilities.\n\n"
        f"**Requirements:**\n{requirements_json}\n\n"
        f"**Product capabilities:**\n{capabilities_text}\n\n"
        "**Instructions:**\n"
        "1. Compare each requirement against the product capabilities.\n"
        "2. Identify gaps where the product falls short of a requirement. "
        "For each gap, assign:\n"
        "   - severity: critical (deal-blocking), major (significant impact), "
        "or minor (low impact)\n"
        "   - recommended_action: build_it (add to roadmap), find_partner "
        "(integrate with partner), or descope (remove from scope)\n"
        "   - workaround: a temporary solution if available, null otherwise\n"
        "3. Detect contradictions between requirements. Each contradiction "
        "must reference at least 2 requirement_ids.\n"
        "4. Compute coverage_percentage: (requirements with matching "
        "capabilities / total requirements) * 100.\n"
        "5. Set requires_sa_escalation to true for any gap with "
        "severity=critical and no workaround.\n"
        "6. Provide a recommended_next_action string summarizing what the "
        "Sales Agent should do next.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


def build_user_story_generation_prompt(
    requirements: list[dict],
    group_by_context: str | None = None,
) -> str:
    """Build a prompt for generating agile user stories from requirements.

    Embeds the UserStory JSON schema so the LLM returns parseable stories
    in standard agile format with traceability to source requirements.

    Args:
        requirements: List of requirement dicts (serialized ExtractedRequirement).
        group_by_context: Optional grouping context (e.g., sprint theme,
            epic name) for organizing stories.

    Returns:
        Prompt string with embedded JSON schema and story generation instructions.
    """
    schema = json.dumps(UserStory.model_json_schema(), indent=2)
    requirements_json = json.dumps(requirements, indent=2)

    group_section = ""
    if group_by_context:
        group_section = (
            f"\n**Grouping context:** {group_by_context}\n"
            "Organize stories around this context where appropriate.\n"
        )

    return (
        "**Task:** Generate agile user stories from the following extracted "
        "requirements.\n\n"
        f"**Requirements:**\n{requirements_json}\n"
        f"{group_section}\n"
        "**Instructions:**\n"
        "1. Use standard agile format: As a [role], I want [feature], "
        "so that [value].\n"
        "2. Include at least 2 acceptance criteria per story.\n"
        "3. Assign story_points using Fibonacci values only: 1, 2, 3, 5, 8, 13.\n"
        "4. Group stories by both epic_theme AND stakeholder_domain.\n"
        "5. For low-confidence requirements (extraction_confidence < 0.6), "
        "include the story but set is_low_confidence to true.\n"
        "6. Link each story back to its source requirements via "
        "source_requirement_ids.\n"
        "7. Assign unique story_ids (e.g., US-001, US-002).\n"
        "8. Match priority from the source requirement's moscow_priority.\n\n"
        "Respond with ONLY a JSON array of objects matching this schema:\n"
        f"```json\n{schema}\n```\n\n"
        "Return the stories as a JSON array: [{...}, {...}, ...]"
    )


def build_process_documentation_prompt(
    conversation_text: str,
    process_context: dict | None = None,
) -> str:
    """Build a prompt for extracting process documentation from a conversation.

    Embeds the ProcessDocumentation JSON schema so the LLM returns a
    structured current-state / future-state process description.

    Args:
        conversation_text: The source conversation describing the process.
        process_context: Optional context (e.g., industry, department,
            existing tools) for enrichment.

    Returns:
        Prompt string with embedded JSON schema and documentation instructions.
    """
    schema = json.dumps(ProcessDocumentation.model_json_schema(), indent=2)

    context_section = ""
    if process_context:
        context_summary = _format_deal_context(process_context)
        context_section = f"\n**Process context:**\n{context_summary}\n"

    return (
        "**Task:** Extract process documentation from the following "
        "conversation, describing both the current state and the desired "
        "future state.\n\n"
        f"**Conversation:**\n{conversation_text}\n"
        f"{context_section}\n"
        "**Instructions:**\n"
        "1. Identify and name the business process being discussed.\n"
        "2. Describe the current_state: how things work today (as-is).\n"
        "3. Describe the future_state: how things should work (to-be).\n"
        "4. Compute the delta: what specifically changes between current "
        "and future state.\n"
        "5. Identify all stakeholders involved in this process.\n"
        "6. List any assumptions made during documentation.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        f"```json\n{schema}\n```"
    )


# ── Internal Helpers ───────────────────────────────────────────────────────


def _format_deal_context(context: dict) -> str:
    """Format a context dict as a readable string for prompt injection.

    Args:
        context: Dict of metadata (deal context, process context, etc.).

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
    "BA_SYSTEM_PROMPT",
    "build_requirements_extraction_prompt",
    "build_gap_analysis_prompt",
    "build_user_story_generation_prompt",
    "build_process_documentation_prompt",
]
