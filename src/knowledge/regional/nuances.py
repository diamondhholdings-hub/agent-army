"""Region-specific content and customization rules for sales operations.

Provides structured access to regional nuance data including cultural
considerations, pricing modifiers, compliance requirements, and
communication guidance. Regional data is loaded from markdown files in
data/regional/ and also provides programmatic access for agent queries
like "What pricing discount applies in APAC?"

The RegionalNuances class is the single source of truth for region-specific
configuration. It works independently of Qdrant -- agents can query it
directly for structured data, while the MethodologyLoader handles
ingesting the markdown content into Qdrant for semantic search.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Base path for regional data files
_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "regional"


class RegionConfig(BaseModel):
    """Configuration and metadata for a single sales region.

    Attributes:
        code: Short region code (e.g., "apac", "emea", "americas").
        name: Human-readable region name.
        description: Brief overview of the region's sales characteristics.
        pricing_modifier: Multiplier applied to base pricing (e.g., 0.9 for 10% discount).
        default_currency: Primary currency for the region.
        payment_terms: Standard payment terms (e.g., "net-30").
        contract_preference: Preferred contract structure.
        avg_sales_cycle_months: Typical enterprise sales cycle length.
        compliance_frameworks: Relevant regulatory frameworks.
        cultural_notes: Key cultural considerations for sales engagement.
        communication_style: Summary of preferred communication approach.
        key_markets: Major markets within the region with brief notes.
        common_objections: Typical objections and suggested responses.
        data_file: Path to the detailed markdown file for this region.
    """

    code: str
    name: str
    description: str
    pricing_modifier: float = 1.0
    default_currency: str = "USD"
    payment_terms: str = "net-30"
    contract_preference: str = "annual"
    avg_sales_cycle_months: tuple[int, int] = (3, 6)
    compliance_frameworks: list[str] = Field(default_factory=list)
    cultural_notes: list[str] = Field(default_factory=list)
    communication_style: str = ""
    key_markets: dict[str, str] = Field(default_factory=dict)
    common_objections: list[str] = Field(default_factory=list)
    data_file: str = ""


class RegionalNuances:
    """Central access point for region-specific sales nuance data.

    Pre-populated with APAC, EMEA, and Americas configurations on
    instantiation. Provides structured lookup by region code for pricing,
    compliance, cultural context, and more.

    Usage::

        nuances = RegionalNuances()
        context = nuances.get_regional_context("apac")
        modifier = nuances.get_pricing_modifier("apac")  # 0.9
        compliance = nuances.get_compliance_requirements("emea")
    """

    def __init__(self) -> None:
        self.regions: dict[str, RegionConfig] = {}
        self._populate_apac()
        self._populate_emea()
        self._populate_americas()

    def get_regional_context(self, region: str) -> dict[str, Any]:
        """Return the full regional context for a given region code.

        Args:
            region: Region code (e.g., "apac", "emea", "americas").

        Returns:
            Dictionary with cultural, pricing, compliance, and communication
            context for the region.

        Raises:
            KeyError: If the region code is not found.
        """
        key = region.lower()
        if key not in self.regions:
            raise KeyError(
                f"Unknown region: {region}. Available: {list(self.regions.keys())}"
            )
        config = self.regions[key]
        return {
            "code": config.code,
            "name": config.name,
            "description": config.description,
            "pricing": {
                "modifier": config.pricing_modifier,
                "currency": config.default_currency,
                "payment_terms": config.payment_terms,
                "contract_preference": config.contract_preference,
            },
            "compliance": config.compliance_frameworks,
            "cultural_notes": config.cultural_notes,
            "communication_style": config.communication_style,
            "key_markets": config.key_markets,
            "avg_sales_cycle_months": config.avg_sales_cycle_months,
            "common_objections": config.common_objections,
        }

    def get_pricing_modifier(self, region: str) -> float:
        """Return the pricing multiplier for a region.

        Args:
            region: Region code (e.g., "apac").

        Returns:
            Float multiplier (e.g., 0.9 for APAC 10% discount, 1.0 for
            no discount).

        Raises:
            KeyError: If the region code is not found.
        """
        key = region.lower()
        if key not in self.regions:
            raise KeyError(
                f"Unknown region: {region}. Available: {list(self.regions.keys())}"
            )
        return self.regions[key].pricing_modifier

    def get_compliance_requirements(self, region: str) -> list[str]:
        """Return the list of compliance frameworks for a region.

        Args:
            region: Region code (e.g., "emea").

        Returns:
            List of compliance framework names (e.g., ["GDPR", "NIS2"]).

        Raises:
            KeyError: If the region code is not found.
        """
        key = region.lower()
        if key not in self.regions:
            raise KeyError(
                f"Unknown region: {region}. Available: {list(self.regions.keys())}"
            )
        return self.regions[key].compliance_frameworks

    def get_data_file_path(self, region: str) -> Path:
        """Return the absolute path to a region's markdown data file.

        Args:
            region: Region code.

        Returns:
            Path to the markdown file.

        Raises:
            KeyError: If the region code is not found.
        """
        key = region.lower()
        if key not in self.regions:
            raise KeyError(
                f"Unknown region: {region}. Available: {list(self.regions.keys())}"
            )
        return _DATA_DIR / self.regions[key].data_file

    def list_regions(self) -> list[str]:
        """Return all available region codes.

        Returns:
            List of region codes sorted alphabetically.
        """
        return sorted(self.regions.keys())

    # ── Region Definitions ─────────────────────────────────────────────────

    def _populate_apac(self) -> None:
        """Populate APAC regional configuration."""
        self.regions["apac"] = RegionConfig(
            code="apac",
            name="Asia-Pacific",
            description=(
                "Relationship-first selling region with diverse sub-markets. "
                "Consensus decision-making, respect for hierarchy, and patience "
                "are critical success factors. Longer sales cycles but strong "
                "loyalty once trust is established."
            ),
            pricing_modifier=0.9,
            default_currency="USD",
            payment_terms="net-60",
            contract_preference="annual",
            avg_sales_cycle_months=(4, 12),
            compliance_frameworks=[
                "PDPA (Singapore)",
                "APPI (Japan)",
                "Privacy Act 1988 (Australia)",
                "PIPL (China)",
                "PDPA (Thailand)",
            ],
            cultural_notes=[
                "Relationship-first: invest in personal rapport before pushing for close",
                "Consensus decision-making: expect multiple stakeholders and offline alignment",
                "Face and harmony: avoid public confrontation or forcing direct 'no' answers",
                "Hierarchy matters: address senior people first, respect chain of command",
                "In-person meetings preferred for deal closing and initial engagement",
            ],
            communication_style=(
                "Indirect communication is the norm, especially in Northeast Asia. "
                "'We will consider it' often means no. Read between the lines. "
                "Written follow-ups help clarify commitments without confrontation. "
                "Patience in negotiations is essential -- rushing creates suspicion."
            ),
            key_markets={
                "Japan": "Formal, process-heavy, 6-12+ month cycles, local language mandatory",
                "Singapore": "Direct, English-fluent, fast decisions, government segment strong",
                "Australia": "Casual, outcome-focused, SaaS-preferred, 3-6 month cycles",
                "India": "High volume, lower ACV, usage-based pricing resonates, aggressive negotiation",
                "South Korea": "Formal procurement, chaebol centralized purchasing, large enterprise budgets",
            },
            common_objections=[
                "We prefer a local vendor",
                "The pricing is too high for our market",
                "We need to involve more stakeholders before deciding",
                "Data must stay in our country",
            ],
            data_file="apac.md",
        )

    def _populate_emea(self) -> None:
        """Populate EMEA regional configuration."""
        self.regions["emea"] = RegionConfig(
            code="emea",
            name="Europe, Middle East, and Africa",
            description=(
                "Most culturally diverse sales region requiring sub-regional "
                "adaptation. GDPR compliance is table stakes. Decision cycles "
                "are longer with more stakeholders. Quality and thoroughness "
                "are valued over speed."
            ),
            pricing_modifier=1.0,
            default_currency="EUR",
            payment_terms="net-30",
            contract_preference="annual",
            avg_sales_cycle_months=(4, 9),
            compliance_frameworks=[
                "GDPR (EU-wide)",
                "NIS2 Directive (EU-wide)",
                "UK Data Protection Act 2018",
                "DORA (EU financial sector)",
                "BDSG (Germany)",
            ],
            cultural_notes=[
                "DACH: Process-oriented, thorough, expects detailed documentation",
                "UK: Pragmatic, ROI-focused, moderate decision cycles",
                "France: Relationship-heavy, intellectual engagement, centralized authority",
                "Nordics: Egalitarian, consensus-driven, value transparency and honesty",
                "Southern Europe: Relationship-first, flexible on time, personal connections important",
                "Middle East (Gulf): High relationship emphasis, formal, use titles",
            ],
            communication_style=(
                "Varies widely by sub-region. DACH is formal and data-driven. "
                "UK is pragmatic and direct. France values intellectual engagement. "
                "Nordics prefer informal, jargon-free communication. "
                "Address people by appropriate titles in DACH and formal markets."
            ),
            key_markets={
                "Germany": "Process-heavy, detailed technical evaluations, premium pricing accepted",
                "UK": "Pragmatic, CIO/CTO-driven, pilot-to-production path popular",
                "France": "C-level decisions, relationship building critical, French language appreciated",
                "Nordics": "Flat organizations, consensus required, transparent pricing expected",
                "Middle East": "Relationship-driven, large government budgets, premium acceptable",
            },
            common_objections=[
                "We need EU data residency",
                "Your solution is not GDPR-compliant",
                "We need the contract in our local language",
                "Decision-making will take longer than you expect",
                "We are already working with a local/European vendor",
            ],
            data_file="emea.md",
        )

    def _populate_americas(self) -> None:
        """Populate Americas regional configuration."""
        self.regions["americas"] = RegionConfig(
            code="americas",
            name="Americas",
            description=(
                "US-anchored region with direct, ROI-focused selling. Fastest "
                "decision cycles globally for mid-market. Canada is more conservative. "
                "LATAM is relationship-driven with longer payment terms and "
                "language requirements."
            ),
            pricing_modifier=1.0,
            default_currency="USD",
            payment_terms="net-30",
            contract_preference="annual",
            avg_sales_cycle_months=(2, 8),
            compliance_frameworks=[
                "SOC 2 Type II",
                "FedRAMP",
                "CCPA/CPRA (California)",
                "HIPAA",
                "PCI DSS",
                "PIPEDA (Canada)",
                "LGPD (Brazil)",
            ],
            cultural_notes=[
                "US: Direct, ROI-focused, pilot-first approach, fast decision cycles",
                "Canada: Similar to US but more conservative, consensus-oriented",
                "Quebec: French language legally mandated for business (Bill 96)",
                "LATAM: Relationship-first, personal connections central, patience essential",
                "Brazil: Warm culture, Portuguese required, complex tax system",
                "Mexico: Growing tech sector, Spanish essential, USMCA ties to US practices",
            ],
            communication_style=(
                "US is direct and efficiency-oriented. Get to the point quickly. "
                "Email and LinkedIn for outreach. Meetings should be time-boxed. "
                "LATAM is warm and personal -- cold, transactional approaches fail. "
                "WhatsApp is a primary business channel in many LATAM markets."
            ),
            key_markets={
                "United States": "Direct, ROI-focused, 2-4 month mid-market cycles, SOC 2 required",
                "Canada": "Conservative, consensus-oriented, bilingual (Quebec), formal government RFPs",
                "Brazil": "Largest LATAM market, Portuguese required, complex tax, relationship-driven",
                "Mexico": "Growing tech sector, Spanish required, nearshoring trend, 3-6 month cycles",
            },
            common_objections=[
                "We need SOC 2 / FedRAMP before we can proceed",
                "We need to run this through our security team",
                "Can we start with a pilot?",
                "The pricing does not work for our market (LATAM)",
                "We need local language support",
            ],
            data_file="americas.md",
        )


def get_regional_context(region: str) -> dict[str, Any]:
    """Module-level convenience function for getting regional context.

    Creates a RegionalNuances instance and returns context for the
    specified region. For repeated access, instantiate RegionalNuances
    directly to avoid re-creating the data each time.

    Args:
        region: Region code (e.g., "apac", "emea", "americas").

    Returns:
        Dictionary with full regional context.
    """
    return RegionalNuances().get_regional_context(region)
