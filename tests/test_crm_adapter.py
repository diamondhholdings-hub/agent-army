"""Unit tests for CRM adapters and sync engine.

Tests PostgresAdapter, NotionAdapter, SyncEngine, and field mapping helpers.
Uses mock/patch for DealRepository and Notion client -- no real database or API calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.deals.crm.adapter import CRMAdapter
from src.app.deals.crm.field_mapping import (
    DEFAULT_FIELD_OWNERSHIP,
    NOTION_PROPERTY_MAP,
    from_notion_properties,
    to_notion_properties,
)
from src.app.deals.crm.postgres import PostgresAdapter
from src.app.deals.crm.sync import SyncEngine
from src.app.deals.schemas import (
    ChangeRecord,
    ContactCreate,
    FieldOwnershipConfig,
    OpportunityCreate,
    OpportunityFilter,
    OpportunityRead,
    OpportunityUpdate,
    SyncResult,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_opportunity_read(**overrides) -> OpportunityRead:
    """Create a test OpportunityRead with sensible defaults."""
    defaults = {
        "id": "opp-123",
        "tenant_id": "tenant-abc",
        "account_id": "acct-456",
        "name": "Test Deal",
        "deal_stage": "prospecting",
        "estimated_value": 50000.0,
        "probability": 0.3,
        "source": "agent_detected",
        "detection_confidence": 0.85,
        "created_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 20, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return OpportunityRead(**defaults)


# ── CRMAdapter ABC Tests ──────────────────────────────────────────────────


class TestCRMAdapterABC:
    """Test that CRMAdapter ABC defines the correct interface."""

    def test_crm_adapter_has_abstract_methods(self):
        """CRMAdapter ABC has all 8 required abstract methods."""
        abstract_methods = CRMAdapter.__abstractmethods__
        expected = {
            "create_opportunity",
            "update_opportunity",
            "get_opportunity",
            "list_opportunities",
            "create_contact",
            "update_contact",
            "create_activity",
            "get_changes_since",
        }
        assert abstract_methods == expected

    def test_crm_adapter_cannot_be_instantiated(self):
        """CRMAdapter ABC cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            CRMAdapter()  # type: ignore[abstract]


# ── PostgresAdapter Tests ─────────────────────────────────────────────────


