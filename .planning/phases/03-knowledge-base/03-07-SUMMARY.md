---
phase: 03-knowledge-base
plan: 07
subsystem: knowledge-retrieval
tags: [rag, langgraph, query-decomposition, multi-source-retrieval, document-grading, synthesis, citations]

# Dependency graph
requires:
  - phase: 03-01
    provides: "QdrantKnowledgeStore with hybrid search"
  - phase: 03-03
    provides: "IngestionPipeline for knowledge chunks"
  - phase: 03-04
    provides: "ESW product knowledge in Qdrant"
  - phase: 03-05
    provides: "Methodology and regional content in Qdrant"
  - phase: 03-06
    provides: "ConversationStore for conversation history"
provides:
  - "QueryDecomposer for breaking complex queries into source-targeted sub-queries"
  - "MultiSourceRetriever for fetching from products, methodology, regional, and conversations"
  - "ResponseSynthesizer for grounded answers with source citations"
  - "AgenticRAGPipeline orchestrating decompose->retrieve->grade->rewrite->synthesize"
  - "RAGResponse model with answer, sources, sub_queries, iterations, confidence"
affects: [04-sales-agent, 05-deal-workflows, agent-context-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: ["agentic RAG with iterative retrieval", "LLM-based query decomposition", "document grading with fail-open", "citation extraction from [N] patterns", "position-based relevance scoring"]

key-files:
  created:
    - src/knowledge/rag/__init__.py
    - src/knowledge/rag/decomposer.py
    - src/knowledge/rag/retriever.py
    - src/knowledge/rag/synthesizer.py
    - src/knowledge/rag/pipeline.py
    - tests/knowledge/test_rag_pipeline.py
  modified: []

key-decisions:
  - "Separate LLM instances for decomposition, grading, and synthesis to avoid prompt interference"
  - "State machine pattern instead of LangGraph graph compilation for testability and simplicity"
  - "Position-based relevance scoring (decaying 0.1 per rank) for deterministic mock testing"
  - "Fail-open grading: LLM errors assume chunk is relevant (prefer stale data over no data)"
  - "50% relevance threshold for triggering query rewrite"
  - "Max 2 rewrite iterations to prevent infinite loops (per plan specification)"

patterns-established:
  - "MockLLM class with response_map and trigger matching for deterministic LLM testing"
  - "Dedicated LLM fixtures per component to prevent mock response interference"
  - "RetrievedChunk as the universal intermediate representation between retrieval and synthesis"
  - "SubQuery as the decomposition output with source_type routing and metadata filters"

# Metrics
duration: 7min
completed: 2026-02-11
---

# Phase 3 Plan 7: Agentic RAG Pipeline Summary

**Agentic RAG pipeline with query decomposition, multi-source retrieval, document grading, iterative rewriting, and citation-grounded synthesis**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-11T20:09:18Z
- **Completed:** 2026-02-11T20:16:18Z
- **Tasks:** 3 (RED-GREEN-REFACTOR TDD cycle)
- **Files created:** 6

## Accomplishments
- QueryDecomposer breaks complex multi-faceted queries into 2-4 source-targeted sub-queries with metadata filters
- MultiSourceRetriever fetches from knowledge base and conversation store, deduplicates by chunk ID, returns ranked top-k
- ResponseSynthesizer produces LLM-grounded answers with [N] citation extraction and confidence scoring
- AgenticRAGPipeline orchestrates the full flow with document grading and query rewriting (max 2 iterations)
- 23 comprehensive tests all passing with mocked LLM and stores (no external API calls)

## Task Commits

Each task was committed atomically (TDD):

1. **RED: Failing tests** - `263d5a3` (test) - 23 test cases defining expected behavior
2. **GREEN: Implementation** - `6ee50cc` (feat) - All 4 components implemented, all tests pass
3. **REFACTOR: Clean up** - `83cd64d` (refactor) - Extracted position scoring helper, cleaned imports

## Files Created/Modified
- `src/knowledge/rag/__init__.py` - Package exports for all RAG components
- `src/knowledge/rag/decomposer.py` - LLM-based query decomposition with JSON parsing and fallback
- `src/knowledge/rag/retriever.py` - Multi-source retrieval with deduplication and ranking
- `src/knowledge/rag/synthesizer.py` - Answer synthesis with citation extraction and confidence
- `src/knowledge/rag/pipeline.py` - State machine orchestrating decompose->retrieve->grade->synthesize
- `tests/knowledge/test_rag_pipeline.py` - 23 tests covering all components and edge cases

## Decisions Made
- **State machine over LangGraph graph**: Used a Python state machine rather than compiling a LangGraph StateGraph. This provides the same decompose->retrieve->grade->rewrite->synthesize flow but is simpler to test with mocked dependencies. The LangGraph pattern can be adopted later if graph-specific features (checkpointing, streaming) are needed.
- **Separate LLM per component**: Each of decomposer, grading, and synthesis gets its own LLM instance to prevent prompt trigger interference in tests and to allow different model configurations per component in production.
- **Fail-open grading**: When the grading LLM call fails, the chunk is assumed relevant. This prevents LLM outages from blocking all queries (consistent with 02-03 LLM fail-open decision).
- **Position-based scoring**: Relevance scores decay by 0.1 per position in the result list (1.0, 0.9, 0.8...). This provides a simple, deterministic ranking that works well with mock embeddings in tests.
- **Citation extraction via regex**: The synthesizer uses `\[(\d+)\]` regex to find citation references and maps them back to source chunks. This is robust to LLM formatting variations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mock LLM interference between pipeline components**
- **Found during:** GREEN phase (test_full_pipeline_complex failing)
- **Issue:** Shared mock_llm instance caused grading responses to interfere with decomposition during rewrite phase. The synthesizer's response_map matched grading prompts, returning non-JSON to the decomposer.
- **Fix:** Created separate LLM fixtures (decomposer_llm, synthesizer_llm, grading_llm) with appropriate default responses for each role.
- **Files modified:** tests/knowledge/test_rag_pipeline.py
- **Verification:** All 23 tests pass including test_full_pipeline_complex
- **Committed in:** 6ee50cc (GREEN phase commit)

---

**Total deviations:** 1 auto-fixed (1 bug in test setup)
**Impact on plan:** Test fixture design issue, not a code architecture change. No scope creep.

## Issues Encountered
None beyond the mock LLM interference noted above.

## User Setup Required
None - no external service configuration required. All tests use mocked LLM and stores.

## Next Phase Readiness
- Phase 3 (Knowledge Base) is now COMPLETE: all 7 plans executed
- RAG pipeline ready for integration into Phase 4 (Sales Agent) for intelligent knowledge queries
- The AgenticRAGPipeline accepts any LLM with an async ainvoke() method, ready for LiteLLM Router integration
- Conversation context support enables agents to include prior discussion history in queries
- Multi-source retrieval covers all knowledge types: products, methodology, regional, conversations

---
*Phase: 03-knowledge-base*
*Completed: 2026-02-11*
