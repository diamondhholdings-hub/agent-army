"""Notion CRM adapter for Project Manager agent operations.

Provides the NotionPMAdapter class for managing Projects database records,
project plan sub-pages, status reports, risk logs, change requests, and
milestone events via the Notion API. Also provides module-level renderers
that convert PM domain models into Notion block structures.

Key implementation details:
- All API calls wrapped with tenacity retry + exponential backoff
- Graceful import handling if notion-client is not installed
- WBS renderer converts 3-level hierarchy to Notion heading/todo blocks
- Report renderer supports both internal and external report formats

Exports:
    NotionPMAdapter: Async Notion adapter with retry-wrapped CRUD methods.
    render_wbs_to_notion_blocks: Convert ProjectPlan WBS to Notion blocks.
    render_report_to_notion_blocks: Convert status reports to Notion blocks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Union

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.app.agents.project_manager.schemas import (
    ExternalStatusReport,
    InternalStatusReport,
    ProjectPlan,
    WBSMilestone,
    WBSPhase,
    WBSTask,
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
                "notion-client is required for NotionPMAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error
else:
    _notion_import_error = None


# ── Notion PM Adapter ──────────────────────────────────────────────────────


class NotionPMAdapter:
    """Notion database adapter for Project Manager CRM operations.

    Manages the Projects database and deal sub-pages via the Notion API
    with retry logic and lazy database initialization.

    Args:
        client: Notion AsyncClient instance (pre-authenticated).
        projects_database_id: Optional pre-existing Projects database ID.
            If None, must call ensure_projects_database() before creating records.
    """

    def __init__(
        self,
        client: AsyncClient,
        projects_database_id: str | None = None,
    ) -> None:
        if _notion_import_error is not None:
            raise ImportError(
                "notion-client is required for NotionPMAdapter. "
                "Install it with: pip install 'notion-client>=2.7.0'"
            ) from _notion_import_error

        self._client = client
        self._projects_db_id = projects_database_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def ensure_projects_database(
        self, parent_page_id: str, deals_database_id: str
    ) -> str:
        """Ensure the Projects database exists, creating it if needed.

        Lazy initialization pattern: if projects_database_id was provided
        in the constructor, returns it immediately. Otherwise creates a new
        Projects database under the specified parent page.

        Args:
            parent_page_id: Notion page ID to create the database under.
            deals_database_id: Notion database ID for the deals pipeline,
                used for the Deal relation property.

        Returns:
            The Projects database ID.
        """
        if self._projects_db_id is not None:
            return self._projects_db_id

        db = await self._client.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": "Projects"}}],
            properties={
                "Name": {"title": {}},
                "Deal": {
                    "relation": {
                        "database_id": deals_database_id,
                        "single_property": {},
                    },
                },
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Planning", "color": "blue"},
                            {"name": "Active", "color": "green"},
                            {"name": "On Hold", "color": "yellow"},
                            {"name": "Completed", "color": "gray"},
                            {"name": "Cancelled", "color": "red"},
                        ],
                    },
                },
                "Overall RAG": {
                    "select": {
                        "options": [
                            {"name": "Green", "color": "green"},
                            {"name": "Amber", "color": "yellow"},
                            {"name": "Red", "color": "red"},
                        ],
                    },
                },
                "Start Date": {"date": {}},
                "Target End Date": {"date": {}},
                "Actual End Date": {"date": {}},
                "Budget Days": {"number": {"format": "number"}},
                "Actual Days": {"number": {"format": "number"}},
                "BCWP": {"number": {"format": "number"}},
                "ACWP": {"number": {"format": "number"}},
                "Risk Count": {"number": {"format": "number"}},
                "Last Report Date": {"date": {}},
                "Change Request Count": {"number": {"format": "number"}},
            },
        )

        self._projects_db_id = db["id"]
        logger.info(
            "notion_pm.projects_database_created",
            database_id=self._projects_db_id,
            parent_page_id=parent_page_id,
        )
        return self._projects_db_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def create_project_record(self, project_data: dict) -> str:
        """Create a project record page in the Projects database.

        Maps project_data fields to Notion database properties and creates
        a new page. The project starts in "Planning" status with "Green" RAG.

        Args:
            project_data: Dict containing project fields:
                - name (str): Project name (required).
                - deal_page_id (str, optional): Notion page ID for Deal relation.
                - start_date (str, optional): ISO date for Start Date.
                - target_end_date (str, optional): ISO date for Target End Date.
                - budget_days (float, optional): Total budget in person-days.

        Returns:
            The Notion page ID of the created project record.
        """
        if self._projects_db_id is None:
            raise ValueError(
                "Projects database not initialized. "
                "Call ensure_projects_database() first."
            )

        properties: dict[str, Any] = {
            "Name": {
                "title": [
                    {
                        "type": "text",
                        "text": {"content": project_data.get("name", "Untitled Project")},
                    }
                ],
            },
            "Status": {"select": {"name": "Planning"}},
            "Overall RAG": {"select": {"name": "Green"}},
        }

        if project_data.get("deal_page_id"):
            properties["Deal"] = {
                "relation": [{"id": project_data["deal_page_id"]}],
            }

        if project_data.get("start_date"):
            properties["Start Date"] = {
                "date": {"start": project_data["start_date"]},
            }

        if project_data.get("target_end_date"):
            properties["Target End Date"] = {
                "date": {"start": project_data["target_end_date"]},
            }

        if project_data.get("budget_days") is not None:
            properties["Budget Days"] = {
                "number": project_data["budget_days"],
            }

        page = await self._client.pages.create(
            parent={"database_id": self._projects_db_id},
            properties=properties,
        )

        page_id = page["id"]
        logger.info(
            "notion_pm.project_record_created",
            page_id=page_id,
            project_name=project_data.get("name"),
        )
        return page_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def create_plan_subpage(
        self, deal_page_id: str, plan_blocks: list[dict]
    ) -> str:
        """Create a "Project Plan" sub-page under a deal page.

        Args:
            deal_page_id: Notion page ID of the parent deal page.
            plan_blocks: List of Notion block objects for the plan content.

        Returns:
            The Notion page ID of the created sub-page.
        """
        page = await self._client.pages.create(
            parent={"page_id": deal_page_id},
            properties={
                "title": [
                    {
                        "type": "text",
                        "text": {"content": "Project Plan"},
                    }
                ],
            },
            children=plan_blocks,
        )

        page_id = page["id"]
        logger.info(
            "notion_pm.plan_subpage_created",
            page_id=page_id,
            deal_page_id=deal_page_id,
            block_count=len(plan_blocks),
        )
        return page_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def append_status_report(
        self, page_id: str, report_blocks: list[dict]
    ) -> None:
        """Append status report blocks to an existing page.

        Args:
            page_id: Notion page ID to append blocks to.
            report_blocks: List of Notion block objects for the report.
        """
        await self._client.blocks.children.append(
            block_id=page_id,
            children=report_blocks,
        )
        logger.info(
            "notion_pm.status_report_appended",
            page_id=page_id,
            block_count=len(report_blocks),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def update_project_metrics(
        self, project_page_id: str, metrics: dict
    ) -> None:
        """Update project metrics properties on a project record page.

        Args:
            project_page_id: Notion page ID of the project record.
            metrics: Dict of metric values to update. Supported keys:
                - overall_rag (str): "Green", "Amber", or "Red".
                - acwp (float): Actual Cost of Work Performed.
                - bcwp (float): Budgeted Cost of Work Performed.
                - actual_days (float): Actual effort spent.
                - last_report_date (str): ISO date of last report.
                - risk_count (int): Number of open risks.
        """
        properties: dict[str, Any] = {}

        if "overall_rag" in metrics:
            properties["Overall RAG"] = {
                "select": {"name": metrics["overall_rag"]},
            }

        if "acwp" in metrics:
            properties["ACWP"] = {"number": metrics["acwp"]}

        if "bcwp" in metrics:
            properties["BCWP"] = {"number": metrics["bcwp"]}

        if "actual_days" in metrics:
            properties["Actual Days"] = {"number": metrics["actual_days"]}

        if "last_report_date" in metrics:
            properties["Last Report Date"] = {
                "date": {"start": metrics["last_report_date"]},
            }

        if "risk_count" in metrics:
            properties["Risk Count"] = {"number": metrics["risk_count"]}

        if not properties:
            logger.warning(
                "notion_pm.no_metrics_to_update",
                project_page_id=project_page_id,
            )
            return

        await self._client.pages.update(
            page_id=project_page_id,
            properties=properties,
        )
        logger.info(
            "notion_pm.project_metrics_updated",
            project_page_id=project_page_id,
            updated_fields=list(properties.keys()),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def append_risk_log_entry(
        self, page_id: str, risk_blocks: list[dict]
    ) -> None:
        """Append risk log entry blocks to a risk log sub-page.

        Args:
            page_id: Notion page ID of the risk log sub-page.
            risk_blocks: List of Notion block objects for the risk entry.
        """
        await self._client.blocks.children.append(
            block_id=page_id,
            children=risk_blocks,
        )
        logger.info(
            "notion_pm.risk_log_entry_appended",
            page_id=page_id,
            block_count=len(risk_blocks),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def append_change_request(
        self, page_id: str, change_blocks: list[dict]
    ) -> None:
        """Append change request blocks to a change request sub-page.

        Args:
            page_id: Notion page ID to append change request blocks to.
            change_blocks: List of Notion block objects for the change request.
        """
        await self._client.blocks.children.append(
            block_id=page_id,
            children=change_blocks,
        )
        logger.info(
            "notion_pm.change_request_appended",
            page_id=page_id,
            block_count=len(change_blocks),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def append_milestone_event(
        self, page_id: str, milestone_blocks: list[dict]
    ) -> None:
        """Append milestone completion event blocks to a deal sub-page.

        Records milestone completion events for audit and stakeholder
        visibility. Each event captures the milestone name, completion date,
        whether success criteria were met, and any notes.

        Args:
            page_id: Notion page ID of the deal sub-page to append to.
            milestone_blocks: List of Notion block objects containing:
                - milestone name, completion date, success criteria met,
                  and optional notes.
        """
        await self._client.blocks.children.append(
            block_id=page_id,
            children=milestone_blocks,
        )
        logger.info(
            "notion_pm.milestone_event_appended",
            page_id=page_id,
            milestone_count=len(milestone_blocks),
        )


# ── Block Renderers ────────────────────────────────────────────────────────


def render_wbs_to_notion_blocks(plan: ProjectPlan) -> list[dict]:
    """Convert a 3-level WBS project plan into Notion block objects.

    Renders the WBS hierarchy as:
    - H1 per phase (phase name + resource estimate)
    - H2 per milestone (milestone name + target date + success criteria)
    - To-do items per task (task name, owner, duration, checked if completed)
    - Divider between phases

    Args:
        plan: A ProjectPlan instance with phases, milestones, and tasks.

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []

    for i, phase in enumerate(plan.phases):
        # Phase heading (H1)
        blocks.append(
            _heading_block(
                1,
                f"{phase.name} ({phase.resource_estimate_days} person-days)",
            )
        )

        for milestone in phase.milestones:
            # Milestone heading (H2)
            target_date_str = milestone.target_date.strftime("%Y-%m-%d")
            blocks.append(
                _heading_block(
                    2,
                    f"{milestone.name} -- Target: {target_date_str}",
                )
            )

            # Success criteria as paragraph
            blocks.append(
                _paragraph_block(
                    f"Success criteria: {milestone.success_criteria}"
                )
            )

            # Tasks as to-do items
            for task in milestone.tasks:
                dep_str = ""
                if task.dependencies:
                    dep_str = f" [depends: {', '.join(task.dependencies)}]"

                blocks.append(
                    _todo_block(
                        text=(
                            f"{task.name} -- {task.owner}, "
                            f"{task.duration_days}d{dep_str}"
                        ),
                        checked=(task.status == "completed"),
                    )
                )

        # Divider between phases (except after last phase)
        if i < len(plan.phases) - 1:
            blocks.append({"type": "divider", "divider": {}})

    return blocks


