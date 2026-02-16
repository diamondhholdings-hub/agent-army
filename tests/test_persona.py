"""Comprehensive tests for persona sub-package: geographic, cloning, builder.

Tests GeographicAdapter prompt section generation, AgentCloneManager
CRUD and prompt interpolation, and PersonaBuilder guided creation with
preview. All tests use in-memory doubles -- no database dependency.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from src.app.intelligence.persona.cloning import AgentCloneManager
from src.app.intelligence.persona.geographic import GeographicAdapter
from src.app.intelligence.persona.persona_builder import PersonaBuilder
from src.app.intelligence.persona.schemas import (
    Clone,
    GeographicProfile,
    PersonaConfig,
    PersonaDimension,
    PersonaPreview,
)


# ── Test Doubles ──────────────────────────────────────────────────────────────


class InMemoryCloneRepository:
    """In-memory test double for clone persistence."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def create_clone(self, tenant_id: str, clone_data: dict[str, Any]) -> dict[str, Any]:
        key = f"{tenant_id}:{clone_data['clone_id']}"
        clone_data["tenant_id"] = tenant_id
        self._store[key] = clone_data
        return clone_data

    async def get_clone(self, tenant_id: str, clone_id: str) -> dict[str, Any] | None:
        return self._store.get(f"{tenant_id}:{clone_id}")

    async def list_clones(self, tenant_id: str) -> list[dict[str, Any]]:
        return [v for k, v in self._store.items() if k.startswith(f"{tenant_id}:")]

    async def update_clone(
        self, tenant_id: str, clone_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        key = f"{tenant_id}:{clone_id}"
        if key not in self._store:
            return None
        self._store[key].update(updates)
        return self._store[key]


class MockLLMService:
    """Mock LLM service that returns canned PersonaPreview data."""

    def __init__(self, response: Any = None) -> None:
        self._response = response
        self.last_prompt: str | None = None

    async def completion(self, **kwargs: Any) -> Any:
        messages = kwargs.get("messages", [])
        if messages:
            self._last_prompt = messages[0].get("content", "")
        if self._response is not None:
            return self._response
        return PersonaPreview(
            persona=PersonaConfig(
                clone_id="preview",
                tenant_id="",
                owner_id="test",
            ),
            sample_email="LLM-generated email sample.",
            sample_chat="LLM-generated chat sample.",
            persona_summary="LLM-generated persona summary.",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_persona(**overrides: Any) -> PersonaConfig:
    defaults: dict[str, Any] = {
        "clone_id": str(uuid.uuid4()),
        "tenant_id": "t-1",
        "owner_id": "user-42",
        "dimensions": {
            PersonaDimension.formal_casual: 0.5,
            PersonaDimension.concise_detailed: 0.5,
            PersonaDimension.technical_business: 0.5,
            PersonaDimension.proactive_reactive: 0.5,
        },
    }
    defaults.update(overrides)
    return PersonaConfig(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# GeographicAdapter Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestGeographicAdapter:
    """Tests for geographic prompt section generation."""

    def setup_method(self) -> None:
        self.adapter = GeographicAdapter()

    def test_build_prompt_section_apac(self) -> None:
        section = self.adapter.build_geographic_prompt_section("apac")
        assert section != ""
        assert "Asia-Pacific" in section
        assert "Relationship-first" in section or "relationship" in section.lower()

    def test_build_prompt_section_emea(self) -> None:
        section = self.adapter.build_geographic_prompt_section("emea")
        assert section != ""
        assert "Europe" in section

    def test_build_prompt_section_americas(self) -> None:
        section = self.adapter.build_geographic_prompt_section("americas")
        assert section != ""
        assert "Americas" in section
        assert "direct" in section.lower() or "Direct" in section or "ROI" in section

    def test_build_prompt_section_unknown_region(self) -> None:
        section = self.adapter.build_geographic_prompt_section("unknown")
        assert section == ""

    def test_build_prompt_section_case_insensitive(self) -> None:
        section = self.adapter.build_geographic_prompt_section("APAC")
        assert section != ""
        assert "Asia-Pacific" in section

    def test_prompt_section_contains_methodology_disclaimer(self) -> None:
        for region in ["apac", "emea", "americas"]:
            section = self.adapter.build_geographic_prompt_section(region)
            assert "Do NOT change the sales methodology" in section, (
                f"Missing methodology disclaimer for {region}"
            )

    def test_get_supported_regions(self) -> None:
        regions = self.adapter.get_supported_regions()
        assert len(regions) == 3
        assert "apac" in regions
        assert "emea" in regions
        assert "americas" in regions

    def test_get_geographic_profile(self) -> None:
        profile = self.adapter.get_geographic_profile("apac")
        assert isinstance(profile, GeographicProfile)
        assert profile.code == "apac"
        assert profile.name == "Asia-Pacific"
        assert profile.formality_default == 0.7
        assert len(profile.cultural_notes) > 0
        assert profile.communication_style != ""

    def test_get_geographic_profile_emea(self) -> None:
        profile = self.adapter.get_geographic_profile("emea")
        assert profile.formality_default == 0.6

    def test_get_geographic_profile_americas(self) -> None:
        profile = self.adapter.get_geographic_profile("americas")
        assert profile.formality_default == 0.4

    def test_get_geographic_profile_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            self.adapter.get_geographic_profile("unknown")


# ══════════════════════════════════════════════════════════════════════════════
# AgentCloneManager Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestAgentCloneManager:
    """Tests for agent clone CRUD and prompt generation."""

    def setup_method(self) -> None:
        self.repo = InMemoryCloneRepository()
        self.manager = AgentCloneManager(repository=self.repo)

    @pytest.mark.asyncio
    async def test_create_clone(self) -> None:
        persona = _make_persona()
        clone = await self.manager.create_clone(
            tenant_id="t-1",
            clone_name="Test Clone",
            owner_id="user-42",
            persona_config=persona,
        )
        assert isinstance(clone, Clone)
        assert clone.clone_name == "Test Clone"
        assert clone.owner_id == "user-42"
        assert clone.active is True

    @pytest.mark.asyncio
    async def test_create_clone_invalid_dimensions(self) -> None:
        persona = _make_persona(
            dimensions={PersonaDimension.formal_casual: 1.5}
        )
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            await self.manager.create_clone(
                tenant_id="t-1",
                clone_name="Bad Clone",
                owner_id="user-42",
                persona_config=persona,
            )

    @pytest.mark.asyncio
    async def test_create_clone_negative_dimension(self) -> None:
        persona = _make_persona(
            dimensions={PersonaDimension.concise_detailed: -0.1}
        )
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            await self.manager.create_clone(
                tenant_id="t-1",
                clone_name="Bad Clone",
                owner_id="user-42",
                persona_config=persona,
            )

    @pytest.mark.asyncio
    async def test_get_clone(self) -> None:
        persona = _make_persona()
        created = await self.manager.create_clone(
            tenant_id="t-1",
            clone_name="Fetch Me",
            owner_id="user-42",
            persona_config=persona,
        )
        fetched = await self.manager.get_clone("t-1", created.clone_id)
        assert fetched is not None
        assert fetched.clone_name == "Fetch Me"

    @pytest.mark.asyncio
    async def test_get_clone_not_found(self) -> None:
        result = await self.manager.get_clone("t-1", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_clones_active_only(self) -> None:
        persona = _make_persona()
        clone1 = await self.manager.create_clone(
            tenant_id="t-1",
            clone_name="Active Clone",
            owner_id="user-1",
            persona_config=persona,
        )
        clone2 = await self.manager.create_clone(
            tenant_id="t-1",
            clone_name="Inactive Clone",
            owner_id="user-2",
            persona_config=persona,
        )
        await self.manager.deactivate_clone("t-1", clone2.clone_id)

        active = await self.manager.list_clones("t-1", active_only=True)
        assert len(active) == 1
        assert active[0].clone_id == clone1.clone_id

    @pytest.mark.asyncio
    async def test_list_clones_all(self) -> None:
        persona = _make_persona()
        await self.manager.create_clone(
            tenant_id="t-1",
            clone_name="Clone A",
            owner_id="user-1",
            persona_config=persona,
        )
        clone2 = await self.manager.create_clone(
            tenant_id="t-1",
            clone_name="Clone B",
            owner_id="user-2",
            persona_config=persona,
        )
        await self.manager.deactivate_clone("t-1", clone2.clone_id)

        all_clones = await self.manager.list_clones("t-1", active_only=False)
        assert len(all_clones) == 2

    @pytest.mark.asyncio
    async def test_deactivate_clone(self) -> None:
        persona = _make_persona()
        clone = await self.manager.create_clone(
            tenant_id="t-1",
            clone_name="To Deactivate",
            owner_id="user-42",
            persona_config=persona,
        )
        result = await self.manager.deactivate_clone("t-1", clone.clone_id)
        assert result is True

        fetched = await self.manager.get_clone("t-1", clone.clone_id)
        assert fetched is not None
        assert fetched.active is False

    @pytest.mark.asyncio
    async def test_deactivate_clone_not_found(self) -> None:
        result = await self.manager.deactivate_clone("t-1", "nonexistent")
        assert result is False

    def test_build_clone_prompt_section(self) -> None:
        persona = _make_persona(
            dimensions={
                PersonaDimension.formal_casual: 0.5,
                PersonaDimension.concise_detailed: 0.5,
                PersonaDimension.technical_business: 0.5,
                PersonaDimension.proactive_reactive: 0.5,
            },
        )
        section = self.manager.build_clone_prompt_section(persona)
        assert "Communication Style" in section
        assert "balanced" in section.lower() or "moderate" in section.lower()

    def test_build_clone_prompt_section_formal(self) -> None:
        persona = _make_persona(
            dimensions={
                PersonaDimension.formal_casual: 0.9,
                PersonaDimension.concise_detailed: 0.5,
                PersonaDimension.technical_business: 0.5,
                PersonaDimension.proactive_reactive: 0.5,
            },
        )
        section = self.manager.build_clone_prompt_section(persona)
        assert "formal" in section.lower()

    def test_build_clone_prompt_section_casual(self) -> None:
        persona = _make_persona(
            dimensions={
                PersonaDimension.formal_casual: 0.1,
                PersonaDimension.concise_detailed: 0.5,
                PersonaDimension.technical_business: 0.5,
                PersonaDimension.proactive_reactive: 0.5,
            },
        )
        section = self.manager.build_clone_prompt_section(persona)
        assert "casual" in section.lower() or "friendly" in section.lower()

    def test_build_clone_prompt_technical(self) -> None:
        persona = _make_persona(
            dimensions={
                PersonaDimension.formal_casual: 0.5,
                PersonaDimension.concise_detailed: 0.5,
                PersonaDimension.technical_business: 0.9,
                PersonaDimension.proactive_reactive: 0.5,
            },
        )
        section = self.manager.build_clone_prompt_section(persona)
        assert "technical" in section.lower()

    def test_build_clone_prompt_business(self) -> None:
        persona = _make_persona(
            dimensions={
                PersonaDimension.formal_casual: 0.5,
                PersonaDimension.concise_detailed: 0.5,
                PersonaDimension.technical_business: 0.1,
                PersonaDimension.proactive_reactive: 0.5,
            },
        )
        section = self.manager.build_clone_prompt_section(persona)
        assert "business" in section.lower()

    def test_build_clone_prompt_proactive(self) -> None:
        persona = _make_persona(
            dimensions={
                PersonaDimension.formal_casual: 0.5,
                PersonaDimension.concise_detailed: 0.5,
                PersonaDimension.technical_business: 0.5,
                PersonaDimension.proactive_reactive: 0.9,
            },
        )
        section = self.manager.build_clone_prompt_section(persona)
        assert "proactive" in section.lower()

    def test_build_clone_prompt_with_custom_instructions(self) -> None:
        persona = _make_persona(
            custom_instructions="Always mention our new enterprise tier."
        )
        section = self.manager.build_clone_prompt_section(persona)
        assert "Always mention our new enterprise tier" in section

    def test_build_clone_prompt_with_region(self) -> None:
        persona = _make_persona(region="apac")
        adapter = GeographicAdapter()
        section = self.manager.build_clone_prompt_section(
            persona, geographic_adapter=adapter
        )
        assert "Asia-Pacific" in section
        assert "Do NOT change the sales methodology" in section

    def test_prompt_section_includes_methodology_disclaimer(self) -> None:
        persona = _make_persona()
        section = self.manager.build_clone_prompt_section(persona)
        assert "do NOT override" in section.lower() or "do not override" in section.lower()

    def test_interpolate_dimension_formal(self) -> None:
        text = self.manager._interpolate_dimension(
            PersonaDimension.formal_casual, 0.0
        )
        assert "casual" in text.lower() or "friendly" in text.lower()

    def test_interpolate_dimension_casual_high(self) -> None:
        text = self.manager._interpolate_dimension(
            PersonaDimension.formal_casual, 1.0
        )
        assert "formal" in text.lower()


# ══════════════════════════════════════════════════════════════════════════════
# PersonaBuilder Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPersonaBuilder:
    """Tests for guided persona creation and preview generation."""

    def setup_method(self) -> None:
        self.builder = PersonaBuilder()

    def test_get_dimension_options_all_keys(self) -> None:
        options = self.builder.get_dimension_options()
        assert len(options) == 4
        dims = {opt["dimension"] for opt in options}
        assert PersonaDimension.formal_casual in dims
        assert PersonaDimension.concise_detailed in dims
        assert PersonaDimension.technical_business in dims
        assert PersonaDimension.proactive_reactive in dims

    def test_get_dimension_options_have_labels(self) -> None:
        options = self.builder.get_dimension_options()
        for opt in options:
            assert "label" in opt
            assert "low" in opt
            assert "high" in opt
            assert "description" in opt
            assert "default" in opt

    def test_build_persona_default_region(self) -> None:
        persona = self.builder.build_persona(
            clone_name="Test",
            owner_id="user-1",
        )
        assert isinstance(persona, PersonaConfig)
        assert persona.owner_id == "user-1"
        assert len(persona.dimensions) == 4
        # Without region, all dimensions at 0.5
        assert persona.dimensions[PersonaDimension.formal_casual] == 0.5

    def test_build_persona_apac_defaults(self) -> None:
        persona = self.builder.build_persona(
            clone_name="APAC Agent",
            owner_id="user-1",
            region="apac",
        )
        # APAC should get higher formality default
        assert persona.dimensions[PersonaDimension.formal_casual] == 0.7
        assert persona.region == "apac"

    def test_build_persona_explicit_formality_overrides_region(self) -> None:
        persona = self.builder.build_persona(
            clone_name="Custom",
            owner_id="user-1",
            dimensions={PersonaDimension.formal_casual: 0.2},
            region="apac",
        )
        # Explicit value should win over region default
        assert persona.dimensions[PersonaDimension.formal_casual] == 0.2

    def test_build_persona_with_custom_instructions(self) -> None:
        persona = self.builder.build_persona(
            clone_name="Custom",
            owner_id="user-1",
            custom_instructions="Focus on healthcare vertical.",
        )
        assert persona.custom_instructions == "Focus on healthcare vertical."

    def test_validate_persona_valid(self) -> None:
        persona = _make_persona()
        warnings = self.builder.validate_persona(persona)
        assert warnings == []

    def test_validate_persona_out_of_range(self) -> None:
        persona = _make_persona(
            dimensions={PersonaDimension.formal_casual: 1.5}
        )
        warnings = self.builder.validate_persona(persona)
        assert len(warnings) > 0
        assert "between 0.0 and 1.0" in warnings[0]

    def test_validate_persona_unknown_region(self) -> None:
        persona = _make_persona(region="narnia")
        warnings = self.builder.validate_persona(persona)
        assert len(warnings) > 0
        assert "Unknown region" in warnings[0]

    def test_validate_persona_empty_clone_id(self) -> None:
        persona = _make_persona(clone_id="")
        warnings = self.builder.validate_persona(persona)
        assert any("clone_id" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_generate_preview_no_llm(self) -> None:
        persona = _make_persona(
            dimensions={
                PersonaDimension.formal_casual: 0.9,
                PersonaDimension.concise_detailed: 0.9,
                PersonaDimension.technical_business: 0.5,
                PersonaDimension.proactive_reactive: 0.5,
            },
        )
        preview = await self.builder.generate_preview(persona)
        assert isinstance(preview, PersonaPreview)
        assert preview.sample_email != ""
        assert preview.sample_chat != ""
        assert preview.persona_summary != ""
        # High formality should show formal greeting
        assert "Dear" in preview.sample_email or "Sir" in preview.sample_email

    @pytest.mark.asyncio
    async def test_generate_preview_casual(self) -> None:
        persona = _make_persona(
            dimensions={
                PersonaDimension.formal_casual: 0.1,
                PersonaDimension.concise_detailed: 0.1,
                PersonaDimension.technical_business: 0.1,
                PersonaDimension.proactive_reactive: 0.1,
            },
        )
        preview = await self.builder.generate_preview(persona)
        assert "Hey" in preview.sample_email or "hey" in preview.sample_email.lower()

    @pytest.mark.asyncio
    async def test_generate_preview_with_llm(self) -> None:
        mock_llm = MockLLMService()
        builder = PersonaBuilder(llm_service=mock_llm)
        persona = _make_persona()
        preview = await builder.generate_preview(persona)
        assert isinstance(preview, PersonaPreview)
        assert "LLM-generated" in preview.sample_email

    @pytest.mark.asyncio
    async def test_generate_preview_llm_fallback_on_error(self) -> None:
        class FailingLLM:
            async def completion(self, **kwargs: Any) -> Any:
                raise RuntimeError("LLM unavailable")

        builder = PersonaBuilder(llm_service=FailingLLM())
        persona = _make_persona()
        preview = await builder.generate_preview(persona)
        # Should fall back to rule-based generation
        assert isinstance(preview, PersonaPreview)
        assert preview.sample_email != ""

    @pytest.mark.asyncio
    async def test_generate_preview_proactive_dimension(self) -> None:
        persona = _make_persona(
            dimensions={
                PersonaDimension.formal_casual: 0.5,
                PersonaDimension.concise_detailed: 0.5,
                PersonaDimension.technical_business: 0.5,
                PersonaDimension.proactive_reactive: 0.9,
            },
        )
        preview = await self.builder.generate_preview(persona)
        assert "proactive" in preview.persona_summary.lower()
