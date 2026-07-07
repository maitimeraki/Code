"""CLI entry point using Typer."""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from harness.config import get_settings
from harness.logging import configure_logging, get_logger
from harness.core.task_manager import TaskStateManager
from harness.core.loop import LoopController
from harness.core.completion import CompletionChecker

app = typer.Typer(help="Sophisticated Agent Harness CLI")
console = Console()
logger = get_logger(__name__)


@app.command()
def plan(
    task: str = typer.Argument(..., help="Task description"),
    output: Optional[Path] = typer.Option(None, help="Save plan to file"),
) -> None:
    """Plan a new task using Architect agent."""
    settings = get_settings()
    configure_logging(settings.log_level)

    logger.info("Planning task", task=task)
    console.print(f"[bold cyan]Planning:[/bold cyan] {task}")

    # Phase 1 hook: Will spawn Architect agent
    console.print("[yellow]Not yet implemented - awaiting Phase 1 (Orchestration)[/yellow]")


@app.command()
def run(
    task_description: str = typer.Option(..., "--task", "-t", help="Task description"),
    max_iterations: int = typer.Option(10, help="Max loop iterations"),
) -> None:
    """Run a new task using the orchestration loop."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def async_run():
        manager = TaskStateManager(settings.data_dir)
        controller = LoopController(settings.data_dir)

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
        manager = TaskStateManager(settings.data_dir)
        controller = LoopController(settings.data_dir)

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
        manager = TaskStateManager(settings.data_dir)
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

    # Create data and templates directories
    settings.data_dir.mkdir(exist_ok=True)
    settings.templates_dir.mkdir(exist_ok=True)

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


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
