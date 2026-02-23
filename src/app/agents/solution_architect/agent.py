"""Solution Architect Agent: BaseAgent subclass for technical pre-sales.

Routes tasks by type to five specialized handlers -- requirements extraction,
architecture narrative generation, POC scoping, objection response, and
technical handoff. Each handler follows the same pattern: RAG context retrieval,
prompt construction, LLM call, JSON parsing into Pydantic model, fail-open
error handling.

Exports:
    SolutionArchitectAgent: The core solution architect agent class.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from src.app.agents.base import AgentRegistration, BaseAgent
from src.app.agents.solution_architect.prompts import (
    build_architecture_narrative_prompt,
    build_objection_response_prompt,
    build_poc_scoping_prompt,
    build_requirements_extraction_prompt,
    build_technical_handoff_prompt,
)
from src.app.agents.solution_architect.schemas import (
    ArchitectureNarrative,
    ObjectionResponse,
    POCPlan,
    TechnicalAnswerPayload,
    TechnicalRequirementsDoc,
)

logger = structlog.get_logger(__name__)


class SolutionArchitectAgent(BaseAgent):
    """Technical pre-sales agent handling architecture and solution scoping.

    Extends BaseAgent with 5 capability handlers:
    - map_requirements: Extract technical requirements from sales transcripts
    - generate_architecture: Generate architecture narratives for prospects
    - scope_poc: Create POC plans with deliverables and resource estimates
    - respond_objection: Craft responses to technical/competitive objections
    - technical_handoff: Answer technical questions from the Sales Agent

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

        Raises:
            ValueError: If task type is unknown.
        """
        task_type = task.get("type", "")

        handlers = {
            "map_requirements": self._handle_map_requirements,
            "generate_architecture": self._handle_generate_architecture,
            "scope_poc": self._handle_scope_poc,
            "respond_objection": self._handle_respond_objection,
            "technical_handoff": self._handle_technical_handoff,
        }

        handler = handlers.get(task_type)
        if handler is None:
            raise ValueError(
                f"Unknown task type: {task_type!r}. "
                f"Supported: {', '.join(handlers.keys())}"
            )

        return await handler(task, context)

    # ── Capability Handlers ──────────────────────────────────────────────────

    async def _handle_map_requirements(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract technical requirements from a sales transcript.

        RAG query: product/methodology content for grounding.
        Prompt: build_requirements_extraction_prompt.
        Output: TechnicalRequirementsDoc-shaped dict.
        """
        try:
            tenant_id = context.get("tenant_id", "")
            transcript = task.get("transcript", "")
            deal_context = task.get("deal_context", {})

            rag_context = await self._query_rag(
                query=f"product features methodology for: {transcript[:200]}",
                tenant_id=tenant_id,
                content_types=["product", "methodology"],
            )

            messages = build_requirements_extraction_prompt(
                transcript=transcript,
                deal_context=deal_context,
                rag_context=rag_context,
            )

            response = await self._llm_service.completion(
                messages=messages,
                model="reasoning",
                max_tokens=4096,
                temperature=0.3,
            )

            raw_content = response.get("content", "")
            result = self._parse_llm_json(raw_content, TechnicalRequirementsDoc)
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "map_requirements_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    async def _handle_generate_architecture(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate an architecture narrative for a prospect.

        RAG query: architecture_template content.
        Prompt: build_architecture_narrative_prompt.
        Output: ArchitectureNarrative-shaped dict.
        """
        try:
            tenant_id = context.get("tenant_id", "")
            tech_stack = task.get("tech_stack", "")
            requirements_json = task.get("requirements_json", "{}")

            rag_context = await self._query_rag(
                query=f"architecture template integration patterns for: {tech_stack}",
                tenant_id=tenant_id,
                content_types=["architecture_template", "product"],
            )

            messages = build_architecture_narrative_prompt(
                tech_stack=tech_stack,
                requirements_json=requirements_json,
                rag_context=rag_context,
            )

            response = await self._llm_service.completion(
                messages=messages,
                model="reasoning",
                max_tokens=4096,
                temperature=0.4,
            )

            raw_content = response.get("content", "")
            result = self._parse_llm_json(raw_content, ArchitectureNarrative)
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "generate_architecture_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    async def _handle_scope_poc(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate a POC plan with deliverables and resource estimates.

        RAG query: poc_template content.
        Prompt: build_poc_scoping_prompt.
        Output: POCPlan-shaped dict.
        """
        try:
            tenant_id = context.get("tenant_id", "")
            requirements_json = task.get("requirements_json", "{}")
            deal_stage = task.get("deal_stage", "evaluation")
            timeline_preference = task.get("timeline_preference", "flexible")

            rag_context = await self._query_rag(
                query="poc template proof of concept planning guidelines",
                tenant_id=tenant_id,
                content_types=["poc_template"],
            )

            messages = build_poc_scoping_prompt(
                requirements_json=requirements_json,
                deal_stage=deal_stage,
                timeline_preference=timeline_preference,
                rag_context=rag_context,
            )

            response = await self._llm_service.completion(
                messages=messages,
                model="reasoning",
                max_tokens=4096,
                temperature=0.3,
            )

            raw_content = response.get("content", "")
            result = self._parse_llm_json(raw_content, POCPlan)
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "scope_poc_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    async def _handle_respond_objection(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Craft a response to a technical or competitive objection.

        RAG query: competitor_analysis + product content.
        Prompt: build_objection_response_prompt.
        Output: ObjectionResponse-shaped dict.
        """
        try:
            tenant_id = context.get("tenant_id", "")
            objection = task.get("objection", "")
            competitor = task.get("competitor", "")
            deal_context = task.get("deal_context", {})

            rag_query = f"competitor analysis product positioning for: {objection[:200]}"
            if competitor:
                rag_query = f"competitor analysis {competitor} battlecard: {objection[:200]}"

            rag_context = await self._query_rag(
                query=rag_query,
                tenant_id=tenant_id,
                content_types=["competitor_analysis", "positioning"],
            )

            messages = build_objection_response_prompt(
                objection=objection,
                competitor=competitor,
                deal_context=deal_context,
                rag_context=rag_context,
            )

            response = await self._llm_service.completion(
                messages=messages,
                model="reasoning",
                max_tokens=2048,
                temperature=0.4,
            )

            raw_content = response.get("content", "")
            result = self._parse_llm_json(raw_content, ObjectionResponse)
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "respond_objection_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    async def _handle_technical_handoff(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Answer a technical question from the Sales Agent.

        RAG query: broad (product + methodology + architecture).
        Prompt: build_technical_handoff_prompt.
        Output: TechnicalAnswerPayload-shaped dict.
        """
        try:
            tenant_id = context.get("tenant_id", "")
            question = task.get("question", "")
            deal_context = task.get("deal_context", {})

            rag_context = await self._query_rag(
                query=f"product methodology architecture: {question[:300]}",
                tenant_id=tenant_id,
                content_types=["product", "architecture_template", "methodology"],
            )

            messages = build_technical_handoff_prompt(
                question=question,
                deal_context=deal_context,
                rag_context=rag_context,
            )

            response = await self._llm_service.completion(
                messages=messages,
                model="reasoning",
                max_tokens=2048,
                temperature=0.3,
            )

            raw_content = response.get("content", "")
            result = self._parse_llm_json(raw_content, TechnicalAnswerPayload)
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "technical_handoff_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _query_rag(
        self,
        query: str,
        tenant_id: str,
        content_types: list[str] | None = None,
    ) -> str:
        """Query the RAG pipeline for knowledge base context.

        Fail-open: returns empty string if the pipeline is None or the
        query raises an exception.

        Args:
            query: Natural language query for the knowledge base.
            tenant_id: Tenant scope for the RAG pipeline.
            content_types: Optional list of content_type values to pre-filter
                results. Forwarded as base_filters to the RAG pipeline.

        Returns:
            RAG answer text, or empty string on failure.
        """
        if self._rag_pipeline is None:
            return ""

        base_filters = {"content_type": content_types} if content_types else None

        try:
            rag_response = await self._rag_pipeline.run(
                query=query,
                tenant_id=tenant_id,
                base_filters=base_filters,
            )
            if rag_response and hasattr(rag_response, "answer"):
                return rag_response.answer or ""
            return ""
        except Exception as exc:
            self._log.warning(
                "rag_query_failed",
                error=str(exc),
                query_preview=query[:100],
            )
            return ""

    @staticmethod
    def _parse_llm_json(raw: str, model_cls: type) -> Any:
        """Parse LLM response text as JSON and validate with a Pydantic model.

        Strips markdown code fences (```json ... ```) before parsing.

        Args:
            raw: Raw LLM response text (may contain code fences).
            model_cls: Pydantic BaseModel subclass to validate against.

        Returns:
            Validated Pydantic model instance.

        Raises:
            json.JSONDecodeError: If the text is not valid JSON after stripping.
            pydantic.ValidationError: If the JSON does not match the model schema.
        """
        # Strip code fences
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())

        parsed = json.loads(cleaned)
        return model_cls.model_validate(parsed)
