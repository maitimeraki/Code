"""CLI entry point using Typer."""

import asyncio
import sys
from pathlib import Path
from typing import Optional
# Typer is a library that turns Python functions into CLI commands
import typer
from rich.console import Console

from harness.config import get_settings, update_mcp_server, remove_mcp_server, load_settings_file
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
    # Windows legacy consoles (cp1252) cannot encode ✓/✗ used throughout the CLI.
    # Force UTF-8 so Rich renders them everywhere (CI, pipes, and ttys alike).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    settings = get_settings()
    configure_logging(settings.log_level)

    # Parse CLI args to extract command info (if any)
    command_info = _parse_command_args(sys.argv[1:])

    # Non-interactive commands that exit without launching the app
    if command_info and command_info["command"] in {"mcp", "plugin"}:
        _run_registry_command(command_info)
        return

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

    if command == "mcp":
        # subcommands: add NAME --command CMD [--args ...] [--env K=V ...], remove NAME, list
        action = args[1] if len(args) > 1 else "list"
        if action == "add" and len(args) >= 2:
            name = args[2] if len(args) > 2 else None
            sub = {}
            i = 3
            while i < len(args):
                if args[i] == "--command" and i + 1 < len(args):
                    sub["command"] = args[i + 1]
                elif args[i] == "--url" and i + 1 < len(args):
                    sub["url"] = args[i + 1]
                elif args[i] == "--args" and i + 1 < len(args):
                    sub["args"] = args[i + 1].split(",")
                elif args[i] == "--env" and i + 1 < len(args):
                    env = {}
                    for pair in args[i + 1].split(","):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            env[k.strip()] = v.strip()
                    sub["env"] = env
                i += 1
            if name and ("command" in sub or "url" in sub):
                return {"command": "mcp", "action": "add", "name": name, "config": sub}
        elif action == "remove" and len(args) > 2:
            return {"command": "mcp", "action": "remove", "name": args[2]}
        return {"command": "mcp", "action": action}

    elif command == "plugin":
        action = args[1] if len(args) > 1 else "list"
        if action == "marketplace":
            sub = args[2] if len(args) > 2 else "list"
            if sub == "add" and len(args) > 3:
                source = args[3]
                alias = None
                i = 4
                while i < len(args):
                    if args[i] == "--alias" and i + 1 < len(args):
                        alias = args[i + 1]
                        i += 2
                    else:
                        i += 1
                return {
                    "command": "plugin",
                    "action": "marketplace",
                    "sub": sub,
                    "target": source,
                    "alias": alias,
                }
            if sub == "remove" and len(args) > 3:
                return {
                    "command": "plugin",
                    "action": "marketplace",
                    "sub": sub,
                    "target": args[3],
                }
            return {"command": "plugin", "action": "marketplace", "sub": sub}
        if action in {"install", "uninstall"} and len(args) > 2:
            return {"command": "plugin", "action": action, "target": args[2]}
        return {"command": "plugin", "action": action}

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

    elif command == "approvals":
        task_id = None
        for i, arg in enumerate(args[1:], 1):
            if arg in {"--task-id", "-id"} and i < len(args) - 1:
                task_id = args[i + 1]
        return {"command": "approvals", "task_id": task_id}

    elif command == "approve":
        approval_id = args[1] if len(args) > 1 else None
        decision = "approved"
        reason = None
        i = 2
        while i < len(args):
            if args[i] == "--reject":
                decision = "rejected"
            elif args[i] == "--reason" and i + 1 < len(args):
                reason = " ".join(args[i + 1:])
                break
            i += 1
        if approval_id:
            return {"command": "approve", "approval_id": approval_id, "decision": decision, "reason": reason}

    return None


