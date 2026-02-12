"""Qualification signal extraction and incremental merge logic.

Provides structured LLM extraction of BANT and MEDDIC qualification signals
from conversation text using instructor + LiteLLM, and pure merge functions
that preserve existing high-confidence data while incorporating new evidence.

Merge strategy (anti-Pitfall 3: never overwrite existing qualification data):
- For each signal field: only update if new value has higher confidence OR
  new value is identified and existing is not.
- Evidence is always appended, never replaced.
- List fields (decision_criteria, key_insights) extend with unique items.
- Contact fields prefer non-None values.
- Recommended next questions are always replaced (they should be fresh).

Exports:
    merge_bant_signals: Merge two BANTSignals preserving higher-confidence data.
    merge_meddic_signals: Merge two MEDDICSignals preserving higher-confidence data.
    merge_qualification_signals: Merge two QualificationState objects.
    QualificationExtractor: LLM-powered extraction using instructor + LiteLLM.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from src.app.agents.sales.schemas import (
    BANTSignals,
    MEDDICSignals,
    QualificationState,
)

logger = structlog.get_logger(__name__)


# ── BANT Merge ────────────────────────────────────────────────────────────────


def merge_bant_signals(existing: BANTSignals, new: BANTSignals) -> BANTSignals:
    """Merge two BANTSignals, preserving higher-confidence existing data.

    For each BANT dimension (budget, authority, need, timeline):
    - Only update if new value has higher confidence OR new value is
      identified and existing is not.
    - Evidence is appended (joined with ' | ') when both exist.

    Args:
        existing: Current BANT signals (higher priority on ties).
        new: Newly extracted BANT signals.

    Returns:
        Merged BANTSignals.
    """
    return BANTSignals(
        # Budget
        budget_identified=existing.budget_identified or new.budget_identified,
        budget_range=_pick_by_confidence(
            existing.budget_range,
            existing.budget_confidence,
            new.budget_range,
            new.budget_confidence,
            existing.budget_identified,
            new.budget_identified,
        ),
        budget_evidence=_merge_evidence(existing.budget_evidence, new.budget_evidence),
        budget_confidence=max(existing.budget_confidence, new.budget_confidence),
        # Authority
        authority_identified=existing.authority_identified or new.authority_identified,
        authority_contact=_pick_by_confidence(
            existing.authority_contact,
            existing.authority_confidence,
            new.authority_contact,
            new.authority_confidence,
            existing.authority_identified,
            new.authority_identified,
        ),
        authority_role=_pick_by_confidence(
            existing.authority_role,
            existing.authority_confidence,
            new.authority_role,
            new.authority_confidence,
            existing.authority_identified,
            new.authority_identified,
        ),
        authority_evidence=_merge_evidence(
            existing.authority_evidence, new.authority_evidence
        ),
        authority_confidence=max(
            existing.authority_confidence, new.authority_confidence
        ),
        # Need
        need_identified=existing.need_identified or new.need_identified,
        need_description=_pick_by_confidence(
            existing.need_description,
            existing.need_confidence,
            new.need_description,
            new.need_confidence,
            existing.need_identified,
            new.need_identified,
        ),
        need_evidence=_merge_evidence(existing.need_evidence, new.need_evidence),
        need_confidence=max(existing.need_confidence, new.need_confidence),
        # Timeline
        timeline_identified=existing.timeline_identified or new.timeline_identified,
        timeline_description=_pick_by_confidence(
            existing.timeline_description,
            existing.timeline_confidence,
            new.timeline_description,
            new.timeline_confidence,
            existing.timeline_identified,
            new.timeline_identified,
        ),
        timeline_evidence=_merge_evidence(
            existing.timeline_evidence, new.timeline_evidence
        ),
        timeline_confidence=max(existing.timeline_confidence, new.timeline_confidence),
    )


# ── MEDDIC Merge ─────────────────────────────────────────────────────────────


def merge_meddic_signals(
    existing: MEDDICSignals, new: MEDDICSignals
) -> MEDDICSignals:
    """Merge two MEDDICSignals, preserving higher-confidence existing data.

    For each MEDDIC dimension: same rules as BANT merge.
    For list fields (decision_criteria): extend with new unique items.
    For contact fields: prefer non-None.

    Args:
        existing: Current MEDDIC signals (higher priority on ties).
        new: Newly extracted MEDDIC signals.

    Returns:
        Merged MEDDICSignals.
    """
    return MEDDICSignals(
        # Metrics
        metrics_identified=existing.metrics_identified or new.metrics_identified,
        metrics_description=_pick_by_confidence(
            existing.metrics_description,
            existing.metrics_confidence,
            new.metrics_description,
            new.metrics_confidence,
            existing.metrics_identified,
            new.metrics_identified,
        ),
        metrics_evidence=_merge_evidence(
            existing.metrics_evidence, new.metrics_evidence
        ),
        metrics_confidence=max(existing.metrics_confidence, new.metrics_confidence),
        # Economic Buyer
        economic_buyer_identified=existing.economic_buyer_identified
        or new.economic_buyer_identified,
        economic_buyer_contact=_prefer_non_none(
            existing.economic_buyer_contact,
            new.economic_buyer_contact,
            existing.economic_buyer_confidence,
            new.economic_buyer_confidence,
        ),
        economic_buyer_evidence=_merge_evidence(
            existing.economic_buyer_evidence, new.economic_buyer_evidence
        ),
        economic_buyer_confidence=max(
            existing.economic_buyer_confidence, new.economic_buyer_confidence
        ),
        # Decision Criteria (list field -- extend with unique items)
        decision_criteria_identified=existing.decision_criteria_identified
        or new.decision_criteria_identified,
        decision_criteria=_merge_unique_list(
            existing.decision_criteria, new.decision_criteria
        ),
        decision_criteria_evidence=_merge_evidence(
            existing.decision_criteria_evidence, new.decision_criteria_evidence
        ),
        decision_criteria_confidence=max(
            existing.decision_criteria_confidence, new.decision_criteria_confidence
        ),
        # Decision Process
        decision_process_identified=existing.decision_process_identified
        or new.decision_process_identified,
        decision_process_description=_pick_by_confidence(
            existing.decision_process_description,
            existing.decision_process_confidence,
            new.decision_process_description,
            new.decision_process_confidence,
            existing.decision_process_identified,
            new.decision_process_identified,
        ),
        decision_process_evidence=_merge_evidence(
            existing.decision_process_evidence, new.decision_process_evidence
        ),
        decision_process_confidence=max(
            existing.decision_process_confidence, new.decision_process_confidence
        ),
        # Pain
        pain_identified=existing.pain_identified or new.pain_identified,
        pain_description=_pick_by_confidence(
            existing.pain_description,
            existing.pain_confidence,
            new.pain_description,
            new.pain_confidence,
            existing.pain_identified,
            new.pain_identified,
        ),
        pain_evidence=_merge_evidence(existing.pain_evidence, new.pain_evidence),
        pain_confidence=max(existing.pain_confidence, new.pain_confidence),
        # Champion
        champion_identified=existing.champion_identified or new.champion_identified,
        champion_contact=_prefer_non_none(
            existing.champion_contact,
            new.champion_contact,
            existing.champion_confidence,
            new.champion_confidence,
        ),
        champion_evidence=_merge_evidence(
            existing.champion_evidence, new.champion_evidence
        ),
        champion_confidence=max(existing.champion_confidence, new.champion_confidence),
    )


# ── Combined Qualification Merge ─────────────────────────────────────────────


def merge_qualification_signals(
    existing: QualificationState, new: QualificationState
) -> QualificationState:
    """Merge two QualificationState objects preserving existing high-confidence data.

    - BANT and MEDDIC merged separately via their respective merge functions.
    - overall_confidence takes the max of both.
    - key_insights extended with unique new items.
    - recommended_next_questions replaced entirely (always fresh).
    - last_updated set to now.

    Args:
        existing: Current qualification state.
        new: Newly extracted qualification state.

    Returns:
        Merged QualificationState.
    """
    merged_bant = merge_bant_signals(existing.bant, new.bant)
    merged_meddic = merge_meddic_signals(existing.meddic, new.meddic)

    return QualificationState(
        bant=merged_bant,
        meddic=merged_meddic,
        overall_confidence=max(existing.overall_confidence, new.overall_confidence),
        key_insights=_merge_unique_list(existing.key_insights, new.key_insights),
        recommended_next_questions=new.recommended_next_questions
        if new.recommended_next_questions
        else existing.recommended_next_questions,
        last_updated=datetime.now(timezone.utc),
    )


# ── Qualification Extractor ──────────────────────────────────────────────────


class QualificationExtractor:
    """LLM-powered qualification signal extraction using instructor + LiteLLM.

    Extracts structured BANT + MEDDIC signals from conversation text in a
    single LLM call. Uses instructor for structured output validation against
    the QualificationState Pydantic model.

    If existing_state is provided, the new extraction is merged with it using
    merge_qualification_signals() to preserve existing high-confidence data.

    On LLM errors, returns existing_state unchanged (fail-open pattern,
    consistent with 02-03 fail-open for LLM failures).

    Args:
        llm_service: LLMService instance from Phase 1 (used for model config).
    """

    def __init__(self, llm_service: object) -> None:
        """Initialize with LLM service reference.

        Args:
            llm_service: LLMService instance (used to get model config).
                Typed as object to avoid import cycle; only needs .router attribute.
        """
        self._llm_service = llm_service

    async def extract_signals(
        self,
        conversation_text: str,
        existing_state: QualificationState | None = None,
    ) -> QualificationState:
        """Extract qualification signals from conversation text.

        Uses instructor with LiteLLM for structured extraction of BANT + MEDDIC
        signals in a single LLM call. Merges with existing_state if provided.

        Args:
            conversation_text: The conversation transcript to analyze.
            existing_state: Optional existing state to merge with.

        Returns:
            QualificationState with extracted (and optionally merged) signals.
        """
        import instructor
        import litellm

        from src.app.agents.sales.prompts import build_qualification_extraction_prompt

        try:
            # Build the extraction prompt
            existing_dict = (
                existing_state.model_dump(mode="json") if existing_state else None
            )
            messages = build_qualification_extraction_prompt(
                conversation_text=conversation_text,
                existing_state=existing_dict,
            )

            # Create instructor client with LiteLLM async completion
            client = instructor.from_litellm(litellm.acompletion)

            # Determine model to use -- prefer reasoning model from router config
            model = "anthropic/claude-sonnet-4-20250514"
            if hasattr(self._llm_service, "router") and self._llm_service.router:
                # Extract model from router's model list
                for m in self._llm_service.router.model_list:
                    if m.get("model_name") == "reasoning":
                        model = m["litellm_params"]["model"]
                        break

            # Single LLM call to extract ALL BANT + MEDDIC signals
            extracted = await client.chat.completions.create(
                model=model,
                response_model=QualificationState,
                messages=messages,
                max_tokens=4096,
                temperature=0.1,  # Low temp for consistent extraction
                max_retries=2,
            )

            logger.info(
                "qualification_signals_extracted",
                bant_completion=extracted.bant.completion_score,
                meddic_completion=extracted.meddic.completion_score,
                overall_confidence=extracted.overall_confidence,
            )

            # Merge with existing if provided
            if existing_state is not None:
                merged = merge_qualification_signals(existing_state, extracted)
                logger.info(
                    "qualification_signals_merged",
                    bant_completion=merged.bant.completion_score,
                    meddic_completion=merged.meddic.completion_score,
                    overall_confidence=merged.overall_confidence,
                )
                return merged

            # Set last_updated for fresh extraction
            extracted.last_updated = datetime.now(timezone.utc)
            return extracted

        except Exception as exc:
            # Fail-open: return existing state unchanged on any LLM error
            logger.warning(
                "qualification_extraction_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                has_existing_state=existing_state is not None,
            )
            if existing_state is not None:
                return existing_state
            # No existing state -- return empty default
            return QualificationState(last_updated=datetime.now(timezone.utc))


# ── Internal Helpers ─────────────────────────────────────────────────────────


def _pick_by_confidence(
    existing_value: str | None,
    existing_confidence: float,
    new_value: str | None,
    new_confidence: float,
    existing_identified: bool,
    new_identified: bool,
) -> str | None:
    """Pick the value with higher confidence, preferring identified over unidentified.

    Rules:
    1. If new is identified and existing is not -> use new value
    2. If both identified, use higher confidence -> existing wins on ties
    3. If neither identified, prefer non-None
    """
    if new_identified and not existing_identified:
        return new_value
    if existing_identified and not new_identified:
        return existing_value
    # Both identified or both not identified
    if new_confidence > existing_confidence:
        return new_value if new_value is not None else existing_value
    return existing_value if existing_value is not None else new_value


def _prefer_non_none(
    existing: str | None,
    new: str | None,
    existing_confidence: float,
    new_confidence: float,
) -> str | None:
    """Prefer non-None contact values, using confidence as tiebreaker."""
    if existing is not None and new is not None:
        return new if new_confidence > existing_confidence else existing
    return existing if existing is not None else new


def _merge_evidence(existing: str | None, new: str | None) -> str | None:
    """Append new evidence to existing, separated by ' | '.

    Never replaces existing evidence -- always accumulates.
    """
    if existing and new:
        # Avoid duplicating the same evidence
        if new in existing:
            return existing
        return f"{existing} | {new}"
    return existing or new


def _merge_unique_list(existing: list[str], new: list[str]) -> list[str]:
    """Extend existing list with unique new items, preserving order."""
    seen = set(existing)
    merged = list(existing)
    for item in new:
        if item not in seen:
            merged.append(item)
            seen.add(item)
    return merged
