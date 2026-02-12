"""Notion CRM adapter -- first external CRM connector via Notion API.

Implements CRMAdapter for Notion databases, enabling bidirectional sync
between the agent's PostgreSQL primary storage and a Notion deal pipeline.

Key implementation details:
- Lazy data_source_id resolution (Pitfall 2: API 2025-09-03 requirement)
- All API calls wrapped with tenacity retry + exponential backoff (Pitfall 1: rate limiting)
- Graceful import handling if notion-client is not installed
- Property mapping via field_mapping.to_notion_properties / from_notion_properties

Per CONTEXT.md: "Notion database as first external connector -- structured but
flexible, good for early adopters without enterprise CRM."
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.app.deals.crm.adapter import CRMAdapter
from src.app.deals.crm.field_mapping import (
    NOTION_PROPERTY_MAP,
    from_notion_properties,
    to_notion_properties,
)
from src.app.deals.schemas import (
    ActivityCreate,
    ChangeRecord,
    ContactCreate,
    ContactUpdate,
    OpportunityCreate,
    OpportunityFilter,
    OpportunityRead,
    OpportunityUpdate,
)

logger = structlog.get_logger(__name__)

# Graceful import -- raise helpful error if notion-client not installed
try:
    from notion_client import AsyncClient
except ImportError as _import_err:
    _notion_import_error = _import_err

    class AsyncClient:  # type: ignore[no-redef]
        """Placeholder that raises ImportError on instantiation."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "notion-client is required for NotionAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error
else:
    _notion_import_error = None


