# Sophisticated Agent Harness Architecture Plan

**Status:** Architecture Design (Awaiting Approval)  
**Date:** 2026-07-07  
**Scope:** Full-featured agent orchestration system with loop execution, parallel spawning, and tool integration

---

## 1. Core Vision

Build a **self-improving agent orchestration harness** that:
- Runs autonomous loops until tasks reach completion or quality thresholds
- Spawns and manages parallel sub-agents with result aggregation
- Provides a unified tool calling interface (Read, Write, Edit, Execute, API)
- Optimizes prompts dynamically based on agent roles and context
- Tracks state, failures, and retry logic across sessions
- Operates in both interactive (user-guided) and autonomous modes

---

## 2. System Architecture (5-Layer Model)

### Layer 1: Core Loop Engine (Runtime)
**Purpose:** Execute tasks until completion  
**Key Components:**
- `Loop Controller` - Main execution loop with exit conditions
- `Task State Manager` - Persist/resume task state across sessions
- `Completion Checker` - Verify task meets acceptance criteria
- `Retry Handler` - Exponential backoff, max retries, failure categorization

**Exit Conditions:**
1. User-defined success criteria met
2. Max iterations reached
3. Critical error encountered
4. User interruption

### Layer 2: Agent Orchestration (Coordination)
**Purpose:** Spawn, manage, and aggregate sub-agent results  
**Key Components:**
- `Agent Spawner` - Launch specific agent types (code-reviewer, architect, etc.)
- `Parallel Executor` - Concurrent task batching with semaphore (max 16 parallel)
- `Result Aggregator` - Combine outputs from multiple agents
- `Agent Registry` - Store agent metadata, capabilities, cost profiles
- `Dependency Graph` - Track agent dependencies (sequential vs parallel)

**Agent Types to Support:**
- Process Agents (planner, architect, tdd-guide, code-reviewer)
- Domain Agents (rust-reviewer, python-reviewer, typescript-reviewer)
- Utility Agents (performance-optimizer, security-reviewer, documentation-updater)
- Worker Agents (parallel execution of similar tasks)

### Layer 3: Tool Calling System (I/O)
**Purpose:** Unified interface for all external operations  
**Key Components:**
- `Tool Router` - Route calls to appropriate tool handler
- `Permission Manager` - Handle permission prompts, caching
- `Context Budget Tracker` - Monitor token usage per operation
- `Result Parser` - Normalize tool outputs to structured format
- `Error Handler` - Categorize and propagate tool failures

**Supported Tools:**
- **File Operations**: Read, Write, Edit, Glob, Grep
- **Execution**: Bash, ctx_execute, ctx_batch_execute
- **Git**: Status, Log, Diff, Commit, Push, Branch
- **External**: WebSearch, WebFetch, GitHub API, MCP resources

### Layer 4: Prompt Optimization (Intelligence)
**Purpose:** Generate task-specific, role-optimized prompts  
**Key Components:**
- `Prompt Template Engine` - Role-based prompt templates
- `Context Injector` - Inject relevant prior knowledge from memory/search
- `Constraint Encoder` - Encode task constraints, guardrails, success criteria
- `Example Seeder` - Few-shot examples from similar prior tasks
- `Tone/Style Adapter` - Adjust for Ponytail (lazy), Karpathy (careful), etc.

**Prompt Structure:**
```
[System Context]
- Role definition (architect, code-reviewer, etc.)
- Behavioral guidelines (Ponytail: lazy/efficient, etc.)
- Available tools and capabilities

[Task Definition]
- User intent (what they want to accomplish)
- Acceptance criteria (how to verify success)
- Constraints (time, scope, guardrails)

[Context Injection]
- Prior similar task solutions (memory)
- Relevant code snippets (codebase context)
- Tool examples (how to structure tool calls)

[Format Instructions]
- How to structure output (JSON, markdown, code blocks)
- How to call tools (exact function signatures)
- How to handle errors and edge cases
```

### Layer 5: State & Memory (Persistence)
**Purpose:** Maintain task state, learning, and resumability  
**Key Components:**
- `Session Manager` - Create/resume sessions with full context
- `Task Journal` - Write-ahead log of all decisions and outputs
- `Knowledge Graph` - Store learnings from prior runs (what works, what fails)
- `Checkpoint System` - Save state at key milestones for resumption
- `Memory Search` - Retrieve relevant prior solutions and patterns

**State Tracked:**
- Current task + sub-tasks
- Agent results and agreements
- Tool outputs and side effects
- Errors and retries
- User decisions and feedback
- Performance metrics (time, tokens, quality)

---

## 3. Execution Flow (Happy Path)

```
User Input
    ↓
Parse Intent & Extract Constraints
    ↓
Search Knowledge Graph (prior solutions?)
    ↓
Enter Main Loop
    ├─ Create Prompt (with context injection)
    ├─ Spawn Agent(s)
    │  ├─ Sequential: Wait for A → B → C
    │  └─ Parallel: Run A, B, C concurrently
    ├─ Collect Results
    ├─ Route to Tool Calls (if needed)
    │  ├─ File ops → Read/Write/Edit
    │  ├─ Execution → Bash/Execute
    │  ├─ Search → Grep/Glob/Web
    │  └─ External → API/MCP
    ├─ Aggregate Results
    ├─ Check Completion (success criteria met?)
    │  ├─ YES → Save to Knowledge Graph → Exit
    │  └─ NO → Loop (with backoff)
    ↓
Persist Session + Learnings
    ↓
Return Final Result to User
```

