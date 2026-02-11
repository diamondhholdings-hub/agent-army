# Phase 3: Knowledge Base - Research

**Researched:** 2026-02-11
**Domain:** Vector search, agentic RAG, document ingestion, knowledge management, conversation history
**Confidence:** HIGH

## Summary

This research covers the knowledge foundation that agents will query -- product knowledge, sales methodologies, regional nuances, and conversation history. The architecture centers on **Qdrant** as the tenant-scoped vector database with hybrid search (dense + BM25 sparse), **LangChain document loaders and text splitters** for the ingestion pipeline, and an **agentic RAG pattern built on LangGraph** for query decomposition, multi-source retrieval, and synthesis.

The existing Phase 2 infrastructure provides the foundation: pgvector-backed `LongTermMemory` for agent memory, `LangGraph AsyncPostgresSaver` for session persistence, `LiteLLM Router` for embedding generation, and the `ContextManager` orchestrating three-tier context. Phase 3 builds a dedicated knowledge layer on top of this -- Qdrant handles the high-volume, metadata-rich knowledge base (products, methodologies, positioning), while pgvector continues serving agent-learned memories. The two systems complement each other: Qdrant for curated knowledge with rich metadata filtering, pgvector for organic agent memories with simple semantic search.

Key architectural decisions from CONTEXT.md are locked: per-product knowledge organization with feature-level chunks, four metadata tag types (product category, buyer persona, sales stage, region), hybrid search (semantic + keyword), agentic RAG with query decomposition, and support for all input formats (PDF, Word, Markdown, JSON, CSV, URLs). The research validates these decisions and provides specific implementation guidance.

**Primary recommendation:** Use Qdrant (v1.16.3 server / v1.16.2 client) with payload-based multitenancy (`is_tenant=true` on `tenant_id` field), hybrid search via dense embeddings (text-embedding-3-small through LiteLLM) + BM25 sparse vectors (Qdrant server-side), and Reciprocal Rank Fusion for result merging. Build the ingestion pipeline with LangChain document loaders + `RecursiveCharacterTextSplitter` (512 tokens, 15% overlap) as the default chunking strategy, with `MarkdownHeaderTextSplitter` for structured documents. Implement agentic RAG as a LangGraph graph with retriever tools, document grading, and query rewriting.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| qdrant-client | >=1.16.2 | Vector database client (async) | First-class multitenancy with `is_tenant`, hybrid search (dense + BM25), server-side inference, Query API with prefetch. Python 3.10+. |
| langchain-text-splitters | >=1.1.0 | Document chunking | RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter, SemanticChunker. Battle-tested in production RAG systems. |
| langchain-community | >=latest | Document loaders | PyPDFLoader, Docx2txtLoader, UnstructuredMarkdownLoader, CSVLoader, JSONLoader, WebBaseLoader. Extensive format coverage. |
| langchain-qdrant | >=1.1.0 | LangChain-Qdrant integration | QdrantVectorStore for LangChain-native vector operations. Optional but useful for standardized retrieval interface. |
| langgraph | >=1.0.8 | Agentic RAG graph | Already installed (Phase 2). `@tool` decorator for retriever tools, `ToolNode` for retrieval execution, conditional edges for grading/rewriting. |
| litellm | >=1.60+ | Embedding generation | Already installed (Phase 1). `aembedding()` for async embedding via `text-embedding-3-small`. Provider-agnostic. |
| fastembed | >=0.7.4 | Local embeddings (optional) | ONNX-based local embedding generation. Useful for development without API costs. Supports dense, sparse, and late-interaction models. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| docling | >=2.73.0 | Advanced document parsing | When PDF/DOCX require layout understanding, table extraction, or OCR. More capable than basic loaders for complex documents. |
| unstructured | >=0.18.32 | Universal document processing | When ingesting diverse formats (EPUB, RTF, email, images). Heavier dependency but broadest format coverage. |
| pypdf | >=latest | PDF text extraction | Already a LangChain dependency. Lightweight PDF parsing for simple PDFs without complex layouts. |
| python-docx | >=latest | DOCX parsing | Direct Word document parsing. LangChain's Docx2txtLoader wraps this. |
| httpx | >=0.27+ | Web content fetching | Already installed (Phase 1). Async HTTP client for URL-based ingestion. |
| watchfiles | >=1.0+ | File system watching | Auto-sync ingestion trigger. Watches folders for new/changed documents. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Qdrant | Pinecone | Managed-only, no self-hosting. Namespace isolation simpler but less flexible. Vendor lock-in. Qdrant's tiered multitenancy and BM25 builtin are stronger for this use case. |
| Qdrant | pgvector only | Already in stack but lacks rich payload filtering, hybrid search, and multitenancy features. pgvector is fine for agent memories but insufficient for the full knowledge base with metadata-driven retrieval. |
| langchain-text-splitters | chonkie | Lightweight alternative but smaller community. LangChain splitters are the ecosystem standard with broader testing. |
| langchain-text-splitters | semchunk | Pure semantic chunking. Good for meaning-based splits but slower due to embedding computation per sentence. Use as a secondary strategy for high-value content. |
| docling | unstructured | Unstructured has broader format support but is heavier (larger dependencies). Docling is better for PDF/DOCX with layout understanding. Choose based on content types being ingested. |
| LiteLLM embeddings | fastembed local | LiteLLM requires API calls and costs money. fastembed runs locally and is free but limited to its model catalog. Use fastembed for development, LiteLLM for production. |

**Installation:**
```bash
pip install qdrant-client>=1.16.2 langchain-text-splitters>=1.1.0 langchain-community langchain-qdrant>=1.1.0 fastembed>=0.7.4 docling watchfiles
```

## Architecture Patterns

