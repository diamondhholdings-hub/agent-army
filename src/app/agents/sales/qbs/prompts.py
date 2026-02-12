"""QBS prompt templates and builder functions.

Provides QBS-specific prompt constants (methodology instructions, signal
analysis prompts, expansion detection prompts) and builder functions that
compose messages lists for instructor LLM calls and dynamic prompt sections
for injection into the main system prompt.

Exports:
    QBS_METHODOLOGY_PROMPT: Core QBS methodology instructions for system prompts.
    QBS_ANALYSIS_SYSTEM_PROMPT: System prompt for QBS engine signal analysis.
    EXPANSION_DETECTION_PROMPT: System prompt for expansion trigger detection.
    build_qbs_analysis_prompt: Build messages list for QBS engine instructor call.
    build_qbs_prompt_section: Build dynamic QBS section for system prompt injection.
    build_expansion_detection_prompt: Build messages list for expansion detection.
"""

from __future__ import annotations

from src.app.agents.sales.qbs.schemas import (
    ExpansionTrigger,
    PainFunnelState,
    QBSQuestionRecommendation,
)


# ── Core QBS Methodology Prompt ────────────────────────────────────────────

QBS_METHODOLOGY_PROMPT: str = """\
You integrate Question Based Selling (QBS) methodology by Thomas Freese \
throughout your interactions. QBS questions are not asked mechanically -- \
they emerge naturally from the conversation, blended with Chris Voss empathy \
techniques and targeted at BANT/MEDDIC qualification gaps.

**QBS Question Types:**

- **Pain Funnel:** Surface problems, then explore business impact, then reach \
emotional/root cause depth. Progress gradually -- not every customer goes deep \
in one conversation. Respect the customer's pace. Note gaps for later.
  Example: "What challenges are you facing with your current approach?"

- **Impact Questions:** Help the customer feel the weight of their problem by \
exploring business consequences. Only effective after pain is identified at \
surface level.
  Example: "What happens to your team's other priorities when they're stuck \
doing this work?"

- **Solution Questions:** Connect their articulated pain to specific product \
capabilities. Only after pain and impact are well-established -- premature \
solution questions lose credibility.
  Example: "If you could eliminate that 40-hour bottleneck, what would your \
team focus on instead?"

- **Confirmation Questions:** Validate understanding and build micro-commitments. \
Use throughout the conversation to demonstrate active listening and ensure \
alignment.
  Example: "So if I'm hearing you correctly, the core issue is that manual \
processing is costing you both time and accuracy?"

**Elite Salesperson Principles:**

- Listen actively for what the customer reveals AND what they do NOT reveal
- Follow the energy -- if they light up on a topic, probe deeper there
- Questions emerge from what was just said, never from a script
- Gap sensing -- intuitively identify what's missing and probe accordingly
- Context over checklist -- respond to the conversation, not a methodology \
sequence

**Methodology Blending:**

Each question blends three dimensions seamlessly:
1. QBS structure -- which question type fits the conversation moment
2. MEDDIC/BANT targeting -- which qualification gap this question fills
3. Voss empathy delivery -- mirror, label, calibrated question, or \
accusation audit

The blend must feel natural and consultative, never formulaic.

**Give Value First:**

Before asking a QBS question, lead with value: mirror what they said, label \
an emotion, or share a relevant insight. Earn the right to ask by \
demonstrating expertise and genuine interest in their success.

**Anti-Interrogation Rule:**

Never ask more than one probing question per message. Balance every question \
with acknowledgment, value, or insight. The conversation should feel \
consultative, not interrogative.

**Pain Funnel Pacing:**

Respect the customer's pace. Not every customer goes deep in one conversation. \
If the customer has not elaborated after 2-3 probes on the same topic, back \
off. Note the gap for later and move to a different angle or topic. Forcing \
emotional disclosure damages trust.\
"""


# ── QBS Analysis System Prompt ─────────────────────────────────────────────