---

## 4. Key Design Decisions (Rationale)

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| **5-layer stack** | Separation of concerns; each layer is testable and swappable | Slight complexity overhead vs monolithic |
| **Parallel-first orchestration** | Most real tasks have independent sub-tasks; parallelism reduces wall-clock time | Token concurrency capped at 16; need semaphore |
| **Knowledge graph persistence** | Avoid re-solving same problems; enable "learning" across sessions | Extra I/O + storage overhead |
| **Prompt templates** | Reusable, optimizable, enables A/B testing of agent effectiveness | Requires upfront investment in template design |
| **Token budget tracking** | Know exactly how much reasoning capacity remains; guide agent spawn decisions | Adds instrumentation, slows down slightly |
| **Max 16 parallel agents** | Natural constraint of Claude Code harness; prevents runaway token spend | Some tasks must run sequentially (dependencies) |
| **Exit conditions explicit** | Clear signal to agents when task is "done"; prevents infinite loops | Requires upfront definition of success |

---

## 5. Prompt Structure Deep-Dive

### 5.1 Role Definition (System)
```markdown
You are a [ROLE] specialized in [DOMAIN].
Your goal: [GOAL]
Constraints: [CONSTRAINT_LIST]
Available tools: [TOOL_LIST]
Behavioral mode: [PONYTAIL|KARPATHY|OTHER]
```

### 5.2 Task Definition (User)
```markdown
**Task:** [CLEAR_ONE_SENTENCE_INTENT]

**What Success Looks Like:**
- Criterion 1: [SPECIFIC_MEASURABLE]
- Criterion 2: [SPECIFIC_MEASURABLE]

**Guardrails:**
- Do not: [X]
- Must: [Y]
- Avoid: [Z]

**Context:**
- Prior attempts: [WHAT_WAS_TRIED]
- Current state: [WHERE_WE_ARE]
- Blockers: [KNOWN_ISSUES]
```

### 5.3 Context Injection (Memory)
```markdown
**Relevant Prior Solutions:**
[Retrieved from Knowledge Graph]
- Task XYZ solved by using pattern ABC
- Similar code in file/module DEF

**Codebase Context:**
[Injected from Grep/Search]
- Functions available: [SIGNATURES]
- Existing patterns: [EXAMPLES]

**Tool Examples:**
- How to structure Read: `Read(path="/Users/.../file.rs")`
- How to structure Write: `Write(path, content)`
```

### 5.4 Format Instructions (Output)
```markdown
**Expected Output Format:**
[JSON | Markdown | Code Block | Structured]

**Tool Calling:**
When you need to execute a tool:
1. State your intent: "I'll read the file to..."
2. Call tool: <exact syntax>
3. Parse result: "The file contains..."
4. Act on result: "This means I should..."

**Error Handling:**
If a tool call fails:
- Retry up to 2 times
- If still failing, report error: "Could not read X because Y"
- Never silently ignore tool failures
```

---

## 6. Agent Spawn Patterns

### Pattern A: Sequential (Blocker)
**Use when:** Result of Agent A is needed by Agent B  
**Example:** Architect designs → Code-Reviewer reviews design → Coder implements
```
Agent(Architect)
  ↓ (wait)
Agent(CodeReviewer)
  ↓ (wait)
Agent(Coder)
```
**Cost:** 3x wall-clock time of single agent

### Pattern B: Parallel (Independent)
**Use when:** Agents work on independent sub-tasks  
**Example:** Review code for performance + security + types in parallel
```
Agent(PerformanceOptimizer)  ┐
Agent(SecurityReviewer)      ├─ (wait for all)
Agent(TypeChecker)           ┘
```
**Cost:** Max wall-clock time of slowest agent

### Pattern C: Fan-Out (Discovery)
**Use when:** Exploring multiple approaches before committing  
**Example:** Try 3 different design patterns, let experts judge each
```
Agent(DesignA) ┐
Agent(DesignB) ├─ (all run)
Agent(DesignC) ┘
    ↓
Agent(Judge) - Pick best + merge ideas
```
**Cost:** ~3x cost, but highest quality outcome

### Pattern D: Feedback Loop (Iterative)
**Use when:** Agent output needs refinement  
```
Agent(Generator) → Evaluator judges → Generator refines → Loop until pass
```
**Cost:** Multiple iterations, but guaranteed quality

---

## 7. Completion Criteria & Exit Conditions

### User-Defined Success Criteria
```python
criteria = {
  "test_coverage": 0.80,          # 80%+
  "type_safety": "strict",        # TypeScript no-any
  "security_scan": "no_critical", # 0 CRITICAL issues
  "code_review": "approved",      # +1 from domain expert
  "performance": "< 100ms",       # Latency requirement
}
```