### Recommended Project Structure
```
src/app/
├── knowledge/                    # Knowledge base service (NEW - Phase 3)
│   ├── __init__.py
│   ├── store.py                 # KnowledgeStore -- Qdrant wrapper with tenant isolation
│   ├── schemas.py               # KnowledgeChunk, KnowledgeMetadata Pydantic models
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── pipeline.py          # IngestionPipeline -- orchestrates load→chunk→embed→store
│   │   ├── loaders.py           # Document loader factory (PDF, Word, Markdown, CSV, JSON, URL)
│   │   ├── chunkers.py          # Chunking strategy factory (recursive, markdown-header, semantic)
│   │   └── validators.py        # Content validation (format, size, duplicate detection)
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── rag.py               # AgenticRAGPipeline -- LangGraph graph for query→retrieve→grade→synthesize
│   │   ├── tools.py             # Retriever tools (@tool decorated) for agent consumption
│   │   ├── reranker.py          # Re-ranking logic (metadata filtering + optional LLM re-rank)
│   │   └── decomposer.py        # Query decomposition (break complex queries into sub-queries)
│   ├── methodology/
│   │   ├── __init__.py
│   │   ├── library.py           # MethodologyLibrary -- structured framework storage and retrieval
│   │   └── schemas.py           # MEDDIC, BANT, TAS framework Pydantic models
│   ├── conversation/
│   │   ├── __init__.py
│   │   ├── history.py           # ConversationHistory -- cross-session, cross-channel persistence
│   │   └── search.py            # Conversation search (what was discussed previously)
│   └── versioning/
│       ├── __init__.py
│       └── tracker.py           # KnowledgeVersionTracker -- version snapshots and change tracking
├── context/                      # (existing from Phase 2 -- extend)
│   ├── memory.py                # LongTermMemory (pgvector -- agent memories, keep as-is)
│   └── manager.py               # ContextManager (extend to include knowledge retrieval)
└── services/
    └── llm.py                   # LLMService (existing -- used for embeddings via litellm.aembedding)
```

### Pattern 1: Qdrant Multi-Tenant Collection with Hybrid Search

**What:** A single Qdrant collection per embedding model, with payload-based tenant isolation using `is_tenant=true`. Hybrid search combines dense vectors (semantic) and BM25 sparse vectors (keyword), merged via Reciprocal Rank Fusion (RRF).

**When to use:** Every knowledge base query. All product knowledge, methodology content, and positioning data lives in Qdrant with tenant-scoped access.

**Example:**
```python
# Source: Qdrant official docs (https://qdrant.tech/documentation/guides/multitenancy/)
# Source: Qdrant hybrid search docs (https://qdrant.tech/documentation/advanced-tutorials/reranking-hybrid-search/)
from qdrant_client import AsyncQdrantClient, models

async def setup_knowledge_collection(client: AsyncQdrantClient):
    """Create the knowledge base collection with hybrid search support."""
    await client.create_collection(
        collection_name="knowledge_base",
        vectors_config={
            "dense": models.VectorParams(
                size=1536,  # text-embedding-3-small dimensions
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "bm25": models.SparseVectorParams(
                modifier=models.Modifier.IDF,
            ),
        },
        # Optimize HNSW for per-tenant indexing
        hnsw_config=models.HnswConfigDiff(
            payload_m=16,  # Build per-tenant indexes
            m=0,           # Disable global index (all queries filter by tenant)
        ),
    )

    # Create tenant isolation index
    await client.create_payload_index(
        collection_name="knowledge_base",
        field_name="tenant_id",
        field_schema=models.KeywordIndexParams(
            type=models.KeywordIndexType.KEYWORD,
            is_tenant=True,
        ),
    )

    # Create metadata indexes for filtered retrieval
    for field in ["product_category", "buyer_persona", "sales_stage", "region"]:
        await client.create_payload_index(
            collection_name="knowledge_base",
            field_name=field,
            field_schema=models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD,
            ),
        )
```

### Pattern 2: Tenant-Scoped Hybrid Search with Metadata Filtering

**What:** Every search query is scoped to a tenant via mandatory `tenant_id` filter. Additional metadata filters (product_category, buyer_persona, sales_stage, region) narrow results to context-appropriate content.

**When to use:** All retrieval operations. Agent in Discovery stage with Executive buyer gets Executive-focused discovery content.

**Example:**
```python
# Source: Qdrant query API docs + hybrid search tutorial
async def hybrid_search(
    client: AsyncQdrantClient,
    tenant_id: str,
    query_text: str,
    query_embedding: list[float],
    metadata_filters: dict | None = None,
    limit: int = 10,
) -> list:
    """Hybrid search with dense + BM25 sparse vectors, tenant-scoped."""
    # Build tenant + metadata filter
    must_conditions = [
        models.FieldCondition(
            key="tenant_id",
            match=models.MatchValue(value=tenant_id),
        ),
    ]
    if metadata_filters:
        for key, value in metadata_filters.items():
            must_conditions.append(
                models.FieldCondition(
                    key=key,
                    match=models.MatchValue(value=value),
                )
            )

    query_filter = models.Filter(must=must_conditions)

    # Hybrid search: dense + BM25, merged via RRF
    results = await client.query_points(
        collection_name="knowledge_base",
        prefetch=[
            # Dense (semantic) search
            models.Prefetch(
                query=query_embedding,
                using="dense",
                limit=20,
                filter=query_filter,
            ),
            # Sparse (BM25 keyword) search -- server-side embedding
            models.Prefetch(
                query=models.Document(
                    text=query_text,
                    model="Qdrant/bm25",
                ),
                using="bm25",
                limit=20,
                filter=query_filter,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    return results.points
```

### Pattern 3: Agentic RAG Pipeline with LangGraph

**What:** A LangGraph graph that receives a query, decides whether to retrieve, grades retrieved documents for relevance, rewrites the query if needed, and generates a grounded answer. Complex queries are decomposed into sub-queries that run as parallel retrieval operations.

