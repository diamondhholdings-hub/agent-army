# Phase 3: Knowledge Base - Context

**Gathered:** 2026-02-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a tenant-scoped knowledge foundation that agents can query to retrieve:
- Product knowledge (Skyvera offerings, pricing, positioning)
- Sales methodologies (MEDDIC, BANT frameworks)
- Regional nuances
- Conversation history

This phase establishes the retrieval infrastructure and knowledge storage. Agent-specific consumption patterns are in later phases.

</domain>

<decisions>
## Implementation Decisions

### Knowledge Structure
- **Organization:** Per product (each Skyvera product is a separate knowledge unit: Monetization Platform, Charging, Billing, etc.)
- **Granularity:** Feature-level chunks (each capability/feature is self-contained for precise retrieval)
- **Metadata tagging:** Four tag types for filtering:
  - Product category (Monetization, Charging, Billing)
  - Buyer persona (Technical, Business, Executive)
  - Sales stage (Discovery, Demo, Negotiation, Implementation)
  - Region (APAC, EMEA, Americas)
- **Cross-references:** Explicit links between related content (e.g., "Prepaid credits" links to "Usage tracking API", "Billing rules")
- **Pricing structure:** Both structured data (queryable fields for tiers/limits/costs) and natural language docs (context/narratives)
- **Positioning:** Both per-competitor battlecards and per-use-case value props
- **Versioning:** Track knowledge versions over time (historical snapshots for "pricing changed on X date")

### Retrieval Strategy
- **Search type:** Hybrid (semantic + keyword) — catches both meaning-based and exact-match queries
- **Retrieval count:** Top 5-10 chunks per query (balance precision and context)
- **Query decomposition:** Yes — break complex questions into sub-queries (agentic RAG pattern)
- **Re-ranking:** Claude's discretion (decide if LLM re-rank or metadata filtering improves precision enough to justify cost)

### Methodology Storage
- **Format:** Both structured framework (data fields, decision trees, rubrics) and text documents (context/examples)
- **Query methods:** Support all query patterns:
  - By deal situation (describe scenario, get applicable guidance)
  - By sales stage (Discovery → BANT, Negotiation → pricing frameworks)
  - By buyer type (Technical → validation frameworks, Executive → business case)
  - By explicit name (direct request for "MEDDIC qualification checklist")
- **Customization:** Universal methodologies across all tenants/regions (not customized per tenant)
- **Examples:** Include rich examples (real deal scenarios, filled templates, good/bad examples)

### Ingestion Pipeline
- **Input formats:** Accept all: Documents (PDF/Word/Markdown), Structured data (JSON/CSV), Web content (URLs), APIs (CMS/docs platforms)
- **Ingestion trigger:** Both manual upload (admin UI) and auto-sync (watch folders, poll APIs)
- **Validation:** Claude's discretion (determine appropriate validation level based on risk)
- **Updates:** Claude's discretion (design update flow based on version tracking decision)

### Claude's Discretion
- Technical documentation organization (by integration type, user journey, or object/resource)
- Re-ranking approach (LLM vs metadata filters)
- Ingestion validation rules
- Update/versioning workflow details

</decisions>

<specifics>
## Specific Ideas

- Feature-level granularity means each capability (like "prepaid credits" or "usage-based pricing tier") is a self-contained chunk
- Metadata enables context-aware retrieval: agent in Discovery stage with Executive buyer gets Executive-focused discovery content
- Version tracking supports renewal/legacy customer scenarios: "What was our pricing when they signed 2 years ago?"
- Hybrid search catches both exact terms ("MEDDIC") and conceptual matches ("qualification framework")
- Agentic RAG decomposes "Compare SaaS vs usage-based pricing" into separate retrievals then synthesis

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-knowledge-base*
*Context gathered: 2026-02-11*
