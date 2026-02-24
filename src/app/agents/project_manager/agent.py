"""Project Manager Agent: BaseAgent subclass for project lifecycle management.

Routes tasks by type to six specialized handlers -- project plan creation,
risk detection, plan adjustment, status report generation, CRM record writing,
and trigger event processing. Each handler follows the same pattern: RAG context
retrieval, prompt construction, LLM call, JSON parsing into Pydantic model,
fail-open error handling. Status reports use pure Python earned value calculation
before the LLM call. Risk detection auto-chains to plan adjustment and
notification dispatch for high/critical severity risks.

Exports:
    ProjectManagerAgent: The core project manager agent class.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from src.app.agents.base import AgentRegistration, BaseAgent
from src.app.agents.project_manager.earned_value import calculate_earned_value
from src.app.agents.project_manager.prompts import (
    build_adjust_plan_prompt,
    build_create_plan_prompt,
    build_detect_risks_prompt,
    build_external_report_prompt,
    build_internal_report_prompt,
    build_process_trigger_prompt,
)
from src.app.agents.project_manager.schemas import (
    ExternalStatusReport,
    InternalStatusReport,
    ProjectPlan,
    ScopeChangeDelta,
    WBSTask,
)

logger = structlog.get_logger(__name__)


class ProjectManagerAgent(BaseAgent):
    """Project lifecycle management agent handling planning, risk, and reporting.

    Extends BaseAgent with 7 capability handlers:
    - create_project_plan: Generate PMBOK-compliant 3-level WBS project plans
    - detect_risks: Analyse milestone progress and flag schedule delays
    - adjust_plan: Produce scope change delta reports for plan adjustments
    - generate_status_report: Generate internal/external status reports with EV
    - write_crm_records: Write project data to Notion CRM via NotionPMAdapter
    - process_trigger: Process trigger events to initiate project planning
    - dispatch_scope_change_analysis: Dispatch scope change impact analysis to BA

    Each handler follows fail-open semantics: on LLM or parse error, the
    handler returns a partial result dict with ``{"error": ..., "confidence":
    "low", "partial": True}`` instead of raising, keeping the workflow
    unblocked.

    Args:
        registration: Agent registration metadata for the registry.
        llm_service: LLMService (or compatible) for generating content.
        rag_pipeline: AgenticRAGPipeline (or compatible) for knowledge
            retrieval. None is allowed -- handlers degrade gracefully.
        notion_pm: NotionPMAdapter (or compatible) for CRM operations.
            None is allowed -- CRM writes are skipped gracefully.
        gmail_service: GmailService (or compatible) for email dispatch.
            None is allowed -- email delivery is skipped gracefully.
    """

    def __init__(
        self,
        registration: AgentRegistration,
        llm_service: object,
        rag_pipeline: object | None = None,
        notion_pm: object | None = None,
        gmail_service: object | None = None,
    ) -> None:
        super().__init__(registration)
        self._llm_service = llm_service
        self._rag_pipeline = rag_pipeline
        self._notion_pm = notion_pm
        self._gmail_service = gmail_service
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
            "create_project_plan": self._handle_create_project_plan,
            "detect_risks": self._handle_detect_risks,
            "adjust_plan": self._handle_adjust_plan,
            "generate_status_report": self._handle_generate_status_report,
            "write_crm_records": self._handle_write_crm_records,
            "process_trigger": self._handle_process_trigger,
            "dispatch_scope_change_analysis": self._handle_dispatch_scope_change_analysis,
        }

        handler = handlers.get(task_type)
        if handler is None:
            raise ValueError(
                f"Unknown task type: {task_type!r}. "
                f"Supported: {', '.join(handlers.keys())}"
            )

        return await handler(task, context)

    # ── Capability Handlers ──────────────────────────────────────────────────

    async def _handle_create_project_plan(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a PMBOK-compliant 3-level WBS project plan.

        RAG query: methodology/product content for grounding.
        Prompt: build_create_plan_prompt.
        Output: ProjectPlan-shaped dict.
        """
        try:
            tenant_id = context.get("tenant_id", "")
            deliverables = task.get("deliverables", [])
            deal_context = task.get("deal_context", {})
            sa_artifacts = task.get("sa_artifacts", "")
            timeline = task.get("timeline", "")

            rag_context = await self._query_rag(
                query=f"project planning methodology for: {', '.join(deliverables[:5])}",
                tenant_id=tenant_id,
                content_types=["methodology", "product"],
            )

            messages = build_create_plan_prompt(
                deliverables=deliverables,
                deal_context=deal_context,
                sa_artifacts=sa_artifacts,
                timeline=timeline,
                rag_context=rag_context,
            )

            response = await self._llm_service.completion(
                messages=messages,
                model="reasoning",
                max_tokens=4096,
                temperature=0.3,
            )

            raw_content = response.get("content", "")
            result = self._parse_llm_json(raw_content, ProjectPlan)
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "create_project_plan_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    async def _handle_detect_risks(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Detect risk signals from plan and progress data.

        RAG query: methodology content for risk assessment grounding.
        Prompt: build_detect_risks_prompt.
        Output: Dict with risks list, risk_count, and auto_adjustments.

        For high/critical severity risks, auto-chains to _handle_adjust_plan
        and dispatches notifications (CRM write + email) with NO human
        approval gate.
        """
        try:
            tenant_id = context.get("tenant_id", "")
            plan_json = task.get("plan_json", "{}")
            current_progress = task.get("current_progress", "")
            deal_context = task.get("deal_context", {})

            rag_context = await self._query_rag(
                query="project risk detection milestone analysis",
                tenant_id=tenant_id,
                content_types=["methodology"],
            )

            messages = build_detect_risks_prompt(
                plan_json=plan_json,
                current_progress=current_progress,
                deal_context=deal_context,
                rag_context=rag_context,
            )

            response = await self._llm_service.completion(
                messages=messages,
                model="reasoning",
                max_tokens=2048,
                temperature=0.2,
            )

            raw_content = response.get("content", "")
            parsed = self._parse_llm_json_raw(raw_content)
            parsed_risks: list[dict[str, Any]] = parsed.get("risks", [])

            # ── Auto-adjust chain for high/critical risks ────────────────
            auto_adjustments: list[dict[str, Any]] = []
            try:
                for risk in parsed_risks:
                    severity = risk.get("severity", "low")
                    if severity not in ("high", "critical"):
                        continue

                    risk_desc = risk.get("description", "Unknown risk")
                    signal_type = risk.get("signal_type", "unknown")

                    # 1. Auto-adjust plan
                    adjust_task: dict[str, Any] = {
                        "type": "adjust_plan",
                        "original_plan_json": plan_json,
                        "scope_change_description": (
                            f"Auto-risk response ({signal_type}): {risk_desc}"
                        ),
                        "trigger": "manual_input",
                        "deal_context": deal_context,
                    }
                    adjustment_result = await self._handle_adjust_plan(
                        adjust_task, context
                    )
                    auto_adjustments.append({
                        "risk_id": risk.get("risk_id", ""),
                        "severity": severity,
                        "adjustment": adjustment_result,
                    })

                    # 2. CRM write -- append risk log entry
                    if self._notion_pm is not None:
                        try:
                            risk_blocks = [
                                {
                                    "type": "paragraph",
                                    "paragraph": {
                                        "rich_text": [
                                            {
                                                "type": "text",
                                                "text": {
                                                    "content": (
                                                        f"[{severity.upper()}] "
                                                        f"{signal_type}: {risk_desc}"
                                                    )
                                                },
                                            }
                                        ],
                                    },
                                }
                            ]
                            page_id = deal_context.get("risk_log_page_id", "")
                            if page_id:
                                await self._notion_pm.append_risk_log_entry(
                                    page_id=page_id,
                                    risk_blocks=risk_blocks,
                                )
                        except Exception as crm_exc:
                            self._log.warning(
                                "auto_risk_crm_write_failed",
                                risk_id=risk.get("risk_id"),
                                error=str(crm_exc),
                            )

                    # 3. Email notification
                    if self._gmail_service is not None:
                        try:
                            stakeholders = deal_context.get("stakeholders", [])
                            if stakeholders:
                                subject = (
                                    f"[{severity.upper()} RISK] {signal_type}: "
                                    f"Auto-adjustment applied"
                                )
                                body = (
                                    f"Risk detected: {risk_desc}\n\n"
                                    f"Severity: {severity}\n"
                                    f"Signal type: {signal_type}\n\n"
                                    f"An automatic plan adjustment has been applied.\n"
                                    f"Please review the updated project plan."
                                )
                                await self._gmail_service.send_email(
                                    to=stakeholders,
                                    subject=subject,
                                    body=body,
                                )
                        except Exception as email_exc:
                            self._log.warning(
                                "auto_risk_email_failed",
                                risk_id=risk.get("risk_id"),
                                error=str(email_exc),
                            )

            except Exception as chain_exc:
                self._log.warning(
                    "auto_adjust_chain_failed",
                    error=str(chain_exc),
                    error_type=type(chain_exc).__name__,
                )

            return {
                "risks": parsed_risks,
                "risk_count": len(parsed_risks),
                "auto_adjustments": auto_adjustments,
            }

        except Exception as exc:
            self._log.warning(
                "detect_risks_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    async def _handle_adjust_plan(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Produce a scope change delta report for plan adjustment.

        RAG query: methodology content for scope change assessment.
        Prompt: build_adjust_plan_prompt.
        Output: ScopeChangeDelta-shaped dict.
        """
        try:
            tenant_id = context.get("tenant_id", "")
            original_plan_json = task.get("original_plan_json", "{}")
            scope_change_description = task.get("scope_change_description", "")
            trigger = task.get("trigger", "manual_input")
            deal_context = task.get("deal_context", {})

            rag_context = await self._query_rag(
                query=f"scope change management impact analysis: {scope_change_description[:200]}",
                tenant_id=tenant_id,
                content_types=["methodology"],
            )

            messages = build_adjust_plan_prompt(
                original_plan_json=original_plan_json,
                scope_change_description=scope_change_description,
                trigger=trigger,
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
            result = self._parse_llm_json(raw_content, ScopeChangeDelta)
            return result.model_dump()

        except Exception as exc:
            self._log.warning(
                "adjust_plan_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    async def _handle_generate_status_report(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate an internal or external status report.

        CRITICAL: Earned value metrics are computed by pure Python FIRST
        (via calculate_earned_value), then serialized into the prompt.
        The LLM must NOT recalculate EV metrics.

        After successful report generation, dispatches email to stakeholders
        via gmail_service. Email failure does NOT fail report generation.
        """
        try:
            tenant_id = context.get("tenant_id", "")
            plan_json = task.get("plan_json", "{}")
            progress_data = task.get("progress_data", "{}")
            deal_context = task.get("deal_context", {})
            sa_summary = task.get("sa_summary", "")
            report_type = task.get("report_type", "internal")
            project_name = task.get("project_name", "")

            rag_context = await self._query_rag(
                query="project status reporting best practices",
                tenant_id=tenant_id,
                content_types=["methodology"],
            )

            if report_type == "internal":
                # ── CRITICAL: Calculate EV with pure Python ──────────
                tasks_for_ev = self._extract_tasks_from_plan_json(plan_json)
                progress_dict = (
                    json.loads(progress_data)
                    if isinstance(progress_data, str)
                    else progress_data
                )
                actual_days_spent = float(
                    progress_dict.get("actual_days_spent", 0.0)
                )
                scheduled_completion_pct = float(
                    progress_dict.get("scheduled_completion_pct", 0.0)
                )

                ev_metrics = calculate_earned_value(
                    tasks=tasks_for_ev,
                    actual_days_spent=actual_days_spent,
                    scheduled_completion_pct=scheduled_completion_pct,
                )
                earned_value_json = json.dumps(ev_metrics.model_dump())

                risk_log = progress_dict.get("risk_log", "[]")
                if isinstance(risk_log, list):
                    risk_log = json.dumps(risk_log)

                messages = build_internal_report_prompt(
                    plan_json=plan_json,
                    progress_data=(
                        progress_data
                        if isinstance(progress_data, str)
                        else json.dumps(progress_data)
                    ),
                    risk_log=risk_log,
                    earned_value_json=earned_value_json,
                    deal_context=deal_context,
                    sa_summary=sa_summary,
                    rag_context=rag_context,
                )

                response = await self._llm_service.completion(
                    messages=messages,
                    model="reasoning",
                    max_tokens=4096,
                    temperature=0.3,
                )

                raw_content = response.get("content", "")
                result = self._parse_llm_json(raw_content, InternalStatusReport)
                report_dict = result.model_dump()

            else:
                # External report
                if not project_name:
                    project_name = deal_context.get("project_name", "Project")

                messages = build_external_report_prompt(
                    plan_json=plan_json,
                    progress_data=(
                        progress_data
                        if isinstance(progress_data, str)
                        else json.dumps(progress_data)
                    ),
                    project_name=project_name,
                    rag_context=rag_context,
                )

                response = await self._llm_service.completion(
                    messages=messages,
                    model="reasoning",
                    max_tokens=4096,
                    temperature=0.3,
                )

                raw_content = response.get("content", "")
                result = self._parse_llm_json(raw_content, ExternalStatusReport)
                report_dict = result.model_dump()

            # ── Email delivery ───────────────────────────────────────
            try:
                stakeholders = deal_context.get("stakeholders", [])
                if self._gmail_service is not None and stakeholders:
                    if not project_name:
                        project_name = deal_context.get("project_name", "Project")
                    subject = f"Project Status Report: {project_name}"
                    body = self._format_report_email_body(report_dict, report_type)
                    await self._gmail_service.send_email(
                        to=stakeholders,
                        subject=subject,
                        body=body,
                    )
                    self._log.info(
                        "status_report_emailed",
                        recipients=len(stakeholders),
                        report_type=report_type,
                    )
                elif self._gmail_service is None:
                    self._log.warning(
                        "status_report_email_skipped",
                        reason="gmail_service not configured",
                    )
            except Exception as email_exc:
                self._log.warning(
                    "status_report_email_failed",
                    error=str(email_exc),
                    error_type=type(email_exc).__name__,
                )

            return report_dict

        except Exception as exc:
            self._log.warning(
                "generate_status_report_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    async def _handle_write_crm_records(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Write project data to Notion CRM via NotionPMAdapter.

        Routes to the appropriate adapter method based on the operation field.
        Supported operations: create_project, update_metrics, append_report,
        append_risk, append_change, append_milestone.
        """
        try:
            operation = task.get("operation", "")

            if self._notion_pm is None:
                return {
                    "error": "NotionPM adapter not configured",
                    "partial": True,
                }

            if operation == "create_project":
                data = task.get("data", {})
                page_id = await self._notion_pm.create_project_record(data)
                return {"status": "written", "operation": operation, "page_id": page_id}

            elif operation == "update_metrics":
                page_id = task.get("page_id", "")
                metrics = task.get("metrics", {})
                await self._notion_pm.update_project_metrics(page_id, metrics)
                return {"status": "written", "operation": operation}

            elif operation == "append_report":
                page_id = task.get("page_id", "")
                blocks = task.get("blocks", [])
                await self._notion_pm.append_status_report(page_id, blocks)
                return {"status": "written", "operation": operation}

            elif operation == "append_risk":
                page_id = task.get("page_id", "")
                blocks = task.get("blocks", [])
                await self._notion_pm.append_risk_log_entry(page_id, blocks)
                return {"status": "written", "operation": operation}

            elif operation == "append_change":
                page_id = task.get("page_id", "")
                blocks = task.get("blocks", [])
                await self._notion_pm.append_change_request(page_id, blocks)
                return {"status": "written", "operation": operation}

            elif operation == "append_milestone":
                page_id = task.get("page_id", "")
                milestone_blocks = task.get("milestone_blocks", [])
                await self._notion_pm.append_milestone_event(page_id, milestone_blocks)
                return {"status": "written", "operation": operation}

            else:
                return {
                    "error": f"Unknown CRM operation: {operation!r}. "
                    f"Supported: create_project, update_metrics, "
                    f"append_report, append_risk, append_change, "
                    f"append_milestone",
                    "partial": True,
                }

        except Exception as exc:
            self._log.warning(
                "write_crm_records_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                operation=task.get("operation"),
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    async def _handle_process_trigger(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Process a trigger event to determine project planning parameters.

        RAG query: deal context for enrichment.
        Prompt: build_process_trigger_prompt.
        If trigger analysis recommends creating a plan, chains to
        _handle_create_project_plan internally.
        """
        try:
            tenant_id = context.get("tenant_id", "")
            trigger_type = task.get("trigger_type", "manual")
            deal_id = task.get("deal_id", "")
            deliverables = task.get("deliverables", [])
            sa_artifacts = task.get("sa_artifacts", "")

            rag_context = await self._query_rag(
                query=f"project planning methodology for deal {deal_id}",
                tenant_id=tenant_id,
                content_types=["methodology", "product"],
            )

            deal_context = task.get("deal_context", {})

            messages = build_process_trigger_prompt(
                trigger_type=trigger_type,
                deal_context=deal_context,
                deliverables=deliverables,
                sa_artifacts=sa_artifacts,
                rag_context=rag_context,
            )

            response = await self._llm_service.completion(
                messages=messages,
                model="reasoning",
                max_tokens=2048,
                temperature=0.3,
            )

            raw_content = response.get("content", "")
            trigger_analysis = self._parse_llm_json_raw(raw_content)

            # If analysis recommends creating a plan, chain internally
            plan_result: dict[str, Any] | None = None
            if trigger_analysis.get("priority") in ("high", "medium"):
                plan_task: dict[str, Any] = {
                    "type": "create_project_plan",
                    "deliverables": deliverables,
                    "deal_context": deal_context,
                    "sa_artifacts": sa_artifacts,
                    "timeline": (
                        f"{trigger_analysis.get('estimated_duration_weeks', 8)} weeks"
                    ),
                }
                plan_result = await self._handle_create_project_plan(
                    plan_task, context
                )

            return {
                "trigger_processed": True,
                "trigger_type": trigger_type,
                "analysis": trigger_analysis,
                "plan": plan_result,
            }

        except Exception as exc:
            self._log.warning(
                "process_trigger_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": str(exc), "confidence": "low", "partial": True}

    async def _handle_dispatch_scope_change_analysis(
        self, task: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Dispatch scope change impact analysis to the Business Analyst agent.

        When a scope change occurs on a project, the PM asks the BA to
        analyze the impact on requirements. Uses lazy import pattern.
        """
        conversation_text = task.get("conversation_text", "")
        deal_id = task.get("deal_id", "")

        if not conversation_text or not deal_id:
            return {
                "status": "failed",
                "error": "conversation_text and deal_id are required for scope change analysis",
            }

        # Lazy import to avoid circular dependency
        from src.app.agents.business_analyst.schemas import BAHandoffRequest

        request = BAHandoffRequest(
            conversation_text=conversation_text,
            deal_id=deal_id,
            tenant_id=context.get("tenant_id", ""),
            analysis_scope="gap_only",  # Scope changes need gap analysis
        )

        handoff_task = {
            "type": "gap_analysis",
            "conversation_text": conversation_text,
            "deal_id": deal_id,
            "existing_requirements": task.get("existing_requirements", []),
        }

        self._log.info(
            "scope_change_analysis_dispatched",
            deal_id=deal_id,
            tenant_id=context.get("tenant_id", ""),
        )

        return {
            "status": "dispatched",
            "handoff_task": handoff_task,
            "payload": request.model_dump_json(),
            "target_agent_id": "business_analyst",
        }

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

    @staticmethod
    def _parse_llm_json_raw(raw: str) -> dict[str, Any]:
        """Parse LLM response text as raw JSON dict (no Pydantic validation).

        Used for responses where the schema is flexible (e.g., risk lists,
        trigger analysis) and strict model validation is not required.

        Args:
            raw: Raw LLM response text (may contain code fences).

        Returns:
            Parsed JSON as a dictionary.

        Raises:
            json.JSONDecodeError: If the text is not valid JSON after stripping.
        """
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())
        return json.loads(cleaned)

    @staticmethod
    def _extract_tasks_from_plan_json(plan_json: str) -> list[WBSTask]:
        """Extract flat list of WBSTask models from plan JSON string.

        Walks the phases -> milestones -> tasks hierarchy and returns all
        tasks as WBSTask instances for earned value calculation.

        Args:
            plan_json: JSON string of a ProjectPlan.

        Returns:
            List of WBSTask instances. Empty list on parse failure.
        """
        try:
            plan_data = json.loads(plan_json) if isinstance(plan_json, str) else plan_json
            tasks: list[WBSTask] = []
            for phase in plan_data.get("phases", []):
                for milestone in phase.get("milestones", []):
                    for task_data in milestone.get("tasks", []):
                        try:
                            tasks.append(WBSTask.model_validate(task_data))
                        except Exception:
                            continue
            return tasks
        except Exception:
            return []

    @staticmethod
    def _format_report_email_body(
        report_dict: dict[str, Any], report_type: str
    ) -> str:
        """Format a status report dict into plain-text email body.

        Args:
            report_dict: Serialized status report dict.
            report_type: "internal" or "external".

        Returns:
            Plain-text email body string.
        """
        lines: list[str] = []

        if report_type == "internal":
            lines.append(f"Overall RAG: {report_dict.get('overall_rag', 'N/A').upper()}")
            lines.append("")

            # Milestone progress
            for mp in report_dict.get("milestone_progress", []):
                lines.append(
                    f"- {mp.get('name', 'N/A')}: "
                    f"{mp.get('pct_complete', 0):.0f}% complete "
                    f"({mp.get('completed_tasks', 0)}/{mp.get('total_tasks', 0)} tasks)"
                )

            # Earned value
            ev = report_dict.get("earned_value", {})
            if ev:
                lines.append("")
                lines.append(
                    f"Earned Value: CPI={ev.get('cpi', 0):.2f}, "
                    f"SPI={ev.get('spi', 0):.2f}"
                )

            # Agent notes
            notes = report_dict.get("agent_notes", "")
            if notes:
                lines.append("")
                lines.append(f"PM Notes: {notes}")

        else:
            lines.append(
                f"Overall Status: {report_dict.get('overall_status', 'N/A')}"
            )
            lines.append("")

            for ms in report_dict.get("milestone_summary", []):
                lines.append(
                    f"- {ms.get('name', 'N/A')}: {ms.get('status', 'N/A')} "
                    f"(Est: {ms.get('estimated_completion', 'N/A')})"
                )

            accomplishments = report_dict.get("key_accomplishments", [])
            if accomplishments:
                lines.append("")
                lines.append("Key Accomplishments:")
                for item in accomplishments:
                    lines.append(f"  - {item}")

        return "\n".join(lines)
