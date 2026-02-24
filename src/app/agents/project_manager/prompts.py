"""Prompt templates for the Project Manager agent.

Provides the PM system prompt and six prompt builder functions -- one per
PM capability. Each builder returns a ``list[dict[str, str]]`` (messages list)
ready for LLM chat completion API consumption.

Capabilities:
    1. Create project plan (PMBOK-compliant 3-level WBS)
    2. Detect risk signals from milestone progress
    3. Adjust plan via scope change delta (NOT full regeneration)
    4. Generate internal status report (detailed, with earned value)
    5. Generate external status report (customer-facing, polished)
    6. Process trigger event to determine project parameters

Exports:
    PM_SYSTEM_PROMPT: Base system prompt establishing PM persona.
    build_create_plan_prompt: Messages for project plan creation.
    build_detect_risks_prompt: Messages for risk signal detection.
    build_adjust_plan_prompt: Messages for scope change delta generation.
    build_internal_report_prompt: Messages for internal status report.
    build_external_report_prompt: Messages for external status report.
    build_process_trigger_prompt: Messages for trigger event processing.
"""

from __future__ import annotations


# ── System Prompt ──────────────────────────────────────────────────────────


PM_SYSTEM_PROMPT: str = """\
You are a Project Manager at Skyvera, a PMBOK-certified delivery management expert \
specializing in enterprise software implementation projects.

**Your expertise:**
- PMBOK-compliant project planning (WBS, milestones, critical path analysis)
- Earned value management (BCWP, ACWP, BCWS, CPI, SPI)
- Risk identification and mitigation (proactive, not reactive)
- Scope change management with impact analysis
- Stakeholder communication (internal teams and external customers)

**Your communication style:**
- Structured: Use PMBOK terminology and WBS hierarchy consistently.
- Quantitative: Lead with numbers -- dates, percentages, effort days.
- Actionable: Every report ends with concrete next steps and owners.
- Audience-aware: Internal reports are detailed; customer reports are polished.

**Your outputs drive project delivery.** Account executives and customers rely \
on your plans, risk alerts, and status reports to track project health. \
Accuracy in dates, effort estimates, and risk assessments is critical.

**Confidence protocol:**
- When confident (>0.8), state the plan/assessment directly.
- When uncertain (0.5-0.8), provide best estimate and note assumptions.
- When low-confidence (<0.5), flag the gap and recommend clarification.\
"""


# ── Prompt Builders ────────────────────────────────────────────────────────


