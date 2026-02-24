"""Notion CRM adapter for Business Analyst agent operations.

Provides the NotionBAAdapter class for creating BA analysis pages in Notion
databases linked to deals, plus module-level block renderers that convert BA
domain models (requirements, gap analysis, user stories, process docs) into
Notion block structures.

Key implementation details:
- All API calls wrapped with tenacity retry + exponential backoff
- Graceful import handling if notion-client is not installed
- Block renderers are module-level functions decoupled from adapter class
- User stories dual-grouped by epic_theme AND stakeholder_domain
- Low-confidence items visually flagged in rendered output

Exports:
    NotionBAAdapter: Async Notion adapter with retry-wrapped CRUD methods.
    render_requirements_to_notion_blocks: Convert requirements to Notion blocks.
    render_gap_analysis_to_notion_blocks: Convert gap analysis to Notion blocks.
    render_user_stories_to_notion_blocks: Convert user stories to Notion blocks.
    render_process_doc_to_notion_blocks: Convert process docs to Notion blocks.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.app.agents.business_analyst.schemas import (
    BAResult,
    CapabilityGap,
    ExtractedRequirement,
    GapAnalysisResult,
    ProcessDocumentation,
    RequirementContradiction,
    UserStory,
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
                "notion-client is required for NotionBAAdapter. "
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


def _toggle_block(text: str, children: list[dict]) -> dict:
    """Create a Notion toggle block with nested children.

    Args:
        text: Toggle heading text.
        children: List of child blocks rendered inside the toggle.

    Returns:
        Notion toggle block dict.
    """
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "children": children,
        },
    }


# ── Module-Level Block Renderers ──────────────────────────────────────────


def render_requirements_to_notion_blocks(
    requirements: list[ExtractedRequirement],
) -> list[dict]:
    """Convert extracted requirements to Notion block objects.

    Groups requirements by category (functional, non_functional, constraint)
    and renders each as a bulleted list with description, MoSCoW priority,
    stakeholder domain, priority score, and confidence. Low-confidence items
    are visually flagged with a "[LOW CONFIDENCE]" prefix.

    Args:
        requirements: List of ExtractedRequirement instances to render.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []
    blocks.append(_heading_block("Requirements", level=2))

    if not requirements:
        blocks.append(_paragraph_block("No requirements extracted."))
        return blocks

    # Group by category
    grouped: dict[str, list[ExtractedRequirement]] = defaultdict(list)
    for req in requirements:
        grouped[req.category].append(req)

    # Render in consistent order
    category_order = ["functional", "non_functional", "constraint"]
    for category in category_order:
        reqs_in_cat = grouped.get(category, [])
        if not reqs_in_cat:
            continue

        category_label = category.replace("_", " ").title()
        blocks.append(_heading_block(category_label, level=3))

        for req in reqs_in_cat:
            prefix = "[LOW CONFIDENCE] " if req.is_low_confidence else ""
            text = (
                f"{prefix}{req.requirement_id}: {req.description} "
                f"| Priority: {req.moscow_priority.replace('_', ' ').title()} "
                f"| Domain: {req.stakeholder_domain} "
                f"| Score: {req.priority_score} "
                f"| Confidence: {req.extraction_confidence:.0%}"
            )
            blocks.append(_bulleted_list_block(text))

            # Add callout for low-confidence items
            if req.is_low_confidence:
                blocks.append(
                    _callout_block(
                        f"Low confidence ({req.extraction_confidence:.0%}) "
                        f"-- verify this requirement with stakeholders.",
                        emoji="!",
                    )
                )

    return blocks


