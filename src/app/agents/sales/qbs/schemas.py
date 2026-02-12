"""QBS (Question Based Selling) Pydantic data models.

Defines structured types for the QBS methodology integration: question types,
pain depth levels, engagement signals, question recommendations, pain funnel
state tracking, and account expansion triggers. These models are used by the
QBS Question Engine, Pain Tracker, and Expansion Detector.

All models follow the existing ``src.app.agents.sales.schemas`` patterns:
``BaseModel`` with ``Field`` descriptors, ``str`` enums, and optional fields
with sensible defaults.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ── Enums ───────────────────────────────────────────────────────────────────


class QBSQuestionType(str, Enum):
    """QBS question categories per Thomas Freese's framework.

    Question types are NOT applied in fixed sequence. The QBS engine selects
    adaptively based on conversation signals: information gaps, customer
    engagement level, and natural conversation flow.
    """

    PAIN_FUNNEL = "pain_funnel"  # Surface problems -> business impact -> emotional depth
    IMPACT = "impact"  # Business consequences of identified pain
    SOLUTION = "solution"  # Connect needs to product capabilities
    CONFIRMATION = "confirmation"  # Validate understanding, build commitment


class PainDepthLevel(str, Enum):
    """Tracks how deep the pain funnel has been explored.

    Depth progresses: NOT_EXPLORED -> SURFACE -> BUSINESS_IMPACT -> EMOTIONAL.
    Not every conversation reaches EMOTIONAL depth -- respect the customer's
    pace and note gaps for later revisit.
    """

    NOT_EXPLORED = "not_explored"  # Pain not yet explored
    SURFACE = "surface"  # Problem identified at surface level
    BUSINESS_IMPACT = "business_impact"  # Business cost/consequences articulated
    EMOTIONAL = "emotional"  # Root cause / emotional driver reached


class EngagementSignal(str, Enum):
    """Customer engagement signals detected in conversation.

    Used by the QBS engine to adapt question strategy: probe deeper on
    HIGH_ENERGY topics, back off on RESISTANT signals, follow TOPIC_SHIFT
    to customer's interest.
    """

    HIGH_ENERGY = "high_energy"  # Customer elaborating, volunteering info
    FACTUAL = "factual"  # Customer responding but not deeply engaged
    RESISTANT = "resistant"  # Customer deflecting, giving short answers
    TOPIC_SHIFT = "topic_shift"  # Customer redirecting conversation
    EMOTIONAL_LANGUAGE = "emotional_language"  # Customer using emotional terms


# ── Question Recommendation ────────────────────────────────────────────────


class QBSQuestionRecommendation(BaseModel):
    """Structured output from the QBS Question Engine.

    Captures the blended triple: QBS question type + MEDDIC/BANT qualification
    target + Chris Voss empathy delivery technique. This is the primary
    instructor ``response_model`` for QBS signal analysis.
    """

    question_type: QBSQuestionType = Field(
        description="QBS question category to use",
    )
    meddic_bant_target: str = Field(
        description=(
            "Which MEDDIC/BANT dimension this question targets, "
            "e.g. 'need', 'metrics', 'budget', 'champion'"
        ),
    )
    voss_delivery: str = Field(
        description=(
            "Chris Voss technique: 'mirror', 'label', "
            "'calibrated_question', 'accusation_audit'"
        ),
    )
    suggested_question: str = Field(
        description="The blended question ready for natural use in conversation",
    )
    rationale: str = Field(
        description=(
            "Why this question type, target, and delivery were chosen "
            "given conversation context"
        ),
    )
    information_gaps: list[str] = Field(
        default_factory=list,
        description="BANT/MEDDIC qualification data still missing",
    )
    engagement_signal: EngagementSignal = Field(
        description="Detected customer engagement level from latest message",
    )
    pain_depth: PainDepthLevel = Field(
        description="Current depth of pain exploration for primary topic",
    )
    should_probe_deeper: bool = Field(
        description="Whether to continue probing current topic vs move on",
    )
    natural_stopping_signals: list[str] = Field(
        default_factory=list,
        description=(
            "Signals detected that suggest stopping current probe"
        ),
    )


# ── Pain Funnel State ──────────────────────────────────────────────────────


class PainTopic(BaseModel):
    """A specific pain point tracked through the funnel.

    Each topic records exploration depth, evidence from the conversation,
    business impact if articulated, and emotional indicators if detected.
    """

    topic: str = Field(description="Brief description of the pain point")
    depth: PainDepthLevel = Field(description="Current exploration depth")
    evidence: str = Field(description="Quote or summary from conversation")
    business_impact: str | None = Field(
        default=None,
        description="Articulated business cost",
    )
    emotional_indicator: str | None = Field(
        default=None,
        description="Emotional language detected",
    )
    first_mentioned_at: int = Field(
        description="Interaction number when first raised",
    )
    last_probed_at: int = Field(
        description="Interaction number of most recent probe",
    )


class PainFunnelState(BaseModel):
    """Pain funnel progression across conversation turns.

    Tracks overall depth, individual pain topics (max 10 per RESEARCH.md
    Pitfall 6), engagement signals, and probing pace to prevent
    over-interrogation.
    """

    depth_level: PainDepthLevel = Field(
        default=PainDepthLevel.NOT_EXPLORED,
        description="Overall deepest depth reached",
    )
    pain_topics: list[PainTopic] = Field(
        default_factory=list,
        description="Tracked pain points (max 10)",
    )
    emotional_recognition_detected: bool = Field(
        default=False,
        description="Whether customer showed emotional weight",
    )
    self_elaboration_count: int = Field(
        default=0,
        description="Times customer volunteered detail unprompted",
    )
    resistance_detected: bool = Field(
        default=False,
        description="Whether customer showed resistance to probing",
    )
    revisit_later: list[str] = Field(
        default_factory=list,
        description="Pain gaps to revisit in future conversations",
    )
    last_probed_topic: str | None = Field(
        default=None,
        description="Most recently probed topic",
    )
    probe_count_current_topic: int = Field(
        default=0,
        description=(
            "Probes on current topic -- back off after 2-3 "
            "without elaboration"
        ),
    )


# ── Account Expansion ──────────────────────────────────────────────────────


class ExpansionTrigger(BaseModel):
    """A detected mention of another person in conversation.

    Captures the mentioned contact, surrounding context, relationship
    inference, and a recommended QBS approach for engagement with urgency
    assessment.
    """

    mentioned_name_or_role: str = Field(
        description=(
            "Who was mentioned: 'my boss', 'the finance team', "
            "'Sarah from procurement'"
        ),
    )
    context_quote: str = Field(
        description="The sentence where they were mentioned",
    )
    relationship_to_contact: str = Field(
        description="Inferred relationship to current contact",
    )
    expansion_approach: str = Field(
        description="Recommended QBS approach for engagement",
    )
    urgency: str = Field(
        description=(
            "'immediate', 'next_conversation', or 'after_trust_builds'"
        ),
    )


class ExpansionRecommendation(BaseModel):
    """Expansion recommendation for instructor extraction.

    Aggregates detected expansion triggers with a primary recommendation,
    resistance assessment, and political context for multi-threading
    orchestration.
    """

    triggers: list[ExpansionTrigger] = Field(
        default_factory=list,
        description="Detected expansion triggers",
    )
    primary_recommendation: str = Field(
        default="",
        description="Best next step for multi-threading",
    )
    resistance_assessment: str = Field(
        default="",
        description="Likelihood of resistance and handling approach",
    )
    political_context: str = Field(
        default="",
        description="How this fits political mapping context",
    )
