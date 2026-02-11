"""LLM service and endpoint tests.

Uses mocks for actual LLM calls to avoid API costs in tests.
Tests response structure, tenant metadata, authentication, and fallback behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── LLM Completion Tests ─────────────────────────────────────────────────────


async def test_llm_completion_requires_auth(client, tenant_alpha):
    """LLM completion without auth token returns 401."""
    response = await client.post(
        "/api/v1/llm/completion",
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "model": "reasoning",
        },
        headers={"X-Tenant-ID": tenant_alpha["id"]},
    )
    assert response.status_code == 401


async def test_llm_completion_with_valid_token(client, alpha_token):
    """LLM completion with valid auth returns structured response."""
    # Mock the LiteLLM Router to avoid actual API calls
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello! How can I help you today?"
    mock_response.model = "claude-sonnet-4-20250514"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 15
    mock_response.usage.total_tokens = 25

    with patch("src.app.services.llm.LLMService") as MockService:
        service_instance = MockService.return_value
        service_instance.router = MagicMock()
        service_instance.completion = AsyncMock(return_value={
            "content": "Hello! How can I help you today?",
            "model": "claude-sonnet-4-20250514",
            "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
            "tenant_id": "test-tenant-id",
        })

        # Patch the singleton getter
        with patch("src.app.api.v1.llm.get_llm_service", return_value=service_instance):
            response = await client.post(
                "/api/v1/llm/completion",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "model": "reasoning",
                },
                headers={"Authorization": f"Bearer {alpha_token}"},
            )

    assert response.status_code == 200, response.text
    data = response.json()
    assert "content" in data
    assert data["content"] == "Hello! How can I help you today?"
    assert "model" in data
    assert "usage" in data
    assert "tenant_id" in data


async def test_llm_completion_includes_tenant_metadata(client, alpha_token, alpha_user):
    """Verify tenant_id is included in LLM response."""
    captured_metadata = {}

    async def mock_completion(messages, model, max_tokens, temperature, metadata=None):
        captured_metadata.update(metadata or {})
        return {
            "content": "Test response",
            "model": "claude-sonnet-4-20250514",
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            "tenant_id": alpha_user["tenant_id"],
        }

    mock_service = MagicMock()
    mock_service.completion = mock_completion

    with patch("src.app.api.v1.llm.get_llm_service", return_value=mock_service):
        response = await client.post(
            "/api/v1/llm/completion",
            json={
                "messages": [{"role": "user", "content": "Test"}],
            },
            headers={"Authorization": f"Bearer {alpha_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == alpha_user["tenant_id"]


async def test_llm_fallback_on_primary_failure():
    """When Claude is unavailable, LiteLLM Router should try GPT-4o fallback.

    This is a unit test of the Router configuration, not an integration test.
    The Router is configured with both models under the "reasoning" group,
    so LiteLLM will automatically try the next model on failure.
    """
    from src.app.services.llm import LLMService

    # Create service with mock settings
    with patch("src.app.services.llm.get_settings") as mock_settings:
        settings = MagicMock()
        settings.ANTHROPIC_API_KEY = "test-anthropic-key"
        settings.OPENAI_API_KEY = "test-openai-key"
        settings.LLM_TIMEOUT = 30
        settings.LLM_MAX_RETRIES = 3
        mock_settings.return_value = settings

        service = LLMService()

    # Verify both models are in the router
    assert service.router is not None
    model_names = [m["model_name"] for m in service.router.model_list]
    assert model_names.count("reasoning") == 2  # Claude + GPT-4o
    assert model_names.count("fast") == 2  # Haiku + GPT-4o-mini