### Automatic Exit Conditions
| Condition | Action |
|-----------|--------|
| All criteria met | Return success + save to Knowledge Graph |
| Max iterations reached (e.g., 10) | Return best effort + log learnings |
| Critical error (unrecoverable) | Abort + report error + investigate |
| Token budget exhausted | Stop + summarize progress |
| User cancellation | Checkpoint state + exit cleanly |

---

## 8. Implementation Breakdown

### Phase 1: Core Loop (Foundation)
- [ ] Task State Manager (JSON-based task journal)
- [ ] Loop Controller with exit conditions
- [ ] Checkpoint/Resume system
- [ ] Completion Checker

**Estimated LOC:** 300-500  
**Deliverable:** A task can run, checkpoint, and resume

### Phase 2: Agent Orchestration
- [ ] Agent Registry + Spawner
- [ ] Parallel Executor with semaphore
- [ ] Result Aggregator
- [ ] Dependency graph resolver (sequential vs parallel)

**Estimated LOC:** 400-600  
**Deliverable:** Can spawn N agents in parallel and aggregate results

### Phase 3: Tool Calling System
- [ ] Tool Router (Read, Write, Edit, Bash, etc.)
- [ ] Permission Manager
- [ ] Context Budget Tracker
- [ ] Error classification + retry logic

**Estimated LOC:** 500-800  
**Deliverable:** All major tools routed through unified interface

### Phase 4: Prompt Optimization
- [ ] Prompt Template Engine
- [ ] Context Injector (memory search integration)
- [ ] Constraint Encoder
- [ ] Example Seeder (few-shot learning)

**Estimated LOC:** 600-1000  
**Deliverable:** Agents receive rich, optimized context

### Phase 5: State & Memory
- [ ] Knowledge Graph (JSON/SQLite backend)
- [ ] Session Manager
- [ ] Memory Search + Retrieval
- [ ] Analytics + Learning loop

**Estimated LOC:** 400-700  
**Deliverable:** System learns from past runs; no repeated mistakes

**Total Estimated:** ~2500-3600 LOC (Python/TypeScript)

---

## 9. Technology Stack (Finalized for Production - Heavy-User Optimized)

### 9.1 Overall Decisions (User-Confirmed)
- **Language:** Python 3.11+ (asyncio + type hints)
- **LLM Support:** Multi-provider (Claude, OpenAI, Azure, Ollama) with retry/fallback
- **Execution Model:** Local + Cloud-native (Docker/Kubernetes ready)
- **Performance Target:** Sub-100ms tool latency, <2s agent spawn time

### 9.2 Layer-by-Layer Tech Stack (Production Grade)

#### **Layer 1: Core Loop Engine (Runtime)**

| Component | Technology | Rationale | Performance Notes |
|-----------|-----------|-----------|------------------|
| **Async Runtime** | `asyncio` (stdlib) + `asyncio.TaskGroup` | Native Python, no external deps, built-in semaphore | Zero overhead, millions of concurrent tasks |
| **Event Loop** | `uvloop` (optional) | 2-10x faster than asyncio on heavy workloads | Install: `pip install uvloop` for production |
| **State Persistence** | `pydantic-settings` + `msgpack` | Type-safe config, binary serialization for speed | 10-100x faster than JSON for large states |
| **Task Journal** | `aiofiles` + `msgpack` | Non-blocking file I/O, efficient binary format | Write-ahead log for crash recovery |
| **Retry Logic** | `tenacity` library | Exponential backoff, configurable max retries | Works across all layers (agents, tools, LLMs) |

**Multi-Provider LLM Fallback (Built into Layer 1):**
```python
PROVIDER_CHAIN = [
    ("claude-3.5-sonnet", "anthropic"),
    ("gpt-4", "openai"),
    ("gpt-4-turbo", "openai"),
    ("local-llama", "ollama"),
]
# System tries Claude first, falls back to GPT-4, then local Ollama
```

---

#### **Layer 2: Agent Orchestration (Coordination)**

| Component | Technology | Rationale | Performance Notes |
|-----------|-----------|-----------|------------------|
| **Multi-LLM Support** | `litellm` library | Unified API for Claude, OpenAI, Azure, Ollama with fallback routing | Single call routes through all providers automatically |
| **Agent Registry** | `pydantic.BaseModel` + `redis` (optional) | Type-safe metadata, in-memory cache for heavy load | Redis optional: 1000+ agent lookups/sec |
| **Dependency Graph** | `networkx` | Topological sort for sequential/parallel execution | O(V+E) complexity, handles 1000s of dependencies |
| **Result Aggregation** | `pydantic.ValidationError` handling | Strongly-typed results, fail-fast on schema mismatch | 100% correctness, type safety |
| **Parallel Executor** | `asyncio.TaskGroup` (Python 3.11+) | Native structured concurrency, built-in exception handling | Perfect for cancellation + result aggregation |

