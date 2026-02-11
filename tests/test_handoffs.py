"""Tests for the handoff validation protocol.

Covers:
- Structural validation (HandoffPayload Pydantic model)
- StrictnessConfig defaults and custom rules
- SemanticValidator with mocked LLM
- HandoffProtocol chaining structural + semantic validation
- HandoffRejectedError with descriptive messages
- Edge cases: fail-open on LLM error, low confidence warnings
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from src.app.handoffs.protocol import HandoffProtocol, HandoffRejectedError
from src.app.handoffs.semantic import SemanticValidator
from src.app.handoffs.validators import (
    HandoffPayload,
    HandoffResult,
    StrictnessConfig,
    ValidationStrictness,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def valid_payload() -> HandoffPayload:
    """A well-formed handoff payload for testing."""
    return HandoffPayload(
        source_agent_id="research_agent",
        target_agent_id="sales_agent",
        call_chain=["user", "supervisor", "research_agent"],
        tenant_id="tenant_001",
        handoff_type="deal_data",
        data={"deal_value": 50000, "company": "Acme Corp"},
        confidence=0.95,
    )


@pytest.fixture
def strictness_config() -> StrictnessConfig:
    """Default strictness configuration."""
    return StrictnessConfig()


@pytest.fixture
def mock_llm_service() -> MagicMock:
    """Mock LLMService for semantic validation tests."""
    mock = MagicMock()
    mock.completion = AsyncMock()
    return mock


# ── Structural Validation Tests ─────────────────────────────────────────────


class TestHandoffPayload:
    """Tests for HandoffPayload Pydantic model validation."""

    def test_valid_handoff_payload(self, valid_payload: HandoffPayload) -> None:
        """Valid payload passes structural validation."""
        assert valid_payload.source_agent_id == "research_agent"
        assert valid_payload.target_agent_id == "sales_agent"
        assert valid_payload.tenant_id == "tenant_001"
        assert valid_payload.handoff_type == "deal_data"
        assert valid_payload.data == {"deal_value": 50000, "company": "Acme Corp"}
        assert valid_payload.confidence == 0.95
        assert len(valid_payload.handoff_id) > 0  # UUID auto-generated
        assert valid_payload.timestamp is not None

    def test_missing_source_in_call_chain(self) -> None:
        """source_agent_id not in call_chain raises ValidationError."""
        with pytest.raises(ValidationError, match="source_agent_id.*must appear in call_chain"):
            HandoffPayload(
                source_agent_id="missing_agent",
                target_agent_id="sales_agent",
                call_chain=["user", "supervisor"],
                tenant_id="t1",
                handoff_type="deal_data",
                data={"key": "value"},
            )

    def test_target_in_call_chain(self) -> None:
        """target_agent_id in call_chain raises ValidationError."""
        with pytest.raises(ValidationError, match="target_agent_id.*must NOT appear in call_chain"):
            HandoffPayload(
                source_agent_id="research_agent",
                target_agent_id="supervisor",
                call_chain=["user", "supervisor", "research_agent"],
                tenant_id="t1",
                handoff_type="deal_data",
                data={"key": "value"},
            )

    def test_empty_call_chain(self) -> None:
        """Empty call_chain raises ValidationError."""
        with pytest.raises(ValidationError):
            HandoffPayload(
                source_agent_id="a1",
                target_agent_id="a2",
                call_chain=[],
                tenant_id="t1",
                handoff_type="deal_data",
                data={"key": "value"},
            )

    def test_confidence_too_high(self) -> None:
        """Confidence above 1.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            HandoffPayload(
                source_agent_id="a1",
                target_agent_id="a2",
                call_chain=["a1"],
                tenant_id="t1",
                handoff_type="deal_data",
                data={},
                confidence=1.5,
            )

    def test_confidence_too_low(self) -> None:
        """Confidence below 0.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            HandoffPayload(
                source_agent_id="a1",
                target_agent_id="a2",
                call_chain=["a1"],
                tenant_id="t1",
                handoff_type="deal_data",
                data={},
                confidence=-0.1,
            )

    def test_empty_source_agent_id(self) -> None:
        """Empty source_agent_id raises ValidationError (min_length=1)."""
        with pytest.raises(ValidationError):
            HandoffPayload(
                source_agent_id="",
                target_agent_id="a2",
                call_chain=[""],
                tenant_id="t1",
                handoff_type="deal_data",
                data={},
            )

    def test_empty_tenant_id(self) -> None:
        """Empty tenant_id raises ValidationError (min_length=1)."""
        with pytest.raises(ValidationError):
            HandoffPayload(
                source_agent_id="a1",
                target_agent_id="a2",
                call_chain=["a1"],
                tenant_id="",
                handoff_type="deal_data",
                data={},
            )


# ── StrictnessConfig Tests ──────────────────────────────────────────────────


class TestStrictnessConfig:
    """Tests for StrictnessConfig handoff type to strictness mapping."""

    def test_strictness_config_defaults(self, strictness_config: StrictnessConfig) -> None:
        """Default rules map handoff types correctly."""
        assert strictness_config.get_strictness("deal_data") == ValidationStrictness.STRICT
        assert strictness_config.get_strictness("customer_info") == ValidationStrictness.STRICT
        assert strictness_config.get_strictness("research_result") == ValidationStrictness.STRICT
        assert strictness_config.get_strictness("status_update") == ValidationStrictness.LENIENT
        assert strictness_config.get_strictness("notification") == ValidationStrictness.LENIENT

    def test_strictness_config_unknown_is_strict(self, strictness_config: StrictnessConfig) -> None:
        """Unknown handoff type defaults to STRICT (fail-safe)."""
        assert strictness_config.get_strictness("unknown_type") == ValidationStrictness.STRICT
        assert strictness_config.get_strictness("") == ValidationStrictness.STRICT
        assert strictness_config.get_strictness("some_new_type") == ValidationStrictness.STRICT

    def test_strictness_config_register_rule(self, strictness_config: StrictnessConfig) -> None:
        """Custom rules can be registered and override defaults."""
        strictness_config.register_rule("custom_type", ValidationStrictness.LENIENT)
        assert strictness_config.get_strictness("custom_type") == ValidationStrictness.LENIENT

        # Override an existing rule
        strictness_config.register_rule("deal_data", ValidationStrictness.LENIENT)
        assert strictness_config.get_strictness("deal_data") == ValidationStrictness.LENIENT


# ── HandoffResult Tests ─────────────────────────────────────────────────────


class TestHandoffResult:
    """Tests for HandoffResult model."""

    def test_handoff_result_valid(self) -> None:
        """Valid HandoffResult has no issues."""
        result = HandoffResult(valid=True, strictness=ValidationStrictness.STRICT)
        assert result.valid is True
        assert result.structural_issues == []
        assert result.semantic_issues == []
        assert result.validated_at is not None
        assert result.validator_model is None

    def test_handoff_result_invalid_with_issues(self) -> None:
        """Invalid HandoffResult carries issue details."""
        result = HandoffResult(
            valid=False,
            strictness=ValidationStrictness.STRICT,
            structural_issues=["missing field: amount"],
            semantic_issues=["claim not grounded: $500k deal"],
            validator_model="fast",
        )
        assert result.valid is False
        assert len(result.structural_issues) == 1
        assert len(result.semantic_issues) == 1
        assert result.validator_model == "fast"


# ── SemanticValidator Tests ─────────────────────────────────────────────────


class TestSemanticValidator:
    """Tests for LLM-based semantic validation."""

    @pytest.mark.asyncio
    async def test_semantic_valid_response(
        self,
        mock_llm_service: MagicMock,
        valid_payload: HandoffPayload,
    ) -> None:
        """SemanticValidator returns valid when LLM confirms data is grounded."""
        mock_llm_service.completion.return_value = {
            "content": '{"valid": true, "issues": []}',
            "model": "claude-haiku",
            "usage": {},
        }

        validator = SemanticValidator(mock_llm_service)
        is_valid, issues = await validator.validate(valid_payload, {"deal": {"value": 50000}})

        assert is_valid is True
        assert issues == []
        mock_llm_service.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_semantic_invalid_response(
        self,
        mock_llm_service: MagicMock,
        valid_payload: HandoffPayload,
    ) -> None:
        """SemanticValidator returns invalid when LLM detects hallucinated claims."""
        mock_llm_service.completion.return_value = {
            "content": '{"valid": false, "issues": ["deal_value of 50000 not found in context", "company Acme Corp not mentioned in source data"]}',
            "model": "claude-haiku",
            "usage": {},
        }

        validator = SemanticValidator(mock_llm_service)
        is_valid, issues = await validator.validate(valid_payload)

        assert is_valid is False
        assert len(issues) == 2
        assert "deal_value" in issues[0]

    @pytest.mark.asyncio
    async def test_semantic_llm_unavailable_failopen(
        self,
        mock_llm_service: MagicMock,
        valid_payload: HandoffPayload,
    ) -> None:
        """SemanticValidator fails open when LLM raises RuntimeError."""
        mock_llm_service.completion.side_effect = RuntimeError("No LLM API keys configured")

        validator = SemanticValidator(mock_llm_service)
        is_valid, issues = await validator.validate(valid_payload)

        assert is_valid is True
        assert issues == ["semantic_validation_unavailable"]

    @pytest.mark.asyncio
    async def test_semantic_llm_timeout_failopen(
        self,
        mock_llm_service: MagicMock,
        valid_payload: HandoffPayload,
    ) -> None:
        """SemanticValidator fails open on timeout."""
        mock_llm_service.completion.side_effect = TimeoutError("LLM request timed out")

        validator = SemanticValidator(mock_llm_service)
        is_valid, issues = await validator.validate(valid_payload)

        assert is_valid is True
        assert issues == ["semantic_validation_unavailable"]

    @pytest.mark.asyncio
    async def test_semantic_unparseable_response_failopen(
        self,
        mock_llm_service: MagicMock,
        valid_payload: HandoffPayload,
    ) -> None:
        """SemanticValidator fails open on unparseable LLM response."""
        mock_llm_service.completion.return_value = {
            "content": "This is not valid JSON",
            "model": "claude-haiku",
            "usage": {},
        }

        validator = SemanticValidator(mock_llm_service)
        is_valid, issues = await validator.validate(valid_payload)

        assert is_valid is True
        assert issues == ["semantic_validation_unavailable"]


# ── HandoffProtocol Tests ───────────────────────────────────────────────────


class TestHandoffProtocol:
    """Tests for the handoff validation protocol."""

    @pytest.mark.asyncio
    async def test_protocol_lenient_skips_semantic(
        self,
        strictness_config: StrictnessConfig,
        mock_llm_service: MagicMock,
    ) -> None:
        """LENIENT handoff type skips semantic validation entirely."""
        semantic_validator = SemanticValidator(mock_llm_service)
        protocol = HandoffProtocol(strictness_config, semantic_validator)

        payload = HandoffPayload(
            source_agent_id="a1",
            target_agent_id="a2",
            call_chain=["a1"],
            tenant_id="t1",
            handoff_type="status_update",  # LENIENT type
            data={"status": "in_progress"},
        )

        result = await protocol.validate(payload)

        assert result.valid is True
        assert result.strictness == ValidationStrictness.LENIENT
        assert result.structural_issues == []
        assert result.semantic_issues == []
        # Semantic validator should NOT have been called
        mock_llm_service.completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_protocol_strict_runs_semantic(
        self,
        strictness_config: StrictnessConfig,
        mock_llm_service: MagicMock,
    ) -> None:
        """STRICT type runs both structural and semantic validation."""
        mock_llm_service.completion.return_value = {
            "content": '{"valid": true, "issues": []}',
            "model": "claude-haiku",
            "usage": {},
        }
        semantic_validator = SemanticValidator(mock_llm_service)
        protocol = HandoffProtocol(strictness_config, semantic_validator)

        payload = HandoffPayload(
            source_agent_id="a1",
            target_agent_id="a2",
            call_chain=["a1"],
            tenant_id="t1",
            handoff_type="deal_data",  # STRICT type
            data={"amount": 100000},
        )

        result = await protocol.validate(payload, {"deal": {"amount": 100000}})

        assert result.valid is True
        assert result.strictness == ValidationStrictness.STRICT
        assert result.validator_model == "fast"
        # Semantic validator SHOULD have been called
        mock_llm_service.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_protocol_semantic_failure_rejects(
        self,
        strictness_config: StrictnessConfig,
        mock_llm_service: MagicMock,
    ) -> None:
        """Mock LLM returns invalid, protocol returns invalid result."""
        mock_llm_service.completion.return_value = {
            "content": '{"valid": false, "issues": ["deal amount 100000 not grounded in context"]}',
            "model": "claude-haiku",
            "usage": {},
        }
        semantic_validator = SemanticValidator(mock_llm_service)
        protocol = HandoffProtocol(strictness_config, semantic_validator)

        payload = HandoffPayload(
            source_agent_id="a1",
            target_agent_id="a2",
            call_chain=["a1"],
            tenant_id="t1",
            handoff_type="deal_data",
            data={"amount": 100000},
        )

        result = await protocol.validate(payload)

        assert result.valid is False
        assert result.strictness == ValidationStrictness.STRICT
        assert len(result.semantic_issues) == 1
        assert "not grounded" in result.semantic_issues[0]

    @pytest.mark.asyncio
    async def test_protocol_llm_unavailable_failopen(
        self,
        strictness_config: StrictnessConfig,
        mock_llm_service: MagicMock,
    ) -> None:
        """Mock LLM raises RuntimeError, validation passes with warning."""
        mock_llm_service.completion.side_effect = RuntimeError("No LLM keys")
        semantic_validator = SemanticValidator(mock_llm_service)
        protocol = HandoffProtocol(strictness_config, semantic_validator)

        payload = HandoffPayload(
            source_agent_id="a1",
            target_agent_id="a2",
            call_chain=["a1"],
            tenant_id="t1",
            handoff_type="deal_data",
            data={"amount": 100000},
        )

        result = await protocol.validate(payload)

        # Fail-open: validation passes even though LLM failed
        assert result.valid is True
        assert result.strictness == ValidationStrictness.STRICT

    @pytest.mark.asyncio
    async def test_protocol_no_semantic_validator(
        self,
        strictness_config: StrictnessConfig,
    ) -> None:
        """Protocol without semantic validator still validates structurally."""
        protocol = HandoffProtocol(strictness_config, semantic_validator=None)

        payload = HandoffPayload(
            source_agent_id="a1",
            target_agent_id="a2",
            call_chain=["a1"],
            tenant_id="t1",
            handoff_type="deal_data",
            data={"amount": 100000},
        )

        result = await protocol.validate(payload)

        assert result.valid is True
        assert result.strictness == ValidationStrictness.STRICT
        assert result.validator_model is None

    @pytest.mark.asyncio
    async def test_validate_or_reject_raises(
        self,
        strictness_config: StrictnessConfig,
        mock_llm_service: MagicMock,
    ) -> None:
        """validate_or_reject raises HandoffRejectedError on semantic failure."""
        mock_llm_service.completion.return_value = {
            "content": '{"valid": false, "issues": ["fabricated company name"]}',
            "model": "claude-haiku",
            "usage": {},
        }
        semantic_validator = SemanticValidator(mock_llm_service)
        protocol = HandoffProtocol(strictness_config, semantic_validator)

        payload = HandoffPayload(
            source_agent_id="a1",
            target_agent_id="a2",
            call_chain=["a1"],
            tenant_id="t1",
            handoff_type="deal_data",
            data={"company": "Fake Corp"},
        )

        with pytest.raises(HandoffRejectedError) as exc_info:
            await protocol.validate_or_reject(payload)

        error = exc_info.value
        assert error.result.valid is False
        assert error.payload.handoff_id == payload.handoff_id
        assert "fabricated company name" in str(error)
        assert "deal_data" in str(error)

    @pytest.mark.asyncio
    async def test_validate_or_reject_passes(
        self,
        strictness_config: StrictnessConfig,
        mock_llm_service: MagicMock,
    ) -> None:
        """validate_or_reject returns payload on success."""
        mock_llm_service.completion.return_value = {
            "content": '{"valid": true, "issues": []}',
            "model": "claude-haiku",
            "usage": {},
        }
        semantic_validator = SemanticValidator(mock_llm_service)
        protocol = HandoffProtocol(strictness_config, semantic_validator)

        payload = HandoffPayload(
            source_agent_id="a1",
            target_agent_id="a2",
            call_chain=["a1"],
            tenant_id="t1",
            handoff_type="deal_data",
            data={"amount": 50000},
        )

        result = await protocol.validate_or_reject(payload)
        assert result.handoff_id == payload.handoff_id


# ── HandoffRejectedError Tests ──────────────────────────────────────────────


class TestHandoffRejectedError:
    """Tests for HandoffRejectedError descriptive messages."""

    def test_rejected_error_str_includes_reasons(self) -> None:
        """HandoffRejectedError.__str__ includes rejection reasons."""
        payload = HandoffPayload(
            source_agent_id="a1",
            target_agent_id="a2",
            call_chain=["a1"],
            tenant_id="t1",
            handoff_type="deal_data",
            data={},
        )
        result = HandoffResult(
            valid=False,
            strictness=ValidationStrictness.STRICT,
            structural_issues=["missing amount field"],
            semantic_issues=["unverified claim"],
        )

        error = HandoffRejectedError(result=result, payload=payload)
        error_str = str(error)

        assert "missing amount field" in error_str
        assert "unverified claim" in error_str
        assert "deal_data" in error_str
        assert "strict" in error_str
        assert payload.handoff_id in error_str
