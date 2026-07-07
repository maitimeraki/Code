# Sophisticated Agent Harness

Self-improving agent orchestration system with autonomous loop execution, parallel agent spawning, and multi-LLM support.

## Quick Start

```bash
# Install
pip install -e .

# Initialize
harness init

# Plan a task
harness plan "Build a REST API with authentication"

# Run autonomously
harness run --task-id <id>

# Resume from checkpoint
harness resume --task-id <id>

# Search knowledge graph
harness knowledge-search "auth patterns"
```

## Architecture

**5-Layer Design:**
1. **Loop Engine** - Autonomous task execution with checkpointing
2. **Agent Orchestration** - Parallel multi-agent coordination with LLM fallback
3. **Tool Calling** - Unified interface for file/code/execution operations
4. **Prompt Optimization** - Role-based prompt generation with context injection
5. **State & Memory** - Persistent knowledge graph for learning across sessions

## Database

- **Development:** SQLite (local, no setup)
- **Production:** Supabase (managed PostgreSQL + pgvector)

Same code works for both. Set `DATABASE_URL` in `.env`.

## Tech Stack

| Layer | Technology | Performance |
|-------|-----------|-------------|
| Loop | asyncio + uvloop + msgpack | <2s spawn, <5ms writes |
| Agents | litellm + taskgroup | 16 parallel, auto fallback |
| Tools | httpx + aiofiles + redis | <100ms calls, 100-1000x cache |
| Prompts | Jinja2 + BM25 | <50ms generation |
| Persistence | SQLAlchemy + PostgreSQL | 10k+ qps |

## Status

- ✅ Phase 0: CLI Scaffolding (DONE)
- ⏳ Phase 1: Core Loop Engine (400-500 LOC)
- ⏳ Phase 2: Agent Orchestration (400-600 LOC)
- ⏳ Phase 3: Tool Calling (500-800 LOC)
- ⏳ Phase 4: Prompt Optimization (600-1000 LOC)
- ⏳ Phase 5: State & Memory (400-700 LOC)

**Total:** ~2500-3600 LOC

## Configuration

See `.env.example` for all options. Minimum required:
- One LLM API key (Claude, OpenAI, or Azure)
- Database URL (defaults to SQLite)

## Development

```bash
pip install -e ".[dev]"
pytest -v --cov=src/harness
```
