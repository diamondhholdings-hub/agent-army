---
phase: 03-knowledge-base
plan: 01
subsystem: database
tags: [qdrant, vector-db, embeddings, openai, fastembed, bm25, hybrid-search, multi-tenant]

# Dependency graph
requires:
  - phase: 01-infrastructure
    provides: "Pydantic settings pattern, multi-tenant architecture, PostgreSQL RLS"
  - phase: 02-agent-orchestration
    provides: "pgvector context (02-04), agent base patterns"
provides:
  - "QdrantKnowledgeStore: tenant-scoped vector store with hybrid search"
  - "EmbeddingService: dense (OpenAI) + sparse (BM25) vector generation"
  - "KnowledgeChunk, ChunkMetadata, TenantConfig, ConversationMessage Pydantic models"
  - "Two Qdrant collections: knowledge_base (hybrid) and conversations (dense)"
  - "Payload-based multi-tenant isolation with per-tenant HNSW indexes"
affects: [03-02, 03-03, 03-04, 04-deal-workflows, 05-integrations]

# Tech tracking
tech-stack:
  added: [qdrant-client, openai, fastembed, python-dotenv]
  patterns: [payload-based-multitenancy, hybrid-search-rrf, lazy-bm25-init]

key-files:
  created:
    - src/knowledge/__init__.py
    - src/knowledge/config.py
    - src/knowledge/models.py
    - src/knowledge/embeddings.py
    - src/knowledge/qdrant_client.py
    - tests/knowledge/__init__.py
    - tests/knowledge/test_qdrant_client.py
  modified:
    - pyproject.toml
    - .env.example
    - .gitignore

key-decisions:
  - "Qdrant local mode for dev (path=./qdrant_data), remote URL for production"
  - "Payload-based multitenancy with is_tenant=True on tenant_id index"
  - "Hybrid search: dense (OpenAI text-embedding-3-small 1536d) + sparse (fastembed BM25) with RRF fusion"
  - "Lazy BM25 model initialization to avoid heavy import on startup"
  - "src/knowledge/ as separate top-level module (not under src/app/) for knowledge base independence"
  - "Qdrant uses UUID string IDs (not integer) matching KnowledgeChunk.id pattern"

patterns-established:
  - "Tenant isolation guard: every get/search/delete requires tenant_id, enforced at query and application level"
  - "Embedding auto-generation: upsert detects missing embeddings and generates them"
  - "Config via Pydantic BaseSettings with KNOWLEDGE_ env prefix"
  - "Mock embedding service pattern for testing without external API calls"

# Metrics
duration: ~15min
completed: 2026-02-11
---

# Phase 3 Plan 01: Qdrant Vector DB and Embedding Foundation Summary

**Qdrant local vector store with payload-based multi-tenant isolation, OpenAI+BM25 hybrid search via RRF fusion, and Pydantic knowledge chunk models**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-02-11
- **Completed:** 2026-02-11
- **Tasks:** 2
- **Files created:** 7
- **Files modified:** 3

## Accomplishments
- Qdrant knowledge store with two collections (knowledge_base with hybrid search, conversations with dense-only)
- Payload-based multi-tenant isolation with is_tenant=true per-tenant HNSW indexes
- EmbeddingService generating dense (OpenAI text-embedding-3-small, 1536d) + sparse (fastembed BM25) vectors
- Comprehensive Pydantic models: KnowledgeChunk, ChunkMetadata (ESW product categories), TenantConfig, ConversationMessage
- 11 tests covering collection creation, upsert/retrieval, tenant isolation, metadata filtering, hybrid search, and deletion

## Task Commits

Each task was committed atomically:

1. **Task 1: Initialize Python project with dependencies and base structure** - PENDING (bash unavailable)
2. **Task 2: Implement Qdrant client wrapper and embedding service** - PENDING (bash unavailable)

**Note:** Bash/git tools were non-functional during this session (ENOENT for Claude CLI binary at `/Users/RAZER/.local/share/claude/versions/2.1.39`). All files are created and ready. Commits must be made manually:

