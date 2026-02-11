"""Per-tenant per-agent cost aggregation from Langfuse.

Queries the Langfuse API for cost data grouped by agent and tenant.
When Langfuse is not configured, returns zero-cost dicts with a
"source": "unavailable" flag so callers can distinguish between
"zero cost" and "cost tracking not available".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from src.app.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class CostTracker:
    """Per-tenant per-agent cost aggregation from Langfuse.

    Queries Langfuse's traces endpoint filtered by user_id (tenant_id)
    and extracts cost and token usage data grouped by agent.

    When Langfuse is not configured, all methods return empty/zero
    cost dictionaries with ``"source": "unavailable"`` so callers can
    detect the absence of cost data.

    Args:
        settings: Application settings. Uses get_settings() if None.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        if settings is None:
            settings = get_settings()
        self._settings = settings
        self._enabled = bool(
            settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY
        )
        self._client: Any = None

        if self._enabled:
            try:
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                    host=settings.LANGFUSE_HOST,
                )
            except Exception:
                logger.warning(
                    "cost_tracker.client_init_failed",
                    exc_info=True,
                )
                self._enabled = False

    @property
    def enabled(self) -> bool:
        """Whether cost tracking is available."""
        return self._enabled

    async def get_tenant_costs(
        self,
        tenant_id: str,
        period_days: int = 30,
    ) -> dict[str, Any]:
        """Get cost data for a tenant grouped by agent.

        Queries Langfuse traces filtered by user_id = tenant_id and
        aggregates cost and token usage by the agent_id tag/metadata.

        Args:
            tenant_id: The tenant to query costs for.
            period_days: Number of days to look back.

        Returns:
            Dict with tenant cost breakdown:
            {
                "tenant_id": str,
                "period_days": int,
                "agents": {
                    agent_id: {
                        "total_cost": float,
                        "total_tokens": int,
                        "invocation_count": int,
                    }
                },
                "total_cost": float,
                "source": "langfuse" | "unavailable",
            }
        """
        if not self._enabled or self._client is None:
            return _empty_tenant_costs(tenant_id, period_days)

        try:
            from_timestamp = datetime.now(timezone.utc) - timedelta(
                days=period_days
            )

            # Langfuse Python SDK provides fetch_traces for listing traces
            traces = self._client.fetch_traces(
                user_id=tenant_id,
                from_timestamp=from_timestamp,
            )

            agents: dict[str, dict[str, Any]] = {}
            total_cost = 0.0

            for trace in traces.data:
                agent_id = (trace.metadata or {}).get("agent_id", "unknown")
                cost = getattr(trace, "total_cost", 0.0) or 0.0
                tokens = getattr(trace, "total_tokens", 0) or 0

                if agent_id not in agents:
                    agents[agent_id] = {
                        "total_cost": 0.0,
                        "total_tokens": 0,
                        "invocation_count": 0,
                    }

                agents[agent_id]["total_cost"] += cost
                agents[agent_id]["total_tokens"] += tokens
                agents[agent_id]["invocation_count"] += 1
                total_cost += cost

            return {
                "tenant_id": tenant_id,
                "period_days": period_days,
                "agents": agents,
                "total_cost": total_cost,
                "source": "langfuse",
            }

        except Exception:
            logger.warning(
                "cost_tracker.get_tenant_costs_failed",
                tenant_id=tenant_id,
                exc_info=True,
            )
            return _empty_tenant_costs(tenant_id, period_days)

    async def get_agent_costs(
        self,
        agent_id: str,
        period_days: int = 30,
    ) -> dict[str, Any]:
        """Get cost data for a specific agent across all tenants.

        Args:
            agent_id: The agent to query costs for.
            period_days: Number of days to look back.

        Returns:
            Dict with agent cost breakdown:
            {
                "agent_id": str,
                "period_days": int,
                "tenants": {
                    tenant_id: {
                        "total_cost": float,
                        "total_tokens": int,
                    }
                },
                "total_cost": float,
                "source": "langfuse" | "unavailable",
            }
        """
        if not self._enabled or self._client is None:
            return _empty_agent_costs(agent_id, period_days)

        try:
            from_timestamp = datetime.now(timezone.utc) - timedelta(
                days=period_days
            )

            # Fetch traces tagged with this agent
            traces = self._client.fetch_traces(
                tags=[f"agent:{agent_id}"],
                from_timestamp=from_timestamp,
            )

            tenants: dict[str, dict[str, Any]] = {}
            total_cost = 0.0

            for trace in traces.data:
                tenant_id = trace.user_id or "unknown"
                cost = getattr(trace, "total_cost", 0.0) or 0.0
                tokens = getattr(trace, "total_tokens", 0) or 0

                if tenant_id not in tenants:
                    tenants[tenant_id] = {
                        "total_cost": 0.0,
                        "total_tokens": 0,
                    }

                tenants[tenant_id]["total_cost"] += cost
                tenants[tenant_id]["total_tokens"] += tokens
                total_cost += cost

            return {
                "agent_id": agent_id,
                "period_days": period_days,
                "tenants": tenants,
                "total_cost": total_cost,
                "source": "langfuse",
            }

        except Exception:
            logger.warning(
                "cost_tracker.get_agent_costs_failed",
                agent_id=agent_id,
                exc_info=True,
            )
            return _empty_agent_costs(agent_id, period_days)


def _empty_tenant_costs(tenant_id: str, period_days: int) -> dict[str, Any]:
    """Return empty tenant cost dict when Langfuse is unavailable."""
    return {
        "tenant_id": tenant_id,
        "period_days": period_days,
        "agents": {},
        "total_cost": 0.0,
        "source": "unavailable",
    }


def _empty_agent_costs(agent_id: str, period_days: int) -> dict[str, Any]:
    """Return empty agent cost dict when Langfuse is unavailable."""
    return {
        "agent_id": agent_id,
        "period_days": period_days,
        "tenants": {},
        "total_cost": 0.0,
        "source": "unavailable",
    }
