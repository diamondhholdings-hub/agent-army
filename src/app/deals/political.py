"""Political mapping with hybrid title heuristics + LLM refinement + human overrides.

Provides quantitative stakeholder scoring across three dimensions (decision_power,
influence_level, relationship_strength) on a 0-10 scale. Scoring follows a
three-layer approach per CONTEXT.md:

1. Title heuristics: Baseline scores from job title keywords (CEO=high, IC=low)
2. Conversation signals: LLM-refined scores that can only INCREASE (never decrease)
   from conversation evidence (Pitfall 5)
3. Human overrides: Always win, clamped to 0-10 range (Pitfall 5)

Each score tracks its source via ScoreSource enum for audit transparency.

Exports:
    PoliticalMapper: Hybrid title+LLM+override scoring for stakeholders.
"""

from __future__ import annotations

import re

import structlog
from pydantic import BaseModel, Field

from src.app.deals.schemas import (
    ScoreSource,
    StakeholderRead,
    StakeholderRole,
    StakeholderScores,
)

logger = structlog.get_logger(__name__)


# ── LLM Response Models ──────────────────────────────────────────────────────


class ConversationScoreRefinement(BaseModel):
    """LLM response model for refining stakeholder scores from conversation."""

    decision_power: int = Field(ge=0, le=10, description="Decision-making authority 0-10")
    influence_level: int = Field(ge=0, le=10, description="Organizational influence 0-10")
    relationship_strength: int = Field(ge=0, le=10, description="Relationship warmth with us 0-10")
    decision_power_evidence: str = Field(default="", description="Evidence for decision power score")
    influence_level_evidence: str = Field(default="", description="Evidence for influence level score")
    relationship_strength_evidence: str = Field(default="", description="Evidence for relationship strength score")


class RoleDetection(BaseModel):
    """LLM response model for detecting stakeholder roles from conversation."""

    detected_roles: list[str] = Field(
        default_factory=list,
        description="Roles detected: decision_maker, influencer, champion, blocker, user, gatekeeper",
    )
    reasoning: str = Field(default="", description="Brief reasoning for each role detected")


# ── Political Mapper ──────────────────────────────────────────────────────────


