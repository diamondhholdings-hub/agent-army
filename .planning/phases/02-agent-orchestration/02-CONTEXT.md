# Phase 2: Agent Orchestration - Context

**Gathered:** 2026-02-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Multi-agent coordination system with supervisor topology, event-driven communication via Redis Streams, three-tier context management (working/session/long-term), and observability infrastructure. Prevents the "bag of agents" anti-pattern through structured handoffs and validation checkpoints.

This phase delivers the orchestration layer that coordinates agent interactions -- not the agents themselves (those come in later phases).

</domain>

<decisions>
## Implementation Decisions

### Event Message Structure
- **Source attribution**: Agent ID + full call chain (e.g., Sales Agent → Supervisor → Research Agent) -- enables complete traceability
- **Context inclusion**: Hybrid approach -- small data inline in event payload, large data referenced from shared context store
- **Failure handling**: Retry with exponential backoff (3 attempts), then dead letter queue for manual review
- **Core schema, versioning, priority, batching, ordering**: Claude's discretion based on technical requirements

### Supervisor Routing Logic
- **Routing strategy**: Hybrid approach
  - Rules-based for known patterns (fast, deterministic)
  - LLM-based analysis for ambiguous cases
- **Task decomposition**: Full decomposition capability -- supervisor can break complex tasks into parallel or sequential sub-tasks
- **Result synthesis**: LLM synthesis to combine agent outputs into coherent response
- **Agent failure handling**: Route to backup agent with similar capabilities (don't retry same agent)

### Handoff Validation Rules
- **Primary goal**: Both hallucination prevention AND completeness equally important
  - Catch unverified/fabricated data passed between agents
  - Ensure all required fields present and valid
- **Strictness level**: Configurable per handoff type
  - Critical handoffs (e.g., deal data, customer info): Strict validation
  - Routine handoffs (e.g., status updates): Lenient validation
- **Validation depth**: LLM semantic validation -- not just structure, but logical consistency and truthfulness
- **Rejection handling**: Claude's discretion (return to sender, supervisor intervention, or DLQ)

### Context Tier Boundaries
- **Session persistence**: Explicit clear only -- persist until deal closes or explicitly cleared, NOT time-based expiration
- **Long-term vs session separation**: All three aspects apply simultaneously:
  1. **Facts vs workflow**: Long-term stores learned facts about customer/deal, session stores current conversation flow
  2. **Permanent vs temporary**: Long-term survives deal lifecycle, session is ephemeral within conversation
  3. **Searchable vs sequential**: Long-term is vector searchable knowledge base, session is linear conversation history
- **Working context scope and size limits**: Claude's discretion based on model capabilities and performance needs

### Claude's Discretion
- Event schema details (exact fields beyond source/tenant/type)
- Event versioning strategy
- Priority/urgency model for events
- Batching support and implementation
- Event ordering guarantees
- Working context compilation strategy
- Context size limits and truncation approach
- Rejection handling mechanics (return path, retry logic)

</decisions>

<specifics>
## Specific Ideas

- The supervisor is the "conductor" -- it doesn't do work itself, it coordinates specialists
- Call chain tracking is critical for debugging: "Why did the Sales Agent say X?" → trace back through supervisor → see which agent provided that info
- Hybrid context approach prevents event bloat (Redis Streams can handle millions of small messages, but large payloads slow everything down)
- LLM semantic validation is the key defense against hallucination cascade: Agent A makes up a fact → Agent B catches it at handoff → prevents Agent C from building on false data
- Session state should survive conversation pauses (user steps away for an hour, comes back, conversation continues where it left off)
- Long-term memory serves multiple roles: searchable knowledge base (RAG), permanent record (audit trail), training data source (future agent improvement)

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 02-agent-orchestration*
*Context gathered: 2026-02-11*