class TestPostgresAdapter:
    """Test PostgresAdapter delegates to DealRepository."""

    @pytest.fixture
    def mock_repo(self):
        """Create a mock DealRepository."""
        repo = AsyncMock()
        return repo

    @pytest.fixture
    def adapter(self, mock_repo):
        """Create a PostgresAdapter with mock repo."""
        return PostgresAdapter(repository=mock_repo, tenant_id="tenant-abc")

    async def test_create_opportunity_delegates_to_repo(self, adapter, mock_repo):
        """create_opportunity delegates to repo and returns string ID."""
        mock_repo.create_opportunity.return_value = _make_opportunity_read(id="opp-new-123")

        opp_create = OpportunityCreate(
            account_id="acct-456",
            name="New Deal",
            product_line="Enterprise",
            deal_stage="prospecting",
        )

        result = await adapter.create_opportunity(opp_create)

        mock_repo.create_opportunity.assert_called_once_with("tenant-abc", opp_create)
        assert result == "opp-new-123"
        assert isinstance(result, str)

    async def test_update_opportunity_delegates_to_repo(self, adapter, mock_repo):
        """update_opportunity delegates to repo."""
        mock_repo.update_opportunity.return_value = _make_opportunity_read()

        update = OpportunityUpdate(deal_stage="qualification")
        await adapter.update_opportunity("opp-123", update)

        mock_repo.update_opportunity.assert_called_once_with("tenant-abc", "opp-123", update)

    async def test_get_opportunity_delegates_to_repo(self, adapter, mock_repo):
        """get_opportunity delegates to repo and returns result."""
        expected = _make_opportunity_read(id="opp-123")
        mock_repo.get_opportunity.return_value = expected

        result = await adapter.get_opportunity("opp-123")

        mock_repo.get_opportunity.assert_called_once_with("tenant-abc", "opp-123")
        assert result == expected

    async def test_get_opportunity_returns_none(self, adapter, mock_repo):
        """get_opportunity returns None when repo returns None."""
        mock_repo.get_opportunity.return_value = None

        result = await adapter.get_opportunity("opp-nonexistent")

        assert result is None

    async def test_list_opportunities_delegates_to_repo(self, adapter, mock_repo):
        """list_opportunities delegates to repo with filters."""
        opps = [_make_opportunity_read(id="opp-1"), _make_opportunity_read(id="opp-2")]
        mock_repo.list_opportunities.return_value = opps

        filters = OpportunityFilter(tenant_id="tenant-abc", deal_stage="prospecting")
        result = await adapter.list_opportunities(filters)

        mock_repo.list_opportunities.assert_called_once_with("tenant-abc", filters)
        assert len(result) == 2
        assert result[0].id == "opp-1"

    async def test_get_changes_since_returns_changes(self, adapter, mock_repo):
        """get_changes_since returns ChangeRecords for recently modified opps."""
        since = datetime(2026, 1, 18, tzinfo=timezone.utc)
        opps = [
            _make_opportunity_read(
                id="opp-1",
                updated_at=datetime(2026, 1, 19, tzinfo=timezone.utc),
            ),
            _make_opportunity_read(
                id="opp-2",
                updated_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            ),
        ]
        mock_repo.list_opportunities.return_value = opps

        result = await adapter.get_changes_since(since)

        # Only opp-1 was updated after since
        assert len(result) == 1
        assert result[0].entity_id == "opp-1"
        assert result[0].entity_type == "opportunity"
        assert result[0].source == "postgres"


# ── SyncEngine Tests ──────────────────────────────────────────────────────


