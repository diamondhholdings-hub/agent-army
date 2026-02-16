"""Cross-channel data consolidation schemas.

Defines the unified customer view and channel interaction types used
to merge data from email, chat, meetings, and CRM into a single
coherent picture of each customer account.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChannelInteraction(BaseModel):
    """A single interaction across any communication channel.

    Represents one touchpoint with a customer -- an email exchange,
    a Slack conversation, a meeting, or a CRM note. Used as timeline
    entries in the unified customer view.
    """

    model_config = ConfigDict(from_attributes=True)

    channel: str = Field(
        ...,
        description="Source channel: email, chat, meeting, crm",
    )
    timestamp: datetime = Field(
        ...,
        description="When this interaction occurred (UTC)",
    )
    participants: List[str] = Field(
        default_factory=list,
        description="Email addresses or names of participants",
    )
    content_summary: str = Field(
        ...,
        description="Brief summary of the interaction content",
    )
    sentiment: Optional[str] = Field(
        default=None,
        description="Detected sentiment: positive, neutral, negative, or None if unknown",
    )
    key_points: List[str] = Field(
        default_factory=list,
        description="Key takeaways extracted from the interaction",
    )


class UnifiedCustomerView(BaseModel):
    """Complete customer context assembled from all channels.

    This is the core data structure for cross-channel consolidation.
    It merges emails, chats, meetings, and CRM data into a single
    chronological view with progressive summarization for older data.

    Recent interactions (last 30 days) are kept in full detail.
    Older interactions are progressively summarized into 90-day
    and 365-day windows.
    """

    model_config = ConfigDict(from_attributes=True)

    tenant_id: str = Field(
        ...,
        description="Tenant identifier",
    )
    account_id: str = Field(
        ...,
        description="Account identifier this view belongs to",
    )
    timeline: List[ChannelInteraction] = Field(
        default_factory=list,
        description="Chronological list of interactions across all channels",
    )
    summary_30d: Optional[str] = Field(
        default=None,
        description="AI-generated summary of last 30 days of activity",
    )
    summary_90d: Optional[str] = Field(
        default=None,
        description="AI-generated summary of last 90 days of activity",
    )
    summary_365d: Optional[str] = Field(
        default=None,
        description="AI-generated summary of last 365 days of activity",
    )
    signals: Dict = Field(
        default_factory=dict,
        description="Extracted signals: BANT/MEDDIC state, pain points, budget mentions",
    )
    last_updated: datetime = Field(
        ...,
        description="When this view was last assembled (UTC)",
    )
