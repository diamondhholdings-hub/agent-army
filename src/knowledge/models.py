"""Pydantic models for the Knowledge Base domain.

Defines the core types used across the knowledge base: chunks with rich metadata,
tenant configuration, and conversation messages. These models are the contract
between ingestion, storage, and retrieval layers.

Product categories match the actual ESW product portfolio:
- monetization: Revenue optimization and pricing strategies
- charging: Usage-based and subscription charging infrastructure
- billing: Invoice generation, payment processing, billing operations
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


# ── Metadata ────────────────────────────────────────────────────────────────


class ChunkMetadata(BaseModel):
    """Rich metadata for a knowledge chunk, enabling filtered retrieval.

    All list fields support multi-value tagging so a single chunk can be
    relevant across multiple personas, stages, or regions.

    Attributes:
        product_category: ESW product this chunk relates to.
        buyer_persona: Target audience roles for this content.
        sales_stage: Sales process stages where this content is relevant.
        region: Geographic regions where this content applies.
        content_type: Classification of the content's purpose.
        source_document: Original document filename or identifier.
        version: Monotonically increasing version number for this chunk.
        valid_from: When this content became effective.
        valid_until: When this content expires (None = still current).
        is_current: Whether this is the active version.
        cross_references: IDs of related chunks for navigation.
    """

    product_category: Literal["monetization", "charging", "billing"]
    buyer_persona: list[str] = Field(
        default_factory=list,
        description="Target personas: technical, business, executive, operations",
    )
    sales_stage: list[str] = Field(
        default_factory=list,
        description="Relevant stages: discovery, demo, evaluation, negotiation, implementation",
    )
    region: list[str] = Field(
        default_factory=list,
        description="Geographic scope: apac, emea, americas, global",
    )
    content_type: Literal["product", "methodology", "regional", "positioning", "pricing"]
    source_document: str
    version: int = 1
    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: datetime | None = None
    is_current: bool = True
    cross_references: list[str] = Field(default_factory=list)


# ── Knowledge Chunk ─────────────────────────────────────────────────────────


class KnowledgeChunk(BaseModel):
    """A single unit of knowledge stored in the vector database.

    Each chunk is tenant-scoped and carries both the text content and its
    dense/sparse vector representations. Chunks are the atomic unit for
    upsert, search, and retrieval operations.

    Attributes:
        id: Unique identifier (UUID4).
        tenant_id: Owning tenant for RLS-equivalent isolation.
        content: The text content of this chunk.
        metadata: Rich metadata for filtered retrieval.
        embedding_dense: Dense vector from OpenAI embedding model.
        embedding_sparse: Sparse BM25 vector as {indices: [...], values: [...]}.
        created_at: When this chunk was first ingested.
        updated_at: When this chunk was last modified.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    content: str
    metadata: ChunkMetadata
    embedding_dense: list[float] | None = None
    embedding_sparse: dict | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Tenant Config ───────────────────────────────────────────────────────────


class TenantConfig(BaseModel):
    """Configuration for a tenant's knowledge base access.

    Defines which products and regions a tenant has licensed, controlling
    what knowledge is available to their agents.

    Attributes:
        tenant_id: Unique tenant identifier.
        name: Human-readable tenant name.
        products: Licensed product categories.
        regions: Active regions for this tenant.
        active: Whether this tenant's knowledge access is enabled.
    """

    tenant_id: str
    name: str
    products: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    active: bool = True


# ── Conversation Message ────────────────────────────────────────────────────


class ConversationMessage(BaseModel):
    """A single message in a sales conversation, stored for retrieval.

    Conversations are stored in a separate Qdrant collection from the
    knowledge base, indexed by tenant_id, session_id, and channel for
    efficient context window assembly.

    Attributes:
        id: Unique message identifier (UUID4).
        tenant_id: Owning tenant.
        session_id: Conversation session identifier.
        channel: Communication channel (e.g., "email", "slack", "call").
        role: Message author role.
        content: Message text content.
        timestamp: When the message was sent.
        metadata: Additional message metadata (flexible dict).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    session_id: str
    channel: str
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = Field(default_factory=dict)
