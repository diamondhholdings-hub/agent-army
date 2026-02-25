"""Agent handler routing and behavior tests for CustomerSuccessAgent.

Proves the CSM agent's execute() routing, handler call patterns, and fail-open
semantics. Health scan uses real CSMHealthScorer (no LLM). QBR generation calls
llm_service.completion() and notion_csm.create_qbr_page(). Expansion check
dispatches to sales_agent.execute() with handle_expansion_opportunity type.
Unknown task type raises ValueError (not fail-open dict).

All external dependencies (LLM, Notion, Gmail, Chat, EventBus) are mocked.
HealthScorer is the real pure-Python implementation (deterministic, no mock).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.agents.base import AgentCapability, AgentRegistration
from src.app.agents.customer_success.agent import CustomerSuccessAgent
from src.app.agents.customer_success.health_scorer import CSMHealthScorer
from src.app.agents.customer_success.schemas import QBRContent


# -- Fixtures ----------------------------------------------------------------


def _make_registration() -> AgentRegistration:
    """Create a minimal AgentRegistration for testing."""
    return AgentRegistration(
        agent_id="customer_success_manager",
        name="Customer Success Manager",
        description="CSM agent for account health and growth",
        capabilities=[
            AgentCapability(
                name="health_scan",
                description="Compute account health score",
            ),
        ],
    )


def _make_mock_llm(response_json: dict | None = None) -> AsyncMock:
    """Create an AsyncMock LLM service with completion returning valid JSON."""
    llm = AsyncMock()
    if response_json is None:
        response_json = {
            "period": "Q1 2026",
            "health_summary": "Account is healthy.",
            "roi_metrics": {"time_saved_hours": 120},
            "feature_adoption_scorecard": {"feature_x": 0.85},
            "expansion_next_steps": ["Expand seats"],
            "trigger": "quarterly",
        }
    llm.completion = AsyncMock(
        return_value={"content": json.dumps(response_json)}
    )
    return llm


def _make_mock_notion() -> AsyncMock:
    """Create an AsyncMock NotionCSMAdapter with standard return values."""
    notion = AsyncMock()
    notion.get_account = AsyncMock(
        return_value={
            "id": "page-uuid-001",
            "account_id": "page-uuid-001",
            "name": "Acme Corp",
            "csm_health_score": 75.0,
            "csm_health_rag": "GREEN",
        }
    )
    notion.query_all_accounts = AsyncMock(
        return_value=[
            {
                "id": "page-uuid-001",
                "account_id": "page-uuid-001",
                "name": "Acme Corp",
            },
        ]
    )
    notion.create_qbr_page = AsyncMock(return_value="qbr-page-uuid")
    notion.create_expansion_record = AsyncMock(return_value="expansion-page-uuid")
    notion.update_health_score = AsyncMock()
    return notion


def _make_mock_sales_agent() -> AsyncMock:
    """Create an AsyncMock Sales Agent with execute returning success dict."""
    agent = AsyncMock()
    agent.execute = AsyncMock(
        return_value={
            "status": "success",
            "task_type": "handle_expansion_opportunity",
        }
    )
    return agent


def _healthy_signals_dict() -> dict:
    """Return a dict of healthy CSMHealthSignals fields."""
    return {
        "feature_adoption_rate": 0.9,
        "usage_trend": "growing",
        "login_frequency_days": 5,
        "days_since_last_interaction": 10,
        "stakeholder_engagement": "high",
        "nps_score": 9,
        "invoice_payment_status": "current",
        "days_to_renewal": 200,
        "seats_utilization_rate": 0.85,
        "open_ticket_count": 0,
        "avg_ticket_sentiment": "positive",
        "escalation_count_90_days": 0,
        "tam_health_rag": None,
    }


def _make_csm_agent(
    llm: AsyncMock | None = None,
    notion: AsyncMock | None = None,
    health_scorer: CSMHealthScorer | None = None,
    sales_agent: AsyncMock | None = None,
) -> CustomerSuccessAgent:
    """Create a CustomerSuccessAgent with configurable dependencies."""
    return CustomerSuccessAgent(
        registration=_make_registration(),
        llm_service=llm or _make_mock_llm(),
        notion_csm=notion,
        gmail_service=None,
        chat_service=None,
        event_bus=None,
        health_scorer=health_scorer,
        sales_agent=sales_agent,
    )


# -- Handler Routing Tests ---------------------------------------------------


class TestCSMHandlers:
    """Tests for CustomerSuccessAgent handler routing and behavior."""

    @pytest.mark.asyncio
    async def test_unknown_task_type_raises_value_error(self):
        """Unknown task type raises ValueError (not fail-open dict)."""
        agent = _make_csm_agent()
        with pytest.raises(ValueError, match="Unknown task type"):
            await agent.execute(
                task={"type": "nonexistent_handler"},
                context={"tenant_id": "t-1"},
            )

    @pytest.mark.asyncio
    async def test_health_scan_uses_health_scorer_not_llm(self):
        """Health scan uses real CSMHealthScorer and does NOT call LLM."""
        mock_llm = _make_mock_llm()
        scorer = CSMHealthScorer()
        agent = _make_csm_agent(llm=mock_llm, health_scorer=scorer)

        result = await agent.execute(
            task={
                "type": "health_scan",
                "account_id": "acct-001",
                "signals": _healthy_signals_dict(),
            },
            context={"tenant_id": "t-1"},
        )

        # LLM should NOT have been called
        mock_llm.completion.assert_not_called()

        # Should have health_scores list
        assert "health_scores" in result
        assert isinstance(result["health_scores"], list)
        assert len(result["health_scores"]) >= 1
        assert result["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_health_scan_fail_open_when_scorer_missing(self):
        """health_scorer=None returns error dict, not exception."""
        agent = _make_csm_agent(health_scorer=None)

        result = await agent.execute(
            task={
                "type": "health_scan",
                "account_id": "acct-001",
                "signals": _healthy_signals_dict(),
            },
            context={"tenant_id": "t-1"},
        )

        assert result["error"] == "CSMHealthScorer not configured"
        assert result["confidence"] == "low"
        assert result["partial"] is True

    @pytest.mark.asyncio
    async def test_generate_qbr_calls_llm_and_creates_notion_page(self):
        """generate_qbr handler calls llm_service.completion() and notion_csm.create_qbr_page()."""
        mock_llm = _make_mock_llm()
        mock_notion = _make_mock_notion()
        agent = _make_csm_agent(llm=mock_llm, notion=mock_notion)

        result = await agent.execute(
            task={
                "type": "generate_qbr",
                "account_id": "acct-qbr",
                "account_data": {"name": "Acme Corp"},
                "health_history": {"scores": [70, 75, 80]},
                "period": "Q1 2026",
            },
            context={"tenant_id": "t-1"},
        )

        # LLM was called
        mock_llm.completion.assert_called_once()

        # Notion create_qbr_page was called with a QBRContent instance
        mock_notion.create_qbr_page.assert_called_once()
        call_args = mock_notion.create_qbr_page.call_args
        qbr_arg = call_args[0][0] if call_args[0] else call_args[1].get("qbr")
        assert isinstance(qbr_arg, QBRContent)

        # Result has expected keys
        assert result["task_type"] == "generate_qbr"
        assert result["confidence"] == "high"
        assert result["qbr_page_id"] == "qbr-page-uuid"

    @pytest.mark.asyncio
    async def test_check_expansion_dispatches_to_sales_agent(self):
        """check_expansion handler dispatches to sales_agent.execute() with handle_expansion_opportunity type."""
        expansion_json = {
            "opportunity_type": "seats",
            "evidence": "Seat utilization at 95%",
            "estimated_arr_impact": 50000.0,
            "recommended_talk_track": "Your team is maxing out seats.",
            "confidence": "high",
        }
        mock_llm = _make_mock_llm(response_json=expansion_json)
        mock_sales = _make_mock_sales_agent()
        agent = _make_csm_agent(llm=mock_llm, sales_agent=mock_sales)

        result = await agent.execute(
            task={
                "type": "check_expansion",
                "account_id": "acct-exp",
                "account_data": {"name": "Acme Corp"},
                "usage_signals": {"seats_used": 95, "seats_total": 100},
            },
            context={"tenant_id": "t-1"},
        )

        # Sales agent was dispatched
        mock_sales.execute.assert_called()
        dispatch_call = mock_sales.execute.call_args
        dispatch_task = dispatch_call[0][0]
        assert dispatch_task["type"] == "handle_expansion_opportunity"
        assert dispatch_task["account_id"] == "acct-exp"

        # Result has expected keys
        assert result["task_type"] == "check_expansion"
        assert result["confidence"] == "high"
        assert len(result["opportunities"]) >= 1

    @pytest.mark.asyncio
    async def test_check_expansion_skips_dispatch_when_sales_agent_none(self):
        """When sales_agent is None, expansion skips dispatch gracefully."""
        expansion_json = {
            "opportunity_type": "module",
            "evidence": "Low adoption of analytics module",
            "estimated_arr_impact": 30000.0,
            "recommended_talk_track": "Consider analytics.",
            "confidence": "medium",
        }
        mock_llm = _make_mock_llm(response_json=expansion_json)
        agent = _make_csm_agent(llm=mock_llm, sales_agent=None)

        result = await agent.execute(
            task={
                "type": "check_expansion",
                "account_id": "acct-no-sales",
                "account_data": {},
                "usage_signals": {},
            },
            context={"tenant_id": "t-1"},
        )

        # Should still return opportunities, just no dispatch
        assert result["task_type"] == "check_expansion"
        assert result["confidence"] == "high"
        assert result["sales_dispatch_result"] is None

    @pytest.mark.asyncio
    async def test_track_feature_adoption_returns_result(self):
        """track_feature_adoption handler returns feature adoption report."""
        adoption_json = {
            "features_used": ["dashboard", "reports"],
            "adoption_rate": 0.65,
            "underutilized_features": ["integrations"],
            "recommendations": ["Enable Slack integration"],
            "benchmark_comparison": None,
        }
        mock_llm = _make_mock_llm(response_json=adoption_json)
        agent = _make_csm_agent(llm=mock_llm)

        result = await agent.execute(
            task={
                "type": "track_feature_adoption",
                "account_id": "acct-adopt",
                "account_data": {"name": "Acme Corp"},
                "feature_usage": {"dashboard": {"active": True, "usage_pct": 0.8}},
            },
            context={"tenant_id": "t-1"},
        )

        mock_llm.completion.assert_called_once()
        assert result["task_type"] == "track_feature_adoption"
        assert result["confidence"] == "high"
        assert "report" in result

    @pytest.mark.asyncio
    async def test_generate_qbr_fails_open_on_exception(self):
        """generate_qbr returns error dict on LLM failure."""
        mock_llm = AsyncMock()
        mock_llm.completion = AsyncMock(side_effect=RuntimeError("LLM down"))
        agent = _make_csm_agent(llm=mock_llm)

        result = await agent.execute(
            task={
                "type": "generate_qbr",
                "account_id": "acct-fail",
                "account_data": {},
                "health_history": {},
                "period": "Q1 2026",
            },
            context={"tenant_id": "t-1"},
        )

        assert result["task_type"] == "generate_qbr"
        assert "error" in result
        assert result["confidence"] == "low"
        assert result["partial"] is True

    @pytest.mark.asyncio
    async def test_check_expansion_fails_open_on_exception(self):
        """check_expansion returns error dict on LLM failure."""
        mock_llm = AsyncMock()
        mock_llm.completion = AsyncMock(side_effect=RuntimeError("LLM down"))
        agent = _make_csm_agent(llm=mock_llm)

        result = await agent.execute(
            task={
                "type": "check_expansion",
                "account_id": "acct-fail",
                "account_data": {},
                "usage_signals": {},
            },
            context={"tenant_id": "t-1"},
        )

        assert result["task_type"] == "check_expansion"
        assert "error" in result
        assert result["confidence"] == "low"
        assert result["partial"] is True

    @pytest.mark.asyncio
    async def test_track_feature_adoption_fails_open_on_exception(self):
        """track_feature_adoption returns error dict on LLM failure."""
        mock_llm = AsyncMock()
        mock_llm.completion = AsyncMock(side_effect=RuntimeError("LLM down"))
        agent = _make_csm_agent(llm=mock_llm)

        result = await agent.execute(
            task={
                "type": "track_feature_adoption",
                "account_id": "acct-fail",
                "account_data": {},
                "feature_usage": {},
            },
            context={"tenant_id": "t-1"},
        )

        assert result["task_type"] == "track_feature_adoption"
        assert "error" in result
        assert result["confidence"] == "low"
        assert result["partial"] is True
