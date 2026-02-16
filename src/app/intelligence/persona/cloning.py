"""Agent clone management with persona-based differentiation.

Handles CRUD operations for persona-differentiated agent clones and
generates system prompt sections from persona configuration. Each clone
has a unique communication style while sharing product knowledge,
sales methodologies, and pattern insights across the tenant.

Architecture note: Clone personas affect communication STYLE only.
Core sales methodology (BANT/MEDDIC/QBS) is never overridden by
persona settings. This is enforced by the methodology disclaimer
included in every generated prompt section.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

import structlog

from src.app.intelligence.persona.geographic import GeographicAdapter
from src.app.intelligence.persona.schemas import (
    Clone,
    PersonaConfig,
    PersonaDimension,
)

logger = structlog.get_logger(__name__)

# Disclaimer that must appear in every clone prompt section.
_METHODOLOGY_DISCLAIMER = (
    "These style preferences do NOT override the core sales methodology "
    "(BANT, MEDDIC, QBS). Apply them to HOW you communicate, not WHAT you do."
)

# Human-readable text for each dimension at low (0.0) and high (1.0) extremes.
_DIMENSION_LABELS: dict[PersonaDimension, dict[str, str]] = {
    PersonaDimension.formal_casual: {
        "low": "Use a casual, friendly, and approachable tone",
        "mid": "Use a balanced professional tone",
        "high": "Maintain high formality and professional decorum at all times",
    },
    PersonaDimension.concise_detailed: {
        "low": "Keep responses brief and to the point",
        "mid": "Provide moderate detail as appropriate",
        "high": "Provide comprehensive, detailed explanations",
    },
    PersonaDimension.technical_business: {
        "low": "Use business-level language accessible to non-technical stakeholders",
        "mid": "Use moderate technical detail, adapting to the audience",
        "high": "Use deep technical jargon and detailed technical references",
    },
    PersonaDimension.proactive_reactive: {
        "low": "Wait for the prospect to ask questions before offering suggestions",
        "mid": "Balance between reactive responses and proactive suggestions",
        "high": "Proactively suggest next steps, opportunities, and follow-ups",
    },
}


class CloneRepository(Protocol):
    """Protocol for clone persistence operations.

    Matches the IntelligenceRepository interface for clone-related
    methods. Allows in-memory test doubles.
    """

    async def create_clone(self, tenant_id: str, clone_data: dict[str, Any]) -> dict[str, Any]: ...
    async def get_clone(self, tenant_id: str, clone_id: str) -> dict[str, Any] | None: ...
    async def list_clones(self, tenant_id: str) -> list[dict[str, Any]]: ...
    async def update_clone(self, tenant_id: str, clone_id: str, updates: dict[str, Any]) -> dict[str, Any] | None: ...


class AgentCloneManager:
    """Manages persona-differentiated agent clones.

    Provides CRUD operations for agent clones and generates prompt
    sections from persona configuration. Each clone has a unique
    communication style configured through ``PersonaDimension`` values,
    while sharing product knowledge and methodologies.

    Usage::

        manager = AgentCloneManager(repository=repo)
        clone = await manager.create_clone(
            tenant_id="t-1",
            clone_name="Sarah's Agent",
            owner_id="user-42",
            persona_config=persona,
        )
        prompt_section = manager.build_clone_prompt_section(persona)
    """

    def __init__(
        self,
        repository: CloneRepository,
        llm_service: Any | None = None,
    ) -> None:
        self._repo = repository
        self._llm = llm_service

    # ── CRUD Operations ───────────────────────────────────────────────

    async def create_clone(
        self,
        tenant_id: str,
        clone_name: str,
        owner_id: str,
        persona_config: PersonaConfig,
    ) -> Clone:
        """Create a new agent clone with persona configuration.

        Args:
            tenant_id: Tenant identifier.
            clone_name: Display name for the clone.
            owner_id: Sales rep who owns this clone.
            persona_config: Persona dimensions and settings.

        Returns:
            The created Clone entity.

        Raises:
            ValueError: If persona dimensions are outside [0.0, 1.0].
        """
        self._validate_persona_dimensions(persona_config)

        clone_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        clone_data = {
            "clone_id": clone_id,
            "tenant_id": tenant_id,
            "clone_name": clone_name,
            "owner_id": owner_id,
            "persona": persona_config.model_dump(mode="json"),
            "created_at": now.isoformat(),
            "active": True,
        }

        stored = await self._repo.create_clone(tenant_id, clone_data)
        logger.info(
            "clone.created",
            tenant_id=tenant_id,
            clone_id=clone_id,
            clone_name=clone_name,
            owner_id=owner_id,
        )

        return Clone(
            clone_id=stored.get("clone_id", clone_id),
            tenant_id=tenant_id,
            clone_name=clone_name,
            owner_id=owner_id,
            persona=persona_config,
            created_at=now,
            active=True,
        )

    async def get_clone(self, tenant_id: str, clone_id: str) -> Clone | None:
        """Retrieve a clone by ID.

        Args:
            tenant_id: Tenant identifier.
            clone_id: Clone identifier.

        Returns:
            Clone if found, None otherwise.
        """
        data = await self._repo.get_clone(tenant_id, clone_id)
        if data is None:
            return None
        return self._dict_to_clone(data)

    async def list_clones(self, tenant_id: str, active_only: bool = True) -> list[Clone]:
        """List all clones for a tenant.

        Args:
            tenant_id: Tenant identifier.
            active_only: If True, return only active clones.

        Returns:
            List of Clone entities.
        """
        all_clones = await self._repo.list_clones(tenant_id)
        clones = [self._dict_to_clone(d) for d in all_clones]
        if active_only:
            clones = [c for c in clones if c.active]
        return clones

    async def update_clone(self, tenant_id: str, clone_id: str, **updates: Any) -> Clone | None:
        """Update a clone's fields.

        Args:
            tenant_id: Tenant identifier.
            clone_id: Clone identifier.
            **updates: Fields to update (clone_name, persona, etc.).

        Returns:
            Updated Clone if found, None otherwise.

        Raises:
            ValueError: If updated persona dimensions are invalid.
        """
        if "persona_config" in updates and isinstance(updates["persona_config"], PersonaConfig):
            self._validate_persona_dimensions(updates["persona_config"])
            updates["persona"] = updates.pop("persona_config").model_dump(mode="json")

        data = await self._repo.update_clone(tenant_id, clone_id, updates)
        if data is None:
            return None

        logger.info(
            "clone.updated",
            tenant_id=tenant_id,
            clone_id=clone_id,
            updated_fields=list(updates.keys()),
        )
        return self._dict_to_clone(data)

    async def deactivate_clone(self, tenant_id: str, clone_id: str) -> bool:
        """Soft-deactivate a clone.

        Args:
            tenant_id: Tenant identifier.
            clone_id: Clone identifier.

        Returns:
            True if deactivated, False if clone not found.
        """
        data = await self._repo.update_clone(tenant_id, clone_id, {"active": False})
        if data is None:
            return False

        logger.info("clone.deactivated", tenant_id=tenant_id, clone_id=clone_id)
        return True

    # ── Prompt Generation ─────────────────────────────────────────────

    def build_clone_prompt_section(
        self,
        config: PersonaConfig,
        geographic_adapter: GeographicAdapter | None = None,
    ) -> str:
        """Generate a system prompt section from persona configuration.

        Converts persona dimension values (0.0-1.0) into descriptive
        text guidance for the LLM. Optionally includes geographic
        adaptation if a region is set and an adapter is provided.

        Args:
            config: Persona configuration with dimension values.
            geographic_adapter: Optional adapter for region-specific guidance.

        Returns:
            Formatted prompt section string ready for system prompt injection.
        """
        lines: list[str] = ["## Communication Style"]
        lines.append("")

        for dimension, value in config.dimensions.items():
            text = self._interpolate_dimension(dimension, value)
            lines.append(f"- {text}")

        if config.custom_instructions:
            lines.append("")
            lines.append(f"Custom instructions: {config.custom_instructions}")

        # Geographic adaptation
        if config.region and geographic_adapter:
            geo_section = geographic_adapter.build_geographic_prompt_section(config.region)
            if geo_section:
                lines.append("")
                lines.append(geo_section.rstrip())

        lines.append("")
        lines.append(_METHODOLOGY_DISCLAIMER)

        return "\n".join(lines) + "\n"

    # ── Internal Helpers ──────────────────────────────────────────────

    def _validate_persona_dimensions(self, config: PersonaConfig) -> None:
        """Validate that all persona dimension values are in [0.0, 1.0].

        Args:
            config: Persona configuration to validate.

        Raises:
            ValueError: If any dimension is outside the valid range.
        """
        for dimension, value in config.dimensions.items():
            if not isinstance(value, (int, float)):
                raise ValueError(
                    f"Dimension {dimension.value} must be a float, got {type(value).__name__}"
                )
            if value < 0.0 or value > 1.0:
                raise ValueError(
                    f"Dimension {dimension.value} must be between 0.0 and 1.0, got {value}"
                )

    def _interpolate_dimension(self, dimension: PersonaDimension, value: float) -> str:
        """Convert a numeric dimension value to descriptive text guidance.

        Maps values in [0.0, 1.0] to one of three bands:
        - < 0.3: low extreme
        - 0.3 to 0.7: balanced midrange
        - > 0.7: high extreme

        Args:
            dimension: Which persona dimension.
            value: Numeric value (0.0 to 1.0).

        Returns:
            Human-readable text describing the desired behavior.
        """
        labels = _DIMENSION_LABELS.get(dimension)
        if labels is None:
            logger.warning("clone.unknown_dimension", dimension=dimension.value)
            return f"Unknown dimension: {dimension.value}"

        if value < 0.3:
            return labels["low"]
        elif value > 0.7:
            return labels["high"]
        else:
            return labels["mid"]

    def _dict_to_clone(self, data: dict[str, Any]) -> Clone:
        """Convert a repository dict to a Clone schema."""
        persona_data = data.get("persona", {})
        if isinstance(persona_data, PersonaConfig):
            persona = persona_data
        else:
            persona = PersonaConfig(**persona_data)

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        return Clone(
            clone_id=data["clone_id"],
            tenant_id=data["tenant_id"],
            clone_name=data["clone_name"],
            owner_id=data["owner_id"],
            persona=persona,
            created_at=created_at,
            active=data.get("active", True),
        )
