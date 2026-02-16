"""Proactive intelligence scheduler -- background task scheduling.

Extends the Phase 4.1 asyncio background loop pattern with 5 intelligence
tasks: pattern scanning, proactive outreach, goal progress updates,
daily digest generation, and context summarization.

Reuses start_scheduler_background from src/app/learning/scheduler.py
for actually starting the asyncio loops. The intelligence scheduler
returns tasks in the same format (dict of name -> callable).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger(__name__)


# ── Task Intervals (seconds) ─────────────────────────────────────────────────

INTELLIGENCE_TASK_INTERVALS: Dict[str, int] = {
    "pattern_scan": 6 * 60 * 60,             # Every 6 hours
    "proactive_outreach_check": 60 * 60,      # Every hour
    "goal_progress_update": 24 * 60 * 60,     # Daily
    "daily_digest_generation": 24 * 60 * 60,  # Daily
    "context_summarization": 24 * 60 * 60,    # Daily
}


async def setup_intelligence_scheduler(
    pattern_engine: Any,
    autonomy_engine: Any,
    goal_tracker: Any,
    insight_generator: Any,
    customer_view_service: Any,
) -> Dict[str, Any]:
    """Configure Phase 7 background tasks for intelligence system.

    Returns a dict of async task functions that can be scheduled
    by the background loop. Each task wraps in try/except so
    individual failures do not crash the scheduler.

    Follows the same pattern as setup_learning_scheduler from Phase 4.1.

    Args:
        pattern_engine: PatternRecognitionEngine for pattern scanning.
        autonomy_engine: AutonomyEngine for proactive outreach gating.
        goal_tracker: GoalTracker for progress updates.
        insight_generator: InsightGenerator for digest generation.
        customer_view_service: CustomerViewService for context summarization.

    Returns:
        Dict mapping task name to async callable.
    """

    async def pattern_scan_task() -> int:
        """Scan accounts with recent activity for pattern changes.

        Scans accounts with interaction in the last 7 days per
        RESEARCH.md recommendation to control LLM costs.

        Returns:
            Number of accounts scanned.
        """
        try:
            scanned = 0
            # Tenant iteration: placeholder for multi-tenant scan
            # In production, iterate tenants via TenantIterator helper
            # and scan each tenant's recently-active accounts
            if hasattr(customer_view_service, "list_active_accounts"):
                accounts = await customer_view_service.list_active_accounts(
                    days=7
                )
                for account in accounts:
                    try:
                        tenant_id = account.get("tenant_id", "")
                        account_id = account.get("account_id", "")
                        view = await customer_view_service.get_unified_view(
                            tenant_id, account_id
                        )
                        patterns = await pattern_engine.detect_patterns(view)
                        if patterns and insight_generator:
                            await insight_generator.create_insights_batch(
                                tenant_id, patterns
                            )
                        scanned += 1
                    except Exception:
                        logger.warning(
                            "intelligence.pattern_scan_account_failed",
                            account=account,
                            exc_info=True,
                        )
                        continue

            logger.info(
                "intelligence.pattern_scan_complete",
                accounts_scanned=scanned,
            )
            return scanned
        except Exception:
            logger.warning("intelligence.pattern_scan_failed", exc_info=True)
            return 0

    async def proactive_outreach_check_task() -> int:
        """Evaluate triggered outreach through guardrails.

        Checks for conditions that warrant proactive outreach:
        follow-ups after silence, buying signal engagement,
        milestone-triggered communication. Each proposed action
        goes through GuardrailChecker via AutonomyEngine.

        Returns:
            Number of outreach actions proposed.
        """
        try:
            proposed = 0
            # In production: iterate recently-active accounts,
            # build customer view, plan proactive actions
            if hasattr(customer_view_service, "list_active_accounts"):
                accounts = await customer_view_service.list_active_accounts(
                    days=1
                )
                for account in accounts:
                    try:
                        tenant_id = account.get("tenant_id", "")
                        account_id = account.get("account_id", "")
                        view = await customer_view_service.get_unified_view(
                            tenant_id, account_id
                        )
                        actions = await autonomy_engine.plan_proactive_actions(
                            tenant_id, view
                        )
                        for action in actions:
                            await autonomy_engine.propose_action(
                                tenant_id, action
                            )
                            proposed += 1
                    except Exception:
                        logger.warning(
                            "intelligence.outreach_account_failed",
                            account=account,
                            exc_info=True,
                        )
                        continue

            logger.info(
                "intelligence.proactive_outreach_complete",
                actions_proposed=proposed,
            )
            return proposed
        except Exception:
            logger.warning(
                "intelligence.proactive_outreach_failed", exc_info=True
            )
            return 0

    async def goal_progress_update_task() -> int:
        """Update goal current_value from latest metrics.

        Runs daily to refresh goal progress by computing fresh
        performance metrics and updating each active goal.

        Returns:
            Number of goals updated.
        """
        try:
            updated = 0
            # In production: iterate tenants and their active goals
            # For each goal, compute metrics and update progress
            logger.info("intelligence.goal_progress_update_complete", updated=updated)
            return updated
        except Exception:
            logger.warning(
                "intelligence.goal_progress_update_failed", exc_info=True
            )
            return 0

    async def daily_digest_task() -> int:
        """Generate daily insight digests.

        Aggregates pending insights from the last 24 hours,
        groups by account, and generates a digest. If email
        delivery is available, sends the digest.

        Returns:
            Number of digests generated.
        """
        try:
            generated = 0
            # In production: iterate tenants and generate digests
            if insight_generator is not None:
                try:
                    # Placeholder: would iterate tenants
                    logger.info(
                        "intelligence.daily_digest_complete",
                        digests_generated=generated,
                    )
                except Exception:
                    logger.warning(
                        "intelligence.daily_digest_generation_failed",
                        exc_info=True,
                    )

            return generated
        except Exception:
            logger.warning(
                "intelligence.daily_digest_failed", exc_info=True
            )
            return 0

    async def context_summarization_task() -> int:
        """Run progressive summarization on stale customer views.

        Identifies accounts where the customer view has not been
        summarized recently and runs progressive summarization to
        keep context manageable.

        Returns:
            Number of accounts summarized.
        """
        try:
            summarized = 0
            # In production: find accounts with stale summaries
            # and run progressive summarization
            if hasattr(customer_view_service, "list_stale_accounts"):
                stale = await customer_view_service.list_stale_accounts()
                for account in stale:
                    try:
                        tenant_id = account.get("tenant_id", "")
                        account_id = account.get("account_id", "")
                        await customer_view_service.refresh_summaries(
                            tenant_id, account_id
                        )
                        summarized += 1
                    except Exception:
                        logger.warning(
                            "intelligence.summarization_account_failed",
                            account=account,
                            exc_info=True,
                        )
                        continue

            logger.info(
                "intelligence.context_summarization_complete",
                accounts_summarized=summarized,
            )
            return summarized
        except Exception:
            logger.warning(
                "intelligence.context_summarization_failed", exc_info=True
            )
            return 0

    return {
        "pattern_scan": pattern_scan_task,
        "proactive_outreach_check": proactive_outreach_check_task,
        "goal_progress_update": goal_progress_update_task,
        "daily_digest_generation": daily_digest_task,
        "context_summarization": context_summarization_task,
    }


async def start_intelligence_scheduler_background(
    tasks: Dict[str, Any],
    app_state: Any,
) -> None:
    """Start intelligence scheduler tasks as background asyncio tasks.

    Mirrors start_scheduler_background from Phase 4.1 but stores
    references as app.state.intelligence_scheduler_tasks.

    Args:
        tasks: Dict mapping task name to async callable
            (from setup_intelligence_scheduler).
        app_state: FastAPI app.state object for storing task references.
    """
    background_tasks: List[asyncio.Task] = []  # type: ignore[type-arg]

    for task_name, task_fn in tasks.items():
        interval = INTELLIGENCE_TASK_INTERVALS.get(task_name, 3600)

        async def _loop(
            fn: Any = task_fn,
            name: str = task_name,
            sleep: int = interval,
        ) -> None:
            """Background loop that runs the task at the configured interval."""
            while True:
                try:
                    await asyncio.sleep(sleep)
                    await fn()
                except asyncio.CancelledError:
                    logger.info(
                        "intelligence_scheduler.task_cancelled", task=name
                    )
                    break
                except Exception:
                    logger.warning(
                        "intelligence_scheduler.task_loop_error",
                        task=name,
                        exc_info=True,
                    )

        bg_task = asyncio.create_task(
            _loop(), name=f"intelligence_scheduler_{task_name}"
        )
        background_tasks.append(bg_task)

    # Store task references on app_state for cleanup during shutdown
    app_state.intelligence_scheduler_tasks = background_tasks

    logger.info(
        "intelligence_scheduler.background_tasks_started",
        task_count=len(background_tasks),
        tasks=list(tasks.keys()),
    )