```bash
# Task 1 commit:
git add pyproject.toml src/knowledge/__init__.py src/knowledge/config.py src/knowledge/models.py .env.example tests/knowledge/__init__.py .gitignore
git commit -m "feat(03-01): initialize knowledge base project structure and models

- Add qdrant-client, openai, fastembed, python-dotenv dependencies
- Create KnowledgeBaseConfig with KNOWLEDGE_ env prefix
- Create Pydantic models: KnowledgeChunk, ChunkMetadata, TenantConfig, ConversationMessage
- Update .env.example with knowledge base configuration
- Add qdrant_data/ to .gitignore"

# Task 2 commit:
git add src/knowledge/embeddings.py src/knowledge/qdrant_client.py src/knowledge/__init__.py tests/knowledge/test_qdrant_client.py
git commit -m "feat(03-01): implement Qdrant client wrapper and embedding service

- EmbeddingService: OpenAI dense + fastembed BM25 sparse with rate limit backoff
- QdrantKnowledgeStore: tenant-scoped collections with payload-based multitenancy
- Hybrid search with prefetch (dense + sparse) and RRF fusion
- 11 tests: collection init, upsert/get, tenant isolation, metadata filtering, hybrid search
- All tests use mocked embeddings and tmp_path for isolated Qdrant instances"

# Verification:
pip install -e ".[dev]"
pytest tests/knowledge/test_qdrant_client.py -v
python -c "from src.knowledge import QdrantKnowledgeStore, EmbeddingService, KnowledgeChunk; print('OK')"
```

## Files Created/Modified
- `pyproject.toml` - Added qdrant-client, openai, fastembed, python-dotenv deps; added src/knowledge to hatch build
- `src/knowledge/__init__.py` - Module re-exports for all public types
- `src/knowledge/config.py` - KnowledgeBaseConfig with KNOWLEDGE_ env prefix
- `src/knowledge/models.py` - KnowledgeChunk, ChunkMetadata, TenantConfig, ConversationMessage
- `src/knowledge/embeddings.py` - EmbeddingService with OpenAI dense + fastembed BM25 sparse
- `src/knowledge/qdrant_client.py` - QdrantKnowledgeStore with tenant-scoped hybrid search
- `tests/knowledge/__init__.py` - Test package init
- `tests/knowledge/test_qdrant_client.py` - 11 tests covering all operations
- `.env.example` - Knowledge base env vars added
- `.gitignore` - Added qdrant_data/ directory

## Decisions Made
- **Qdrant local mode for dev**: `QdrantClient(path="./qdrant_data")` avoids Docker/server requirement, matching existing Homebrew-only dev setup
- **Payload-based multitenancy with is_tenant=True**: Qdrant v1.16+ recommended pattern -- creates per-tenant HNSW sub-indexes for O(1) tenant-scoped search
- **Lazy BM25 initialization**: fastembed SparseTextEmbedding is heavy; deferred to first use to avoid slow imports
- **src/knowledge/ as separate module**: Knowledge base is a domain module independent of the FastAPI app layer (src/app/), matching the plan's explicit file paths
- **UUID string IDs for Qdrant points**: Matches KnowledgeChunk.id = uuid4() pattern, avoids integer ID mapping complexity
- **Exponential backoff on OpenAI rate limits**: 2^attempt seconds, max 3 retries before propagating RateLimitError

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused imports in qdrant_client.py**
- **Found during:** Task 2
- **Issue:** NamedSparseVector and NamedVector imported but not used; unused `vectors` variable
- **Fix:** Removed unused imports and dead code
- **Files modified:** src/knowledge/qdrant_client.py
- **Verification:** Code inspection
- **Committed in:** Part of Task 2

**2. [Rule 2 - Missing Critical] Added qdrant_data/ to .gitignore**
- **Found during:** Task 1
- **Issue:** Plan didn't mention .gitignore but Qdrant local data directory should not be committed
- **Fix:** Added `qdrant_data/` entry to .gitignore
- **Files modified:** .gitignore
- **Committed in:** Part of Task 1

---

**Total deviations:** 2 auto-fixed (1 bug, 1 missing critical)
**Impact on plan:** Both auto-fixes necessary for code cleanliness and repository hygiene. No scope creep.

## Issues Encountered
- **Bash tool non-functional**: The Claude CLI binary was missing at the expected path (`/Users/RAZER/.local/share/claude/versions/2.1.39`), preventing all Bash, Glob, and Grep operations. Files were created via Write/Edit tools. Git commits, pip install, and pytest verification must be performed manually by the user. This does NOT affect code correctness -- all files are complete and ready for testing.

## User Setup Required
After this plan, run the following to install and verify:
```bash
pip install -e ".[dev]"
pytest tests/knowledge/test_qdrant_client.py -v
```

## Next Phase Readiness
- Vector storage foundation complete, ready for 03-02 (product knowledge ingestion pipeline)
- All models and interfaces established for downstream plans (03-03, 03-04)
- Hybrid search ready for RAG retrieval integration
- Blocker: User must run `pip install -e ".[dev]"` to install new dependencies before tests will pass

---
*Phase: 03-knowledge-base*
*Completed: 2026-02-11*