class PoliticalMapper:
    """Hybrid title + LLM + human override scoring for stakeholder political mapping.

    Scoring layers (each can only increase or maintain scores):
    1. Title heuristics: Baseline from job title keywords
    2. Conversation signals: LLM-refined from conversation evidence (only increases)
    3. Human overrides: Always win, clamped to 0-10

    Title heuristic tiers:
    - c-suite: CEO, CTO, CFO, COO, CIO, CISO, CRO, CMO, CPO
    - vp: VP, Vice President, SVP, EVP
    - director: Director
    - manager: Manager
    - ic: Individual contributor (default for unknown titles)

    Args:
        model: LiteLLM model name to use (default: "fast" for speed).
    """

    TITLE_HEURISTICS: dict[str, dict[str, int]] = {
        "c-suite": {"decision_power": 9, "influence_level": 8, "relationship_strength": 3},
        "vp": {"decision_power": 8, "influence_level": 7, "relationship_strength": 3},
        "director": {"decision_power": 6, "influence_level": 6, "relationship_strength": 3},
        "manager": {"decision_power": 4, "influence_level": 5, "relationship_strength": 3},
        "ic": {"decision_power": 2, "influence_level": 3, "relationship_strength": 3},
    }

    # Title keyword patterns mapped to tiers
    _TITLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\b(?:CEO|CTO|CFO|COO|CIO|CISO|CRO|CMO|CPO|Chief)\b", re.IGNORECASE), "c-suite"),
        (re.compile(r"\b(?:VP|Vice\s+President|SVP|EVP)\b", re.IGNORECASE), "vp"),
        (re.compile(r"\bDirector\b", re.IGNORECASE), "director"),
        (re.compile(r"\bManager\b", re.IGNORECASE), "manager"),
    ]

    def __init__(self, model: str = "fast") -> None:
        self._model = model

    def score_from_title(self, title: str | None) -> StakeholderScores:
        """Generate baseline political scores from a stakeholder's job title.

        Maps title keywords (CEO, CTO, VP, Director, Manager, etc.) to
        heuristic baselines. Unknown or None titles default to IC tier.

        Args:
            title: Job title string, or None for unknown.

        Returns:
            StakeholderScores with heuristic baseline values.
        """
        tier = self._classify_title(title)
        heuristic = self.TITLE_HEURISTICS[tier]
        return StakeholderScores(
            decision_power=heuristic["decision_power"],
            influence_level=heuristic["influence_level"],
            relationship_strength=heuristic["relationship_strength"],
        )

    async def refine_from_conversation(
        self,
        stakeholder: StakeholderRead,
        conversation_text: str,
    ) -> tuple[StakeholderScores, dict[str, str]]:
        """Refine stakeholder scores using conversation signals via LLM.

        Uses instructor + LiteLLM to extract relationship signals from
        conversation text. Conversation signals can ONLY increase scores,
        never decrease them (per Pitfall 5).

        On LLM failure, returns existing scores unchanged (fail-open pattern
        from 02-03).

        Args:
            stakeholder: Current stakeholder data with existing scores.
            conversation_text: Conversation transcript to analyze.

        Returns:
            Tuple of (updated StakeholderScores, evidence dict).
            Evidence maps score field names to evidence strings.
        """
        import instructor
        import litellm

        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are analyzing a sales conversation to assess a stakeholder's "
                        "political influence. Score the following dimensions on a 0-10 scale:\n"
                        "- decision_power: How much authority they have to approve/reject deals\n"
                        "- influence_level: How much they can sway others' opinions\n"
                        "- relationship_strength: How warm/positive our relationship with them is\n\n"
                        "Provide specific evidence from the conversation for each score."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Stakeholder: {stakeholder.contact_name}\n"
                        f"Title: {stakeholder.title or 'Unknown'}\n"
                        f"Current Scores: decision_power={stakeholder.scores.decision_power}, "
                        f"influence_level={stakeholder.scores.influence_level}, "
                        f"relationship_strength={stakeholder.scores.relationship_strength}\n\n"
                        f"CONVERSATION:\n{conversation_text}"
                    ),
                },
            ]

            client = instructor.from_litellm(litellm.acompletion)
            refinement = await client.chat.completions.create(
                model=self._model,
                response_model=ConversationScoreRefinement,
                messages=messages,
                max_tokens=1024,
                temperature=0.1,
                max_retries=2,
            )

            # Conversation signals can ONLY increase scores (Pitfall 5)
            updated_scores = StakeholderScores(
                decision_power=max(stakeholder.scores.decision_power, refinement.decision_power),
                influence_level=max(stakeholder.scores.influence_level, refinement.influence_level),
                relationship_strength=max(
                    stakeholder.scores.relationship_strength, refinement.relationship_strength
                ),
            )

            # Collect evidence for fields that changed
            evidence: dict[str, str] = {}
            if refinement.decision_power_evidence:
                evidence["decision_power"] = refinement.decision_power_evidence
            if refinement.influence_level_evidence:
                evidence["influence_level"] = refinement.influence_level_evidence
            if refinement.relationship_strength_evidence:
                evidence["relationship_strength"] = refinement.relationship_strength_evidence

            logger.info(
                "stakeholder_scores_refined",
                stakeholder=stakeholder.contact_name,
                original_dp=stakeholder.scores.decision_power,
                refined_dp=updated_scores.decision_power,
                original_il=stakeholder.scores.influence_level,
                refined_il=updated_scores.influence_level,
                original_rs=stakeholder.scores.relationship_strength,
                refined_rs=updated_scores.relationship_strength,
            )

            return updated_scores, evidence

        except Exception as exc:
            # Fail-open: return existing scores unchanged
            logger.warning(
                "stakeholder_refinement_failed",
                stakeholder=stakeholder.contact_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return stakeholder.scores, {}

    def apply_override(
        self,
        current_scores: StakeholderScores,
        overrides: dict[str, int],
    ) -> StakeholderScores:
        """Apply human overrides to stakeholder scores.

        Human overrides always win (per Pitfall 5). Values are clamped
        to the 0-10 range.

        Args:
            current_scores: Current StakeholderScores.
            overrides: Dict mapping score field names to override values.
                Valid keys: "decision_power", "influence_level", "relationship_strength".

        Returns:
            Updated StakeholderScores with overrides applied.
        """
        scores_dict = current_scores.model_dump()

        for field, value in overrides.items():
            if field in scores_dict:
                # Clamp to 0-10 range
                scores_dict[field] = max(0, min(10, value))

        return StakeholderScores(**scores_dict)

    async def detect_roles_from_conversation(
        self,
        conversation_text: str,
        stakeholder_name: str,
    ) -> list[StakeholderRole]:
        """Detect stakeholder roles from conversation context using LLM.

        Looks for signals indicating roles:
        - decision_maker: "I make the final call", "I'll approve this"
        - champion: "I'll champion this internally", "Let me push for this"
        - blocker: "I have concerns about...", "I don't think we should..."
        - influencer: "I'll recommend to...", "My team relies on..."
        - user: "We use this daily", "My team would benefit from..."
        - gatekeeper: "You'll need to go through me", "I handle vendor selection"

        Multiple roles are allowed per person (CONTEXT.md decision).

        Args:
            conversation_text: Conversation transcript to analyze.
            stakeholder_name: Name of the stakeholder to detect roles for.

        Returns:
            List of StakeholderRole enums detected from conversation.
            Empty list on LLM failure (fail-open).
        """
        import instructor
        import litellm

        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are analyzing a sales conversation to determine what roles "
                        "a specific person plays in the buying process.\n\n"
                        "Possible roles (a person can have MULTIPLE roles):\n"
                        "- decision_maker: Has authority to approve or reject the purchase\n"
                        "- influencer: Can sway the decision through recommendations\n"
                        "- champion: Actively advocates for our solution internally\n"
                        "- blocker: Has concerns or opposition to the purchase\n"
                        "- user: Will be an end user of the product/service\n"
                        "- gatekeeper: Controls access to decision makers or information\n\n"
                        "Only assign roles with clear evidence from the conversation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Stakeholder: {stakeholder_name}\n\n"
                        f"CONVERSATION:\n{conversation_text}"
                    ),
                },
            ]

            client = instructor.from_litellm(litellm.acompletion)
            detection = await client.chat.completions.create(
                model=self._model,
                response_model=RoleDetection,
                messages=messages,
                max_tokens=512,
                temperature=0.1,
                max_retries=2,
            )

            # Convert string roles to StakeholderRole enums, skip invalid
            roles: list[StakeholderRole] = []
            for role_str in detection.detected_roles:
                try:
                    roles.append(StakeholderRole(role_str))
                except ValueError:
                    logger.debug(
                        "unknown_role_detected",
                        role=role_str,
                        stakeholder=stakeholder_name,
                    )

            logger.info(
                "stakeholder_roles_detected",
                stakeholder=stakeholder_name,
                roles=[r.value for r in roles],
            )

            return roles

        except Exception as exc:
            # Fail-open: return empty list
            logger.warning(
                "role_detection_failed",
                stakeholder=stakeholder_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []

    def _classify_title(self, title: str | None) -> str:
        """Classify a job title into a heuristic tier.

        Args:
            title: Job title string, or None.

        Returns:
            Tier key: "c-suite", "vp", "director", "manager", or "ic".
        """
        if title is None:
            return "ic"

        for pattern, tier in self._TITLE_PATTERNS:
            if pattern.search(title):
                return tier

        return "ic"
