"""Pydantic data models for the Solution Architect agent domain.

Defines all structured types used across the Solution Architect agent:
technical requirements extraction, architecture narratives, POC scoping,
objection handling, and inter-agent technical handoff payloads. These models
are the foundational types that every SA capability depends on.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Technical Requirements ─────────────────────────────────────────────────


class TechRequirement(BaseModel):
    """A single technical requirement extracted from a sales conversation.

    Attributes:
        category: Technical domain of the requirement.
        description: Plain-language description of the requirement.
        priority: Business priority classification.
        source_quote: Verbatim quote from the transcript that evidences this
            requirement. Empty string if no direct quote available.
        confidence: Model's confidence in the extraction (0.0 to 1.0).
    """

    category: Literal[
        "integration",
        "security",
        "performance",
        "compliance",
        "scalability",
    ]
    description: str
    priority: Literal["must_have", "nice_to_have", "dealbreaker"]
    source_quote: str = ""
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class TechnicalRequirementsDoc(BaseModel):
    """Structured technical requirements document extracted from a transcript.

    Aggregates individual requirements with a human-readable summary and
    traceability back to the source transcript.

    Attributes:
        requirements: List of extracted technical requirements.
        summary: Human-readable summary of the overall technical needs.
        confidence: Overall confidence in the extraction (0.0 to 1.0).
        source_transcript_hash: SHA-256 hash of the source transcript for
            traceability. Empty string if not computed.
    """

    requirements: list[TechRequirement]
    summary: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    source_transcript_hash: str = ""


# ── Architecture Narrative ─────────────────────────────────────────────────


class IntegrationPoint(BaseModel):
    """A single integration point in a proposed architecture.

    Attributes:
        name: Human-readable name of the integration (e.g., "CRM Sync").
        integration_type: Technical integration pattern.
        description: How this integration works and what data flows through it.
        complexity: Estimated implementation complexity.
    """

    name: str
    integration_type: Literal[
        "rest_api",
        "webhook",
        "database_sync",
        "event_stream",
        "file_transfer",
    ]
    description: str
    complexity: Literal["low", "medium", "high"]


class ArchitectureNarrative(BaseModel):
    """A prose architecture narrative suitable for inclusion in sales materials.

    Describes how the solution would integrate with the prospect's existing
    tech stack, including specific integration points and a diagram description
    for visual representation.

    Attributes:
        overview: High-level architecture narrative (2-4 paragraphs).
        integration_points: Specific integration touch-points with the prospect.
        diagram_description: Text description of the architecture diagram
            suitable for diagram generation tools.
        assumptions: Technical assumptions made during narrative generation.
        prospect_tech_stack: Comma-separated list of prospect technologies
            referenced in the narrative. Empty string if unknown.
    """

    overview: str
    integration_points: list[IntegrationPoint]
    diagram_description: str
    assumptions: list[str] = Field(default_factory=list)
    prospect_tech_stack: str = ""


# ── POC Scoping ────────────────────────────────────────────────────────────


class POCDeliverable(BaseModel):
    """A single deliverable in a POC plan.

    Attributes:
        name: Short name for the deliverable (e.g., "API Integration Demo").
        description: What this deliverable demonstrates or proves.
        acceptance_criteria: How success is measured for this deliverable.
    """

    name: str
    description: str
    acceptance_criteria: str


class ResourceEstimate(BaseModel):
    """Resource estimate for a POC engagement.

    Attributes:
        developer_days: Estimated developer effort in person-days.
        qa_days: Estimated QA effort in person-days.
        pm_hours: Estimated project management effort in hours.
    """

    developer_days: int = Field(ge=0)
    qa_days: int = Field(ge=0)
    pm_hours: int = Field(ge=0)


class POCPlan(BaseModel):
    """Complete POC plan with deliverables, timeline, and resource estimates.

    Attributes:
        deliverables: List of POC deliverables to produce.
        timeline_weeks: Estimated duration in weeks.
        resource_estimate: Resource allocation for the POC.
        success_criteria: List of measurable success criteria for the POC.
        risks: Identified risks and mitigations.
        tier: POC size classification affecting resource allocation.
    """

    deliverables: list[POCDeliverable]
    timeline_weeks: int = Field(ge=1)
    resource_estimate: ResourceEstimate
    success_criteria: list[str]
    risks: list[str] = Field(default_factory=list)
    tier: Literal["small", "medium", "large"]


# ── Objection Handling ─────────────────────────────────────────────────────


class Evidence(BaseModel):
    """A piece of evidence supporting an objection response.

    Attributes:
        claim: The specific claim being supported.
        source_doc: Knowledge base document or source for this evidence.
        confidence: How strongly the evidence supports the claim (0.0 to 1.0).
    """

    claim: str
    source_doc: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ObjectionResponse(BaseModel):
    """Structured response to a technical objection or competitive challenge.

    Attributes:
        response: The narrative response addressing the objection.
        evidence: Supporting evidence from the knowledge base.
        recommended_followup: Suggested next step after delivering the response.
        competitor_name: Name of the competitor being addressed, if applicable.
            Empty string for non-competitive objections.
    """

    response: str
    evidence: list[Evidence]
    recommended_followup: str
    competitor_name: str = ""


# ── Inter-Agent Handoff Payloads ───────────────────────────────────────────


class TechnicalQuestionPayload(BaseModel):
    """Payload sent from Sales Agent to SA agent requesting technical input.

    Attributes:
        question: The technical question from the prospect or sales rep.
        deal_id: Deal/opportunity identifier for context lookup.
        prospect_tech_stack: Known technologies in the prospect's environment.
            None if unknown.
        context_chunks: Pre-retrieved knowledge base chunks for RAG context.
    """

    question: str
    deal_id: str
    prospect_tech_stack: str | None = None
    context_chunks: list[str] = Field(default_factory=list)


class TechnicalAnswerPayload(BaseModel):
    """Payload returned from SA agent to Sales Agent with technical response.

    Attributes:
        answer: The technical answer in sales-ready language.
        evidence: Source document references supporting the answer.
        architecture_diagram_url: URL to a generated architecture diagram,
            if one was produced. None otherwise.
        related_docs: Paths or IDs of related knowledge base documents.
        confidence: SA agent's confidence in the answer (0.0 to 1.0).
    """

    answer: str
    evidence: list[str] = Field(default_factory=list)
    architecture_diagram_url: str | None = None
    related_docs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


__all__ = [
    "TechRequirement",
    "TechnicalRequirementsDoc",
    "IntegrationPoint",
    "ArchitectureNarrative",
    "POCDeliverable",
    "ResourceEstimate",
    "POCPlan",
    "Evidence",
    "ObjectionResponse",
    "TechnicalQuestionPayload",
    "TechnicalAnswerPayload",
]
