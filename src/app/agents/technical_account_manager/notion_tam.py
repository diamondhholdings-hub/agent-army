"""Notion CRM adapter for Technical Account Manager agent operations.

Provides the NotionTAMAdapter class for managing relationship profiles,
health dashboards, and communication logs as Notion sub-pages under
account pages. Also provides module-level block renderers that convert
TAM domain models into Notion block structures.

Key implementation details:
- All API calls wrapped with tenacity retry + exponential backoff
- Graceful import handling if notion-client is not installed
- Block renderers are module-level functions decoupled from adapter class
- Relationship profiles stored as sub-pages under account pages
- 100-block limit handled: create with first 100, append rest in batches

Exports:
    NotionTAMAdapter: Async Notion adapter with retry-wrapped CRUD methods.
    render_relationship_profile_blocks: Convert RelationshipProfile to blocks.
    render_health_dashboard_blocks: Convert HealthScoreResult to blocks.
    render_communication_log_blocks: Convert CommunicationRecords to blocks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.app.agents.technical_account_manager.schemas import (
    CommunicationRecord,
    CoDevOpportunity,
    FeatureAdoption,
    HealthScoreResult,
    IntegrationStatus,
    RelationshipProfile,
    StakeholderProfile,
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
                "notion-client is required for NotionTAMAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error
else:
    _notion_import_error = None


# ── Block Construction Helpers ────────────────────────────────────────────


def _heading_block(text: str, level: int = 2) -> dict:
    """Create a Notion heading block (H2 or H3).

    Args:
        text: Heading text content.
        level: Heading level (2 or 3).

    Returns:
        Notion heading block dict.
    """
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _paragraph_block(text: str) -> dict:
    """Create a Notion paragraph block.

    Args:
        text: Paragraph text content.

    Returns:
        Notion paragraph block dict.
    """
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _bulleted_list_block(text: str) -> dict:
    """Create a Notion bulleted list item block.

    Args:
        text: Bullet item text content.

    Returns:
        Notion bulleted_list_item block dict.
    """
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _callout_block(text: str, emoji: str = "!") -> dict:
    """Create a Notion callout block.

    Args:
        text: Callout text content.
        emoji: Emoji icon for the callout.

    Returns:
        Notion callout block dict.
    """
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "icon": {"type": "emoji", "emoji": emoji},
        },
    }


# ── Module-Level Block Renderers ──────────────────────────────────────────


def render_relationship_profile_blocks(
    profile: RelationshipProfile,
) -> list[dict]:
    """Convert a RelationshipProfile to Notion block objects.

    Renders the complete relationship profile as structured Notion blocks
    with sections for stakeholders, integrations, feature adoption,
    customer environment, and co-development opportunities.

    Args:
        profile: RelationshipProfile instance to render.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []

    # Title heading
    blocks.append(
        _heading_block(
            f"Technical Relationship Profile - {profile.account_name}",
            level=2,
        )
    )

    # ── Stakeholder Map ───────────────────────────────────────────────
    blocks.append(_heading_block("Stakeholder Map", level=3))
    if profile.stakeholders:
        for s in profile.stakeholders:
            notes_suffix = f" | Notes: {s.notes}" if s.notes else ""
            blocks.append(
                _bulleted_list_block(
                    f"{s.name}: {s.role} | Maturity: {s.technical_maturity}"
                    f"{notes_suffix}"
                )
            )
    else:
        blocks.append(_paragraph_block("No stakeholders recorded."))

    # ── Integration Depth ─────────────────────────────────────────────
    blocks.append(_heading_block("Integration Depth", level=3))
    if profile.integrations:
        for i in profile.integrations:
            status = "Active" if i.is_active else "Inactive"
            since_suffix = f" | Since: {i.since}" if i.since else ""
            blocks.append(
                _bulleted_list_block(
                    f"{i.integration_name}: {status}{since_suffix}"
                )
            )
    else:
        blocks.append(_paragraph_block("No integrations recorded."))

    # ── Feature Adoption ──────────────────────────────────────────────
    blocks.append(_heading_block("Feature Adoption", level=3))
    if profile.feature_adoption:
        for f in profile.feature_adoption:
            adopted = "In Use" if f.adopted else "Not Adopted"
            blocks.append(
                _bulleted_list_block(
                    f"{f.feature_name}: {adopted} | Source: {f.source}"
                )
            )
    else:
        blocks.append(_paragraph_block("No feature adoption data."))

    # ── Customer Environment ──────────────────────────────────────────
    blocks.append(_heading_block("Customer Environment", level=3))
    if profile.customer_environment:
        for env_item in profile.customer_environment:
            blocks.append(_bulleted_list_block(env_item))
    else:
        blocks.append(_paragraph_block("No environment data recorded."))

    # ── Co-Development Opportunities ──────────────────────────────────
    blocks.append(_heading_block("Co-Development Opportunities", level=3))
    if profile.co_dev_opportunities:
        for opp in profile.co_dev_opportunities:
            dispatched = " [Dispatched to Sales]" if opp.dispatched_to_sales else ""
            blocks.append(
                _bulleted_list_block(
                    f"{opp.opportunity_name}: {opp.description} "
                    f"| Status: {opp.status}{dispatched}"
                )
            )
    else:
        blocks.append(_paragraph_block("No co-development opportunities identified."))

    return blocks


