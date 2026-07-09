# code.md

This file provides guidance to code Code (code.ai/code) when working with code in this repository.

## Quick Setup

```bash
# Install in development mode
pip install -e .

# Install with dev dependencies (testing, linting, type checking)
pip install -e ".[dev]"

# Initialize project (creates .env and directories)
harness init

# Run tests with coverage
pytest -v --cov=src/harness
```

## Running the Application

The harness has two modes:

**Interactive Terminal UI (default):**
```bash
python -m harness.main
# Or via CLI if installed:
harness
```
Launches a Rich-based terminal UI styled like code Code with input handler, command palette, and live output streaming.

**CLI Mode (specific commands):**
```bash
harness run --task "Build a REST API with authentication"
harness resume --task-id <id>
harness status
harness knowledge-search "auth patterns"
```

## Architecture Overview

**5-Layer Design** (see README.md for detailed roadmap):

1. **Loop Engine** (`src/harness/core/`)
   - `loop.py`: `LoopController` - Async task execution loop with checkpoint/resume
   - `task_manager.py`: `TaskStateManager` - Persistent task state (SQLite/PostgreSQL)
   - `models.py`: `TaskState` - Complete task state for serialization
   - `completion.py`: `CompletionChecker` - Success criteria evaluation

2. **Agent Orchestration** (`src/harness/orchestration/`)
   - `orchestrator.py`: `HarnessOrchestrator` - Coordinates agents + tools + prompts
   - `spawner.py`: `AgentSpawner` - Spawns parallel agents (up to 16 concurrent)
   - `agent.py`: `AgentConfig`, `AgentResult` - Agent state and results

3. **Tool Calling** (`src/harness/tools/`)
   - `router.py`: `ToolRouter` - Routes tool calls to handlers
   - `executor.py`: `ToolExecutor` - Executes tools with timeout + retry logic
   - `handlers.py`: Tool-specific handlers (file ops, code execution, etc.)
   - `models.py`: `ToolCall`, `ToolResult` - Tool request/response format

4. **Prompt Optimization** (`src/harness/prompts/`)
   - `engine.py`: `PromptEngine` - Generates prompts from templates
   - `context_injector.py`: Injects relevant context (BM25 ranking)
   - `constraints.py`: Token budget, role-based constraints

5. **State & Memory** (`src/harness/persistence/`)
   - `knowledge_graph.py`: Query/store past solutions (NetworkX + DB)
   - `session.py`: `SessionManager` - Session state persistence
   - `models.py`: SQLAlchemy ORM models

**Terminal UI** (`src/harness/ui/`)
- Organized as Phase 2A-2E:
  - **2A**: Rendering (Rich components, styling)
  - **2B**: Keyboard input (keybinds, input handler)
  - **2C**: Real-time streams (log listener, aggregator)
  - **2D**: Agent state display (agent view, tool view)
  - **2E**: Command actions (command execution)

## Configuration

`.env` file (created by `harness init`):
```
code_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
DATABASE_URL=sqlite+aiosqlite:///harness.db
REDIS_URL=redis://localhost:6379  # optional, for caching
MAX_PARALLEL_AGENTS=16
TOOL_TIMEOUT_SECONDS=30
LOG_LEVEL=info
```

Programmatic config: `src/harness/config.py` → `Settings` (Pydantic).

### Path Resolution (code Code Standard)

Following code Code's pattern, all resource paths resolve with **project-level priority**:

**Agents:**
- Project: `./.code/agents/` (if exists, used first)
- User: `~/.code/agents/` (fallback, auto-created)
- Access: `settings.get_agents_dir()`

**Skills:**
- Project: `./.code/skills/` (if exists, used first)
- User: `~/.code/skills/` (fallback, auto-created)
- Access: `settings.get_skills_dir()`

**Config:**
- Project: `./.code/` (if exists, used first)
- User: `~/.code/` (fallback, auto-created)
- Access: `settings.get_config_dir()`

**Data (Task Checkpoints):**
- Project: `./.code/data/` (if exists, used first)
- User: `~/.code/data/` (fallback, auto-created)
- Access: `settings.get_data_dir()`

**Templates (Prompts):**
- Project: `./.code/templates/` (if exists, used first)
- User: `~/.code/templates/` (fallback, auto-created)
- Access: `settings.get_templates_dir()`

**Resolution Pattern:**
1. User-level dirs (`.code/`) are auto-created on first access via `mkdir(parents=True, exist_ok=True)`
2. Project-level dirs are not auto-created—users must explicitly create them to override user-level paths
3. Resolver methods return project path if it exists, otherwise return user path
4. Use resolver methods (`get_*_dir()`) instead of direct path properties for runtime resolution

## Development

**Common tasks:**

```bash
# Run all tests
pytest -v --cov=src/harness

# Run specific test
pytest tests/test_loop.py -v

# Format code
black src/ tests/

# Type checking
mypy src/harness

# Linting
ruff check src/

# Run main app with debug logging
LOG_LEVEL=debug python -m harness.main
```

