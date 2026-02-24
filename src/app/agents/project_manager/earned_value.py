"""Earned value management calculations for the Project Manager agent.

Pure Python module with NO LLM calls. All functions are deterministic
arithmetic operating on PM domain models. Uses the PMBOK 0/100 completion
rule: tasks are either 0% complete (not finished) or 100% complete
(finished). This avoids subjective percent-complete estimates.

Key formulas (PMBOK standard):
    BCWP (Earned Value) = sum of budget for completed tasks
    ACWP (Actual Cost)  = actual effort spent (passed in)
    BCWS (Planned Value) = total_budget * scheduled_completion_pct
    CPI  = BCWP / ACWP   (cost efficiency; >1 = under budget)
    SPI  = BCWP / BCWS   (schedule efficiency; >1 = ahead of schedule)
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.app.agents.project_manager.schemas import (
    EarnedValueMetrics,
    MilestoneProgress,
    WBSMilestone,
    WBSTask,
)


def calculate_earned_value(
    tasks: list[WBSTask],
    actual_days_spent: float,
    scheduled_completion_pct: float,
) -> EarnedValueMetrics:
    """Calculate earned value metrics from task-level data using 0/100 rule.

    The 0/100 rule means only fully completed tasks count toward earned
    value. In-progress tasks contribute 0% until they are marked completed.
    This provides the most conservative and objective EV measurement.

    Args:
        tasks: List of WBS tasks with status and duration_days.
        actual_days_spent: Total actual effort spent so far (person-days).
            This is the ACWP (Actual Cost of Work Performed).
        scheduled_completion_pct: Fraction of the schedule elapsed (0.0-1.0).
            Used to compute BCWS (Planned Value). For example, if the
            project is 3 months into a 6-month timeline, this would be 0.5.

    Returns:
        EarnedValueMetrics with BCWP, ACWP, BCWS, CPI, and SPI.

    Examples:
        >>> from src.app.agents.project_manager.schemas import WBSTask
        >>> tasks = [
        ...     WBSTask(task_id="t1", name="A", owner="X",
        ...             duration_days=5, status="completed"),
        ...     WBSTask(task_id="t2", name="B", owner="Y",
        ...             duration_days=10, status="not_started"),
        ... ]
        >>> ev = calculate_earned_value(tasks, actual_days_spent=6.0,
        ...                             scheduled_completion_pct=0.5)
        >>> ev.bcwp
        5.0
        >>> ev.cpi  # 5.0 / 6.0
        0.833...
    """
    # BCWP: sum of budget for completed tasks (0/100 rule)
    bcwp = sum(t.duration_days for t in tasks if t.status == "completed")

    # ACWP: actual effort spent (passed in directly)
    acwp = actual_days_spent

    # Total planned budget: sum of all task budgets
    total_planned_budget = sum(t.duration_days for t in tasks)

    # BCWS: planned value = total budget * scheduled completion fraction
    bcws = total_planned_budget * scheduled_completion_pct

    # CPI: cost performance index (guard against division by zero)
    cpi = bcwp / acwp if acwp > 0 else 1.0

    # SPI: schedule performance index (guard against division by zero)
    spi = bcwp / bcws if bcws > 0 else 1.0

    return EarnedValueMetrics(
        bcwp=bcwp,
        acwp=acwp,
        bcws=bcws,
        cpi=cpi,
        spi=spi,
    )


def compute_milestone_progress(milestone: WBSMilestone) -> MilestoneProgress:
    """Compute progress metrics for a single milestone.

    Calculates task completion percentage and derives milestone health
    status by comparing current progress against the target date.

    Status derivation logic:
        - "completed": All tasks are completed
        - "overdue": Target date has passed and not all tasks are completed
        - "at_risk": Target date is within 2 days and completion < 80%
        - "on_track": Otherwise (sufficient progress relative to timeline)

    Args:
        milestone: A WBS milestone with its constituent tasks.

    Returns:
        MilestoneProgress snapshot with completion metrics and status.
    """
    total_tasks = len(milestone.tasks)
    completed_tasks = sum(
        1 for t in milestone.tasks if t.status == "completed"
    )
    pct_complete = (completed_tasks / total_tasks * 100.0) if total_tasks > 0 else 0.0

    now = datetime.now(timezone.utc)
    target = milestone.target_date
    # Ensure target is timezone-aware for comparison
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)

    # Derive status
    if completed_tasks == total_tasks and total_tasks > 0:
        status: str = "completed"
    elif now > target:
        status = "overdue"
    elif (target - now).days <= 2 and pct_complete < 80.0:
        status = "at_risk"
    else:
        status = "on_track"

    return MilestoneProgress(
        milestone_id=milestone.milestone_id,
        name=milestone.name,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pct_complete=pct_complete,
        status=status,  # type: ignore[arg-type]
        target_date=milestone.target_date,
        projected_date=None,
    )


__all__ = [
    "calculate_earned_value",
    "compute_milestone_progress",
]
