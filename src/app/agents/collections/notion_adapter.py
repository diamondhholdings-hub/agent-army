"""Notion CRM adapter for Collections Agent operations.

Provides the NotionCollectionsAdapter class for managing AR invoice data,
escalation state, payment plan pages, and collection event logs in Notion.
Also provides module-level block renderer helpers that convert options dicts
and text into Notion block structures.

Key implementation details:
- All API calls wrapped with tenacity retry + exponential backoff
- Graceful import handling if notion-client is not installed
- Block renderers are module-level functions decoupled from adapter class
- Pre-authenticated AsyncClient injected via constructor (same as CSM/TAM)
- All methods fail-open: log errors, don't raise, return safe defaults

Exports:
    NotionCollectionsAdapter: Async Notion adapter with 6 async methods.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.app.agents.collections.schemas import (
    ARAgingBucket,
    ARAgingReport,
    EscalationState,
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
                "notion-client is required for NotionCollectionsAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error

else:
    _notion_import_error = None


# ── Block Construction Helpers ────────────────────────────────────────────


def _make_heading(text: str, level: int = 2) -> dict:
    """Create a Notion heading block.

    Args:
        text: Heading text content.
        level: Heading level (1, 2, or 3). Defaults to 2.

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


def _make_paragraph(text: str) -> dict:
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


def _make_option_bullet(option: dict) -> dict:
    """Create a Notion bulleted list item block for a payment plan option.

    Renders a payment plan option dict as a single bulleted item containing
    its type, description, and total amount.

    Args:
        option: Payment plan option dict with keys like option_type,
            description, total_usd, proposed_amounts, proposed_dates.

    Returns:
        Notion bulleted_list_item block dict.
    """
    option_type = option.get("option_type", "unknown")
    description = option.get("description", "")
    total_usd = option.get("total_usd", 0.0)
    text = f"{option_type}: {description} (Total: ${total_usd:,.2f})"

    proposed_amounts = option.get("proposed_amounts", [])
    proposed_dates = option.get("proposed_dates", [])
    if proposed_amounts and proposed_dates:
        schedule_parts = [
            f"${amt:,.2f} on {dt}"
            for amt, dt in zip(proposed_amounts, proposed_dates)
        ]
        text += " — " + ", ".join(schedule_parts)

    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


# ── Notion Collections Adapter ────────────────────────────────────────────


