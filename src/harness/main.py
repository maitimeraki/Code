"""CLI entry point using Typer."""

import asyncio
from pathlib import Path
from typing import Optional
# Typer is a library that turns Python functions into CLI commands
import typer
from rich.console import Console

from harness.config import get_settings
from harness.logging import configure_logging, get_logger
from harness.core.task_manager import TaskStateManager
from harness.core.loop import LoopController
from harness.core.completion import CompletionChecker
from harness.app import HarnessApp

app = typer.Typer(help="Agent Harness")
console = Console()
logger = get_logger(__name__)


def main() -> None:
    """Main entry point - always launch UI with optional auto-execution."""
    import sys
    settings = get_settings()
    configure_logging(settings.log_level)

    # Parse CLI args to extract command info (if any)
    command_info = _parse_command_args(sys.argv[1:])

    # Always launch the app (with optional command to auto-execute)
    app_instance = HarnessApp(auto_command=command_info)

    try:
        asyncio.run(app_instance.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error("Fatal error in main", error=str(e))
        raise


def _parse_command_args(args: list[str]) -> Optional[dict]:
    """Parse command-line arguments and return command info dict or None."""
    if not args:
        return None

    # Handle help/version flags (exit early)
    if args[0] in {"--help", "-h", "--version"}:
        app()
        return None

    command = args[0]

    if command == "run":
        task_desc = None
        max_iter = 10
        for i, arg in enumerate(args[1:], 1):
            if arg in {"--task", "-t"} and i < len(args) - 1:
                task_desc = args[i + 1]
            elif arg == "--max-iterations" and i < len(args) - 1:
                try:
                    max_iter = int(args[i + 1])
                except ValueError:
                    pass
        if task_desc:
            return {"command": "run", "task": task_desc, "max_iterations": max_iter}

    elif command == "resume":
        task_id = None
        for i, arg in enumerate(args[1:], 1):
            if arg in {"--task-id", "-id"} and i < len(args) - 1:
                task_id = args[i + 1]
        if task_id:
            return {"command": "resume", "task_id": task_id}

    elif command == "status":
        return {"command": "status"}

    elif command == "init":
        return {"command": "init"}

    elif command == "knowledge-search":
        query = args[1] if len(args) > 1 else None
        limit = 5
        for i, arg in enumerate(args[1:], 1):
            if arg == "--limit" and i < len(args) - 1:
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    pass
        if query:
            return {"command": "knowledge-search", "query": query, "limit": limit}

    return None


@app.command()
def run(
    task_description: str = typer.Option(..., "--task", "-t", help="Task description"),
    max_iterations: int = typer.Option(10, help="Max loop iterations"),
) -> None:
    """Run a new task using the orchestration loop."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def async_run():
        manager = TaskStateManager(settings.get_data_dir())
        controller = LoopController(settings.get_data_dir())

        console.print(f"[bold green]Starting task:[/bold green] {task_description}")

        state = await manager.create_task(
            description=task_description,
            success_criteria={},  # Phase 2 will add criteria
            max_iterations=max_iterations,
        )

        # Phase 2 will register actual handlers (spawn agents, call tools, etc.)
        # For now, dummy handler increments iteration count
        async def dummy_work(s):
            s.results["status"] = f"Iteration {s.iteration} completed"
            console.print(f"  Iteration {s.iteration}/{max_iterations}")

        controller.register_handler("execute", dummy_work)

        # Phase 2 will define meaningful completion criteria
        checker = CompletionChecker.create_simple({})

        result = await controller.run(state, checker)

        console.print(f"[bold blue]Task completed:[/bold blue] {result.task_id}")
        console.print(f"  Status: {result.status.value}")
        console.print(f"  Iterations: {result.iteration}")
        console.print(f"  Exit reason: {result.exit_condition.value if result.exit_condition else 'N/A'}")

    asyncio.run(async_run())


@app.command()
def resume(
    task_id: str = typer.Option(..., "--task-id", "-id", help="Task ID to resume"),
) -> None:
    """Resume a paused task from checkpoint."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def async_resume():
        manager = TaskStateManager(settings.get_data_dir())
        controller = LoopController(settings.get_data_dir())

        state = await manager.load_state(task_id)
        if not state:
            console.print(f"[red]Error:[/red] No checkpoint found for task {task_id}")
            return

        console.print(f"[bold blue]Resuming:[/bold blue] {task_id}")
        console.print(f"  From iteration: {state.iteration}")

        # Phase 2: Will register actual handlers
        async def dummy_work(s):
            s.results["status"] = f"Iteration {s.iteration} completed"

        controller.register_handler("execute", dummy_work)
        checker = CompletionChecker.create_simple({})

        result = await controller.resume(task_id, checker)

        console.print(f"[bold blue]Task completed:[/bold blue] {result.task_id}")
        console.print(f"  Final iteration: {result.iteration}")

    asyncio.run(async_resume())


@app.command()
def status() -> None:
    """Show status of all active tasks."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def async_status():
        manager = TaskStateManager(settings.get_data_dir())
        task_ids = await manager.list_tasks()

        console.print("[bold]Active Tasks:[/bold]")
        if not task_ids:
            console.print("  (none)")
            return

        for task_id in task_ids:
            state = await manager.load_state(task_id)
            if state:
                console.print(f"  {task_id[:8]}... - {state.description}")
                console.print(f"    Status: {state.status.value}, Iteration: {state.iteration}/{state.max_iterations}")

    asyncio.run(async_status())


@app.command()
def knowledge_search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(5, help="Max results"),
) -> None:
    """Search knowledge graph for similar past solutions."""
    settings = get_settings()
    configure_logging(settings.log_level)

    logger.info("Searching knowledge graph", query=query, limit=limit)
    console.print(f"[bold magenta]Searching:[/bold magenta] {query}")

    # Phase 5 hook: Will query knowledge graph
    console.print("[yellow]Not yet implemented - awaiting Phase 5 (Knowledge Graph)[/yellow]")


@app.command()
def init() -> None:
    """Initialize a new harness project."""
    settings = get_settings()
    configure_logging(settings.log_level)

    console.print("[bold green]Initializing harness project...[/bold green]")

    # User-level dirs are auto-created on first access via get_*_dir()
    # Project-level dirs must be created manually by users to override user-level paths
    settings.get_data_dir()
    settings.get_templates_dir()

    # Create .env if not exists
    env_file = Path(".env")
    if not env_file.exists():
        env_file.write_text(
            """# LLM Providers
CLAUDE_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
AZURE_API_KEY=...

# Database (dev uses SQLite, prod uses PostgreSQL)
DATABASE_URL=sqlite+aiosqlite:///harness.db

# Cache (optional)
REDIS_URL=redis://localhost:6379

# Execution
EXECUTION_MODE=local
MAX_PARALLEL_AGENTS=16
MAX_AGENT_RETRIES=3
TOOL_TIMEOUT_SECONDS=30

# Logging
LOG_LEVEL=info
"""
        )
        console.print("✓ Created .env file")

    console.print("✓ Harness initialized")


if __name__ == "__main__":
    main()
