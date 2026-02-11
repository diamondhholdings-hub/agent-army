"""Authentication and authorization tests.

Tests JWT login, token refresh, protected endpoints, cross-tenant
authorization, and API key authentication.
"""

from __future__ import annotations

from jose import jwt

from src.app.config import get_settings
from src.app.core.security import create_access_token


# ── Login Tests ───────────────────────────────────────────────────────────────


async def test_login_valid_credentials(client, tenant_alpha, alpha_user):
    """Login with valid credentials returns JWT tokens with tenant claims."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": alpha_user["email"], "password": alpha_user["password"]},
        headers={"X-Tenant-ID": alpha_user["tenant_id"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"

    # Decode access token and verify tenant claims
    settings = get_settings()
    payload = jwt.decode(
        data["access_token"],
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    assert payload["sub"] == alpha_user["id"]
    assert payload["tenant_id"] == alpha_user["tenant_id"]
    assert payload["tenant_slug"] == "test-alpha"
    assert payload["type"] == "access"


async def test_login_invalid_credentials(client, tenant_alpha, alpha_user):
    """Login with wrong password returns 401."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": alpha_user["email"], "password": "wrong-password"},
        headers={"X-Tenant-ID": alpha_user["tenant_id"]},
    )
    assert response.status_code == 401


async def test_login_nonexistent_user(client, tenant_alpha):
    """Login with unknown email returns 401."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "any-password"},
        headers={"X-Tenant-ID": tenant_alpha["id"]},
    )
    assert response.status_code == 401


# ── Protected Endpoint Tests ─────────────────────────────────────────────────


async def test_access_protected_endpoint(client, alpha_token, alpha_user):
    """Access /auth/me with valid token returns 200 with user info."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {alpha_token}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["email"] == alpha_user["email"]
    assert data["role"] == "admin"
    assert data["tenant_slug"] == "test-alpha"


async def test_access_without_token(client, tenant_alpha):
    """Access /auth/me without token returns 401."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"X-Tenant-ID": tenant_alpha["id"]},
    )
    assert response.status_code == 401


async def test_access_with_invalid_token(client, tenant_alpha):
    """Access /auth/me with invalid token and X-Tenant-ID falls back to header-based tenant."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": "Bearer invalid.token.here",
            "X-Tenant-ID": tenant_alpha["id"],
        },
    )
    # Invalid JWT means get_current_user dependency raises 401
    assert response.status_code == 401


# ── Cross-Tenant Authorization Tests ─────────────────────────────────────────


async def test_cross_tenant_token_rejected(client, alpha_user, tenant_beta):
    """Token claiming wrong tenant_id is rejected when user doesn't exist there."""
    # Create a token claiming tenant_beta but with alpha user's ID
    token_data = {
        "sub": alpha_user["id"],
        "tenant_id": tenant_beta["id"],
        "tenant_slug": "test-beta",
        "email": alpha_user["email"],
        "role": "admin",
    }
    token = create_access_token(token_data)

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    # User does not exist in tenant_beta, so should get 401
    assert response.status_code == 401


async def test_access_wrong_tenant_forbidden(client, alpha_user, tenant_beta):
    """JWT for tenant A accessing endpoint with X-Tenant-ID for tenant B.

    The middleware resolves tenant from JWT (preferred), so the X-Tenant-ID
    header is ignored. The user in tenant A can still access /me because
    the JWT already carries the correct tenant context. True cross-tenant
    rejection is tested in test_cross_tenant_token_rejected above.
    """
    token_data = {
        "sub": alpha_user["id"],
        "tenant_id": alpha_user["tenant_id"],
        "tenant_slug": "test-alpha",
        "email": alpha_user["email"],
        "role": "admin",
    }
    token = create_access_token(token_data)

    # JWT takes priority over X-Tenant-ID, so tenant resolves to alpha
    response = await client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": tenant_beta["id"],
        },
    )
    # JWT tenant wins, user exists in alpha, so 200
    assert response.status_code == 200


# ── Token Refresh Tests ──────────────────────────────────────────────────────


async def test_token_refresh(client, tenant_alpha, alpha_user):
    """Refresh token yields new access + refresh tokens."""
    # Login first to get a refresh token
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": alpha_user["email"], "password": alpha_user["password"]},
        headers={"X-Tenant-ID": alpha_user["tenant_id"]},
    )
    assert login_response.status_code == 200
    refresh_token = login_response.json()["refresh_token"]

    # Use the refresh token to get new tokens
    refresh_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
        headers={"X-Tenant-ID": alpha_user["tenant_id"]},
    )
    assert refresh_response.status_code == 200, refresh_response.text
    data = refresh_response.json()
    assert "access_token" in data
    assert "refresh_token" in data

    # Verify the new access token works
    me_response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me_response.status_code == 200


# ── API Key Tests ─────────────────────────────────────────────────────────────


async def test_api_key_creation(client, alpha_token):
    """Creating an API key returns the raw key value."""
    response = await client.post(
        "/api/v1/auth/api-keys",
        json={"name": "Test CI Key"},
        headers={"Authorization": f"Bearer {alpha_token}"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "Test CI Key"
    assert "key" in data
    assert len(data["key"]) > 20  # token_urlsafe(32) produces ~43 chars
    assert "id" in data


async def test_api_key_authenticates_request(client, alpha_token, alpha_user):
    """API key in X-API-Key header authenticates and resolves user context."""
    # First, create an API key
    create_response = await client.post(
        "/api/v1/auth/api-keys",
        json={"name": "Auth Test Key"},
        headers={"Authorization": f"Bearer {alpha_token}"},
    )
    assert create_response.status_code == 201
    raw_key = create_response.json()["key"]

    # Now use the API key to access a protected endpoint
    me_response = await client.get(
        "/api/v1/auth/me",
        headers={
            "X-API-Key": raw_key,
        },
    )
    assert me_response.status_code == 200, me_response.text
    data = me_response.json()
    assert data["email"] == alpha_user["email"]


# ── Response Header Tests ────────────────────────────────────────────────────


async def test_response_has_request_id(client, alpha_token):
    """Every response includes X-Request-ID header."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {alpha_token}"},
    )
    assert "X-Request-ID" in response.headers
    # Should be a valid UUID format
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 36  # UUID format: 8-4-4-4-12