def render_health_dashboard_blocks(
    health_score: HealthScoreResult,
) -> list[dict]:
    """Convert a HealthScoreResult to Notion health dashboard blocks.

    Renders the health score, RAG status, scan timestamp, trend
    indicator, and escalation warning (if applicable).

    Args:
        health_score: HealthScoreResult instance to render.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []

    blocks.append(_heading_block("Health Dashboard", level=3))

    # Current score and RAG status
    blocks.append(
        _paragraph_block(
            f"Current Score: {health_score.score}/100 "
            f"| Status: {health_score.rag_status}"
        )
    )

    # Last scan timestamp
    scan_time = health_score.scan_timestamp.strftime("%Y-%m-%d %H:%M UTC")
    blocks.append(_paragraph_block(f"Last Scan: {scan_time}"))

    # Trend indicator (if previous score available)
    if health_score.previous_score is not None:
        delta = health_score.score - health_score.previous_score
        if delta > 0:
            trend = "Improving"
        elif delta < 0:
            trend = "Declining"
        else:
            trend = "Stable"
        blocks.append(
            _paragraph_block(
                f"Trend: {trend} (delta: {delta:+d} from previous "
                f"score of {health_score.previous_score})"
            )
        )

    # Escalation warning callout
    if health_score.should_escalate:
        blocks.append(
            _callout_block(
                "ESCALATION TRIGGERED: Health score requires immediate "
                "attention. Check open tickets and integration status.",
                emoji="!",
            )
        )

    return blocks


def render_communication_log_blocks(
    records: list[CommunicationRecord],
) -> list[dict]:
    """Convert CommunicationRecords to Notion communication log blocks.

    Renders each communication record as a bulleted list item with
    date, type, subject, and outcome.

    Args:
        records: List of CommunicationRecord instances to render.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []

    blocks.append(_heading_block("Communication History", level=3))

    if not records:
        blocks.append(_paragraph_block("No communications recorded."))
        return blocks

    for record in records:
        comm_type = record.communication_type.replace("_", " ").title()
        outcome_suffix = f" | Outcome: {record.outcome}" if record.outcome else ""
        blocks.append(
            _bulleted_list_block(
                f"{record.date} | {comm_type} | {record.subject}"
                f"{outcome_suffix}"
            )
        )

    return blocks


# ── Notion TAM Adapter ────────────────────────────────────────────────────


