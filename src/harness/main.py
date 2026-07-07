"""CLI entry point using Typer."""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from harness.config import get_settings
from harness.logging import configure_logging, get_logger

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
    task_id: str = typer.Option(..., help="Task ID to run"),
    max_iterations: int = typer.Option(10, help="Max loop iterations"),
) -> None:
    """Run a task using the orchestration loop."""
    settings = get_settings()
    configure_logging(settings.log_level)

    logger.info("Running task", task_id=task_id, max_iterations=max_iterations)
    console.print(f"[bold green]Running:[/bold green] {task_id}")

    # Phase 1 hook: Will enter LoopController
    console.print("[yellow]Not yet implemented - awaiting Phase 1 (Loop Engine)[/yellow]")


@app.command()
def resume(
    task_id: str = typer.Option(..., help="Task ID to resume"),
) -> None:
    """Resume a paused task from checkpoint."""
    settings = get_settings()
    configure_logging(settings.log_level)

    logger.info("Resuming task", task_id=task_id)
    console.print(f"[bold blue]Resuming:[/bold blue] {task_id}")

    # Phase 1 hook: Will restore from checkpoint
    console.print("[yellow]Not yet implemented - awaiting Phase 1 (Checkpoint System)[/yellow]")


@app.command()
def status() -> None:
    """Show status of all active tasks."""
    settings = get_settings()
    configure_logging(settings.log_level)

    logger.info("Fetching task status")
    console.print("[bold]Active Tasks:[/bold]")

    # Phase 5 hook: Will query persistence layer
    console.print("[yellow]Not yet implemented - awaiting Phase 5 (Persistence)[/yellow]")


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
