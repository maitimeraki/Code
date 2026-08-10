# Harness

**Self-improving, multi-agent orchestration system that runs autonomous coding agents in your terminal with loops, checkpoint/resume, parallel agents, a tool-calling system, MCP support, and persistent memory.**

Built like Claude Code: an interactive Rich terminal UI plus a full CLI, all in one installable Python package (Python ≥ 3.11).

---

## What is this?

Harness is a production-ready foundation for building and running **autonomous agents** long-running tasks that plan, use tools, spawn sub-agents, iterate, and resume from where they left off.

Instead of sitting at a prompt asking for permission at every step, your agent executes a task loop: it runs iterations, calls tools, spawns parallel agents, records what it learned, and checkpoints after every step. Interrupted or out of tokens? Pick it back up with one command — it resumes without re-doing completed work.

| Layer | What it does |
|-------|--------------|
| **Loop engine** | Runs tasks autonomously with automatic checkpoint/resume per iteration |
| **Agent orchestration** | Spawns up to 16 concurrent agents with automatic fallback between LLMs |
| **Multi-LLM** | Claude, OpenAI, or Azure through one interface (litellm) |
| **Tool calling** | Unified file / code / shell / HTTP execution with timeouts, retries, and output spilling |
| **MCP + plugins** | Register any Model Context Protocol server or install marketplace plugins — stored in `settings.json` |
| **Terminal UI** | Real-time Rich dashboard with command palette and live agent/tool state |
| **Memory** | NetworkX-backed knowledge graph + SQL database for cross-session learning |
| **Human approval** | Risky tool calls pause and wait for `harness approve` / `harness approvals` |

## How it helps you

- **Trust your agent to grind.** Long tasks run unattended; checkpoints mean a crash or context limit is a `resume`, not a restart.
- **Parallelize the boring work.** Fan out independent sub-tasks across up to 16 agents at once, with automatic LLM fallback if one provider fails.
- **Extend without forking.** Point any MCP server at it (`harness mcp add`) or pull plugins from a marketplace no code changes.
- **Decide what's safe.** Risk-gated tool calls queue as approval requests you can review and approve/reject from the CLI.
- **Learn across sessions.** Past solutions are stored in a knowledge graph and injected into future prompts.
- **One package, two surfaces.** Launch the full terminal UI or script the exact same engine from the CLI.

---

## Quick Start (install → running in ~60 seconds)

### 0. Prerequisites

- **Python 3.11+** (`python --version`), **git**

### 1. Install

**Unix / macOS / Git Bash:**

```bash
git clone <repo-url> code && cd code
python -m venv .venv && source .venv/bin/activate
pip install -e . && harness init
```

**Windows (PowerShell / cmd):**

```powershell
git clone <repo-url> code; cd code
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .; harness init
```

Prefer a single line (Unix/macOS/Git Bash):

```bash
git clone <repo-url> code && cd code && python -m venv .venv && source .venv/bin/activate && pip install -e . && harness init
```

That's it — `harness init` creates your config file and data directories automatically.

### 2. Provide an API key

