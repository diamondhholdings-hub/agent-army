"""Progressive context summarization for long-running account timelines.

Partitions interaction timelines into three tiers by age:
- Recent (<=30 days): kept in full detail
- Medium (31-90 days): summarized per ISO week
- Old (>90 days): summarized per month

Supports LLM-based summarization when an llm_service is available,
with a deterministic rule-based fallback for offline/test usage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

import structlog

from src.app.intelligence.consolidation.schemas import ChannelInteraction

logger = structlog.get_logger(__name__)


# ── LLM service protocol ─────────────────────────────────────────────────────


class LLMServiceProtocol(Protocol):
    """Minimal interface for LLM summarization calls."""

    async def completion(
        self, *, messages: list[dict[str, str]], model: str, **kwargs: Any
    ) -> str: ...


# ── SummarizedTimeline ────────────────────────────────────────────────────────


class SummarizedTimeline:
    """Result of progressive summarization across 30/90/365 day windows.

    Attributes:
        recent_interactions: Full-detail interactions from the last 30 days.
        medium_summaries: Per-week summaries for days 31-90.
        historical_summaries: Per-month summaries for days 91+.
    """

    __slots__ = ("recent_interactions", "medium_summaries", "historical_summaries")

    def __init__(
        self,
        recent_interactions: list[ChannelInteraction],
        medium_summaries: list[dict[str, Any]],
        historical_summaries: list[dict[str, Any]],
    ) -> None:
        self.recent_interactions = recent_interactions
        self.medium_summaries = medium_summaries
        self.historical_summaries = historical_summaries

    def __repr__(self) -> str:
        return (
            f"SummarizedTimeline(recent={len(self.recent_interactions)}, "
            f"medium={len(self.medium_summaries)}, "
            f"historical={len(self.historical_summaries)})"
        )


# ── ContextSummarizer ────────────────────────────────────────────────────────


class ContextSummarizer:
    """Progressive summarization engine for customer interaction timelines.

    Partitions a timeline into 30/90/365-day windows and applies
    increasingly aggressive summarization to older content. Recent
    interactions are preserved verbatim; medium-age content is grouped
    by week; old content is grouped by month.

    Args:
        llm_service: Optional LLM service for intelligent summarization.
            When None, a deterministic rule-based fallback is used.
        max_tokens_per_summary: Maximum character length for each
            group summary (default 500).
    """

    RECENT_WINDOW_DAYS: int = 30
    MEDIUM_WINDOW_DAYS: int = 90
    OLD_WINDOW_DAYS: int = 365

    CHARS_PER_TOKEN: float = 4.0  # Matches 03-02 convention

    def __init__(
        self,
        llm_service: LLMServiceProtocol | None = None,
        max_tokens_per_summary: int = 500,
    ) -> None:
        self._llm_service = llm_service
        self._max_tokens_per_summary = max_tokens_per_summary

    # ── Public API ────────────────────────────────────────────────────────

    async def summarize_timeline(
        self, timeline: list[ChannelInteraction]
    ) -> SummarizedTimeline:
        """Partition and progressively summarize a timeline.

        1. Split interactions into recent / medium / old buckets.
        2. Recent: returned as-is (full detail).
        3. Medium: grouped by ISO week, each group summarized.
        4. Old: grouped by month, each group summarized.

        Args:
            timeline: Chronological list of ChannelInteraction objects.

        Returns:
            SummarizedTimeline with three tiers of detail.
        """
        now = datetime.now(timezone.utc)

        recent: list[ChannelInteraction] = []
        medium: list[ChannelInteraction] = []
        old: list[ChannelInteraction] = []

        for interaction in timeline:
            age_days = (now - interaction.timestamp).days
            if age_days <= self.RECENT_WINDOW_DAYS:
                recent.append(interaction)
            elif age_days <= self.MEDIUM_WINDOW_DAYS:
                medium.append(interaction)
            else:
                old.append(interaction)

        logger.debug(
            "summarizer.partitioned",
            recent=len(recent),
            medium=len(medium),
            old=len(old),
        )

        # Medium: summarize by week
        medium_groups = self._group_by_period(medium, "week")
        medium_summaries = []
        for period_label, interactions in medium_groups.items():
            summary = await self._summarize_group(interactions, period_label)
            medium_summaries.append(summary)

        # Old: summarize by month
        old_groups = self._group_by_period(old, "month")
        historical_summaries = []
        for period_label, interactions in old_groups.items():
            summary = await self._summarize_group(interactions, period_label)
            historical_summaries.append(summary)

        return SummarizedTimeline(
            recent_interactions=recent,
            medium_summaries=medium_summaries,
            historical_summaries=historical_summaries,
        )

    # ── Grouping ──────────────────────────────────────────────────────────

    @staticmethod
    def _group_by_period(
        interactions: list[ChannelInteraction], period: str
    ) -> dict[str, list[ChannelInteraction]]:
        """Group interactions by time period.

        Args:
            interactions: List of ChannelInteraction to group.
            period: Either "week" (ISO year-week) or "month" (year-month).

        Returns:
            Dict mapping period labels to interaction lists, sorted by key.
        """
        groups: dict[str, list[ChannelInteraction]] = {}

        for interaction in interactions:
            ts = interaction.timestamp
            if period == "week":
                iso_cal = ts.isocalendar()
                label = f"{iso_cal[0]}-W{iso_cal[1]:02d}"
            else:  # month
                label = f"{ts.year}-{ts.month:02d}"

            if label not in groups:
                groups[label] = []
            groups[label].append(interaction)

        # Return sorted by period label
        return dict(sorted(groups.items()))

    # ── Token estimation ──────────────────────────────────────────────────

    def _compute_token_estimate(self, text: str) -> int:
        """Estimate token count from text length.

        Uses the CHARS_PER_TOKEN constant (matching the 03-02 convention
        of approximately 4 characters per token).

        Args:
            text: Text to estimate token count for.

        Returns:
            Estimated token count (integer).
        """
        return int(len(text) / self.CHARS_PER_TOKEN)

    # ── Summarization ─────────────────────────────────────────────────────

    async def _summarize_group(
        self,
        interactions: list[ChannelInteraction],
        period_label: str,
    ) -> dict[str, Any]:
        """Summarize a group of interactions for a given period.

        If an LLM service is available, uses it for intelligent
        summarization. Otherwise falls back to deterministic
        rule-based concatenation and truncation.

        Args:
            interactions: Interactions within the period.
            period_label: Human-readable period identifier (e.g., "2026-W05").

        Returns:
            Dict with keys: period, summary, interaction_count, channels.
        """
        channels = list({i.channel for i in interactions})

        if self._llm_service is not None:
            summary = await self._llm_summarize(interactions, period_label)
        else:
            summary = self._rule_based_summarize(interactions, period_label)

        return {
            "period": period_label,
            "summary": summary,
            "interaction_count": len(interactions),
            "channels": channels,
        }

    async def _llm_summarize(
        self,
        interactions: list[ChannelInteraction],
        period_label: str,
    ) -> str:
        """Use LLM to generate an intelligent summary of interactions.

        Args:
            interactions: Interactions to summarize.
            period_label: Period identifier for context.

        Returns:
            LLM-generated summary string.
        """
        content_parts = []
        for i in interactions:
            content_parts.append(
                f"[{i.channel}] {i.timestamp.isoformat()}: {i.content_summary}"
            )
        content_text = "\n".join(content_parts)

        prompt = (
            f"Summarize the following customer interactions from period "
            f"{period_label} in a concise paragraph. Focus on key topics, "
            f"decisions, and action items.\n\n{content_text}"
        )

        try:
            result = await self._llm_service.completion(  # type: ignore[union-attr]
                messages=[{"role": "user", "content": prompt}],
                model="fast",
            )
            # Truncate to max_tokens equivalent in characters
            max_chars = int(self._max_tokens_per_summary * self.CHARS_PER_TOKEN)
            return result[:max_chars]
        except Exception:
            logger.warning(
                "summarizer.llm_failed",
                period=period_label,
                exc_info=True,
            )
            # Fall back to rule-based on LLM failure
            return self._rule_based_summarize(interactions, period_label)

    def _rule_based_summarize(
        self,
        interactions: list[ChannelInteraction],
        period_label: str,
    ) -> str:
        """Deterministic rule-based fallback summarization.

        Concatenates content_summary fields, truncates to
        max_tokens_per_summary characters, and prefixes with
        a period descriptor.

        Args:
            interactions: Interactions to summarize.
            period_label: Period identifier for the prefix.

        Returns:
            Truncated summary string.
        """
        parts = [i.content_summary for i in interactions if i.content_summary]
        combined = " | ".join(parts)

        max_chars = int(self._max_tokens_per_summary * self.CHARS_PER_TOKEN)
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "..."

        return f"[{period_label}] {combined}"
