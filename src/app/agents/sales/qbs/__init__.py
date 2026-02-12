"""QBS (Question Based Selling) methodology subpackage.

Provides QBS-specific data models, prompt templates, and builder functions
for integrating Thomas Freese's QBS framework with the existing Sales Agent.
The QBS Question Engine, Pain Tracker, and Expansion Detector (Plans 02/03)
build on the schemas and prompts defined here.

Exports:
    QBSQuestionType: Question category enum (pain_funnel, impact, solution, confirmation).
    PainDepthLevel: Pain exploration depth enum (not_explored -> surface -> business_impact -> emotional).
    EngagementSignal: Customer engagement signal enum.
    QBSQuestionRecommendation: Blended triple (QBS type + MEDDIC/BANT target + Voss delivery).
    PainTopic: Individual pain point with depth and evidence.
    PainFunnelState: Pain funnel progression state across conversation turns.
    ExpansionTrigger: Detected mention of another person in conversation.
    ExpansionRecommendation: Aggregated expansion recommendation with triggers.
"""

from src.app.agents.sales.qbs.schemas import (
    EngagementSignal,
    ExpansionRecommendation,
    ExpansionTrigger,
    PainDepthLevel,
    PainFunnelState,
    PainTopic,
    QBSQuestionRecommendation,
    QBSQuestionType,
)

__all__ = [
    "EngagementSignal",
    "ExpansionRecommendation",
    "ExpansionTrigger",
    "PainDepthLevel",
    "PainFunnelState",
    "PainTopic",
    "QBSQuestionRecommendation",
    "QBSQuestionType",
]