class NotionCollectionsAdapter:
    """Notion database adapter for Collections Agent: AR aging, escalation state,
    payment plans, and event logging.

    Manages three Collections-specific Notion databases:
    - AR invoices tracking DB (for aging reports and delinquent account scans)
    - Escalation state DB (per-account escalation stage persistence)
    - Collections events DB (append-only audit log)

    All methods fail-open: on error, log and return a safe default value
    rather than raising.

    Args:
        notion_client: Pre-authenticated Notion AsyncClient instance.
        ar_database_id: Notion database ID for AR invoices (keyword-only).
        escalation_database_id: Notion database ID for escalation state
            records (keyword-only).
        events_database_id: Notion database ID for collection event log
            (keyword-only).
    """

    def __init__(
        self,
        notion_client: AsyncClient,
        *,
        ar_database_id: str,
        escalation_database_id: str,
        events_database_id: str,
    ) -> None:
        if _notion_import_error is not None:
            raise ImportError(
                "notion-client is required for NotionCollectionsAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error

        self._client = notion_client
        self._ar_db = ar_database_id
        self._esc_db = escalation_database_id
        self._events_db = events_database_id

    # ── AR Aging ─────────────────────────────────────────────────────────

    async def get_ar_aging(self, account_id: str) -> ARAgingReport:
        """Query the AR DB and build an ARAgingReport with 4 aging buckets.

        Filters AR invoice records by account_id AND status=="outstanding",
        groups them into the 4 standard aging buckets by days_overdue
        (0-30, 31-60, 61-90, 90+), and returns a complete ARAgingReport.

        Fails-open: on any error returns an empty ARAgingReport for the
        account.

        Args:
            account_id: Account identifier to query AR records for.

        Returns:
            ARAgingReport populated with outstanding invoices, or an empty
            report with zero buckets if no invoices found or on error.
        """
        try:
            return await self._fetch_ar_aging(account_id)
        except Exception:
            logger.exception(
                "notion_collections.get_ar_aging_error",
                account_id=account_id,
            )
            # Fail-open: return empty report
            today = date.today()
            return ARAgingReport(
                account_id=account_id,
                account_name="Unknown",
                total_outstanding_usd=0.0,
                buckets=[],
                oldest_invoice_number="",
                oldest_invoice_amount_usd=0.0,
                oldest_invoice_date=today,
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def _fetch_ar_aging(self, account_id: str) -> ARAgingReport:
        """Internal retry-wrapped AR aging query."""
        response = await self._client.databases.query(
            database_id=self._ar_db,
            filter={
                "and": [
                    {
                        "property": "Account ID",
                        "rich_text": {"equals": account_id},
                    },
                    {
                        "property": "Status",
                        "select": {"equals": "outstanding"},
                    },
                ]
            },
        )

        results = response.get("results", [])
        if not results:
            logger.info(
                "notion_collections.no_ar_records",
                account_id=account_id,
            )
            today = date.today()
            return ARAgingReport(
                account_id=account_id,
                account_name="Unknown",
                total_outstanding_usd=0.0,
                buckets=[],
                oldest_invoice_number="",
                oldest_invoice_amount_usd=0.0,
                oldest_invoice_date=today,
            )

        # Parse invoices and group into aging buckets
        bucket_map: dict[str, list[dict]] = {
            "0-30": [],
            "31-60": [],
            "61-90": [],
            "90+": [],
        }

        total_outstanding = 0.0
        account_name = "Unknown"
        oldest_invoice_number = ""
        oldest_invoice_amount = 0.0
        oldest_invoice_date: date | None = None

        for page in results:
            props = page.get("properties", {})

            # Extract invoice number
            inv_parts = props.get("Invoice Number", {}).get("title", [])
            invoice_number = inv_parts[0]["plain_text"] if inv_parts else ""

            # Extract amount
            amount = props.get("Amount USD", {}).get("number") or 0.0

            # Extract days overdue
            days_overdue = props.get("Days Overdue", {}).get("number") or 0

            # Extract due date
            due_date_str = props.get("Due Date", {}).get("date", {})
            if due_date_str:
                start = due_date_str.get("start", "")
                try:
                    inv_date = date.fromisoformat(start[:10])
                except (ValueError, TypeError):
                    inv_date = date.today()
            else:
                inv_date = date.today()

            # Extract account name (use first occurrence)
            if account_name == "Unknown":
                acct_parts = props.get("Account Name", {}).get("rich_text", [])
                if acct_parts:
                    account_name = acct_parts[0].get("plain_text", "Unknown")

            total_outstanding += amount

            # Track oldest invoice
            if oldest_invoice_date is None or inv_date < oldest_invoice_date:
                oldest_invoice_date = inv_date
                oldest_invoice_number = invoice_number
                oldest_invoice_amount = amount

            # Assign to aging bucket
            invoice_data = {
                "invoice_number": invoice_number,
                "amount": amount,
                "date": inv_date,
                "days_overdue": days_overdue,
            }
            if days_overdue <= 30:
                bucket_map["0-30"].append(invoice_data)
            elif days_overdue <= 60:
                bucket_map["31-60"].append(invoice_data)
            elif days_overdue <= 90:
                bucket_map["61-90"].append(invoice_data)
            else:
                bucket_map["90+"].append(invoice_data)

        # Build ARAgingBucket list (only non-empty buckets)
        buckets: list[ARAgingBucket] = []
        for label, invoices in bucket_map.items():
            if not invoices:
                continue
            bucket_total = sum(inv["amount"] for inv in invoices)
            oldest_in_bucket = min(invoices, key=lambda x: x["date"])
            buckets.append(
                ARAgingBucket(
                    bucket_label=label,  # type: ignore[arg-type]
                    invoice_count=len(invoices),
                    total_amount_usd=bucket_total,
                    oldest_invoice_date=oldest_in_bucket["date"],
                    oldest_invoice_number=oldest_in_bucket["invoice_number"],
                )
            )

        final_oldest_date = oldest_invoice_date or date.today()

        logger.info(
            "notion_collections.ar_aging_fetched",
            account_id=account_id,
            invoice_count=len(results),
            total_outstanding=total_outstanding,
        )

        return ARAgingReport(
            account_id=account_id,
            account_name=account_name,
            total_outstanding_usd=total_outstanding,
            buckets=buckets,
            oldest_invoice_number=oldest_invoice_number,
            oldest_invoice_amount_usd=oldest_invoice_amount,
            oldest_invoice_date=final_oldest_date,
        )

    # ── Delinquent Accounts Scan ──────────────────────────────────────────

    async def get_all_delinquent_accounts(self) -> list[dict]:
        """Query all accounts with outstanding overdue invoices.

        Filters the AR DB for status=="outstanding" AND days_overdue > 0.
        Returns a deduplicated list of account dicts for scheduler scans.

        Fails-open: on error returns an empty list.

        Returns:
            List of dicts with keys: account_id, account_name,
            days_overdue (max), total_outstanding_usd. Each account_id
            appears at most once.
        """
        try:
            return await self._query_delinquent_accounts()
        except Exception:
            logger.exception(
                "notion_collections.get_all_delinquent_accounts_error"
            )
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def _query_delinquent_accounts(self) -> list[dict]:
        """Internal retry-wrapped delinquent accounts query."""
        response = await self._client.databases.query(
            database_id=self._ar_db,
            filter={
                "and": [
                    {
                        "property": "Status",
                        "select": {"equals": "outstanding"},
                    },
                    {
                        "property": "Days Overdue",
                        "number": {"greater_than": 0},
                    },
                ]
            },
        )

        results = response.get("results", [])

        # Aggregate by account_id (deduplicate)
        account_map: dict[str, dict] = {}
        for page in results:
            props = page.get("properties", {})

            # Extract account ID
            acct_id_parts = props.get("Account ID", {}).get("rich_text", [])
            account_id = acct_id_parts[0]["plain_text"] if acct_id_parts else ""
            if not account_id:
                continue

            # Extract account name
            acct_name_parts = props.get("Account Name", {}).get("rich_text", [])
            account_name = (
                acct_name_parts[0]["plain_text"] if acct_name_parts else "Unknown"
            )

            # Extract amount and days overdue
            amount = props.get("Amount USD", {}).get("number") or 0.0
            days_overdue = props.get("Days Overdue", {}).get("number") or 0

            if account_id not in account_map:
                account_map[account_id] = {
                    "account_id": account_id,
                    "account_name": account_name,
                    "days_overdue": days_overdue,
                    "total_outstanding_usd": 0.0,
                }

            account_map[account_id]["total_outstanding_usd"] += amount
            # Track maximum days overdue across invoices for this account
            if days_overdue > account_map[account_id]["days_overdue"]:
                account_map[account_id]["days_overdue"] = days_overdue

        accounts = list(account_map.values())
        logger.info(
            "notion_collections.delinquent_accounts_fetched",
            account_count=len(accounts),
        )
        return accounts

    # ── Escalation State ──────────────────────────────────────────────────

    async def get_escalation_state(self, account_id: str) -> EscalationState:
        """Retrieve the current escalation state for an account.

        Queries the escalation DB filtered by account_id. If no record
        exists, returns a default EscalationState with stage=0.

        Fails-open: on error returns default EscalationState(account_id).

        Args:
            account_id: Account identifier to look up.

        Returns:
            EscalationState for the account, or default state if not found
            or on error.
        """
        try:
            return await self._fetch_escalation_state(account_id)
        except Exception:
            logger.exception(
                "notion_collections.get_escalation_state_error",
                account_id=account_id,
            )
            return EscalationState(account_id=account_id)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def _fetch_escalation_state(self, account_id: str) -> EscalationState:
        """Internal retry-wrapped escalation state query."""
        response = await self._client.databases.query(
            database_id=self._esc_db,
            filter={
                "property": "Account ID",
                "rich_text": {"equals": account_id},
            },
            page_size=1,
        )

        results = response.get("results", [])
        if not results:
            logger.info(
                "notion_collections.escalation_state_not_found",
                account_id=account_id,
            )
            return EscalationState(account_id=account_id)

        page = results[0]
        props = page.get("properties", {})

        # Parse current_stage
        stage_prop = props.get("Current Stage", {}).get("number")
        current_stage = int(stage_prop) if stage_prop is not None else 0
        current_stage = max(0, min(5, current_stage))  # clamp to [0, 5]

        # Parse messages_unanswered
        msgs_prop = props.get("Messages Unanswered", {}).get("number")
        messages_unanswered = int(msgs_prop) if msgs_prop is not None else 0

        # Parse stage5_notified
        stage5_prop = props.get("Stage5 Notified", {}).get("checkbox")
        stage5_notified = bool(stage5_prop) if stage5_prop is not None else False

        # Parse datetime fields
        def _parse_dt(key: str) -> datetime | None:
            dt_prop = props.get(key, {}).get("date")
            if not dt_prop:
                return None
            start = dt_prop.get("start")
            if not start:
                return None
            try:
                return datetime.fromisoformat(start.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None

        logger.info(
            "notion_collections.escalation_state_fetched",
            account_id=account_id,
            current_stage=current_stage,
        )

        return EscalationState(
            account_id=account_id,
            current_stage=current_stage,
            stage_entered_at=_parse_dt("Stage Entered At"),
            last_message_sent_at=_parse_dt("Last Message Sent At"),
            messages_unanswered=messages_unanswered,
            stage5_notified=stage5_notified,
            payment_received_at=_parse_dt("Payment Received At"),
            response_received_at=_parse_dt("Response Received At"),
        )

    # ── Escalation State Upsert ───────────────────────────────────────────

    async def update_escalation_state(
        self,
        account_id: str,
        state: EscalationState,
    ) -> None:
        """Upsert escalation state for an account to the escalation DB.

        Queries for an existing page by account_id; updates if found,
        creates a new page if not.

        Fails-open: on error logs and returns without raising.

        Args:
            account_id: Account identifier to upsert state for.
            state: EscalationState with updated values.
        """
        try:
            await self._upsert_escalation_state(account_id, state)
        except Exception:
            logger.exception(
                "notion_collections.update_escalation_state_error",
                account_id=account_id,
                current_stage=state.current_stage,
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def _upsert_escalation_state(
        self,
        account_id: str,
        state: EscalationState,
    ) -> None:
        """Internal retry-wrapped escalation state upsert."""

        def _dt_prop(dt: datetime | None) -> dict:
            """Format datetime as Notion date property or empty."""
            if dt is None:
                return {"date": None}
            return {
                "date": {
                    "start": dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                }
            }

        properties: dict[str, Any] = {
            "Account ID": {
                "rich_text": [
                    {"type": "text", "text": {"content": account_id}}
                ]
            },
            "Current Stage": {"number": state.current_stage},
            "Messages Unanswered": {"number": state.messages_unanswered},
            "Stage5 Notified": {"checkbox": state.stage5_notified},
            "Stage Entered At": _dt_prop(state.stage_entered_at),
            "Last Message Sent At": _dt_prop(state.last_message_sent_at),
            "Payment Received At": _dt_prop(state.payment_received_at),
            "Response Received At": _dt_prop(state.response_received_at),
        }

        # Check if page already exists
        response = await self._client.databases.query(
            database_id=self._esc_db,
            filter={
                "property": "Account ID",
                "rich_text": {"equals": account_id},
            },
            page_size=1,
        )
        results = response.get("results", [])

        if results:
            # Update existing page
            page_id = results[0]["id"]
            await self._client.pages.update(
                page_id=page_id,
                properties=properties,
            )
            logger.info(
                "notion_collections.escalation_state_updated",
                account_id=account_id,
                page_id=page_id,
                current_stage=state.current_stage,
            )
        else:
            # Create new page with title = account_id
            title_property = {
                "title": [
                    {"type": "text", "text": {"content": account_id}}
                ]
            }
            await self._client.pages.create(
                parent={"database_id": self._esc_db},
                properties={**title_property, **properties},
            )
            logger.info(
                "notion_collections.escalation_state_created",
                account_id=account_id,
                current_stage=state.current_stage,
            )

    # ── Payment Plan Pages ────────────────────────────────────────────────

    async def create_payment_plan_page(
        self,
        account_id: str,
        options: dict,
    ) -> str:
        """Create a Notion page with structured payment plan options.

        Creates a page titled "Payment Plan Options — {account_id} — {date}"
        in the events database. The page includes a heading, bulleted list
        of payment plan options, and an LLM rationale paragraph.

        Fails-open: on error logs and returns empty string.

        Args:
            account_id: Account identifier for the payment plan.
            options: Dict with keys: options (list of option dicts),
                llm_rationale (str), total_outstanding_usd (float).

        Returns:
            Notion page ID (UUID str) of the created page, or "" on failure.
        """
        try:
            return await self._create_payment_plan_page(account_id, options)
        except Exception:
            logger.exception(
                "notion_collections.create_payment_plan_page_error",
                account_id=account_id,
            )
            return ""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def _create_payment_plan_page(
        self,
        account_id: str,
        options: dict,
    ) -> str:
        """Internal retry-wrapped payment plan page creation."""
        today_str = date.today().isoformat()
        title = f"Payment Plan Options — {account_id} — {today_str}"

        option_list = options.get("options", [])
        llm_rationale = options.get("llm_rationale", "")
        total_outstanding = options.get("total_outstanding_usd", 0.0)

        blocks: list[dict] = []

        # Heading
        blocks.append(_make_heading("Payment Plan Options", level=2))

        # Summary paragraph
        blocks.append(
            _make_paragraph(
                f"Account: {account_id} | Total Outstanding: ${total_outstanding:,.2f}"
            )
        )

        # Options heading
        blocks.append(_make_heading("Proposed Options", level=3))

        # Option bullets
        if option_list:
            for opt in option_list:
                opt_dict = opt if isinstance(opt, dict) else opt.model_dump()
                blocks.append(_make_option_bullet(opt_dict))
        else:
            blocks.append(_make_paragraph("No payment plan options available."))

        # LLM rationale
        if llm_rationale:
            blocks.append(_make_heading("LLM Rationale", level=3))
            blocks.append(_make_paragraph(llm_rationale))

        page = await self._client.pages.create(
            parent={"database_id": self._events_db},
            properties={
                "title": [
                    {"type": "text", "text": {"content": title}}
                ]
            },
            children=blocks[:100],
        )

        page_id = page["id"]

        # Append remaining blocks in batches
        remaining = blocks[100:]
        while remaining:
            batch = remaining[:100]
            remaining = remaining[100:]
            await self._client.blocks.children.append(
                block_id=page_id,
                children=batch,
            )

        logger.info(
            "notion_collections.payment_plan_page_created",
            account_id=account_id,
            page_id=page_id,
            option_count=len(option_list),
        )
        return page_id

    # ── Collection Event Log ──────────────────────────────────────────────

    async def log_collection_event(
        self,
        account_id: str,
        event_type: str,
        details: dict,
    ) -> None:
        """Append a new collection event entry to the events DB.

        Creates a new Notion page in the events database. Append-only —
        no updates to existing entries.

        Fails-open: on error logs and returns without raising.

        Args:
            account_id: Account identifier for the event.
            event_type: Type of collection event (e.g., "escalation_stage_1",
                "payment_received", "plan_sent").
            details: Additional event details as a free-form dict.
        """
        try:
            await self._append_collection_event(account_id, event_type, details)
        except Exception:
            logger.exception(
                "notion_collections.log_collection_event_error",
                account_id=account_id,
                event_type=event_type,
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def _append_collection_event(
        self,
        account_id: str,
        event_type: str,
        details: dict,
    ) -> None:
        """Internal retry-wrapped collection event creation."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        title = f"[{event_type}] {account_id} — {now_str}"

        blocks: list[dict] = []
        blocks.append(_make_heading("Collection Event", level=2))
        blocks.append(_make_paragraph(f"Account: {account_id}"))
        blocks.append(_make_paragraph(f"Event Type: {event_type}"))
        blocks.append(_make_paragraph(f"Timestamp: {now_str}"))

        if details:
            blocks.append(_make_heading("Details", level=3))
            for key, value in details.items():
                blocks.append(_make_paragraph(f"{key}: {value}"))

        await self._client.pages.create(
            parent={"database_id": self._events_db},
            properties={
                "title": [
                    {"type": "text", "text": {"content": title}}
                ]
            },
            children=blocks[:100],
        )

        logger.info(
            "notion_collections.event_logged",
            account_id=account_id,
            event_type=event_type,
        )


__all__ = ["NotionCollectionsAdapter"]
