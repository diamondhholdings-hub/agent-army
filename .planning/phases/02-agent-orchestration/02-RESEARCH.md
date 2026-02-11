# Phase 2: Agent Orchestration - Research

**Researched:** 2026-02-11
**Domain:** Multi-agent coordination, event-driven architecture, context management, observability
**Confidence:** HIGH

## Summary

This phase builds the orchestration layer that coordinates agent interactions on top of the Phase 1 infrastructure (FastAPI, PostgreSQL with RLS, Redis, LiteLLM Router, Prometheus metrics). The standard approach uses **LangGraph** as the agent orchestration framework (supervisor topology with functional API), **Redis Streams** for the event bus (already available via Phase 1's redis-py), **Pydantic** for structural validation plus LLM-based semantic validation at handoffs, and **Langfuse** for observability with per-tenant per-agent cost tracking.

The three-tier context management follows the Google ADK pattern: working context compiled per invocation from session + long-term memory, session state persisted via LangGraph's checkpointer (Redis-backed for this project), and long-term memory stored in PostgreSQL with pgvector for semantic search. This architecture maps cleanly to the locked decisions from CONTEXT.md while leveraging the existing infrastructure.

The supervisor pattern is well-supported by LangGraph's functional API (`@entrypoint` / `@task` decorators) and the `langgraph-supervisor` library. Redis Streams provide the event bus with consumer groups, acknowledgment, and dead letter queue patterns via `XADD`/`XREADGROUP`/`XACK`/`XAUTOCLAIM`. Langfuse (MIT-licensed, self-hostable) integrates directly with LiteLLM via callback and provides the tracing, cost tracking, and multi-agent debugging UI required by success criteria.

**Primary recommendation:** Use LangGraph (functional API) + Redis Streams + Langfuse + Pydantic validators as the core stack. Build a custom agent registry on top of LangGraph's `create_react_agent` with tenant-scoped Redis Streams for event isolation.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| langgraph | >=1.0.8 | Agent orchestration framework | Official LangChain framework for stateful multi-agent systems. Supervisor topology, functional API, built-in persistence. Fastest benchmarked framework. |
| langgraph-supervisor | >=0.0.31 | Supervisor pattern helpers | Official library for hierarchical multi-agent coordination with `create_supervisor()`. Tool-based handoff mechanism. |
| langgraph-checkpoint-postgres | >=3.0.4 | Session state persistence | PostgreSQL-backed checkpointer for LangGraph. Project already uses PostgreSQL. Async support via `AsyncPostgresSaver`. |
| redis (redis-py) | >=5.0.0 | Event bus via Redis Streams | Already installed in Phase 1. Provides `xadd`, `xreadgroup`, `xack`, `xautoclaim` for streams + consumer groups. |
| langfuse | >=3.14.1 | Observability and tracing | MIT-licensed, self-hostable. Native LiteLLM integration. Per-tenant metadata, cost tracking, multi-agent trace visualization. |
| pydantic | >=2.0.0 | Handoff validation schemas | Already installed in Phase 1. `AfterValidator`, `ValidationInfo` for structural + context-driven validation. |
| langchain-anthropic | >=latest | Claude model integration | LangGraph model binding for Anthropic Claude (project's primary model). |
| langchain-openai | >=latest | OpenAI fallback integration | LangGraph model binding for GPT-4o (project's fallback model). |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| langgraph-checkpoint-redis | >=0.3.4 | Alternative session persistence | If Redis-only persistence preferred over PostgreSQL. Includes vector search in RedisStore. Requires Redis 8.0+ or Redis Stack. |
| pgvector | >=0.3.0 | Vector search for long-term memory | PostgreSQL extension for semantic similarity search in long-term memory tier. |
| tiktoken | >=0.7.0 | Token counting | Working context size estimation and truncation. Used to enforce context window limits. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| LangGraph | CrewAI | CrewAI is higher-level but less flexible for custom supervisor logic. LangGraph gives fine-grained control needed for hybrid routing. |
| LangGraph | Google ADK | ADK pioneered the three-tier pattern but is tightly coupled to Google Cloud (Vertex AI). LangGraph is provider-agnostic. |
| Langfuse | LangSmith | LangSmith has deeper LangGraph integration but is proprietary SaaS. Langfuse is MIT/self-hostable, critical for data sovereignty with customer data. |
| Langfuse | AgentOps | AgentOps is agent-focused but less mature. Langfuse has larger community and LiteLLM native integration. |
| Redis Streams | Kafka | Kafka has better throughput at scale but massive operational overhead. Redis Streams is already available and sufficient for agent-to-agent communication volumes. |
| pgvector | Qdrant | Requirements mention Qdrant for Phase 3 KB. For Phase 2 long-term memory, pgvector avoids adding another dependency since PostgreSQL is already available. Phase 3 may still introduce Qdrant for the full knowledge base. |

**Installation:**
```bash
# Add to pyproject.toml dependencies
pip install langgraph>=1.0.8 langgraph-supervisor>=0.0.31 langgraph-checkpoint-postgres>=3.0.4 langfuse>=3.14.1 langchain-anthropic langchain-openai tiktoken pgvector>=0.3.0
```

## Architecture Patterns

### Recommended Project Structure
```
src/app/
├── agents/                    # Agent definitions
│   ├── __init__.py
│   ├── base.py               # BaseAgent abstract class and agent registry
│   ├── registry.py           # AgentRegistry -- register/discover agents
│   └── supervisor.py         # Supervisor orchestrator (LangGraph graph)
├── events/                    # Event bus infrastructure
│   ├── __init__.py
│   ├── bus.py                # TenantEventBus -- tenant-scoped Redis Streams
│   ├── schemas.py            # Event message Pydantic models (AgentEvent, etc.)
│   ├── consumer.py           # Stream consumer with consumer groups
│   └── dlq.py               # Dead letter queue handler
├── context/                   # Three-tier context management
│   ├── __init__.py
│   ├── working.py            # WorkingContext compiler (assembles per-invocation)
│   ├── session.py            # SessionStore (LangGraph checkpointer wrapper)
│   ├── memory.py             # LongTermMemory (pgvector semantic search)
│   └── manager.py            # ContextManager -- orchestrates all three tiers
├── handoffs/                  # Handoff validation
│   ├── __init__.py
│   ├── validators.py         # Pydantic structural validators
│   ├── semantic.py           # LLM-based semantic validation
│   └── protocol.py           # HandoffProtocol -- validation pipeline
├── observability/             # Tracing and cost tracking
│   ├── __init__.py
│   ├── tracer.py             # Langfuse integration wrapper
│   └── cost.py               # Per-tenant per-agent cost aggregation
├── core/                      # (existing from Phase 1)
│   ├── monitoring.py         # Prometheus metrics (extend with agent metrics)
│   └── ...
└── services/                  # (existing from Phase 1)
    └── llm.py                # LiteLLM Router (extend with Langfuse callbacks)
```

### Pattern 1: Supervisor Orchestration with LangGraph Functional API
**What:** The supervisor receives tasks, decomposes them, routes to specialist agents, and synthesizes results. Uses LangGraph's functional API (`@entrypoint`/`@task` decorators) for clarity.
**When to use:** Every multi-agent task flows through the supervisor. This is the primary coordination pattern.
**Example:**
```python
# Source: LangGraph docs (https://docs.langchain.com/oss/python/langgraph/workflows-agents)
from langgraph.func import entrypoint, task
from langgraph.prebuilt import create_react_agent
from langgraph_supervisor import create_supervisor
from langchain_anthropic import ChatAnthropic

model = ChatAnthropic(model="claude-sonnet-4-20250514")

# Specialist agents are created via create_react_agent
research_agent = create_react_agent(
    model=model,
    tools=[search_knowledge_base, search_crm],
    name="research_agent",
)

# Supervisor coordinates specialists
workflow = create_supervisor(
    agents=[research_agent, writing_agent],
    model=model,
    prompt="You are a sales operations supervisor. Route research queries to research_agent, writing tasks to writing_agent.",
)

app = workflow.compile(
    checkpointer=postgres_checkpointer,  # Session persistence
    store=memory_store,                   # Long-term memory
)
```

### Pattern 2: Tenant-Scoped Redis Streams Event Bus
**What:** Each tenant gets isolated stream keys (`t:{tenant_id}:events:{stream_name}`). Consumer groups enable parallel processing. Events carry source attribution and call chains.
**When to use:** All inter-agent communication uses the event bus for traceability and decoupling.
**Example:**
```python
# Source: redis-py docs (https://github.com/redis/redis-py)
import redis.asyncio as aioredis
import json
import uuid
from datetime import datetime

class TenantEventBus:
    """Tenant-scoped event bus using Redis Streams."""

    def __init__(self, redis: aioredis.Redis, tenant_id: str):
        self._redis = redis
        self._tenant_id = tenant_id

    def _stream_key(self, stream: str) -> str:
        return f"t:{self._tenant_id}:events:{stream}"

    async def publish(self, stream: str, event: dict) -> str:
        """Publish an event to a tenant-scoped stream."""
        event_data = {
            "event_id": str(uuid.uuid4()),
            "tenant_id": self._tenant_id,
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0",
            **{k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
               for k, v in event.items()},
        }
        return await self._redis.xadd(self._stream_key(stream), event_data)

    async def subscribe(
        self, stream: str, group: str, consumer: str, count: int = 10, block: int = 5000
    ) -> list:
        """Read events as a consumer in a group."""
        try:
            await self._redis.xgroup_create(
                self._stream_key(stream), group, id="0", mkstream=True
            )
        except aioredis.ResponseError:
            pass  # Group already exists
        return await self._redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={self._stream_key(stream): ">"},
            count=count,
            block=block,
        )

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge a processed message."""
        await self._redis.xack(self._stream_key(stream), group, message_id)
```

### Pattern 3: Three-Tier Context Management
**What:** Working context is compiled per-invocation from session history + long-term memory + current task. Session state persists via LangGraph checkpointer. Long-term memory uses pgvector for semantic search.
**When to use:** Every agent invocation compiles a working context. Session state is the conversation thread. Long-term memory stores facts about customers/deals.
**Example:**
```python
# Source: LangGraph memory docs (https://docs.langchain.com/oss/python/langgraph/add-memory)
from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain.embeddings import init_embeddings

# Session state: LangGraph checkpointer (PostgreSQL-backed)
checkpointer = AsyncPostgresSaver.from_conn_string(database_url)
await checkpointer.setup()

# Long-term memory: Store with semantic search
embeddings = init_embeddings("openai:text-embedding-3-small")
# In production, use a PostgreSQL-backed store with pgvector
# For now, InMemoryStore demonstrates the pattern
memory_store = InMemoryStore(
    index={"embed": embeddings, "dims": 1536}
)

# Working context compilation
class WorkingContextCompiler:
    """Compiles working context for each agent invocation."""

    async def compile(
        self, tenant_id: str, session_id: str, task: dict
    ) -> dict:
        # 1. Get session history (recent messages)
        session_messages = await self.get_session_messages(session_id)

        # 2. Search long-term memory for relevant facts
        relevant_memories = memory_store.search(
            (tenant_id, "memories"),
            query=task["description"],
            limit=10,
        )

        # 3. Compile into working context
        return {
            "system_prompt": self.build_system_prompt(task),
            "session_history": self.truncate_to_budget(session_messages),
            "relevant_context": [m.value["text"] for m in relevant_memories],
            "task": task,
        }
```

### Pattern 4: Hybrid Routing (Rules + LLM)
**What:** Known patterns are routed deterministically via rules (fast). Ambiguous cases fall through to LLM-based routing (flexible). This is a locked decision from CONTEXT.md.
**When to use:** Supervisor routing logic. Rules catch 80% of cases instantly; LLM handles the remaining 20%.
**Example:**
```python
from pydantic import BaseModel, Field
from typing import Literal

class RoutingDecision(BaseModel):
    """Structured output for LLM routing decisions."""
    agent: str = Field(description="The agent to route to")
    reasoning: str = Field(description="Why this agent was chosen")
    subtasks: list[str] = Field(default_factory=list, description="Task decomposition if needed")

class HybridRouter:
    """Rules-based routing with LLM fallback."""

    def __init__(self, model, agent_registry):
        self._model = model
        self._registry = agent_registry
        self._rules: list[tuple[callable, str]] = []

    def add_rule(self, matcher: callable, agent_name: str):
        """Register a deterministic routing rule."""
        self._rules.append((matcher, agent_name))

    async def route(self, task: dict) -> RoutingDecision:
        # Phase 1: Try rules-based routing
        for matcher, agent_name in self._rules:
            if matcher(task):
                return RoutingDecision(
                    agent=agent_name,
                    reasoning=f"Matched rule for {agent_name}",
                )

        # Phase 2: LLM-based routing for ambiguous cases
        available_agents = self._registry.list_agents()
        router_llm = self._model.with_structured_output(RoutingDecision)
        return await router_llm.ainvoke([
            {"role": "system", "content": f"Route this task to the best agent. Available: {available_agents}"},
            {"role": "user", "content": str(task)},
        ])
```

### Pattern 5: Handoff Validation with LLM Semantic Check
**What:** Two-layer validation: Pydantic structural validation (schema, types, required fields) followed by LLM semantic validation (logical consistency, truthfulness). Configurable strictness per handoff type.
**When to use:** Every agent-to-agent handoff passes through validation. Critical handoffs (deal data) get strict + semantic validation; routine handoffs (status updates) get lenient structural-only validation.
**Example:**
```python
# Source: Pydantic docs (https://pydantic.dev/articles/llm-validation)
from pydantic import BaseModel, AfterValidator, ValidationInfo, model_validator
from typing import Annotated
from enum import Enum

class ValidationStrictness(str, Enum):
    STRICT = "strict"    # Full structural + semantic validation
    LENIENT = "lenient"  # Structural only

class HandoffPayload(BaseModel):
    """Base handoff payload with source attribution."""
    source_agent_id: str
    call_chain: list[str]  # e.g., ["sales_agent", "supervisor", "research_agent"]
    tenant_id: str
    data: dict
    confidence: float  # 0.0-1.0

    @model_validator(mode="after")
    def validate_call_chain_includes_source(self):
        if self.source_agent_id not in self.call_chain:
            raise ValueError("Source agent must appear in call chain")
        return self

async def semantic_validation(payload: HandoffPayload, context: dict) -> tuple[bool, str]:
    """LLM-based semantic validation for critical handoffs."""
    validation_prompt = f"""Validate this agent handoff for logical consistency and truthfulness.

Source agent: {payload.source_agent_id}
Call chain: {' -> '.join(payload.call_chain)}
Data: {payload.data}
Available context: {context}

Check for:
1. Are all claims supported by the available context?
2. Are there any fabricated/hallucinated data points?
3. Is the data logically consistent (no contradictions)?

Respond with: {{"valid": true/false, "issues": ["list of problems"]}}"""

    result = await llm.completion(
        messages=[{"role": "user", "content": validation_prompt}],
        model="fast",  # Use fast model for validation
        temperature=0.0,
    )
    return parse_validation_result(result)
```

### Anti-Patterns to Avoid
- **Bag of agents:** Agents communicating directly without a coordinator. Always route through the supervisor. The supervisor maintains the global view of task state and prevents duplicate work.
- **Fat events:** Putting large payloads (documents, full context) into Redis Stream events. Use the hybrid approach: small data inline, large data by reference to shared context store.
- **Implicit context passing:** Agents assuming context from previous interactions without explicit compilation. Every invocation must compile its working context fresh.
- **Unvalidated handoffs:** Passing data between agents without validation. Even "routine" handoffs need structural validation to catch schema drift.
- **Global state mutation:** Agents modifying shared state directly. All state changes flow through the event bus or context manager for auditability.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Agent state persistence | Custom Redis/PG session storage | LangGraph checkpointer (AsyncPostgresSaver) | Handles serialization, thread management, time-travel debugging. Weeks of edge cases already solved. |
| Supervisor routing graph | Custom state machine / if-else chains | LangGraph StateGraph or functional API | Handles cycles, parallel execution, error recovery, streaming. Battle-tested in production. |
| LLM call tracing | Custom logging middleware | Langfuse `@observe` decorator + LiteLLM callback | Full trace trees, cost tracking, latency histograms, comparison UI. Thousands of hours of tooling. |
| Token counting | Custom string length estimation | tiktoken library | Accurate per-model token counting. Different models tokenize differently. Critical for context window management. |
| Consumer group management | Custom Redis lock-based consumers | Redis Streams consumer groups (`XREADGROUP`) | Built-in message delivery tracking, pending entry list, auto-claim for dead consumers. Redis handles the hard parts. |
| Retry with backoff | Custom sleep/retry loops | tenacity library (already installed) | Decorators for exponential backoff, jitter, retry conditions, stop conditions. Already in project dependencies. |
| Vector similarity search | Custom cosine similarity on arrays | pgvector extension for PostgreSQL | Optimized HNSW/IVFFlat indexes, SQL-native queries, millions of vectors. PostgreSQL already in stack. |

**Key insight:** The orchestration layer is glue code between well-tested components. LangGraph handles the agent execution graph, Redis Streams handle event delivery, Langfuse handles observability, and Pydantic handles validation. The custom code should focus on the business logic: routing rules, context compilation strategy, and validation criteria -- not the infrastructure plumbing.

## Common Pitfalls

### Pitfall 1: Context Window Overflow
**What goes wrong:** Working context compiled with full session history + all relevant memories exceeds the model's context window, causing truncation or errors.
**Why it happens:** No budget enforcement during context compilation. Session history grows unbounded. Memory search returns too many results.
**How to avoid:** Implement a token budget system. Use tiktoken to count tokens. Allocate budget: ~20% system prompt, ~30% session history (most recent first), ~30% relevant memories (highest relevance first), ~20% reserved for response. Truncate each section to its budget.
**Warning signs:** Increasing LLM costs per invocation, degraded response quality, context-related API errors.

### Pitfall 2: Hallucination Cascade Between Agents
**What goes wrong:** Agent A fabricates a fact (e.g., "customer budget is $500k"). Agent B receives this and builds on it (e.g., "since budget is $500k, recommend Enterprise tier"). Agent C cites this chain as verified.
**Why it happens:** No validation at handoff boundaries. Agents trust upstream output without verification.
**How to avoid:** LLM semantic validation at every critical handoff. Require source attribution in handoff payloads -- every claim must reference where the data came from. Validation checks claims against available context.
**Warning signs:** Agent outputs referencing facts not in any knowledge base. Confidence scores that don't correlate with data availability.

### Pitfall 3: Redis Streams Message Backlog
**What goes wrong:** Consumer falls behind, pending entry list grows unbounded, Redis memory usage spikes.
**Why it happens:** Consumer processing is slower than producer rate. Failed messages aren't acknowledged or dead-lettered. No stream trimming.
**How to avoid:** Set MAXLEN on streams via `XTRIM` (approximate is fine for performance). Implement dead letter queue: after 3 retries, move to DLQ stream. Use `XAUTOCLAIM` to reclaim messages from dead consumers. Monitor pending count with `XPENDING`.
**Warning signs:** Growing `XPENDING` count, increasing Redis memory, delayed event processing.

### Pitfall 4: Tenant Context Leakage in Event Bus
**What goes wrong:** Event from Tenant A is accidentally processed in Tenant B's context, or a consumer reads from the wrong stream.
**Why it happens:** Stream keys not properly tenant-scoped. Consumer group names not unique per tenant. Context variable not set before processing event.
**How to avoid:** Strict tenant prefix in all stream keys: `t:{tenant_id}:events:{stream}`. Validate `tenant_id` in every event payload matches the stream key. Set tenant context (from Phase 1's `set_tenant_context()`) before processing any event.
**Warning signs:** Cross-tenant data in agent responses. Tenant ID mismatches in event logs.

### Pitfall 5: Supervisor Becomes Bottleneck
**What goes wrong:** Supervisor processes every task sequentially. As agent count grows, supervisor becomes the throughput ceiling.
**Why it happens:** Supervisor waits for each agent to complete before routing the next task. No parallel execution of independent subtasks.
**How to avoid:** LangGraph's functional API supports parallel task execution naturally -- `@task` functions return futures that can be awaited in parallel. Decompose tasks into independent subtasks that run concurrently. Only serialize dependent tasks.
**Warning signs:** Linear increase in latency with agent count. Supervisor idle time while waiting for agents.

### Pitfall 6: Langfuse Self-Hosting Complexity
**What goes wrong:** Langfuse v3 requires PostgreSQL + Redis + ClickHouse + S3-compatible storage. Heavy infrastructure for development.
**Why it happens:** Langfuse v3 architecture uses ClickHouse for analytics and S3 for event storage.
**How to avoid:** Use Langfuse Cloud (free tier: 50k observations/month) for development. Self-host only for production when data sovereignty requires it. Alternatively, start with LiteLLM's built-in `success_callback=["langfuse"]` pointing to cloud, migrate to self-hosted later.
**Warning signs:** Spending more time on observability infrastructure than agent logic during development.

## Code Examples

Verified patterns from official sources:

### Redis Streams: Publish and Consume with Dead Letter Queue
```python
# Source: redis-py docs (https://github.com/redis/redis-py)
import redis.asyncio as aioredis
import asyncio
import json
from datetime import datetime

class EventConsumer:
    """Redis Streams consumer with retry and dead letter queue."""

    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 4, 16]  # Exponential backoff: 1s, 4s, 16s

    def __init__(self, redis: aioredis.Redis, stream: str, group: str, consumer: str):
        self._redis = redis
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._dlq_stream = f"{stream}:dlq"

    async def process_loop(self, handler):
        """Main processing loop with retry logic."""
        while True:
            messages = await self._redis.xreadgroup(
                groupname=self._group,
                consumername=self._consumer,
                streams={self._stream: ">"},
                count=10,
                block=5000,
            )
            for stream_name, stream_messages in messages:
                for message_id, data in stream_messages:
                    await self._process_with_retry(message_id, data, handler)

    async def _process_with_retry(self, message_id: str, data: dict, handler):
        """Process message with exponential backoff retry."""
        retry_count = int(data.get("_retry_count", "0"))

        try:
            await handler(data)
            await self._redis.xack(self._stream, self._group, message_id)
        except Exception as e:
            if retry_count >= self.MAX_RETRIES:
                # Move to dead letter queue
                await self._redis.xadd(self._dlq_stream, {
                    "original_stream": self._stream,
                    "original_id": message_id,
                    "error": str(e),
                    "retry_count": str(retry_count),
                    "timestamp": datetime.utcnow().isoformat(),
                    **data,
                })
                await self._redis.xack(self._stream, self._group, message_id)
            else:
                delay = self.RETRY_DELAYS[min(retry_count, len(self.RETRY_DELAYS) - 1)]
                await asyncio.sleep(delay)
                # Re-publish with incremented retry count
                data["_retry_count"] = str(retry_count + 1)
                await self._redis.xadd(self._stream, data)
                await self._redis.xack(self._stream, self._group, message_id)

    async def reclaim_abandoned(self, idle_time_ms: int = 60000):
        """Reclaim messages from dead/stalled consumers."""
        claimed = await self._redis.xautoclaim(
            self._stream, self._group, self._consumer,
            min_idle_time=idle_time_ms, start_id="0", count=10,
        )
        return claimed
```

### Event Schema with Source Attribution and Call Chain
```python
# Source: Pydantic docs (https://docs.pydantic.dev/latest/)
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Any
import uuid

class EventPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

class EventType(str, Enum):
    TASK_ASSIGNED = "task.assigned"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    HANDOFF_REQUEST = "handoff.request"
    HANDOFF_VALIDATED = "handoff.validated"
    HANDOFF_REJECTED = "handoff.rejected"
    CONTEXT_UPDATED = "context.updated"

class AgentEvent(BaseModel):
    """Core event schema for inter-agent communication."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    version: str = "1.0"
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tenant_id: str
    priority: EventPriority = EventPriority.NORMAL

    # Source attribution (locked decision)
    source_agent_id: str
    call_chain: list[str]  # Full trace: ["user", "supervisor", "research_agent"]

    # Hybrid payload (locked decision)
    data: dict[str, Any] = Field(default_factory=dict)          # Small inline data
    context_refs: list[str] = Field(default_factory=list)  # References to large data in context store

    # Correlation
    correlation_id: str | None = None  # Groups related events
    parent_event_id: str | None = None  # Links to triggering event

    def to_stream_dict(self) -> dict[str, str]:
        """Serialize for Redis Streams (all values must be strings)."""
        return {
            "event_id": self.event_id,
            "version": self.version,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "tenant_id": self.tenant_id,
            "priority": self.priority.value,
            "source_agent_id": self.source_agent_id,
            "call_chain": ",".join(self.call_chain),
            "data": json.dumps(self.data),
            "context_refs": ",".join(self.context_refs),
            "correlation_id": self.correlation_id or "",
            "parent_event_id": self.parent_event_id or "",
        }
```

### Langfuse Integration with LiteLLM
```python
# Source: Langfuse docs (https://langfuse.com/docs/integrations/litellm/tracing)
# Source: LiteLLM docs (https://docs.litellm.ai/docs/observability/langfuse_integration)
import os
import litellm
from langfuse import observe, get_client, propagate_attributes

# Configure Langfuse with LiteLLM callbacks
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-..."
os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-..."
os.environ["LANGFUSE_HOST"] = "https://cloud.langfuse.com"  # Or self-hosted URL

litellm.success_callback = ["langfuse"]
litellm.failure_callback = ["langfuse"]

# Wrap agent execution with Langfuse tracing
@observe()
async def execute_agent_task(task: dict, tenant_id: str, agent_id: str):
    langfuse = get_client()

    with propagate_attributes(
        user_id=tenant_id,  # Maps to tenant for cost tracking
        session_id=task.get("session_id"),
        tags=[f"agent:{agent_id}", f"tenant:{tenant_id}"],
        metadata={
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "task_type": task.get("type"),
        },
    ):
        # All LiteLLM calls within this scope are automatically traced
        result = await llm_service.completion(
            messages=task["messages"],
            model="reasoning",
            metadata={
                "generation_name": f"{agent_id}-{task['type']}",
                "trace_user_id": tenant_id,
                "session_id": task.get("session_id"),
                "tags": [agent_id, tenant_id],
            },
        )

        langfuse.update_current_trace(
            input={"task": task},
            output={"result": result},
        )

    return result
```

### Agent Registry Pattern
```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class AgentCapability:
    name: str
    description: str
    input_schema: type  # Pydantic model
    output_schema: type  # Pydantic model

@dataclass
class AgentRegistration:
    agent_id: str
    name: str
    description: str
    capabilities: list[AgentCapability]
    graph: Any  # Compiled LangGraph
    backup_agent_id: str | None = None  # For failure routing (locked decision)
    tags: list[str] = field(default_factory=list)

class AgentRegistry:
    """Registry for discovering and managing agents."""

    def __init__(self):
        self._agents: dict[str, AgentRegistration] = {}

    def register(self, registration: AgentRegistration) -> None:
        self._agents[registration.agent_id] = registration

    def get(self, agent_id: str) -> AgentRegistration | None:
        return self._agents.get(agent_id)

    def get_backup(self, agent_id: str) -> AgentRegistration | None:
        """Get backup agent for failure routing (locked decision)."""
        agent = self._agents.get(agent_id)
        if agent and agent.backup_agent_id:
            return self._agents.get(agent.backup_agent_id)
        return None

    def find_by_capability(self, capability_name: str) -> list[AgentRegistration]:
        """Find agents that can handle a specific capability."""
        return [
            agent for agent in self._agents.values()
            if any(c.name == capability_name for c in agent.capabilities)
        ]

    def list_agents(self) -> list[dict]:
        """List all registered agents (for LLM routing context)."""
        return [
            {"id": a.agent_id, "name": a.name, "description": a.description,
             "capabilities": [c.name for c in a.capabilities]}
            for a in self._agents.values()
        ]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| LangChain AgentExecutor | LangGraph functional API (`@entrypoint`/`@task`) | LangGraph 1.0 (2025) | Much simpler code, native async, parallel task execution. AgentExecutor is legacy. |
| LangChain ConversationBufferMemory | LangGraph checkpointer + store (two-tier) | 2025 | Thread-scoped short-term + namespace-scoped long-term. Clean separation. |
| Custom tracing middleware | Langfuse v3 `@observe` + OpenTelemetry | June 2025 | SDK rewrite with propagate_attributes, native LiteLLM integration. Major simplification. |
| LangSmith-only tracing | Langfuse as open-source alternative | 2024-2025 | MIT-licensed, self-hostable. Production-ready for data-sovereign use cases. |
| langgraph-supervisor library | Direct tool-based supervisor pattern | Late 2025 | Library authors now recommend building supervisors directly with tools for more control. Library still works but is less flexible. |
| Separate Redis + PostgreSQL stores | langgraph-checkpoint-redis with vector search | 2025-2026 | RedisStore includes vector search. But requires Redis 8.0+ with RediSearch module. |
| Synchronous checkpointers | AsyncPostgresSaver / AsyncRedisSaver | 2025 | Full async support critical for FastAPI applications. |

**Deprecated/outdated:**
- `ConversationBufferMemory` / `ConversationSummaryMemory`: Replaced by LangGraph checkpointer pattern
- `AgentExecutor`: Replaced by LangGraph graphs. LangChain docs explicitly say "use LangGraph for all new agents"
- Langfuse v2 SDK: Rewritten in v3 (June 2025). Migration guide available but API changed significantly
- `langgraph-supervisor` as the primary approach: Library README now recommends direct tool-based pattern "for most use cases"

## Open Questions

Things that couldn't be fully resolved:

1. **LangGraph + Custom Event Bus Integration**
   - What we know: LangGraph has its own internal state management. Redis Streams is the event bus for inter-agent communication.
   - What's unclear: How to cleanly bridge LangGraph's internal message passing with Redis Streams events. Should every LangGraph node emit events, or only at graph boundaries?
   - Recommendation: Emit events at graph boundaries (task received, task completed, handoff initiated). Internal LangGraph node communication stays within the graph. This prevents event noise while maintaining traceability.

2. **pgvector vs Qdrant for Long-Term Memory**
   - What we know: Phase 3 (Knowledge Base) specifies Qdrant (KB-02). Phase 2 needs vector search for long-term memory. pgvector is already in PostgreSQL.
   - What's unclear: Should Phase 2 use pgvector (simpler, already available) or set up Qdrant early (consistent with Phase 3)?
   - Recommendation: Use pgvector for Phase 2 long-term memory. It's already in the stack and sufficient for agent memory. Phase 3 may introduce Qdrant for the larger knowledge base. The long-term memory interface should be abstract enough to swap implementations.

3. **Langfuse Cloud vs Self-Hosted for Development**
   - What we know: Langfuse v3 self-hosting requires PostgreSQL + Redis + ClickHouse + S3. The project doesn't have Docker available on dev machine.
   - What's unclear: Whether the free cloud tier (50k observations/month) is sufficient for development.
   - Recommendation: Start with Langfuse Cloud free tier for development. Defer self-hosting to production deployment. The SDK is identical for both -- just change the `LANGFUSE_HOST` environment variable.

4. **LangGraph Supervisor Library vs Direct Implementation**
   - What we know: `langgraph-supervisor` exists (v0.0.31) but its own README says "We now recommend using the supervisor pattern directly via tools rather than this library for most use cases."
   - What's unclear: Whether the library provides enough value for the hybrid routing pattern (rules + LLM) or if direct implementation is better.
   - Recommendation: Use the library as a starting reference but implement the supervisor directly with LangGraph's functional API. This gives full control over the hybrid routing logic and validation pipeline that the library doesn't support out of the box.

5. **Working Context Token Budget Strategy**
   - What we know: Claude Sonnet 4 has 200k context window. GPT-4o has 128k. Working context must fit within these limits.
   - What's unclear: Optimal budget allocation across system prompt, session history, retrieved memories, and task data.
   - Recommendation: Start conservative -- 8k total working context for the "fast" model tier, 32k for "reasoning" tier. Allocate: 15% system prompt, 35% session history (most recent), 35% retrieved context, 15% task + response buffer. Tune based on actual usage patterns. Use tiktoken for accurate counting.

## Sources

### Primary (HIGH confidence)
- `/redis/redis-py` via Context7 -- Redis Streams API (XADD, XREADGROUP, XACK, XAUTOCLAIM, consumer groups)
- `/websites/langchain_oss_python_langgraph` via Context7 -- LangGraph functional API, supervisor pattern, orchestrator-worker, memory/store
- `/websites/langchain_langsmith` via Context7 -- LangSmith tracing, cost tracking, metadata tags
- `/langfuse/langfuse-docs` via Context7 -- Langfuse @observe decorator, propagate_attributes, cost tracking, Docker self-hosting
- https://pydantic.dev/articles/llm-validation -- Pydantic validators for LLM output, hallucination prevention
- https://pypi.org/project/langgraph/ -- LangGraph v1.0.8 (Feb 6, 2026)
- https://pypi.org/project/langgraph-supervisor/ -- langgraph-supervisor v0.0.31
- https://pypi.org/project/langgraph-checkpoint-postgres/ -- v3.0.4 (Jan 31, 2026)
- https://pypi.org/project/langgraph-checkpoint-redis/ -- v0.3.4 (Feb 3, 2026)
- https://pypi.org/project/langfuse/ -- Langfuse v3.14.1 (Feb 9, 2026)

### Secondary (MEDIUM confidence)
- https://github.com/langchain-ai/langgraph-supervisor-py -- Supervisor API, usage patterns, library README recommendation
- https://docs.litellm.ai/docs/observability/langfuse_integration -- LiteLLM + Langfuse callback integration
- https://langfuse.com/faq/all/langsmith-alternative -- Langfuse vs LangSmith comparison
- https://google.github.io/adk-docs/sessions/ -- Google ADK three-tier context pattern (Session/State/Memory)
- https://redis.io/blog/langgraph-redis-build-smarter-ai-agents-with-memory-persistence/ -- LangGraph + Redis integration patterns
- https://github.com/pgvector/pgvector-python -- pgvector SQLAlchemy integration for vector search

### Tertiary (LOW confidence)
- https://medium.com/@gopikwork/building-agentic-memory-patterns-with-strands-and-langgraph-3cc8389b350d -- Context engineering patterns (single source, needs validation)
- https://medium.com/@vinay.georgiatech/dead-letter-queues-and-retry-queues -- DLQ patterns (general concepts, not Redis-specific)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All library versions verified via PyPI. APIs verified via Context7 official docs. LangGraph 1.0+ is stable.
- Architecture: HIGH -- Patterns from official LangGraph docs (functional API, supervisor, memory). Redis Streams patterns from redis-py official examples. Three-tier context follows Google ADK pattern validated by LangGraph's checkpointer+store design.
- Pitfalls: MEDIUM -- Derived from multiple sources and experience patterns. Context window management and hallucination cascade are well-documented concerns. Langfuse self-hosting complexity is verified from Docker Compose requirements.

**Research date:** 2026-02-11
**Valid until:** 2026-03-11 (30 days -- stack is stable with LangGraph 1.0+ and Langfuse v3)