**When to use:** Every agent knowledge query. The agent calls the retriever tool, and the RAG pipeline handles decomposition, retrieval, grading, and synthesis.

**Example:**
```python
# Source: LangGraph agentic RAG docs (https://docs.langchain.com/oss/python/langgraph/agentic-rag)
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.tools import tool

@tool
def retrieve_knowledge(query: str, product_category: str = None,
                       buyer_persona: str = None, sales_stage: str = None,
                       region: str = None) -> str:
    """Search the knowledge base for product, methodology, or positioning information.

    Args:
        query: The search query.
        product_category: Filter by product (Monetization, Charging, Billing).
        buyer_persona: Filter by audience (Technical, Business, Executive).
        sales_stage: Filter by sales stage (Discovery, Demo, Negotiation, Implementation).
        region: Filter by region (APAC, EMEA, Americas).
    """
    # Build metadata filters from non-None arguments
    filters = {}
    if product_category:
        filters["product_category"] = product_category
    if buyer_persona:
        filters["buyer_persona"] = buyer_persona
    if sales_stage:
        filters["sales_stage"] = sales_stage
    if region:
        filters["region"] = region

    results = knowledge_store.search(
        tenant_id=get_current_tenant().tenant_id,
        query=query,
        metadata_filters=filters,
        limit=10,
    )
    return "\n\n---\n\n".join([r.payload["content"] for r in results])

def generate_query_or_respond(state: MessagesState):
    """Decide whether to retrieve or respond directly."""
    response = model.bind_tools([retrieve_knowledge]).invoke(state["messages"])
    return {"messages": [response]}

def grade_documents(state: MessagesState):
    """Grade retrieved documents for relevance. Route to generate or rewrite."""
    # Check if retrieved content is relevant to the query
    last_message = state["messages"][-1]
    if is_relevant(last_message):
        return "generate_answer"
    return "rewrite_question"

def rewrite_question(state: MessagesState):
    """Rewrite the query for better retrieval results."""
    # LLM reformulates the query based on what was retrieved
    response = model.invoke([
        {"role": "system", "content": "Rewrite the query to improve retrieval."},
        *state["messages"],
    ])
    return {"messages": [response]}

def generate_answer(state: MessagesState):
    """Generate answer grounded in retrieved documents."""
    # Synthesize answer from retrieved content
    response = model.invoke([
        {"role": "system", "content": "Answer based ONLY on the retrieved content. Cite sources."},
        *state["messages"],
    ])
    return {"messages": [response]}

# Assemble the agentic RAG graph
workflow = StateGraph(MessagesState)
workflow.add_node(generate_query_or_respond)
workflow.add_node("retrieve", ToolNode([retrieve_knowledge]))
workflow.add_node(rewrite_question)
workflow.add_node(generate_answer)

workflow.add_edge(START, "generate_query_or_respond")
workflow.add_conditional_edges(
    "generate_query_or_respond",
    tools_condition,
    {"tools": "retrieve", END: END},
)
workflow.add_conditional_edges("retrieve", grade_documents)
workflow.add_edge("generate_answer", END)
workflow.add_edge("rewrite_question", "generate_query_or_respond")

rag_graph = workflow.compile()
```

### Pattern 4: Document Ingestion Pipeline

**What:** A pipeline that accepts documents in any format, parses them into text, chunks them with appropriate strategies, generates embeddings, attaches metadata, and stores in Qdrant. Supports both manual upload and auto-sync.

**When to use:** Adding new product knowledge, updating methodology content, ingesting documents from ESW acquisitions.

**Example:**
```python
# Source: LangChain docs (loaders, splitters) + Qdrant upsert patterns
from langchain_community.document_loaders import (
    PyPDFLoader, Docx2txtLoader, CSVLoader, JSONLoader, WebBaseLoader,
)
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter,
)
import uuid
from datetime import datetime, timezone

class IngestionPipeline:
    """Orchestrates document ingestion: load -> chunk -> embed -> store."""

    def __init__(self, knowledge_store, llm_service):
        self._store = knowledge_store
        self._llm = llm_service
        self._default_splitter = RecursiveCharacterTextSplitter(
            chunk_size=512,
            chunk_overlap=77,  # ~15% overlap
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        self._markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "header_1"),
                ("##", "header_2"),
                ("###", "header_3"),
            ],
            strip_headers=False,
        )

    async def ingest_document(
        self,
        tenant_id: str,
        file_path: str,
        metadata: dict,
        version: str | None = None,
    ) -> list[str]:
        """Ingest a document into the knowledge base.

        Steps:
        1. Load document based on file type
        2. Chunk with appropriate strategy
        3. Generate embeddings
        4. Store in Qdrant with metadata
        """
        # Step 1: Load
        loader = self._get_loader(file_path)
        documents = loader.load()

        # Step 2: Chunk
        if file_path.endswith(".md"):
            # Markdown: split by headers first, then by size
            header_splits = self._markdown_splitter.split_text(
                documents[0].page_content
            )
            chunks = self._default_splitter.split_documents(header_splits)
        else:
            chunks = self._default_splitter.split_documents(documents)

        # Step 3 & 4: Embed and store
        point_ids = []
        for chunk in chunks:
            # Generate embedding via LiteLLM
            embedding = await self._generate_embedding(chunk.page_content)

            point_id = str(uuid.uuid4())
            payload = {
                "tenant_id": tenant_id,
                "content": chunk.page_content,
                "source_file": file_path,
                "chunk_index": chunks.index(chunk),
                "version": version or datetime.now(timezone.utc).isoformat(),
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                **metadata,  # product_category, buyer_persona, sales_stage, region
                # Preserve any header metadata from markdown splitting
                **chunk.metadata,
            }

            await self._store.upsert_point(
                point_id=point_id,
                embedding=embedding,
                text=chunk.page_content,  # For BM25 server-side indexing
                payload=payload,
            )
            point_ids.append(point_id)

        return point_ids

    def _get_loader(self, file_path: str):
        """Factory for document loaders based on file type."""
        if file_path.endswith(".pdf"):
            return PyPDFLoader(file_path)
        elif file_path.endswith(".docx"):
            return Docx2txtLoader(file_path)
        elif file_path.endswith(".csv"):
            return CSVLoader(file_path)
        elif file_path.endswith(".json"):
            return JSONLoader(file_path, jq_schema=".", text_content=False)
        elif file_path.startswith("http"):
            return WebBaseLoader(file_path)
        else:
            # Default: treat as plain text / markdown
            from langchain_community.document_loaders import TextLoader
            return TextLoader(file_path)
```

