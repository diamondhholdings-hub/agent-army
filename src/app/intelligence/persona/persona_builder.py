"""Guided persona creation with dimension options and preview generation.

PersonaBuilder provides a wizard-like interface for creating agent
personas. Sales reps select dimension values (formal/casual, concise/
detailed, technical/business, proactive/reactive) and optionally set
a geographic region and custom instructions. The builder then generates
a preview showing sample email and chat messages in that persona's style.

Preview generation uses LLM (via ``llm_service``) when available, with
a rule-based fallback for environments without LLM access.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from src.app.intelligence.persona.geographic import GeographicAdapter
from src.app.intelligence.persona.schemas import (
    PersonaConfig,
    PersonaDimension,
    PersonaPreview,
)

logger = structlog.get_logger(__name__)

# Dimension metadata for the guided builder UI.
_DIMENSION_OPTIONS: list[dict[str, Any]] = [
    {
        "dimension": PersonaDimension.formal_casual,
        "label": "Communication Formality",
        "low": "Casual and friendly",
        "high": "Formal and professional",
        "description": "How formal should communication be?",
        "default": 0.5,
    },
    {
        "dimension": PersonaDimension.concise_detailed,
        "label": "Response Detail",
        "low": "Concise and to the point",
        "high": "Comprehensive and detailed",
        "description": "How much detail should responses include?",
        "default": 0.5,
    },
    {
        "dimension": PersonaDimension.technical_business,
        "label": "Technical Depth",
        "low": "Business-level language",
        "high": "Deep technical detail",
        "description": "How technical should the language be?",
        "default": 0.5,
    },
    {
        "dimension": PersonaDimension.proactive_reactive,
        "label": "Initiative Level",
        "low": "Reactive (respond when asked)",
        "high": "Proactive (suggest next steps)",
        "description": "How proactive should the agent be?",
        "default": 0.5,
    },
]

# Region-specific formality defaults for persona creation.
_REGION_FORMALITY_DEFAULTS: dict[str, float] = {
    "apac": 0.7,
    "emea": 0.6,
    "americas": 0.4,
}


class PersonaBuilder:
    """Guided persona creation service with preview generation.

    Provides dimension metadata for UI rendering, persona construction
    from user inputs, validation, and preview generation to let sales
    reps evaluate a clone's communication style before activating.

    Usage::

        builder = PersonaBuilder(llm_service=llm)
        options = builder.get_dimension_options()
        persona = builder.build_persona(
            clone_name="Sarah's Agent",
            owner_id="user-42",
            dimensions={PersonaDimension.formal_casual: 0.8},
        )
        preview = await builder.generate_preview(persona)
    """

    def __init__(
        self,
        llm_service: Any | None = None,
        geographic_adapter: GeographicAdapter | None = None,
    ) -> None:
        self._llm = llm_service
        self._geo = geographic_adapter or GeographicAdapter()

    # ── Public API ────────────────────────────────────────────────────

    def get_dimension_options(self) -> list[dict[str, Any]]:
        """Return dimension metadata for the guided builder UI.

        Each item describes one persona dimension with labels, default
        value, and description suitable for rendering a slider or
        selection control.

        Returns:
            List of dimension metadata dictionaries.
        """
        return _DIMENSION_OPTIONS

    def build_persona(
        self,
        clone_name: str,
        owner_id: str,
        dimensions: dict[PersonaDimension, float] | None = None,
        region: str | None = None,
        custom_instructions: str | None = None,
    ) -> PersonaConfig:
        """Construct a PersonaConfig from guided builder inputs.

        Fills in default dimension values for any dimensions not
        provided. Applies region-specific formality defaults when
        a region is specified and no explicit formal_casual value
        is given.

        Args:
            clone_name: Display name for the persona.
            owner_id: Sales rep identifier.
            dimensions: Dimension values (0.0-1.0). Defaults filled for missing.
            region: Geographic region code (apac, emea, americas).
            custom_instructions: Free-form customization text.

        Returns:
            Validated PersonaConfig instance.
        """
        clone_id = str(uuid.uuid4())

        # Start with defaults for all 4 dimensions.
        final_dims: dict[PersonaDimension, float] = {
            PersonaDimension.formal_casual: 0.5,
            PersonaDimension.concise_detailed: 0.5,
            PersonaDimension.technical_business: 0.5,
            PersonaDimension.proactive_reactive: 0.5,
        }

        # Apply region-specific formality default if region provided
        # and no explicit formal_casual value given.
        if region and (dimensions is None or PersonaDimension.formal_casual not in dimensions):
            default_formality = _REGION_FORMALITY_DEFAULTS.get(region.lower(), 0.5)
            final_dims[PersonaDimension.formal_casual] = default_formality

        # Override with any user-provided dimensions.
        if dimensions:
            final_dims.update(dimensions)

        return PersonaConfig(
            clone_id=clone_id,
            tenant_id="",  # Filled by caller/clone manager
            owner_id=owner_id,
            dimensions=final_dims,
            region=region,
            custom_instructions=custom_instructions,
        )

    async def generate_preview(self, config: PersonaConfig) -> PersonaPreview:
        """Generate sample outputs demonstrating the persona's style.

        Uses LLM when available for realistic samples. Falls back to
        rule-based generation using dimension thresholds when LLM
        is not configured.

        Args:
            config: Persona configuration to preview.

        Returns:
            PersonaPreview with sample email, chat message, and summary.
        """
        if self._llm is not None:
            return await self._generate_preview_llm(config)
        return self._generate_preview_rules(config)

    def validate_persona(self, config: PersonaConfig) -> list[str]:
        """Validate a persona configuration and return warnings.

        Does NOT raise exceptions -- returns a list of warning strings
        suitable for UI display. An empty list means the config is valid.

        Args:
            config: Persona configuration to validate.

        Returns:
            List of warning/error strings (empty if valid).
        """
        warnings: list[str] = []

        # Check dimensions in range
        for dim, val in config.dimensions.items():
            if not isinstance(val, (int, float)):
                warnings.append(f"Dimension {dim.value} must be a number")
            elif val < 0.0 or val > 1.0:
                warnings.append(
                    f"Dimension {dim.value} must be between 0.0 and 1.0 (got {val})"
                )

        # Check region is valid if set
        if config.region:
            supported = self._geo.get_supported_regions()
            if config.region.lower() not in supported:
                warnings.append(
                    f"Unknown region '{config.region}'. Supported: {supported}"
                )

        # Check clone_id is non-empty
        if not config.clone_id:
            warnings.append("clone_id must not be empty")

        return warnings

    # ── Private Helpers ───────────────────────────────────────────────

    async def _generate_preview_llm(self, config: PersonaConfig) -> PersonaPreview:
        """Generate preview using LLM service."""
        from src.app.intelligence.persona.cloning import AgentCloneManager

        # Build dimension descriptions for the prompt
        manager = AgentCloneManager(repository=None)  # type: ignore[arg-type]
        dim_lines = []
        for dim, val in config.dimensions.items():
            text = manager._interpolate_dimension(dim, val)
            dim_lines.append(f"- {text}")

        geo_section = ""
        if config.region:
            geo_section = self._geo.build_geographic_prompt_section(config.region)

        prompt = (
            "You are previewing a sales agent persona with these characteristics:\n"
            + "\n".join(dim_lines)
            + "\n"
        )
        if geo_section:
            prompt += f"\n{geo_section}\n"
        prompt += (
            "\nGenerate:\n"
            "1. A sample email (3-4 sentences) responding to 'Tell me more about your product'\n"
            "2. A sample Slack message (1-2 sentences) following up after a demo\n"
            "3. A persona summary (2-3 sentences) describing this agent's communication style\n"
            "\nThe samples should demonstrate the persona's distinct style while following "
            "sales best practices."
        )

        try:
            result = await self._llm.completion(
                messages=[{"role": "user", "content": prompt}],
                model="fast",
                response_model=PersonaPreview,
            )
            # If the LLM returns a PersonaPreview-like dict, construct properly
            if isinstance(result, dict):
                return PersonaPreview(
                    persona=config,
                    sample_email=result.get("sample_email", ""),
                    sample_chat=result.get("sample_chat", ""),
                    persona_summary=result.get("persona_summary", ""),
                )
            if isinstance(result, PersonaPreview):
                return PersonaPreview(
                    persona=config,
                    sample_email=result.sample_email,
                    sample_chat=result.sample_chat,
                    persona_summary=result.persona_summary,
                )
            return result
        except Exception:
            logger.warning("persona_builder.llm_preview_failed", exc_info=True)
            return self._generate_preview_rules(config)

    def _generate_preview_rules(self, config: PersonaConfig) -> PersonaPreview:
        """Generate preview using rule-based dimension thresholds."""
        formality = config.dimensions.get(PersonaDimension.formal_casual, 0.5)
        detail = config.dimensions.get(PersonaDimension.concise_detailed, 0.5)
        technical = config.dimensions.get(PersonaDimension.technical_business, 0.5)
        proactive = config.dimensions.get(PersonaDimension.proactive_reactive, 0.5)

        # Email sample
        if formality > 0.7:
            greeting = "Dear Sir/Madam,"
            closing = "Kind regards,"
        elif formality < 0.3:
            greeting = "Hey there!"
            closing = "Cheers,"
        else:
            greeting = "Hi,"
            closing = "Best,"

        if detail > 0.7:
            body = (
                "Thank you for your interest. Our platform provides comprehensive "
                "sales automation including multi-channel outreach, deal pipeline "
                "management, and AI-powered conversation learning. I would be happy "
                "to schedule a detailed walkthrough covering all capabilities."
            )
        elif detail < 0.3:
            body = (
                "Happy to share more. Our platform automates sales outreach "
                "and deal management. Want to jump on a quick call?"
            )
        else:
            body = (
                "Thanks for reaching out. Our platform handles sales automation "
                "across email, chat, and meetings. I can walk you through the "
                "key features -- would a brief demo work?"
            )

        sample_email = f"{greeting}\n\n{body}\n\n{closing}"

        # Chat sample
        if formality > 0.7:
            chat = (
                "Thank you for attending the demonstration. I would like to "
                "schedule a follow-up to discuss next steps at your earliest convenience."
            )
        elif formality < 0.3:
            chat = "Great demo today! Want to chat about next steps?"
        else:
            chat = "Thanks for the demo today. Shall we set up a follow-up to discuss next steps?"

        if proactive > 0.7:
            chat += " I have a few suggestions for how we could proceed."

        # Summary
        style_parts = []
        if formality > 0.7:
            style_parts.append("formal and professional")
        elif formality < 0.3:
            style_parts.append("casual and approachable")
        else:
            style_parts.append("balanced in tone")

        if technical > 0.7:
            style_parts.append("technically detailed")
        elif technical < 0.3:
            style_parts.append("business-focused")

        if proactive > 0.7:
            style_parts.append("highly proactive")
        elif proactive < 0.3:
            style_parts.append("responsive to prospect direction")

        summary = (
            f"This agent communicates in a {', '.join(style_parts)} manner. "
            f"Responses are {'comprehensive and thorough' if detail > 0.7 else 'concise and efficient' if detail < 0.3 else 'moderately detailed'}."
        )

        return PersonaPreview(
            persona=config,
            sample_email=sample_email,
            sample_chat=chat,
            persona_summary=summary,
        )