**LLM Retry & Fallback Strategy:**
```python
from litellm import acompletion

async def call_agent_with_fallback(agent_name: str, prompt: str):
    providers = [
        ("claude-3.5-sonnet", "anthropic"),
        ("gpt-4", "openai"),
        ("gpt-4-turbo", "openai"),
        ("llama-2", "ollama"),  # Local fallback
    ]
    
    for model, provider in providers:
        try:
            response = await acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                timeout=30,
                max_retries=3
            )
            logger.info(f"Agent {agent_name} succeeded via {model}")
            return response
        except Exception as e:
            logger.warning(f"{model} failed: {e}, trying next...")
            continue
    
    raise RuntimeError("All LLM providers exhausted after retries")
```

---

#### **Layer 3: Tool Calling System (I/O)**

| Component | Technology | Rationale | Performance Notes |
|-----------|-----------|-----------|------------------|
| **HTTP Client** | `httpx` (async) | Fast, type-safe, connection pooling, streaming | 10x faster than requests lib |
| **Tool Router** | `dispatch` dict + callable registry | O(1) lookup, type-safe tool dispatch | <1ms dispatch overhead |
| **Subprocess Execution** | `asyncio.create_subprocess_exec` | Non-blocking, handles 1000s of processes | Real-time stdout streaming |
| **File I/O** | `aiofiles` | Non-blocking async file operations | Critical for heavy I/O workloads |
| **Result Caching** | `aioredis` (Redis) or `diskcache` (local) | Cache expensive tool results, avoid re-runs | 100-1000x speedup for repeated calls |
| **Circuit Breaker** | `pybreaker` | Fail-fast on downstream failures | Prevents cascading failures under load |
| **Retry on Tools** | Built-in per-tool retry config | Exponential backoff per tool type | Read/Write: 3 retries, API: 5 retries |

**Tool Router Pattern:**
```python
class ToolRouter:
    tools = {
        "read": read_file,
        "write": write_file,
        "bash": execute_bash,
        "grep": search_pattern,
        "http_get": fetch_url,
    }
    
    async def call(self, tool_name: str, **kwargs):
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        return await self.tools[tool_name](**kwargs)
```

---

#### **Layer 4: Prompt Optimization (Intelligence)**

| Component | Technology | Rationale | Performance Notes |
|-----------|-----------|-----------|------------------|
| **Template Engine** | `jinja2` (sync, pre-compiled) | Fast, secure templating, zero runtime overhead | Pre-compile all templates at startup |
| **Context Injection** | `rank_bm25` library | BM25 ranking for fast semantic search | <100ms search across 1000 documents |
| **Embeddings** | `sentence-transformers` (local model) | Avoid external APIs, run on CPU in parallel | 50-200ms per embedding batch |
| **Example Seeding** | In-memory cache + random sampling | Few-shot learning from cached similar tasks | O(1) retrieval from memory |
| **Constraint Encoding** | Pydantic models + JSON schema | Type-safe, auto-validates constraints | Zero-cost abstraction |

**Prompt Generation (Sub-50ms Target):**
```python
class PromptEngine:
    def __init__(self):
        self.templates = {}
        # Pre-compile all Jinja2 templates on startup
        for role in ["architect", "code-reviewer", "tdd-guide"]:
            self.templates[role] = env.get_template(f"templates/{role}.j2")
    
    async def build_prompt(self, role: str, task: str, context: dict):
        # Pre-compiled template: <1ms
        # BM25 search (cached): <50ms
        # JSON schema generation (cached): <1ms
        relevant_examples = self.bm25_search(task, top_k=3)
        return self.templates[role].render(
            task=task,
            examples=relevant_examples,
            constraints=context.get("constraints", {})
        )
```

---

#### **Layer 5: State & Memory (Persistence)**

| Component | Technology | Rationale | Performance Notes |
|-----------|-----------|-----------|------------------|
| **Primary Store (Dev)** | SQLite + WAL (write-ahead logging) | Lightweight, ACID, indexed queries | 10k queries/sec locally |
| **Primary Store (Prod - RECOMMENDED)** | **Supabase** (PostgreSQL-based BaaS) | Managed PostgreSQL, pgvector, real-time, REST API, zero ops | 10k+ queries/sec, auto backups, monitoring |
| **Session Cache** | Redis (optional, for sub-1ms latency) | <1ms in-memory lookup for active sessions | Supabase built-in caching often sufficient |
| **Task Journal** | msgpack binary format + append-only log | Efficient serialization + crash safety | Write-ahead log prevents data loss |
| **Knowledge Graph** | SQLite FTS5 (dev) or **Supabase pgvector** (prod) | Full-text + vector semantic search | pgvector: 1000+ documents/sec, L2/cosine similarity |
| **Async ORM** | `sqlalchemy[asyncio]` + `asyncpg` (works with Supabase) | True async operations, connection pooling | 100x faster than sync ORM under load |
| **Vector Embeddings** | `pgvector` SQLAlchemy extension | Store + search task embeddings for semantic similarity | Native in Supabase, L2 distance queries |
| **Real-time Monitoring** | Supabase real-time subscriptions (optional) | Watch task progress live via WebSocket | Built-in, no extra server needed |

**Database Layers:**

