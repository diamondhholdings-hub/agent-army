"""CRM integration layer -- pluggable adapter pattern for deal sync.

Provides abstract CRMAdapter interface with concrete implementations:
- PostgresAdapter: Always-on primary storage wrapping DealRepository
- NotionAdapter: First external CRM connector via Notion API
- SyncEngine: Bidirectional sync orchestration with field-level conflict resolution
- FieldOwnershipConfig: Defines agent/human/shared field ownership for conflict resolution

Architecture: PostgreSQL is always primary (agent always has data access).
External CRM adapters (Notion, future Salesforce/HubSpot) sync bidirectionally.
"""

from src.app.deals.crm.adapter import CRMAdapter
from src.app.deals.crm.field_mapping import (
    DEFAULT_FIELD_OWNERSHIP,
    NOTION_PROPERTY_MAP,
    from_notion_properties,
    to_notion_properties,
)
from src.app.deals.crm.notion import NotionAdapter
from src.app.deals.crm.postgres import PostgresAdapter
from src.app.deals.crm.sync import SyncEngine

__all__ = [
    "CRMAdapter",
    "PostgresAdapter",
    "NotionAdapter",
    "SyncEngine",
    "DEFAULT_FIELD_OWNERSHIP",
    "NOTION_PROPERTY_MAP",
    "to_notion_properties",
    "from_notion_properties",
]