### Pattern 5: Methodology Library with Structured + Text Storage

**What:** Sales methodologies (MEDDIC, BANT, TAS) stored as both structured Pydantic models (for programmatic querying by field, stage, buyer type) and embedded text documents (for semantic search). Supports all four query patterns from CONTEXT.md.

**When to use:** Agent needs qualification guidance, framework steps, or scenario-specific methodology advice.

**Example:**
```python
# Structured methodology models
from pydantic import BaseModel, Field

class FrameworkStep(BaseModel):
    """A single step in a sales methodology framework."""
    name: str
    description: str
    questions: list[str]  # Discovery questions for this step
    signals: list[str]    # What to look for in customer responses
    next_actions: list[str]

class QualificationCriteria(BaseModel):
    """A qualification criterion (e.g., Budget in BANT)."""
    name: str
    definition: str
    assessment_questions: list[str]
    scoring_rubric: dict[str, str]  # score -> description
    examples: list[dict]  # good_example, bad_example pairs

class SalesMethodology(BaseModel):
    """Complete sales methodology framework."""
    name: str  # "MEDDIC", "BANT", "TAS"
    description: str
    applicable_stages: list[str]  # ["Discovery", "Qualification"]
    applicable_buyer_types: list[str]  # ["Technical", "Executive"]
    steps: list[FrameworkStep]
    criteria: list[QualificationCriteria]
    decision_tree: dict  # Scenario -> recommended approach
    examples: list[dict]  # Real deal scenarios with framework applied

class MethodologyLibrary:
    """Structured + semantic access to sales methodology frameworks."""

    async def query_by_situation(self, deal_context: dict) -> list:
        """Describe a deal situation, get applicable methodology guidance."""
        # Semantic search over methodology text in Qdrant
        ...

    async def query_by_stage(self, sales_stage: str) -> list:
        """Get methodology guidance for a specific sales stage."""
        # Metadata filter: sales_stage == stage
        ...

    async def query_by_buyer_type(self, buyer_type: str) -> list:
        """Get methodology guidance for a specific buyer type."""
        # Metadata filter: buyer_persona == buyer_type
        ...

    async def query_by_name(self, framework_name: str) -> SalesMethodology:
        """Direct lookup of a specific framework by name."""
        # Exact match on framework name in structured storage
        ...
```

### Pattern 6: Conversation History with Cross-Session/Channel Retrieval

**What:** Conversation history persists across sessions and channels. Each message is stored with channel metadata (email, chat, meeting), session/thread IDs, and timestamps. Agents can search what was discussed previously across any channel.

**When to use:** Agent preparing for a meeting needs to recall what was discussed in a previous email thread. Agent in chat needs context from a prior phone call.

**Example:**
```python
# Conversation history extends the existing Phase 2 session store
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import uuid

class ConversationMessage(BaseModel):
    """A single message in conversation history."""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    account_id: str | None = None      # Customer account
    deal_id: str | None = None          # Associated deal
    channel: str                        # "email" | "chat" | "meeting" | "phone"
    session_id: str                     # Thread/session within channel
    role: str                           # "agent" | "customer" | "internal"
    content: str
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ConversationHistory:
    """Cross-session, cross-channel conversation persistence and retrieval.

    Stores conversation messages in Qdrant with embeddings for semantic
    search. Supports recall across sessions and channels.
    """

    async def store_message(self, message: ConversationMessage) -> str:
        """Store a conversation message with embedding for future retrieval."""
        embedding = await self._generate_embedding(message.content)
        # Store in Qdrant with full metadata for filtering
        await self._qdrant.upsert(
            collection_name="conversations",
            points=[models.PointStruct(
                id=message.message_id,
                vector={"dense": embedding},
                payload={
                    "tenant_id": message.tenant_id,
                    "account_id": message.account_id,
                    "deal_id": message.deal_id,
                    "channel": message.channel,
                    "session_id": message.session_id,
                    "role": message.role,
                    "content": message.content,
                    "timestamp": message.timestamp.isoformat(),
                    **message.metadata,
                },
            )],
        )
        return message.message_id

    async def search_history(
        self,
        tenant_id: str,
        query: str,
        account_id: str | None = None,
        deal_id: str | None = None,
        channel: str | None = None,
        limit: int = 20,
    ) -> list:
        """Search conversation history across sessions and channels."""
        # Semantic search with optional account/deal/channel filters
        ...

    async def get_session_messages(
        self, tenant_id: str, session_id: str
    ) -> list:
        """Get all messages in a specific session, ordered by time."""
        # Scroll with filter on session_id, ordered by timestamp
        ...
```

### Anti-Patterns to Avoid

