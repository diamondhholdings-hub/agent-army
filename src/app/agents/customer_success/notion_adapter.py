"""Notion CRM adapter for Customer Success Manager agent operations.

Provides the NotionCSMAdapter class for managing CSM health records,
QBR pages, and expansion opportunities in Notion. Also provides
module-level block renderers that convert CSM domain models into
Notion block structures.

Key implementation details:
- All API calls wrapped with tenacity retry + exponential backoff
- Graceful import handling if notion-client is not installed
- Block renderers are module-level functions decoupled from adapter class
- Pre-authenticated AsyncClient injected via constructor (same as TAM)

Exports:
    NotionCSMAdapter: Async Notion adapter with retry-wrapped CRUD methods.
    render_health_record_blocks: Convert CSMHealthScore to Notion blocks.
    render_qbr_blocks: Convert QBRContent to Notion blocks with 4 sections.
    render_expansion_blocks: Convert ExpansionOpportunity to Notion blocks.
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

from src.app.agents.customer_success.schemas import (
    CSMHealthScore,
    ExpansionOpportunity,
    QBRContent,
)
from src.app.config import get_settings

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
                "notion-client is required for NotionCSMAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error
else:
    _notion_import_error = None


# ── Block Construction Helpers ────────────────────────────────────────────


def _heading_block(text: str, level: int = 2) -> dict:
    """Create a Notion heading block.

    Args:
        text: Heading text content.
        level: Heading level (1, 2, or 3).

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


# ── Module-Level Block Renderers ──────────────────────────────────────────


def render_health_record_blocks(health_score: CSMHealthScore) -> list[dict]:
    """Convert a CSMHealthScore to Notion block objects.

    Renders the health score with RAG status, churn risk, and signal
    breakdown as structured Notion blocks.

    Args:
        health_score: CSMHealthScore instance to render.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []

    blocks.append(_heading_block("CSM Health Score", level=2))

    # Score and RAG
    blocks.append(
        _paragraph_block(
            f"Score: {health_score.score:.1f}/100 | RAG: {health_score.rag}"
        )
    )

    # Churn risk
    churn_text = f"Churn Risk: {health_score.churn_risk_level}"
    if health_score.churn_triggered_by:
        churn_text += f" (triggered by: {health_score.churn_triggered_by})"
    blocks.append(_paragraph_block(churn_text))

    # Computed at
    computed_str = health_score.computed_at.strftime("%Y-%m-%d %H:%M UTC")
    blocks.append(_paragraph_block(f"Computed: {computed_str}"))

    # Signal breakdown
    if health_score.signal_breakdown:
        blocks.append(_heading_block("Signal Breakdown", level=3))
        for signal_name, contribution in health_score.signal_breakdown.items():
            label = signal_name.replace("_", " ").title()
            blocks.append(
                _bulleted_list_block(f"{label}: {contribution:.1f}")
            )

    return blocks


def render_qbr_blocks(qbr: QBRContent) -> list[dict]:
    """Convert QBRContent to Notion block objects with 4 sections.

    Sections:
    1. Account Health Summary (heading_1 + paragraph)
    2. ROI & Business Impact (heading_2 + bulleted items)
    3. Feature Adoption Scorecard (heading_2 + bulleted items)
    4. Expansion & Next Steps (heading_2 + bulleted items)

    Args:
        qbr: QBRContent instance to render.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []

    # Section 1: Account Health Summary
    blocks.append(_heading_block("Account Health Summary", level=1))
    blocks.append(_paragraph_block(qbr.health_summary))

    # Section 2: ROI & Business Impact
    blocks.append(_heading_block("ROI & Business Impact", level=2))
    if qbr.roi_metrics:
        for metric_name, metric_value in qbr.roi_metrics.items():
            label = metric_name.replace("_", " ").title()
            blocks.append(_bulleted_list_block(f"{label}: {metric_value}"))
    else:
        blocks.append(_paragraph_block("No ROI metrics available."))

    # Section 3: Feature Adoption Scorecard
    blocks.append(_heading_block("Feature Adoption Scorecard", level=2))
    if qbr.feature_adoption_scorecard:
        for feature_name, adoption_data in qbr.feature_adoption_scorecard.items():
            label = feature_name.replace("_", " ").title()
            if isinstance(adoption_data, dict):
                details = ", ".join(
                    f"{k}: {v}" for k, v in adoption_data.items()
                )
                blocks.append(_bulleted_list_block(f"{label}: {details}"))
            else:
                blocks.append(_bulleted_list_block(f"{label}: {adoption_data}"))
    else:
        blocks.append(_paragraph_block("No feature adoption data available."))

    # Section 4: Expansion & Next Steps
    blocks.append(_heading_block("Expansion & Next Steps", level=2))
    if qbr.expansion_next_steps:
        for step in qbr.expansion_next_steps:
            blocks.append(_bulleted_list_block(step))
    else:
        blocks.append(_paragraph_block("No expansion steps identified."))

    return blocks


