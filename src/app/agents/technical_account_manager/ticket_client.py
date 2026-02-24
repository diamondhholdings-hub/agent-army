"""Ticket data access abstraction for TAM agent.

Reads from a Notion "Support Tickets" database where tickets are pre-synced
from Kayako/Jira via an external process. This avoids new external API
dependencies and keeps all data in Notion (unified data layer).

The sync script that populates this Notion database is outside TAM agent scope.

Exports:
    TicketClient: Async ticket data access abstraction reading from Notion DB.
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

from src.app.agents.technical_account_manager.schemas import TicketSummary

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
                "notion-client is required for TicketClient. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error
else:
    _notion_import_error = None


class TicketClient:
    """Async ticket data access abstraction reading from Notion DB.

    Queries a Notion "Support Tickets" database for ticket data that has
    been pre-synced from Kayako/Jira. All queries are retry-wrapped with
    tenacity for resilience against transient Notion API failures.

    Expected Notion DB properties:
    - Ticket ID (title): Unique identifier from the source system.
    - Account (rich_text): Account identifier.
    - Priority (select): P1, P2, P3, or P4.
    - Status (select): open, pending, resolved, or closed.
    - Created Date (date): When the ticket was created.
    - Subject (rich_text): Brief description of the issue.

    Args:
        notion_client: Pre-authenticated Notion AsyncClient instance.
        tickets_database_id: Notion database ID for the Support Tickets DB.
    """

    def __init__(
        self,
        notion_client: AsyncClient,
        tickets_database_id: str,
    ) -> None:
        if _notion_import_error is not None:
            raise ImportError(
                "notion-client is required for TicketClient. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error

        self._client = notion_client
        self._db_id = tickets_database_id

    def _parse_ticket(self, page: dict[str, Any]) -> TicketSummary:
        """Parse a Notion page into a TicketSummary model.

        Extracts ticket fields from Notion page properties and computes
        age_days from created_at to now (UTC).

        Args:
            page: Notion page dict from a database query result.

        Returns:
            TicketSummary with computed age_days.
        """
        props = page.get("properties", {})

        # Ticket ID from title property
        ticket_id_parts = props.get("Ticket ID", {}).get("title", [])
        ticket_id = ticket_id_parts[0]["plain_text"] if ticket_id_parts else ""

        # Account from rich_text property
        account_parts = props.get("Account", {}).get("rich_text", [])
        account_id = account_parts[0]["plain_text"] if account_parts else ""

        # Priority from select property
        priority_obj = props.get("Priority", {}).get("select")
        priority = priority_obj["name"] if priority_obj else "P4"

        # Status from select property
        status_obj = props.get("Status", {}).get("select")
        status = status_obj["name"].lower() if status_obj else "open"

        # Created Date from date property
        date_obj = props.get("Created Date", {}).get("date")
        if date_obj and date_obj.get("start"):
            created_at = datetime.fromisoformat(
                date_obj["start"].replace("Z", "+00:00")
            )
        else:
            created_at = datetime.now(timezone.utc)

        # Subject from rich_text property
        subject_parts = props.get("Subject", {}).get("rich_text", [])
        subject = subject_parts[0]["plain_text"] if subject_parts else ""

        # Compute age_days
        now_utc = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (now_utc - created_at).total_seconds() / 86400.0

        return TicketSummary(
            ticket_id=ticket_id,
            account_id=account_id,
            priority=priority,
            status=status,
            created_at=created_at,
            age_days=round(age_days, 2),
            subject=subject,
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def get_open_tickets(self, account_id: str) -> list[TicketSummary]:
        """Get all open/pending tickets for an account.

        Queries the Notion Support Tickets database for tickets matching
        the account with status "open" or "pending", sorted by creation
        date descending (newest first).

        Args:
            account_id: Account identifier to filter tickets for.

        Returns:
            List of TicketSummary models sorted by created_at descending.
        """
        response = await self._client.databases.query(
            database_id=self._db_id,
            filter={
                "and": [
                    {
                        "property": "Account",
                        "rich_text": {"equals": account_id},
                    },
                    {
                        "or": [
                            {
                                "property": "Status",
                                "select": {"equals": "open"},
                            },
                            {
                                "property": "Status",
                                "select": {"equals": "pending"},
                            },
                        ],
                    },
                ],
            },
            sorts=[
                {
                    "property": "Created Date",
                    "direction": "descending",
                },
            ],
        )

        tickets = [self._parse_ticket(page) for page in response.get("results", [])]
        logger.info(
            "ticket_client.get_open_tickets",
            account_id=account_id,
            count=len(tickets),
        )
        return tickets

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def get_p1_p2_tickets(self, account_id: str) -> list[TicketSummary]:
        """Get open/pending P1/P2 priority tickets for an account.

        Queries the Notion Support Tickets database for high-priority
        tickets (P1, P2) with open or pending status, sorted by age
        descending (oldest first).

        Args:
            account_id: Account identifier to filter tickets for.

        Returns:
            List of TicketSummary models sorted by age_days descending.
        """
        response = await self._client.databases.query(
            database_id=self._db_id,
            filter={
                "and": [
                    {
                        "property": "Account",
                        "rich_text": {"equals": account_id},
                    },
                    {
                        "or": [
                            {
                                "property": "Priority",
                                "select": {"equals": "P1"},
                            },
                            {
                                "property": "Priority",
                                "select": {"equals": "P2"},
                            },
                        ],
                    },
                    {
                        "or": [
                            {
                                "property": "Status",
                                "select": {"equals": "open"},
                            },
                            {
                                "property": "Status",
                                "select": {"equals": "pending"},
                            },
                        ],
                    },
                ],
            },
            sorts=[
                {
                    "property": "Created Date",
                    "direction": "ascending",
                },
            ],
        )

        tickets = [self._parse_ticket(page) for page in response.get("results", [])]
        # Sort by age_days descending (oldest first)
        tickets.sort(key=lambda t: t.age_days, reverse=True)
        logger.info(
            "ticket_client.get_p1_p2_tickets",
            account_id=account_id,
            count=len(tickets),
        )
        return tickets

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def get_ticket_count_by_account(self, account_id: str) -> int:
        """Get the count of open tickets for an account.

        Args:
            account_id: Account identifier to count tickets for.

        Returns:
            Number of open/pending tickets for the account.
        """
        response = await self._client.databases.query(
            database_id=self._db_id,
            filter={
                "and": [
                    {
                        "property": "Account",
                        "rich_text": {"equals": account_id},
                    },
                    {
                        "or": [
                            {
                                "property": "Status",
                                "select": {"equals": "open"},
                            },
                            {
                                "property": "Status",
                                "select": {"equals": "pending"},
                            },
                        ],
                    },
                ],
            },
        )

        count = len(response.get("results", []))
        logger.info(
            "ticket_client.get_ticket_count",
            account_id=account_id,
            count=count,
        )
        return count


__all__ = ["TicketClient"]
