"""Weekly status report scheduler for the Project Manager agent.

Provides a lightweight APScheduler wrapper that runs weekly report generation
for all active projects. APScheduler is an optional dependency -- if not
installed, the scheduler logs a warning and returns False on start().

Exports:
    PMScheduler: Async scheduler for weekly PM status reports.
"""

from __future__ import annotations

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    AsyncIOScheduler = None  # type: ignore[assignment, misc]
    CronTrigger = None  # type: ignore[assignment, misc]

import structlog

logger = structlog.get_logger(__name__)


class PMScheduler:
    """Lightweight scheduler for weekly PM status reports using APScheduler.

    Wraps an AsyncIOScheduler with a Monday 9:00 AM cron job that iterates
    over active projects (via NotionPMAdapter) and generates status reports
    through the PM agent.

    Graceful degradation: if APScheduler is not installed, start() returns
    False and logs a warning. If notion_pm is not configured, the job
    logs a warning and returns without processing.

    Args:
        pm_agent: ProjectManagerAgent instance for generating reports.
        notion_pm: NotionPMAdapter for querying active projects. Optional.
        gmail_service: GmailService for email dispatch. Optional.
    """

    def __init__(
        self,
        pm_agent: object,
        notion_pm: object | None = None,
        gmail_service: object | None = None,
    ) -> None:
        self._pm_agent = pm_agent
        self._notion_pm = notion_pm
        self._gmail_service = gmail_service
        self._scheduler: AsyncIOScheduler | None = None  # type: ignore[assignment]
        self._started = False

    def start(self) -> bool:
        """Start the scheduler. Returns False if APScheduler not available."""
        if AsyncIOScheduler is None:
            logger.warning(
                "pm_scheduler_unavailable",
                reason="apscheduler not installed",
            )
            return False

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._generate_weekly_reports,
            trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
            id="pm_weekly_reports",
            name="Generate weekly PM status reports",
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        self._started = True
        logger.info(
            "pm_scheduler_started",
            job="weekly_reports",
            schedule="Monday 9:00 AM",
        )
        return True

    async def _generate_weekly_reports(self) -> None:
        """Generate status reports for all active projects.

        Queries NotionPMAdapter for active projects and iterates through
        each one, calling the PM agent's execute() with a
        generate_status_report task. Failures for individual projects
        do not block other projects from being processed.
        """
        logger.info("pm_weekly_reports_triggered")

        if self._notion_pm is None:
            logger.warning(
                "pm_weekly_reports_skipped",
                reason="notion_pm not configured",
            )
            return

        try:
            active_projects = await self._notion_pm.query_active_projects()  # type: ignore[union-attr]
        except AttributeError:
            logger.warning(
                "pm_weekly_reports_skipped",
                reason="query_active_projects not available on notion_pm",
            )
            return
        except Exception as exc:
            logger.error(
                "pm_weekly_reports_query_failed",
                error=str(exc),
            )
            return

        if not active_projects:
            logger.info("pm_weekly_reports_none_active", count=0)
            return

        logger.info(
            "pm_weekly_reports_processing",
            project_count=len(active_projects),
        )

        results = {"success": 0, "failed": 0}

        for project in active_projects:
            try:
                task = {
                    "type": "generate_status_report",
                    "plan_json": project.get("plan_json", "{}"),
                    "progress_data": project.get("progress_data", "{}"),
                    "deal_context": project.get("deal_context", {}),
                    "sa_summary": project.get("sa_summary", ""),
                    "report_type": "internal",
                    "project_name": project.get("project_name", "Unknown"),
                }
                result = await self._pm_agent.execute(task, context={})  # type: ignore[union-attr]

                if "error" not in result:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    logger.warning(
                        "pm_weekly_report_partial",
                        project=project.get("project_name"),
                        error=result.get("error"),
                    )
            except Exception as exc:
                results["failed"] += 1
                logger.error(
                    "pm_weekly_report_failed",
                    project=project.get("project_name"),
                    error=str(exc),
                )

        logger.info("pm_weekly_reports_complete", **results)

    def stop(self) -> None:
        """Shut down the scheduler."""
        if self._scheduler and self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("pm_scheduler_stopped")


__all__ = ["PMScheduler"]