def render_gap_analysis_to_notion_blocks(
    gap_analysis: GapAnalysisResult,
) -> list[dict]:
    """Convert gap analysis results to Notion block objects.

    Renders coverage percentage, identified gaps with severity and actions,
    requirement contradictions, and recommended next action.

    Args:
        gap_analysis: GapAnalysisResult instance to render.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []
    blocks.append(_heading_block("Gap Analysis", level=2))
    blocks.append(
        _paragraph_block(f"Coverage: {gap_analysis.coverage_percentage:.1f}%")
    )

    # Gaps
    if gap_analysis.gaps:
        blocks.append(_heading_block("Gaps", level=3))
        for gap in gap_analysis.gaps:
            escalation = " [SA ESCALATION REQUIRED]" if gap.requires_sa_escalation else ""
            workaround_text = f" | Workaround: {gap.workaround}" if gap.workaround else ""
            text = (
                f"[{gap.severity.upper()}] {gap.gap_description} "
                f"(Req: {gap.requirement_id}) "
                f"| Action: {gap.recommended_action.replace('_', ' ')}"
                f"{workaround_text}{escalation}"
            )
            blocks.append(_bulleted_list_block(text))

    # Contradictions
    if gap_analysis.contradictions:
        blocks.append(_heading_block("Contradictions", level=3))
        for contradiction in gap_analysis.contradictions:
            affected = ", ".join(contradiction.requirement_ids)
            text = (
                f"[{contradiction.severity.upper()}] "
                f"{contradiction.conflict_description} "
                f"| Affected: {affected} "
                f"| Suggestion: {contradiction.resolution_suggestion}"
            )
            blocks.append(_bulleted_list_block(text))

    # Recommended next action
    blocks.append(
        _callout_block(
            f"Recommended Next Action: {gap_analysis.recommended_next_action}",
            emoji="!",
        )
    )

    return blocks


def render_user_stories_to_notion_blocks(
    stories: list[UserStory],
) -> list[dict]:
    """Convert user stories to Notion block objects with dual grouping.

    First section groups stories by epic_theme with full details in toggle
    blocks. Second section groups by stakeholder_domain with cross-references
    to the epic section. Low-confidence stories are flagged.

    Args:
        stories: List of UserStory instances to render.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []
    blocks.append(_heading_block("User Stories", level=2))

    if not stories:
        blocks.append(_paragraph_block("No user stories generated."))
        return blocks

    # ── Section 1: Grouped by Epic/Theme ──────────────────────────────
    blocks.append(_heading_block("By Epic / Theme", level=3))

    epic_groups: dict[str, list[UserStory]] = defaultdict(list)
    for story in stories:
        epic_groups[story.epic_theme].append(story)

    for epic, epic_stories in sorted(epic_groups.items()):
        blocks.append(_heading_block(epic, level=3))

        for story in epic_stories:
            prefix = "[LOW CONFIDENCE] " if story.is_low_confidence else ""
            toggle_title = f"{prefix}{story.story_id}: {story.i_want}"

            # Build toggle children
            children: list[dict] = []
            children.append(
                _paragraph_block(
                    f"As a {story.as_a}, I want {story.i_want}, "
                    f"so that {story.so_that}"
                )
            )
            children.append(
                _paragraph_block(
                    f"Story Points: {story.story_points} | "
                    f"Priority: {story.priority.replace('_', ' ').title()} | "
                    f"Domain: {story.stakeholder_domain}"
                )
            )

            # Acceptance criteria
            for idx, criterion in enumerate(story.acceptance_criteria, 1):
                children.append(
                    _bulleted_list_block(f"AC-{idx}: {criterion}")
                )

            blocks.append(_toggle_block(toggle_title, children))

    # ── Section 2: Grouped by Stakeholder Domain ──────────────────────
    blocks.append(_heading_block("By Stakeholder Domain", level=3))

    domain_groups: dict[str, list[UserStory]] = defaultdict(list)
    for story in stories:
        domain_groups[story.stakeholder_domain].append(story)

    for domain, domain_stories in sorted(domain_groups.items()):
        domain_label = domain.title()
        story_refs = ", ".join(s.story_id for s in domain_stories)
        blocks.append(
            _bulleted_list_block(f"{domain_label}: {story_refs}")
        )

    return blocks


