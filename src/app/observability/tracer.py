"""Langfuse tracing wrapper with agent-scoped trace creation.

Integrates with LiteLLM via success/failure callbacks so every LLM call
is automatically traced with tenant_id, agent_id, and session_id metadata.

When Langfuse keys are not configured, all operations are no-ops --
the application runs without tracing rather than crashing.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Any, Generator

import structlog

from src.app.config import Settings, get_settings

logger = structlog.get_logger(__name__)


def init_langfuse(settings: Settings | None = None) -> bool:
    """Initialize Langfuse tracing on LiteLLM.

    Sets litellm.success_callback and litellm.failure_callback to
    ["langfuse"] so that all LiteLLM completion/embedding calls are
    automatically traced. Also sets LANGFUSE_* environment variables
    from the application settings if not already present.

    Args:
        settings: Application settings. Uses get_settings() if None.

    Returns:
        True if Langfuse was initialized, False if skipped.
    """
    if settings is None:
        settings = get_settings()

    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        logger.info(
            "langfuse.skipped",
            reason="LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not configured",
        )
        return False

    # Set environment variables for the Langfuse SDK (used by LiteLLM
    # callback integration). Only set if not already present so that
    # explicit env vars take precedence over Settings.
    _set_env_if_missing("LANGFUSE_PUBLIC_KEY", settings.LANGFUSE_PUBLIC_KEY)
    _set_env_if_missing("LANGFUSE_SECRET_KEY", settings.LANGFUSE_SECRET_KEY)
    _set_env_if_missing("LANGFUSE_HOST", settings.LANGFUSE_HOST)

    # Configure LiteLLM callbacks
    import litellm

    if "langfuse" not in (litellm.success_callback or []):
        litellm.success_callback = litellm.success_callback or []
        litellm.success_callback.append("langfuse")

    if "langfuse" not in (litellm.failure_callback or []):
        litellm.failure_callback = litellm.failure_callback or []
        litellm.failure_callback.append("langfuse")

    logger.info(
        "langfuse.initialized",
        host=settings.LANGFUSE_HOST,
        callbacks_registered=True,
    )
    return True


def _set_env_if_missing(key: str, value: str) -> None:
    """Set an environment variable only if it is not already set."""
    if not os.environ.get(key):
        os.environ[key] = value


class AgentTracer:
    """Langfuse tracing with agent-scoped metadata propagation.

    Uses ``langfuse.propagate_attributes`` to set user_id, session_id,
    tags, and metadata so that all LiteLLM calls within the context
    manager are automatically annotated.

    When Langfuse is not configured, every method is a no-op.

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
                    "langfuse.client_init_failed",
                    exc_info=True,
                )
                self._enabled = False

    @property
    def enabled(self) -> bool:
        """Whether Langfuse tracing is active."""
        return self._enabled

    @contextmanager
    def trace_agent_execution(
        self,
        agent_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Context manager that propagates Langfuse trace attributes.

        All LiteLLM calls made within this context are automatically
        tagged with the provided agent and tenant metadata via the
        Langfuse callback integration.

        Args:
            agent_id: The agent being executed.
            tenant_id: Tenant for cost grouping (maps to Langfuse user_id).
            session_id: Conversation thread ID (maps to Langfuse session_id).

        Yields:
            Dict with trace metadata (trace_id, agent_id, tenant_id).
        """
        trace_id = str(uuid.uuid4())
        metadata: dict[str, Any] = {
            "trace_id": trace_id,
            "agent_id": agent_id,
            "tenant_id": tenant_id,
        }

        if not self._enabled:
            yield metadata
            return

        try:
            import litellm

            # Set metadata on litellm so the Langfuse callback picks it up.
            # litellm passes these through to Langfuse as trace attributes.
            litellm.langfuse_default_tags = [
                f"agent:{agent_id}",
                f"tenant:{tenant_id}",
            ]

            # Store previous metadata to restore after context
            prev_metadata = getattr(litellm, "_langfuse_default_metadata", None)
            litellm._langfuse_default_metadata = {
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "trace_id": trace_id,
            }

            yield metadata

        except Exception:
            logger.warning(
                "langfuse.trace_context_error",
                agent_id=agent_id,
                tenant_id=tenant_id,
                exc_info=True,
            )
            yield metadata
        finally:
            try:
                import litellm

                litellm.langfuse_default_tags = []
                litellm._langfuse_default_metadata = prev_metadata
            except Exception:
                pass

    def trace_handoff(
        self,
        source_agent: str,
        target_agent: str,
        tenant_id: str,
        valid: bool,
    ) -> None:
        """Record a handoff validation event in Langfuse.

        Creates a Langfuse event/span documenting whether a handoff
        between two agents passed or failed validation. Useful for
        debugging handoff rejections in the Langfuse dashboard.

        Args:
            source_agent: Agent that produced the handoff data.
            target_agent: Agent that will receive the data.
            tenant_id: Tenant context.
            valid: Whether the handoff passed validation.
        """
        if not self._enabled or self._client is None:
            return

        try:
            trace = self._client.trace(
                name=f"handoff:{source_agent}->{target_agent}",
                user_id=tenant_id,
                tags=[
                    f"agent:{source_agent}",
                    f"agent:{target_agent}",
                    f"tenant:{tenant_id}",
                    f"handoff:{'valid' if valid else 'rejected'}",
                ],
                metadata={
                    "source_agent": source_agent,
                    "target_agent": target_agent,
                    "tenant_id": tenant_id,
                    "valid": valid,
                },
            )
            trace.event(
                name="handoff_validation",
                metadata={
                    "source_agent": source_agent,
                    "target_agent": target_agent,
                    "valid": valid,
                },
                level="DEFAULT" if valid else "WARNING",
            )
        except Exception:
            logger.warning(
                "langfuse.trace_handoff_error",
                source_agent=source_agent,
                target_agent=target_agent,
                exc_info=True,
            )