class NotionAdapter(CRMAdapter):
    """Notion database adapter for CRM operations.

    Connects to a Notion database via the Notion API AsyncClient with
    retry logic and lazy data_source_id resolution.

    Args:
        token: Notion integration token (internal integration secret).
        database_id: Notion database ID for the deals pipeline.
    """

    def __init__(self, token: str, database_id: str) -> None:
        if _notion_import_error is not None:
            raise ImportError(
                "notion-client is required for NotionAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error

        self._client = AsyncClient(auth=token)
        self._database_id = database_id
        self._data_source_id: str | None = None  # Resolved lazily

    async def _ensure_data_source(self) -> str:
        """Resolve data_source_id from database (API 2025-09-03 requirement).

        Tries data_sources namespace first; if SDK doesn't support it,
        falls back to database_id directly.

        Returns:
            The data_source_id string for API calls.
        """
        if self._data_source_id is not None:
            return self._data_source_id

        try:
            db = await self._client.databases.retrieve(self._database_id)
            sources = db.get("data_sources", [])
            if sources:
                self._data_source_id = sources[0]["id"]
            else:
                self._data_source_id = self._database_id
        except Exception:
            logger.warning(
                "notion.data_source_fallback",
                database_id=self._database_id,
            )
            self._data_source_id = self._database_id

        return self._data_source_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def create_opportunity(self, opportunity: OpportunityCreate) -> str:
        """Create a page in the Notion deals database.

        Converts opportunity fields to Notion properties and creates a new page.
        Returns the Notion page ID as external_id.
        """
        await self._ensure_data_source()

        properties = to_notion_properties(
            {
                "name": opportunity.name,
                "deal_stage": opportunity.deal_stage,
                "estimated_value": opportunity.estimated_value,
                "close_date": (
                    opportunity.close_date.isoformat() if opportunity.close_date else None
                ),
                "product_line": opportunity.product_line,
                "source": opportunity.source,
            },
            NOTION_PROPERTY_MAP,
        )

        page = await self._client.pages.create(
            parent={"database_id": self._database_id},
            properties=properties,
        )

        page_id = page["id"]
        logger.info(
            "notion.opportunity_created",
            page_id=page_id,
            database_id=self._database_id,
        )
        return page_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def update_opportunity(self, external_id: str, data: OpportunityUpdate) -> None:
        """Update a Notion page's properties by page_id."""
        update_dict: dict[str, Any] = {}
        fields = data.model_dump(exclude_none=True)

        for field_name, value in fields.items():
            if field_name == "close_date" and value is not None:
                update_dict[field_name] = value.isoformat() if hasattr(value, "isoformat") else value
            else:
                update_dict[field_name] = value

        properties = to_notion_properties(update_dict, NOTION_PROPERTY_MAP)

        if properties:
            await self._client.pages.update(
                page_id=external_id,
                properties=properties,
            )
            logger.info(
                "notion.opportunity_updated",
                page_id=external_id,
                fields=list(fields.keys()),
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def get_opportunity(self, external_id: str) -> OpportunityRead | None:
        """Retrieve a Notion page by page_id and map to OpportunityRead."""
        try:
            page = await self._client.pages.retrieve(page_id=external_id)
        except Exception:
            logger.warning("notion.page_not_found", page_id=external_id)
            return None

        properties = page.get("properties", {})
        data = from_notion_properties(properties, NOTION_PROPERTY_MAP)

        return OpportunityRead(
            id=page["id"],
            tenant_id="",  # External source, no tenant_id
            account_id="",  # External source, no account_id
            external_id=page["id"],
            name=data.get("name", ""),
            product_line=data.get("product_line"),
            deal_stage=data.get("deal_stage", "prospecting"),
            estimated_value=data.get("estimated_value"),
            probability=data.get("probability", 0.1),
            close_date=None,
            detection_confidence=0.0,
            source=data.get("source", "imported"),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def list_opportunities(self, filters: OpportunityFilter) -> list[OpportunityRead]:
        """Query Notion database with optional filter on Stage."""
        notion_filter: dict[str, Any] | None = None

        if filters.deal_stage:
            notion_filter = {
                "property": "Stage",
                "select": {"equals": filters.deal_stage},
            }

        kwargs: dict[str, Any] = {"database_id": self._database_id}
        if notion_filter:
            kwargs["filter"] = notion_filter

        response = await self._client.databases.query(**kwargs)

        results: list[OpportunityRead] = []
        for page in response.get("results", []):
            properties = page.get("properties", {})
            data = from_notion_properties(properties, NOTION_PROPERTY_MAP)
            results.append(
                OpportunityRead(
                    id=page["id"],
                    tenant_id=filters.tenant_id,
                    account_id=filters.account_id or "",
                    external_id=page["id"],
                    name=data.get("name", ""),
                    product_line=data.get("product_line"),
                    deal_stage=data.get("deal_stage", "prospecting"),
                    estimated_value=data.get("estimated_value"),
                    probability=data.get("probability", 0.1),
                    close_date=None,
                    detection_confidence=0.0,
                    source=data.get("source", "imported"),
                )
            )

        return results

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def create_contact(self, contact: ContactCreate) -> str:
        """Create a contact page in the Notion database.

        Creates a page with contact information as properties.
        Returns the Notion page ID.
        """
        properties = to_notion_properties(
            {
                "contact_name": contact.contact_name,
                "contact_email": contact.contact_email,
            },
            NOTION_PROPERTY_MAP,
        )

        page = await self._client.pages.create(
            parent={"database_id": self._database_id},
            properties=properties,
        )

        page_id = page["id"]
        logger.info("notion.contact_created", page_id=page_id)
        return page_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def update_contact(self, external_id: str, data: ContactUpdate) -> None:
        """Update contact properties on a Notion page."""
        update_dict: dict[str, Any] = {}
        if data.contact_name is not None:
            update_dict["contact_name"] = data.contact_name
        if data.contact_email is not None:
            update_dict["contact_email"] = data.contact_email

        properties = to_notion_properties(update_dict, NOTION_PROPERTY_MAP)

        if properties:
            await self._client.pages.update(
                page_id=external_id,
                properties=properties,
            )
            logger.info("notion.contact_updated", page_id=external_id)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def create_activity(self, activity: ActivityCreate) -> str:
        """Append activity as a paragraph block to a Notion page.

        If related_opportunity_id is a Notion page ID, appends a block
        to that page's body. Returns a generated activity ID.
        """
        import uuid

        activity_id = str(uuid.uuid4())

        if activity.related_opportunity_id:
            block_content = (
                f"[{activity.type}] {activity.subject}: {activity.description} "
                f"({activity.timestamp.isoformat()})"
            )

            try:
                await self._client.blocks.children.append(
                    block_id=activity.related_opportunity_id,
                    children=[
                        {
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [
                                    {"type": "text", "text": {"content": block_content}}
                                ]
                            },
                        }
                    ],
                )
                logger.info(
                    "notion.activity_created",
                    activity_id=activity_id,
                    page_id=activity.related_opportunity_id,
                )
            except Exception:
                logger.warning(
                    "notion.activity_append_failed",
                    page_id=activity.related_opportunity_id,
                )

        return activity_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def get_changes_since(self, since: datetime) -> list[ChangeRecord]:
        """Query Notion for records modified since timestamp.

        Uses Last edited time filter to find changed pages.
        Returns ChangeRecord list for sync processing.
        """
        response = await self._client.databases.query(
            database_id=self._database_id,
            filter={
                "property": "Last edited time",
                "last_edited_time": {"after": since.isoformat()},
            },
        )

        changes: list[ChangeRecord] = []
        for page in response.get("results", []):
            properties = page.get("properties", {})
            data = from_notion_properties(properties, NOTION_PROPERTY_MAP)

            changes.append(
                ChangeRecord(
                    entity_type="opportunity",
                    entity_id=page["id"],
                    external_id=page["id"],
                    changed_fields=data,
                    timestamp=datetime.fromisoformat(
                        page.get("last_edited_time", since.isoformat())
                    ),
                    source="notion",
                )
            )

        return changes
