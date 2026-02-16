"""Unified customer view service -- cross-channel data composition.

CustomerViewService assembles a complete customer view by composing
existing Phase 3/4/5/6 repositories. It does NOT duplicate or replace
existing data stores -- it queries them on demand and merges the results
into a unified chronological timeline with progressive summarization.

This is the central intelligence service that every downstream component
(pattern recognition, autonomy engine, etc.) uses to understand the
complete customer context across all channels.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import structlog

from src.app.intelligence.consolidation.entity_linker import (
    ChannelSignal,
    EntityLinker,
)
from src.app.intelligence.consolidation.schemas import (
    ChannelInteraction,
    UnifiedCustomerView,
)
from src.app.intelligence.consolidation.summarizer import (
    ContextSummarizer,
    SummarizedTimeline,
)

logger = structlog.get_logger(__name__)


# ── Repository protocols ──────────────────────────────────────────────────────
# Minimal interfaces for dependency injection and testing.


class ConversationStoreProtocol(Protocol):
    """Minimal interface for conversation store."""

    async def get_channel_history(
        self, tenant_id: str, channel: str, limit: int = 50
    ) -> list[Any]: ...

    async def get_recent_context(
        self, tenant_id: str, limit: int = 10
    ) -> list[Any]: ...


class StateRepositoryProtocol(Protocol):
    """Minimal interface for conversation state repository."""

    async def list_states_by_tenant(
        self, tenant_id: str, deal_stage: str | None = None
    ) -> list[Any]: ...


class DealRepositoryProtocol(Protocol):
    """Minimal interface for deal repository."""

    async def list_accounts(self, tenant_id: str) -> list[Any]: ...

    async def list_stakeholders(
        self, tenant_id: str, account_id: str
    ) -> list[Any]: ...

    async def list_opportunities(
        self, tenant_id: str, filters: Any | None = None
    ) -> list[Any]: ...


class MeetingRepositoryProtocol(Protocol):
    """Minimal interface for meeting repository."""

    async def get_upcoming_meetings(
        self, tenant_id: str, from_time: datetime, to_time: datetime
    ) -> list[Any]: ...


# ── CustomerViewService ──────────────────────────────────────────────────────


class CustomerViewService:
    """Central cross-channel composition service.

    Queries across ConversationStore (Qdrant), ConversationStateRepository
    (PostgreSQL), DealRepository (PostgreSQL), and MeetingRepository
    (PostgreSQL) to assemble a unified customer view.

    Args:
        conversation_store: Phase 3 conversation store (Qdrant-backed).
        state_repository: Phase 4 conversation state repository.
        deal_repository: Phase 5 deal repository.
        meeting_repository: Phase 6 meeting repository.
        summarizer: ContextSummarizer for progressive timeline compression.
        entity_linker: EntityLinker for cross-channel entity resolution.
    """

    def __init__(
        self,
        conversation_store: ConversationStoreProtocol,
        state_repository: StateRepositoryProtocol,
        deal_repository: DealRepositoryProtocol,
        meeting_repository: MeetingRepositoryProtocol,
        summarizer: ContextSummarizer,
        entity_linker: EntityLinker,
    ) -> None:
        self._conversations = conversation_store
        self._states = state_repository
        self._deals = deal_repository
        self._meetings = meeting_repository
        self._summarizer = summarizer
        self._entity_linker = entity_linker

    # ── Main entry point ──────────────────────────────────────────────────

    async def get_unified_view(
        self, tenant_id: str, account_id: str
    ) -> UnifiedCustomerView:
        """Assemble a complete customer view across all channels.

        Fetches data from all 4 repositories in parallel, builds a
        chronological timeline, applies progressive summarization,
        and extracts current signals.

        Args:
            tenant_id: Tenant identifier.
            account_id: Account to build the view for.

        Returns:
            UnifiedCustomerView with timeline, summaries, and signals.
        """
        from src.app.deals.schemas import OpportunityFilter

        # Parallel fetch from all data sources
        opportunities, stakeholders, meetings, conversation_states = (
            await asyncio.gather(
                self._deals.list_opportunities(
                    tenant_id,
                    filters=OpportunityFilter(
                        tenant_id=tenant_id, account_id=account_id
                    ),
                ),
                self._deals.list_stakeholders(tenant_id, account_id),
                self._fetch_account_meetings(tenant_id, account_id, stakeholders=None),
                self._states.list_states_by_tenant(tenant_id),
            )
        )

        # If the initial meeting fetch was without stakeholder context,
        # re-fetch with proper participant matching using stakeholders
        if stakeholders:
            meetings = await self._fetch_account_meetings(
                tenant_id, account_id, stakeholders=stakeholders
            )

        # Build chronological timeline
        timeline = self._build_timeline(
            conversation_states, opportunities, meetings
        )

        # Apply progressive summarization
        summarized = await self._summarizer.summarize_timeline(timeline)

        # Extract current signals (most recent wins)
        signals = self._extract_current_signals(opportunities, conversation_states)

        # Build action history (agent-initiated actions)
        action_history = self._build_action_history(conversation_states, meetings)

        # Generate summary strings from SummarizedTimeline
        summary_30d = None
        summary_90d = None
        summary_365d = None

        if summarized.recent_interactions:
            summary_30d = (
                f"{len(summarized.recent_interactions)} interactions "
                f"in last 30 days"
            )
        if summarized.medium_summaries:
            parts = [s["summary"] for s in summarized.medium_summaries]
            summary_90d = " ".join(parts)
        if summarized.historical_summaries:
            parts = [s["summary"] for s in summarized.historical_summaries]
            summary_365d = " ".join(parts)

        return UnifiedCustomerView(
            tenant_id=tenant_id,
            account_id=account_id,
            timeline=timeline,
            summary_30d=summary_30d,
            summary_90d=summary_90d,
            summary_365d=summary_365d,
            signals=signals,
            last_updated=datetime.now(timezone.utc),
        )

    # ── Recent activity (lightweight) ─────────────────────────────────────

    async def get_recent_activity(
        self, tenant_id: str, account_id: str, days: int = 7
    ) -> list[ChannelInteraction]:
        """Return only recent interactions -- no summarization, no LLM cost.

        Convenience method for quick context checks that don't need
        the full unified view.

        Args:
            tenant_id: Tenant identifier.
            account_id: Account to query.
            days: Number of days to look back (default 7).

        Returns:
            List of ChannelInteraction objects from the last N days.
        """
        from src.app.deals.schemas import OpportunityFilter

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)

        # Fetch lightweight data
        opportunities, meetings, states = await asyncio.gather(
            self._deals.list_opportunities(
                tenant_id,
                filters=OpportunityFilter(
                    tenant_id=tenant_id, account_id=account_id
                ),
            ),
            self._fetch_account_meetings(tenant_id, account_id, stakeholders=None),
            self._states.list_states_by_tenant(tenant_id),
        )

        timeline = self._build_timeline(states, opportunities, meetings)
        return [i for i in timeline if i.timestamp >= cutoff]

    # ── Internal: meeting fetch with participant matching ──────────────────

    async def _fetch_account_meetings(
        self,
        tenant_id: str,
        account_id: str,
        stakeholders: list[Any] | None,
    ) -> list[Any]:
        """Fetch meetings associated with an account.

        Since MeetingRepository doesn't have an account_id filter,
        we fetch meetings within a broad time window and filter by
        participant email domain overlap with account stakeholders.

        Args:
            tenant_id: Tenant identifier.
            account_id: Account to match.
            stakeholders: Pre-fetched stakeholders (or None for initial call).

        Returns:
            List of meetings associated with the account.
        """
        now = datetime.now(timezone.utc)
        from_time = now - timedelta(days=365)

        all_meetings = await self._meetings.get_upcoming_meetings(
            tenant_id, from_time, now
        )

        if not stakeholders:
            return all_meetings

        # Build set of stakeholder email domains for matching
        account_domains: set[str] = set()
        for s in stakeholders:
            email = getattr(s, "contact_email", None)
            if email and "@" in email:
                account_domains.add(email.split("@", 1)[1].strip().lower())

        if not account_domains:
            return []

        # Filter meetings by participant email domain overlap
        matched: list[Any] = []
        for meeting in all_meetings:
            participants = getattr(meeting, "participants", [])
            for p in participants:
                p_email = getattr(p, "email", "")
                if p_email and "@" in p_email:
                    domain = p_email.split("@", 1)[1].strip().lower()
                    if domain in account_domains:
                        matched.append(meeting)
                        break

        return matched

    # ── Internal: timeline building ───────────────────────────────────────

    @staticmethod
    def _build_timeline(
        conversations: list[Any],
        deals: list[Any],
        meetings: list[Any],
    ) -> list[ChannelInteraction]:
        """Merge all data sources into a sorted list of ChannelInteraction.

        Each data source maps to a channel tag:
        - Conversation states -> "email" or "chat"
        - Opportunities -> "crm"
        - Meetings -> "meeting"

        Args:
            conversations: ConversationState objects.
            deals: OpportunityRead objects.
            meetings: Meeting objects.

        Returns:
            Chronologically sorted list of ChannelInteraction objects.
        """
        interactions: list[ChannelInteraction] = []

        # Conversation states -> channel interactions
        for conv in conversations:
            channel = getattr(conv, "channel", "email")
            if isinstance(channel, str):
                channel_name = channel
            else:
                channel_name = getattr(channel, "value", "email")

            timestamp = getattr(conv, "last_interaction_at", None)
            if timestamp is None:
                timestamp = getattr(conv, "updated_at", None)
            if timestamp is None:
                timestamp = datetime.now(timezone.utc)

            contact_id = getattr(conv, "contact_id", "unknown")
            account_id = getattr(conv, "account_id", "unknown")
            deal_stage = getattr(conv, "deal_stage", None)
            stage_str = ""
            if deal_stage:
                stage_str = getattr(deal_stage, "value", str(deal_stage))

            interactions.append(
                ChannelInteraction(
                    channel=channel_name,
                    timestamp=timestamp,
                    participants=[contact_id],
                    content_summary=(
                        f"Conversation with {contact_id} "
                        f"(account {account_id}, stage: {stage_str})"
                    ),
                    key_points=[f"deal_stage={stage_str}"] if stage_str else [],
                )
            )

        # Opportunities -> CRM interactions
        for opp in deals:
            created = getattr(opp, "created_at", None)
            if created is None:
                created = datetime.now(timezone.utc)

            interactions.append(
                ChannelInteraction(
                    channel="crm",
                    timestamp=created,
                    participants=[],
                    content_summary=(
                        f"Opportunity: {getattr(opp, 'name', 'unknown')} "
                        f"(stage: {getattr(opp, 'deal_stage', 'unknown')}, "
                        f"value: {getattr(opp, 'estimated_value', 'N/A')})"
                    ),
                    key_points=[
                        f"deal_stage={getattr(opp, 'deal_stage', '')}",
                        f"value={getattr(opp, 'estimated_value', '')}",
                    ],
                )
            )

        # Meetings -> meeting interactions
        for meeting in meetings:
            start = getattr(meeting, "scheduled_start", None)
            if start is None:
                start = datetime.now(timezone.utc)

            participants_list: list[str] = []
            for p in getattr(meeting, "participants", []):
                email = getattr(p, "email", None)
                name = getattr(p, "name", None)
                participants_list.append(email or name or "unknown")

            interactions.append(
                ChannelInteraction(
                    channel="meeting",
                    timestamp=start,
                    participants=participants_list,
                    content_summary=(
                        f"Meeting: {getattr(meeting, 'title', 'Untitled')} "
                        f"(status: {getattr(meeting, 'status', 'unknown')})"
                    ),
                    key_points=[
                        f"status={getattr(meeting, 'status', '')}",
                    ],
                )
            )

        # Sort chronologically
        interactions.sort(key=lambda i: i.timestamp)
        return interactions

    # ── Internal: signal extraction ───────────────────────────────────────

    @staticmethod
    def _extract_current_signals(
        deals: list[Any],
        conversations: list[Any],
    ) -> dict[str, Any]:
        """Extract the latest signals from deals and conversations.

        Uses most-recent-wins conflict resolution when the same signal
        appears across multiple channels.

        Args:
            deals: OpportunityRead objects.
            conversations: ConversationState objects.

        Returns:
            Dict mapping signal names to their most recent values.
        """
        signal_groups: dict[str, list[ChannelSignal]] = {}

        # Deal-based signals
        for opp in deals:
            timestamp = getattr(opp, "updated_at", None) or getattr(
                opp, "created_at", datetime.now(timezone.utc)
            )

            # Deal stage signal
            stage = getattr(opp, "deal_stage", None)
            if stage:
                if "deal_stage" not in signal_groups:
                    signal_groups["deal_stage"] = []
                signal_groups["deal_stage"].append(
                    ChannelSignal(
                        channel="crm",
                        key="deal_stage",
                        value=stage,
                        timestamp=timestamp,
                    )
                )

            # Estimated value signal
            value = getattr(opp, "estimated_value", None)
            if value is not None:
                if "estimated_value" not in signal_groups:
                    signal_groups["estimated_value"] = []
                signal_groups["estimated_value"].append(
                    ChannelSignal(
                        channel="crm",
                        key="estimated_value",
                        value=value,
                        timestamp=timestamp,
                    )
                )

        # Conversation-based signals
        for conv in conversations:
            timestamp = getattr(conv, "last_interaction_at", None)
            if timestamp is None:
                timestamp = getattr(conv, "updated_at", datetime.now(timezone.utc))

            qual = getattr(conv, "qualification", None)
            if qual:
                # BANT budget signal
                budget_identified = getattr(qual, "budget_identified", None)
                if budget_identified is not None:
                    if "budget_identified" not in signal_groups:
                        signal_groups["budget_identified"] = []
                    signal_groups["budget_identified"].append(
                        ChannelSignal(
                            channel="conversation",
                            key="budget_identified",
                            value=budget_identified,
                            timestamp=timestamp,
                        )
                    )

        # Resolve conflicts: most recent wins
        resolved: dict[str, Any] = {}
        for key, signals in signal_groups.items():
            winner = EntityLinker.resolve_conflict(signals)
            resolved[key] = winner.value

        return resolved

    # ── Internal: action history ──────────────────────────────────────────

    @staticmethod
    def _build_action_history(
        conversations: list[Any],
        meetings: list[Any],
    ) -> list[ChannelInteraction]:
        """Build a timeline of agent-initiated actions.

        Filters for interactions where the agent took action
        (sent emails, attended meetings), excluding received/inbound.

        Args:
            conversations: ConversationState objects.
            meetings: Meeting objects.

        Returns:
            Chronologically sorted list of agent-initiated ChannelInteraction.
        """
        actions: list[ChannelInteraction] = []

        # Agent-initiated conversations (those with next_actions or follow-ups)
        for conv in conversations:
            next_actions = getattr(conv, "next_actions", [])
            if next_actions:
                timestamp = getattr(conv, "last_interaction_at", None)
                if timestamp is None:
                    timestamp = getattr(
                        conv, "updated_at", datetime.now(timezone.utc)
                    )

                actions.append(
                    ChannelInteraction(
                        channel=getattr(
                            getattr(conv, "channel", "email"), "value", "email"
                        ),
                        timestamp=timestamp,
                        participants=[getattr(conv, "contact_id", "unknown")],
                        content_summary=f"Agent actions planned: {len(next_actions)}",
                        key_points=[
                            getattr(a, "description", str(a))
                            for a in next_actions[:3]
                        ],
                    )
                )

        # Meetings attended
        for meeting in meetings:
            start = getattr(meeting, "scheduled_start", None)
            if start is None:
                start = datetime.now(timezone.utc)

            status = getattr(meeting, "status", None)
            status_val = getattr(status, "value", str(status)) if status else ""

            actions.append(
                ChannelInteraction(
                    channel="meeting",
                    timestamp=start,
                    participants=[
                        getattr(p, "email", getattr(p, "name", "unknown"))
                        for p in getattr(meeting, "participants", [])
                    ],
                    content_summary=(
                        f"Meeting attended: {getattr(meeting, 'title', 'Untitled')} "
                        f"(status: {status_val})"
                    ),
                    key_points=[],
                )
            )

        actions.sort(key=lambda i: i.timestamp)
        return actions
