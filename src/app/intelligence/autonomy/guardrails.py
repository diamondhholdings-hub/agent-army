"""Guardrail checker -- safety mechanism for all autonomous actions.

Implements three-tier action classification per CONTEXT.md locked decisions:
1. AUTONOMOUS_ACTIONS: Agent can execute without human approval
2. APPROVAL_REQUIRED: Agent must get human sign-off before executing
3. HARD_STOPS: Actions that are NEVER allowed autonomously

Unknown action types default to approval_required (fail-safe per RESEARCH.md
Pitfall 3). Additional stage gating blocks autonomous actions in late-stage
deals (negotiation, evaluation, closed).
"""

from __future__ import annotations

import structlog

from src.app.intelligence.autonomy.schemas import (
    ActionCategory,
    AutonomyAction,
    GuardrailResult,
)

logger = structlog.get_logger(__name__)


class GuardrailChecker:
    """Determines if an action can proceed autonomously or needs approval.

    Every autonomous action must pass through the guardrail check before
    execution. Hard stops are absolute -- they cannot be overridden.
    Unknown action types fail safe to approval_required.

    Stage gating provides an additional layer: even autonomous actions
    are blocked in late-stage deals (negotiation, evaluation, closed_won,
    closed_lost) to ensure human oversight during critical deal phases.
    """

    # ── Three-Tier Action Classification ─────────────────────────────────

    AUTONOMOUS_ACTIONS: set[str] = {
        "send_follow_up_email",
        "send_routine_response",
        "send_chat_message",
        "schedule_meeting",
        "qualify_conversation",
        "progress_early_stage",
        "update_account_context",
        "create_briefing",
        "log_interaction",
    }

    APPROVAL_REQUIRED: set[str] = {
        "send_proposal",
        "discuss_pricing",
        "negotiate_terms",
        "progress_past_evaluation",
        "contact_c_suite",
        "share_minutes_externally",
        "modify_account_plan",
        "escalate_to_management",
    }

    HARD_STOPS: set[str] = {
        "commit_pricing",
        "modify_contract",
        "approve_discount",
        "strategic_decision",
        "initiate_executive_relationship",
        "legal_commitment",
        "market_positioning_change",
    }

    # Stages where autonomous actions are blocked (stage gating)
    _RESTRICTED_STAGES: set[str] = {
        "negotiation",
        "evaluation",
        "closed_won",
        "closed_lost",
    }

    def check(self, action: AutonomyAction) -> GuardrailResult:
        """Run guardrail check on a proposed action.

        Priority order:
        1. Hard stops: always blocked, requires human
        2. Approval required: blocked, requires human approval
        3. Autonomous: allowed unless stage-gated
        4. Unknown: fail-safe to approval_required

        Args:
            action: The proposed autonomous action to check.

        Returns:
            GuardrailResult with allowed/blocked status and reason.
        """
        action_type = action.action_type

        # 1. Hard stops -- NEVER proceed autonomously
        if action_type in self.HARD_STOPS:
            logger.warning(
                "guardrails.hard_stop",
                action_type=action_type,
                account_id=action.account_id,
            )
            return GuardrailResult(
                allowed=False,
                reason="hard_stop",
                requires_human=True,
                action=action,
            )

        # 2. Approval required
        if action_type in self.APPROVAL_REQUIRED:
            logger.info(
                "guardrails.approval_required",
                action_type=action_type,
                account_id=action.account_id,
            )
            return GuardrailResult(
                allowed=False,
                reason="approval_required",
                requires_human=True,
                action=action,
            )

        # 3. Autonomous actions with stage gating
        if action_type in self.AUTONOMOUS_ACTIONS:
            if action.deal_stage and action.deal_stage in self._RESTRICTED_STAGES:
                logger.info(
                    "guardrails.stage_gate",
                    action_type=action_type,
                    deal_stage=action.deal_stage,
                    account_id=action.account_id,
                )
                return GuardrailResult(
                    allowed=False,
                    reason="stage_gate",
                    requires_human=True,
                    action=action,
                )

            logger.info(
                "guardrails.autonomous_allowed",
                action_type=action_type,
                account_id=action.account_id,
            )
            return GuardrailResult(
                allowed=True,
                reason="autonomous",
                requires_human=False,
                action=action,
            )

        # 4. Unknown action type -- fail-safe to approval_required
        logger.warning(
            "guardrails.unknown_action_type",
            action_type=action_type,
            account_id=action.account_id,
            message="Unknown action defaulting to approval_required (fail-safe)",
        )
        return GuardrailResult(
            allowed=False,
            reason="unknown_action_type",
            requires_human=True,
            action=action,
        )

    def classify_action(self, action_type: str) -> ActionCategory:
        """Classify an action type without performing a full check.

        Used for UI display to show which category an action falls into.

        Args:
            action_type: The action type string to classify.

        Returns:
            ActionCategory enum value.
        """
        if action_type in self.HARD_STOPS:
            return ActionCategory.hard_stop
        if action_type in self.APPROVAL_REQUIRED:
            return ActionCategory.approval_required
        if action_type in self.AUTONOMOUS_ACTIONS:
            return ActionCategory.autonomous
        # Unknown defaults to approval_required (fail-safe)
        return ActionCategory.approval_required

    def get_allowed_actions(self) -> set[str]:
        """Return the set of action types that can proceed autonomously.

        Returns:
            Set of autonomous action type strings.
        """
        return set(self.AUTONOMOUS_ACTIONS)

    def get_restricted_actions(self) -> dict[str, str]:
        """Return all non-autonomous actions with their restriction reason.

        Returns:
            Dict mapping action_type to reason string
            (approval_required or hard_stop).
        """
        restricted: dict[str, str] = {}
        for action_type in self.APPROVAL_REQUIRED:
            restricted[action_type] = "approval_required"
        for action_type in self.HARD_STOPS:
            restricted[action_type] = "hard_stop"
        return restricted
