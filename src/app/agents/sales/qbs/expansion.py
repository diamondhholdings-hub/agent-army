"""Account Expansion Detector for multi-threading opportunity identification.

Scans conversation text for natural mentions of other people, teams, or roles
and produces expansion recommendations with QBS/Voss approaches. Uses the
'fast' LLM model for low-latency extraction.

Falls back gracefully on LLM failure (returns empty list -- fail-open).

Exports:
    AccountExpansionDetector: Detects expansion triggers from conversation text.
"""

from __future__ import annotations

import structlog

from src.app.agents.sales.qbs.schemas import (
    ExpansionRecommendation,
    ExpansionTrigger,
)
from src.app.agents.sales.schemas import ConversationState

logger = structlog.get_logger(__name__)

# Maximum number of expansion entries to keep in state
_MAX_EXPANSION_ENTRIES: int = 20


class AccountExpansionDetector:
    """Detects account expansion opportunities from conversation text.

    Scans for natural mentions of other people, teams, or roles.
    Produces expansion recommendations with QBS/Voss approaches.
    Uses 'fast' model for low-latency extraction.

    Args:
        llm_service: LLMService instance (typed as object to avoid import
            cycle; only needs .router attribute for model config).
    """

    def __init__(self, llm_service: object) -> None:
        """Initialize with LLM service reference.

        Args:
            llm_service: LLMService instance (used to get model config).
        """
        self._llm_service = llm_service

    async def detect_expansion_triggers(
        self,
        conversation_text: str,
        existing_contacts: list[str],
        interaction_count: int = 0,
    ) -> list[ExpansionTrigger]:
        """Detect expansion triggers from conversation text.

        Scans conversation for mentions of new contacts not in the
        existing contacts list. Returns structured expansion triggers
        with recommended QBS approach and urgency assessment.

        Urgency adjustment: if ``interaction_count < 3``, any "immediate"
        urgency is overridden to "next_conversation" to prevent premature
        expansion (RESEARCH.md Pitfall 4).

        Args:
            conversation_text: Full conversation text to scan.
            existing_contacts: List of known contact names/roles to exclude.
            interaction_count: Current interaction number (for urgency
                adjustment).

        Returns:
            List of ExpansionTrigger objects. Empty list on LLM failure.
        """
        import instructor
        import litellm

        from src.app.agents.sales.qbs.prompts import (
            build_expansion_detection_prompt,
        )

        try:
            # Build prompt messages
            messages = build_expansion_detection_prompt(
                conversation_text=conversation_text,
                existing_contacts=existing_contacts,
            )

            # Create instructor client with LiteLLM async completion
            client = instructor.from_litellm(litellm.acompletion)

            # Resolve fast model for low-latency extraction
            model = self._resolve_model("fast")

            # Single LLM call for expansion trigger detection
            result = await client.chat.completions.create(
                model=model,
                response_model=ExpansionRecommendation,
                messages=messages,
                max_tokens=512,
                temperature=0.2,
                max_retries=1,
            )

            triggers = result.triggers

            # Urgency adjustment for early interactions
            if interaction_count < 3:
                for trigger in triggers:
                    if trigger.urgency == "immediate":
                        trigger.urgency = "next_conversation"

            logger.info(
                "expansion_triggers_detected",
                trigger_count=len(triggers),
                interaction_count=interaction_count,
            )

            return triggers

        except Exception as exc:
            # Fail-open: return empty list on any LLM error
            logger.warning(
                "expansion_detection_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []

    def _resolve_model(self, model_name: str) -> str:
        """Resolve model name to LiteLLM model identifier.

        Looks up the model name in the LLM service router config.
        Defaults to claude-sonnet-4-20250514 if not found.

        Args:
            model_name: Logical model name (e.g. "fast", "reasoning").

        Returns:
            LiteLLM model identifier string.
        """
        default = "anthropic/claude-sonnet-4-20250514"
        if hasattr(self._llm_service, "router") and self._llm_service.router:
            for m in self._llm_service.router.model_list:
                if m.get("model_name") == model_name:
                    return m["litellm_params"]["model"]
        return default

    @staticmethod
    def save_expansion_state(
        state: ConversationState,
        triggers: list[ExpansionTrigger],
    ) -> None:
        """Save expansion triggers to conversation metadata.

        Merges new triggers with existing ones, deduplicating by
        ``mentioned_name_or_role``. Caps total entries at 20.
        Does NOT call state_repository.save_state -- caller handles
        persistence.

        Args:
            state: Conversation state to update.
            triggers: New expansion triggers to merge.
        """
        state.metadata.setdefault("qbs", {})
        expansion = state.metadata["qbs"].setdefault(
            "expansion", {"detected_contacts": []}
        )

        existing_contacts = expansion.get("detected_contacts", [])

        # Build set of existing contact names for dedup
        existing_names = {
            c.get("mentioned_name_or_role", "")
            for c in existing_contacts
        }

        # Append new triggers that are not duplicates
        for trigger in triggers:
            if trigger.mentioned_name_or_role not in existing_names:
                existing_contacts.append(trigger.model_dump(mode="json"))
                existing_names.add(trigger.mentioned_name_or_role)

        # Cap at max entries
        if len(existing_contacts) > _MAX_EXPANSION_ENTRIES:
            existing_contacts = existing_contacts[-_MAX_EXPANSION_ENTRIES:]

        expansion["detected_contacts"] = existing_contacts
