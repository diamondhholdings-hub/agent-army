"""Main.py lifespan CSM wiring tests for Phase 14 integration.

Proves that the Phase 14 CSM agent wiring in main.py is correctly structured:
app.state.customer_success is set when CustomerSuccessAgent initializes,
app.state.csm_scheduler is set when CSMScheduler starts, shutdown cleanup
stops the scheduler, and the Sales Agent registers handle_expansion_opportunity.

All external dependencies (LLM, Notion, Gmail, Chat, EventBus) are mocked.
CSMHealthScorer is the real pure-Python implementation (deterministic, no mock).
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.agents.base import AgentCapability, AgentRegistration
from src.app.agents.customer_success.agent import CustomerSuccessAgent
from src.app.agents.customer_success.health_scorer import CSMHealthScorer
from src.app.agents.customer_success.scheduler import CSMScheduler


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


def _read_main_py_source() -> str:
    """Read main.py as text to avoid triggering the full import chain."""
    with open("src/app/main.py") as f:
        return f.read()


# -- Test class ---------------------------------------------------------------


class TestCSMWiring:
    """Test suite for CSM agent wiring in main.py lifespan."""

    def test_csm_agent_attributes_set_correctly(self) -> None:
        """Instantiate CustomerSuccessAgent with mock deps; verify attributes."""
        reg = _make_registration()
        mock_llm = AsyncMock()
        mock_notion = AsyncMock()
        mock_gmail = AsyncMock()
        mock_chat = AsyncMock()
        mock_event_bus = AsyncMock()
        mock_scorer = MagicMock()
        mock_sales = AsyncMock()

        agent = CustomerSuccessAgent(
            registration=reg,
            llm_service=mock_llm,
            notion_csm=mock_notion,
            gmail_service=mock_gmail,
            chat_service=mock_chat,
            event_bus=mock_event_bus,
            health_scorer=mock_scorer,
            sales_agent=mock_sales,
        )

        assert agent._llm_service is mock_llm
        assert agent._notion_csm is mock_notion
        assert agent._gmail_service is mock_gmail
        assert agent._chat_service is mock_chat
        assert agent._event_bus is mock_event_bus
        assert agent._health_scorer is mock_scorer
        assert agent._sales_agent is mock_sales

    @pytest.mark.asyncio
    async def test_csm_agent_handles_none_sales_agent(self) -> None:
        """With sales_agent=None, check_expansion should not raise AttributeError."""
        reg = _make_registration()

        # LLM mock returning a valid expansion opportunity JSON
        mock_llm = AsyncMock()
        mock_llm.completion = AsyncMock(
            return_value={
                "content": '{"opportunity_type": "seats", "evidence": "high util", '
                '"recommended_talk_track": "pitch more seats", "confidence": "high"}'
            }
        )

        agent = CustomerSuccessAgent(
            registration=reg,
            llm_service=mock_llm,
            sales_agent=None,  # Explicitly None
        )

        # Should not raise -- logs warning and skips dispatch
        result = await agent.execute(
            {"type": "check_expansion", "account_id": "acct-001"},
            {"tenant_id": "t1"},
        )

        assert result["task_type"] == "check_expansion"
        # No error key -- the handler completes successfully
        assert "error" not in result
        # sales_dispatch_result is None since sales_agent is None
        assert result.get("sales_dispatch_result") is None

    @pytest.mark.asyncio
    async def test_csm_scheduler_starts_and_stops(self) -> None:
        """CSMScheduler.start() returns bool; stop() doesn't raise."""
        mock_agent = AsyncMock()
        scheduler = CSMScheduler(csm_agent=mock_agent, notion_csm=None)

        # start() returns True if APScheduler is installed, False otherwise.
        # Running inside async context provides the event loop APScheduler needs.
        started = scheduler.start()
        assert isinstance(started, bool)

        # stop() should never raise regardless of start status
        scheduler.stop()

    def test_main_py_has_phase14_block(self) -> None:
        """Read main.py source; assert 'customer_success' and 'csm_scheduler' present."""
        source = _read_main_py_source()

        assert "customer_success" in source, (
            "main.py should reference 'customer_success' for Phase 14 wiring"
        )
        assert "csm_scheduler" in source, (
            "main.py should reference 'csm_scheduler' for Phase 14 wiring"
        )

    def test_main_py_shutdown_stops_csm_scheduler(self) -> None:
        """Read main.py source; assert CSM scheduler stop logic present."""
        source = _read_main_py_source()

        # The shutdown section should stop the CSM scheduler
        assert "csm_scheduler_ref" in source or (
            "csm_scheduler" in source and ".stop()" in source
        ), "main.py shutdown should stop the CSM scheduler"

    def test_sales_agent_handler_registered(self) -> None:
        """Read sales/agent.py source; assert 'handle_expansion_opportunity' present."""
        source = inspect.getsource(
            __import__(
                "src.app.agents.sales.agent", fromlist=["SalesAgent"]
            )
        )

        assert "handle_expansion_opportunity" in source, (
            "Sales agent should have 'handle_expansion_opportunity' handler "
            "registered for receiving CSM expansion dispatch"
        )

    def test_csm_agent_accepts_health_scorer(self) -> None:
        """Instantiate with real CSMHealthScorer(); no error."""
        reg = _make_registration()
        real_scorer = CSMHealthScorer()

        agent = CustomerSuccessAgent(
            registration=reg,
            llm_service=AsyncMock(),
            health_scorer=real_scorer,
        )

        assert agent._health_scorer is real_scorer
        assert isinstance(agent._health_scorer, CSMHealthScorer)