- **Separate Qdrant collection per tenant:** Creates massive resource overhead. Use a single collection with payload-based `is_tenant` partitioning. Qdrant docs explicitly recommend this.
- **Fixed-size chunking without overlap:** Breaks sentences and concepts mid-thought. Use `RecursiveCharacterTextSplitter` with 10-20% overlap to maintain context at boundaries.
- **Embedding entire documents as single vectors:** Retrieval quality degrades with large chunks. Feature-level chunking (512 tokens) enables precise retrieval. The decision to use feature-level granularity is correct.
- **Skipping BM25 for keyword search:** Semantic search alone misses exact terminology matches. "MEDDIC" as a semantic query might not find MEDDIC content as reliably as a keyword match. Hybrid search catches both.
- **Ingesting without metadata:** Knowledge without metadata tags cannot be filtered by context (buyer persona, sales stage). Every chunk must carry the four metadata types defined in CONTEXT.md.
- **Querying without tenant_id filter:** Every Qdrant query MUST include `tenant_id` in the filter. Missing this filter exposes cross-tenant data. This is the #1 security requirement.
- **Re-embedding on every query:** Cache frequently-used query embeddings. The same question ("What are our pricing tiers?") generates the same embedding every time.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PDF text extraction | Custom pypdf wrapper with layout detection | `PyPDFLoader` (simple) or `docling` (complex layouts) | PDF parsing has hundreds of edge cases (scanned pages, multi-column, tables, headers/footers). Libraries handle them. |
| Text chunking | Custom string splitting by character count | `RecursiveCharacterTextSplitter` | Respects paragraph/sentence boundaries, configurable overlap, language-aware splitting. Research shows 85-89% recall. |
| BM25 sparse vectors | Client-side TF-IDF computation | Qdrant server-side BM25 (since v1.15.2) | Qdrant computes IDF automatically on the server. No need to manage vocabulary or term frequencies client-side. |
| Hybrid search result merging | Custom score normalization and merging | Qdrant's `FusionQuery(fusion=Fusion.RRF)` | Reciprocal Rank Fusion is the standard merging algorithm. Qdrant implements it natively with configurable `k` parameter (since v1.16.0). |
| Document deduplication | Custom hash-based dedup | Qdrant point IDs + content hashing | Use deterministic point IDs (hash of tenant_id + source_file + chunk_index) to prevent duplicates on re-ingestion. |
| Embedding generation | Custom model hosting | `litellm.aembedding()` | Already in stack. Supports text-embedding-3-small (OpenAI), Cohere, Voyage, etc. through unified API. |
| Query decomposition | Custom regex/rule-based splitting | LLM-based decomposition in agentic RAG graph | Complex queries need semantic understanding to decompose. "Compare SaaS vs usage-based pricing across regions" requires LLM to identify the sub-queries. |
| Content versioning | Custom file-based version tracking | Qdrant payload `version` field + `ingested_at` timestamp + point overwrite | Store version metadata in payload. On update, delete old points and insert new ones. Query historical versions via timestamp filter. |

**Key insight:** The knowledge base stack is mature -- Qdrant handles vector storage, hybrid search, and multitenancy natively. LangChain handles document loading and chunking. LangGraph handles the agentic retrieval pipeline. The custom code should focus on the domain-specific logic: metadata tagging rules, methodology structuring, cross-reference linking, and context-appropriate retrieval filtering.

## Common Pitfalls

### Pitfall 1: Qdrant Local Mode Limitations vs Production

**What goes wrong:** Development uses Qdrant local mode (`:memory:` or `path=...`), but some features behave differently -- particularly server-side BM25 inference which requires the Qdrant server.

**Why it happens:** The qdrant-client local mode runs an embedded Rust engine in Python. It supports most features but server-side inference (the `Document` query type) requires the full Qdrant server.

**How to avoid:** For development without Docker: use Qdrant local mode (`QdrantClient(path="./qdrant_data")`) for dense vector operations and testing. Generate BM25 sparse vectors client-side using `fastembed` with the SPLADE model. For integration testing with hybrid search: use Qdrant Cloud free tier (1GB). For production: use Qdrant Cloud or a self-hosted Qdrant server via Docker on CI/production hosts.

**Warning signs:** Tests pass locally but hybrid search returns different results in production. BM25 queries returning empty results in local mode.

### Pitfall 2: Chunk Size Too Large or Too Small

**What goes wrong:** Large chunks (>1000 tokens) cause "lost in the middle" problems -- the LLM ignores content in the middle of long chunks. Small chunks (<100 tokens) lose context -- a feature description split across 3 chunks returns incomplete information.

**Why it happens:** No one-size-fits-all chunk size. The optimal size depends on content type and retrieval pattern.

**How to avoid:** Start with 512 tokens, 15% overlap (77 tokens) as the default. For technical documentation: 256-512 tokens with 20% overlap (higher precision). For narrative content (case studies, value props): 512-800 tokens with 12.5% overlap (preserve story flow). For structured data (pricing tables, feature lists): chunk at the logical unit level (one feature per chunk, one pricing tier per chunk). Benchmark with actual queries against actual content.

**Warning signs:** Retrieval returning long chunks where the answer is buried in the middle. Retrieval returning fragments that lack necessary context.

### Pitfall 3: Missing Cross-References Between Related Chunks

**What goes wrong:** "Prepaid credits" chunk is retrieved but the related "Usage tracking API" and "Billing rules" chunks are not, leading to incomplete answers.

**Why it happens:** Semantic search finds the most similar chunks to the query, but related chunks may not be semantically similar to the query -- they are similar to each other.

**How to avoid:** Implement explicit cross-references as a `related_chunks` field in the payload. During ingestion, identify related content (same feature, same product area) and store their IDs. During retrieval, after the initial search, fetch 1-2 related chunks per result. This is the "graph RAG" enhancement to standard vector retrieval.

**Warning signs:** Agent responses that mention a feature but miss critical implementation details or pricing context. Users asking follow-up questions for information that was in related but unretrieved chunks.

### Pitfall 4: Stale Knowledge After Updates

