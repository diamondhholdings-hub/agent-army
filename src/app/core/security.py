"""JWT authentication, password hashing, and API key validation.

Provides the core security primitives used by auth endpoints and
middleware to authenticate and authorize requests.

Uses bcrypt directly (not passlib) for Python 3.13 compatibility.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, status
from jose import JWTError, jwt

from src.app.config import get_settings

logger = logging.getLogger(__name__)

# ── Password Hashing ──────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against its bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT Token Creation ────────────────────────────────────────────────────────


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token with tenant-scoped claims.

    The data dict should contain at minimum:
    - sub: user_id (str)
    - tenant_id: tenant UUID (str)
    - tenant_slug: tenant slug (str)
    """
    settings = get_settings()
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "exp": expire,
        "iat": now,
        "type": "access",
    })
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Create a JWT refresh token with longer expiry.

    The data dict should contain at minimum:
    - sub: user_id (str)
    - tenant_id: tenant UUID (str)
    - tenant_slug: tenant slug (str)
    """
    settings = get_settings()
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "iat": now,
        "type": "refresh",
    })
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# ── JWT Token Verification ────────────────────────────────────────────────────


def verify_token(token: str, token_type: str = "access") -> dict:
    """Decode and validate a JWT token.

    Args:
        token: The JWT string.
        token_type: Expected token type ("access" or "refresh").

    Returns:
        The decoded payload dict.

    Raises:
        HTTPException(401): If the token is invalid, expired, or wrong type.
    """
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        if payload.get("type") != token_type:
            raise credentials_exception
        if not payload.get("sub"):
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception


# ── API Key Validation ────────────────────────────────────────────────────────


async def validate_api_key(api_key: str) -> dict | None:
    """Look up an API key in the database and return associated user/tenant info.

    Iterates through all active tenant schemas, sets RLS context for each,
    and checks if the provided API key matches any stored hash.

    Returns a dict with tenant_id, tenant_slug, user_id, user_email if valid,
    or None if the key is not found or inactive.
    """
    from sqlalchemy import text

    from src.app.core.database import get_engine

    engine = get_engine()

    async with engine.connect() as conn:
        # Query all active tenants
        result = await conn.execute(
            text("SELECT schema_name, slug, id::text as tenant_id FROM shared.tenants WHERE is_active = true")
        )
        tenants = result.fetchall()

        for tenant_row in tenants:
            schema = tenant_row.schema_name
            try:
                # Set RLS context for this tenant so queries pass RLS policies
                await conn.execute(
                    text(f"SET app.current_tenant_id = '{tenant_row.tenant_id}'")
                )
                # Commit the SET so it takes effect for subsequent queries
                await conn.commit()

                key_result = await conn.execute(
                    text(f"""
                        SELECT ak.key_hash, ak.user_id::text, ak.is_active,
                               u.email, u.name as user_name
                        FROM {schema}.api_keys ak
                        JOIN {schema}.users u ON ak.user_id = u.id
                        WHERE ak.is_active = true
                    """)
                )
                for key_row in key_result.fetchall():
                    if verify_password(api_key, key_row.key_hash):
                        # Update last_used_at
                        await conn.execute(
                            text(f"""
                                UPDATE {schema}.api_keys
                                SET last_used_at = NOW()
                                WHERE key_hash = :key_hash
                            """),
                            {"key_hash": key_row.key_hash},
                        )
                        await conn.commit()
                        return {
                            "tenant_id": tenant_row.tenant_id,
                            "tenant_slug": tenant_row.slug,
                            "user_id": key_row.user_id,
                            "user_email": key_row.email,
                        }
            except Exception as e:
                # Schema might not have api_keys table yet
                logger.warning("API key lookup failed for schema %s: %s", schema, e)
                # Rollback the failed transaction before continuing
                await conn.rollback()
                continue

    return None