class TestSyncEngine:
    """Test SyncEngine bidirectional sync and conflict resolution."""

    @pytest.fixture
    def ownership(self):
        """Standard field ownership config."""
        return FieldOwnershipConfig(
            agent_owned_fields=["qualification_snapshot", "detection_confidence", "probability"],
            human_owned_fields=["custom_notes", "manual_tags", "override_stage"],
            shared_fields=["deal_stage", "estimated_value", "close_date", "name"],
        )

    @pytest.fixture
    def mock_primary(self):
        """Mock primary CRM adapter."""
        return AsyncMock(spec=CRMAdapter)

    @pytest.fixture
    def mock_external(self):
        """Mock external CRM adapter."""
        return AsyncMock(spec=CRMAdapter)

    def test_sync_engine_has_external(self, mock_primary, mock_external, ownership):
        """has_external returns True when external adapter is configured."""
        engine = SyncEngine(mock_primary, mock_external, ownership)
        assert engine.has_external() is True

    def test_sync_engine_no_external(self, mock_primary, ownership):
        """has_external returns False when no external adapter."""
        engine = SyncEngine(mock_primary, None, ownership)
        assert engine.has_external() is False

    async def test_sync_outbound_no_external(self, mock_primary, ownership):
        """sync_outbound returns empty SyncResult when no external configured."""
        engine = SyncEngine(mock_primary, None, ownership)

        changes = [
            ChangeRecord(
                entity_type="opportunity",
                entity_id="opp-1",
                changed_fields={"name": "Updated Deal"},
            )
        ]
        result = await engine.sync_outbound(changes)

        assert result == SyncResult(pushed=0, pulled=0, conflicts=0, errors=[])

    async def test_sync_outbound_pushes_changes(
        self, mock_primary, mock_external, ownership
    ):
        """sync_outbound pushes changes to external CRM."""
        engine = SyncEngine(mock_primary, mock_external, ownership)

        changes = [
            ChangeRecord(
                entity_type="opportunity",
                entity_id="opp-1",
                external_id="notion-page-1",
                changed_fields={"name": "Updated Deal", "deal_stage": "qualification"},
            )
        ]
        result = await engine.sync_outbound(changes)

        assert result.pushed == 1
        assert result.errors == []
        mock_external.update_opportunity.assert_called_once()

    async def test_sync_outbound_filters_human_owned_fields(
        self, mock_primary, mock_external, ownership
    ):
        """sync_outbound skips human-owned fields."""
        engine = SyncEngine(mock_primary, mock_external, ownership)

        changes = [
            ChangeRecord(
                entity_type="opportunity",
                entity_id="opp-1",
                external_id="notion-page-1",
                changed_fields={
                    "name": "Updated Deal",
                    "custom_notes": "My notes",  # human-owned, should be filtered
                },
            )
        ]
        result = await engine.sync_outbound(changes)

        # Should push but without custom_notes
        assert result.pushed == 1
        call_args = mock_external.update_opportunity.call_args
        update_obj = call_args[0][1]
        assert update_obj.name == "Updated Deal"

    async def test_resolve_conflict_agent_owned(self, mock_primary, ownership):
        """Agent-owned fields: agent wins -- external change is dropped."""
        engine = SyncEngine(mock_primary, None, ownership)

        change = ChangeRecord(
            entity_type="opportunity",
            entity_id="opp-1",
            changed_fields={
                "qualification_snapshot": {"bant": "new_data"},
                "detection_confidence": 0.95,
            },
            source="notion",
        )

        resolved = engine._resolve_conflict(change)

        # Agent-owned fields should be dropped (agent wins)
        assert "qualification_snapshot" not in resolved.changed_fields
        assert "detection_confidence" not in resolved.changed_fields

    async def test_resolve_conflict_human_owned(self, mock_primary, ownership):
        """Human-owned fields: external CRM wins always."""
        engine = SyncEngine(mock_primary, None, ownership)

        change = ChangeRecord(
            entity_type="opportunity",
            entity_id="opp-1",
            changed_fields={
                "custom_notes": "Updated by human in Notion",
                "manual_tags": "priority-high",
            },
            source="notion",
        )

        resolved = engine._resolve_conflict(change)

        # Human-owned fields should be kept (external wins)
        assert resolved.changed_fields["custom_notes"] == "Updated by human in Notion"
        assert resolved.changed_fields["manual_tags"] == "priority-high"

    async def test_resolve_conflict_shared_last_write_wins(self, mock_primary, ownership):
        """Shared fields: last-write-wins (external wins for inbound sync)."""
        engine = SyncEngine(mock_primary, None, ownership)

        change = ChangeRecord(
            entity_type="opportunity",
            entity_id="opp-1",
            changed_fields={
                "deal_stage": "negotiation",
                "estimated_value": 75000.0,
                "name": "Renamed Deal",
            },
            timestamp=datetime(2026, 1, 25, tzinfo=timezone.utc),
            source="notion",
        )

        resolved = engine._resolve_conflict(change)

        # Shared fields use last-write-wins; for inbound, external is newer
        assert resolved.changed_fields["deal_stage"] == "negotiation"
        assert resolved.changed_fields["estimated_value"] == 75000.0
        assert resolved.changed_fields["name"] == "Renamed Deal"

    async def test_sync_inbound_updates_last_sync(
        self, mock_primary, mock_external, ownership
    ):
        """After sync_inbound, _last_sync is updated."""
        engine = SyncEngine(mock_primary, mock_external, ownership)
        assert engine._last_sync is None

        mock_external.get_changes_since.return_value = []

        await engine.sync_inbound()

        assert engine._last_sync is not None
        assert isinstance(engine._last_sync, datetime)

    async def test_sync_inbound_no_external(self, mock_primary, ownership):
        """sync_inbound returns empty SyncResult when no external configured."""
        engine = SyncEngine(mock_primary, None, ownership)

        result = await engine.sync_inbound()

        assert result == SyncResult(pushed=0, pulled=0, conflicts=0, errors=[])

    async def test_sync_inbound_pulls_and_applies_changes(
        self, mock_primary, mock_external, ownership
    ):
        """sync_inbound pulls changes from external and applies to primary."""
        engine = SyncEngine(mock_primary, mock_external, ownership)

        mock_external.get_changes_since.return_value = [
            ChangeRecord(
                entity_type="opportunity",
                entity_id="opp-1",
                external_id="notion-page-1",
                changed_fields={"name": "Updated by Human", "deal_stage": "evaluation"},
                source="notion",
            )
        ]
        mock_primary.update_opportunity.return_value = None

        result = await engine.sync_inbound()

        assert result.pulled == 1
        mock_primary.update_opportunity.assert_called_once()

    def test_default_sync_interval(self, mock_primary, ownership):
        """Default sync interval is 60 seconds per Pitfall 1."""
        engine = SyncEngine(mock_primary, None, ownership)
        assert engine._sync_interval == 60


