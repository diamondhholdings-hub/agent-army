"""Integration tests for Sales Agent -> Solution Architect handoff round-trip.

Proves the SA-05 inter-agent handoff requirement: the Sales Agent can detect
a technical question, construct a TechnicalQuestionPayload, dispatch a handoff
task to the Solution Architect, and the SA returns a validated
TechnicalAnswerPayload that the Sales Agent can incorporate.

All external dependencies (LLM, RAG, GSuite, stores) are mocked. The tests
exercise the actual execute() routing and handler logic for both agents.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.agents.sales.agent import SalesAgent
from src.app.agents.sales.capabilities import create_sales_registration
from src.app.agents.solution_architect.agent import SolutionArchitectAgent
from src.app.agents.solution_architect.capabilities import create_sa_registration
from src.app.agents.solution_architect.schemas import TechnicalAnswerPayload


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_sales_agent(
    llm_mock: AsyncMock | None = None,
) -> SalesAgent:
    """Create a SalesAgent with all dependencies mocked.

    The dispatch_technical_question handler does NOT use any of the
    external services (gmail, chat, rag, etc.), so simple stubs suffice.
    """
    registration = create_sales_registration()
    return SalesAgent(
        registration=registration,
        llm_service=llm_mock or AsyncMock(),
        gmail_service=AsyncMock(),
        chat_service=AsyncMock(),
        rag_pipeline=AsyncMock(),
        conversation_store=AsyncMock(),
        session_manager=AsyncMock(),
        state_repository=AsyncMock(),
        qualification_extractor=AsyncMock(),
        action_engine=AsyncMock(),
        escalation_manager=AsyncMock(),
    )


def _make_sa_agent(llm_mock: AsyncMock) -> SolutionArchitectAgent:
    """Create a SolutionArchitectAgent with a mock LLM and no RAG."""
    registration = create_sa_registration()
    return SolutionArchitectAgent(
        registration=registration,
        llm_service=llm_mock,
        rag_pipeline=None,
    )


# ── Test Cases ──────────────────────────────────────────────────────────────


class TestSalesAgentDispatch:
    """Tests for the Sales Agent's dispatch_technical_question handler."""

    @pytest.mark.asyncio
    async def test_sales_agent_dispatches_technical_question(self):
        """Sales Agent constructs a valid handoff task for the SA agent."""
        agent = _make_sales_agent()
        result = await agent.execute(
            {
                "type": "dispatch_technical_question",
                "question": "How does Skyvera handle webhook retries and failure recovery?",
                "deal_id": "deal-123",
                "prospect_tech_stack": "AWS, Node.js",
            },
            {"tenant_id": "test"},
        )

        assert result["status"] == "dispatched"
        assert result["handoff_task"]["type"] == "technical_handoff"
        assert "webhook retries" in result["handoff_task"]["question"]
        assert result["target_agent_id"] == "solution_architect"
        assert result["handoff_task"]["deal_id"] == "deal-123"
        assert result["handoff_task"]["prospect_tech_stack"] == "AWS, Node.js"

    @pytest.mark.asyncio
    async def test_sales_agent_dispatch_empty_question_fails(self):
        """Empty question returns failed status with descriptive error."""
        agent = _make_sales_agent()
        result = await agent.execute(
            {"type": "dispatch_technical_question", "question": ""},
            {"tenant_id": "test"},
        )

        assert result["status"] == "failed"
        assert "No question" in result["error"]
        assert result["handoff_task"] is None


class TestSAReceivesHandoff:
    """Tests for the SA agent receiving a handoff task from Sales Agent."""

    @pytest.mark.asyncio
    async def test_sa_agent_receives_handoff_task(self):
        """SA agent processes a handoff_task and returns a TechnicalAnswerPayload shape."""
        sa_llm = AsyncMock()
        sa_llm.completion = AsyncMock(
            return_value={
                "content": json.dumps(
                    {
                        "answer": "Skyvera implements exponential backoff for webhook retries...",
                        "evidence": ["Webhook reliability guide section 2.1"],
                        "confidence": 0.88,
                        "related_docs": ["docs/webhooks.md"],
                    }
                )
            }
        )
        sa_agent = _make_sa_agent(sa_llm)

        handoff_task = {
            "type": "technical_handoff",
            "question": "How does Skyvera handle webhook retries?",
            "deal_id": "deal-123",
        }
        result = await sa_agent.execute(handoff_task, {"tenant_id": "test"})

        assert "answer" in result
        assert isinstance(result["answer"], str)
        assert len(result["answer"]) > 0
        assert "evidence" in result
        assert isinstance(result["evidence"], list)
        assert result["confidence"] >= 0.0