class NotionTAMAdapter:
    """Notion database adapter for TAM relationship profiles and health dashboards.

    Creates and manages Technical Relationship Profile sub-pages under
    account pages in Notion. Updates health score properties on account
    pages and appends communication log entries.

    Notion structure:
        Account Page (existing)
          |-- Technical Relationship Profile (sub-page, created by TAM)
                |-- Stakeholder Map (section)
                |-- Integration Depth (section)
                |-- Feature Adoption (section)
                |-- Customer Environment (section)
                |-- Co-Dev Opportunities (section)
                |-- Health Dashboard (section with score + RAG)
                |-- Communication History (section)

    Args:
        client: Notion AsyncClient instance (pre-authenticated).
        accounts_database_id: Optional Notion database ID for the
            Accounts/Deals database. Required for query_all_accounts.
    """

    def __init__(
        self,
        client: AsyncClient,
        accounts_database_id: str | None = None,
    ) -> None:
        if _notion_import_error is not None:
            raise ImportError(
                "notion-client is required for NotionTAMAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error

        self._client = client
        self._accounts_db_id = accounts_database_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def create_relationship_profile(
        self,
        account_page_id: str,
        profile: RelationshipProfile,
    ) -> str:
        """Create a Technical Relationship Profile sub-page under an account.

        Renders the profile and health dashboard as Notion blocks, then
        creates a sub-page under the specified account page. Handles the
        100-block Notion API limit by creating with the first batch and
        appending the remainder.

        Args:
            account_page_id: Notion page ID of the parent account page.
            profile: RelationshipProfile with all relationship data.

        Returns:
            The Notion page ID (UUID) of the created sub-page.
        """
        # Render all blocks
        blocks: list[dict] = []
        blocks.extend(render_relationship_profile_blocks(profile))

        # Add health dashboard if score is available
        if profile.health_score is not None and profile.health_rag is not None:
            health_result = HealthScoreResult(
                account_id=profile.account_id,
                score=profile.health_score,
                rag_status=profile.health_rag,
                scan_timestamp=(
                    profile.last_health_scan
                    or datetime.now(timezone.utc)
                ),
            )
            blocks.extend(render_health_dashboard_blocks(health_result))

        # Create sub-page with first 100 blocks (Notion API limit)
        page = await self._client.pages.create(
            parent={"page_id": account_page_id},
            properties={
                "title": [
                    {
                        "type": "text",
                        "text": {
                            "content": (
                                f"Technical Relationship Profile - "
                                f"{profile.account_name}"
                            ),
                        },
                    }
                ],
            },
            children=blocks[:100],
        )

        page_id = page["id"]

        # Append remaining blocks in batches of 100
        remaining = blocks[100:]
        while remaining:
            batch = remaining[:100]
            remaining = remaining[100:]
            await self._client.blocks.children.append(
                block_id=page_id,
                children=batch,
            )

        logger.info(
            "notion_tam.relationship_profile_created",
            page_id=page_id,
            account_page_id=account_page_id,
            account_name=profile.account_name,
            block_count=len(blocks),
        )
        return page_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def update_health_score(
        self,
        account_page_id: str,
        score: int,
        rag_status: str,
    ) -> None:
        """Update health score and RAG status on an account page.

        Updates the "Health Score" (number), "Health Status" (select),
        and "Last Health Scan" (date) properties on the account page.

        Args:
            account_page_id: Notion page ID of the account page.
            score: Health score (0-100).
            rag_status: RAG status ("Green", "Amber", "Red").
        """
        await self._client.pages.update(
            page_id=account_page_id,
            properties={
                "Health Score": {"number": score},
                "Health Status": {"select": {"name": rag_status}},
                "Last Health Scan": {
                    "date": {
                        "start": datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%S.000Z"
                        ),
                    },
                },
            },
        )
        logger.info(
            "notion_tam.health_score_updated",
            account_page_id=account_page_id,
            score=score,
            rag_status=rag_status,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def append_communication_log(
        self,
        profile_page_id: str,
        record: CommunicationRecord,
    ) -> None:
        """Append a communication record to the relationship profile sub-page.

        Renders the record as Notion blocks and appends them to the
        existing relationship profile page.

        Args:
            profile_page_id: Notion page ID of the relationship profile sub-page.
            record: CommunicationRecord to append.
        """
        blocks = render_communication_log_blocks([record])
        await self._client.blocks.children.append(
            block_id=profile_page_id,
            children=blocks,
        )
        logger.info(
            "notion_tam.communication_log_appended",
            profile_page_id=profile_page_id,
            communication_type=record.communication_type,
            subject=record.subject,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def query_all_accounts(self) -> list[dict]:
        """Query all active accounts from the Accounts database.

        Returns a list of account dicts with id, name, and health
        properties for the daily health scan.

        Returns:
            List of account dicts with keys: id, name, health_score,
            health_rag, last_heartbeat, hours_since_heartbeat.

        Raises:
            ValueError: If accounts_database_id was not configured.
        """
        if self._accounts_db_id is None:
            raise ValueError(
                "accounts_database_id not configured. "
                "Pass it in the NotionTAMAdapter constructor."
            )

        response = await self._client.databases.query(
            database_id=self._accounts_db_id,
            filter={
                "property": "Status",
                "select": {"does_not_equal": "Inactive"},
            },
        )

        accounts: list[dict] = []
        for page in response.get("results", []):
            props = page.get("properties", {})

            # Extract account name from title property
            name_parts = props.get("Name", {}).get("title", [])
            name = name_parts[0]["plain_text"] if name_parts else "Unknown"

            # Extract health properties
            health_score_prop = props.get("Health Score", {}).get("number")
            health_status_prop = props.get("Health Status", {}).get("select")
            health_rag = (
                health_status_prop["name"] if health_status_prop else None
            )

            # Extract heartbeat data
            last_heartbeat_prop = props.get("Last Heartbeat", {}).get("date")
            last_heartbeat = None
            hours_since_heartbeat = None
            if last_heartbeat_prop and last_heartbeat_prop.get("start"):
                last_heartbeat = last_heartbeat_prop["start"]
                try:
                    hb_dt = datetime.fromisoformat(
                        last_heartbeat.replace("Z", "+00:00")
                    )
                    if hb_dt.tzinfo is None:
                        hb_dt = hb_dt.replace(tzinfo=timezone.utc)
                    delta = datetime.now(timezone.utc) - hb_dt
                    hours_since_heartbeat = delta.total_seconds() / 3600.0
                except (ValueError, TypeError):
                    pass

            accounts.append(
                {
                    "id": page["id"],
                    "name": name,
                    "health_score": health_score_prop,
                    "health_rag": health_rag,
                    "last_heartbeat": last_heartbeat,
                    "hours_since_heartbeat": hours_since_heartbeat,
                }
            )

        logger.info(
            "notion_tam.query_all_accounts",
            account_count=len(accounts),
        )
        return accounts

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def get_relationship_profile_page(
        self,
        account_page_id: str,
    ) -> str | None:
        """Find the Technical Relationship Profile sub-page under an account.

        Searches children of the account page for a page with a title
        starting with "Technical Relationship Profile".

        Args:
            account_page_id: Notion page ID of the account page.

        Returns:
            Page ID of the relationship profile sub-page if found,
            None otherwise.
        """
        response = await self._client.blocks.children.list(
            block_id=account_page_id,
        )

        for block in response.get("results", []):
            if block.get("type") == "child_page":
                title = block.get("child_page", {}).get("title", "")
                if title.startswith("Technical Relationship Profile"):
                    return block["id"]

        return None


__all__ = [
    "NotionTAMAdapter",
    "render_relationship_profile_blocks",
    "render_health_dashboard_blocks",
    "render_communication_log_blocks",
]
