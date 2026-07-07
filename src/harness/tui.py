"""Terminal User Interface with rich formatting and live updates."""

from typing import Optional, Callable, Any
from datetime import datetime
import asyncio

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text


class HarnessUI:
    """Terminal UI for Harness agent orchestration."""

    def __init__(self):
        self.console = Console()

    def show_header(self) -> None:
        """Display application header."""
        header = Panel(
            "[bold cyan]🤖 Sophisticated Agent Harness[/bold cyan]\n"
            "[dim]Autonomous Multi-Agent Orchestration[/dim]",
            expand=False,
            border_style="cyan",
        )
        self.console.print(header)

    def show_main_menu(self) -> str:
        """Display main menu and get user choice."""
        self.console.print()
        menu_items = [
            "[1] [bold green]➕ Create New Task[/bold green]",
            "[2] [bold blue]▶️ Resume Task[/bold blue]",
            "[3] [bold magenta]📊 Task Status[/bold magenta]",
            "[4] [bold cyan]🔍 Search Knowledge Graph[/bold cyan]",
            "[5] [bold yellow]⚙️ Settings[/bold yellow]",
            "[0] [bold red]❌ Exit[/bold red]",
        ]

        menu_panel = Panel(
            "\n".join(menu_items),
            title="[bold]Main Menu[/bold]",
            border_style="blue",
            expand=False,
        )
        self.console.print(menu_panel)
        return self.console.input("[bold cyan]Select option:[/bold cyan] ")

    def create_task_form(self) -> tuple[str, dict[str, Any]]:
        """Interactive form to create a new task."""
        self.console.clear()
        self.show_header()

        form_panel = Panel(
            "[bold]Create New Task[/bold]\n"
            "[dim]Answer a few questions to get started[/dim]",
            border_style="green",
        )
        self.console.print(form_panel)
        self.console.print()

        # Get task description
        description = self.console.input(
            "[bold cyan]📝 Task description:[/bold cyan] "
        ).strip()

        # Get success criteria
        self.console.print("[bold cyan]✓ Success Criteria[/bold cyan]")
        self.console.print("[dim]Enter criteria as 'name: threshold' (e.g., 'coverage: 0.8')[/dim]")

        criteria = {}
        while True:
            criterion = self.console.input(
                "[cyan]  Add criterion (or press Enter to skip):[/cyan] "
            ).strip()
            if not criterion:
                break

            try:
                name, value = criterion.split(":")
                name = name.strip()
                value_str = value.strip()

                # Try to parse as number
                try:
                    value = float(value_str)
                except ValueError:
                    value = value_str

                criteria[name] = value
                self.console.print(f"  ✓ Added: {name} = {value}")
            except ValueError:
                self.console.print("[red]  ✗ Invalid format[/red]")

        # Get max iterations
        max_iter = self.console.input(
            "[bold cyan]🔄 Max iterations:[/bold cyan] (default 10) "
        ).strip()
        max_iterations = int(max_iter) if max_iter else 10

        return description, {
            "success_criteria": criteria,
            "max_iterations": max_iterations,
        }

    async def show_task_progress(
        self,
        task_id: str,
        state_getter: Callable,
        max_iterations: int = 10,
    ) -> None:
        """Display live task progress with real-time updates."""
        self.console.clear()
        self.show_header()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.1f}%"),
            console=self.console,
            expand=False,
        ) as progress:
            task = progress.add_task(
                f"[cyan]Executing task {task_id[:8]}...[/cyan]",
                total=max_iterations,
                visible=True,
            )

            # Live update loop
            while True:
                state = await state_getter(task_id)
                if not state:
                    break

                progress.update(task, completed=state.iteration)

                # Show iteration info
                status_text = f"[bold cyan]Iteration {state.iteration}/{max_iterations}[/bold cyan]"
                if state.criteria_met:
                    met_count = sum(1 for v in state.criteria_met.values() if v)
                    status_text += f" | Criteria: {met_count}/{len(state.criteria_met)}"

                progress.update(task, description=status_text)

                # Check if complete
                if state.status.value in ("completed", "failed", "paused"):
                    break

                await asyncio.sleep(0.5)

    def show_task_result(self, state: Any) -> None:
        """Display task completion result."""
        self.console.print()

        # Result panel
        status_color = "green" if state.status.value == "completed" else "red"
        result_text = (
            f"[bold {status_color}]Status: {state.status.value.upper()}[/bold {status_color}]\n"
            f"[cyan]Task ID:[/cyan] {state.task_id}\n"
            f"[cyan]Iterations:[/cyan] {state.iteration}/{state.max_iterations}\n"
            f"[cyan]Exit Reason:[/cyan] {state.exit_condition.value if state.exit_condition else 'N/A'}"
        )

        if state.started_at and state.completed_at:
            elapsed = (state.completed_at - state.started_at).total_seconds()
            result_text += f"\n[cyan]Time Elapsed:[/cyan] {elapsed:.2f}s"

        result_panel = Panel(
            result_text,
            title="[bold]Task Complete[/bold]",
            border_style=status_color,
        )
        self.console.print(result_panel)

        # Criteria results
        if state.criteria_met:
            self.console.print()
            self.console.print("[bold]✓ Criteria Met:[/bold]")
            for criterion, met in state.criteria_met.items():
                icon = "✅" if met else "❌"
                self.console.print(f"  {icon} {criterion}: {met}")

        # Errors
        if state.errors:
            self.console.print()
            self.console.print("[bold red]⚠️ Errors:[/bold red]")
            for error in state.errors:
                self.console.print(f"  [red]{error}[/red]")

    def show_task_table(self, tasks: list[dict]) -> None:
        """Display tasks in a formatted table."""
        table = Table(title="Active Tasks", show_header=True, header_style="bold cyan")
        table.add_column("Task ID", style="dim", width=10)
        table.add_column("Description", width=30)
        table.add_column("Status", width=12)
        table.add_column("Iteration", width=12)
        table.add_column("Progress", width=20)

        for task in tasks:
            task_id_short = task["task_id"][:8]
            status = task["status"]
            iteration = f"{task['iteration']}/{task['max_iterations']}"

            # Progress bar
            progress_pct = (task["iteration"] / task["max_iterations"]) * 100
            progress_bar = "█" * int(progress_pct // 5) + "░" * (20 - int(progress_pct // 5))

            status_style = {
                "completed": "green",
                "running": "cyan",
                "paused": "yellow",
                "failed": "red",
            }.get(status, "white")

            table.add_row(
                task_id_short,
                task.get("description", "N/A")[:30],
                f"[{status_style}]{status}[/{status_style}]",
                iteration,
                progress_bar,
            )

        self.console.print()
        self.console.print(table)

    def show_error(self, message: str) -> None:
        """Display error message in a panel."""
        error_panel = Panel(
            f"[bold red]{message}[/bold red]",
            title="[bold red]Error[/bold red]",
            border_style="red",
            expand=False,
        )
        self.console.print(error_panel)

    def show_success(self, message: str) -> None:
        """Display success message in a panel."""
        success_panel = Panel(
            f"[bold green]{message}[/bold green]",
            title="[bold green]Success[/bold green]",
            border_style="green",
            expand=False,
        )
        self.console.print(success_panel)

    def show_info(self, title: str, content: str) -> None:
        """Display information in a panel."""
        info_panel = Panel(
            content,
            title=f"[bold blue]{title}[/bold blue]",
            border_style="blue",
        )
        self.console.print(info_panel)

    def prompt_continue(self) -> bool:
        """Ask user to continue."""
        response = self.console.input(
            "\n[bold cyan]Press Enter to continue, or type 'q' to quit:[/bold cyan] "
        )
        return response.lower() != "q"
