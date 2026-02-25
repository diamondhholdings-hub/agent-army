"""NotionCSMAdapter mock tests for CSM Notion CRUD operations.

Proves the NotionCSMAdapter methods call the correct Notion client API methods
with the expected parameters. All Notion client calls are mocked -- no real
Notion API is contacted. Covers account queries (get_account returns both id
and account_id), QBR page creation (uses database_id parent), expansion record
creation, health score updates, and block renderers.

The adapter takes a pre-authenticated AsyncClient instance via constructor,
matching the TAM adapter pattern.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.agents.customer_success.notion_adapter import (
    NotionCSMAdapter,
    render_qbr_blocks,
)
from src.app.agents.customer_success.schemas import (
    ExpansionOpportunity,
    QBRContent,
)


# -- Fixtures ----------------------------------------------------------------


def _make_mock_client() -> AsyncMock:
    """Create a mock Notion AsyncClient with standard return values.

    Mimics the notion-client library's AsyncClient interface:
    - client.pages.retrieve -> single page
    - client.pages.create -> created page with id
    - client.pages.update -> updated page with id
    - client.databases.query -> query results with results list
    - client.blocks.children.append -> appended blocks
    """
    client = AsyncMock()

    # pages.retrieve -> single page with properties
    client.pages.retrieve = AsyncMock(
        return_value={
            "id": "page-uuid-001",
            "properties": {
                "Name": {
                    "title": [{"plain_text": "Acme Corp"}],
                },
                "CSM Health Score": {"number": 75.0},
                "CSM Health RAG": {"select": {"name": "GREEN"}},
            },
        }
    )

    # pages.create -> created page
    client.pages.create = AsyncMock(
        return_value={"id": "new-page-uuid"}
    )

    # pages.update -> updated page
    client.pages.update = AsyncMock(
        return_value={"id": "page-uuid-001"}
    )

    # databases.query -> query results with one page
    client.databases.query = AsyncMock(
        return_value={
            "results": [
                {
                    "id": "page-uuid-001",
                    "properties": {
                        "Name": {
                            "title": [{"plain_text": "Acme Corp"}],
                        },
                        "CSM Health Score": {"number": 75.0},
                        "CSM Health RAG": {"select": {"name": "GREEN"}},
                        "Status": {"select": {"name": "Active"}},
                    },
                },
            ],
        }
    )

    # blocks.children.append -> appended blocks
    client.blocks.children.append = AsyncMock(
        return_value={"results": []}
    )

    return client


def _make_adapter(client: AsyncMock | None = None) -> NotionCSMAdapter:
    """Create a NotionCSMAdapter with a mock client and patched settings."""
    if client is None:
        client = _make_mock_client()

    mock_settings = MagicMock()
    mock_settings.NOTION_DATABASE_ID = "db-accounts-uuid"
    mock_settings.NOTION_CSM_HEALTH_DATABASE_ID = "db-health-uuid"
    mock_settings.NOTION_CSM_QBR_DATABASE_ID = "db-qbr-uuid"
    mock_settings.NOTION_CSM_EXPANSION_DATABASE_ID = "db-expansion-uuid"

    with patch(
        "src.app.agents.customer_success.notion_adapter.get_settings",
        return_value=mock_settings,
    ):
        adapter = NotionCSMAdapter(notion_client=client)

    # Patch settings on the instance for use in method calls
    adapter._settings = mock_settings
    return adapter


def _make_qbr_content() -> QBRContent:
    """Create a minimal QBRContent instance for testing."""
    return QBRContent(
        account_id="acct-qbr",
        period="Q1 2026",
        health_summary="Account is healthy with growing usage.",
        roi_metrics={"time_saved_hours": 120},
        feature_adoption_scorecard={"dashboard": {"adopted": True, "usage_pct": 0.85}},
        expansion_next_steps=["Expand seats", "Add analytics module"],
        trigger="quarterly",
    )


def _make_expansion_opportunity() -> ExpansionOpportunity:
    """Create a minimal ExpansionOpportunity instance for testing."""
    return ExpansionOpportunity(
        account_id="acct-exp",
        opportunity_type="seats",
        evidence="Seat utilization at 95%",
        estimated_arr_impact=50000.0,
        recommended_talk_track="Your team is maxing out seats.",
        confidence="high",
    )


# -- Tests -------------------------------------------------------------------


class TestNotionCSMAdapter:
    """Tests for NotionCSMAdapter CRUD operations."""

    @pytest.mark.asyncio
    async def test_get_account_returns_both_id_and_account_id(self):
        """get_account returns dict with both 'id' and 'account_id' keys."""
        client = _make_mock_client()
        adapter = _make_adapter(client)

        result = await adapter.get_account("page-uuid-001")

        assert "id" in result
        assert "account_id" in result
        assert result["id"] == "page-uuid-001"
        assert result["account_id"] == "page-uuid-001"

    @pytest.mark.asyncio
    async def test_get_account_returns_empty_when_not_found(self):
        """get_account returns empty dict when page retrieval fails."""
        client = _make_mock_client()
        client.pages.retrieve = AsyncMock(side_effect=Exception("Not found"))
        adapter = _make_adapter(client)

        result = await adapter.get_account("nonexistent-id")

        assert result == {}

    @pytest.mark.asyncio
    async def test_query_all_accounts_returns_list(self):
        """query_all_accounts returns a list of account dicts."""
        client = _make_mock_client()
        adapter = _make_adapter(client)

        result = await adapter.query_all_accounts()

        assert isinstance(result, list)
        assert len(result) >= 1
        # Each account should have id and account_id
        for account in result:
            assert "id" in account
            assert "account_id" in account

    @pytest.mark.asyncio
    async def test_update_health_score_calls_pages_update(self):
        """update_health_score calls client.pages.update with correct properties."""
        client = _make_mock_client()
        adapter = _make_adapter(client)

        await adapter.update_health_score("page-uuid-001", 85.0, "GREEN")

        client.pages.update.assert_called_once()
        call_kwargs = client.pages.update.call_args[1]
        assert call_kwargs["page_id"] == "page-uuid-001"
        props = call_kwargs["properties"]
        assert props["CSM Health Score"]["number"] == 85.0
        assert props["CSM Health RAG"]["select"]["name"] == "GREEN"

    @pytest.mark.asyncio
    async def test_create_qbr_page_uses_database_parent(self):
        """create_qbr_page passes parent with 'database_id', not 'page_id'."""
        client = _make_mock_client()
        adapter = _make_adapter(client)
        qbr = _make_qbr_content()

        page_id = await adapter.create_qbr_page(qbr, account_name="Acme Corp")

        assert page_id == "new-page-uuid"
        client.pages.create.assert_called_once()
        call_kwargs = client.pages.create.call_args[1]
        parent = call_kwargs["parent"]
        assert "database_id" in parent
        assert "page_id" not in parent
        assert parent["database_id"] == "db-qbr-uuid"

    @pytest.mark.asyncio
    async def test_create_expansion_record_calls_pages_create(self):
        """create_expansion_record calls client.pages.create with expansion DB parent."""
        client = _make_mock_client()
        adapter = _make_adapter(client)
        opp = _make_expansion_opportunity()

        page_id = await adapter.create_expansion_record(opp)

        assert page_id == "new-page-uuid"
        client.pages.create.assert_called_once()
        call_kwargs = client.pages.create.call_args[1]
        parent = call_kwargs["parent"]
        assert "database_id" in parent
        assert parent["database_id"] == "db-expansion-uuid"

    def test_render_qbr_blocks_produces_multiple_blocks(self):
        """render_qbr_blocks returns list with 4+ items (4 sections)."""
        qbr = _make_qbr_content()

        blocks = render_qbr_blocks(qbr)

        assert isinstance(blocks, list)
        # 4 sections minimum: heading + content for each section
        # Section 1: heading_1 + paragraph = 2
        # Section 2: heading_2 + bulleted items = 2+
        # Section 3: heading_2 + bulleted items = 2+
        # Section 4: heading_2 + bulleted items = 2+
        assert len(blocks) >= 4