**What goes wrong:** Product pricing changes but the old pricing chunks remain in Qdrant. The agent retrieves both old and new pricing, generating conflicting information.

**Why it happens:** No versioning or cleanup during content updates. New chunks are added but old ones are not removed.

**How to avoid:** Use deterministic point IDs based on content identity: `hash(tenant_id + source_file + section_path)`. On re-ingestion, existing points with the same source are deleted before new ones are inserted. Store `version` and `ingested_at` in payload for auditability. For the locked versioning decision: maintain historical snapshots by storing `valid_from` and `valid_until` dates in the payload, and filtering by date during retrieval.

**Warning signs:** Agent responses containing contradictory information. Customers receiving outdated pricing.

### Pitfall 5: Query Decomposition Loops

**What goes wrong:** The agentic RAG pipeline decomposes a query, retrieves documents, grades them as irrelevant, rewrites the query, retrieves again, grades again as irrelevant, and loops indefinitely.

**Why it happens:** No maximum iteration limit on the rewrite-retrieve-grade cycle. Overly strict relevance grading. Query that genuinely has no matching content in the knowledge base.

**How to avoid:** Set a maximum of 2 rewrite iterations. After 2 failed retrievals, return a "no relevant knowledge found" response with the query decomposition for debugging. Use a lenient grading threshold -- some relevant content is better than no content. Log all decomposition/grading decisions for observability.

**Warning signs:** High latency on knowledge queries. Token costs spiking per query. Circular patterns in Langfuse traces.

### Pitfall 6: Conversation History Growing Unbounded

**What goes wrong:** Every message across every channel is stored with embeddings. After months of operation, the conversations collection has millions of points, query latency degrades, and storage costs increase.

**Why it happens:** No retention policy. No summarization. Raw messages stored indefinitely.

**How to avoid:** Implement tiered retention: keep raw messages for 90 days, then compress to summaries. Use conversation summaries (LLM-generated) as the long-term representation. Store summaries in Qdrant with the same account/deal metadata for retrieval. Archive raw messages to PostgreSQL (cheaper storage) for compliance. Index only the summary in Qdrant for search.

**Warning signs:** Conversation collection size growing linearly with time. Query latency increasing month-over-month. Qdrant storage costs spiking.

## Code Examples

Verified patterns from official sources:

### Qdrant Async Client Initialization (Development vs Production)
```python
# Source: qdrant-client docs (https://github.com/qdrant/qdrant-client)
from qdrant_client import AsyncQdrantClient

def create_qdrant_client(settings) -> AsyncQdrantClient:
    """Create Qdrant client based on environment.

    Development: Local mode with persistent storage (no server needed).
    Production: Connect to Qdrant Cloud or self-hosted server.
    """
    if settings.ENVIRONMENT == "development":
        # Local mode -- runs embedded Qdrant engine in Python process
        # Supports most features except server-side inference
        return AsyncQdrantClient(path="./qdrant_data")
    elif settings.QDRANT_URL:
        # Production -- connect to Qdrant server
        return AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
        )
    else:
        # Fallback: in-memory for testing
        return AsyncQdrantClient(":memory:")
```

### Upsert Knowledge Chunk with Dense + BM25 Vectors
```python
# Source: Qdrant hybrid search docs + qdrant-client upsert examples
import litellm

async def upsert_knowledge_chunk(
    client: AsyncQdrantClient,
    chunk_id: str,
    content: str,
    metadata: dict,
) -> None:
    """Store a knowledge chunk with dense embedding.

    BM25 sparse vectors are generated server-side when using
    Qdrant server (production). For local development, generate
    sparse vectors client-side with fastembed.
    """
    # Generate dense embedding via LiteLLM
    response = await litellm.aembedding(
        model="text-embedding-3-small",
        input=[content],
    )
    dense_vector = response.data[0]["embedding"]

    await client.upsert(
        collection_name="knowledge_base",
        points=[
            models.PointStruct(
                id=chunk_id,
                vector={
                    "dense": dense_vector,
                },
                payload={
                    "content": content,
                    **metadata,
                },
            ),
        ],
    )
```

### RecursiveCharacterTextSplitter with Metadata Preservation
```python
# Source: LangChain text splitters docs
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader

# Load PDF
loader = PyPDFLoader("skyvera_monetization_platform.pdf")
documents = loader.load()

# Split with overlap for context preservation
splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,       # ~512 tokens
    chunk_overlap=77,     # ~15% overlap
    separators=["\n\n", "\n", ". ", " ", ""],
    length_function=len,  # Character count (approximate; use tiktoken for exact)
)

chunks = splitter.split_documents(documents)

# Each chunk preserves source metadata
for chunk in chunks:
    print(f"Source: {chunk.metadata['source']}, Page: {chunk.metadata.get('page')}")
    print(f"Content: {chunk.page_content[:100]}...")
```

### Markdown Ingestion with Header-Based Splitting
```python
# Source: LangChain MarkdownHeaderTextSplitter docs
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# Two-stage splitting for markdown: headers first, then size
def split_markdown(content: str) -> list:
    """Split markdown by headers, then enforce size limits."""
    # Stage 1: Split by markdown headers
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "product"),
            ("##", "feature"),
            ("###", "detail"),
        ],
        strip_headers=False,  # Keep headers in content for context
    )
    header_splits = header_splitter.split_text(content)

    # Stage 2: Enforce chunk size limits
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=512,
        chunk_overlap=77,
    )
    final_chunks = size_splitter.split_documents(header_splits)

    # Each chunk has header metadata: {"product": "Monetization", "feature": "Prepaid Credits"}
    return final_chunks
```