| Environment | Config | Features |
|-------------|--------|----------|
| **Development** | SQLite (`harness.db`) + in-memory cache | Local, fast iteration, no internet |
| **Single-Machine** | SQLite with WAL + diskcache (local SSD) | Persistent, ~10k queries/sec |
| **Cloud Production (Recommended)** | **Supabase** (free tier: 500MB, $25/mo: 8GB) | PostgreSQL + pgvector + real-time + REST API + auto-backups |
| **High-Scale** | Supabase + optional Redis replica cache | 100k+ queries/sec, <1ms session lookup, point-in-time recovery |

---

### 9.3b Why Supabase for Production (User Choice)

**Supabase = PostgreSQL + Zero DevOps + Vector Search Built-in**

Your code changes: **ZERO**. Same async driver, identical ORM usage.

```python
# Development (SQLite)
DATABASE_URL = "sqlite+aiosqlite:///harness.db"

# Production (Supabase - drop-in replacement)
DATABASE_URL = "postgresql+asyncpg://postgres:PASSWORD@proj-xyz.supabase.co:5432/postgres"

# asyncpg works the same. That's it.
```

**What Supabase Gives You (Free):**

1. ✅ **Managed PostgreSQL** — Uptime SLA, 24/7 support, scaling handles itself
2. ✅ **pgvector Built-in** — Vector search without installing extensions
3. ✅ **Auto-backups** — Daily + point-in-time recovery (never lose task state)
4. ✅ **Real-time Subscriptions** — Live task progress monitoring (optional UI)
5. ✅ **Auto-generated REST API** — External dashboards, webhooks
6. ✅ **Connection Pooling** — PgBouncer, no connection management needed
7. ✅ **Monitoring Dashboard** — Query stats, slow logs, performance insights
8. ✅ **Row-Level Security** — Auth built-in if you need it
9. ✅ **Replication** — Read replicas for scaling without code changes

**Knowledge Graph with Vector Search (Supabase pgvector):**

```python
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Float, String, DateTime

class KnowledgeEntry(Base):
    """Task solutions stored with semantic embeddings"""
    __tablename__ = "knowledge_graph"
    
    entry_id = Column(String(36), primary_key=True)
    task_description = Column(String(5000))  # User's original task
    solution = Column(String(10000))         # Solution + code
    quality_score = Column(Float)            # 0.0-1.0 (how well it worked)
    
    # 1536-dimensional vector (OpenAI embeddings)
    embedding = Column(Vector(1536))
    created_at = Column(DateTime, default=datetime.now)

# Semantic search: find similar past solutions
async def find_similar_solutions(
    user_task: str,
    embedding_model,
    top_k: int = 5
):
    """Find past task solutions similar to current task (by meaning, not keywords)"""
    
    # Embed the user's current task
    user_embedding = embedding_model.encode(user_task)
    
    # Supabase pgvector: L2 distance (Euclidean) search
    # Finds closest vectors in N-dimensional space
    stmt = select(KnowledgeEntry).order_by(
        KnowledgeEntry.embedding.l2_distance(user_embedding)
    ).limit(top_k)
    
    async with AsyncSession(engine) as session:
        results = await session.execute(stmt)
        return results.scalars().all()

# Real-world example:
# User: "Build authentication system"
# → Finds past solutions for:
#    - "Create user login flow"
#    - "Implement JWT tokens"
#    - "Add session management"
# (ranked by semantic similarity, not keyword match)
```

**Why Supabase Over Self-Managed PostgreSQL:**

| Aspect | Self-Managed RDS | Supabase |
|--------|------------------|----------|
| **Setup Time** | 2 hours | 5 minutes |
| **Monthly Cost** | $50-100 | $25-50 |
| **DevOps Effort** | 4 hrs/month | 0 |
| **Backups** | You manage | Automated |
| **Scaling** | Manual config | Auto-scaling |
| **Vector Search** | Install pgvector manually | Built-in |
| **Monitoring** | Third-party tools | Built-in dashboard |
| **Replication** | $200+ extra | Included in pricing |
| **Point-in-time Recovery** | Manual + complex | One-click restore |

**Real Pricing (Annual):**

| Setup | Monthly | Annual | Maintenance |
|-------|---------|--------|------------|
| Self-managed PostgreSQL (AWS RDS HA) | $80 | $960 | 4 hrs/month |
| Supabase production tier | $25 | $300 | 0 hrs/month |
| **Savings** | **$55/mo** | **$660/year** | **48 hrs/year** |

**Decision: Supabase is recommended for production.** Same code, less ops, more features.

---

### 9.3 Complete Dependencies Stack