**Entry point flow:**
1. `src/harness/main.py` → `main()` checks for CLI args
2. If no args → launches `HarnessApp().run()` (TUI mode)
3. If args → delegates to Typer CLI handlers (`run`, `resume`, `status`, etc.)
4. TUI → `TerminalUI.run()` → concurrent input loop + display loop

**UI event loop** (`src/harness/ui/terminal.py`):
- Renders layout with Rich.Live (auto_refresh enabled)
- Input handler listens for key events in separate task
- StreamAggregator collects logs + tool output
- CommandPalette routes user commands to `CommandActions`

## Key Design Patterns

**Async-first:** All I/O (DB, API, file) is async. Use `asyncio.run()` in CLI handlers.

**Checkpoint/Resume:** `TaskStateManager` persists state after each iteration. Loop can resume from `task_id`.

**Parallel agents:** `AgentSpawner` uses `TaskGroup` for concurrent agent execution (up to `MAX_PARALLEL_AGENTS`).

**Tool execution:** `ToolRouter` dispatches to handler, `ToolExecutor` wraps with timeout + retry logic.

**Real-time UI:** `Live` display with `auto_refresh=True` + concurrent input polling (no flickering).

## Common Workflows

**Adding a new command:**
1. Add handler in `src/harness/main.py` with `@app.command()`
2. Implement async logic
3. Return results via Rich console or update UI state

**Adding a new tool:**
1. Define handler in `src/harness/tools/handlers.py`
2. Register in `ToolRouter.register()`
3. Return `ToolResult` (status + output + metadata)

**Adding a new agent type:**
1. Extend `AgentConfig` in `src/harness/orchestration/agent.py`
2. Implement in `AgentSpawner.spawn()`
3. Prompt templates in `src/harness/prompts/` (Jinja2)

**Testing UI interactions:**
- Use `pytest` + `pytest-asyncio` for async tests
- Mock Rich `Console` or use capsys for output capture
- See `tests/test_ui_functionality.py` for examples

## Dependencies

**Core runtime:** asyncio, aiofiles, httpx, msgpack
**Multi-LLM:** litellm (code, OpenAI, Azure)
**Database:** SQLAlchemy, asyncpg (PostgreSQL in prod, SQLite in dev)
**UI:** Rich (terminal styling + Live display)
**Prompts:** Jinja2, rank-bm25 (context ranking)
**Orchestration:** taskgroup (Python 3.11+ feature)
**Monitoring:** structlog, prometheus-client

See `pyproject.toml` for exact versions.

## Using the Path Resolution System

The harness follows **code Code's standard directory layout** with project-level and user-level overrides.

### Directory Structure

**User-level** (auto-created, for global settings):
```
~/.code/
├── agents/         # Global agents
├── skills/         # Global skills
├── data/           # Global task checkpoints
├── templates/      # Global prompt templates
└── config/         # Global config files
```

**Project-level** (create explicitly to override user-level):
```
./.code/
├── agents/         # Project agents (overrides ~/.code/agents/)
├── skills/         # Project skills (overrides ~/.code/skills/)
├── data/           # Project data (overrides ~/.code/data/)
├── templates/      # Project templates (overrides ~/.code/templates/)
└── config/         # Project config (overrides ~/.code/)
```

### Example: Override User Settings at Project Level

```bash
# Create project-level directories to override user-level paths
mkdir -p ./.code/agents
mkdir -p ./.code/skills
mkdir -p ./.code/data
mkdir -p ./.code/templates

# Copy or create project-specific agents/skills
cp ~/.code/agents/architect.md ./.code/agents/
```

### In Code

```python
from harness.config import get_settings

settings = get_settings()

# Get resolved path (project-level if exists, else user-level)
agents_path = settings.get_agents_dir()          # Returns ./.code/agents or ~/.code/agents
skills_path = settings.get_skills_dir()          # Returns ./.code/skills or ~/.code/skills
data_path = settings.get_data_dir()              # Returns ./.code/data or ~/.code/data
templates_path = settings.get_templates_dir()    # Returns ./.code/templates or ~/.code/templates
config_path = settings.get_config_dir()          # Returns ./.code or ~/.code

# Get specific directory (without resolution)
user_agents = settings.user_agents_dir           # Always ~/.code/agents/
project_agents = settings.project_agents_dir     # Always ./.code/agents/ (may not exist)
```

## Debugging Tips

**Enable verbose logging:**
```bash
LOG_LEVEL=debug python -m harness.main
```

**Check database state:**
```bash
sqlite3 harness.db
SELECT * FROM tasks;
```

**Watch task execution:**
- TUI shows real-time logs in main panel
- Check `.data/` directory for checkpoint files

**UI not rendering?**
- Ensure `TerminalUI.run()` is awaited (async context)
- Check for exceptions in task logs
- Verify `auto_refresh=True` in Rich Live

## Phase Roadmap

Phase 0 (DONE): CLI scaffolding + config management
Phase 1 (TODO): Core loop engine (checkpoint/resume)
Phase 2 (IN PROGRESS): Terminal UI + agent orchestration
Phase 3 (TODO): Tool calling + execution
Phase 4 (TODO): Prompt optimization + role-based generation
Phase 5 (TODO): Knowledge graph + learning

See README.md for details.