def _run_registry_command(command_info: dict) -> None:
    """Handle `harness mcp ...` and `harness plugin ...` without launching the TUI."""
    command = command_info["command"]

    if command == "mcp":
        action = command_info.get("action", "list")
        if action == "add":
            name = command_info.get("name")
            config = command_info.get("config")
            if not name or not config:
                console.print("[yellow]Usage:[/yellow] harness mcp add <name> --command <cmd> [--args a,b] [--env K=V]")
                console.print("[yellow]  or:[/yellow] harness mcp add <name> --url <url>")
                return
            update_mcp_server(name, config)
            console.print(
                f"[bold green]✓[/bold green] MCP server "
                f"[bold]{command_info['name']}[/bold] registered in settings.json"
            )
            console.print("  Restart the harness (or plugin install) to load it.")
        elif action == "remove":
            removed = remove_mcp_server(command_info["name"])
            if removed:
                console.print(
                    f"[bold green]✓[/bold green] MCP server "
                    f"[bold]{command_info['name']}[/bold] removed from settings.json"
                )
            else:
                console.print(
                    f"[red]✗[/red] MCP server [bold]{command_info['name']}[/bold] not found"
                )
        else:  # list
            servers = load_settings_file().get("mcpServers", {}) or {}
            console.print("[bold]Configured MCP Servers:[/bold]")
            if not servers:
                console.print("  (none)")
            for name, cfg in servers.items():
                transport = cfg.get("command") or cfg.get("url") or "?"
                console.print(f"  - {name}  ({transport})")

    elif command == "plugin":
        action = command_info.get("action", "list")

        if action == "marketplace":
            _plugin_marketplace_command(command_info)
            return

        from harness.plugins import PluginInstaller

        installer = PluginInstaller()

        if action == "install":
            target = command_info["target"]
            from_marketplace = "@" in target and not Path(target).exists()
            try:
                if from_marketplace:
                    name, _, alias = target.partition("@")
                    record = installer.install_from_marketplace(name, alias)
                else:
                    record = installer.install(Path(target))
            except ValueError as exc:
                console.print(f"[red]✗[/red] {exc}")
                return
            console.print(
                f"[bold green]✓[/bold green] Plugin [bold]{record.name}[/bold] "
                f"v{record.version} installed"
            )
            if record.agent_names:
                console.print(f"  Agents: {', '.join(record.agent_names)}")
            if record.skill_names:
                console.print(f"  Skills: {', '.join(record.skill_names)}")
            if record.command_names:
                console.print(f"  Commands: {', '.join(record.command_names)}")
            if record.instruction_names:
                console.print(f"  Instructions: {', '.join(record.instruction_names)}")
            if record.rule_names:
                console.print(f"  Rules: {', '.join(record.rule_names)}")
            if record.mcp_server_names:
                console.print(f"  MCP servers: {', '.join(record.mcp_server_names)}")
            console.print("  Restart the harness to load the plugin.")
        elif action == "uninstall":
            removed = installer.uninstall(command_info["target"])
            if removed:
                console.print(
                    f"[bold green]✓[/bold green] Plugin "
                    f"[bold]{command_info['target']}[/bold] uninstalled"
                )
            else:
                console.print(
                    f"[red]✗[/red] Plugin [bold]{command_info['target']}[/bold] not installed"
                )
        else:  # list
            records = installer.list_installed()
            console.print("[bold]Installed Plugins:[/bold]")
            if not records:
                console.print("  (none)")
            for rec in records:
                counts = (
                    f"({len(rec.agent_names)}a {len(rec.skill_names)}s "
                    f"{len(rec.command_names)}c {len(rec.instruction_names)}i "
                    f"{len(rec.rule_names)}r {len(rec.mcp_server_names)}m)"
                )
                console.print(f"  - {rec.name} v{rec.version}  {counts}")