```
# Core Runtime (Required)
python==3.11.0
asyncio-contextmanager
uvloop==0.17.0              # 2-10x faster event loop (production only)

# Multi-LLM Support (Required for fallback)
litellm==1.0.0              # Universal API: Claude, GPT, Azure, Ollama
anthropic==0.7.0            # Direct Claude SDK (fallback)
openai==1.0.0               # Direct OpenAI (fallback)

# Async & Concurrency (Required)
tenacity==8.2.3             # Retry + backoff logic
aiofiles==23.2.1            # Non-blocking file I/O
httpx==0.25.0               # Async HTTP client with pooling
asyncpg==0.28.0             # PostgreSQL async driver
aioredis==2.0.1             # Redis async client (optional for production)

# Database & State (Required)
sqlalchemy[asyncio]==2.0.0  # Async ORM
pydantic==2.0.0             # Type validation + schemas
pydantic-settings==2.0.0    # Configuration management
msgpack==1.0.7              # Binary serialization (10-100x faster than JSON)

# Prompt & Context (Required)
jinja2==3.1.2               # Template engine (pre-compile)
rank-bm25==0.2.2            # BM25 semantic search
networkx==3.1               # Dependency graphs

# Optional (For Enhanced Performance)
sentence-transformers==2.2.2 # Local embeddings (CPU-based)
elasticsearch==8.9.0         # Full-text search (for 100GB+ knowledge graphs)
neo4j==5.14.0               # Graph database (for complex dependencies)
diskcache==5.6.1            # Local cache (alternative to Redis)
redis==5.0.0                # Redis client (production caching)

# Monitoring & Logging (Required)
structlog==23.1.0           # Structured JSON logging
prometheus-client==0.17.1   # Metrics export
opentelemetry-api==1.20.0   # Distributed tracing

# CLI & Config (Required)
typer==0.9.0                # Modern CLI framework
python-dotenv==1.0.0        # .env file support

# Development & Testing (Dev Only)
pytest==7.4.0
pytest-asyncio==0.21.0
pytest-cov==4.1.0
ruff==0.1.0                 # Fast linter
black==23.10.0              # Code formatter
mypy==1.5.0                 # Type checker
```

---

### 9.4 Performance Targets (Heavy-User Benchmarks)

| Metric | Target | Technology Achieving It |
|--------|--------|-------------------------|
| **Agent Spawn Latency** | <2 seconds | Semaphore pooling, pre-loaded models |
| **Tool Call Latency** | <100ms | Async I/O, connection pooling, caching |
| **Prompt Generation** | <50ms | Pre-compiled Jinja2 templates, BM25 search |
| **State Lookup** | <10ms | Redis + indexed database |
| **LLM Retry Chain** | <30s total | litellm auto-fallback (3 retries per provider) |
| **Parallel Agent Throughput** | 16 agents/batch | Semaphore limiting + TaskGroup |
| **Memory per Agent** | <50MB | Lightweight async tasks, no thread pools |
| **Journal Write Latency** | <5ms | msgpack + fsync on checkpoint |
| **Max Concurrent Users** | 1000+ | Connection pooling + Redis sessions |
| **Knowledge Graph Search** | <100ms | BM25 indexing on 1000+ documents |

---

### 9.5 Deployment Architecture

#### **Development (Single Machine)**
```
localhost:8000  ← CLI / API
    ↓
[asyncio event loop with uvloop]
    ↓
SQLite (harness.db)
File-based task journal
In-memory caching
```

#### **Production (Cloud-Ready)**
```
Load Balancer (AWS ALB / Azure LB)
    ↓
Kubernetes Cluster
    ├─ Pod 1: Harness Worker (asyncio)
    ├─ Pod 2: Harness Worker (asyncio)
    └─ Pod N: Harness Worker (asyncio)
    ↓
PostgreSQL (AWS RDS / Azure Database)
Redis Cache (ElastiCache / Azure Cache)
CloudWatch / ELK Logs
Prometheus Metrics
```

**Environment Variables (for flexibility):**
```bash
# LLM Providers
CLAUDE_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
AZURE_API_KEY=...

# Database
DATABASE_URL=postgresql+asyncpg://...  # Prod
DATABASE_URL=sqlite+aiosqlite:///harness.db  # Dev

# Cache (optional)
REDIS_URL=redis://localhost:6379

# Execution Mode
EXECUTION_MODE=local|cloud|hybrid

# Performance Tuning
MAX_PARALLEL_AGENTS=16
MAX_AGENT_RETRIES=3
TOOL_TIMEOUT_SECONDS=30
PROMPT_CACHE_SIZE_MB=500
```

---

### 9.6 Directory Structure (Ready for Implementation)

