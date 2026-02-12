"""Post-conversation hook orchestrating all deal management operations.

Runs after every sales conversation to detect opportunities, update political
maps, refresh plans, and evaluate stage progression. This hook is fire-and-forget:
errors are logged but do not block the agent's conversation response.

Exports:
    PostConversationHook: Orchestrator for post-conversation deal management.
    HookResult: Summary of operations performed by the hook.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from src.app.agents.sales.schemas import ConversationState
from src.app.deals.detection import OpportunityDetector
from src.app.deals.political import PoliticalMapper
from src.app.deals.plans import PlanManager
from src.app.deals.progression import StageProgressionEngine
from src.app.deals.repository import DealRepository
from src.app.deals.schemas import (
    OpportunityCreate,
    OpportunityUpdate,
    ScoreSource,
)

logger = structlog.get_logger(__name__)


class HookResult(BaseModel):
    """Summary of operations performed by the post-conversation hook."""

    opportunities_created: int = 0
    opportunities_updated: int = 0
    stakeholders_updated: int = 0
    plans_updated: int = 0
    stage_progressions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PostConversationHook:
    """Runs after every sales conversation to detect opportunities,
    update political maps, refresh plans, and evaluate stage progression.

    This hook is fire-and-forget -- errors are logged but do not block
    the agent's conversation response.

    Args:
        detector: OpportunityDetector for post-conversation signal extraction.
        political_mapper: PoliticalMapper for stakeholder scoring.
        plan_manager: PlanManager for account/opportunity plan lifecycle.
        progression_engine: StageProgressionEngine for auto-advancement.
        repository: DealRepository for CRUD operations.
    """

    def __init__(
        self,
        detector: OpportunityDetector,
        political_mapper: PoliticalMapper,
        plan_manager: PlanManager,
        progression_engine: StageProgressionEngine,
        repository: DealRepository,
    ) -> None:
        self._detector = detector
        self._mapper = political_mapper
        self._plan_manager = plan_manager
        self._progression = progression_engine
        self._repo = repository

    async def run(
        self,
        tenant_id: str,
        conversation_text: str,
        conversation_state: ConversationState,
    ) -> HookResult:
        """Orchestrate all post-conversation deal management operations.

        Steps:
        1. Opportunity Detection -- detect signals, create/update opportunities
        2. Political Mapping -- score and update stakeholders mentioned
        3. Plan Updates -- refresh account and opportunity plans
        4. Stage Progression -- evaluate and apply stage advancement

        Entire flow is wrapped in try/except: errors are logged but never raised
        (fire-and-forget pattern).

        Args:
            tenant_id: Tenant UUID string.
            conversation_text: The conversation transcript.
            conversation_state: Current conversation state.

        Returns:
            HookResult summarizing all operations performed.
        """
        result = HookResult()

        try:
            account_id = conversation_state.account_id

            # Ensure account exists
            await self._ensure_account(
                tenant_id, account_id, conversation_state.contact_name
            )

            # ── 1. Opportunity Detection ──────────────────────────────────
            try:
                existing_opps = await self._repo.list_opportunities(tenant_id)
                account_opps = [
                    o for o in existing_opps if o.account_id == account_id
                ]

                signals = await self._detector.detect_signals(
                    conversation_text=conversation_text,
                    conversation_state=conversation_state,
                    existing_opportunities=account_opps,
                )

                if self._detector.should_create_opportunity(signals):
                    opp_name = (
                        f"{signals.product_line or 'Opportunity'} - "
                        f"{conversation_state.contact_name}"
                    )
                    opp_data = OpportunityCreate(
                        account_id=account_id,
                        name=opp_name,
                        product_line=signals.product_line,
                        deal_stage=conversation_state.deal_stage.value,
                        estimated_value=signals.estimated_value,
                        detection_confidence=signals.deal_potential_confidence,
                        source="agent_detected",
                    )
                    new_opp = await self._repo.create_opportunity(tenant_id, opp_data)
                    result.opportunities_created += 1

                    # Create opportunity plan for the new opportunity
                    stakeholders = await self._repo.list_stakeholders(
                        tenant_id, account_id
                    )
                    await self._plan_manager.create_or_update_opportunity_plan(
                        tenant_id=tenant_id,
                        opportunity_id=new_opp.id,
                        opportunity=new_opp,
                        conversation_state=conversation_state,
                        stakeholders=stakeholders,
                    )
                    result.plans_updated += 1

                elif self._detector.should_update_opportunity(signals):
                    opp_id = signals.matching_opportunity_id
                    update_data = OpportunityUpdate(
                        detection_confidence=signals.deal_potential_confidence,
                        estimated_value=signals.estimated_value,
                        product_line=signals.product_line,
                    )
                    await self._repo.update_opportunity(
                        tenant_id, opp_id, update_data
                    )
                    result.opportunities_updated += 1

            except Exception as exc:
                error_msg = f"Opportunity detection failed: {exc}"
                logger.warning("hook.opportunity_detection_error", error=str(exc))
                result.errors.append(error_msg)

            # ── 2. Political Mapping ──────────────────────────────────────
            try:
                stakeholders = await self._repo.list_stakeholders(
                    tenant_id, account_id
                )
                for stakeholder in stakeholders:
                    try:
                        # Refine scores from conversation
                        updated_scores, evidence = (
                            await self._mapper.refine_from_conversation(
                                stakeholder=stakeholder,
                                conversation_text=conversation_text,
                            )
                        )

                        # Detect roles from conversation
                        roles = await self._mapper.detect_roles_from_conversation(
                            conversation_text=conversation_text,
                            stakeholder_name=stakeholder.contact_name,
                        )

                        # Update stakeholder scores in repository
                        sources = {
                            k: ScoreSource.CONVERSATION_SIGNAL.value
                            for k in evidence
                        }
                        await self._repo.update_stakeholder_scores(
                            tenant_id=tenant_id,
                            stakeholder_id=stakeholder.id,
                            scores=updated_scores,
                            sources=sources,
                            evidence=evidence,
                        )
                        result.stakeholders_updated += 1

                    except Exception as exc:
                        logger.warning(
                            "hook.stakeholder_update_error",
                            stakeholder=stakeholder.contact_name,
                            error=str(exc),
                        )
                        result.errors.append(
                            f"Stakeholder update failed for {stakeholder.contact_name}: {exc}"
                        )

            except Exception as exc:
                error_msg = f"Political mapping failed: {exc}"
                logger.warning("hook.political_mapping_error", error=str(exc))
                result.errors.append(error_msg)

            # ── 3. Plan Updates ───────────────────────────────────────────
            try:
                stakeholders = await self._repo.list_stakeholders(
                    tenant_id, account_id
                )

                # Update account plan
                await self._plan_manager.create_or_update_account_plan(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    conversation_state=conversation_state,
                    stakeholders=stakeholders,
                )
                result.plans_updated += 1

                # Update opportunity plans for all active opportunities
                active_opps = [
                    o
                    for o in await self._repo.list_opportunities(tenant_id)
                    if o.account_id == account_id
                    and o.deal_stage not in ("closed_won", "closed_lost")
                ]
                for opp in active_opps:
                    await self._plan_manager.create_or_update_opportunity_plan(
                        tenant_id=tenant_id,
                        opportunity_id=opp.id,
                        opportunity=opp,
                        conversation_state=conversation_state,
                        stakeholders=stakeholders,
                    )
                    result.plans_updated += 1

            except Exception as exc:
                error_msg = f"Plan update failed: {exc}"
                logger.warning("hook.plan_update_error", error=str(exc))
                result.errors.append(error_msg)

            # ── 4. Stage Progression ──────────────────────────────────────
            try:
                active_opps = [
                    o
                    for o in await self._repo.list_opportunities(tenant_id)
                    if o.account_id == account_id
                    and o.deal_stage not in ("closed_won", "closed_lost")
                ]

                from src.app.agents.sales.schemas import DealStage

                for opp in active_opps:
                    try:
                        current_stage = DealStage(opp.deal_stage)
                    except ValueError:
                        continue

                    next_stage = self._progression.evaluate_progression(
                        current_stage=current_stage,
                        qualification=conversation_state.qualification,
                        interaction_count=conversation_state.interaction_count,
                    )

                    if next_stage is not None:
                        await self._repo.update_opportunity(
                            tenant_id,
                            opp.id,
                            OpportunityUpdate(deal_stage=next_stage.value),
                        )
                        progression_desc = (
                            f"{opp.name}: {opp.deal_stage} -> {next_stage.value}"
                        )
                        result.stage_progressions.append(progression_desc)
                        logger.info(
                            "hook.stage_progression_applied",
                            opportunity=opp.name,
                            from_stage=opp.deal_stage,
                            to_stage=next_stage.value,
                        )

            except Exception as exc:
                error_msg = f"Stage progression failed: {exc}"
                logger.warning("hook.stage_progression_error", error=str(exc))
                result.errors.append(error_msg)

        except Exception as exc:
            # Top-level catch: never raise from hook (fire-and-forget)
            error_msg = f"PostConversationHook failed: {exc}"
            logger.error("hook.run_failed", error=str(exc), exc_info=True)
            result.errors.append(error_msg)

        logger.info(
            "hook.run_complete",
            opportunities_created=result.opportunities_created,
            opportunities_updated=result.opportunities_updated,
            stakeholders_updated=result.stakeholders_updated,
            plans_updated=result.plans_updated,
            stage_progressions=len(result.stage_progressions),
            errors=len(result.errors),
        )

        return result

    async def _ensure_account(
        self, tenant_id: str, account_id: str, account_name: str
    ) -> None:
        """Get or create account for the conversation's account_id.

        Args:
            tenant_id: Tenant UUID string.
            account_id: Account UUID string.
            account_name: Fallback account name if creating new.
        """
        existing = await self._repo.get_account(tenant_id, account_id)
        if existing is not None:
            return

        from src.app.deals.schemas import AccountCreate

        try:
            await self._repo.create_account(
                tenant_id,
                AccountCreate(account_name=account_name or "Unknown Account"),
            )
            logger.info(
                "hook.account_created",
                tenant_id=tenant_id,
                account_id=account_id,
            )
        except Exception as exc:
            # Account creation may fail if ID already exists (race condition)
            # or if account_id doesn't match UUID format for the new account.
            # This is non-fatal for the hook.
            logger.debug(
                "hook.account_creation_skipped",
                error=str(exc),
            )
