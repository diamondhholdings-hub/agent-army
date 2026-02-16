"""Geographic communication adaptation for sales agents.

Extends the existing RegionalNuances knowledge base into LLM-ready
prompt sections that guide an agent's communication style for specific
geographic regions. The core sales methodology (BANT/MEDDIC/QBS) is
NEVER overridden by geographic adaptation -- only tone and style change.
"""

from __future__ import annotations

import structlog

from src.app.intelligence.persona.schemas import GeographicProfile
from src.knowledge.regional.nuances import RegionalNuances

logger = structlog.get_logger(__name__)

# Methodology disclaimer appended to every geographic prompt section.
# Per CONTEXT.md Pitfall 5: persona/geographic settings must not override
# the sales methodology, qualification process, or deal progression approach.
_METHODOLOGY_DISCLAIMER = (
    "IMPORTANT: Adapt your TONE and COMMUNICATION STYLE per the above guidance.\n"
    "Do NOT change the sales methodology, qualification process, or deal progression approach.\n"
    "The core methodology is consistent across all regions."
)

# Default formality levels by region (APAC more formal, Americas more casual)
_REGION_FORMALITY_DEFAULTS: dict[str, float] = {
    "apac": 0.7,
    "emea": 0.6,
    "americas": 0.4,
}


class GeographicAdapter:
    """Converts regional nuance data into prompt-ready communication guidance.

    Composes the existing ``RegionalNuances`` knowledge source and
    transforms its structured data into system prompt sections suitable
    for LLM injection. Each section provides communication style guidance
    for a specific region while preserving methodology integrity.

    Usage::

        adapter = GeographicAdapter()
        section = adapter.build_geographic_prompt_section("apac")
        # Inject *section* into the agent's system prompt
    """

    def __init__(self) -> None:
        self._nuances = RegionalNuances()

    # ── Public API ────────────────────────────────────────────────────

    def build_geographic_prompt_section(self, region: str) -> str:
        """Generate a prompt section for geographic communication adaptation.

        Args:
            region: Region code (e.g. ``"apac"``, ``"emea"``, ``"americas"``).

        Returns:
            A formatted prompt section string. Returns an empty string for
            unknown regions (graceful fallback, not an error).
        """
        try:
            context = self._nuances.get_regional_context(region.lower())
        except KeyError:
            logger.warning(
                "geographic.unknown_region",
                region=region,
                available=self._nuances.list_regions(),
            )
            return ""

        cultural_lines = "\n".join(
            f"- {note}" for note in context["cultural_notes"]
        )

        return (
            f"## Geographic Communication Adaptation ({context['name']})\n"
            f"\n"
            f"Communication style: {context['communication_style']}\n"
            f"\n"
            f"Cultural awareness:\n"
            f"{cultural_lines}\n"
            f"\n"
            f"{_METHODOLOGY_DISCLAIMER}\n"
        )

    def get_supported_regions(self) -> list[str]:
        """Return the list of supported region codes.

        Returns:
            Sorted list of region code strings (e.g. ``["americas", "apac", "emea"]``).
        """
        return self._nuances.list_regions()

    def get_geographic_profile(self, region: str) -> GeographicProfile:
        """Return a structured geographic profile for a region.

        Builds a ``GeographicProfile`` from RegionalNuances data with
        region-appropriate formality defaults.

        Args:
            region: Region code.

        Returns:
            GeographicProfile with communication metadata and defaults.

        Raises:
            KeyError: If the region is not found.
        """
        context = self._nuances.get_regional_context(region.lower())
        formality = _REGION_FORMALITY_DEFAULTS.get(region.lower(), 0.5)
        return GeographicProfile(
            code=context["code"],
            name=context["name"],
            communication_style=context["communication_style"],
            cultural_notes=context["cultural_notes"],
            formality_default=formality,
        )