QBS_ANALYSIS_SYSTEM_PROMPT: str = """\
You are a QBS (Question Based Selling) signal analyst. Your job is to analyze \
a sales conversation and recommend the optimal next question using the QBS \
methodology blended with MEDDIC/BANT qualification and Chris Voss empathy \
techniques.

**Three Sensing Modes:**

1. **Information Gap Sensing:** Analyze what BANT/MEDDIC qualification data \
is still missing. Identify the most critical gap that could be filled with a \
natural question. Consider which gaps are most relevant to the current deal \
stage and conversation context.

2. **Engagement Signal Detection:** Assess the customer's engagement level \
from their latest message. Look for:
   - HIGH_ENERGY: Customer elaborating, volunteering information, asking \
follow-up questions
   - FACTUAL: Customer responding adequately but not deeply engaged
   - RESISTANT: Customer deflecting, giving short answers, pushing back
   - TOPIC_SHIFT: Customer redirecting the conversation to a different subject
   - EMOTIONAL_LANGUAGE: Customer using emotional terms ("frustrated", \
"worried", "excited", "exhausted")

3. **Natural Conversation Flow:** Determine what logically follows from the \
customer's latest message. The next question should feel like a natural \
continuation, not a jarring topic change. Follow the customer's energy.

**Question Selection (NOT Fixed Sequence):**

Select the optimal QBS question type based on the sensing modes above. Do NOT \
follow a fixed pain->impact->solution->confirmation sequence. Any question \
type can appear at any stage when the moment calls for it.

- PAIN_FUNNEL: When pain is not yet explored or only at surface level
- IMPACT: When pain is identified but business consequences not articulated
- SOLUTION: When pain and impact are established and customer is ready for \
capabilities discussion
- CONFIRMATION: When validating understanding or building micro-commitments

**Methodology Blending:**

For the selected question type, identify:
- The MEDDIC/BANT dimension with the biggest gap that this question should \
target
- The Chris Voss delivery technique that fits the engagement level (mirror \
for high-energy, label for emotional, calibrated_question for factual, \
accusation_audit for resistant)

**Question Generation:**

Generate a natural, blended question -- not template-stitched. The question \
should achieve the QBS goal, fill the MEDDIC/BANT gap, and use the Voss \
technique, all while sounding like something a top 1% salesperson would \
naturally say.

**Pain Depth Assessment:**

Assess the current pain exploration depth:
- NOT_EXPLORED: No pain topics identified yet
- SURFACE: Problem identified at surface level
- BUSINESS_IMPACT: Business cost/consequences have been articulated
- EMOTIONAL: Root cause or emotional driver has been reached

**Probing Decision:**

Determine whether to continue probing the current topic or move on. Look for \
natural stopping signals:
- Customer gives a clear, complete answer
- Customer shifts focus or changes topic
- Customer shows resistance (shorter answers, deflection)
- Same topic has been probed 2-3 times without new elaboration\
"""


# ── Expansion Detection Prompt ─────────────────────────────────────────────

EXPANSION_DETECTION_PROMPT: str = """\
You are an account expansion analyst for a sales team. Your job is to scan \
conversation text for mentions of other people, teams, or roles that could \
represent multi-threading opportunities.

**Detection Rules:**

1. Scan for any mention of another person by name, title, role, or team \
reference (e.g., "my boss", "the VP of Engineering", "Sarah from procurement", \
"the finance team", "our CTO").

2. For each detected mention, extract:
   - **mentioned_name_or_role:** The person or role as mentioned in context
   - **context_quote:** The exact sentence where they were mentioned
   - **relationship_to_contact:** Inferred relationship to the current speaker \
(e.g., "direct manager", "peer in another department", "executive sponsor")
   - **expansion_approach:** Recommended QBS approach for engaging this new \
contact. Use one of these strategies:
     * Direct request: "Can you introduce me to [person]?"
     * QBS-style: "How does [person] experience this problem?"
     * Value-based: "To ensure this works for [team], it would help to \
understand their requirements"
     * Voss calibrated: "How am I supposed to solve [pain] without \
understanding what [person] needs?"
   - **urgency:** Assessment of when to pursue expansion:
     * "immediate" -- High trust established, strong engagement, natural \
opening in conversation
     * "next_conversation" -- Good rapport but topic needs further \
development first
     * "after_trust_builds" -- Early relationship, insufficient trust for \
expansion request

3. Only flag NEW contacts not already in the known contacts list.

4. Do NOT flag generic references that don't represent actionable expansion \
opportunities (e.g., "the team" without specific context, vague "someone" \
references).\
"""


# ── Builder Functions ──────────────────────────────────────────────────────


