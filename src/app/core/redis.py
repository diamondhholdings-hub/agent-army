"""Tenant-aware Redis wrapper with automatic key prefixing.

Every Redis key is automatically prefixed with t:{tenant_id}: to ensure
complete cache isolation between tenants. No cross-tenant cache leakage
is possible when using this wrapper.
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis

from src.app.config import get_settings
from src.app.core.tenant import get_current_tenant

# ── Module-level Redis pool (lazy init) ─────────────────────────────────────

_redis_pool: aioredis.Redis | None = None


def get_redis_pool() -> aioredis.Redis:
    """Get or create the Redis connection pool singleton."""
    global _redis_pool
    if _redis_pool is None:
        settings = get_settings()
        _redis_pool = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis_pool


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _redis_pool
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None


# ── Tenant Redis Wrapper ───────────────────────────────────────────────────


class TenantRedis:
    """Tenant-aware Redis wrapper that auto-prefixes all keys with t:{tenant_id}:.

    This ensures complete cache isolation between tenants. All operations
    use the current tenant context from contextvars.
    """

    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client

    def _key(self, key: str) -> str:
        """Generate a tenant-prefixed key: t:{tenant_id}:{key}."""
        tenant = get_current_tenant()
        return f"t:{tenant.tenant_id}:{key}"

    # ── String operations ───────────────────────────────────────────────

    async def get(self, key: str) -> str | None:
        """Get a value by tenant-prefixed key."""
        return await self._redis.get(self._key(key))

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Set a value with optional TTL (seconds)."""
        await self._redis.set(self._key(key), value, ex=ex)

    async def delete(self, key: str) -> int:
        """Delete a key. Returns number of keys deleted."""
        return await self._redis.delete(self._key(key))

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        return bool(await self._redis.exists(self._key(key)))

    async def expire(self, key: str, seconds: int) -> bool:
        """Set TTL on an existing key."""
        return bool(await self._redis.expire(self._key(key), seconds))

    async def keys(self, pattern: str = "*") -> list[str]:
        """Get keys matching a pattern (within tenant namespace)."""
        full_pattern = self._key(pattern)
        return await self._redis.keys(full_pattern)

    # ── Pub/Sub ─────────────────────────────────────────────────────────

    async def publish(self, channel: str, message: str) -> int:
        """Publish a message to a tenant-prefixed channel."""
        return await self._redis.publish(self._key(channel), message)

    # ── Hash operations ─────────────────────────────────────────────────

    async def hset(self, name: str, key: str, value: str) -> int:
        """Set a hash field."""
        return await self._redis.hset(self._key(name), key, value)

    async def hget(self, name: str, key: str) -> str | None:
        """Get a hash field value."""
        return await self._redis.hget(self._key(name), key)

    async def hgetall(self, name: str) -> dict[str, Any]:
        """Get all fields and values in a hash."""
        return await self._redis.hgetall(self._key(name))


def get_tenant_redis() -> TenantRedis:
    """Get a TenantRedis instance using the global Redis pool."""
    return TenantRedis(get_redis_pool())