Set one of these (it's read at launch):

```bash
export CODE_API_KEY="sk-ant-..."      # Claude / Anthropic (default)
# or: export OPENAI_API_KEY="sk-..."  # OpenAI
# or: export AZURE_API_KEY="..."      # Azure
```

Or, instead of exporting, create a `.env` in the project root:

```
CODE_API_KEY=sk-ant-...
```

### 3. Run your first task

```bash
harness run --task "Build a REST API with authentication" --max-iterations 20
```

Or launch the interactive terminal UI, then type tasks in the prompt:

```bash
harness
```

### Verify it works

```bash
harness status          # → shows your in-progress / completed tasks
harness knowledge-search "auth patterns"   # → searches learned context
```

---

## CLI Reference

| Command | What it does |
|---------|--------------|
| `harness` | Launch the interactive Rich terminal UI |
| `harness run --task "..." [--max-iterations N]` | Run a task autonomously through the loop |
| `harness resume --task-id <id>` | Resume a task from its last checkpoint |
| `harness status` | List all tasks and their progress |
| `harness knowledge-search <query> [--limit N]` | Search past solutions in the knowledge graph |
| `harness approvals [--task-id <id>]` | List pending human-approval requests |
| `harness approve <approval-id> [--reject] [--reason "..."]` | Approve / reject a queued risky action |
| `harness init` | Create `settings.json` + data directories |
| `harness mcp add <name> --command <cmd>` | Register an MCP server (stdin/stdout) |
| `harness mcp add <name> --url <url>` | Register an MCP server (HTTP) |
| `harness mcp remove <name>` / `harness mcp list` | Remove / list registered MCP servers |
| `harness plugin install <path-or-name@version>` | Install a plugin (or from a marketplace) |
| `harness plugin uninstall <name>` / `harness plugin list` | Remove / list installed plugins |
| `harness plugin marketplace add <source>` | Register a plugin marketplace (git URL) |

---

## Configuration

All configuration lives in **`settings.json`** (Claude-Code style), created by `harness init` and resolved project-first, then user-level (`~/.code/`) — with a `.env` file as a fallback. MCP servers and plugins you add are stored right here.

```json
{
  "env": {
    "CODE_BASE_URL": "https://api.anthropic.com",
    "CODE_API_KEY": "env:CODE_API_KEY"
  },
  "model": "claude-3-5-sonnet-20241022",
  "subagent_model": "claude-3-5-haiku-20241022",
  "mcpServers": {}
}
```

Key environment variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `CODE_API_KEY` | Claude / Anthropic API key (base URL overrideable via `CODE_BASE_URL`) | `https://api.anthropic.com` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `AZURE_API_KEY` | Azure API key | — |
| `DATABASE_URL` | `sqlite+aiosqlite:///harness.db` (dev) or `postgresql+asyncpg://...` (prod) | SQLite |
| `MAX_PARALLEL_AGENTS` | Concurrent agent cap | `16` |
| `TOOL_TIMEOUT_SECONDS` | Per-tool execution timeout | `30` |

---

## Architecture

**5-layer design** — files mirror this layout under `src/harness/`.

| Layer | Module | Responsibility |
|-------|--------|----------------|
| **1. Loop Engine** | `core/` | `LoopController` async loop, `TaskStateManager` checkpoint/resume, `CompletionChecker`, error memory |
| **2. Orchestration** | `orchestration/` | `HarnessOrchestrator` coordinates agents + tools + prompts; `AgentSpawner` runs up to 16 in parallel |
| **3. Tool Calling** | `tools/` | `ToolRouter` → handlers; `ToolExecutor` wraps timeout + retries; `output_cap` spills huge outputs to cache; `mcp_manager` bridges MCP servers |
| **4. Prompting** | `prompts/` | Jinja2 templates, `context_injector` BM25-ranked context, token/role constraints |
| **5. State & Memory** | `persistence/` | NetworkX + SQLAlchemy knowledge graph, session state, `database` pooling, `transient_cache` |

**Terminal UI** (`ui/`): concurrent input loop + `Rich.Live` display (rendering → keyboard → live streams → agent/tool state → command actions), so output streams with zero flicker.

**Key patterns:** everything is async (`asyncio`); state persists after every loop iteration; agents run in a `TaskGroup` with automatic LLM fallback; large tool outputs spill to a persistent cache and return a reference.

---

## Development

```bash
# Install dev tooling (pytest, ruff, black, mypy)
pip install -e ".[dev]"

# Test with coverage (target ≥80%)
pytest -v --cov=src/harness

# Lint / type-check / format
ruff check src/
mypy src/harness
black src/ tests/

# Debug logging (verbose) — run the TUI or a task with full logs
LOG_LEVEL=debug python -m harness.main
```

**Extending the harness:**

- **New tool** → add a `@tool_handler("name")` in `src/harness/tools/handlers.py`, return `ToolResult(status, output, metadata)`; it's auto-discovered.
- **New agent type** → extend `AgentConfig` in `orchestration/agent.py`, implement in `AgentSpawner.spawn()`, add a Jinja2 prompt in `prompts/`.
- **New MCP server** → `harness mcp add <name> --command <cmd>`; it's persisted in `settings.json`.
- Suggested flow: research existing solutions first → plan → write tests (TDD) → review → commit (conventional commits).

---

## Contributing

1. **Research first** — check for existing implementations before writing new code
2. **Plan** — use `/plan` for complex features
3. **TDD** — write tests before implementation
4. **Review** — use `/code-review` after writing
5. **Commit** — conventional commits (`feat:`, `fix:`, …)

See `CLAUDE.md` for detailed architecture, path resolution, and workflows.

## License

MIT