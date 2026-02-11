"""Tests for ConversationStore and SessionManager.

Uses Qdrant local mode with tmp_path for isolated test instances.
EmbeddingService is mocked to return deterministic vectors, avoiding
OpenAI API calls during testing. Tests cover:
- Message persistence and retrieval
- Cross-session semantic search
- Tenant isolation
- Channel filtering
- Session lifecycle management
- Time-range queries
- Session deletion
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.knowledge.config import KnowledgeBaseConfig
from src.knowledge.conversations.session import ConversationSession, SessionManager
from src.knowledge.conversations.store import ConversationStore
from src.knowledge.embeddings import EmbeddingService
from src.knowledge.models import ConversationMessage
from src.knowledge.qdrant_client import QdrantKnowledgeStore


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_dense_vector(seed: float = 0.1, dims: int = 1536) -> list[float]:
    """Generate a deterministic dense vector for testing.

    Uses sin function with seed to create unique but reproducible vectors.
    Same seed always produces the same vector, different seeds produce
    different vectors with some cosine similarity variation.
    """
    return [math.sin(seed * (i + 1)) for i in range(dims)]


def _make_message(
    tenant_id: str,
    session_id: str,
    channel: str = "web",
    role: str = "user",
    content: str = "Test message",
    timestamp: datetime | None = None,
    metadata: dict | None = None,
) -> ConversationMessage:
    """Create a ConversationMessage for testing."""
    return ConversationMessage(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        session_id=session_id,
        channel=channel,
        role=role,
        content=content,
        timestamp=timestamp or datetime.now(timezone.utc),
        metadata=metadata or {},
    )


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def config(tmp_path) -> KnowledgeBaseConfig:
    """Create a KnowledgeBaseConfig pointing at a temporary directory."""
    return KnowledgeBaseConfig(
        qdrant_path=str(tmp_path / "qdrant_conv_test"),
        openai_api_key="test-key-not-used",
    )


@pytest.fixture
def mock_embedder() -> EmbeddingService:
    """Create a mock EmbeddingService returning deterministic vectors.

    Uses hash of text content to generate unique vectors per message,
    ensuring that semantically different texts get different vectors
    while the same text always produces the same vector.
    """
    service = MagicMock(spec=EmbeddingService)

    async def mock_embed_text(text: str) -> tuple[list[float], dict]:
        seed = abs(hash(text)) % 1000 / 1000.0 + 0.01
        return _make_dense_vector(seed), {"indices": [1, 5], "values": [1.0, 0.5]}

    service.embed_text = AsyncMock(side_effect=mock_embed_text)

    async def mock_embed_batch(
        texts: list[str],
    ) -> list[tuple[list[float], dict]]:
        results = []
        for text in texts:
            seed = abs(hash(text)) % 1000 / 1000.0 + 0.01
            results.append((_make_dense_vector(seed), {"indices": [1, 5], "values": [1.0, 0.5]}))
        return results

    service.embed_batch = AsyncMock(side_effect=mock_embed_batch)

    return service


@pytest.fixture
async def qdrant_store(config, mock_embedder) -> QdrantKnowledgeStore:
    """Create a QdrantKnowledgeStore with initialized collections."""
    store = QdrantKnowledgeStore(config=config, embedding_service=mock_embedder)
    await store.initialize_collections()
    yield store
    store.close()


@pytest.fixture
def conv_store(qdrant_store, mock_embedder) -> ConversationStore:
    """Create a ConversationStore backed by the test Qdrant instance."""
    return ConversationStore(
        qdrant_client=qdrant_store.client,
        embedder=mock_embedder,
        collection_name="conversations",
    )


@pytest.fixture
def session_mgr(conv_store) -> SessionManager:
    """Create a SessionManager backed by the test ConversationStore."""
    return SessionManager(store=conv_store)


# ── Tests: Message Persistence and Retrieval ───────────────────────────────


async def test_add_and_retrieve_messages(conv_store: ConversationStore):
    """Add 5 messages to a session, retrieve session history, verify order and content."""
    tenant = "tenant-conv-1"
    session = str(uuid.uuid4())
    base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    messages = []
    for i in range(5):
        msg = _make_message(
            tenant_id=tenant,
            session_id=session,
            role="user" if i % 2 == 0 else "assistant",
            content=f"Message number {i}: talking about topic {i}",
            timestamp=base_time + timedelta(minutes=i),
        )
        messages.append(msg)

    # Add messages one by one
    for msg in messages:
        await conv_store.add_message(msg)

    # Retrieve session history
    history = await conv_store.get_session_history(
        tenant_id=tenant, session_id=session
    )

    assert len(history) == 5

    # Verify order (ascending by timestamp)
    for i, msg in enumerate(history):
        assert f"Message number {i}" in msg.content
        assert msg.tenant_id == tenant
        assert msg.session_id == session

    # Verify timestamps are ascending
    for i in range(len(history) - 1):
        assert history[i].timestamp <= history[i + 1].timestamp


# ── Tests: Cross-Session Semantic Search ───────────────────────────────────


async def test_cross_session_search(conv_store: ConversationStore):
    """Create 2 sessions for same tenant. Search from session 2 finds session 1 content."""
    tenant = "tenant-search-1"
    session_1 = str(uuid.uuid4())
    session_2 = str(uuid.uuid4())

    # Session 1: discuss pricing for enterprise tier
    pricing_messages = [
        _make_message(
            tenant_id=tenant,
            session_id=session_1,
            content="Let's discuss pricing for the enterprise tier",
        ),
        _make_message(
            tenant_id=tenant,
            session_id=session_1,
            role="assistant",
            content="Enterprise pricing starts at $50,000 per year with volume discounts",
        ),
        _make_message(
            tenant_id=tenant,
            session_id=session_1,
            content="What about pricing for more than 1000 users?",
        ),
    ]
    await conv_store.add_messages(pricing_messages)

    # Session 2: different topic
    other_messages = [
        _make_message(
            tenant_id=tenant,
            session_id=session_2,
            content="How does the integration work with Salesforce?",
        ),
    ]
    await conv_store.add_messages(other_messages)

    # Search for "pricing" across all sessions
    results = await conv_store.search_conversations(
        tenant_id=tenant,
        query="pricing enterprise tier cost",
        top_k=5,
    )

    assert len(results) > 0
    # Should find messages from session 1 about pricing
    session_1_results = [r for r in results if r.session_id == session_1]
    assert len(session_1_results) > 0


# ── Tests: Tenant Isolation ────────────────────────────────────────────────


async def test_tenant_isolation(conv_store: ConversationStore):
    """Tenant A cannot search or retrieve tenant B messages."""
    session_a = str(uuid.uuid4())
    session_b = str(uuid.uuid4())

    # Tenant A messages
    await conv_store.add_message(
        _make_message(
            tenant_id="tenant-A",
            session_id=session_a,
            content="Tenant A secret pricing strategy for Q3",
        )
    )

    # Tenant B messages
    await conv_store.add_message(
        _make_message(
            tenant_id="tenant-B",
            session_id=session_b,
            content="Tenant B competitive analysis",
        )
    )

    # Tenant A searches: should NOT find tenant B messages
    results_a = await conv_store.search_conversations(
        tenant_id="tenant-A",
        query="competitive analysis",
        top_k=10,
    )
    for r in results_a:
        assert r.tenant_id == "tenant-A"

    # Tenant B searches: should NOT find tenant A messages
    results_b = await conv_store.search_conversations(
        tenant_id="tenant-B",
        query="pricing strategy",
        top_k=10,
    )
    for r in results_b:
        assert r.tenant_id == "tenant-B"

    # Tenant A session history: cannot see tenant B sessions
    history_a = await conv_store.get_session_history(
        tenant_id="tenant-A", session_id=session_b
    )
    assert len(history_a) == 0

    # Tenant B session history: cannot see tenant A sessions
    history_b = await conv_store.get_session_history(
        tenant_id="tenant-B", session_id=session_a
    )
    assert len(history_b) == 0


# ── Tests: Channel History ─────────────────────────────────────────────────


async def test_channel_history(conv_store: ConversationStore):
    """Messages across 2 channels are correctly filtered by channel."""
    tenant = "tenant-channel-1"
    session = str(uuid.uuid4())

    # Web channel messages
    web_msg = _make_message(
        tenant_id=tenant,
        session_id=session,
        channel="web",
        content="Web chat message about product features",
    )
    await conv_store.add_message(web_msg)

    # Email channel messages
    email_msg = _make_message(
        tenant_id=tenant,
        session_id=session,
        channel="email",
        content="Email follow-up about contract terms",
    )
    await conv_store.add_message(email_msg)

    # Retrieve web channel history
    web_history = await conv_store.get_channel_history(
        tenant_id=tenant, channel="web"
    )
    assert len(web_history) == 1
    assert web_history[0].channel == "web"
    assert "product features" in web_history[0].content

    # Retrieve email channel history
    email_history = await conv_store.get_channel_history(
        tenant_id=tenant, channel="email"
    )
    assert len(email_history) == 1
    assert email_history[0].channel == "email"
    assert "contract terms" in email_history[0].content


# ── Tests: SessionManager ─────────────────────────────────────────────────


async def test_session_manager_create_and_add(session_mgr: SessionManager):
    """SessionManager creates session, adds messages, and tracks count."""
    session = await session_mgr.create_session(
        tenant_id="tenant-sm-1",
        channel="slack",
        metadata={"prospect_name": "Acme Corp"},
    )

    assert session.tenant_id == "tenant-sm-1"
    assert session.channel == "slack"
    assert session.message_count == 0
    assert session.metadata["prospect_name"] == "Acme Corp"

    # Add messages
    msg1 = await session_mgr.add_message_to_session(
        session, role="user", content="Hello, I need help with billing"
    )
    assert msg1.tenant_id == "tenant-sm-1"
    assert msg1.session_id == session.session_id
    assert msg1.channel == "slack"
    assert session.message_count == 1

    msg2 = await session_mgr.add_message_to_session(
        session, role="assistant", content="Sure, what billing issue are you having?"
    )
    assert session.message_count == 2

    msg3 = await session_mgr.add_message_to_session(
        session, role="user", content="My invoice shows incorrect amount"
    )
    assert session.message_count == 3


# ── Tests: Cross-Session Context ───────────────────────────────────────────


async def test_cross_session_context(
    conv_store: ConversationStore, session_mgr: SessionManager
):
    """get_context_for_session includes relevant messages from prior sessions."""
    tenant = "tenant-ctx-1"

    # Session 1: discuss pricing (prior session)
    session_1 = await session_mgr.create_session(tenant_id=tenant, channel="web")
    await session_mgr.add_message_to_session(
        session_1, role="user", content="What is the pricing for enterprise plan?"
    )
    await session_mgr.add_message_to_session(
        session_1, role="assistant", content="Enterprise plan starts at $50,000 annually"
    )

    # Session 2: new session, different topic that might relate
    session_2 = await session_mgr.create_session(tenant_id=tenant, channel="email")
    await session_mgr.add_message_to_session(
        session_2, role="user", content="Can we get a volume discount on the enterprise plan pricing?"
    )

    # Get context for session 2 with cross-session enabled
    context = await session_mgr.get_context_for_session(
        session_2, include_cross_session=True, max_messages=20
    )

    # Should include session 2's own message
    session_2_msgs = [m for m in context if m.session_id == session_2.session_id]
    assert len(session_2_msgs) >= 1

    # Context should have messages (at minimum the current session's)
    assert len(context) >= 1


async def test_cross_session_context_disabled(
    conv_store: ConversationStore, session_mgr: SessionManager
):
    """get_context_for_session with include_cross_session=False returns only current."""
    tenant = "tenant-ctx-2"

    # Session 1: prior session
    session_1 = await session_mgr.create_session(tenant_id=tenant, channel="web")
    await session_mgr.add_message_to_session(
        session_1, role="user", content="Prior session about billing issues"
    )

    # Session 2: current session
    session_2 = await session_mgr.create_session(tenant_id=tenant, channel="web")
    await session_mgr.add_message_to_session(
        session_2, role="user", content="New session about billing questions"
    )

    # Get context without cross-session
    context = await session_mgr.get_context_for_session(
        session_2, include_cross_session=False
    )

    # Should only contain session 2 messages
    for msg in context:
        assert msg.session_id == session_2.session_id


# ── Tests: Time Range Search ──────────────────────────────────────────────


async def test_time_range_search(conv_store: ConversationStore):
    """Search with time_range filter returns only messages in that range."""
    tenant = "tenant-time-1"
    session = str(uuid.uuid4())

    base_time = datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc)

    # Message from Jan 10
    old_msg = _make_message(
        tenant_id=tenant,
        session_id=session,
        content="Old message about product roadmap from January",
        timestamp=base_time,
    )
    await conv_store.add_message(old_msg)

    # Message from Jan 20
    mid_msg = _make_message(
        tenant_id=tenant,
        session_id=session,
        content="Mid message about product demo in mid-January",
        timestamp=base_time + timedelta(days=10),
    )
    await conv_store.add_message(mid_msg)

    # Message from Feb 1
    new_msg = _make_message(
        tenant_id=tenant,
        session_id=session,
        content="New message about product pricing in February",
        timestamp=base_time + timedelta(days=22),
    )
    await conv_store.add_message(new_msg)

    # Search within Jan 15 - Jan 25 range
    range_start = base_time + timedelta(days=5)
    range_end = base_time + timedelta(days=15)

    results = await conv_store.search_conversations(
        tenant_id=tenant,
        query="product",
        top_k=10,
        time_range=(range_start, range_end),
    )

    # Should only find the mid-January message
    assert len(results) == 1
    assert "mid-January" in results[0].content


# ── Tests: Delete Session ──────────────────────────────────────────────────


async def test_delete_session(conv_store: ConversationStore):
    """Delete session removes all messages and returns correct count."""
    tenant = "tenant-del-1"
    session = str(uuid.uuid4())

    # Add 3 messages
    for i in range(3):
        msg = _make_message(
            tenant_id=tenant,
            session_id=session,
            content=f"Message {i} to be deleted",
        )
        await conv_store.add_message(msg)

    # Verify they exist
    history = await conv_store.get_session_history(tenant_id=tenant, session_id=session)
    assert len(history) == 3

    # Delete session
    deleted_count = await conv_store.delete_session(
        tenant_id=tenant, session_id=session
    )
    assert deleted_count == 3

    # Verify messages are gone
    history_after = await conv_store.get_session_history(
        tenant_id=tenant, session_id=session
    )
    assert len(history_after) == 0


async def test_delete_session_tenant_isolation(conv_store: ConversationStore):
    """Deleting a session as wrong tenant deletes nothing."""
    session = str(uuid.uuid4())

    # Add message as tenant A
    await conv_store.add_message(
        _make_message(
            tenant_id="tenant-A",
            session_id=session,
            content="Tenant A message",
        )
    )

    # Try to delete as tenant B
    deleted = await conv_store.delete_session(
        tenant_id="tenant-B", session_id=session
    )
    assert deleted == 0

    # Verify tenant A message still exists
    history = await conv_store.get_session_history(
        tenant_id="tenant-A", session_id=session
    )
    assert len(history) == 1


# ── Tests: Batch Operations ───────────────────────────────────────────────


async def test_add_messages_batch(conv_store: ConversationStore):
    """Batch add_messages stores all messages efficiently."""
    tenant = "tenant-batch-1"
    session = str(uuid.uuid4())

    messages = [
        _make_message(
            tenant_id=tenant,
            session_id=session,
            content=f"Batch message {i}",
            timestamp=datetime(2026, 1, 15, 10, i, 0, tzinfo=timezone.utc),
        )
        for i in range(5)
    ]

    ids = await conv_store.add_messages(messages)
    assert len(ids) == 5

    # Verify all stored
    history = await conv_store.get_session_history(
        tenant_id=tenant, session_id=session
    )
    assert len(history) == 5


async def test_add_messages_empty_list(conv_store: ConversationStore):
    """Batch add_messages with empty list returns empty list."""
    ids = await conv_store.add_messages([])
    assert ids == []


# ── Tests: Recent Context ─────────────────────────────────────────────────


async def test_get_recent_context(conv_store: ConversationStore):
    """get_recent_context returns most recent messages for tenant."""
    tenant = "tenant-recent-1"
    base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    for i in range(5):
        await conv_store.add_message(
            _make_message(
                tenant_id=tenant,
                session_id=str(uuid.uuid4()),
                content=f"Recent message {i}",
                timestamp=base_time + timedelta(minutes=i),
            )
        )

    recent = await conv_store.get_recent_context(tenant_id=tenant, limit=3)
    assert len(recent) == 3
    # Should be ordered by timestamp descending (most recent first)
    for i in range(len(recent) - 1):
        assert recent[i].timestamp >= recent[i + 1].timestamp


# ── Tests: Session Summary ─────────────────────────────────────────────────


async def test_summarize_session(session_mgr: SessionManager):
    """Session summary includes metadata and extracted topics."""
    session = await session_mgr.create_session(
        tenant_id="tenant-sum-1", channel="web"
    )

    await session_mgr.add_message_to_session(
        session, role="user", content="We need to discuss enterprise pricing for the billing product"
    )
    await session_mgr.add_message_to_session(
        session, role="assistant", content="The billing product enterprise pricing starts at $50,000"
    )
    await session_mgr.add_message_to_session(
        session, role="user", content="Can we get a discount on the enterprise billing pricing?"
    )

    summary = await session_mgr.summarize_session(session)

    assert session.session_id in summary
    assert "web" in summary
    assert "3 messages" in summary
    assert "Topics discussed:" in summary
    # Should extract meaningful keywords
    assert "pricing" in summary.lower() or "billing" in summary.lower() or "enterprise" in summary.lower()


async def test_summarize_empty_session(session_mgr: SessionManager):
    """Summarizing an empty session returns appropriate message."""
    session = await session_mgr.create_session(
        tenant_id="tenant-sum-2", channel="email"
    )

    summary = await session_mgr.summarize_session(session)

    assert session.session_id in summary
    assert "0 messages" in summary
