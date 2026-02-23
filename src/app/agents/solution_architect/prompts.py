"""Prompt templates for the Solution Architect agent.

Provides the SA system prompt and five prompt builder functions -- one per
SA capability. Each builder returns a ``list[dict[str, str]]`` (messages list)
ready for LLM chat completion API consumption.

Capabilities:
    1. Requirements extraction from sales transcripts
    2. Architecture narrative generation
    3. POC scoping and tier selection
    4. Technical objection response
    5. Technical question handoff (Sales Agent -> SA -> Sales Agent)

Exports:
    SA_SYSTEM_PROMPT: Base system prompt establishing SA persona.
    build_requirements_extraction_prompt: Messages for requirements extraction.
    build_architecture_narrative_prompt: Messages for architecture narrative.
    build_poc_scoping_prompt: Messages for POC plan generation.
    build_objection_response_prompt: Messages for objection handling.
    build_technical_handoff_prompt: Messages for technical Q&A handoff.
"""

from __future__ import annotations


# ── System Prompt ──────────────────────────────────────────────────────────


SA_SYSTEM_PROMPT: str = """\
You are a Solution Architect at Skyvera, a technical pre-sales expert \
specializing in enterprise software integration, API design, cloud \
architecture, and solution scoping.

**Your expertise:**
- Enterprise integration patterns (REST, webhooks, event streams, ETL)
- Cloud-native architecture (microservices, containerization, serverless)
- Security and compliance (SOC 2, GDPR, encryption at rest/in transit)
- Performance engineering (caching, CDN, database optimization, load balancing)
- Solution scoping and POC planning with accurate effort estimation

**Your communication style:**
- Precise: Use specific technical terms, exact numbers, and concrete examples.
- Confident: State recommendations with clear rationale. Avoid hedging unless \
genuinely uncertain.
- Concise: Lead with the answer, then provide supporting detail. Executives \
and sales reps read your outputs -- respect their time.
- Evidence-grounded: Every claim references specific technical documentation, \
benchmarks, or architecture precedents.

**Your outputs are used in live sales conversations.** Sales representatives \
rely on your technical analysis to answer prospect questions, scope POCs, and \
address competitive objections. Accuracy and clarity are critical.

**Confidence protocol:**
- When you are confident (>0.8), state the answer directly.
- When uncertain (0.5-0.8), provide the best answer and note the uncertainty.
- When low-confidence (<0.5), explicitly flag the gap and recommend further \
investigation rather than speculating.\
"""


# ── Prompt Builders ────────────────────────────────────────────────────────