def render_report_to_notion_blocks(
    report: Union[InternalStatusReport, ExternalStatusReport],
    is_internal: bool,
) -> list[dict]:
    """Convert a status report into Notion block objects.

    Renders the report as structured Notion blocks with headings,
    paragraphs, and bulleted lists. Internal reports include risks
    and next actions; external reports include accomplishments and
    upcoming activities.

    Args:
        report: An InternalStatusReport or ExternalStatusReport instance.
        is_internal: True for internal reports (includes risks, earned value),
            False for external reports (customer-facing).

    Returns:
        List of Notion block dicts ready for page creation or appending.
    """
    blocks: list[dict] = []

    if is_internal:
        assert isinstance(report, InternalStatusReport)
        report_date_str = report.report_date.strftime("%Y-%m-%d")

        # Report header
        blocks.append(
            _heading_block(2, f"Status Report -- {report_date_str}")
        )

        # Overall RAG
        rag_label = report.overall_rag.upper()
        blocks.append(
            _paragraph_block(f"Overall RAG: {rag_label}")
        )

        # Milestone progress
        blocks.append(_heading_block(3, "Milestone Progress"))
        for mp in report.milestone_progress:
            blocks.append(
                _bulleted_block(
                    f"{mp.name}: {mp.pct_complete:.0f}% complete "
                    f"({mp.completed_tasks}/{mp.total_tasks} tasks) -- "
                    f"{mp.status}"
                )
            )

        # Risks
        if report.risks_and_issues:
            blocks.append(_heading_block(3, "Risks and Issues"))
            for risk in report.risks_and_issues:
                blocks.append(
                    _bulleted_block(
                        f"[{risk.severity.upper()}] {risk.description} "
                        f"(Owner: {risk.owner}, Status: {risk.status})"
                    )
                )

        # Next actions
        if report.next_actions:
            blocks.append(_heading_block(3, "Next Actions"))
            for action in report.next_actions:
                due_str = action.due_date.strftime("%Y-%m-%d")
                blocks.append(
                    _bulleted_block(
                        f"{action.description} -- {action.owner} "
                        f"(Due: {due_str})"
                    )
                )

        # Earned value summary
        ev = report.earned_value
        blocks.append(_heading_block(3, "Earned Value"))
        blocks.append(
            _paragraph_block(
                f"BCWP: {ev.bcwp:.1f} | ACWP: {ev.acwp:.1f} | "
                f"BCWS: {ev.bcws:.1f} | CPI: {ev.cpi:.2f} | "
                f"SPI: {ev.spi:.2f}"
            )
        )

    else:
        assert isinstance(report, ExternalStatusReport)
        report_date_str = report.report_date.strftime("%Y-%m-%d")

        # Report header
        blocks.append(
            _heading_block(
                2, f"Status Report -- {report_date_str}"
            )
        )

        # Overall status
        blocks.append(
            _paragraph_block(f"Overall Status: {report.overall_status}")
        )

        # Milestone summary
        blocks.append(_heading_block(3, "Milestone Summary"))
        for ms in report.milestone_summary:
            blocks.append(
                _bulleted_block(
                    f"{ms.name}: {ms.status} "
                    f"(Est. completion: {ms.estimated_completion})"
                )
            )

        # Key accomplishments
        if report.key_accomplishments:
            blocks.append(_heading_block(3, "Key Accomplishments"))
            for item in report.key_accomplishments:
                blocks.append(_bulleted_block(item))

        # Upcoming activities
        if report.upcoming_activities:
            blocks.append(_heading_block(3, "Upcoming Activities"))
            for item in report.upcoming_activities:
                blocks.append(_bulleted_block(item))

        # Items requiring attention
        if report.items_requiring_attention:
            blocks.append(
                _heading_block(3, "Items Requiring Attention")
            )
            for item in report.items_requiring_attention:
                blocks.append(_bulleted_block(item))

    return blocks


# ── Block Construction Helpers ─────────────────────────────────────────────


def _heading_block(level: int, text: str) -> dict:
    """Create a Notion heading block (H1, H2, or H3).

    Args:
        level: Heading level (1, 2, or 3).
        text: Heading text content.

    Returns:
        Notion heading block dict.
    """
    key = f"heading_{level}"
    return {
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
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _bulleted_block(text: str) -> dict:
    """Create a Notion bulleted list item block.

    Args:
        text: Bullet item text content.

    Returns:
        Notion bulleted_list_item block dict.
    """
    return {
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _todo_block(text: str, checked: bool = False) -> dict:
    """Create a Notion to-do (checkbox) block.

    Args:
        text: To-do item text content.
        checked: Whether the checkbox is checked.

    Returns:
        Notion to_do block dict.
    """
    return {
        "type": "to_do",
        "to_do": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "checked": checked,
        },
    }


__all__ = [
    "NotionPMAdapter",
    "render_wbs_to_notion_blocks",
    "render_report_to_notion_blocks",
]
