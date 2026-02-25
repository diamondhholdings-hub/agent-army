"""Notion adapter method tests for the Collections Agent.

Tests NotionCollectionsAdapter with a mocked Notion AsyncClient to validate
AR aging bucket computation, escalation state creation/update, payment plan
page creation, and event log append-only behavior.

All Notion API calls are mocked with AsyncMock. No real Notion client is used.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.collections.schemas import ARAgingReport, EscalationState


# -- Fixtures -----------------------------------------------------------------


def _make_mock_client() -> AsyncMock:
    """Build a mock Notion AsyncClient with databases and pages sub-mocks."""
    client = MagicMock()
    client.databases = MagicMock()
    client.databases.query = AsyncMock()
    client.pages = MagicMock()
    client.pages.create = AsyncMock()
    client.pages.update = AsyncMock()
    client.blocks = MagicMock()
    client.blocks.children = MagicMock()
    client.blocks.children.append = AsyncMock()
    return client


def _make_adapter(client: MagicMock) -> object:
    """Instantiate NotionCollectionsAdapter with mock client and test DB IDs."""
    from src.app.agents.collections.notion_adapter import NotionCollectionsAdapter

    return NotionCollectionsAdapter(
        client,
        ar_database_id="ar-db-001",
        escalation_database_id="esc-db-001",
        events_database_id="events-db-001",
    )


def _empty_query_response() -> dict:
    """Return a Notion API query response with no results."""
    return {"results": [], "has_more": False}


def _make_invoice_page(
    invoice_number: str,
    amount: float,
    days_overdue: int,
    due_date: str = "2026-01-01",
    account_name: str = "TestCorp",
) -> dict:
    """Build a mock Notion page dict representing an AR invoice."""
    return {
        "id": f"page-{invoice_number}",
        "properties": {
            "Invoice Number": {
                "title": [{"plain_text": invoice_number}]
            },
            "Amount USD": {"number": amount},
            "Days Overdue": {"number": days_overdue},
            "Due Date": {"date": {"start": due_date}},
            "Account Name": {
                "rich_text": [{"plain_text": account_name}]
            },
            "Account ID": {
                "rich_text": [{"plain_text": "acct-001"}]
            },
        },
    }


# -- Test class ---------------------------------------------------------------


class TestNotionCollectionsAdapterARaging:
    """AR aging query tests."""

    @pytest.mark.asyncio
    async def test_get_ar_aging_empty(self) -> None:
        """Mock Notion client returning 0 results -> ARAgingReport with empty buckets."""
        client = _make_mock_client()
        client.databases.query = AsyncMock(return_value=_empty_query_response())
        adapter = _make_adapter(client)

        result = await adapter.get_ar_aging("acct-empty")

        assert isinstance(result, ARAgingReport)
        assert result.account_id == "acct-empty"
        assert result.total_outstanding_usd == 0.0
        assert result.buckets == []

    @pytest.mark.asyncio
    async def test_get_ar_aging_buckets_correct(self) -> None:
        """Mock Notion client returning 3 invoices -> correct buckets populated.

        Invoice 1: 15 days overdue -> 0-30 bucket
        Invoice 2: 45 days overdue -> 31-60 bucket
        Invoice 3: 75 days overdue -> 61-90 bucket
        """
        client = _make_mock_client()
        client.databases.query = AsyncMock(
            return_value={
                "results": [
                    _make_invoice_page("INV-001", 500.0, 15, "2026-01-10"),
                    _make_invoice_page("INV-002", 1200.0, 45, "2025-12-10"),
                    _make_invoice_page("INV-003", 800.0, 75, "2025-11-10"),
                ],
                "has_more": False,
            }
        )
        adapter = _make_adapter(client)

        result = await adapter.get_ar_aging("acct-001")

        assert isinstance(result, ARAgingReport)
        # Total should be sum of all 3 invoices
        assert result.total_outstanding_usd == pytest.approx(2500.0)
        # Should have 3 non-empty buckets
        bucket_labels = {b.bucket_label for b in result.buckets}
        assert "0-30" in bucket_labels
        assert "31-60" in bucket_labels
        assert "61-90" in bucket_labels


class TestNotionCollectionsAdapterEscalationState:
    """Escalation state retrieval and upsert tests."""

    @pytest.mark.asyncio
    async def test_get_escalation_state_default_when_not_found(self) -> None:
        """Mock returns no results -> EscalationState with stage=0."""
        client = _make_mock_client()
        client.databases.query = AsyncMock(return_value=_empty_query_response())
        adapter = _make_adapter(client)

        result = await adapter.get_escalation_state("acct-new")

        assert isinstance(result, EscalationState)
        assert result.account_id == "acct-new"
        assert result.current_stage == 0
        assert result.messages_unanswered == 0

    @pytest.mark.asyncio
    async def test_update_escalation_state_creates_when_not_found(self) -> None:
        """Mock returns no existing record -> client.pages.create called."""
        client = _make_mock_client()
        # Query returns no existing page
        client.databases.query = AsyncMock(return_value=_empty_query_response())
        client.pages.create = AsyncMock(
            return_value={"id": "new-page-uuid"}
        )
        adapter = _make_adapter(client)

        state = EscalationState(
            account_id="acct-create",
            current_stage=1,
            messages_unanswered=1,
        )
        await adapter.update_escalation_state("acct-create", state)

        # Should have called create (not update) since no existing page found
        client.pages.create.assert_called_once()
        client.pages.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_escalation_state_updates_when_found(self) -> None:
        """Mock returns existing page -> client.pages.update called."""
        client = _make_mock_client()
        existing_page = {
            "id": "existing-page-uuid",
            "properties": {
                "Current Stage": {"number": 1},
                "Messages Unanswered": {"number": 0},
                "Stage5 Notified": {"checkbox": False},
                "Stage Entered At": {"date": None},
                "Last Message Sent At": {"date": None},
                "Payment Received At": {"date": None},
                "Response Received At": {"date": None},
            }
        }
        client.databases.query = AsyncMock(
            return_value={"results": [existing_page], "has_more": False}
        )
        client.pages.update = AsyncMock(return_value={"id": "existing-page-uuid"})
        adapter = _make_adapter(client)

        state = EscalationState(
            account_id="acct-update",
            current_stage=2,
            messages_unanswered=1,
        )
        await adapter.update_escalation_state("acct-update", state)

        # Should have called update (not create) since existing page found
        client.pages.update.assert_called_once()


class TestNotionCollectionsAdapterPaymentPlan:
    """Payment plan page creation tests."""

    @pytest.mark.asyncio
    async def test_create_payment_plan_page_returns_page_id(self) -> None:
        """Mock create returns page with id -> adapter returns UUID string."""
        client = _make_mock_client()
        expected_page_id = "payment-plan-page-uuid-001"
        client.pages.create = AsyncMock(
            return_value={"id": expected_page_id}
        )
        adapter = _make_adapter(client)

        options = {
            "account_id": "acct-001",
            "total_outstanding_usd": 3000.0,
            "options": [
                {
                    "option_type": "installment_schedule",
                    "description": "3 monthly payments",
                    "proposed_amounts": [1000.0, 1000.0, 1000.0],
                    "proposed_dates": ["2026-03-01", "2026-04-01", "2026-05-01"],
                    "total_usd": 3000.0,
                }
            ],
            "llm_rationale": "Installment schedule recommended for long-standing customer.",
        }

        result = await adapter.create_payment_plan_page("acct-001", options)

        assert result == expected_page_id
        client.pages.create.assert_called_once()


class TestNotionCollectionsAdapterEventLog:
    """Collection event log append-only tests."""

    @pytest.mark.asyncio
    async def test_log_collection_event_append_only(self) -> None:
        """log_collection_event calls pages.create (append-only), NOT pages.update."""
        client = _make_mock_client()
        client.pages.create = AsyncMock(
            return_value={"id": "event-page-uuid"}
        )
        adapter = _make_adapter(client)

        await adapter.log_collection_event(
            "acct-001",
            "escalation_stage_1",
            {"stage": 1, "tone_modifier": 1.1},
        )

        # Append-only: create is called, update is NOT called
        client.pages.create.assert_called_once()
        client.pages.update.assert_not_called()
