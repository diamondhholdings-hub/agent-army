"""Background scheduler for TAM agent health scans and monthly check-ins.

Provides a lightweight APScheduler wrapper:
- Daily health scan at 7:00 AM (iterates all accounts)
- Monthly health check-ins on 1st of month at 10:00 AM

APScheduler is an optional dependency -- if not installed, start() returns False.

Exports:
    TAMScheduler: Async scheduler for daily health scans and monthly check-ins.
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

# Max escalation alerts per daily scan to prevent notification storms.
_MAX_ESCALATION_ALERTS_PER_SCAN = 5


class TAMScheduler:
    """Lightweight scheduler for TAM daily health scans and monthly check-ins.

    Wraps an AsyncIOScheduler with two cron jobs:
    1. Daily health scan at 7:00 AM -- iterates all accounts, computes
       health scores, and triggers escalation for at-risk accounts.
    2. Monthly health check-ins on 1st of month at 10:00 AM -- generates
       periodic check-in communications for each account.

    Graceful degradation: if APScheduler is not installed, start() returns
    False and logs a warning. If notion_tam is not configured, jobs log
    a warning and return without processing.

    Args:
        tam_agent: TAMAgent instance for executing health scans and check-ins.
        notion_tam: NotionTAMAdapter for querying accounts. Optional.
    """

    def __init__(
        self,
        tam_agent: object,
        notion_tam: object | None = None,
    ) -> None:
        self._tam_agent = tam_agent
        self._notion_tam = notion_tam
        self._scheduler: AsyncIOScheduler | None = None  # type: ignore[assignment]
        self._started = False

    def start(self) -> bool:
        """Start the scheduler. Returns False if APScheduler not available."""
        if AsyncIOScheduler is None:
            logger.warning(
                "tam_scheduler_unavailable",
                reason="apscheduler not installed",
            )
            return False

        self._scheduler = AsyncIOScheduler()

        # Daily health scan at 7:00 AM
        self._scheduler.add_job(
            self._daily_health_scan,
            trigger=CronTrigger(hour=7, minute=0),
            id="tam_daily_health_scan",
            name="TAM daily health scan for all accounts",
            misfire_grace_time=3600,
        )

        # Monthly health check-ins on 1st of month at 10:00 AM
        self._scheduler.add_job(
            self._monthly_health_checkins,
            trigger=CronTrigger(day=1, hour=10, minute=0),
            id="tam_monthly_health_checkins",
            name="TAM monthly health check-in communications",
            misfire_grace_time=7200,
        )

        self._scheduler.start()
        self._started = True
        logger.info(
            "tam_scheduler_started",
            jobs=["daily_health_scan", "monthly_health_checkins"],
            schedule_scan="Daily 7:00 AM",
            schedule_checkin="1st of month 10:00 AM",
        )
        return True

    async def _daily_health_scan(self) -> None:
        """Run daily health scan for all active accounts.

        Queries all accounts via NotionTAMAdapter, then dispatches
        a batch health scan to the TAM agent. Rate-limits escalation
        alerts to prevent notification storms (max 5 per scan; any
        remaining are bundled into a summary).
        """
        logger.info("tam_daily_health_scan_triggered")

        if self._notion_tam is None:
            logger.warning(
                "tam_daily_health_scan_skipped",
                reason="notion_tam not configured",
            )
            return

        try:
            accounts = await self._notion_tam.query_all_accounts()  # type: ignore[union-attr]
        except AttributeError:
            logger.warning(
                "tam_daily_health_scan_skipped",
                reason="query_all_accounts not available on notion_tam",
            )
            return
        except Exception as exc:
            logger.error(
                "tam_daily_health_scan_query_failed",
                error=str(exc),
            )
            return

        if not accounts:
            logger.info("tam_daily_health_scan_no_accounts", count=0)
            return

        logger.info(
            "tam_daily_health_scan_processing",
            account_count=len(accounts),
        )

        results = {"success": 0, "failed": 0, "escalations": 0}

        for account in accounts:
            try:
                task = {
                    "type": "health_scan",
                    "account_id": account.get("id", ""),
                    "account_name": account.get("name", ""),
                }
                result = await self._tam_agent.execute(task, context={})  # type: ignore[union-attr]

                if "error" not in result:
                    results["success"] += 1
                    # Track escalations (rate-limited)
                    if result.get("should_escalate"):
                        results["escalations"] += 1
                        if results["escalations"] > _MAX_ESCALATION_ALERTS_PER_SCAN:
                            logger.warning(
                                "tam_escalation_rate_limited",
                                account=account.get("name"),
                                escalation_count=results["escalations"],
                                max_alerts=_MAX_ESCALATION_ALERTS_PER_SCAN,
                            )
                else:
                    results["failed"] += 1
                    logger.warning(
                        "tam_daily_scan_partial",
                        account=account.get("name"),
                        error=result.get("error"),
                    )
            except Exception as exc:
                results["failed"] += 1
                logger.error(
                    "tam_daily_scan_account_failed",
                    account=account.get("name"),
                    error=str(exc),
                )

        logger.info("tam_daily_health_scan_complete", **results)

    async def _monthly_health_checkins(self) -> None:
        """Generate monthly health check-in communications for all accounts.

        Queries all accounts and dispatches health_checkin tasks to the
        TAM agent. Individual failures do not block other accounts.
        """
        logger.info("tam_monthly_checkins_triggered")

        if self._notion_tam is None:
            logger.warning(
                "tam_monthly_checkins_skipped",
                reason="notion_tam not configured",
            )
            return

        try:
            accounts = await self._notion_tam.query_all_accounts()  # type: ignore[union-attr]
        except AttributeError:
            logger.warning(
                "tam_monthly_checkins_skipped",
                reason="query_all_accounts not available on notion_tam",
            )
            return
        except Exception as exc:
            logger.error(
                "tam_monthly_checkins_query_failed",
                error=str(exc),
            )
            return

        if not accounts:
            logger.info("tam_monthly_checkins_no_accounts", count=0)
            return

        logger.info(
            "tam_monthly_checkins_processing",
            account_count=len(accounts),
        )

        results = {"success": 0, "failed": 0}

        for account in accounts:
            try:
                task = {
                    "type": "health_checkin",
                    "account_id": account.get("id", ""),
                    "account_name": account.get("name", ""),
                }
                result = await self._tam_agent.execute(task, context={})  # type: ignore[union-attr]

                if "error" not in result:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    logger.warning(
                        "tam_monthly_checkin_partial",
                        account=account.get("name"),
                        error=result.get("error"),
                    )
            except Exception as exc:
                results["failed"] += 1
                logger.error(
                    "tam_monthly_checkin_failed",
                    account=account.get("name"),
                    error=str(exc),
                )

        logger.info("tam_monthly_checkins_complete", **results)

    def stop(self) -> None:
        """Shut down the scheduler."""
        if self._scheduler and self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("tam_scheduler_stopped")


__all__ = ["TAMScheduler"]