```
sophisticated-agent-harness/
├── src/harness/
│   ├── __init__.py
│   ├── main.py              # CLI entry point
│   ├── config.py            # Pydantic config management
│   ├── logging.py           # Structured logging setup
│   │
│   ├── core/                # Layer 1: Loop Engine
│   │   ├── loop.py          # LoopController class
│   │   ├── task_manager.py  # TaskStateManager class
│   │   └── checkpoint.py    # CheckpointSystem class
│   │
│   ├── orchestration/       # Layer 2: Agent Orchestration
│   │   ├── agent.py         # AgentConfig + Agent class
│   │   ├── spawner.py       # AgentSpawner class
│   │   ├── registry.py      # AgentRegistry class
│   │   └── llm_provider.py  # Multi-LLM fallback logic
│   │
│   ├── tools/               # Layer 3: Tool Calling
│   │   ├── router.py        # ToolRouter class
│   │   ├── executor.py      # Subprocess/HTTP executor
│   │   ├── cache.py         # Result caching layer
│   │   └── retry.py         # Per-tool retry logic
│   │
│   ├── prompts/             # Layer 4: Prompt Optimization
│   │   ├── engine.py        # PromptEngine class
│   │   ├── context_injector.py  # Context + examples
│   │   ├── templates/       # Jinja2 template files
│   │   └── constraints.py   # Constraint encoding
│   │
│   └── persistence/         # Layer 5: State & Memory
│       ├── models.py        # SQLAlchemy ORM models
│       ├── session.py       # SessionManager class
│       ├── knowledge_graph.py  # Knowledge graph queries
│       └── migrations/      # Alembic DB migrations
│
├── tests/
│   ├── test_loop.py
│   ├── test_orchestration.py
│   ├── test_tools.py
│   ├── test_prompts.py
│   └── test_persistence.py
│
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── .dockerignore
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEPLOYMENT.md
│   ├── API.md
│   └── PERFORMANCE_TUNING.md
│
├── templates/               # Jinja2 prompt templates
│   ├── architect.j2
│   ├── code-reviewer.j2
│   ├── tdd-guide.j2
│   └── security-reviewer.j2
│
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── README.md
```

---

### 9.7 Acceptance Criteria (Updated Tech Stack)

- [ ] **Python 3.11+** with asyncio + uvloop for production
- [ ] **Multi-LLM support** via litellm with automatic fallback (Claude → GPT → Ollama)
- [ ] **Retry logic** built into every layer (agents, tools, LLMs)
- [ ] **SQLite (dev)** + **PostgreSQL (prod)** with async ORM
- [ ] **Redis cache** for sessions + tool results (optional but recommended)
- [ ] **msgpack serialization** for 10-100x JSON speedup
- [ ] **Jinja2 templates** pre-compiled at startup (<1ms per prompt)
- [ ] **BM25 search** for context injection (<100ms per search)
- [ ] **Kubernetes-ready** (Docker + env var configuration)
- [ ] **Performance targets** met: <2s agent spawn, <100ms tool call, <50ms prompt gen

---

## 10. Example Usage (Interactive Mode)

```bash
$ python harness.py plan "Build a REST API with authentication"

[System loads prior solutions from Knowledge Graph]
[System spawns Architect agent in parallel with SecurityReviewer]
[Architect returns design; SecurityReviewer flags auth patterns]
[System aggregates: design + security checklist]
[System enters feedback loop: Coder implements → CodeReviewer reviews → Loop]
[After 3 iterations: All criteria met]
[System saves solution to Knowledge Graph for reuse]

✓ Task Complete: REST API with auth
  - 92% code coverage
  - 0 security issues
  - 2 agents consulted
  - Completed in 4 minutes
```

---

## 10. Final Tech Stack Summary (Confirmed)

**Your Decisions:**
- ✅ **Language:** Python 3.11+ (with asyncio + type hints)
- ✅ **LLM Support:** Multi-provider (Claude → GPT → Azure → Ollama) with automatic retry/fallback
- ✅ **Execution Model:** Local + Cloud-native (Docker/Kubernetes ready)

**Recommended Stack by Layer:**

| Layer | Stack | Performance |
|-------|-------|-------------|
| **1. Loop Engine** | asyncio + uvloop + tenacity + msgpack | <2s agent spawn, <5ms journal writes |
| **2. Orchestration** | litellm + asyncio.TaskGroup + networkx | 16 parallel agents, auto LLM fallback |
| **3. Tool Calling** | httpx + aiofiles + redis/diskcache | <100ms tool calls, 100-1000x cache speedup |
| **4. Prompts** | Jinja2 (pre-compiled) + BM25 + sentence-transformers | <50ms prompt generation, <100ms search |
| **5. Persistence** | SQLAlchemy + PostgreSQL (prod) / SQLite (dev) + Redis | 10k+ queries/sec, 1000+ concurrent users |

**Database Strategy:**
- **MVP/Dev:** SQLite with WAL mode (write-ahead logging)
- **Scale-Up:** PostgreSQL with connection pooling
- **Heavy Load:** PostgreSQL + Redis + optional Elasticsearch

---

## 11. Acceptance Criteria (Final - Tech Stack Finalized)

Before we proceed to Phase 1 implementation, confirm ALL checkboxes:

**Architecture & Design:**
- [ ] 5-layer model (Loop, Orchestration, Tools, Prompts, Persistence) is correct
- [ ] Agent spawn patterns (Sequential/Parallel/Fan-out/Feedback Loop) match use case
- [ ] Prompt structure (Role + Task + Context + Format) covers all needs
- [ ] Exit conditions (success criteria, max iterations, errors) are appropriate

**Technology Choices:**
- [ ] Python 3.11+ with asyncio + uvloop is acceptable
- [ ] Multi-LLM with automatic fallback (Claude → GPT → Ollama) is correct approach
- [ ] SQLite (dev) + PostgreSQL (prod) meets scaling requirements
- [ ] Redis caching for performance-critical workloads makes sense
- [ ] Async-first design (no thread pools) is the right call

