"""Cross-channel entity linking via email domain and participant matching.

Provides EntityLinker for resolving conversations, emails, and meetings
to their parent account/deal by comparing email domains between
participants and known stakeholders.

Per CONTEXT.md locked decision: "Email domain + participant matching.
NO fuzzy matching." Only explicit domain/participant overlap is used.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)


# ── Protocols for dependency injection ────────────────────────────────────────


class DealRepositoryProtocol(Protocol):
    """Minimal interface for deal repository used by EntityLinker."""

    async def list_accounts(self, tenant_id: str) -> list[Any]: ...

    async def list_stakeholders(self, tenant_id: str, account_id: str) -> list[Any]: ...

    async def list_opportunities(
        self, tenant_id: str, filters: Any | None = None
    ) -> list[Any]: ...


# ── ChannelSignal (used by conflict resolution) ──────────────────────────────


class ChannelSignal:
    """A timestamped signal from a communication channel.

    Used for conflict resolution when the same data point appears
    across multiple channels (e.g., budget mentioned in email vs meeting).
    Per CONTEXT.md: most recent timestamp wins.
    """

    __slots__ = ("channel", "key", "value", "timestamp")

    def __init__(
        self,
        channel: str,
        key: str,
        value: Any,
        timestamp: datetime,
    ) -> None:
        self.channel = channel
        self.key = key
        self.value = value
        self.timestamp = timestamp

    def __repr__(self) -> str:
        return (
            f"ChannelSignal(channel={self.channel!r}, key={self.key!r}, "
            f"value={self.value!r}, timestamp={self.timestamp!r})"
        )


# ── EntityLinker ──────────────────────────────────────────────────────────────


class EntityLinker:
    """Cross-channel entity resolution via exact email domain matching.

    Links conversations to accounts by comparing participant email domains
    against stakeholder email domains already stored in the deal repository.

    This class is stateless and requires no constructor dependencies.
    Repository instances are passed per-call to keep the linker lightweight.
    """

    # ── Domain extraction ─────────────────────────────────────────────────

    @staticmethod
    def extract_domains(participants: list[str]) -> set[str]:
        """Extract unique email domains from a list of email addresses.

        Lowercases all domains. Silently skips entries without an "@" sign.

        Args:
            participants: List of email addresses (or free-text entries).

        Returns:
            Set of lowercase domain strings.
        """
        domains: set[str] = set()
        for entry in participants:
            if "@" not in entry:
                continue
            domain = entry.split("@", 1)[1].strip().lower()
            if domain:
                domains.add(domain)
        return domains

    # ── Account linking ───────────────────────────────────────────────────

    async def link_to_account(
        self,
        tenant_id: str,
        participants: list[str],
        deal_repository: DealRepositoryProtocol,
    ) -> str | None:
        """Find the matching account by email domain overlap.

        Extracts domains from the given participant list and compares
        against stakeholder email domains for each account in the tenant.

        Args:
            tenant_id: Tenant identifier.
            participants: List of email addresses from the interaction.
            deal_repository: Repository providing account/stakeholder queries.

        Returns:
            Account ID string if a match is found, None otherwise.
        """
        participant_domains = self.extract_domains(participants)
        if not participant_domains:
            logger.debug(
                "entity_linker.no_domains",
                tenant_id=tenant_id,
                participant_count=len(participants),
            )
            return None

        accounts = await deal_repository.list_accounts(tenant_id)

        for account in accounts:
            stakeholders = await deal_repository.list_stakeholders(
                tenant_id, account.id
            )
            account_domains: set[str] = set()
            for s in stakeholders:
                email = getattr(s, "contact_email", None)
                if email and "@" in email:
                    account_domains.add(email.split("@", 1)[1].strip().lower())

            if participant_domains & account_domains:
                logger.info(
                    "entity_linker.account_match",
                    tenant_id=tenant_id,
                    account_id=account.id,
                    matching_domains=list(participant_domains & account_domains),
                )
                return account.id

        logger.debug(
            "entity_linker.no_account_match",
            tenant_id=tenant_id,
            domains=list(participant_domains),
        )
        return None

    # ── Deal linking ──────────────────────────────────────────────────────

    async def link_to_deal(
        self,
        tenant_id: str,
        account_id: str,
        deal_repository: DealRepositoryProtocol,
    ) -> str | None:
        """Find the most relevant open opportunity for an account.

        Queries all opportunities for the account and returns the first
        one that is not in a closed state (closed_won or closed_lost).

        Args:
            tenant_id: Tenant identifier.
            account_id: Account to search deals for.
            deal_repository: Repository providing opportunity queries.

        Returns:
            Opportunity ID string if an open deal is found, None otherwise.
        """
        from src.app.deals.schemas import OpportunityFilter

        filters = OpportunityFilter(
            tenant_id=tenant_id,
            account_id=account_id,
        )
        opportunities = await deal_repository.list_opportunities(
            tenant_id, filters=filters
        )

        closed_stages = {"closed_won", "closed_lost"}
        for opp in opportunities:
            if getattr(opp, "deal_stage", "") not in closed_stages:
                logger.info(
                    "entity_linker.deal_match",
                    tenant_id=tenant_id,
                    account_id=account_id,
                    opportunity_id=opp.id,
                )
                return opp.id

        logger.debug(
            "entity_linker.no_open_deal",
            tenant_id=tenant_id,
            account_id=account_id,
        )
        return None

    # ── Conflict resolution ───────────────────────────────────────────────

    @staticmethod
    def resolve_conflict(signals: list[ChannelSignal]) -> ChannelSignal:
        """Resolve conflicting signals by recency -- most recent wins.

        Per CONTEXT.md locked decision: "Most recent wins -- latest
        information across channels is assumed correct."

        Args:
            signals: List of ChannelSignal instances to resolve.

        Returns:
            The most recent ChannelSignal.

        Raises:
            ValueError: If the signals list is empty.
        """
        if not signals:
            raise ValueError("Cannot resolve conflict: no signals provided")

        return sorted(signals, key=lambda s: s.timestamp, reverse=True)[0]