def build_qbs_analysis_prompt(
    conversation_state_summary: str,
    latest_message: str,
    conversation_history_summary: str,
    pain_state_summary: str,
    qualification_gaps: str,
) -> list[dict[str, str]]:
    """Build messages list for the QBS engine's instructor call.

    Uses ``QBS_ANALYSIS_SYSTEM_PROMPT`` as the system message. The user
    message includes all context summaries needed for signal analysis.

    Args:
        conversation_state_summary: Summary of deal stage, persona, and
            interaction count.
        latest_message: The customer's most recent message text.
        conversation_history_summary: Condensed summary of prior turns.
        pain_state_summary: Current pain funnel state description.
        qualification_gaps: Summary of missing BANT/MEDDIC data.

    Returns:
        List of two message dicts: system and user.
    """
    user_content = (
        "**Conversation State:**\n"
        f"{conversation_state_summary}\n\n"
        "**Latest Customer Message:**\n"
        f"{latest_message}\n\n"
        "**Conversation History:**\n"
        f"{conversation_history_summary}\n\n"
        "**Pain Funnel State:**\n"
        f"{pain_state_summary}\n\n"
        "**Qualification Gaps:**\n"
        f"{qualification_gaps}\n\n"
        "Based on all the above context, analyze the conversation signals "
        "and recommend the optimal QBS question. Select the question type, "
        "MEDDIC/BANT target, and Voss delivery technique that best fits "
        "this moment in the conversation."
    )

    return [
        {"role": "system", "content": QBS_ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_qbs_prompt_section(
    qbs_recommendation: QBSQuestionRecommendation,
    pain_state: PainFunnelState,
    expansion_triggers: list[ExpansionTrigger],
) -> str:
    """Build the dynamic QBS guidance section for system prompt injection.

    This section is inserted into the main system prompt (via agent.py)
    to provide conversation-specific QBS guidance. It formats the question
    recommendation, pain funnel guidance, and expansion opportunities as
    a string section -- NOT a messages list.

    Args:
        qbs_recommendation: The QBS engine's question recommendation.
        pain_state: Current pain funnel state.
        expansion_triggers: Detected expansion opportunities (may be empty).

    Returns:
        Formatted string section for system prompt injection.
    """
    section = (
        "**Question Based Selling (QBS) Guidance for This Message:**\n\n"
        f"**Primary Question Type:** {qbs_recommendation.question_type.value}\n"
        f"**Target:** Extract {qbs_recommendation.meddic_bant_target} data\n"
        f"**Delivery:** Use {qbs_recommendation.voss_delivery} technique\n"
        f"**Suggested Question:** \"{qbs_recommendation.suggested_question}\"\n\n"
        f"**Rationale:** {qbs_recommendation.rationale}\n\n"
    )

    # Information gaps
    if qbs_recommendation.information_gaps:
        section += (
            "**Information Gaps to Fill:**\n"
            + "\n".join(
                f"- {gap}" for gap in qbs_recommendation.information_gaps
            )
            + "\n\n"
        )

    # Pain funnel guidance
    section += _build_pain_guidance(pain_state, qbs_recommendation)

    # Account expansion guidance
    if expansion_triggers:
        section += _build_expansion_guidance(expansion_triggers)

    return section


def build_expansion_detection_prompt(
    conversation_text: str,
    existing_contacts: list[str],
) -> list[dict[str, str]]:
    """Build messages list for expansion trigger detection.

    Uses ``EXPANSION_DETECTION_PROMPT`` as the system message with
    existing contacts appended so the LLM only flags new mentions.

    Args:
        conversation_text: The conversation text to scan for mentions.
        existing_contacts: List of already-known contact names/roles.

    Returns:
        List of two message dicts: system and user.
    """
    contacts_section = ""
    if existing_contacts:
        contacts_section = (
            "\n\n**Known Contacts Already Engaged:**\n"
            + ", ".join(existing_contacts)
            + "\n\nOnly flag NEW contacts not in this list."
        )
    else:
        contacts_section = (
            "\n\n**Known Contacts Already Engaged:**\n"
            "None -- all detected contacts are potentially new."
        )

    system_content = EXPANSION_DETECTION_PROMPT + contacts_section

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": conversation_text},
    ]


# ── Internal Helpers ───────────────────────────────────────────────────────


def _build_pain_guidance(
    pain_state: PainFunnelState,
    recommendation: QBSQuestionRecommendation,
) -> str:
    """Build pain funnel guidance sub-section."""
    section = "**Pain Funnel Status:**\n"

    section += f"- Current depth: {pain_state.depth_level.value}\n"

    if pain_state.pain_topics:
        section += f"- Active pain topics: {len(pain_state.pain_topics)}\n"
        for topic in pain_state.pain_topics[:3]:
            section += (
                f"  - \"{topic.topic}\" (depth: {topic.depth.value})"
            )
            if topic.business_impact:
                section += f" -- impact: {topic.business_impact}"
            section += "\n"

    if pain_state.resistance_detected:
        section += (
            "- **RESISTANCE DETECTED:** Back off current probe. "
            "Switch to a different angle or provide value.\n"
        )

    if recommendation.should_probe_deeper:
        section += "- Recommendation: Continue probing current topic.\n"
    else:
        section += (
            "- Recommendation: Move on to a different topic or angle.\n"
        )

    if pain_state.revisit_later:
        section += (
            "- Topics to revisit later: "
            + ", ".join(pain_state.revisit_later[:3])
            + "\n"
        )

    section += "\n"
    return section


def _build_expansion_guidance(
    triggers: list[ExpansionTrigger],
) -> str:
    """Build account expansion guidance sub-section."""
    section = "**Account Expansion Opportunities:**\n\n"

    for trigger in triggers:
        section += (
            f"- **{trigger.mentioned_name_or_role}** "
            f"({trigger.relationship_to_contact})\n"
            f"  Context: \"{trigger.context_quote}\"\n"
            f"  Approach: {trigger.expansion_approach}\n"
            f"  Urgency: {trigger.urgency}\n\n"
        )

    return section
