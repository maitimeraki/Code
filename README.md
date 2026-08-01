# Agent Harness

Self-improving agent orchestration system with autonomous loop execution, parallel agent spawning, and multi-LLM support. Built like Claude Code with extensible tool calling, persistent knowledge graph, and checkpoint/resume capability.

## Features

- **Autonomous Loops** - Execute long-running tasks with automatic checkpointing and resume capability
- **Parallel Agents** - Spawn up to 16 concurrent agents with automatic fallback between LLMs
- **Multi-LLM Support** - Switch between Claude, OpenAI, Azure seamlessly via litellm
- **Rich Terminal UI** - Real-time progress with Rich-based dashboard and command palette
- **Persistent Knowledge** - NetworkX-backed knowledge graph for cross-session learning
- **Tool Orchestration** - Unified interface for file operations, code execution, and external APIs
- **Database Flexibility** - SQLite for development, PostgreSQL/Supabase in production

## Quick Start

### Installation

```bash
# Clone repository
git clone <repo-url>
cd code

# Install in development mode
pip install -e .

# Install with dev dependencies (testing, type checking, linting)
pip install -e ".[dev]"

# Initialize project (creates .env, directories)
harness init
```

### Running

**Interactive Terminal UI (default):**
```bash
python -m harness.main
```

Launches a Rich-based terminal with command palette, real-time output streaming, and live agent state tracking.

**CLI Mode (specific operations):**
```bash
# Run a task autonomously
harness run --task "Build a REST API with authentication"

# Resume from checkpoint
harness resume --task-id <task-id>

# Check task status
harness status --task-id <task-id>

# Search knowledge graph
harness knowledge-search "auth patterns"
```

### Configuration

Create `.env` after running `harness init`:

```env
# LLM API Keys (at least one required)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
AZURE_API_KEY=...

# Database
DATABASE_URL=sqlite+aiosqlite:///harness.db
# For PostgreSQL/Supabase:
# DATABASE_URL=postgresql+asyncpg://user:pass@host/db

# Optional
REDIS_URL=redis://localhost:6379
MAX_PARALLEL_AGENTS=16
TOOL_TIMEOUT_SECONDS=30
LOG_LEVEL=info
```

## Architecture

**5-Layer Design** (3000-4000 LOC total):

### 1. Loop Engine (`src/harness/core/`)
Autonomous task execution with checkpoint/resume.

| File | Purpose |
|------|---------|
| `loop.py` | `LoopController` - Async iteration with state persistence |
| `task_manager.py` | `TaskStateManager` - Checkpoints, resume, state tracking |
| `models.py` | `TaskState` - Serializable task state |
| `completion.py` | `CompletionChecker` - Success criteria evaluation |
| `error_memory.py` | Error tracking and retry logic |

**Pattern:** Loop persists state after each iteration. Tasks resume from checkpoint without re-executing completed work.

### 2. Agent Orchestration (`src/harness/orchestration/`)
Parallel multi-agent coordination with LLM fallback.

| File | Purpose |
|------|---------|
| `orchestrator.py` | `HarnessOrchestrator` - Coordinates agents + tools + prompts |
| `spawner.py` | `AgentSpawner` - Spawns agents concurrently (up to 16) |
| `agent.py` | `AgentConfig`, `AgentResult` - Agent configuration and results |

**Pattern:** Orchestrator delegates work to agents, collects results, manages timeouts and retries.

### 3. Tool Calling (`src/harness/tools/`)
Unified interface for file operations, code execution, API calls.

| File | Purpose |
|------|---------|
| `router.py` | `ToolRouter` - Routes tool calls to handlers |
| `executor.py` | `ToolExecutor` - Wraps execution with timeout + retry |
| `handlers.py` | Tool-specific handlers (file, code, shell, http) |
| `models.py` | `ToolCall`, `ToolResult` - Request/response format |
| `factory.py` | Tool definition factory |
| `output_cap.py` | Output spilling for oversized results |

**Pattern:** Tools return `ToolResult(status, output, metadata)`. Large outputs are spilled to persistent cache.

### 4. Prompt Optimization (`src/harness/prompts/`)
Role-based prompt generation with context injection.

| File | Purpose |
|------|---------|
| `engine.py` | `PromptEngine` - Renders templates with context |
| `context_injector.py` | BM25-ranked context retrieval |
| `constraints.py` | Token budget and role-specific constraints |

**Pattern:** Prompts are Jinja2 templates with injected context from knowledge graph.

### 5. State & Memory (`src/harness/persistence/`)
Persistent knowledge graph and session state.

| File | Purpose |
|------|---------|
| `knowledge_graph.py` | Query/store past solutions (NetworkX + DB) |
| `session.py` | `SessionManager` - Session state persistence |
| `models.py` | SQLAlchemy ORM definitions |
| `database.py` | Connection pool and migrations |
| `transient_cache.py` | In-memory cache for tool output |

**Pattern:** All state flows through database. NetworkX graph enables pattern recognition across sessions.

### Terminal UI (`src/harness/ui/`)
Real-time progress tracking with Rich.

| Phase | Purpose |
|-------|---------|
| 2A | Rendering - Rich components, layout styling |
| 2B | Keyboard input - Keybinds, command palette |
| 2C | Real-time streams - Log aggregation, output streaming |
| 2D | Agent state - Agent view, tool results display |
| 2E | Command actions - Execute user commands |

**Pattern:** Concurrent input loop + display loop with `Rich.Live` (no flickering).