**Performance & Scale:**
- [ ] Target: <2s agent spawn, <100ms tool calls, <50ms prompts
- [ ] Target: 16 parallel agents, 1000+ concurrent users
- [ ] Target: msgpack for 10-100x JSON speedup is worthwhile
- [ ] All benchmarks achievable with recommended stack

**Implementation Scope:**
- [ ] 2500-3600 LOC across 5 phases is reasonable
- [ ] Each phase ships independently (foundation → orchestration → tools → prompts → memory)
- [ ] Dependencies listed (16 required + 8 optional) are acceptable

---

## 12. Next Steps (Ready for Implementation)

### Phase 1: Core Loop Engine (400-500 LOC)
**Deliverable:** Task can run, checkpoint, and resume autonomously

1. ✅ Create project structure + dependency management
2. ✅ Implement LoopController (with uvloop)
3. ✅ Implement TaskStateManager (with msgpack journal)
4. ✅ Implement CheckpointSystem (with recovery)
5. ✅ Implement basic completion checker
6. ✅ Write integration tests

**File Structure:**
```
src/harness/core/loop.py
src/harness/core/task_manager.py
src/harness/core/checkpoint.py
src/harness/persistence/models.py  # (early)
```

---

### Phase 2: Agent Orchestration (400-600 LOC)
**Deliverable:** Can spawn N agents in parallel, aggregate results, handle dependencies

1. ✅ Implement AgentSpawner (with multi-LLM fallback)
2. ✅ Implement AgentRegistry
3. ✅ Implement ParallelExecutor (with semaphore limiting)
4. ✅ Implement dependency graph resolver
5. ✅ Implement result aggregator
6. ✅ Integrate litellm for Claude/GPT/Ollama

**File Structure:**
```
src/harness/orchestration/agent.py
src/harness/orchestration/spawner.py
src/harness/orchestration/registry.py
src/harness/orchestration/llm_provider.py
```

---

### Phase 3: Tool Calling System (500-800 LOC)
**Deliverable:** All major tools routed through unified interface

1. ✅ Implement ToolRouter (O(1) dispatch)
2. ✅ Implement handlers: Read, Write, Edit, Bash, Grep, Glob
3. ✅ Implement caching layer (Redis or diskcache)
4. ✅ Implement per-tool retry + circuit breaker
5. ✅ Implement context budget tracking
6. ✅ Error classification + fallback logic

**File Structure:**
```
src/harness/tools/router.py
src/harness/tools/executor.py
src/harness/tools/cache.py
src/harness/tools/retry.py
```

---

### Phase 4: Prompt Optimization (600-1000 LOC)
**Deliverable:** Rich, role-optimized prompts with context injection

1. ✅ Implement PromptEngine with Jinja2 (pre-compile)
2. ✅ Create role-based templates (architect, reviewer, tdd-guide, etc.)
3. ✅ Implement context injector (BM25 search)
4. ✅ Implement constraint encoder (Pydantic schemas)
5. ✅ Implement example seeder (cached examples)
6. ✅ Tone/style adapter (Ponytail, Karpathy modes)

**File Structure:**
```
src/harness/prompts/engine.py
src/harness/prompts/context_injector.py
src/harness/prompts/constraints.py
templates/architect.j2
templates/code-reviewer.j2
templates/tdd-guide.j2
```

---

### Phase 5: State & Memory (400-700 LOC)
**Deliverable:** System learns from past runs, no repeated mistakes

1. ✅ Implement SessionManager (with async ORM)
2. ✅ Implement knowledge graph (SQLite FTS5 or PostgreSQL)
3. ✅ Implement memory search + retrieval
4. ✅ Implement task analytics + learning metrics
5. ✅ Implement multi-database support (dev/prod)
6. ✅ Add Alembic migrations for schema updates

**File Structure:**
```
src/harness/persistence/models.py
src/harness/persistence/session.py
src/harness/persistence/knowledge_graph.py
src/harness/persistence/migrations/
```

---

### CLI Entry Point (Phase 0 - Before Phase 1)
**Deliverable:** Functional CLI to accept user tasks

```bash
# Commands to implement
python -m harness.main plan "Build a REST API"
python -m harness.main run --task-id <id>
python -m harness.main resume --task-id <id>
python -m harness.main status
python -m harness.main knowledge-graph search "auth patterns"
```

**File Structure:**
```
src/harness/main.py         # CLI entry
src/harness/config.py       # Pydantic config
src/harness/logging.py      # Structured logging
```

---

### Post-Phase 5: Deployment & DevOps
- Dockerfile + docker-compose.yml
- Kubernetes manifests (.yaml)
- Environment configuration (.env.example)
- GitHub Actions CI/CD pipeline
- Performance monitoring (Prometheus + Grafana dashboards)
- Load testing (locust or k6)

---

## 13. Ready for Implementation?

**Confirm by responding with:**
1. ✅ on all acceptance criteria above
2. Which phase should we start with? (Recommend: Phase 0 CLI + Phase 1 Loop)
3. Any last questions before we begin coding?

Once confirmed, I will:
1. Generate Phase 0 (CLI scaffolding)
2. Generate Phase 1 (Core Loop Engine) with full code
3. Set up test suite + verification
4. Commit and document everything
