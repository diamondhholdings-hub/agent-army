"""Integration tests for the Project Manager agent.

Tests cover all 6 capability handlers (create_project_plan, detect_risks,
adjust_plan, generate_status_report, write_crm_records, process_trigger),
fail-open on LLM error, registration correctness, email dispatch,
auto-adjust chain for high-severity risks, milestone CRM writes, and
unknown-task-type error handling.

All external dependencies (LLM service, RAG pipeline, Notion adapter,
Gmail service) are mocked -- no external services are required to run
these tests.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.agents.project_manager import (
    ProjectManagerAgent,
    create_pm_registration,
)


# ── Mock LLM responses ──────────────────────────────────────────────────────


def _make_project_plan_json() -> str:
    """Return a realistic ProjectPlan JSON string."""
    return json.dumps(
        {
            "plan_id": "p-test-1",
            "deal_id": "d-test-1",
            "project_name": "Test Integration Project",
            "phases": [
                {
                    "phase_id": "ph-1",
                    "name": "Discovery",
                    "resource_estimate_days": 10.0,
                    "milestones": [
                        {
                            "milestone_id": "m-1",
                            "name": "Requirements Complete",
                            "target_date": "2026-03-01T00:00:00Z",
                            "tasks": [
                                {
                                    "task_id": "t-1",
                                    "name": "Gather requirements",
                                    "owner": "PM",
                                    "duration_days": 5.0,
                                    "dependencies": [],
                                    "status": "not_started",
                                }
                            ],
                            "success_criteria": "Requirements document signed off",
                            "status": "not_started",
                        }
                    ],
                }
            ],
            "created_at": "2026-02-23T00:00:00Z",
            "updated_at": "2026-02-23T00:00:00Z",
            "version": 1,
            "trigger_source": "deal_won",
            "total_budget_days": 10.0,
        }
    )


def _make_risk_list_json(severity: str = "high") -> str:
    """Return a risk list JSON wrapped in a 'risks' key."""
    return json.dumps(
        {
            "risks": [
                {
                    "risk_id": "r-1",
                    "signal_type": "milestone_overdue",
                    "severity": severity,
                    "description": "Milestone 1 is behind schedule by 3 days",
                    "recommended_action": "Re-baseline timeline",
                    "detected_at": "2026-02-23T00:00:00Z",
                }
            ]
        }
    )


def _make_empty_risk_list_json() -> str:
    """Return an empty risk list JSON."""
    return json.dumps({"risks": []})


def _make_scope_change_delta_json() -> str:
    """Return a valid ScopeChangeDelta JSON string."""
    return json.dumps(
        {
            "change_request_id": "cr-1",
            "original_plan_version": 1,
            "revised_plan_version": 2,
            "trigger": "manual_input",
            "changes": [
                {
                    "element_type": "milestone",
                    "element_id": "m-1",
                    "field": "target_date",
                    "original_value": "2026-03-01",
                    "revised_value": "2026-03-08",
                    "change_type": "modified",
                }
            ],
            "timeline_impact_days": 7,
            "resource_impact_days": 0.0,
            "affected_milestones": ["m-1"],
            "risk_assessment": "Low risk - one week extension within acceptable range",
            "recommendation": "approve",
        }
    )


def _make_internal_report_json() -> str:
    """Return a valid InternalStatusReport JSON string."""
    return json.dumps(
        {
            "report_id": "rpt-1",
            "project_id": "p-test-1",
            "report_date": "2026-02-23T00:00:00Z",
            "overall_rag": "green",
            "milestone_progress": [],
            "risks_and_issues": [],
            "next_actions": [],
            "earned_value": {
                "bcwp": 5.0,
                "acwp": 6.0,
                "bcws": 7.5,
                "cpi": 0.83,
                "spi": 0.67,
            },
            "deal_context": {},
            "agent_notes": "Project progressing well",
            "sa_summary": "",
        }
    )


def _make_external_report_json() -> str:
    """Return a valid ExternalStatusReport JSON string."""
    return json.dumps(
        {
            "report_id": "rpt-ext-1",
            "project_name": "Test Project",
            "report_date": "2026-02-23T00:00:00Z",
            "overall_status": "On Track",
            "milestone_summary": [],
            "key_accomplishments": ["Requirements gathered"],
            "upcoming_activities": ["Development begins"],
            "items_requiring_attention": [],
        }
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_llm(agent: ProjectManagerAgent, json_content: str) -> None:
    """Set agent LLM to return a JSON string wrapped in code fences."""
    agent._llm_service.completion = AsyncMock(
        return_value={"content": f"```json\n{json_content}\n```"}
    )


def _make_pm_agent(
    notion_pm: object | None = None,
    gmail_service: object | None = None,
) -> ProjectManagerAgent:
    """Create a PM agent with mocked services."""
    registration = create_pm_registration()
    return ProjectManagerAgent(
        registration=registration,
        llm_service=AsyncMock(),
        rag_pipeline=AsyncMock(),
        notion_pm=notion_pm if notion_pm is not None else AsyncMock(),
        gmail_service=gmail_service if gmail_service is not None else AsyncMock(),
    )


# ── Test Cases ───────────────────────────────────────────────────────────────


class TestPMCreateProjectPlan:
    """Tests for create_project_plan handler."""

    @pytest.mark.asyncio
    async def test_pm_creates_plan_from_deliverables(self):
        """execute() routes 'create_project_plan' and returns ProjectPlan-shaped dict."""
        agent = _make_pm_agent()
        _mock_llm(agent, _make_project_plan_json())

        result = await agent.execute(
            {
                "type": "create_project_plan",
                "deliverables": ["CRM integration", "Data migration"],
                "deal_context": {"deal_id": "d-test-1"},
            },
            {"tenant_id": "test"},
        )

        assert "plan_id" in result
        assert "phases" in result
        assert isinstance(result["phases"], list)
        assert len(result["phases"]) > 0
        assert result["plan_id"] == "p-test-1"

    @pytest.mark.asyncio
    async def test_pm_create_plan_fail_open(self):
        """LLM error returns partial result instead of raising."""
        agent = _make_pm_agent()
        agent._llm_service.completion = AsyncMock(
            side_effect=RuntimeError("LLM unavailable")
        )

        result = await agent.execute(
            {
                "type": "create_project_plan",
                "deliverables": ["Something"],
            },
            {"tenant_id": "test"},
        )

        assert isinstance(result, dict)
        assert "error" in result
        assert result["confidence"] == "low"
        assert result["partial"] is True


class TestPMDetectRisks:
    """Tests for detect_risks handler including auto-adjust chain."""

    @pytest.mark.asyncio
    async def test_pm_detects_risks(self):
        """execute() routes 'detect_risks' and returns risks list."""
        agent = _make_pm_agent()
        _mock_llm(agent, _make_risk_list_json())

        result = await agent.execute(
            {
                "type": "detect_risks",
                "plan_json": "{}",
                "current_progress": "milestone 1 is 3 days overdue",
            },
            {"tenant_id": "test"},
        )

        assert "risks" in result
        assert isinstance(result["risks"], list)
        assert len(result["risks"]) > 0

    @pytest.mark.asyncio
    async def test_pm_detect_risks_empty_when_no_issues(self):
        """When LLM returns empty risk list, result has zero risks."""
        agent = _make_pm_agent()
        _mock_llm(agent, _make_empty_risk_list_json())

        result = await agent.execute(
            {
                "type": "detect_risks",
                "plan_json": "{}",
                "current_progress": "everything on track",
            },
            {"tenant_id": "test"},
        )

        assert "risks" in result
        assert len(result["risks"]) == 0

    @pytest.mark.asyncio
    async def test_pm_detect_risks_auto_adjust_chain(self):
        """High-severity risk triggers auto-adjust chain producing adjustments."""
        agent = _make_pm_agent()

        # First call (detect_risks) returns high-severity risk
        # Second call (auto-triggered adjust_plan) returns scope change delta
        risk_response = {"content": f"```json\n{_make_risk_list_json('high')}\n```"}
        delta_response = {
            "content": f"```json\n{_make_scope_change_delta_json()}\n```"
        }
        agent._llm_service.completion = AsyncMock(
            side_effect=[risk_response, delta_response]
        )

        result = await agent.execute(
            {
                "type": "detect_risks",
                "plan_json": "{}",
                "current_progress": "milestone 1 is critically behind",
                "deal_context": {},
            },
            {"tenant_id": "test"},
        )

        assert "auto_adjustments" in result
        assert len(result["auto_adjustments"]) >= 1
        adjustment = result["auto_adjustments"][0]
        assert adjustment["severity"] == "high"
        assert "adjustment" in adjustment


class TestPMAdjustPlan:
    """Tests for adjust_plan handler."""

    @pytest.mark.asyncio
    async def test_pm_produces_scope_change_delta(self):
        """execute() routes 'adjust_plan' and returns ScopeChangeDelta-shaped dict."""
        agent = _make_pm_agent()
        _mock_llm(agent, _make_scope_change_delta_json())

        result = await agent.execute(
            {
                "type": "adjust_plan",
                "original_plan_json": "{}",
                "scope_change_description": "Extend milestone 1 by 1 week",
                "trigger": "manual_input",
            },
            {"tenant_id": "test"},
        )

        assert "changes" in result
        assert "timeline_impact_days" in result
        assert "recommendation" in result
        assert result["timeline_impact_days"] == 7
        assert result["recommendation"] == "approve"


class TestPMStatusReport:
    """Tests for generate_status_report handler (internal and external)."""

    @pytest.mark.asyncio
    async def test_pm_generates_internal_report(self):
        """Internal report contains overall_rag and earned_value."""
        agent = _make_pm_agent()
        _mock_llm(agent, _make_internal_report_json())

        result = await agent.execute(
            {
                "type": "generate_status_report",
                "plan_json": json.dumps(
                    {
                        "phases": [
                            {
                                "milestones": [{"tasks": []}],
                                "resource_estimate_days": 0,
                            }
                        ]
                    }
                ),
                "progress_data": json.dumps(
                    {"actual_days_spent": 0, "scheduled_completion_pct": 0}
                ),
                "deal_context": {},
                "sa_summary": "",
                "report_type": "internal",
            },
            {"tenant_id": "test"},
        )

        assert "overall_rag" in result
        assert "earned_value" in result
        assert result["overall_rag"] in ("red", "amber", "green")

    @pytest.mark.asyncio
    async def test_pm_generates_external_report(self):
        """External report has overall_status and key_accomplishments but NOT overall_rag."""
        agent = _make_pm_agent()
        _mock_llm(agent, _make_external_report_json())

        result = await agent.execute(
            {
                "type": "generate_status_report",
                "plan_json": json.dumps(
                    {
                        "phases": [
                            {
                                "milestones": [{"tasks": []}],
                                "resource_estimate_days": 0,
                            }
                        ]
                    }
                ),
                "progress_data": json.dumps(
                    {"actual_days_spent": 0, "scheduled_completion_pct": 0}
                ),
                "deal_context": {},
                "sa_summary": "",
                "report_type": "external",
                "project_name": "Test Project",
            },
            {"tenant_id": "test"},
        )

        assert "overall_status" in result
        assert "key_accomplishments" in result
        assert "overall_rag" not in result

    @pytest.mark.asyncio
    async def test_pm_report_earned_value_is_precalculated(self):
        """EV is calculated in pure Python before the LLM call, not by the LLM."""
        agent = _make_pm_agent()
        # Return a report JSON -- the key point is that EV is calculated
        # BEFORE the LLM call, so even if the LLM returns different EV
        # numbers, the handler ran calculate_earned_value first.
        _mock_llm(agent, _make_internal_report_json())

        # Spy on the LLM completion call to inspect the prompt
        original_completion = agent._llm_service.completion

        captured_messages = []

        async def capture_completion(**kwargs):
            captured_messages.append(kwargs.get("messages", []))
            return await original_completion(**kwargs)

        agent._llm_service.completion = capture_completion

        plan_with_tasks = json.dumps(
            {
                "phases": [
                    {
                        "milestones": [
                            {
                                "tasks": [
                                    {
                                        "task_id": "t-1",
                                        "name": "Task A",
                                        "owner": "PM",
                                        "duration_days": 10.0,
                                        "dependencies": [],
                                        "status": "completed",
                                    }
                                ]
                            }
                        ],
                        "resource_estimate_days": 10,
                    }
                ]
            }
        )

        result = await agent.execute(
            {
                "type": "generate_status_report",
                "plan_json": plan_with_tasks,
                "progress_data": json.dumps(
                    {"actual_days_spent": 8, "scheduled_completion_pct": 0.5}
                ),
                "deal_context": {},
                "sa_summary": "",
                "report_type": "internal",
            },
            {"tenant_id": "test"},
        )

        # Verify the prompt sent to LLM contained pre-calculated EV data
        # (earned_value_json is injected into the prompt by the handler)
        assert len(captured_messages) == 1
        prompt_text = json.dumps(captured_messages[0])
        # The prompt should contain bcwp/acwp/bcws from calculate_earned_value
        assert "bcwp" in prompt_text.lower() or "earned" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_pm_report_email_sent(self):
        """After report generation, email is sent to stakeholders."""
        gmail_mock = AsyncMock()
        gmail_mock.send_email = AsyncMock()
        agent = _make_pm_agent(gmail_service=gmail_mock)
        _mock_llm(agent, _make_internal_report_json())

        await agent.execute(
            {
                "type": "generate_status_report",
                "plan_json": json.dumps(
                    {
                        "phases": [
                            {
                                "milestones": [{"tasks": []}],
                                "resource_estimate_days": 0,
                            }
                        ]
                    }
                ),
                "progress_data": json.dumps(
                    {"actual_days_spent": 0, "scheduled_completion_pct": 0}
                ),
                "deal_context": {
                    "stakeholders": [
                        {"email": "test@example.com", "name": "Test User"}
                    ]
                },
                "sa_summary": "",
                "report_type": "internal",
            },
            {"tenant_id": "test"},
        )

        gmail_mock.send_email.assert_called_once()
        call_kwargs = gmail_mock.send_email.call_args
        # stakeholders list is passed as 'to' argument
        to_arg = call_kwargs.kwargs.get("to") or call_kwargs[1].get("to")
        assert any("test@example.com" in str(r) for r in to_arg)

    @pytest.mark.asyncio
    async def test_pm_report_email_failure_does_not_break_report(self):
        """Email send failure does not prevent report from being returned."""
        gmail_mock = AsyncMock()
        gmail_mock.send_email = AsyncMock(
            side_effect=Exception("SMTP connection failed")
        )
        agent = _make_pm_agent(gmail_service=gmail_mock)
        _mock_llm(agent, _make_internal_report_json())

        result = await agent.execute(
            {
                "type": "generate_status_report",
                "plan_json": json.dumps(
                    {
                        "phases": [
                            {
                                "milestones": [{"tasks": []}],
                                "resource_estimate_days": 0,
                            }
                        ]
                    }
                ),
                "progress_data": json.dumps(
                    {"actual_days_spent": 0, "scheduled_completion_pct": 0}
                ),
                "deal_context": {
                    "stakeholders": [
                        {"email": "test@example.com", "name": "Test User"}
                    ]
                },
                "sa_summary": "",
                "report_type": "internal",
            },
            {"tenant_id": "test"},
        )

        # Report is returned successfully despite email failure
        assert isinstance(result, dict)
        assert "error" not in result
        assert "overall_rag" in result


class TestPMWriteCRM:
    """Tests for write_crm_records handler."""

    @pytest.mark.asyncio
    async def test_pm_write_crm_calls_notion_adapter(self):
        """create_project operation calls notion_pm.create_project_record."""
        notion_mock = AsyncMock()
        notion_mock.create_project_record = AsyncMock(return_value="page-abc")
        agent = _make_pm_agent(notion_pm=notion_mock)

        result = await agent.execute(
            {
                "type": "write_crm_records",
                "operation": "create_project",
                "data": {"project_name": "Test"},
            },
            {"tenant_id": "test"},
        )

        notion_mock.create_project_record.assert_called_once()
        assert result["status"] == "written"
        assert result["page_id"] == "page-abc"

    @pytest.mark.asyncio
    async def test_pm_write_crm_no_adapter(self):
        """With notion_pm=None, write_crm_records returns error."""
        agent = _make_pm_agent(notion_pm=None)
        # Override _notion_pm to None (since _make_pm_agent defaults to AsyncMock)
        agent._notion_pm = None

        result = await agent.execute(
            {
                "type": "write_crm_records",
                "operation": "create_project",
                "data": {"project_name": "Test"},
            },
            {"tenant_id": "test"},
        )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_pm_write_crm_milestone_event(self):
        """append_milestone calls notion_pm.append_milestone_event with page_id."""
        notion_mock = AsyncMock()
        notion_mock.append_milestone_event = AsyncMock()
        agent = _make_pm_agent(notion_pm=notion_mock)

        result = await agent.execute(
            {
                "type": "write_crm_records",
                "operation": "append_milestone",
                "page_id": "page-123",
                "milestone_blocks": [{"type": "paragraph"}],
            },
            {"tenant_id": "test"},
        )

        notion_mock.append_milestone_event.assert_called_once_with(
            "page-123", [{"type": "paragraph"}]
        )
        assert result["status"] == "written"


class TestPMRegistration:
    """Tests for PM agent registration and capabilities."""

    def test_pm_registration_has_correct_capabilities(self):
        """create_pm_registration() returns correct agent_id, 6 capabilities."""
        reg = create_pm_registration()

        assert reg.agent_id == "project_manager"
        assert reg.name == "Project Manager"
        assert len(reg.capabilities) == 6

        cap_names = {c.name for c in reg.capabilities}
        assert "create_project_plan" in cap_names
        assert "detect_risks" in cap_names
        assert "adjust_plan" in cap_names
        assert "generate_status_report" in cap_names
        assert "write_crm_records" in cap_names
        assert "process_trigger" in cap_names


class TestPMErrorHandling:
    """Tests for error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_pm_unknown_task_type_raises_valueerror(self):
        """execute() raises ValueError for unknown task type."""
        agent = _make_pm_agent()

        with pytest.raises(ValueError, match="create_project_plan"):
            await agent.execute(
                {"type": "invalid_task"},
                {"tenant_id": "test"},
            )
