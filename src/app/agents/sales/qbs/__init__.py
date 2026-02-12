"""QBS (Question Based Selling) methodology subpackage.

Provides QBS-specific data models, prompt templates, builder functions,
and service classes for integrating Thomas Freese's QBS framework with the
existing Sales Agent.

Exports:
    QBSQuestionType: Question category enum (pain_funnel, impact, solution, confirmation).
    PainDepthLevel: Pain exploration depth enum (not_explored -> surface -> business_impact -> emotional).
    EngagementSignal: Customer engagement signal enum.
    QBSQuestionRecommendation: Blended triple (QBS type + MEDDIC/BANT target + Voss delivery).
    PainTopic: Individual pain point with depth and evidence.
    PainFunnelState: Pain funnel progression state across conversation turns.
    ExpansionTrigger: Detected mention of another person in conversation.
    ExpansionRecommendation: Aggregated expansion recommendation with triggers.
    QBSQuestionEngine: Adaptive QBS question selection based on conversation signals.
    PainDepthTracker: Pain funnel state management for QBS methodology.
    AccountExpansionDetector: Detects expansion triggers from conversation text.
"""

from src.app.agents.sales.qbs.engine import QBSQuestionEngine
from src.app.agents.sales.qbs.expansion import AccountExpansionDetector
from src.app.agents.sales.qbs.pain_tracker import PainDepthTracker
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
    "AccountExpansionDetector",
    "EngagementSignal",
    "ExpansionRecommendation",
    "ExpansionTrigger",
    "PainDepthLevel",
    "PainDepthTracker",
    "PainFunnelState",
    "PainTopic",
    "QBSQuestionEngine",
    "QBSQuestionRecommendation",
    "QBSQuestionType",
]