class TestFullRoundTrip:
    """End-to-end round-trip test: Sales Agent -> SA Agent -> validated response."""

    @pytest.mark.asyncio
    async def test_full_round_trip_sales_to_sa_and_back(self):
        """Full Supervisor-mediated handoff round-trip: dispatch -> process -> validate."""
        # Step 1: Sales Agent dispatches technical question
        sales_agent = _make_sales_agent()
        dispatch_result = await sales_agent.execute(
            {
                "type": "dispatch_technical_question",
                "question": (
                    "What authentication protocols does Skyvera support "
                    "for enterprise SSO integration?"
                ),
                "deal_id": "deal-456",
                "prospect_tech_stack": "Azure AD, SAML 2.0",
            },
            {"tenant_id": "test_tenant"},
        )
        assert dispatch_result["status"] == "dispatched"
        handoff_task = dispatch_result["handoff_task"]

        # Step 2: Route handoff_task to SA agent (simulating Supervisor routing)
        sa_llm = AsyncMock()
        sa_llm.completion = AsyncMock(
            return_value={
                "content": json.dumps(
                    {
                        "answer": (
                            "Skyvera supports SAML 2.0, OAuth 2.0, and OIDC "
                            "for enterprise SSO. Azure AD integration uses "
                            "SAML 2.0 with automatic metadata discovery."
                        ),
                        "evidence": [
                            "SSO integration guide section 3.2",
                            "Security whitepaper p.12",
                        ],
                        "confidence": 0.92,
                        "related_docs": ["docs/sso-integration.md"],
                    }
                )
            }
        )
        sa_agent = _make_sa_agent(sa_llm)
        sa_result = await sa_agent.execute(handoff_task, {"tenant_id": "test_tenant"})

        # Step 3: Verify the SA response has TechnicalAnswerPayload shape
        assert "answer" in sa_result
        assert isinstance(sa_result["answer"], str)
        assert len(sa_result["answer"]) > 0
        assert "evidence" in sa_result
        assert isinstance(sa_result["evidence"], list)
        assert sa_result["confidence"] >= 0.0

        # Step 4: Validate type-safety through TechnicalAnswerPayload parsing
        answer_payload = TechnicalAnswerPayload(**sa_result)
        assert answer_payload.answer  # non-empty
        assert answer_payload.confidence > 0.5
        assert len(answer_payload.evidence) >= 1


class TestTechnicalQuestionDetection:
    """Tests for the _is_technical_question heuristic helper."""

    def test_is_technical_question_detection(self):
        """Heuristic detects technical vs. non-technical questions."""
        # Technical questions (2+ keyword matches) -> True
        assert SalesAgent._is_technical_question(
            "How does your API handle rate limiting and OAuth2?"
        )
        assert SalesAgent._is_technical_question(
            "Can you integrate with our Kubernetes deployment and handle webhook retries?"
        )

        # Non-technical questions (fewer than 2 keyword matches) -> False
        assert not SalesAgent._is_technical_question(
            "What's your pricing for 100 users?"
        )
        assert not SalesAgent._is_technical_question(
            "When can we schedule a follow-up meeting?"
        )


class TestContextPreservation:
    """Tests that context is preserved through the handoff."""

    @pytest.mark.asyncio
    async def test_dispatch_preserves_context_chunks(self):
        """Context chunks from the task are passed through to the handoff task."""
        agent = _make_sales_agent()
        result = await agent.execute(
            {
                "type": "dispatch_technical_question",
                "question": "How does the ETL pipeline handle schema migrations?",
                "deal_id": "deal-789",
                "context_chunks": ["chunk1", "chunk2"],
            },
            {"tenant_id": "test"},
        )

        assert result["status"] == "dispatched"
        assert result["handoff_task"]["context_chunks"] == ["chunk1", "chunk2"]
