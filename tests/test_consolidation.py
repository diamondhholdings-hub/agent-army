"""Comprehensive tests for cross-channel data consolidation.

Tests EntityLinker (6 tests), ContextSummarizer (5 tests), and
CustomerViewService (5 tests) using in-memory test doubles.
No database or external services required.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

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
from src.app.intelligence.consolidation.customer_view import CustomerViewService


# ── Test Doubles ──────────────────────────────────────────────────────────────
# Minimal in-memory implementations for testing. Not production code.


class _FakeStakeholder:
    """Minimal stakeholder for testing."""

    def __init__(self, contact_email: str, account_id: str = "acc-1") -> None:
        self.contact_email = contact_email
        self.account_id = account_id


class _FakeAccount:
    """Minimal account for testing."""

    def __init__(self, id: str, account_name: str = "Test Corp") -> None:
        self.id = id
        self.account_name = account_name


class _FakeOpportunity:
    """Minimal opportunity for testing."""

    def __init__(
        self,
        id: str,
        name: str = "Deal",
        deal_stage: str = "discovery",
        estimated_value: float | None = 50000.0,
        account_id: str = "acc-1",
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.deal_stage = deal_stage
        self.estimated_value = estimated_value
        self.account_id = account_id
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or self.created_at


class _FakeParticipant:
    """Minimal meeting participant for testing."""

    def __init__(self, email: str, name: str = "Test User") -> None:
        self.email = email
        self.name = name


class _FakeMeeting:
    """Minimal meeting for testing."""

    def __init__(
        self,
        title: str = "Test Meeting",
        scheduled_start: datetime | None = None,
        status: str = "ended",
        participants: list[_FakeParticipant] | None = None,
    ) -> None:
        self.title = title
        self.scheduled_start = scheduled_start or datetime.now(timezone.utc)
        self.status = status
        self.participants = participants or []


class _FakeConversationState:
    """Minimal conversation state for testing."""

    def __init__(
        self,
        contact_id: str = "contact-1",
        account_id: str = "acc-1",
        channel: str = "email",
        deal_stage: str = "discovery",
        last_interaction_at: datetime | None = None,
        qualification: Any = None,
        next_actions: list[Any] | None = None,
    ) -> None:
        self.contact_id = contact_id
        self.account_id = account_id
        self.channel = channel
        self.deal_stage = deal_stage
        self.last_interaction_at = last_interaction_at or datetime.now(timezone.utc)
        self.updated_at = self.last_interaction_at
        self.qualification = qualification
        self.next_actions = next_actions or []


class MockDealRepository:
    """In-memory deal repository for testing."""

    def __init__(
        self,
        accounts: list[_FakeAccount] | None = None,
        stakeholders: dict[str, list[_FakeStakeholder]] | None = None,
        opportunities: list[_FakeOpportunity] | None = None,
    ) -> None:
        self._accounts = accounts or []
        self._stakeholders = stakeholders or {}
        self._opportunities = opportunities or []

    async def list_accounts(self, tenant_id: str) -> list[_FakeAccount]:
        return self._accounts

    async def list_stakeholders(
        self, tenant_id: str, account_id: str
    ) -> list[_FakeStakeholder]:
        return self._stakeholders.get(account_id, [])

    async def list_opportunities(
        self, tenant_id: str, filters: Any | None = None
    ) -> list[_FakeOpportunity]:
        if filters is not None:
            account_id = getattr(filters, "account_id", None)
            if account_id:
                return [o for o in self._opportunities if o.account_id == account_id]
        return self._opportunities


class MockMeetingRepository:
    """In-memory meeting repository for testing."""

    def __init__(self, meetings: list[_FakeMeeting] | None = None) -> None:
        self._meetings = meetings or []

    async def get_upcoming_meetings(
        self, tenant_id: str, from_time: datetime, to_time: datetime
    ) -> list[_FakeMeeting]:
        return self._meetings


class MockConversationStore:
    """In-memory conversation store for testing."""

    def __init__(self, messages: list[Any] | None = None) -> None:
        self._messages = messages or []

    async def get_channel_history(
        self, tenant_id: str, channel: str, limit: int = 50
    ) -> list[Any]:
        return self._messages

    async def get_recent_context(
        self, tenant_id: str, limit: int = 10
    ) -> list[Any]:
        return self._messages[:limit]


class MockStateRepository:
    """In-memory conversation state repository for testing."""

    def __init__(self, states: list[_FakeConversationState] | None = None) -> None:
        self._states = states or []

    async def list_states_by_tenant(
        self, tenant_id: str, deal_stage: str | None = None
    ) -> list[_FakeConversationState]:
        if deal_stage:
            return [s for s in self._states if s.deal_stage == deal_stage]
        return self._states


# ══════════════════════════════════════════════════════════════════════════════
#  EntityLinker Tests (6)
# ══════════════════════════════════════════════════════════════════════════════


class TestEntityLinkerExtractDomains:
    """Tests for EntityLinker.extract_domains."""

    def test_extract_domains(self) -> None:
        """Extracts correct domains from a list of email addresses."""
        participants = [
            "alice@acmecorp.com",
            "bob@bigco.io",
            "carol@acmecorp.com",
        ]
        domains = EntityLinker.extract_domains(participants)
        assert domains == {"acmecorp.com", "bigco.io"}

    def test_extract_domains_invalid_emails(self) -> None:
        """Skips entries without '@' sign."""
        participants = [
            "alice@acmecorp.com",
            "not-an-email",
            "bob@bigco.io",
            "just-a-name",
            "",
        ]
        domains = EntityLinker.extract_domains(participants)
        assert domains == {"acmecorp.com", "bigco.io"}


class TestEntityLinkerLinkToAccount:
    """Tests for EntityLinker.link_to_account."""

    @pytest.mark.asyncio
    async def test_link_to_account_match(self) -> None:
        """Finds account when participant domain overlaps with stakeholder."""
        linker = EntityLinker()
        repo = MockDealRepository(
            accounts=[_FakeAccount(id="acc-1", account_name="Acme Corp")],
            stakeholders={
                "acc-1": [
                    _FakeStakeholder(contact_email="jane@acmecorp.com"),
                    _FakeStakeholder(contact_email="john@acmecorp.com"),
                ]
            },
        )

        result = await linker.link_to_account(
            "tenant-1",
            ["alice@acmecorp.com", "bob@other.com"],
            repo,
        )
        assert result == "acc-1"

    @pytest.mark.asyncio
    async def test_link_to_account_no_match(self) -> None:
        """Returns None when no domain overlap exists."""
        linker = EntityLinker()
        repo = MockDealRepository(
            accounts=[_FakeAccount(id="acc-1")],
            stakeholders={
                "acc-1": [
                    _FakeStakeholder(contact_email="jane@acmecorp.com"),
                ]
            },
        )

        result = await linker.link_to_account(
            "tenant-1",
            ["alice@totally-different.com"],
            repo,
        )
        assert result is None


class TestEntityLinkerConflictResolution:
    """Tests for EntityLinker.resolve_conflict."""

    def test_resolve_conflict_most_recent(self) -> None:
        """Most recent signal wins when resolving conflicts."""
        old_signal = ChannelSignal(
            channel="email",
            key="budget",
            value=500_000,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        new_signal = ChannelSignal(
            channel="meeting",
            key="budget",
            value=750_000,
            timestamp=datetime(2026, 2, 15, tzinfo=timezone.utc),
        )

        winner = EntityLinker.resolve_conflict([old_signal, new_signal])
        assert winner.value == 750_000
        assert winner.channel == "meeting"

    def test_resolve_conflict_empty(self) -> None:
        """Raises ValueError on empty signal list."""
        with pytest.raises(ValueError, match="no signals provided"):
            EntityLinker.resolve_conflict([])


# ══════════════════════════════════════════════════════════════════════════════
#  ContextSummarizer Tests (5)
# ══════════════════════════════════════════════════════════════════════════════


def _make_interaction(
    days_ago: int, channel: str = "email", summary: str = "Test interaction"
) -> ChannelInteraction:
    """Helper to create a ChannelInteraction with a specific age."""
    return ChannelInteraction(
        channel=channel,
        timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
        participants=["test@example.com"],
        content_summary=summary,
    )


class TestContextSummarizer:
    """Tests for ContextSummarizer."""

    @pytest.mark.asyncio
    async def test_summarize_recent_only(self) -> None:
        """All recent interactions are kept as-is in full detail."""
        summarizer = ContextSummarizer()
        timeline = [
            _make_interaction(1, summary="Day 1 call"),
            _make_interaction(5, summary="Day 5 email"),
            _make_interaction(15, summary="Day 15 chat"),
            _make_interaction(29, summary="Day 29 meeting"),
        ]

        result = await summarizer.summarize_timeline(timeline)

        assert isinstance(result, SummarizedTimeline)
        assert len(result.recent_interactions) == 4
        assert len(result.medium_summaries) == 0
        assert len(result.historical_summaries) == 0

    @pytest.mark.asyncio
    async def test_summarize_mixed_timeline(self) -> None:
        """Recent interactions kept in full, medium/old are summarized."""
        summarizer = ContextSummarizer()
        timeline = [
            _make_interaction(5, summary="Recent email"),
            _make_interaction(20, summary="Recent meeting"),
            _make_interaction(45, summary="Medium age chat"),
            _make_interaction(60, summary="Medium age email"),
            _make_interaction(120, summary="Old meeting"),
            _make_interaction(200, summary="Old email"),
        ]

        result = await summarizer.summarize_timeline(timeline)

        assert len(result.recent_interactions) == 2
        assert len(result.medium_summaries) >= 1
        assert len(result.historical_summaries) >= 1

    @pytest.mark.asyncio
    async def test_group_by_week(self) -> None:
        """Groups interactions correctly by ISO week."""
        summarizer = ContextSummarizer()

        # Create interactions in the same week
        base = datetime(2026, 2, 9, tzinfo=timezone.utc)  # Monday W07
        interactions = [
            ChannelInteraction(
                channel="email",
                timestamp=base,
                participants=[],
                content_summary="Monday email",
            ),
            ChannelInteraction(
                channel="chat",
                timestamp=base + timedelta(days=2),
                participants=[],
                content_summary="Wednesday chat",
            ),
        ]

        groups = summarizer._group_by_period(interactions, "week")
        # Both should be in the same ISO week
        assert len(groups) == 1
        week_key = list(groups.keys())[0]
        assert "W07" in week_key or "W06" in week_key  # ISO week
        assert len(list(groups.values())[0]) == 2

    @pytest.mark.asyncio
    async def test_group_by_month(self) -> None:
        """Groups interactions correctly by year-month."""
        summarizer = ContextSummarizer()

        interactions = [
            ChannelInteraction(
                channel="email",
                timestamp=datetime(2026, 1, 5, tzinfo=timezone.utc),
                participants=[],
                content_summary="January email",
            ),
            ChannelInteraction(
                channel="chat",
                timestamp=datetime(2026, 1, 20, tzinfo=timezone.utc),
                participants=[],
                content_summary="January chat",
            ),
            ChannelInteraction(
                channel="email",
                timestamp=datetime(2026, 2, 10, tzinfo=timezone.utc),
                participants=[],
                content_summary="February email",
            ),
        ]

        groups = summarizer._group_by_period(interactions, "month")
        assert "2026-01" in groups
        assert "2026-02" in groups
        assert len(groups["2026-01"]) == 2
        assert len(groups["2026-02"]) == 1

    @pytest.mark.asyncio
    async def test_fallback_without_llm(self) -> None:
        """Rule-based summarization when llm_service is None."""
        summarizer = ContextSummarizer(llm_service=None, max_tokens_per_summary=50)

        interactions = [
            _make_interaction(45, summary="First interaction"),
            _make_interaction(50, summary="Second interaction"),
        ]

        result = await summarizer.summarize_timeline(interactions)

        # Medium summaries should exist and use rule-based approach
        assert len(result.medium_summaries) >= 1
        for s in result.medium_summaries:
            assert "summary" in s
            assert "period" in s
            assert "interaction_count" in s
            assert "channels" in s
            # Rule-based prefix includes the period label in brackets
            assert "[" in s["summary"]


# ══════════════════════════════════════════════════════════════════════════════
#  CustomerViewService Tests (5)
# ══════════════════════════════════════════════════════════════════════════════


def _build_service(
    states: list[_FakeConversationState] | None = None,
    opportunities: list[_FakeOpportunity] | None = None,
    meetings: list[_FakeMeeting] | None = None,
    accounts: list[_FakeAccount] | None = None,
    stakeholders: dict[str, list[_FakeStakeholder]] | None = None,
) -> CustomerViewService:
    """Build a CustomerViewService with test doubles."""
    return CustomerViewService(
        conversation_store=MockConversationStore(),
        state_repository=MockStateRepository(states or []),
        deal_repository=MockDealRepository(
            accounts=accounts or [],
            stakeholders=stakeholders or {},
            opportunities=opportunities or [],
        ),
        meeting_repository=MockMeetingRepository(meetings or []),
        summarizer=ContextSummarizer(llm_service=None),
        entity_linker=EntityLinker(),
    )


class TestCustomerViewService:
    """Tests for CustomerViewService."""

    @pytest.mark.asyncio
    async def test_get_unified_view_assembles_all_channels(self) -> None:
        """Unified view contains data from all 4 data sources."""
        now = datetime.now(timezone.utc)

        service = _build_service(
            states=[
                _FakeConversationState(
                    contact_id="contact-1",
                    account_id="acc-1",
                    channel="email",
                    last_interaction_at=now - timedelta(hours=1),
                ),
            ],
            opportunities=[
                _FakeOpportunity(
                    id="opp-1",
                    name="Enterprise Deal",
                    account_id="acc-1",
                    created_at=now - timedelta(days=5),
                ),
            ],
            meetings=[
                _FakeMeeting(
                    title="Kickoff Call",
                    scheduled_start=now - timedelta(days=2),
                    participants=[_FakeParticipant(email="test@acme.com")],
                ),
            ],
        )

        view = await service.get_unified_view("tenant-1", "acc-1")

        assert isinstance(view, UnifiedCustomerView)
        assert view.tenant_id == "tenant-1"
        assert view.account_id == "acc-1"

        # Timeline should contain entries from conversations, CRM, and meetings
        channels_in_timeline = {i.channel for i in view.timeline}
        assert "email" in channels_in_timeline
        assert "crm" in channels_in_timeline
        assert "meeting" in channels_in_timeline

    @pytest.mark.asyncio
    async def test_timeline_chronological_order(self) -> None:
        """Interactions are sorted by timestamp ascending."""
        now = datetime.now(timezone.utc)

        service = _build_service(
            states=[
                _FakeConversationState(
                    contact_id="c1",
                    last_interaction_at=now - timedelta(days=3),
                ),
                _FakeConversationState(
                    contact_id="c2",
                    last_interaction_at=now - timedelta(days=1),
                ),
            ],
            opportunities=[
                _FakeOpportunity(
                    id="o1",
                    account_id="acc-1",
                    created_at=now - timedelta(days=10),
                ),
            ],
        )

        view = await service.get_unified_view("tenant-1", "acc-1")

        timestamps = [i.timestamp for i in view.timeline]
        assert timestamps == sorted(timestamps)

    @pytest.mark.asyncio
    async def test_current_signals_most_recent_wins(self) -> None:
        """Conflicting signals across channels resolved by recency."""
        now = datetime.now(timezone.utc)

        service = _build_service(
            opportunities=[
                _FakeOpportunity(
                    id="o1",
                    account_id="acc-1",
                    deal_stage="discovery",
                    estimated_value=100_000,
                    created_at=now - timedelta(days=30),
                    updated_at=now - timedelta(days=30),
                ),
                _FakeOpportunity(
                    id="o2",
                    account_id="acc-1",
                    deal_stage="evaluation",
                    estimated_value=250_000,
                    created_at=now - timedelta(days=5),
                    updated_at=now - timedelta(days=5),
                ),
            ],
        )

        view = await service.get_unified_view("tenant-1", "acc-1")

        # Most recent opportunity should win for deal_stage and estimated_value
        assert view.signals.get("deal_stage") == "evaluation"
        assert view.signals.get("estimated_value") == 250_000

    @pytest.mark.asyncio
    async def test_get_recent_activity(self) -> None:
        """Returns only interactions from the last N days."""
        now = datetime.now(timezone.utc)

        service = _build_service(
            states=[
                _FakeConversationState(
                    contact_id="c1",
                    last_interaction_at=now - timedelta(days=2),
                ),
                _FakeConversationState(
                    contact_id="c2",
                    last_interaction_at=now - timedelta(days=15),
                ),
            ],
        )

        recent = await service.get_recent_activity("tenant-1", "acc-1", days=7)

        # Only the 2-day-old interaction should appear
        assert len(recent) == 1
        assert "c1" in recent[0].participants

    @pytest.mark.asyncio
    async def test_empty_account(self) -> None:
        """Handles account with no interactions gracefully."""
        service = _build_service()

        view = await service.get_unified_view("tenant-1", "acc-1")

        assert isinstance(view, UnifiedCustomerView)
        assert view.timeline == []
        assert view.signals == {}
        assert view.summary_30d is None
        assert view.summary_90d is None
        assert view.summary_365d is None
