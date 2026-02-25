"""Background scheduler for Collections Agent: daily AR scan and daily escalation check.

Provides a lightweight APScheduler wrapper with 2 cron jobs:
- Daily AR scan at 6:00 AM (iterates all delinquent accounts, dispatches ar_aging_report)
- Daily escalation check at 7:00 AM (iterates all delinquent accounts, dispatches run_escalation_check)

APScheduler is an optional dependency -- if not installed, start() returns False.

Exports:
    CollectionsScheduler: Async scheduler for daily AR scanning and escalation checking.
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    AsyncIOScheduler = None  # type: ignore[assignment, misc]
    CronTrigger = None  # type: ignore[assignment, misc]

import structlog

logger = structlog.get_logger(__name__)


class CollectionsScheduler:
    """Lightweight scheduler for Collections daily AR scans and escalation checks.

    Wraps an AsyncIOScheduler with two cron jobs:
    1. Daily AR scan at 6:00 AM -- fetches delinquent accounts via NotionCollectionsAdapter
       and dispatches ar_aging_report tasks to the Collections agent.
    2. Daily escalation check at 7:00 AM -- fetches delinquent accounts and dispatches
       run_escalation_check tasks to determine if any accounts should advance stages.

    Graceful degradation: if APScheduler is not installed, start() returns False and
    logs a warning. If notion_collections is not configured, jobs log a warning and
    return without processing.

    Args:
        collections_agent: CollectionsAgent instance for executing tasks.
        notion_collections: NotionCollectionsAdapter for querying accounts. Optional.
    """

    def __init__(
        self,
        collections_agent: object,
        notion_collections: object | None = None,
    ) -> None:
        self._agent = collections_agent
        self._notion = notion_collections
        self._scheduler: AsyncIOScheduler | None = None  # type: ignore[assignment]
        self._started = False

    def start(self) -> bool:
        """Start the scheduler. Returns False if APScheduler not available."""
        if AsyncIOScheduler is None:
            logger.warning(
                "collections_scheduler.apscheduler_unavailable",
                reason="apscheduler not installed",
            )
            return False

        try:
            self._scheduler = AsyncIOScheduler()

            # Job 1: Daily AR scan at 6:00 AM
            self._scheduler.add_job(
                self._run_daily_ar_scan,
                trigger=CronTrigger(hour=6, minute=0),
                id="collections_daily_ar_scan",
                name="Collections daily AR aging scan for delinquent accounts",
                misfire_grace_time=3600,
            )

            # Job 2: Daily escalation check at 7:00 AM
            self._scheduler.add_job(
                self._run_daily_escalation_check,
                trigger=CronTrigger(hour=7, minute=0),
                id="collections_daily_escalation_check",
                name="Collections daily escalation stage check for delinquent accounts",
                misfire_grace_time=3600,
            )

            self._scheduler.start()
            self._started = True
            logger.info(
                "collections_scheduler.started",
                jobs=["daily_ar_scan", "daily_escalation_check"],
                schedule_ar_scan="Daily 6:00 AM",
                schedule_escalation="Daily 7:00 AM",
            )
            return True

        except Exception as exc:
            logger.warning(
                "collections_scheduler.start_failed",
                error=str(exc),
            )
            return False

    def stop(self) -> None:
        """Shut down the scheduler."""
        if self._scheduler is not None and self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("collections_scheduler.stopped")

    async def _run_daily_ar_scan(self) -> None:
        """Run daily AR aging scan for all delinquent accounts.

        Queries all delinquent accounts via NotionCollectionsAdapter, then
        dispatches an ar_aging_report task for each to the Collections agent.
        Individual account failures do not block processing other accounts.
        """
        logger.info("collections_scheduler.ar_scan_triggered")

        if self._notion is None:
            logger.warning(
                "collections_scheduler.ar_scan_skipped",
                reason="notion_not_configured",
            )
            return

        try:
            accounts = await self._notion.get_all_delinquent_accounts()  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning(
                "collections_scheduler.ar_scan_query_failed",
                error=str(exc),
            )
            return

        if not accounts:
            logger.info("collections_scheduler.ar_scan_no_accounts", count=0)
            return

        logger.info(
            "collections_scheduler.ar_scan_processing",
            account_count=len(accounts),
        )

        results = {"success": 0, "failed": 0}

        for account in accounts:
            try:
                result = await self._agent.execute(  # type: ignore[union-attr]
                    {
                        "request_type": "ar_aging_report",
                        "account_id": account.get("account_id", ""),
                    },
                    context={},
                )
                if "error" not in result:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    logger.warning(
                        "collections_scheduler.ar_scan_partial",
                        account_id=account.get("account_id"),
                        error=result.get("error"),
                    )
            except Exception as exc:
                results["failed"] += 1
                logger.warning(
                    "collections_scheduler.ar_scan_account_failed",
                    account_id=account.get("account_id"),
                    error=str(exc),
                )

        logger.info("collections_scheduler.ar_scan_complete", **results)

    async def _run_daily_escalation_check(self) -> None:
        """Run daily escalation stage check for all delinquent accounts.

        Queries all delinquent accounts via NotionCollectionsAdapter, then
        dispatches a run_escalation_check task for each to the Collections agent.
        Individual account failures do not block processing other accounts.
        """
        logger.info("collections_scheduler.escalation_check_triggered")

        if self._notion is None:
            logger.warning(
                "collections_scheduler.escalation_check_skipped",
                reason="notion_not_configured",
            )
            return

        try:
            accounts = await self._notion.get_all_delinquent_accounts()  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning(
                "collections_scheduler.escalation_check_query_failed",
                error=str(exc),
            )
            return

        if not accounts:
            logger.info(
                "collections_scheduler.escalation_check_no_accounts", count=0
            )
            return

        logger.info(
            "collections_scheduler.escalation_check_processing",
            account_count=len(accounts),
        )

        results = {"success": 0, "failed": 0}

        for account in accounts:
            try:
                result = await self._agent.execute(  # type: ignore[union-attr]
                    {
                        "request_type": "run_escalation_check",
                        "account_id": account.get("account_id", ""),
                    },
                    context={},
                )
                if "error" not in result:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    logger.warning(
                        "collections_scheduler.escalation_check_partial",
                        account_id=account.get("account_id"),
                        error=result.get("error"),
                    )
            except Exception as exc:
                results["failed"] += 1
                logger.warning(
                    "collections_scheduler.escalation_check_account_failed",
                    account_id=account.get("account_id"),
                    error=str(exc),
                )

        logger.info("collections_scheduler.escalation_check_complete", **results)


__all__ = ["CollectionsScheduler"]