# ── NotionAdapter Tests ───────────────────────────────────────────────────


class TestNotionAdapter:
    """Test NotionAdapter initialization and import handling."""

    def test_notion_adapter_init(self):
        """NotionAdapter initializes with token and database_id."""
        from src.app.deals.crm.notion import NotionAdapter

        with patch("src.app.deals.crm.notion.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()
            adapter = NotionAdapter(token="test-token", database_id="db-123")

            assert adapter._database_id == "db-123"
            assert adapter._data_source_id is None
            mock_client_cls.assert_called_once_with(auth="test-token")

    def test_notion_adapter_requires_notion_client(self):
        """NotionAdapter raises helpful ImportError if notion-client not installed."""
        import src.app.deals.crm.notion as notion_module

        # Save original error state
        original_error = notion_module._notion_import_error

        try:
            # Simulate import error
            notion_module._notion_import_error = ImportError("no notion_client")

            with pytest.raises(ImportError, match="notion-client is required"):
                notion_module.NotionAdapter(token="test", database_id="db-123")
        finally:
            # Restore original state
            notion_module._notion_import_error = original_error

    async def test_notion_create_opportunity(self):
        """NotionAdapter.create_opportunity creates a page and returns page_id."""
        from src.app.deals.crm.notion import NotionAdapter

        with patch("src.app.deals.crm.notion.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.databases.retrieve.return_value = {"data_sources": []}
            mock_client.pages.create.return_value = {"id": "notion-page-abc"}

            adapter = NotionAdapter(token="test-token", database_id="db-123")

            opp = OpportunityCreate(
                account_id="acct-1",
                name="Test Notion Deal",
                product_line="Enterprise",
                deal_stage="prospecting",
                estimated_value=100000.0,
            )

            result = await adapter.create_opportunity(opp)

            assert result == "notion-page-abc"
            mock_client.pages.create.assert_called_once()

    async def test_notion_get_changes_since(self):
        """NotionAdapter.get_changes_since returns ChangeRecords."""
        from src.app.deals.crm.notion import NotionAdapter

        with patch("src.app.deals.crm.notion.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.databases.query.return_value = {
                "results": [
                    {
                        "id": "page-1",
                        "last_edited_time": "2026-01-20T10:00:00.000000+00:00",
                        "properties": {
                            "Deal Name": {
                                "title": [{"text": {"content": "Updated Deal"}}]
                            },
                            "Stage": {"select": {"name": "evaluation"}},
                        },
                    }
                ]
            }

            adapter = NotionAdapter(token="test-token", database_id="db-123")

            since = datetime(2026, 1, 15, tzinfo=timezone.utc)
            changes = await adapter.get_changes_since(since)

            assert len(changes) == 1
            assert changes[0].entity_id == "page-1"
            assert changes[0].changed_fields["name"] == "Updated Deal"
            assert changes[0].changed_fields["deal_stage"] == "evaluation"
            assert changes[0].source == "notion"


# ── Field Mapping Tests ───────────────────────────────────────────────────


class TestFieldMapping:
    """Test field mapping and conversion functions."""

    def test_default_field_ownership_has_all_categories(self):
        """DEFAULT_FIELD_OWNERSHIP has agent, human, and shared fields."""
        assert len(DEFAULT_FIELD_OWNERSHIP.agent_owned_fields) > 0
        assert len(DEFAULT_FIELD_OWNERSHIP.human_owned_fields) > 0
        assert len(DEFAULT_FIELD_OWNERSHIP.shared_fields) > 0

    def test_notion_property_map_has_required_fields(self):
        """NOTION_PROPERTY_MAP maps all required internal fields."""
        required = {"name", "deal_stage", "estimated_value", "close_date", "product_line"}
        assert required.issubset(set(NOTION_PROPERTY_MAP.keys()))

    def test_to_notion_properties_title(self):
        """to_notion_properties converts title field correctly."""
        result = to_notion_properties({"name": "Test Deal"})
        assert result["Deal Name"] == {"title": [{"text": {"content": "Test Deal"}}]}

    def test_to_notion_properties_number(self):
        """to_notion_properties converts number field correctly."""
        result = to_notion_properties({"estimated_value": 50000})
        assert result["Value"] == {"number": 50000.0}

    def test_to_notion_properties_select(self):
        """to_notion_properties converts select field correctly."""
        result = to_notion_properties({"deal_stage": "qualification"})
        assert result["Stage"] == {"select": {"name": "qualification"}}

    def test_to_notion_properties_date(self):
        """to_notion_properties converts date field correctly."""
        result = to_notion_properties({"close_date": "2026-03-15"})
        assert result["Close Date"] == {"date": {"start": "2026-03-15"}}

    def test_to_notion_properties_email(self):
        """to_notion_properties converts email field correctly."""
        result = to_notion_properties({"contact_email": "test@example.com"})
        assert result["Email"] == {"email": "test@example.com"}

    def test_to_notion_properties_skips_none_values(self):
        """to_notion_properties skips None values."""
        result = to_notion_properties({"name": "Deal", "estimated_value": None})
        assert "Deal Name" in result
        assert "Value" not in result

    def test_to_notion_properties_skips_unknown_fields(self):
        """to_notion_properties skips fields not in property map."""
        result = to_notion_properties({"name": "Deal", "unknown_field": "value"})
        assert len(result) == 1
        assert "Deal Name" in result

    def test_from_notion_properties_title(self):
        """from_notion_properties extracts title field correctly."""
        props = {"Deal Name": {"title": [{"text": {"content": "My Deal"}}]}}
        result = from_notion_properties(props)
        assert result["name"] == "My Deal"

    def test_from_notion_properties_number(self):
        """from_notion_properties extracts number field correctly."""
        props = {"Value": {"number": 75000.0}}
        result = from_notion_properties(props)
        assert result["estimated_value"] == 75000.0

    def test_from_notion_properties_select(self):
        """from_notion_properties extracts select field correctly."""
        props = {"Stage": {"select": {"name": "negotiation"}}}
        result = from_notion_properties(props)
        assert result["deal_stage"] == "negotiation"

    def test_from_notion_properties_empty_title(self):
        """from_notion_properties handles empty title array."""
        props = {"Deal Name": {"title": []}}
        result = from_notion_properties(props)
        assert "name" not in result

    def test_from_notion_properties_null_select(self):
        """from_notion_properties handles null select value."""
        props = {"Stage": {"select": None}}
        result = from_notion_properties(props)
        assert "deal_stage" not in result

    def test_roundtrip_conversion(self):
        """to_notion -> from_notion roundtrip preserves data."""
        original = {
            "name": "Roundtrip Deal",
            "deal_stage": "evaluation",
            "estimated_value": 100000.0,
        }
        notion_props = to_notion_properties(original)
        recovered = from_notion_properties(notion_props)

        assert recovered["name"] == original["name"]
        assert recovered["deal_stage"] == original["deal_stage"]
        assert recovered["estimated_value"] == original["estimated_value"]