### Knowledge Version Tracking
```python
# Source: Composite pattern for content versioning
from datetime import datetime, timezone
import hashlib

class KnowledgeVersionTracker:
    """Track knowledge versions for historical snapshots."""

    def generate_chunk_id(
        self, tenant_id: str, source_file: str, chunk_index: int
    ) -> str:
        """Deterministic ID for deduplication on re-ingestion."""
        content = f"{tenant_id}:{source_file}:{chunk_index}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def ingest_versioned(
        self,
        tenant_id: str,
        source_file: str,
        chunks: list,
        version_label: str,
    ) -> None:
        """Ingest with version tracking.

        Old versions are marked with valid_until but NOT deleted,
        supporting historical queries ("pricing when they signed").
        """
        now = datetime.now(timezone.utc).isoformat()

        # Mark previous version as superseded
        await self._mark_superseded(tenant_id, source_file, now)

        # Ingest new version
        for i, chunk in enumerate(chunks):
            chunk_id = self.generate_chunk_id(tenant_id, source_file, i)
            await self._store.upsert(
                chunk_id=chunk_id,
                content=chunk.page_content,
                metadata={
                    "tenant_id": tenant_id,
                    "source_file": source_file,
                    "version": version_label,
                    "valid_from": now,
                    "valid_until": None,  # Current version
                    "is_current": True,
                    **chunk.metadata,
                },
            )

    async def _mark_superseded(
        self, tenant_id: str, source_file: str, superseded_at: str
    ) -> None:
        """Mark all chunks from a source file as superseded."""
        # Scroll through existing points for this source file
        # and update valid_until + is_current
        ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Client-side BM25/TF-IDF | Qdrant server-side BM25 (v1.15.2+) | Mid-2025 | Eliminates client-side vocabulary management. Server computes IDF automatically. |
| Separate dense + sparse collections | Qdrant hybrid prefetch with RRF (Query API) | 2025 | Single query combines dense + sparse results. No client-side merging needed. |
| Collection-per-tenant isolation | Payload-based `is_tenant` with per-tenant HNSW (v1.11+) | 2024-2025 | Single collection, efficient resource usage. Tiered promotion for large tenants (v1.16). |
| Fixed-size text chunking | Recursive + semantic chunking | 2024-2025 | 85-89% recall with RecursiveCharacterTextSplitter at 400-512 tokens. Semantic chunking adds cost but improves for complex documents. |
| Static RAG (query -> retrieve -> generate) | Agentic RAG (decide -> decompose -> retrieve -> grade -> rewrite -> generate) | 2025-2026 | Agent decides when to retrieve, grades quality, rewrites queries. Significantly better for complex multi-part questions. |
| Single embedding model per query | Multi-vector hybrid search (dense + sparse + late-interaction) | 2025-2026 | Dense catches meaning, sparse catches exact terms, late-interaction provides fine-grained re-ranking. |
| LangChain RetrievalQA chain | LangGraph agentic RAG graph | 2025-2026 | LangChain retrieval chains are legacy. LangGraph provides conditional routing, grading, rewriting with full control. |
| Global vector index for all tenants | Per-tenant HNSW indexes (`payload_m=16, m=0`) | Qdrant v1.11+ | Faster queries because each tenant's index is smaller. No cross-tenant index pollution. |

**Deprecated/outdated:**
- **LangChain `RetrievalQA` / `ConversationalRetrievalChain`:** Replaced by LangGraph agentic RAG pattern. LangChain docs themselves say "use LangGraph for retrieval agents."
- **Chroma for multi-tenant:** Not production-ready for multi-tenant isolation. No `is_tenant` equivalent.
- **FAISS for production:** Library, not a database. No persistence, no multi-tenancy, no payload filtering.
- **Client-side BM25 via NLTK/scikit-learn:** Server-side BM25 in Qdrant eliminates this complexity entirely.
- **fastembed as mandatory for BM25:** Since Qdrant v1.15.2, fastembed is no longer required for BM25 -- the server handles it.

## Open Questions

Things that couldn't be fully resolved:

1. **Qdrant Local Mode and BM25**
   - What we know: Qdrant local mode (Python client) supports dense vector operations. Qdrant server-side BM25 requires the full server.
   - What's unclear: Whether qdrant-client local mode supports the `Document` query type for BM25 or if it requires a running server.
   - Recommendation: Use dense-only search in local development (still good for testing). Generate BM25 sparse vectors client-side with fastembed as a fallback. Test hybrid search against Qdrant Cloud free tier or in CI with Docker. This is a development workflow concern, not an architecture concern.

2. **Optimal Chunk Size for Skyvera Product Content**
   - What we know: 512 tokens with 15% overlap is the standard starting point. Research shows 85-89% recall at this size. Feature-level chunking is the locked decision.
   - What's unclear: Whether Skyvera's product documentation (API specs, pricing tables, integration guides) performs better at 256 or 512 tokens.
   - Recommendation: Start with 512 tokens as default. After initial ingestion, evaluate retrieval quality with sample queries. Adjust per content type if needed. The ingestion pipeline should support per-document-type chunk size configuration.

3. **Re-ranking: LLM vs Metadata Filtering vs Cross-Encoder**
   - What we know: This is a Claude's Discretion item. Options: (a) metadata filtering narrows results before/after vector search, (b) LLM re-ranking uses Claude to score relevance, (c) cross-encoder models (e.g., via fastembed reranker) provide fast re-ranking.
   - What's unclear: Whether the precision improvement from LLM re-ranking justifies the latency and cost at 5-10 chunks per query.
   - Recommendation: **Use metadata filtering as the primary precision mechanism** (it is free and instant). The four metadata tags (product_category, buyer_persona, sales_stage, region) should dramatically narrow the result set before vector search. Add cross-encoder re-ranking via fastembed only if retrieval quality is insufficient after metadata filtering. Defer LLM re-ranking -- the cost of an extra LLM call per knowledge query is likely not justified when metadata filtering is well-designed. Re-evaluate after benchmarking.

4. **Conversation History Collection Separation**
   - What we know: Product knowledge goes in the `knowledge_base` collection. Conversation history is different data (shorter, more temporal, different query patterns).
   - What's unclear: Whether conversation history should share the `knowledge_base` collection or have its own `conversations` collection.
   - Recommendation: **Separate collection.** Conversation messages have different embedding patterns, different metadata schemas, different retention policies, and different query patterns than curated knowledge. A separate `conversations` collection with its own HNSW configuration avoids polluting the knowledge index and allows independent scaling/retention.

5. **Docker-less Qdrant for Development**
   - What we know: Docker is not installed on the dev machine (per STATE.md blockers). Qdrant local mode works without Docker.
   - What's unclear: Whether all tests can run effectively with local mode, or if some integration tests need the full server.
   - Recommendation: Use `QdrantClient(path="./qdrant_data")` for development and unit tests. Use `QdrantClient(":memory:")` for isolated test runs. Use Qdrant Cloud free tier for integration tests that need hybrid search. CI/CD runners have Docker and can run the full Qdrant server image.

## Sources

### Primary (HIGH confidence)
- `/websites/qdrant_tech` via Context7 -- Multitenancy guide, hybrid search with prefetch, RRF fusion, `is_tenant` payload index, collection configuration
- `/qdrant/qdrant-client` via Context7 -- AsyncQdrantClient initialization, local mode, upsert, search with filtering, collection creation
- `/websites/langchain_oss_python` via Context7 -- Document loaders (PyPDFLoader, etc.), RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter, RAG indexing overview
- `/websites/langchain_oss_python_langgraph` via Context7 -- Agentic RAG pipeline (generate_query_or_respond, ToolNode, grade_documents, rewrite_question, generate_answer), StateGraph assembly
- https://pypi.org/project/qdrant-client/ -- v1.16.2, Python 3.10+
- https://pypi.org/project/langchain-text-splitters/ -- v1.1.0
- https://pypi.org/project/langchain-qdrant/ -- v1.1.0
- https://pypi.org/project/fastembed/ -- v0.7.4
- https://github.com/qdrant/qdrant/releases -- Qdrant server v1.16.3
- https://qdrant.tech/documentation/guides/multitenancy/ -- Complete multitenancy setup, tiered sharding, `is_tenant`, HNSW config
- https://qdrant.tech/documentation/concepts/inference/ -- Server-side BM25, cloud inference, supported models
- https://qdrant.tech/documentation/guides/installation/ -- Installation methods, local mode, Docker, compilation

### Secondary (MEDIUM confidence)
- https://docs.langchain.com/oss/python/langgraph/agentic-rag -- LangGraph agentic RAG tutorial with code
- https://docs.langchain.com/oss/python/langchain/rag -- LangChain RAG indexing pipeline overview
- https://levelup.gitconnected.com/building-a-scalable-production-grade-agentic-rag-pipeline-1168dcd36260 -- Production agentic RAG patterns
- https://pub.towardsai.net/rag-in-practice-exploring-versioning-observability-and-evaluation-in-production-systems-85dc28e1d9a8 -- RAG versioning and observability
- https://www.regal.ai/blog/rag-playbook-structuring-knowledge-bases -- Knowledge base structuring for RAG
- https://www.kapa.ai/blog/rag-best-practices -- RAG best practices from 100+ teams
- https://www.mongodb.com/company/blog/product-release-announcements/powering-long-term-memory-for-agents-langgraph -- LangGraph long-term memory patterns
- https://docs.langchain.com/oss/python/langgraph/add-memory -- LangGraph memory and checkpointing
- https://pypi.org/project/docling/ -- v2.73.0, document processing
- https://pypi.org/project/unstructured/ -- v0.18.32, universal document processing

### Tertiary (LOW confidence)
- https://medium.com/@yohanesegipratama/build-a-modern-rag-pipeline-in-2026-docling-qdrant-hybrid-bm25-dense-ai-agent -- Single source, modern pipeline pattern (needs validation)
- https://medium.com/@krtarunsingh/goodbye-basic-rag-hello-agents-the-2026-playbook-python-langgraph-llamaindex -- Agentic RAG overview (single source)
- https://www.firecrawl.dev/blog/best-chunking-strategies-rag-2025 -- Chunking strategies comparison
- https://medium.com/@aniruddhyak/the-death-of-sessionless-ai-how-conversation-memory-will-evolve-from-2026-2030 -- Memory evolution trends (forward-looking)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All library versions verified via PyPI. Qdrant multitenancy verified via official docs + Context7. LangChain splitters and loaders verified via Context7. LangGraph agentic RAG verified via official tutorial.
- Architecture (Qdrant multi-tenant + hybrid search): HIGH -- Officially documented pattern with `is_tenant`, HNSW per-tenant config, and hybrid prefetch/RRF. Multiple consistent sources.
- Architecture (agentic RAG pipeline): HIGH -- Official LangGraph tutorial provides the exact pattern. Well-established in the ecosystem.
- Architecture (ingestion pipeline): MEDIUM -- LangChain loaders are well-documented but specific chunking parameters need benchmarking with actual Skyvera content.
- Architecture (conversation history): MEDIUM -- Pattern is well-understood but specific collection design and retention strategy need validation during implementation.
- Architecture (versioning): MEDIUM -- Payload-based versioning is straightforward but the historical snapshot query pattern needs careful implementation.
- Pitfalls: HIGH -- Multitenancy pitfalls from Qdrant docs. Chunking pitfalls from multiple RAG best practices sources. Loop prevention from agentic RAG community experience.

**Research date:** 2026-02-11
**Valid until:** 2026-03-11 (30 days -- Qdrant and LangChain are stable; agentic RAG patterns are established)
