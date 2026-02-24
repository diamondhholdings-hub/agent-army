"""Pydantic data models for the Business Analyst agent domain.

Defines all structured types used across the Business Analyst agent:
requirements extraction, gap analysis, user story generation, process
documentation, and inter-agent handoff payloads. These models are the
foundational types that every BA capability handler, prompt builder,
and adapter depends on.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Requirements Extraction ───────────────────────────────────────────────


class ExtractedRequirement(BaseModel):
    """A single requirement extracted from a sales/stakeholder conversation.

    Captures structured requirement data with multi-dimensional classification
    (functional/non-functional/constraint, MoSCoW priority, stakeholder domain)
    and confidence scoring for extraction quality tracking.

    Attributes:
        requirement_id: Unique identifier (e.g., "REQ-001").
        description: Plain-language description of the requirement.
        category: Technical classification of the requirement type.
        moscow_priority: MoSCoW prioritization for backlog management.
        stakeholder_domain: Business domain of the originating stakeholder.
        priority_score: Overall priority ranking for triage.
        extraction_confidence: Model's confidence in extraction accuracy
            (0.0 to 1.0). Defaults to 0.7.
        is_low_confidence: Auto-set to True when extraction_confidence < 0.6.
        source_quote: Verbatim quote from the transcript evidencing this
            requirement. Empty string if no direct quote available.
    """

    requirement_id: str
    description: str
    category: Literal["functional", "non_functional", "constraint"]
    moscow_priority: Literal["must_have", "should_have", "could_have", "wont_have"]
    stakeholder_domain: Literal["sales", "tech", "ops", "finance"]
    priority_score: Literal["high", "med", "low"]
    extraction_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    is_low_confidence: bool = False
    source_quote: str = ""

    @model_validator(mode="after")
    def _set_low_confidence_flag(self) -> ExtractedRequirement:
        """Auto-set is_low_confidence based on extraction_confidence threshold."""
        self.is_low_confidence = self.extraction_confidence < 0.6
        return self


# ── Gap Analysis ──────────────────────────────────────────────────────────


class CapabilityGap(BaseModel):
    """A gap between an extracted requirement and current product capabilities.

    Identifies where the product falls short of a requirement and recommends
    an action path. Gaps with severity=critical and no workaround trigger
    SA escalation.

    Attributes:
        requirement_id: Links back to the ExtractedRequirement this gap
            relates to.
        gap_description: What capability is missing or insufficient.
        severity: Impact severity of the gap on the deal.
        recommended_action: Suggested path to address the gap.
        workaround: Temporary workaround if available, None otherwise.
        requires_sa_escalation: True if this gap needs Solution Architect
            involvement (auto-set for critical gaps without workaround).
    """

    requirement_id: str
    gap_description: str
    severity: Literal["critical", "major", "minor"]
    recommended_action: Literal["build_it", "find_partner", "descope"]
    workaround: str | None = None
    requires_sa_escalation: bool = False


class RequirementContradiction(BaseModel):
    """A detected contradiction between two or more requirements.

    Flags conflicting requirements that need stakeholder resolution before
    implementation can proceed.

    Attributes:
        requirement_ids: The conflicting requirement IDs (minimum 2).
        conflict_description: What the conflict is and why it matters.
        resolution_suggestion: Recommended approach to resolve the conflict.
        severity: Impact severity of the contradiction.
    """

    requirement_ids: list[str] = Field(min_length=2)
    conflict_description: str
    resolution_suggestion: str
    severity: Literal["blocking", "significant", "minor"]


# ── User Stories ──────────────────────────────────────────────────────────


class UserStory(BaseModel):
    """An agile user story generated from extracted requirements.

    Follows the standard "As a / I want / So that" format with acceptance
    criteria, Fibonacci story points, and traceability back to source
    requirements.

    Attributes:
        story_id: Unique identifier (e.g., "US-001").
        as_a: The user role or persona.
        i_want: The desired functionality or capability.
        so_that: The business value or outcome.
        acceptance_criteria: List of testable acceptance criteria (min 1).
        story_points: Fibonacci effort estimate (1, 2, 3, 5, 8, or 13).
        priority: MoSCoW prioritization matching source requirements.
        epic_theme: Grouping theme for backlog organization.
        stakeholder_domain: Business domain this story serves.
        is_low_confidence: True if derived from low-confidence requirements.
        source_requirement_ids: Traceability links to ExtractedRequirement IDs.
    """

    story_id: str
    as_a: str
    i_want: str
    so_that: str
    acceptance_criteria: list[str] = Field(min_length=1)
    story_points: int = Field(ge=1)
    priority: Literal["must_have", "should_have", "could_have", "wont_have"]
    epic_theme: str
    stakeholder_domain: Literal["sales", "tech", "ops", "finance"]
    is_low_confidence: bool = False
    source_requirement_ids: list[str] = Field(default_factory=list)

    @field_validator("story_points")
    @classmethod
    def _validate_fibonacci(cls, v: int) -> int:
        """Ensure story points follow the Fibonacci sequence used in agile."""
        allowed = {1, 2, 3, 5, 8, 13}
        if v not in allowed:
            msg = f"story_points must be a Fibonacci value in {sorted(allowed)}, got {v}"
            raise ValueError(msg)
        return v


# ── Process Documentation ─────────────────────────────────────────────────


class ProcessDocumentation(BaseModel):
    """Current-state and future-state process documentation.

    Describes a business process as-is and to-be, with a delta summary
    highlighting what changes, plus stakeholder identification.

    Attributes:
        process_name: Name of the business process being documented.
        current_state: Narrative description of the current (as-is) process.
        future_state: Narrative description of the future (to-be) process.
        delta: Summary of what changes between current and future state.
        stakeholders: People or roles involved in this process.
        assumptions: Assumptions made during documentation.
    """

    process_name: str
    current_state: str
    future_state: str
    delta: str
    stakeholders: list[str]
    assumptions: list[str] = Field(default_factory=list)


# ── Gap Analysis Result ───────────────────────────────────────────────────


class GapAnalysisResult(BaseModel):
    """Complete gap analysis output combining requirements, gaps, and contradictions.

    Provides a comprehensive assessment of requirement coverage against
    product capabilities, including actionable recommendations for the
    Sales Agent.

    Attributes:
        requirements: The requirements analyzed in this gap analysis.
        gaps: Identified capability gaps.
        contradictions: Detected contradictions between requirements.
        coverage_percentage: Percentage of requirements covered by current
            capabilities (0.0 to 100.0).
        recommended_next_action: Summary action for the Sales Agent.
        requires_sa_escalation: True if any gap needs SA involvement.
    """

    requirements: list[ExtractedRequirement]
    gaps: list[CapabilityGap]
    contradictions: list[RequirementContradiction]
    coverage_percentage: float = Field(ge=0.0, le=100.0)
    recommended_next_action: str
    requires_sa_escalation: bool = False


# ── Task / Result Envelopes ───────────────────────────────────────────────


class BATask(BaseModel):
    """Task envelope dispatched to the BA agent for processing.

    Specifies which BA capability to invoke, the input conversation text,
    and optional context for enrichment.

    Attributes:
        task_type: Which BA capability to execute.
        conversation_text: The source conversation or transcript to analyze.
        deal_id: Associated CRM deal identifier, if applicable.
        tenant_id: Tenant context for multi-tenant isolation.
        existing_requirements: Previously extracted requirements for use
            in user_story_generation (pass-through from prior extraction).
        metadata: Additional context from the triggering event.
    """

    task_type: Literal[
        "requirements_extraction",
        "gap_analysis",
        "user_story_generation",
        "process_documentation",
    ]
    conversation_text: str
    deal_id: str | None = None
    tenant_id: str
    existing_requirements: list[ExtractedRequirement] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BAResult(BaseModel):
    """Result envelope returned by the BA agent after processing.

    Contains outputs from whichever capability was invoked, with error
    handling and confidence metadata. Uses the fail-open pattern: on
    error, returns partial=True with the error field populated.

    Attributes:
        task_type: Which BA capability produced this result.
        requirements: Extracted requirements (populated for requirements_extraction).
        gap_analysis: Gap analysis output (populated for gap_analysis).
        user_stories: Generated user stories (populated for user_story_generation).
        process_documentation: Process docs (populated for process_documentation).
        error: Error message if processing failed, None on success.
        confidence: Overall confidence in the result.
        partial: True if the result is incomplete due to error or timeout.
    """

    task_type: str
    requirements: list[ExtractedRequirement] = Field(default_factory=list)
    gap_analysis: GapAnalysisResult | None = None
    user_stories: list[UserStory] = Field(default_factory=list)
    process_documentation: ProcessDocumentation | None = None
    error: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    partial: bool = False


# ── Inter-Agent Handoff Payloads ──────────────────────────────────────────


class BAHandoffRequest(BaseModel):
    """Handoff request from Sales Agent to BA agent for requirements analysis.

    Sent when the Sales Agent detects a conversation that needs structured
    requirements analysis, gap assessment, user story generation, or
    process documentation.

    Attributes:
        handoff_type: Fixed to "requirements_analysis" for BA handoffs.
        conversation_text: The source conversation to analyze.
        deal_id: Associated CRM deal identifier.
        tenant_id: Tenant context for multi-tenant isolation.
        analysis_scope: Which BA capabilities to invoke.
    """

    handoff_type: Literal["requirements_analysis"] = "requirements_analysis"
    conversation_text: str
    deal_id: str
    tenant_id: str
    analysis_scope: Literal["full", "gap_only", "stories_only", "process_only"] = "full"


class BAHandoffResponse(BaseModel):
    """Handoff response from BA agent back to Sales Agent.

    Returns the structured analysis results for the Sales Agent to
    incorporate into its conversation flow.

    Attributes:
        handoff_type: Fixed to "requirements_analysis" for BA handoffs.
        requirements: Extracted requirements from the conversation.
        gap_analysis: Gap analysis results, if scope included it.
        user_stories: Generated user stories, if scope included it.
        process_documentation: Process docs, if scope included it.
        recommended_next_action: Summary action for the Sales Agent.
        confidence: Overall confidence in the analysis (0.0 to 1.0).
    """

    handoff_type: Literal["requirements_analysis"] = "requirements_analysis"
    requirements: list[ExtractedRequirement] = Field(default_factory=list)
    gap_analysis: GapAnalysisResult | None = None
    user_stories: list[UserStory] = Field(default_factory=list)
    process_documentation: ProcessDocumentation | None = None
    recommended_next_action: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


__all__ = [
    "ExtractedRequirement",
    "CapabilityGap",
    "RequirementContradiction",
    "UserStory",
    "ProcessDocumentation",
    "GapAnalysisResult",
    "BATask",
    "BAResult",
    "BAHandoffRequest",
    "BAHandoffResponse",
]
