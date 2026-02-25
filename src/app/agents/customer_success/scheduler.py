"""Background scheduler for CSM agent health scans, contract checks, and QBR gen.

Provides a lightweight APScheduler wrapper with 3 cron jobs:
- Daily health scan at 7:00 AM (iterates all accounts)
- Daily contract check at 8:00 AM (alerts for accounts with renewal <= 60 days)
- Quarterly QBR generation on 1st of Jan/Apr/Jul/Oct at 4:00 AM

APScheduler is an optional dependency -- if not installed, start() returns False.

Exports:
    CSMScheduler: Async scheduler for daily health scans, contract checks,
        and quarterly QBR generation.
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


class CSMScheduler:
    """Lightweight scheduler for CSM daily scans, contract checks, and QBRs.

    Wraps an AsyncIOScheduler with three cron jobs:
    1. Daily health scan at 7:00 AM -- iterates all accounts, computes
       health scores via CSMHealthScorer, triggers churn alerts for at-risk.
    2. Daily contract check at 8:00 AM -- identifies accounts with
       days_to_renewal <= 60 and dispatches health scans for urgent review.
    3. Quarterly QBR generation on 1st of Jan/Apr/Jul/Oct at 4:00 AM --
       generates Quarterly Business Review content for all active accounts.

    Graceful degradation: if APScheduler is not installed, start() returns
    False and logs a warning. If notion_csm is not configured, jobs log
    a warning and return without processing.

    Args:
        csm_agent: CustomerSuccessAgent instance for executing tasks.
        notion_csm: NotionCSMAdapter for querying accounts. Optional.
    """

    def __init__(
        self,
        csm_agent: object,
        notion_csm: object | None = None,
    ) -> None:
        self._csm_agent = csm_agent
        self._notion_csm = notion_csm
        self._scheduler: AsyncIOScheduler | None = None  # type: ignore[assignment]
        self._started = False

    def start(self) -> bool:
        """Start the scheduler. Returns False if APScheduler not available."""
        if AsyncIOScheduler is None:
            logger.warning(
                "csm_scheduler_unavailable",
                reason="apscheduler not installed",
            )
            return False

        self._scheduler = AsyncIOScheduler()

        # Job 1: Daily health scan at 7:00 AM
        self._scheduler.add_job(
            self._daily_health_scan,
            trigger=CronTrigger(hour=7, minute=0),
            id="csm_daily_health_scan",
            name="CSM daily health scan for all accounts",
            misfire_grace_time=3600,
        )

        # Job 2: Daily contract check at 8:00 AM
        self._scheduler.add_job(
            self._daily_contract_check,
            trigger=CronTrigger(hour=8, minute=0),
            id="csm_daily_contract_check",
            name="CSM daily contract renewal proximity check",
            misfire_grace_time=3600,
        )

        # Job 3: Quarterly QBR generation on 1st of Jan/Apr/Jul/Oct at 4:00 AM
        self._scheduler.add_job(
            self._quarterly_qbr_generation,
            trigger=CronTrigger(month="1,4,7,10", day=1, hour=4, minute=0),
            id="csm_quarterly_qbr",
            name="CSM quarterly QBR generation for all accounts",
            misfire_grace_time=7200,
        )

        self._scheduler.start()
        self._started = True
        logger.info(
            "csm_scheduler_started",
            jobs=[
                "daily_health_scan",
                "daily_contract_check",
                "quarterly_qbr_generation",
            ],
            schedule_scan="Daily 7:00 AM",
            schedule_contract="Daily 8:00 AM",
            schedule_qbr="Quarterly 1st Jan/Apr/Jul/Oct 4:00 AM",
        )
        return True

    async def _daily_health_scan(self) -> None:
        """Run daily health scan for all active accounts.

        Queries all accounts via NotionCSMAdapter, then dispatches
        a health_scan task for each to the CSM agent.
        """
        logger.info("csm_daily_health_scan_triggered")

        if self._notion_csm is None:
            logger.warning(
                "csm_daily_health_scan_skipped",
                reason="notion_csm not configured",
            )
            return

        try:
            accounts = await self._notion_csm.query_all_accounts()  # type: ignore[union-attr]
        except AttributeError:
            logger.warning(
                "csm_daily_health_scan_skipped",
                reason="query_all_accounts not available on notion_csm",
            )
            return
        except Exception as exc:
            logger.error(
                "csm_daily_health_scan_query_failed",
                error=str(exc),
            )
            return

        if not accounts:
            logger.info("csm_daily_health_scan_no_accounts", count=0)
            return

        logger.info(
            "csm_daily_health_scan_processing",
            account_count=len(accounts),
        )

        results = {"success": 0, "failed": 0}

        for account in accounts:
            try:
                task = {
                    "type": "health_scan",
                    "account_id": account.get("id", ""),
                    "account_name": account.get("name", ""),
                }
                result = await self._csm_agent.execute(task, context={})  # type: ignore[union-attr]

                if "error" not in result:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    logger.warning(
                        "csm_daily_scan_partial",
                        account=account.get("name"),
                        error=result.get("error"),
                    )
            except Exception as exc:
                results["failed"] += 1
                logger.error(
                    "csm_daily_scan_account_failed",
                    account=account.get("name"),
                    error=str(exc),
                )

        logger.info("csm_daily_health_scan_complete", **results)

    async def _daily_contract_check(self) -> None:
        """Check contract renewal proximity for all accounts.

        Queries all accounts, identifies those with days_to_renewal <= 60,
        and dispatches health_scan tasks for urgent contract-proximity review.
        """
        logger.info("csm_daily_contract_check_triggered")

        if self._notion_csm is None:
            logger.warning(
                "csm_daily_contract_check_skipped",
                reason="notion_csm not configured",
            )
            return

        try:
            accounts = await self._notion_csm.query_all_accounts()  # type: ignore[union-attr]
        except AttributeError:
            logger.warning(
                "csm_daily_contract_check_skipped",
                reason="query_all_accounts not available on notion_csm",
            )
            return
        except Exception as exc:
            logger.error(
                "csm_daily_contract_check_query_failed",
                error=str(exc),
            )
            return

        if not accounts:
            logger.info("csm_daily_contract_check_no_accounts", count=0)
            return

        # Filter accounts with contract end date within 60 days
        urgent_accounts: list[dict] = []
        now = datetime.now(timezone.utc)

        for account in accounts:
            contract_end = account.get("Contract End Date") or account.get(
                "contract_end_date"
            )
            if contract_end is None:
                continue

            try:
                if isinstance(contract_end, str):
                    # Parse ISO date string
                    end_date = datetime.fromisoformat(
                        contract_end.replace("Z", "+00:00")
                    )
                elif isinstance(contract_end, datetime):
                    end_date = contract_end
                else:
                    continue

                days_to_renewal = (end_date - now).days
                if days_to_renewal <= 60:
                    account["days_to_renewal"] = days_to_renewal
                    urgent_accounts.append(account)
            except (ValueError, TypeError) as parse_err:
                logger.warning(
                    "csm_contract_check_parse_failed",
                    account=account.get("name"),
                    error=str(parse_err),
                )

        if not urgent_accounts:
            logger.info(
                "csm_daily_contract_check_none_urgent",
                total_accounts=len(accounts),
            )
            return

        logger.info(
            "csm_daily_contract_check_processing",
            urgent_count=len(urgent_accounts),
            total_accounts=len(accounts),
        )

        results = {"success": 0, "failed": 0}

        for account in urgent_accounts:
            try:
                task = {
                    "type": "health_scan",
                    "account_id": account.get("id", ""),
                    "account_name": account.get("name", ""),
                }
                result = await self._csm_agent.execute(task, context={})  # type: ignore[union-attr]

                if "error" not in result:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    logger.warning(
                        "csm_contract_check_partial",
                        account=account.get("name"),
                        days_to_renewal=account.get("days_to_renewal"),
                        error=result.get("error"),
                    )
            except Exception as exc:
                results["failed"] += 1
                logger.error(
                    "csm_contract_check_account_failed",
                    account=account.get("name"),
                    error=str(exc),
                )

        logger.info("csm_daily_contract_check_complete", **results)

    async def _quarterly_qbr_generation(self) -> None:
        """Generate Quarterly Business Reviews for all active accounts.

        Computes the current quarter label and dispatches generate_qbr tasks
        to the CSM agent. Individual failures do not block other accounts.
        """
        logger.info("csm_quarterly_qbr_triggered")

        if self._notion_csm is None:
            logger.warning(
                "csm_quarterly_qbr_skipped",
                reason="notion_csm not configured",
            )
            return

        try:
            accounts = await self._notion_csm.query_all_accounts()  # type: ignore[union-attr]
        except AttributeError:
            logger.warning(
                "csm_quarterly_qbr_skipped",
                reason="query_all_accounts not available on notion_csm",
            )
            return
        except Exception as exc:
            logger.error(
                "csm_quarterly_qbr_query_failed",
                error=str(exc),
            )
            return

        if not accounts:
            logger.info("csm_quarterly_qbr_no_accounts", count=0)
            return

        # Compute current quarter label
        now = datetime.now(timezone.utc)
        quarter = (now.month - 1) // 3 + 1
        period = f"Q{quarter} {now.year}"

        logger.info(
            "csm_quarterly_qbr_processing",
            account_count=len(accounts),
            period=period,
        )

        results = {"success": 0, "failed": 0}

        for account in accounts:
            try:
                task = {
                    "type": "generate_qbr",
                    "account_id": account.get("id", ""),
                    "account_name": account.get("name", ""),
                    "account_data": account,
                    "health_history": {},
                    "period": period,
                }
                result = await self._csm_agent.execute(task, context={})  # type: ignore[union-attr]

                if "error" not in result:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    logger.warning(
                        "csm_quarterly_qbr_partial",
                        account=account.get("name"),
                        error=result.get("error"),
                    )
            except Exception as exc:
                results["failed"] += 1
                logger.error(
                    "csm_quarterly_qbr_account_failed",
                    account=account.get("name"),
                    error=str(exc),
                )

        logger.info("csm_quarterly_qbr_complete", **results)

    def stop(self) -> None:
        """Shut down the scheduler."""
        if self._scheduler and self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("csm_scheduler_stopped")


__all__ = ["CSMScheduler"]