def render_process_doc_to_notion_blocks(
    process_doc: ProcessDocumentation,
) -> list[dict]:
    """Convert process documentation to Notion block objects.

    Renders current state, future state, delta, stakeholders, and
    assumptions as structured Notion blocks.

    Args:
        process_doc: ProcessDocumentation instance to render.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []
    blocks.append(
        _heading_block(f"Process: {process_doc.process_name}", level=2)
    )

    # Current State
    blocks.append(_heading_block("Current State", level=3))
    blocks.append(_paragraph_block(process_doc.current_state))

    # Future State
    blocks.append(_heading_block("Future State", level=3))
    blocks.append(_paragraph_block(process_doc.future_state))

    # Delta
    blocks.append(_heading_block("Delta (Changes)", level=3))
    blocks.append(_paragraph_block(process_doc.delta))

    # Stakeholders
    blocks.append(_heading_block("Stakeholders", level=3))
    for stakeholder in process_doc.stakeholders:
        blocks.append(_bulleted_list_block(stakeholder))

    # Assumptions
    if process_doc.assumptions:
        blocks.append(_heading_block("Assumptions", level=3))
        for assumption in process_doc.assumptions:
            blocks.append(_bulleted_list_block(assumption))

    return blocks


# ── Notion BA Adapter ─────────────────────────────────────────────────────


class NotionBAAdapter:
    """Notion database adapter for Business Analyst CRM operations.

    Creates and manages BA analysis pages in a Notion database, linking
    results to deals. Follows the NotionPMAdapter pattern: takes a
    pre-authenticated AsyncClient, returns page_id (UUID) from creation
    methods, and wraps all API calls with retry logic.

    Args:
        notion_client: Notion AsyncClient instance (pre-authenticated).
        database_id: Notion database ID for BA analysis pages.
    """

    def __init__(
        self,
        notion_client: AsyncClient,
        database_id: str,
    ) -> None:
        if _notion_import_error is not None:
            raise ImportError(
                "notion-client is required for NotionBAAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error

        self.client = notion_client
        self.database_id = database_id
        self._log = structlog.get_logger(__name__).bind(
            adapter="NotionBAAdapter",
            database_id=database_id,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def create_requirements_page(
        self,
        deal_id: str,
        result: BAResult,
        title: str | None = None,
    ) -> str:
        """Create a BA analysis page in the Notion database.

        Composes blocks from all available result sections (requirements,
        gap analysis, user stories, process documentation) and creates a
        new Notion page linked to the deal.

        Args:
            deal_id: CRM deal identifier to link the page to.
            result: BAResult containing analysis outputs to render.
            title: Optional page title. Defaults to
                "BA Analysis - {deal_id} - {date}".

        Returns:
            The Notion page ID (UUID), matching NotionPMAdapter pattern.
        """
        page_title = title or (
            f"BA Analysis - {deal_id} - "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        )

        # Compose blocks from available result sections
        blocks: list[dict] = []

        if result.requirements:
            blocks.extend(render_requirements_to_notion_blocks(result.requirements))

        if result.gap_analysis:
            blocks.extend(render_gap_analysis_to_notion_blocks(result.gap_analysis))

        if result.user_stories:
            blocks.extend(render_user_stories_to_notion_blocks(result.user_stories))

        if result.process_documentation:
            blocks.extend(
                render_process_doc_to_notion_blocks(result.process_documentation)
            )

        # Create the page with first 100 blocks (Notion API limit)
        page = await self.client.pages.create(
            parent={"database_id": self.database_id},
            properties={
                "title": {
                    "title": [{"text": {"content": page_title}}],
                },
                "Deal ID": {
                    "rich_text": [{"text": {"content": deal_id}}],
                },
                "Analysis Date": {
                    "date": {
                        "start": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    },
                },
                "Task Type": {
                    "select": {"name": result.task_type},
                },
            },
            children=blocks[:100],
        )

        # Return page_id to match NotionPMAdapter pattern (NOT page URL)
        page_id = page.get("id", "")

        # Append remaining blocks in batches of 100 if needed
        remaining = blocks[100:]
        while remaining:
            batch = remaining[:100]
            remaining = remaining[100:]
            await self.client.blocks.children.append(
                block_id=page_id,
                children=batch,
            )

        self._log.info(
            "notion_ba.requirements_page_created",
            page_id=page_id,
            deal_id=deal_id,
            block_count=len(blocks),
            title=page_title,
        )
        return page_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def update_requirements_page(
        self,
        page_id: str,
        result: BAResult,
    ) -> None:
        """Append new analysis blocks to an existing BA page.

        Used for incremental analysis updates -- appends blocks from the
        result without replacing existing content.

        Args:
            page_id: Notion page ID to append blocks to.
            result: BAResult containing new analysis outputs to render.
        """
        blocks: list[dict] = []

        if result.requirements:
            blocks.extend(render_requirements_to_notion_blocks(result.requirements))

        if result.gap_analysis:
            blocks.extend(render_gap_analysis_to_notion_blocks(result.gap_analysis))

        if result.user_stories:
            blocks.extend(render_user_stories_to_notion_blocks(result.user_stories))

        if result.process_documentation:
            blocks.extend(
                render_process_doc_to_notion_blocks(result.process_documentation)
            )

        if not blocks:
            self._log.warning(
                "notion_ba.no_blocks_to_append",
                page_id=page_id,
            )
            return

        # Append in batches of 100
        remaining = blocks
        while remaining:
            batch = remaining[:100]
            remaining = remaining[100:]
            await self.client.blocks.children.append(
                block_id=page_id,
                children=batch,
            )

        self._log.info(
            "notion_ba.requirements_page_updated",
            page_id=page_id,
            block_count=len(blocks),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def get_deal_analysis_pages(
        self,
        deal_id: str,
    ) -> list[dict]:
        """Query the database for BA analysis pages linked to a deal.

        Args:
            deal_id: CRM deal identifier to search for.

        Returns:
            List of page metadata dicts matching the deal_id filter.
        """
        response = await self.client.databases.query(
            database_id=self.database_id,
            filter={
                "property": "Deal ID",
                "rich_text": {"equals": deal_id},
            },
        )

        pages = response.get("results", [])
        self._log.info(
            "notion_ba.deal_analysis_pages_queried",
            deal_id=deal_id,
            page_count=len(pages),
        )
        return pages


__all__ = [
    "NotionBAAdapter",
    "render_requirements_to_notion_blocks",
    "render_gap_analysis_to_notion_blocks",
    "render_user_stories_to_notion_blocks",
    "render_process_doc_to_notion_blocks",
]
