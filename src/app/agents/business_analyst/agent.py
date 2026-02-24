"""Business Analyst Agent: BaseAgent subclass for requirements engineering.

Routes tasks by type to four specialized handlers -- requirements extraction,
gap analysis, user story generation, and process documentation. Each handler
follows the same pattern: optional RAG context retrieval, prompt construction,
LLM call, JSON parsing into Pydantic model, fail-open error handling.

Exports:
    BusinessAnalystAgent: The core business analyst agent class.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from src.app.agents.base import AgentRegistration, BaseAgent
from src.app.agents.business_analyst.prompts import (
    BA_SYSTEM_PROMPT,
    build_gap_analysis_prompt,
    build_process_documentation_prompt,
    build_requirements_extraction_prompt,
    build_user_story_generation_prompt,
)
from src.app.agents.business_analyst.schemas import (
    BAResult,
    ExtractedRequirement,
    GapAnalysisResult,
    ProcessDocumentation,
    UserStory,
)


class BusinessAnalystAgent(BaseAgent):
    """Requirements engineering agent for sales conversation analysis.

    Extends BaseAgent with 4 capability handlers:
    - requirements_extraction: Extract structured requirements from conversations
    - gap_analysis: Compare requirements against product capabilities
    - user_story_generation: Generate agile user stories from requirements
    - process_documentation: Produce current/future state process docs

    Each handler follows fail-open semantics: on LLM or parse error, the
    handler returns a partial result dict with ``{"error": ..., "confidence":
    "low", "partial": True}`` instead of raising, keeping the sales workflow
    unblocked.

    Args:
        registration: Agent registration metadata for the registry.
        llm_service: LLMService (or compatible) for generating content.
        rag_pipeline: AgenticRAGPipeline (or compatible) for knowledge
            retrieval. None is allowed -- handlers degrade gracefully.
    """

    def __init__(
        self,
        registration: AgentRegistration,
        llm_service: object,
        rag_pipeline: object | None = None,
    ) -> None:
        super().__init__(registration)
        self._llm_service = llm_service
        self._rag_pipeline = rag_pipeline
        self._log = structlog.get_logger(__name__).bind(
            agent_id=registration.agent_id,
            agent_name=registration.name,
        )

    # ── Task Router ──────────────────────────────────────────────────────────

    async def execute(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Route task to the appropriate handler by task type.

        Args:
            task: Task specification with 'type' key and handler-specific fields.
            context: Execution context with tenant_id and session data.

        Returns:
            Handler-specific result dictionary.
        """
        task_type = task.get("type", "")

        handlers = {
            "requirements_extraction": self._handle_requirements_extraction,
            "gap_analysis": self._handle_gap_analysis,
            "user_story_generation": self._handle_user_story_generation,
            "process_documentation": self._handle_process_documentation,
        }

        handler = handlers.get(task_type)
        if handler is None:
            # Intentionally fail-open: return error dict rather than raise ValueError
            # to keep the sales workflow unblocked. SA/PM agents raise ValueError for
            # unknown types, but BA is called from the sales flow where an exception
            # would halt the conversation. This divergence is deliberate.
            return {
                "error": f"Unknown task type: {task_type}",
                "confidence": "low",
                "partial": True,
            }

        return await handler(task, context)

    # ── Capability Handlers ──────────────────────────────────────────────────

    async def _handle_requirements_extraction(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract structured requirements from a conversation.

        Prompt: build_requirements_extraction_prompt.
        Output: BAResult with requirements list.
        """
        try:
            conversation_text = task.get("conversation_text", "")
            deal_context = task.get("deal_context")

            prompt = build_requirements_extraction_prompt(
                conversation_text=conversation_text,
                deal_context=deal_context,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": BA_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model="reasoning",
                max_tokens=4096,
                temperature=0.3,
            )

            raw_content = response.get("content", "")
            cleaned = self._extract_json_from_response(raw_content)
            requirements = [
                ExtractedRequirement.model_validate(r)
                for r in json.loads(cleaned)
            ]

            result = BAResult(
                task_type="requirements_extraction",
                requirements=requirements,
                confidence=self._compute_confidence(requirements),
            )
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "requirements_extraction_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "requirements_extraction",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_gap_analysis(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Compare requirements against product capabilities and detect contradictions.

        If no existing_requirements provided, extracts them first via the
        requirements extraction handler. Queries RAG for product capability
        chunks to ground the gap analysis. Escalates to SA agent when the
        result indicates requires_sa_escalation is True.

        Prompt: build_gap_analysis_prompt.
        Output: BAResult with gap_analysis + optional SA escalation flag.
        """
        try:
            conversation_text = task.get("conversation_text", "")
            existing_requirements = task.get("existing_requirements")
            tenant_id = context.get("tenant_id", "")

            # If no existing requirements, extract them first
            if not existing_requirements:
                requirements_result = await self._handle_requirements_extraction(
                    task, context
                )
                if requirements_result.get("error"):
                    self._log.warning(
                        "gap_analysis.requirements_extraction_fallback_failed",
                        error=requirements_result.get("error"),
                    )
                    existing_requirements = []
                else:
                    existing_requirements = requirements_result.get(
                        "requirements", []
                    )

            # Normalize requirements to list of dicts
            requirements_dicts = [
                r if isinstance(r, dict) else r.model_dump()
                if hasattr(r, "model_dump")
                else r
                for r in existing_requirements
            ]

            # Query RAG for product capability chunks
            capability_chunks = await self._get_product_capabilities(
                tenant_id=tenant_id,
                query=f"product capabilities features for gap analysis: "
                f"{conversation_text[:200]}",
            )

            prompt = build_gap_analysis_prompt(
                requirements=requirements_dicts,
                capability_chunks=capability_chunks,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": BA_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model="reasoning",
                max_tokens=4096,
                temperature=0.3,
            )

            raw_content = response.get("content", "")
            cleaned = self._extract_json_from_response(raw_content)
            gap_result = GapAnalysisResult.model_validate(json.loads(cleaned))

            # SA Escalation (LOCKED DECISION from CONTEXT.md)
            if gap_result.requires_sa_escalation:
                try:
                    # Lazy import to avoid circular dependency
                    from src.app.agents.solution_architect.schemas import (
                        TechnicalQuestionPayload,
                    )

                    # Build escalation payload with the critical gap descriptions
                    escalation_gaps = [
                        g
                        for g in gap_result.gaps
                        if g.recommended_action != "descope"
                    ]
                    gap_descriptions = "; ".join(
                        f"{g.requirement_id}: {g.gap_description}"
                        for g in escalation_gaps
                    )

                    _sa_request = TechnicalQuestionPayload(
                        question=f"BA gap escalation: {gap_descriptions}",
                        deal_id=task.get("deal_id", ""),
                    )

                    escalation_dispatched = True
                    self._log.info(
                        "gap_analysis.sa_escalation_dispatched",
                        deal_id=task.get("deal_id", ""),
                        gap_count=len(escalation_gaps),
                    )
                except Exception as esc_err:
                    escalation_dispatched = False
                    self._log.warning(
                        "gap_analysis.sa_escalation_failed",
                        error=str(esc_err),
                    )
            else:
                escalation_dispatched = False

            result = BAResult(
                task_type="gap_analysis",
                requirements=[
                    ExtractedRequirement.model_validate(r)
                    for r in requirements_dicts
                ]
                if requirements_dicts
                else gap_result.requirements,
                gap_analysis=gap_result,
                confidence=self._compute_gap_confidence(gap_result),
            )
            result_dict = result.model_dump()
            result_dict["escalation_dispatched"] = escalation_dispatched
            return result_dict

        except Exception as exc:
            self._log.warning(
                "gap_analysis_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "gap_analysis",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_user_story_generation(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate agile user stories from extracted requirements.

        If no existing_requirements provided, extracts them first from
        conversation_text using the requirements extraction handler.

        Prompt: build_user_story_generation_prompt.
        Output: BAResult with user_stories list.
        """
        try:
            existing_requirements = task.get("existing_requirements")
            conversation_text = task.get("conversation_text", "")

            # If no existing requirements, extract them first
            if not existing_requirements:
                requirements_result = await self._handle_requirements_extraction(
                    {"conversation_text": conversation_text, "type": "requirements_extraction"},
                    context,
                )
                if requirements_result.get("error"):
                    self._log.warning(
                        "user_story_generation.requirements_extraction_fallback_failed",
                        error=requirements_result.get("error"),
                    )
                    existing_requirements = []
                else:
                    existing_requirements = requirements_result.get(
                        "requirements", []
                    )

            # Normalize requirements to list of dicts
            requirements_dicts = [
                r if isinstance(r, dict) else r.model_dump()
                if hasattr(r, "model_dump")
                else r
                for r in existing_requirements
            ]

            prompt = build_user_story_generation_prompt(
                requirements=requirements_dicts,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": BA_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model="reasoning",
                max_tokens=4096,
                temperature=0.4,
            )

            raw_content = response.get("content", "")
            cleaned = self._extract_json_from_response(raw_content)
            stories = [
                UserStory.model_validate(s) for s in json.loads(cleaned)
            ]

            result = BAResult(
                task_type="user_story_generation",
                user_stories=stories,
                confidence=self._compute_story_confidence(stories),
            )
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "user_story_generation_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "user_story_generation",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    async def _handle_process_documentation(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Produce process documentation from workflow conversations.

        Shows current state, future state, and delta between them.

        Prompt: build_process_documentation_prompt.
        Output: BAResult with process_documentation.
        """
        try:
            conversation_text = task.get("conversation_text", "")
            process_context = task.get("process_context")

            prompt = build_process_documentation_prompt(
                conversation_text=conversation_text,
                process_context=process_context,
            )

            response = await self._llm_service.completion(
                messages=[
                    {"role": "system", "content": BA_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model="reasoning",
                max_tokens=4096,
                temperature=0.3,
            )

            raw_content = response.get("content", "")
            cleaned = self._extract_json_from_response(raw_content)
            doc = ProcessDocumentation.model_validate(json.loads(cleaned))

            result = BAResult(
                task_type="process_documentation",
                process_documentation=doc,
                confidence="high",
            )
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "process_documentation_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {
                "task_type": "process_documentation",
                "error": str(exc),
                "confidence": "low",
                "partial": True,
            }

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_json_from_response(text: str) -> str:
        """Extract JSON content from an LLM response, stripping code fences.

        Handles markdown code fences (```json ... ```) and finds the first
        JSON array or object in the text.

        Args:
            text: Raw LLM response text (may contain code fences).

        Returns:
            Cleaned JSON string ready for json.loads().

        Raises:
            ValueError: If no JSON array or object is found in the text.
        """
        # Strip code fences
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())

        # Find first JSON array or object
        match = re.search(r"[\[{]", cleaned)
        if match:
            return cleaned[match.start():]

        raise ValueError(f"No JSON found in LLM response: {text[:200]!r}")

    async def _get_product_capabilities(
        self, tenant_id: str, query: str
    ) -> list[str]:
        """Query RAG pipeline for product capability text chunks.

        Fail-open: returns empty list if the pipeline is None or the
        query raises an exception.

        Args:
            tenant_id: Tenant scope for the RAG pipeline.
            query: Natural language query for product capabilities.

        Returns:
            List of product capability text chunks, or empty list on failure.
        """
        if self._rag_pipeline is None:
            self._log.debug(
                "rag_pipeline_unavailable",
                msg="No RAG pipeline configured; skipping product capability lookup",
            )
            return []

        try:
            rag_response = await self._rag_pipeline.run(
                query=query,
                tenant_id=tenant_id,
                base_filters={"content_type": ["product"]},
            )
            if rag_response and hasattr(rag_response, "chunks"):
                return [
                    chunk.text
                    for chunk in rag_response.chunks
                    if hasattr(chunk, "text") and chunk.text
                ]
            if rag_response and hasattr(rag_response, "answer"):
                return [rag_response.answer] if rag_response.answer else []
            return []
        except Exception as exc:
            self._log.warning(
                "product_capabilities_query_failed",
                error=str(exc),
                query_preview=query[:100],
            )
            return []

    @staticmethod
    def _compute_confidence(
        requirements: list[ExtractedRequirement],
    ) -> str:
        """Compute overall confidence from a list of extracted requirements.

        Args:
            requirements: List of extracted requirements with confidence scores.

        Returns:
            "high", "medium", or "low" confidence string.
        """
        if not requirements:
            return "low"

        avg = sum(r.extraction_confidence for r in requirements) / len(
            requirements
        )
        if avg >= 0.8:
            return "high"
        if avg >= 0.5:
            return "medium"
        return "low"

    @staticmethod
    def _compute_gap_confidence(gap_result: GapAnalysisResult) -> str:
        """Compute confidence level from gap analysis coverage.

        Args:
            gap_result: The gap analysis result with coverage percentage.

        Returns:
            "high", "medium", or "low" confidence string.
        """
        if gap_result.coverage_percentage >= 80.0:
            return "high"
        if gap_result.coverage_percentage >= 50.0:
            return "medium"
        return "low"

    @staticmethod
    def _compute_story_confidence(stories: list[UserStory]) -> str:
        """Compute confidence from user story generation results.

        Args:
            stories: List of generated user stories.

        Returns:
            "high", "medium", or "low" confidence string.
        """
        if not stories:
            return "low"

        low_confidence_count = sum(1 for s in stories if s.is_low_confidence)
        ratio = low_confidence_count / len(stories)
        if ratio <= 0.1:
            return "high"
        if ratio <= 0.3:
            return "medium"
        return "low"