def _plugin_marketplace_command(command_info: dict) -> None:
    """Handle `harness plugin marketplace add/remove/list`."""
    from harness.config import URLFetchError
    from harness.plugins.marketplace import MarketplaceRegistry

    registry = MarketplaceRegistry()
    sub = command_info.get("sub", "list")

    if sub == "add":
        try:
            record = registry.add(command_info["target"], command_info.get("alias"))
        except (ValueError, URLFetchError) as exc:
            console.print(f"[red]✗[/red] Could not register marketplace: {exc}")
            return
        console.print(
            f"[bold green]✓[/bold green] Marketplace [bold]{record.name}[/bold] "
            f"registered (cloned to {record.path})"
        )
    elif sub == "remove":
        removed = registry.remove(command_info["target"])
        if removed:
            console.print(
                f"[bold green]✓[/bold green] Marketplace "
                f"[bold]{command_info['target']}[/bold] removed"
            )
        else:
            console.print(
                f"[red]✗[/red] Marketplace [bold]{command_info['target']}[/bold] not found"
            )
    else:  # list
        records = registry.list()
        console.print("[bold]Registered Marketplaces:[/bold]")
        if not records:
            console.print("  (none)")
        for rec in records:
            console.print(f"  - {rec.name}  ({rec.path})")


@app.command()
def run(
    task_description: str = typer.Option(..., "--task", "-t", help="Task description"),
    max_iterations: int = typer.Option(10, help="Max loop iterations"),
) -> None:
    """Run a new task using the orchestration loop."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def async_run():
        from harness.persistence.database import init_db
        await init_db()
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
        from harness.persistence.database import init_db
        await init_db()
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
        from harness.persistence.database import init_db
        await init_db()
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
def approvals(
    task_id: Optional[str] = typer.Option(None, "--task-id", "-id", help="Filter by task ID"),
) -> None:
    """List pending approval requests."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def async_approvals():
        from harness.persistence.database import init_db
        from harness.core.approval_manager import get_pending_approvals
        from harness.persistence.models import ApprovalRequest
        from sqlalchemy import select
        from harness.persistence.database import get_session

        await init_db()

        console.print("[bold]Pending Approvals:[/bold]")

        if task_id:
            # Get approvals for specific task
            pending = await get_pending_approvals(task_id)
            if not pending:
                console.print(f"  No pending approvals for task {task_id}")
                return
            for req in pending:
                console.print(f"  {req.approval_id[:8]}... - {req.summary}")
                console.print(f"    Risk: {req.risk_level}, Created: {req.created_at}")
        else:
            # Get all pending approvals
            async with get_session() as db_session:
                result = await db_session.execute(
                    select(ApprovalRequest).where(ApprovalRequest.status == "pending")
                )
                pending = result.scalars().all()
            if not pending:
                console.print("  (none)")
                return
            for req in pending:
                console.print(f"  {req.approval_id[:8]}... - Task {req.task_id[:8]}... - {req.summary}")
                console.print(f"    Risk: {req.risk_level}, Created: {req.created_at}")

    asyncio.run(async_approvals())


@app.command()
def approve(
    approval_id: str = typer.Argument(..., help="Approval ID"),
    reject: bool = typer.Option(False, "--reject", help="Reject instead of approve"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason for decision"),
) -> None:
    """Approve or reject a pending approval request."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def async_approve():
        from harness.persistence.database import init_db
        from harness.core.approval_manager import apply_decision

        await init_db()

        decision = "rejected" if reject else "approved"
        notes = reason or ""

        success = await apply_decision(approval_id, decision, decided_by="cli", notes=notes)

        if success:
            console.print(f"[bold green]✓ Approval decision recorded:[/bold green] {decision}")
            if reason:
                console.print(f"  Reason: {reason}")
        else:
            console.print(f"[bold red]✗ Failed to record decision[/bold red]")
            console.print(f"  Approval ID not found: {approval_id}")

    asyncio.run(async_approve())


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

    # Create settings.json if not exists
    import json
    settings_file = settings.get_settings_file_path()
    if not settings_file.exists():
        settings_template = {
            "env": {
                "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                "ANTHROPIC_API_KEY": "env:CODE_API_KEY",
            },
            "model": "claude-3-5-sonnet-20241022",
            "subagent_model": "claude-3-5-haiku-20241022"
        }
        settings_file.write_text(json.dumps(settings_template, indent=2))
        console.print("✓ Created settings.json")

    console.print("✓ Harness initialized")


if __name__ == "__main__":
    main()
