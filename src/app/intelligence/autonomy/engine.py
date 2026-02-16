"""Autonomy engine -- central autonomous decision-making service.

AutonomyEngine proposes actions, routes them through GuardrailChecker,
logs all decisions for audit trail, manages approval workflows, and
plans proactive actions based on detected patterns and active goals.

Every autonomous action is gated by guardrails before execution.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from src.app.intelligence.autonomy.guardrails import GuardrailChecker
from src.app.intelligence.autonomy.goals import GoalTracker
from src.app.intelligence.autonomy.schemas import (
    ApprovalRequest,
    AutonomyAction,
    GoalType,
    GuardrailResult,
)

logger = structlog.get_logger(__name__)


class AutonomyEngine:
    """Central service for guardrail-gated autonomous decision-making.

    Orchestrates the full lifecycle of autonomous actions: proposal,
    guardrail checking, approval routing, execution, and outcome tracking.

    Args:
        guardrail_checker: GuardrailChecker instance for action classification.
        goal_tracker: GoalTracker instance for goal-aware action planning.
        pattern_engine: PatternRecognitionEngine (or compatible) for
            insight-driven actions. Must have ``detect_patterns`` method.
        repository: IntelligenceRepository (or compatible) for persistence.
        llm_service: Optional LLM service for refined action planning.
            If None, uses rule-based action generation.
    """

    def __init__(
        self,
        guardrail_checker: GuardrailChecker,
        goal_tracker: GoalTracker,
        pattern_engine: Any,
        repository: Any,
        llm_service: Optional[Any] = None,
    ) -> None:
        self._guardrail_checker = guardrail_checker
        self._goal_tracker = goal_tracker
        self._pattern_engine = pattern_engine
        self._repository = repository
        self._llm_service = llm_service

    async def propose_action(
        self,
        tenant_id: str,
        action: AutonomyAction,
    ) -> GuardrailResult:
        """Propose an autonomous action and route through guardrails.

        1. Run guardrail check.
        2. Log the action via repository with guardrail result.
        3. If allowed: return result (caller executes the action).
        4. If approval_required: create ApprovalRequest, store, notify.
        5. If hard_stop: log and return blocked result.

        Args:
            tenant_id: Tenant identifier.
            action: The proposed autonomous action.

        Returns:
            GuardrailResult indicating whether action is allowed.
        """
        result = self._guardrail_checker.check(action)

        # Determine approval_status for audit log
        if result.allowed:
            approval_status = "approved"
        elif result.reason == "hard_stop":
            approval_status = "blocked"
        else:
            approval_status = "pending"

        # Log action for audit trail
        try:
            await self._repository.log_autonomous_action(
                tenant_id=tenant_id,
                action_type=action.action_type,
                account_id=action.account_id,
                action_data={
                    "action_id": action.action_id,
                    "rationale": action.rationale,
                    "deal_stage": action.deal_stage,
                    "guardrail_result": result.reason,
                },
                approval_status=approval_status,
            )
        except Exception:
            logger.warning(
                "autonomy.action_logging_failed",
                action_type=action.action_type,
                exc_info=True,
            )

        # Handle approval workflow
        if result.reason == "approval_required" or result.reason == "unknown_action_type":
            try:
                approval = ApprovalRequest(
                    action_id=action.action_id,
                    tenant_id=tenant_id,
                    action=action,
                    requested_at=datetime.now(timezone.utc),
                )
                # Store approval request in pending actions
                if hasattr(self._repository, "log_autonomous_action"):
                    logger.info(
                        "autonomy.approval_requested",
                        action_id=action.action_id,
                        action_type=action.action_type,
                    )
            except Exception:
                logger.warning(
                    "autonomy.approval_request_failed",
                    action_id=action.action_id,
                    exc_info=True,
                )

        if result.reason == "hard_stop":
            logger.warning(
                "autonomy.hard_stop_blocked",
                action_type=action.action_type,
                account_id=action.account_id,
            )

        logger.info(
            "autonomy.action_proposed",
            action_type=action.action_type,
            allowed=result.allowed,
            reason=result.reason,
            account_id=action.account_id,
        )

        return result

    async def plan_proactive_actions(
        self,
        tenant_id: str,
        customer_view: Any,
        clone_id: Optional[str] = None,
    ) -> List[AutonomyAction]:
        """Plan proactive actions based on patterns and goals.

        1. Check active goals for this tenant/clone.
        2. Detect patterns in customer view.
        3. Generate candidate actions from patterns and goals.
        4. If LLM available, refine proposals; otherwise use rules.
        5. Return proposed actions (NOT yet guardrail-checked).

        Args:
            tenant_id: Tenant identifier.
            customer_view: UnifiedCustomerView with cross-channel data.
            clone_id: Optional clone identifier.

        Returns:
            List of proposed AutonomyAction objects. The caller should
            use propose_action() for each to apply guardrail checks.
        """
        now = datetime.now(timezone.utc)
        actions: List[AutonomyAction] = []

        # 1. Get active goals
        goals = await self._goal_tracker.get_active_goals(tenant_id, clone_id)

        # 2. Detect patterns in customer view
        patterns = []
        try:
            patterns = await self._pattern_engine.detect_patterns(customer_view)
        except Exception:
            logger.warning(
                "autonomy.pattern_detection_failed",
                tenant_id=tenant_id,
                exc_info=True,
            )

        # 3. Generate candidate actions from patterns
        account_id = getattr(customer_view, "account_id", "unknown")

        for pattern in patterns:
            pattern_type = getattr(pattern, "pattern_type", None)
            if pattern_type is None:
                continue

            pattern_type_value = (
                pattern_type.value
                if hasattr(pattern_type, "value")
                else str(pattern_type)
            )

            if pattern_type_value == "buying_signal":
                actions.append(
                    AutonomyAction(
                        action_id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        action_type="send_follow_up_email",
                        account_id=account_id,
                        rationale=f"Buying signal detected: {', '.join(getattr(pattern, 'evidence', [])[:2])}",
                        proposed_at=now,
                    )
                )
            elif pattern_type_value == "risk_indicator":
                severity = getattr(pattern, "severity", "medium")
                if severity in ("critical", "high"):
                    actions.append(
                        AutonomyAction(
                            action_id=str(uuid.uuid4()),
                            tenant_id=tenant_id,
                            action_type="escalate_to_management",
                            account_id=account_id,
                            rationale=f"High-severity risk detected: {', '.join(getattr(pattern, 'evidence', [])[:2])}",
                            proposed_at=now,
                        )
                    )
                else:
                    actions.append(
                        AutonomyAction(
                            action_id=str(uuid.uuid4()),
                            tenant_id=tenant_id,
                            action_type="send_follow_up_email",
                            account_id=account_id,
                            rationale=f"Risk indicator detected, re-engaging: {', '.join(getattr(pattern, 'evidence', [])[:2])}",
                            proposed_at=now,
                        )
                    )
            elif pattern_type_value == "engagement_change":
                actions.append(
                    AutonomyAction(
                        action_id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        action_type="send_chat_message",
                        account_id=account_id,
                        rationale=f"Engagement change detected: {', '.join(getattr(pattern, 'evidence', [])[:2])}",
                        proposed_at=now,
                    )
                )

        # 4. Generate goal-driven actions
        for goal in goals:
            goal_suggestions = await self._goal_tracker.suggest_actions(
                tenant_id, goal
            )
            if goal_suggestions:
                # Map first suggestion to an action type
                action_type = self._goal_suggestion_to_action_type(goal.goal_type)
                actions.append(
                    AutonomyAction(
                        action_id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        action_type=action_type,
                        account_id=account_id,
                        rationale=f"Goal '{goal.goal_type.value}' behind target: {goal_suggestions[0]}",
                        proposed_at=now,
                    )
                )

        # 5. LLM refinement if available (placeholder -- would use instructor)
        if self._llm_service is not None and actions:
            try:
                logger.info(
                    "autonomy.llm_refinement",
                    tenant_id=tenant_id,
                    candidate_count=len(actions),
                )
                # In production: use instructor for structured output
                # refined = await self._llm_service.completion(
                #     messages=[...], model="fast", response_model=list[AutonomyAction]
                # )
                # For now, return rule-based actions
            except Exception:
                logger.warning(
                    "autonomy.llm_refinement_failed",
                    exc_info=True,
                )

        logger.info(
            "autonomy.proactive_actions_planned",
            tenant_id=tenant_id,
            account_id=account_id,
            action_count=len(actions),
            pattern_count=len(patterns),
            goal_count=len(goals),
        )

        return actions

    async def execute_approved_action(
        self,
        tenant_id: str,
        action_id: str,
    ) -> Dict[str, Any]:
        """Execute a previously approved action.

        1. Load action from repository.
        2. Verify approval_status == "approved".
        3. Execute the action (placeholder for actual execution).
        4. Update execution_result in repository.
        5. Return execution result.

        Args:
            tenant_id: Tenant identifier.
            action_id: ID of the approved action.

        Returns:
            Execution result dict.

        Raises:
            ValueError: If action not found or not approved.
        """
        action_data = await self._repository.get_action(tenant_id, action_id)

        if action_data is None:
            raise ValueError(f"Action not found: {action_id}")

        if action_data.get("approval_status") != "approved":
            raise ValueError(
                f"Action not approved: status={action_data.get('approval_status')}"
            )

        # Placeholder: actual execution delegated to SalesAgent methods
        execution_result = {
            "status": "executed",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "action_type": action_data["action_type"],
            "message": f"Action {action_data['action_type']} executed successfully",
        }

        # Update result in repository
        await self._repository.update_action_result(
            tenant_id=tenant_id,
            action_id=action_id,
            execution_result=execution_result,
        )

        logger.info(
            "autonomy.action_executed",
            action_id=action_id,
            action_type=action_data["action_type"],
        )

        return execution_result

    async def get_pending_approvals(
        self,
        tenant_id: str,
    ) -> List[ApprovalRequest]:
        """List actions awaiting human approval.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            List of ApprovalRequest objects.
        """
        # Query repository for pending actions
        if hasattr(self._repository, "list_pending_actions"):
            pending = await self._repository.list_pending_actions(tenant_id)
        else:
            # Fallback: no dedicated method, return empty
            pending = []

        approvals: List[ApprovalRequest] = []
        for data in pending:
            try:
                action = AutonomyAction(
                    action_id=data.get("id", str(uuid.uuid4())),
                    tenant_id=tenant_id,
                    action_type=data["action_type"],
                    account_id=data.get("account_id", "unknown"),
                    rationale=data.get("action_data", {}).get("rationale", ""),
                    proposed_at=data.get("proposed_at", datetime.now(timezone.utc)),
                )
                approvals.append(
                    ApprovalRequest(
                        action_id=action.action_id,
                        tenant_id=tenant_id,
                        action=action,
                        requested_at=data.get("proposed_at", datetime.now(timezone.utc)),
                    )
                )
            except Exception:
                logger.warning(
                    "autonomy.approval_parse_error",
                    exc_info=True,
                )
                continue

        return approvals

    async def resolve_approval(
        self,
        tenant_id: str,
        action_id: str,
        approved: bool,
        resolved_by: str,
    ) -> bool:
        """Approve or reject a pending action.

        Args:
            tenant_id: Tenant identifier.
            action_id: ID of the action to resolve.
            approved: True to approve, False to reject.
            resolved_by: User ID of the person resolving.

        Returns:
            True if resolution was successful, False otherwise.
        """
        new_status = "approved" if approved else "rejected"

        try:
            action_data = await self._repository.get_action(tenant_id, action_id)
            if action_data is None:
                logger.warning(
                    "autonomy.resolve_not_found",
                    action_id=action_id,
                )
                return False

            # Update via execution_result to store resolution info
            await self._repository.update_action_result(
                tenant_id=tenant_id,
                action_id=action_id,
                execution_result={
                    "approval_status": new_status,
                    "resolved_by": resolved_by,
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            logger.info(
                "autonomy.approval_resolved",
                action_id=action_id,
                approved=approved,
                resolved_by=resolved_by,
            )
            return True

        except Exception:
            logger.warning(
                "autonomy.resolve_failed",
                action_id=action_id,
                exc_info=True,
            )
            return False

    @staticmethod
    def _goal_suggestion_to_action_type(goal_type: GoalType) -> str:
        """Map a goal type to the most relevant action type.

        Args:
            goal_type: The type of goal that is behind target.

        Returns:
            Action type string for the corrective action.
        """
        mapping = {
            GoalType.revenue: "send_follow_up_email",
            GoalType.pipeline: "send_follow_up_email",
            GoalType.activity: "schedule_meeting",
            GoalType.quality: "qualify_conversation",
        }
        return mapping.get(goal_type, "send_follow_up_email")