def build_create_plan_prompt(
    deliverables: list[str],
    deal_context: dict,
    sa_artifacts: str,
    timeline: str,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for creating a PMBOK-compliant 3-level WBS project plan.

    Args:
        deliverables: List of expected project deliverables.
        deal_context: Deal metadata (stage, prospect info, value).
        sa_artifacts: Solution Architect artifacts for enrichment context.
        timeline: Human-readable timeline description (e.g., "3 months").
        rag_context: Pre-retrieved knowledge base context for grounding.

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    deal_summary = _format_deal_context(deal_context)
    deliverables_str = "\n".join(f"- {d}" for d in deliverables) if deliverables else "None specified"

    sa_section = ""
    if sa_artifacts:
        sa_section = (
            f"\n**Solution Architect artifacts (optional enrichment):**\n"
            f"{sa_artifacts}\n"
        )

    user_message = (
        "**Task:** Create a PMBOK-compliant 3-level WBS project plan for the "
        "following deliverables.\n\n"
        f"**Deal context:**\n{deal_summary}\n\n"
        f"**Deliverables:**\n{deliverables_str}\n\n"
        f"**Timeline:** {timeline}\n"
        f"{sa_section}\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        "**Instructions:**\n"
        "1. Build a 3-level WBS: Phases -> Milestones -> Tasks.\n"
        "2. Each phase must include a resource_estimate_days (total effort "
        "in person-days).\n"
        "3. Each milestone must include a target_date (ISO 8601), and "
        "success_criteria describing what constitutes completion.\n"
        "4. Each task must include owner (role), duration_days (effort), "
        "dependencies (list of task_ids), and status.\n"
        "5. Assign unique IDs: phase_id (ph-NNN), milestone_id (m-NNN), "
        "task_id (t-NNN).\n"
        "6. Identify the critical path and note it in the first phase "
        "description.\n"
        "7. Follow PMBOK-compliant planning practices: define scope clearly, "
        "include buffer for risk, assign owners to every task.\n"
        "8. Set total_budget_days as the sum of all phase resource estimates.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "plan_id": "string (unique identifier)",\n'
        '  "deal_id": "string (from deal context)",\n'
        '  "project_name": "string (descriptive project name)",\n'
        '  "phases": [\n'
        "    {\n"
        '      "phase_id": "ph-001",\n'
        '      "name": "string (e.g., Discovery, Implementation, Go-Live)",\n'
        '      "resource_estimate_days": 10,\n'
        '      "milestones": [\n'
        "        {\n"
        '          "milestone_id": "m-001",\n'
        '          "name": "string",\n'
        '          "target_date": "2024-03-15T00:00:00Z",\n'
        '          "success_criteria": "string describing completion criteria",\n'
        '          "status": "not_started|in_progress|completed|at_risk|overdue",\n'
        '          "tasks": [\n'
        "            {\n"
        '              "task_id": "t-001",\n'
        '              "name": "string",\n'
        '              "owner": "string (role, e.g., PM, Developer, QA)",\n'
        '              "duration_days": 2,\n'
        '              "dependencies": ["t-000"],\n'
        '              "status": "not_started|in_progress|completed|blocked"\n'
        "            }\n"
        "          ]\n"
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "created_at": "ISO 8601 timestamp",\n'
        '  "updated_at": "ISO 8601 timestamp",\n'
        '  "version": 1,\n'
        '  "trigger_source": "deal_won|poc_scoped|complex_deal|manual",\n'
        '  "total_budget_days": 0\n'
        "}\n"
        "```"
    )

    return [
        {"role": "system", "content": PM_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def build_detect_risks_prompt(
    plan_json: str,
    current_progress: str,
    deal_context: dict,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for detecting risk signals from plan and progress data.

    Args:
        plan_json: JSON string of the current ProjectPlan.
        current_progress: Summary of milestone progress and timeline status.
        deal_context: Deal metadata for contextual risk assessment.
        rag_context: Pre-retrieved knowledge base context.

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    deal_summary = _format_deal_context(deal_context)

    user_message = (
        "**Task:** Analyze the project plan and current progress to detect "
        "risk signals that require attention or automatic adjustment.\n\n"
        f"**Deal context:**\n{deal_summary}\n\n"
        f"**Current project plan:**\n{plan_json}\n\n"
        f"**Current progress data:**\n{current_progress}\n\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        "**Instructions:**\n"
        "1. Compare milestone target_dates against current progress to detect "
        "overdue milestones.\n"
        "2. Identify tasks on the critical path that are blocked or at risk.\n"
        "3. Check resource utilization against budget (resource_exceeded if "
        "actual effort > budget by threshold).\n"
        "4. Detect deal stage stalling (no CRM activity for extended period).\n"
        "5. Assign severity: low (monitor), medium (action needed this week), "
        "high (action needed today), critical (escalate immediately).\n"
        "6. Provide a specific, actionable recommended_action for each risk.\n\n"
        "**Risk types to evaluate:**\n"
        "- milestone_overdue: A milestone has passed its target_date without "
        "completion.\n"
        "- critical_path_blocked: A task on the critical path is blocked by "
        "dependencies or resources.\n"
        "- resource_exceeded: Actual effort spent exceeds the budgeted "
        "resource_estimate_days.\n"
        "- deal_stage_stalled: The CRM deal stage has not progressed and no "
        "activity has been logged.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "risks": [\n'
        "    {\n"
        '      "risk_id": "string (unique identifier, e.g., r-001)",\n'
        '      "signal_type": "milestone_overdue|critical_path_blocked|resource_exceeded|deal_stage_stalled",\n'
        '      "severity": "low|medium|high|critical",\n'
        '      "description": "string (what the risk is and why it matters)",\n'
        '      "affected_milestone_id": "string or null",\n'
        '      "recommended_action": "string (specific, actionable step)",\n'
        '      "auto_adjustment": null,\n'
        '      "detected_at": "ISO 8601 timestamp"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "```\n\n"
        "If no risks are detected, return an empty risks array."
    )

    return [
        {"role": "system", "content": PM_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def build_adjust_plan_prompt(
    original_plan_json: str,
    scope_change_description: str,
    trigger: str,
    deal_context: dict,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for generating a scope change delta report.

    The LLM produces a delta report showing changes -- it does NOT
    regenerate the full plan. This ensures traceability and version control.

    Args:
        original_plan_json: JSON string of the current ProjectPlan.
        scope_change_description: Description of the requested scope change.
        trigger: What caused the scope change (e.g., "sa_updated_requirements").
        deal_context: Deal metadata for impact assessment context.
        rag_context: Pre-retrieved knowledge base context.

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    deal_summary = _format_deal_context(deal_context)

    user_message = (
        "**Task:** Produce a delta report showing the impact of a scope change "
        "on the existing project plan. Do NOT regenerate the full plan.\n\n"
        f"**Deal context:**\n{deal_summary}\n\n"
        f"**Original project plan:**\n{original_plan_json}\n\n"
        f"**Scope change description:**\n{scope_change_description}\n\n"
        f"**Trigger:** {trigger}\n\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        "**Instructions:**\n"
        "1. Produce a delta report showing changes, NOT a regenerated plan.\n"
        "2. Identify which phases, milestones, and tasks are affected.\n"
        "3. Calculate timeline_impact_days (positive = project gets longer, "
        "negative = shorter).\n"
        "4. Calculate resource_impact_days (additional or reduced effort).\n"
        "5. List all affected_milestones by milestone_id.\n"
        "6. Provide a risk_assessment of the scope change impact.\n"
        "7. Recommend: approve, approve_with_conditions, or "
        "reject_recommend_descope.\n"
        "8. Each change element must specify element_type, element_id, "
        "field, original_value, revised_value, and change_type.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "change_request_id": "string (unique identifier)",\n'
        '  "original_plan_version": 1,\n'
        '  "revised_plan_version": 2,\n'
        '  "trigger": "sa_updated_requirements|manual_input",\n'
        '  "changes": [\n'
        "    {\n"
        '      "element_type": "phase|milestone|task",\n'
        '      "element_id": "string (id of affected element)",\n'
        '      "field": "string (field name that changed)",\n'
        '      "original_value": "string",\n'
        '      "revised_value": "string",\n'
        '      "change_type": "added|removed|modified"\n'
        "    }\n"
        "  ],\n"
        '  "timeline_impact_days": 0,\n'
        '  "resource_impact_days": 0.0,\n'
        '  "affected_milestones": ["m-001"],\n'
        '  "risk_assessment": "string (assessment of risk from this change)",\n'
        '  "recommendation": "approve|approve_with_conditions|reject_recommend_descope"\n'
        "}\n"
        "```"
    )

    return [
        {"role": "system", "content": PM_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def build_internal_report_prompt(
    plan_json: str,
    progress_data: str,
    risk_log: str,
    earned_value_json: str,
    deal_context: dict,
    sa_summary: str,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for generating an internal status report.

    The earned_value field is PRE-CALCULATED and must be included as-is.
    The LLM should NOT recalculate earned value metrics.

    Args:
        plan_json: JSON string of the current ProjectPlan.
        progress_data: Milestone progress summary data.
        risk_log: JSON string of current risk log entries.
        earned_value_json: Pre-calculated earned value metrics (BCWP, ACWP,
            BCWS, CPI, SPI). Included as-is, not recomputed.
        deal_context: CRM deal metadata for context.
        sa_summary: Summary from the Solution Architect agent.
        rag_context: Pre-retrieved knowledge base context.

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    deal_summary = _format_deal_context(deal_context)

    sa_section = ""
    if sa_summary:
        sa_section = (
            f"\n**Solution Architect summary:**\n{sa_summary}\n"
        )

    user_message = (
        "**Task:** Generate a comprehensive internal status report for the "
        "project team and management.\n\n"
        f"**Deal context:**\n{deal_summary}\n\n"
        f"**Current project plan:**\n{plan_json}\n\n"
        f"**Milestone progress data:**\n{progress_data}\n\n"
        f"**Risk log:**\n{risk_log}\n\n"
        f"**Pre-calculated earned value metrics:**\n{earned_value_json}\n"
        f"{sa_section}\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        "**Instructions:**\n"
        "1. Determine overall RAG status (red/amber/green) based on milestone "
        "progress and risk severity.\n"
        "2. Summarize each milestone's progress with task completion counts "
        "and percentage.\n"
        "3. Include current risks and issues from the risk log.\n"
        "4. Define concrete next actions with owners and due dates.\n"
        "5. The earned_value field is PRE-CALCULATED. Include it as-is. "
        "Do NOT recalculate CPI, SPI, BCWP, ACWP, or BCWS values.\n"
        "6. Include deal_context information for situational awareness.\n"
        "7. Add PM agent analysis in agent_notes (trends, concerns, "
        "recommendations).\n"
        "8. Include SA summary if available.\n\n"
        "**RAG guidelines:**\n"
        "- Green: All milestones on track, CPI >= 0.9, SPI >= 0.9.\n"
        "- Amber: Minor delays or 1-2 medium risks, CPI 0.7-0.9 or "
        "SPI 0.7-0.9.\n"
        "- Red: Critical risks, major delays, CPI < 0.7 or SPI < 0.7.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "report_id": "string (unique identifier)",\n'
        '  "project_id": "string (plan_id from the project plan)",\n'
        '  "report_date": "ISO 8601 timestamp",\n'
        '  "overall_rag": "red|amber|green",\n'
        '  "milestone_progress": [\n'
        "    {\n"
        '      "milestone_id": "string",\n'
        '      "name": "string",\n'
        '      "total_tasks": 5,\n'
        '      "completed_tasks": 3,\n'
        '      "pct_complete": 60.0,\n'
        '      "status": "on_track|at_risk|overdue|completed",\n'
        '      "target_date": "ISO 8601 timestamp",\n'
        '      "projected_date": "ISO 8601 timestamp or null"\n'
        "    }\n"
        "  ],\n"
        '  "risks_and_issues": [\n'
        "    {\n"
        '      "risk_id": "string",\n'
        '      "signal_type": "string",\n'
        '      "severity": "string",\n'
        '      "description": "string",\n'
        '      "owner": "string",\n'
        '      "status": "open|mitigated|closed|accepted",\n'
        '      "created_at": "ISO 8601 timestamp",\n'
        '      "resolved_at": "ISO 8601 timestamp or null"\n'
        "    }\n"
        "  ],\n"
        '  "next_actions": [\n'
        "    {\n"
        '      "action_id": "string",\n'
        '      "description": "string",\n'
        '      "owner": "string",\n'
        '      "due_date": "ISO 8601 timestamp",\n'
        '      "status": "pending|in_progress|completed"\n'
        "    }\n"
        "  ],\n"
        '  "earned_value": {\n'
        '    "bcwp": 0.0,\n'
        '    "acwp": 0.0,\n'
        '    "bcws": 0.0,\n'
        '    "cpi": 0.0,\n'
        '    "spi": 0.0\n'
        "  },\n"
        '  "deal_context": {},\n'
        '  "agent_notes": "string (PM analysis: trends, concerns, recommendations)",\n'
        '  "sa_summary": "string"\n'
        "}\n"
        "```"
    )

    return [
        {"role": "system", "content": PM_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def build_external_report_prompt(
    plan_json: str,
    progress_data: str,
    project_name: str,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for generating a customer-facing status report.

    External reports use polished language and do NOT include deal_context,
    agent_notes, SA summary, or earned value metrics. These are internal-only.

    Args:
        plan_json: JSON string of the current ProjectPlan.
        progress_data: Milestone progress summary data.
        project_name: Customer-visible project name.
        rag_context: Pre-retrieved knowledge base context.

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    user_message = (
        "**Task:** Generate a polished, customer-facing status report for "
        f'the project "{project_name}".\n\n'
        f"**Current project plan:**\n{plan_json}\n\n"
        f"**Milestone progress data:**\n{progress_data}\n\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        "**Instructions:**\n"
        '1. Use overall_status: "On Track", "At Risk", or "Delayed" '
        "(NOT red/amber/green -- those are internal only).\n"
        "2. Summarize each milestone with customer-friendly status and "
        "estimated completion (e.g., 'Week of March 15').\n"
        "3. List key_accomplishments: recent wins the customer should know.\n"
        "4. List upcoming_activities: what happens next.\n"
        "5. List items_requiring_attention: issues needing customer awareness "
        "or action.\n"
        "6. Use polished, professional language. The customer sees this.\n"
        "7. Do NOT include internal metrics (earned value, CPI, SPI), "
        "deal context, agent notes, or SA summary.\n"
        "8. Do NOT use internal risk terminology (red/amber/green RAG).\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "report_id": "string (unique identifier)",\n'
        '  "project_name": "string",\n'
        '  "report_date": "ISO 8601 timestamp",\n'
        '  "overall_status": "On Track|At Risk|Delayed",\n'
        '  "milestone_summary": [\n'
        "    {\n"
        '      "name": "string",\n'
        '      "status": "string (customer-friendly description)",\n'
        '      "estimated_completion": "string (e.g., Week of March 15)"\n'
        "    }\n"
        "  ],\n"
        '  "key_accomplishments": ["string"],\n'
        '  "upcoming_activities": ["string"],\n'
        '  "items_requiring_attention": ["string"]\n'
        "}\n"
        "```"
    )

    return [
        {"role": "system", "content": PM_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def build_process_trigger_prompt(
    trigger_type: str,
    deal_context: dict,
    deliverables: list[str],
    sa_artifacts: str,
    rag_context: str,
) -> list[dict[str, str]]:
    """Build messages for processing a trigger event and determining plan params.

    Different trigger types receive different instruction emphasis:
    - deal_won: Focus on delivery execution planning.
    - poc_scoped: Focus on POC execution within constrained timeline.
    - complex_deal: Focus on comprehensive planning with risk mitigation.

    Args:
        trigger_type: Type of trigger event (deal_won, poc_scoped, etc.).
        deal_context: Deal metadata for contextual planning.
        deliverables: List of expected deliverables from the trigger.
        sa_artifacts: Solution Architect artifacts for enrichment.
        rag_context: Pre-retrieved knowledge base context.

    Returns:
        Messages list with system and user messages for LLM consumption.
    """
    deal_summary = _format_deal_context(deal_context)
    deliverables_str = "\n".join(f"- {d}" for d in deliverables) if deliverables else "None specified"

    # Trigger-specific instruction emphasis
    trigger_instructions: dict[str, str] = {
        "deal_won": (
            "**Trigger emphasis -- Deal Won:**\n"
            "This deal has been closed-won. Focus on delivery execution:\n"
            "- Prioritize rapid project kickoff and resource allocation.\n"
            "- Define clear handoff from sales to delivery team.\n"
            "- Establish project governance and communication cadence.\n"
            "- Set realistic milestones based on contract commitments.\n"
        ),
        "poc_scoped": (
            "**Trigger emphasis -- POC Scoped:**\n"
            "A proof of concept has been scoped by the Solution Architect. "
            "Focus on POC execution:\n"
            "- Constrain timeline to POC duration (typically 2-4 weeks).\n"
            "- Prioritize demonstrable outcomes over comprehensive coverage.\n"
            "- Define success criteria that map to POC deliverables.\n"
            "- Plan for rapid iteration and stakeholder demos.\n"
        ),
        "complex_deal": (
            "**Trigger emphasis -- Complex Deal:**\n"
            "This deal requires comprehensive planning before commitment. "
            "Focus on thorough planning:\n"
            "- Include detailed risk analysis and mitigation strategies.\n"
            "- Plan for multiple integration points and dependencies.\n"
            "- Build in adequate buffer for unknowns.\n"
            "- Define phased delivery with early value milestones.\n"
        ),
    }

    emphasis = trigger_instructions.get(trigger_type, (
        "**Trigger emphasis -- Manual:**\n"
        "A project plan has been manually requested. Apply standard "
        "PMBOK planning practices.\n"
    ))

    sa_section = ""
    if sa_artifacts:
        sa_section = (
            f"\n**Solution Architect artifacts:**\n{sa_artifacts}\n"
        )

    user_message = (
        "**Task:** Analyze this trigger event and determine the recommended "
        "project plan parameters.\n\n"
        f"**Trigger type:** {trigger_type}\n\n"
        f"{emphasis}\n"
        f"**Deal context:**\n{deal_summary}\n\n"
        f"**Deliverables:**\n{deliverables_str}\n"
        f"{sa_section}\n"
        f"**Knowledge base context:**\n{rag_context}\n\n"
        "**Instructions:**\n"
        "1. Determine a descriptive project_name based on deal context and "
        "deliverables.\n"
        "2. Recommend project phases appropriate for the trigger type and "
        "complexity.\n"
        "3. Estimate total duration in weeks.\n"
        "4. Assign priority: high (deal_won, time-sensitive), medium "
        "(poc_scoped, standard), low (complex_deal planning phase).\n"
        "5. Add any notes about assumptions, risks, or special "
        "considerations.\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "```json\n"
        "{\n"
        '  "project_name": "string (descriptive name for the project)",\n'
        '  "recommended_phases": [\n'
        '    "Discovery",\n'
        '    "Implementation",\n'
        '    "Testing",\n'
        '    "Go-Live"\n'
        "  ],\n"
        '  "estimated_duration_weeks": 8,\n'
        '  "priority": "high|medium|low",\n'
        '  "notes": "string (assumptions, risks, special considerations)"\n'
        "}\n"
        "```"
    )

    return [
        {"role": "system", "content": PM_SYSTEM_PROMPT},
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
    "PM_SYSTEM_PROMPT",
    "build_create_plan_prompt",
    "build_detect_risks_prompt",
    "build_adjust_plan_prompt",
    "build_internal_report_prompt",
    "build_external_report_prompt",
    "build_process_trigger_prompt",
]