def build_requirements_extraction_prompt(
    transcript: str,
    deal_context: dict,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for extracting technical requirements from a transcript.

    Args:
        transcript: Sales call or meeting transcript text.
        deal_context: Deal metadata (stage, prospect info, known tech stack).
        rag_context: Pre-retrieved knowledge base context for grounding.

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    deal_summary = _format_deal_context(deal_context)

    user_message = (
        "**Task:** Extract all technical requirements from the following "
        "sales transcript.\n\n"
        f"**Deal context:**\n{deal_summary}\n\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        f"**Transcript:**\n{transcript}\n\n"
        "**Instructions:**\n"
        "1. Identify every technical requirement mentioned or implied.\n"
        "2. Classify each by category: integration, security, performance, "
        "compliance, or scalability.\n"
        "3. Assign priority: must_have, nice_to_have, or dealbreaker.\n"
        "4. Include the source quote from the transcript when available.\n"
        "5. Rate your confidence for each requirement (0.0-1.0).\n"
        "6. Write a concise summary of the overall technical needs.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "requirements": [\n'
        "    {\n"
        '      "category": "integration|security|performance|compliance|scalability",\n'
        '      "description": "string",\n'
        '      "priority": "must_have|nice_to_have|dealbreaker",\n'
        '      "source_quote": "string",\n'
        '      "confidence": 0.8\n'
        "    }\n"
        "  ],\n"
        '  "summary": "string",\n'
        '  "confidence": 0.8,\n'
        '  "source_transcript_hash": ""\n'
        "}\n"
        "```"
    )

    return [
        {"role": "system", "content": SA_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def build_architecture_narrative_prompt(
    tech_stack: str,
    requirements_json: str,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for generating an architecture narrative.

    Args:
        tech_stack: Comma-separated list of prospect's technologies.
        requirements_json: JSON string of TechnicalRequirementsDoc.
        rag_context: Pre-retrieved knowledge base context (architecture
            templates, product docs).

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    user_message = (
        "**Task:** Generate an architecture narrative describing how Skyvera "
        "integrates with the prospect's technology stack.\n\n"
        f"**Prospect tech stack:** {tech_stack}\n\n"
        f"**Technical requirements:**\n{requirements_json}\n\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        "**Instructions:**\n"
        "1. Write a clear overview (2-4 paragraphs) of the proposed "
        "architecture.\n"
        "2. Define each integration point with type and complexity.\n"
        "3. Describe a diagram that could be generated from this narrative.\n"
        "4. List any assumptions you are making.\n"
        "5. Reference the prospect's specific technologies by name.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "overview": "string (2-4 paragraphs)",\n'
        '  "integration_points": [\n'
        "    {\n"
        '      "name": "string",\n'
        '      "integration_type": "rest_api|webhook|database_sync|event_stream|file_transfer",\n'
        '      "description": "string",\n'
        '      "complexity": "low|medium|high"\n'
        "    }\n"
        "  ],\n"
        '  "diagram_description": "string",\n'
        '  "assumptions": ["string"],\n'
        '  "prospect_tech_stack": "string"\n'
        "}\n"
        "```"
    )

    return [
        {"role": "system", "content": SA_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def build_poc_scoping_prompt(
    requirements_json: str,
    deal_stage: str,
    timeline_preference: str,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for generating a POC plan.

    Args:
        requirements_json: JSON string of TechnicalRequirementsDoc.
        deal_stage: Current deal stage (e.g., "evaluation", "qualification").
        timeline_preference: Prospect's stated timeline preference
            (e.g., "2 weeks", "Q2", "ASAP").
        rag_context: Pre-retrieved knowledge base context (POC templates,
            past POC data).

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    user_message = (
        "**Task:** Generate a POC plan with deliverables, timeline, resource "
        "estimates, and success criteria.\n\n"
        f"**Technical requirements:**\n{requirements_json}\n\n"
        f"**Deal stage:** {deal_stage}\n\n"
        f"**Timeline preference:** {timeline_preference}\n\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        "**Instructions:**\n"
        "1. Select an appropriate tier (small/medium/large) based on "
        "requirements complexity.\n"
        "2. Define concrete deliverables with acceptance criteria.\n"
        "3. Estimate resources (developer_days, qa_days, pm_hours).\n"
        "4. Set a timeline in weeks that respects the prospect's preference.\n"
        "5. Define measurable success criteria.\n"
        "6. Identify risks with mitigations.\n\n"
        "**Tier guidelines:**\n"
        "- small: 1-2 integration points, 1-2 weeks, <=5 dev days\n"
        "- medium: 3-4 integration points, 2-4 weeks, 6-15 dev days\n"
        "- large: 5+ integration points, 4-8 weeks, 16+ dev days\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "deliverables": [\n'
        "    {\n"
        '      "name": "string",\n'
        '      "description": "string",\n'
        '      "acceptance_criteria": "string"\n'
        "    }\n"
        "  ],\n"
        '  "timeline_weeks": 2,\n'
        '  "resource_estimate": {\n'
        '    "developer_days": 5,\n'
        '    "qa_days": 2,\n'
        '    "pm_hours": 8\n'
        "  },\n"
        '  "success_criteria": ["string"],\n'
        '  "risks": ["string"],\n'
        '  "tier": "small|medium|large"\n'
        "}\n"
        "```"
    )

    return [
        {"role": "system", "content": SA_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def build_objection_response_prompt(
    objection: str,
    competitor: str,
    deal_context: dict,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for generating a technical objection response.

    Args:
        objection: The technical objection or competitive claim to address.
        competitor: Name of the competitor (empty string if not competitive).
        deal_context: Deal metadata for situational awareness.
        rag_context: Pre-retrieved knowledge base context (competitor analysis,
            battlecards, product positioning).

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    deal_summary = _format_deal_context(deal_context)

    competitor_section = ""
    if competitor:
        competitor_section = (
            f"\n**Competitor:** {competitor}\n"
            "Focus your response on specific technical differentiators. "
            "Avoid generic claims -- cite benchmarks, architecture advantages, "
            "or customer evidence.\n"
        )

    user_message = (
        "**Task:** Craft a technical response to the following objection "
        "that a sales representative can deliver in conversation.\n\n"
        f"**Objection:** {objection}\n"
        f"{competitor_section}\n"
        f"**Deal context:**\n{deal_summary}\n\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        "**Instructions:**\n"
        "1. Address the objection directly and specifically.\n"
        "2. Support every claim with evidence from the knowledge base.\n"
        "3. Recommend a concrete follow-up action.\n"
        "4. Keep the response concise -- sales reps will paraphrase it.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "response": "string",\n'
        '  "evidence": [\n'
        "    {\n"
        '      "claim": "string",\n'
        '      "source_doc": "string",\n'
        '      "confidence": 0.8\n'
        "    }\n"
        "  ],\n"
        '  "recommended_followup": "string",\n'
        '  "competitor_name": "string"\n'
        "}\n"
        "```"
    )

    return [
        {"role": "system", "content": SA_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def build_technical_handoff_prompt(
    question: str,
    deal_context: dict,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for answering a technical question from the Sales Agent.

    This is the SA's response path in the Sales Agent -> SA -> Sales Agent
    handoff flow. The output is structured for the Sales Agent to incorporate
    into its conversation.

    Args:
        question: Technical question from the prospect or sales rep.
        deal_context: Deal metadata including known tech stack.
        rag_context: Pre-retrieved knowledge base context.

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    deal_summary = _format_deal_context(deal_context)

    user_message = (
        "**Task:** Answer the following technical question. Your response "
        "will be delivered by a sales representative, so write in clear, "
        "non-jargon language while remaining technically accurate.\n\n"
        f"**Question:** {question}\n\n"
        f"**Deal context:**\n{deal_summary}\n\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        "**Instructions:**\n"
        "1. Answer the question directly and completely.\n"
        "2. List source documents that support your answer.\n"
        "3. Reference related documentation the prospect might find useful.\n"
        "4. Rate your confidence in the answer (0.0-1.0).\n"
        "5. If an architecture diagram would help, describe it in "
        "architecture_diagram_url (set to null if not needed).\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "answer": "string",\n'
        '  "evidence": ["source_doc_name"],\n'
        '  "architecture_diagram_url": null,\n'
        '  "related_docs": ["doc_path_or_id"],\n'
        '  "confidence": 0.8\n'
        "}\n"
        "```"
    )

    return [
        {"role": "system", "content": SA_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


# ── Internal Helpers ───────────────────────────────────────────────────────


def _format_deal_context(deal_context: dict) -> str:
    """Format a deal context dict as a readable string for prompt injection.

    Args:
        deal_context: Dict of deal metadata (stage, prospect info, etc.).

    Returns:
        Formatted string, or "No deal context provided." if empty.
    """
    if not deal_context:
        return "No deal context provided."

    parts: list[str] = []
    for key, value in deal_context.items():
        label = key.replace("_", " ").title()
        parts.append(f"- {label}: {value}")
    return "\n".join(parts)


__all__ = [
    "SA_SYSTEM_PROMPT",
    "build_requirements_extraction_prompt",
    "build_architecture_narrative_prompt",
    "build_poc_scoping_prompt",
    "build_objection_response_prompt",
    "build_technical_handoff_prompt",
]