def render_expansion_blocks(opportunity: ExpansionOpportunity) -> list[dict]:
    """Convert an ExpansionOpportunity to Notion block objects.

    Renders the expansion opportunity with type, evidence, confidence,
    ARR impact, and recommended talk track.

    Args:
        opportunity: ExpansionOpportunity instance to render.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []

    blocks.append(_heading_block("Expansion Opportunity", level=2))

    # Type and confidence
    blocks.append(
        _paragraph_block(
            f"Type: {opportunity.opportunity_type} | "
            f"Confidence: {opportunity.confidence}"
        )
    )

    # Evidence
    blocks.append(_heading_block("Evidence", level=3))
    blocks.append(_paragraph_block(opportunity.evidence))

    # ARR impact
    if opportunity.estimated_arr_impact is not None:
        blocks.append(
            _paragraph_block(
                f"Estimated ARR Impact: ${opportunity.estimated_arr_impact:,.0f}"
            )
        )

    # Recommended talk track
    blocks.append(_heading_block("Recommended Talk Track", level=3))
    blocks.append(_paragraph_block(opportunity.recommended_talk_track))

    # Created at
    created_str = opportunity.created_at.strftime("%Y-%m-%d %H:%M UTC")
    blocks.append(_paragraph_block(f"Identified: {created_str}"))

    return blocks


# ── Notion CSM Adapter ────────────────────────────────────────────────────


class NotionCSMAdapter:
    """Notion database adapter for CSM health records, QBR pages, and expansions.

    Manages CSM-specific Notion databases for health score tracking,
    Quarterly Business Review pages, and expansion opportunity records.
    Also queries and updates the shared Accounts database for CSM health
    properties.

    Args:
        notion_client: Pre-authenticated Notion AsyncClient instance.
    """

    def __init__(self, notion_client: AsyncClient) -> None:
        if _notion_import_error is not None:
            raise ImportError(
                "notion-client is required for NotionCSMAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error

        self._client = notion_client
        self._settings = get_settings()

    # ── Account Queries ──────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def get_account(self, account_id: str) -> dict[str, Any]:
        """Retrieve a single account page and parse its properties.

        Queries the accounts database by account_id. Returns a dict with
        both ``id`` and ``account_id`` keys for agent.py compatibility.

        Args:
            account_id: Notion page ID of the account page.

        Returns:
            Account dict with keys: id, account_id, name, csm_health_score,
            csm_health_rag. Returns empty dict if not found.
        """
        try:
            page = await self._client.pages.retrieve(page_id=account_id)
        except Exception:
            logger.warning(
                "notion_csm.get_account_not_found",
                account_id=account_id,
            )
            return {}

        props = page.get("properties", {})

        # Extract account name from title property
        name_parts = props.get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else "Unknown"

        # Extract CSM health properties
        csm_score_prop = props.get("CSM Health Score", {}).get("number")
        csm_rag_prop = props.get("CSM Health RAG", {}).get("select")
        csm_rag = csm_rag_prop["name"] if csm_rag_prop else None

        logger.info(
            "notion_csm.account_fetched",
            account_id=account_id,
        )
        return {
            "id": page["id"],
            "account_id": page["id"],
            "name": name,
            "csm_health_score": csm_score_prop,
            "csm_health_rag": csm_rag,
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def query_all_accounts(self) -> list[dict[str, Any]]:
        """Query all active accounts from the Accounts database.

        Returns a list of account dicts for the CSM health scan.

        Returns:
            List of account dicts with keys: id, account_id, name,
            csm_health_score, csm_health_rag.

        Raises:
            ValueError: If NOTION_DATABASE_ID is not configured.
        """
        db_id = self._settings.NOTION_DATABASE_ID
        if not db_id:
            raise ValueError(
                "NOTION_DATABASE_ID not configured. "
                "Set it in environment variables or .env file."
            )

        response = await self._client.databases.query(
            database_id=db_id,
            filter={
                "property": "Status",
                "select": {"does_not_equal": "Inactive"},
            },
        )

        accounts: list[dict[str, Any]] = []
        for page in response.get("results", []):
            props = page.get("properties", {})

            # Extract account name from title property
            name_parts = props.get("Name", {}).get("title", [])
            name = name_parts[0]["plain_text"] if name_parts else "Unknown"

            # Extract CSM health properties
            csm_score_prop = props.get("CSM Health Score", {}).get("number")
            csm_rag_prop = props.get("CSM Health RAG", {}).get("select")
            csm_rag = csm_rag_prop["name"] if csm_rag_prop else None

            accounts.append(
                {
                    "id": page["id"],
                    "account_id": page["id"],
                    "name": name,
                    "csm_health_score": csm_score_prop,
                    "csm_health_rag": csm_rag,
                }
            )

        logger.info(
            "notion_csm.query_all_accounts",
            account_count=len(accounts),
        )
        return accounts

    # ── Health Score Updates ──────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def update_health_score(
        self,
        page_id: str,
        score: float,
        rag: str,
    ) -> None:
        """Update CSM health score and RAG status on an account page.

        Updates the "CSM Health Score" (number), "CSM Health RAG" (select),
        and "CSM Last Scan" (date: now ISO) properties on the account page.

        Args:
            page_id: Notion page ID of the account page.
            score: CSM health score (0-100).
            rag: RAG status ("GREEN", "AMBER", "RED").
        """
        await self._client.pages.update(
            page_id=page_id,
            properties={
                "CSM Health Score": {"number": score},
                "CSM Health RAG": {"select": {"name": rag}},
                "CSM Last Scan": {
                    "date": {
                        "start": datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%S.000Z"
                        ),
                    },
                },
            },
        )
        logger.info(
            "notion_csm.health_score_updated",
            page_id=page_id,
            score=score,
            rag=rag,
        )

    # ── QBR Pages ────────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def create_qbr_page(
        self,
        qbr: QBRContent,
        account_name: str = "",
    ) -> str:
        """Create a QBR page in the CSM QBR database.

        Creates a structured Notion page with title
        "QBR: {account_name} -- {qbr.period}" and all 4 QBR sections
        rendered as blocks.

        Args:
            qbr: QBRContent with health summary, ROI, adoption, expansion.
            account_name: Display name for the account in the title.

        Returns:
            The Notion page ID (UUID) of the created QBR page.

        Raises:
            ValueError: If NOTION_CSM_QBR_DATABASE_ID is not configured.
        """
        db_id = self._settings.NOTION_CSM_QBR_DATABASE_ID
        if not db_id:
            raise ValueError(
                "NOTION_CSM_QBR_DATABASE_ID not configured. "
                "Set it in environment variables or .env file."
            )

        title = f"QBR: {account_name} — {qbr.period}"
        blocks = render_qbr_blocks(qbr)

        # Create page with first 100 blocks (Notion API limit)
        page = await self._client.pages.create(
            parent={"database_id": db_id},
            properties={
                "title": [
                    {
                        "type": "text",
                        "text": {"content": title},
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
            "notion_csm.qbr_page_created",
            page_id=page_id,
            account_name=account_name,
            period=qbr.period,
            block_count=len(blocks),
        )
        return page_id

    # ── Expansion Records ────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def create_expansion_record(
        self,
        opportunity: ExpansionOpportunity,
    ) -> str:
        """Create an expansion opportunity record in the CSM expansion database.

        Creates a Notion page with the expansion opportunity details
        rendered as blocks.

        Args:
            opportunity: ExpansionOpportunity with type, evidence, talk track.

        Returns:
            The Notion page ID (UUID) of the created expansion record.

        Raises:
            ValueError: If NOTION_CSM_EXPANSION_DATABASE_ID is not configured.
        """
        db_id = self._settings.NOTION_CSM_EXPANSION_DATABASE_ID
        if not db_id:
            raise ValueError(
                "NOTION_CSM_EXPANSION_DATABASE_ID not configured. "
                "Set it in environment variables or .env file."
            )

        title = (
            f"Expansion: {opportunity.opportunity_type} — "
            f"{opportunity.account_id}"
        )
        blocks = render_expansion_blocks(opportunity)

        # Create page with first 100 blocks (Notion API limit)
        page = await self._client.pages.create(
            parent={"database_id": db_id},
            properties={
                "title": [
                    {
                        "type": "text",
                        "text": {"content": title},
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
            "notion_csm.expansion_record_created",
            page_id=page_id,
            opportunity_type=opportunity.opportunity_type,
            account_id=opportunity.account_id,
            block_count=len(blocks),
        )
        return page_id

    # ── Health Records ───────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def get_health_record(
        self,
        account_id: str,
    ) -> dict[str, Any]:
        """Query the CSM health database for the latest record of an account.

        Queries NOTION_CSM_HEALTH_DATABASE_ID filtered by account_id,
        sorted by created_time descending, and returns the first result.

        Args:
            account_id: Account identifier to look up.

        Returns:
            Dict with health record data, or empty dict if no record found.

        Raises:
            ValueError: If NOTION_CSM_HEALTH_DATABASE_ID is not configured.
        """
        db_id = self._settings.NOTION_CSM_HEALTH_DATABASE_ID
        if not db_id:
            raise ValueError(
                "NOTION_CSM_HEALTH_DATABASE_ID not configured. "
                "Set it in environment variables or .env file."
            )

        response = await self._client.databases.query(
            database_id=db_id,
            filter={
                "property": "Account ID",
                "rich_text": {"equals": account_id},
            },
            sorts=[
                {
                    "timestamp": "created_time",
                    "direction": "descending",
                }
            ],
            page_size=1,
        )

        results = response.get("results", [])
        if not results:
            logger.info(
                "notion_csm.health_record_not_found",
                account_id=account_id,
            )
            return {}

        page = results[0]
        props = page.get("properties", {})

        # Extract health record properties
        score_prop = props.get("Score", {}).get("number")
        rag_prop = props.get("RAG", {}).get("select")
        rag = rag_prop["name"] if rag_prop else None
        churn_prop = props.get("Churn Risk", {}).get("select")
        churn_risk = churn_prop["name"] if churn_prop else None

        logger.info(
            "notion_csm.health_record_fetched",
            account_id=account_id,
            page_id=page["id"],
        )
        return {
            "id": page["id"],
            "account_id": account_id,
            "score": score_prop,
            "rag": rag,
            "churn_risk": churn_risk,
            "created_time": page.get("created_time"),
        }


__all__ = [
    "NotionCSMAdapter",
    "render_health_record_blocks",
    "render_qbr_blocks",
    "render_expansion_blocks",
]
