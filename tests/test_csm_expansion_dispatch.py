"""Bidirectional CSM->Sales expansion dispatch round-trip tests.

Proves the first reverse-direction cross-agent handoff: CSM agent detects
expansion opportunities via LLM analysis, constructs handle_expansion_opportunity
tasks, and dispatches them to the Sales Agent. The Sales Agent processes the
task and creates a Gmail draft for rep review.

Validates: ExpansionOpportunity schema, CSM check_expansion dispatch, Sales
Agent handler registration, graceful degradation with None sales_agent, and
the full CSM->Sales round-trip flow.

All external dependencies (LLM, Gmail, Notion, Chat, EventBus) are mocked.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.app.agents.base import AgentCapability, AgentRegistration
from src.app.agents.customer_success.agent import CustomerSuccessAgent
from src.app.agents.customer_success.schemas import ExpansionOpportunity


# -- Fixtures ----------------------------------------------------------------


def _make_csm_registration() -> AgentRegistration:
    """Create a minimal CSM AgentRegistration for testing."""
    return AgentRegistration(
        agent_id="customer_success_manager",
        name="Customer Success Manager",
        description="CSM agent for account health and growth",
        capabilities=[
            AgentCapability(
                name="check_expansion",
                description="Detect expansion opportunities",
            ),
        ],
    )


def _make_csm_agent(
    llm_response: dict | str | None = None,
    sales_agent: object | None = None,
    gmail_service: object | None = None,
    notion_csm: object | None = None,
) -> CustomerSuccessAgent:
    """Create a CustomerSuccessAgent with mocked LLM and optional dependencies."""
    reg = _make_csm_registration()

    mock_llm = AsyncMock()
    if llm_response is None:
        # Default: single expansion opportunity
        llm_response = {
            "opportunity_type": "seats",
            "evidence": "Seat utilization at 95%, 3 pending user requests",
            "estimated_arr_impact": 24000.0,
            "recommended_talk_track": "Highlight ROI of additional seats",
            "confidence": "high",
        }
    if isinstance(llm_response, dict):
        llm_response = json.dumps(llm_response)
    mock_llm.completion = AsyncMock(return_value={"content": llm_response})

    return CustomerSuccessAgent(
        registration=reg,
        llm_service=mock_llm,
        notion_csm=notion_csm,
        gmail_service=gmail_service,
        sales_agent=sales_agent,
    )


# -- Test class ---------------------------------------------------------------


class TestCSMExpansionDispatch:
    """Test suite for bidirectional CSM->Sales expansion dispatch."""

    def test_expansion_opportunity_schema_valid(self) -> None:
        """ExpansionOpportunity model validates with all required fields."""
        opp = ExpansionOpportunity(
            account_id="acct-001",
            opportunity_type="seats",
            evidence="High seat utilization at 95%",
            estimated_arr_impact=24000.0,
            recommended_talk_track="Pitch additional seats based on usage growth",
            confidence="high",
        )

        assert opp.account_id == "acct-001"
        assert opp.opportunity_type == "seats"
        assert opp.evidence == "High seat utilization at 95%"
        assert opp.estimated_arr_impact == 24000.0
        assert opp.recommended_talk_track == "Pitch additional seats based on usage growth"
        assert opp.confidence == "high"
        assert opp.created_at is not None

    @pytest.mark.asyncio
    async def test_csm_check_expansion_dispatches_correct_task_type(
        self,
    ) -> None:
        """Mock sales_agent; run check_expansion; assert sales_agent.execute called
        with task containing 'handle_expansion_opportunity' type."""
        mock_sales = AsyncMock()
        mock_sales.execute = AsyncMock(
            return_value={
                "task_type": "handle_expansion_opportunity",
                "account_id": "acct-001",
                "draft_id": "draft-xyz",
                "confidence": "high",
            }
        )

        agent = _make_csm_agent(sales_agent=mock_sales)

        result = await agent.execute(
            {
                "type": "check_expansion",
                "account_id": "acct-001",
                "account_data": {"name": "Acme Corp"},
                "usage_signals": {"seat_utilization": 0.95},
            },
            {"tenant_id": "t1"},
        )

        # Sales agent should have been called
        mock_sales.execute.assert_called()

        # Extract the task dict passed to sales_agent.execute
        call_args = mock_sales.execute.call_args
        dispatched_task = call_args[0][0]  # First positional arg

        assert dispatched_task["type"] == "handle_expansion_opportunity"

    @pytest.mark.asyncio
    async def test_csm_check_expansion_passes_account_id(self) -> None:
        """Assert task dispatched to sales_agent has account_id."""
        mock_sales = AsyncMock()
        mock_sales.execute = AsyncMock(
            return_value={
                "task_type": "handle_expansion_opportunity",
                "account_id": "acct-042",
                "draft_id": None,
                "confidence": "high",
            }
        )

        agent = _make_csm_agent(sales_agent=mock_sales)

        result = await agent.execute(
            {
                "type": "check_expansion",
                "account_id": "acct-042",
            },
            {"tenant_id": "t1"},
        )

        # Verify account_id was passed in the dispatched task
        call_args = mock_sales.execute.call_args
        dispatched_task = call_args[0][0]

        assert dispatched_task["account_id"] == "acct-042"

    @pytest.mark.asyncio
    async def test_csm_check_expansion_skips_dispatch_when_no_sales_agent(
        self,
    ) -> None:
        """sales_agent=None; no exception raised, dispatch skipped."""
        agent = _make_csm_agent(sales_agent=None)

        # Should not raise
        result = await agent.execute(
            {
                "type": "check_expansion",
                "account_id": "acct-001",
            },
            {"tenant_id": "t1"},
        )

        assert result["task_type"] == "check_expansion"
        assert "error" not in result
        assert result.get("sales_dispatch_result") is None

    @pytest.mark.asyncio
    async def test_sales_agent_expansion_handler_fail_open(self) -> None:
        """Sales Agent _handle_expansion_opportunity with failing gmail;
        returns result dict (not exception)."""
        # Import SalesAgent directly -- it doesn't trigger the heavy chain
        from src.app.agents.sales.agent import SalesAgent
        from src.app.agents.sales.capabilities import create_sales_registration

        mock_gmail = AsyncMock()
        mock_gmail.create_draft = AsyncMock(
            side_effect=Exception("Gmail API unavailable")
        )

        sales_agent = SalesAgent(
            registration=create_sales_registration(),
            llm_service=AsyncMock(),
            gmail_service=mock_gmail,
            chat_service=AsyncMock(),
            rag_pipeline=AsyncMock(),
            conversation_store=AsyncMock(),
            session_manager=AsyncMock(),
            state_repository=AsyncMock(),
            qualification_extractor=AsyncMock(),
            action_engine=AsyncMock(),
            escalation_manager=AsyncMock(),
        )

        result = await sales_agent.execute(
            {
                "type": "handle_expansion_opportunity",
                "account_id": "acct-001",
                "opportunity_type": "module",
                "evidence": "Low adoption of analytics module",
            },
            {"tenant_id": "t1"},
        )

        # Should return result dict even with Gmail failure (fail-open)
        assert result["task_type"] == "handle_expansion_opportunity"
        assert result["account_id"] == "acct-001"
        # draft_id is None because Gmail failed, but no exception
        assert result.get("draft_id") is None
        assert result["confidence"] == "high"

    def test_sales_agent_expansion_handler_registered(self) -> None:
        """Inspect SalesAgentSupervisor source; 'handle_expansion_opportunity' in source."""
        import src.app.agents.sales.agent as sales_module

        source = inspect.getsource(sales_module)

        # The handler should be registered in the handlers dict
        assert '"handle_expansion_opportunity"' in source, (
            "Sales agent handlers dict should contain "
            "'handle_expansion_opportunity' key"
        )
        # The handler method should exist
        assert "_handle_expansion_opportunity" in source, (
            "Sales agent should have _handle_expansion_opportunity method"
        )

    @pytest.mark.asyncio
    async def test_csm_to_sales_full_round_trip(self) -> None:
        """CSM with mock LLM returning 1 opportunity + mock sales_agent;
        run check_expansion; assert dispatched count > 0 in result."""
        # Mock sales agent that records calls
        mock_sales = AsyncMock()
        mock_sales.execute = AsyncMock(
            return_value={
                "task_type": "handle_expansion_opportunity",
                "account_id": "acct-round-trip",
                "opportunity_type": "seats",
                "draft_id": "draft-round-trip-001",
                "confidence": "high",
            }
        )

        # LLM returns a single expansion opportunity
        llm_response = {
            "opportunity_type": "seats",
            "evidence": "Seat util at 98%, queue of 5 pending requests",
            "estimated_arr_impact": 36000.0,
            "recommended_talk_track": "Expand seat count to match demand",
            "confidence": "high",
        }

        agent = _make_csm_agent(
            llm_response=llm_response,
            sales_agent=mock_sales,
        )

        result = await agent.execute(
            {
                "type": "check_expansion",
                "account_id": "acct-round-trip",
                "account_data": {"name": "RoundTrip Corp"},
                "usage_signals": {"seat_utilization": 0.98},
            },
            {"tenant_id": "t1"},
        )

        # Verify round-trip success
        assert result["task_type"] == "check_expansion"
        assert "error" not in result
        assert result["confidence"] == "high"

        # Verify opportunities were detected
        opportunities = result.get("opportunities", [])
        assert len(opportunities) > 0, "Should have detected at least 1 opportunity"

        # Verify sales dispatch happened
        assert result.get("sales_dispatch_result") is not None
        assert mock_sales.execute.call_count > 0

        # Verify the dispatched task structure
        dispatched_task = mock_sales.execute.call_args[0][0]
        assert dispatched_task["type"] == "handle_expansion_opportunity"
        assert dispatched_task["account_id"] == "acct-round-trip"
        assert dispatched_task["opportunity_type"] == "seats"

    def test_expansion_opportunity_invalid_type_rejected(self) -> None:
        """ExpansionOpportunity(opportunity_type='enterprise') raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ExpansionOpportunity(
                account_id="acct-001",
                opportunity_type="enterprise",  # Invalid -- must be seats|module|integration
                evidence="Some evidence",
                recommended_talk_track="Some talk track",
                confidence="high",
            )

        # Verify the error is about the opportunity_type field
        errors = exc_info.value.errors()
        assert any(
            "opportunity_type" in str(e.get("loc", ()))
            for e in errors
        ), "Validation error should reference opportunity_type field"