## Tech Stack

| Layer | Technology | Performance |
|-------|-----------|-------------|
| Loop | asyncio + uvloop + msgpack | <2s spawn, <5ms writes |
| Agents | litellm + TaskGroup | 16 parallel, auto fallback |
| Tools | httpx + aiofiles + Redis | <100ms calls, 100-1000x cache |
| Prompts | Jinja2 + BM25 | <50ms generation |
| Persistence | SQLAlchemy + PostgreSQL | 10k+ qps |
| UI | Rich (Live + Console) | <50ms render |

## Development

### Common Tasks

```bash
# Run tests with coverage
pytest -v --cov=src/harness

# Run specific test
pytest tests/test_loop.py::test_checkpoint -v

# Type checking
mypy src/harness

# Linting
ruff check src/

# Format code
black src/ tests/

# Debug mode (verbose logging)
LOG_LEVEL=debug python -m harness.main
```

### Adding a New Tool

1. Define handler in `src/harness/tools/handlers.py`
2. Register in `ToolRouter` (auto-discovered from handlers)
3. Return `ToolResult(status, output, metadata)`

```python
@tool_handler("my_tool")
async def handle_my_tool(params: dict) -> ToolResult:
    # Implementation
    return ToolResult(
        status="success",
        output="Result here",
        metadata={"key": "value"}
    )
```

### Adding a New Agent Type

1. Extend `AgentConfig` in `src/harness/orchestration/agent.py`
2. Implement in `AgentSpawner.spawn()`
3. Add Jinja2 template in `src/harness/prompts/`

### Testing

**Write tests first (TDD):**
```bash
pytest tests/test_my_feature.py -v
```

**Check coverage:**
```bash
pytest --cov=src/harness --cov-report=html
# Open htmlcov/index.html
```

Target: 80%+ coverage.

## Configuration & Paths

Follows **Claude Code standard** with project-level and user-level overrides.

### Directory Resolution

```
Project-level (explicit override):
./.code/
├── agents/     # Project-specific agents
├── skills/     # Project-specific skills
├── data/       # Project task checkpoints
├── templates/  # Project prompt templates
└── config/     # Project config

User-level (default, auto-created):
~/.code/
├── agents/
├── skills/
├── data/
├── templates/
└── config/
```

**In code:**
```python
from harness.config import get_settings

settings = get_settings()
agents_path = settings.get_agents_dir()    # ./.code/agents or ~/.code/agents
data_path = settings.get_data_dir()        # ./.code/data or ~/.code/data
```

**Priority:** Project-level paths (if exist) override user-level paths.

## Key Design Patterns

### Async-First
All I/O (database, files, APIs) is async. Use `asyncio.run()` for CLI entry points.

### Checkpoint/Resume
`TaskStateManager` persists complete task state after each loop iteration:
```python
# Resume doesn't re-execute completed steps
await loop.resume(task_id)
```

### Parallel Agents with Fallback
`AgentSpawner` manages concurrent execution with automatic LLM fallback:
```python
# If Claude fails, try OpenAI automatically
agents = await spawner.spawn(count=4, fallback_models=["gpt-4", "gpt-3.5"])
```

### Tool Output Spilling
Large tool outputs are stored in persistent cache, not returned directly:
```python
# If output > cap, store in cache and return reference
result = ToolResult(output="...", metadata={"spilled": True, "cache_key": "abc123"})
```

### Context Injection
Prompts include ranked context from knowledge graph (BM25):
```python
# Relevant past solutions automatically injected into prompt
prompt = await engine.render("task", context=injector.get_context("auth"))
```

## Debugging

### Enable Verbose Logging
```bash
LOG_LEVEL=debug python -m harness.main
```

### Check Database State
```bash
sqlite3 harness.db
SELECT * FROM tasks ORDER BY created_at DESC;
SELECT * FROM tool_calls WHERE task_id = '<id>';
```

### Monitor Task Execution
- TUI shows real-time logs in main panel
- Check `.code/data/` for checkpoint files
- Exceptions logged to `.code/logs/` (if configured)

### UI Not Rendering?
- Ensure `TerminalUI.run()` is awaited (async context)
- Check Rich console for rendering errors
- Verify `auto_refresh=True` in Live display

## Dependencies

**Core runtime:**
- asyncio, aiofiles, httpx, msgpack

**Multi-LLM:**
- litellm (Claude, OpenAI, Azure, others)

**Database:**
- SQLAlchemy, asyncpg (PostgreSQL), aiosqlite (SQLite)

**UI:**
- Rich (terminal styling, Live display)

**Prompts:**
- Jinja2, rank-bm25 (context ranking)

**Orchestration:**
- asyncio.TaskGroup (Python 3.11+)

**Monitoring:**
- structlog, prometheus-client

See `pyproject.toml` for exact versions.

## Contributing

1. **Research first** - Check existing implementations before new code
2. **Plan** - Use `/plan` skill for complex features
3. **TDD** - Write tests before implementation
4. **Review** - Use `/code-review` skill after writing
5. **Commit** - Conventional commits format (feat:, fix:, etc.)

See CLAUDE.md for detailed workflows.

## License

MIT

## Support

- **Documentation:** See CLAUDE.md for architecture details, paths, debugging
- **Issues:** GitHub issues for bugs, feature requests
- **Development:** `pip install -e ".[dev]"` for local setup

---

**Built for Claude Code.** Extensible, observable, and designed for autonomous agent workflows.
