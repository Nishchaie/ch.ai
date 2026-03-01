"""Terminal UI utilities for ch.ai - role-colored output, tables, panels."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from rich import box

from ..types import AgentEvent, RoleType, TaskSpec, TaskStatus
from .themes import get_theme


def _role_color(role: Optional[RoleType]) -> str:
    if role is None:
        return "white"
    theme = get_theme("default")
    return theme.get_role_color(role.value)


class TerminalUI:
    """Role-colored terminal output using rich."""

    def __init__(self, console: Optional[Console] = None, theme: str = "default") -> None:
        self.console = console or Console()
        self._theme = get_theme(theme)
        self._status: Optional[Status] = None

    def print_welcome(self, provider: str, model: str) -> None:
        """Print welcome banner."""
        self.console.print()
        self.console.print(
            Panel(
                f"[bold]ch.ai[/bold] AI Engineering Team Harness\n"
                f"Provider: [cyan]{provider}[/cyan]  Model: [cyan]{model}[/cyan]",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )
        self.console.print()

    # -- Activity spinner -------------------------------------------------

    _PHASE_LABELS = {
        "planning": "Planning\u2026 decomposing prompt into tasks",
        "executing": "Executing\u2026 running task graph",
        "reviewing": "Reviewing\u2026 validating results",
    }

    def start_activity(self, message: str = "Starting\u2026") -> None:
        """Start an animated spinner with a status message."""
        self._status = self.console.status(message, spinner="dots")
        self._status.start()

    def update_activity(self, message: str) -> None:
        """Update the spinner message to describe current activity."""
        if self._status:
            self._status.update(message)

    def stop_activity(self) -> None:
        """Stop the spinner."""
        if self._status:
            self._status.stop()
            self._status = None

    def _activity_message(self, event: AgentEvent) -> Optional[str]:
        """Derive a human-readable spinner label from an event."""
        data = event.data
        role_str = event.role.value.upper() if event.role else "SYSTEM"

        if event.type == "status" and isinstance(data, dict):
            phase = data.get("phase")
            if phase:
                return self._PHASE_LABELS.get(phase, f"{phase.capitalize()}\u2026")
            task_started = data.get("task_started")
            if task_started:
                title = data.get("title", task_started)
                return f"[{role_str}] {title}\u2026"
            task_completed = data.get("task_completed")
            if task_completed:
                return f"[{role_str}] Completed {task_completed}"
            iteration = data.get("iteration")
            if iteration is not None:
                return f"[{role_str}] Iteration {iteration}\u2026"
        elif event.type == "activity":
            msg = data.get("message", str(data)) if isinstance(data, dict) else str(data)
            return f"[{role_str}] {msg}"
        elif event.type == "tool_call":
            name = data.get("name", "?") if isinstance(data, dict) else "?"
            return f"[{role_str}] Calling tool: {name}"
        elif event.type == "text":
            return f"[{role_str}] Responding\u2026"
        elif event.type == "info" and isinstance(data, dict) and "tasks" in data:
            return f"Created {len(data['tasks'])} tasks"
        return None

    # -- Event printing ---------------------------------------------------

    def print_event(self, event: AgentEvent) -> None:
        """Format and print an agent event with role coloring."""
        activity_msg = self._activity_message(event)
        if activity_msg:
            self.update_activity(activity_msg)

        evt_type = event.type
        data = event.data
        role = event.role
        task_id = event.task_id or ""
        color = _role_color(role)
        role_str = role.value.upper() if role else "SYSTEM"

        if evt_type == "activity":
            # Spinner-only: no printed line, _activity_message already updated it
            return
        elif evt_type == "text":
            text = str(data) if not isinstance(data, dict) else data.get("text", str(data))
            if text.strip():
                prefix = f"[{color}][{role_str}][/{color}] "
                self.console.print(prefix + text)
        elif evt_type == "text_chunk":
            self.console.print(str(data), end="")
        elif evt_type == "tool_call":
            name = data.get("name", "?") if isinstance(data, dict) else "?"
            self.console.print(f"[{color}][{role_str}][/{color}] [dim]\u2192 tool: {name}[/dim]")
        elif evt_type == "tool_result":
            success = data.get("success", False) if isinstance(data, dict) else False
            mark = "[green]\u2713[/green]" if success else "[red]\u2717[/red]"
            self.console.print(f"[{color}][{role_str}][/{color}] [dim]{mark} tool result[/dim]")
        elif evt_type == "error":
            msg = str(data) if not isinstance(data, dict) else data.get("message", str(data))
            self.console.print(self.format_error(f"[{role_str}] {msg}"))
        elif evt_type == "info":
            if isinstance(data, dict) and "tasks" in data:
                tasks = data["tasks"]
                self.console.print(f"[dim]Tasks: {', '.join(str(t) for t in tasks)}[/dim]")
            else:
                self.console.print(self.format_info(str(data)))
        elif evt_type == "status":
            if isinstance(data, dict):
                task_started = data.get("task_started")
                task_completed = data.get("task_completed")
                if task_started:
                    title = data.get("title", task_started)
                    self.console.print(
                        f"[{color}][{role_str}][/{color}] [dim]\u25b6 {title}[/dim]"
                    )
                    return
                if task_completed:
                    self.console.print(
                        f"[{color}][{role_str}][/{color}] [green]\u2713[/green] [dim]done[/dim]"
                    )
                    return
                phase = data.get("phase", "")
            else:
                phase = str(data)
            if phase:
                self.console.print(f"[dim]\u25ba {phase}[/dim]")
        elif evt_type == "waiting":
            self.console.print(f"[dim]\u23f3 {data}[/dim]")
        else:
            self.console.print(f"[{color}][{role_str}][/{color}] {data}")

    def print_team_status(self, status: Dict) -> None:
        """Formatted team status table."""
        table = Table(title="Team Status", box=box.ROUNDED)
        table.add_column("Role", style="bold")
        table.add_column("Provider", style="cyan")
        table.add_column("Model", style="cyan")
        table.add_column("Autonomy", style="dim")
        state = status.get("state", "unknown")
        table.caption = f"State: [bold]{state}[/bold]"
        for role_name, info in status.get("members", {}).items():
            if isinstance(info, dict):
                table.add_row(
                    role_name,
                    info.get("provider", "-"),
                    info.get("model", "-") or "-",
                    info.get("autonomy", "-"),
                )
        self.console.print(table)

    def print_task_board(self, tasks: List[TaskSpec]) -> None:
        """Kanban-style task display (pending / in-progress / done columns)."""
        pending = [t for t in tasks if t.status == TaskStatus.PENDING]
        in_progress = [t for t in tasks if t.status == TaskStatus.IN_PROGRESS]
        reviewing = [t for t in tasks if t.status == TaskStatus.REVIEWING]
        done = [
            t
            for t in tasks
            if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        ]

        cols = [
            self._task_column("Pending", pending, "yellow"),
            self._task_column("In Progress", in_progress, "cyan"),
            self._task_column("Reviewing", reviewing, "magenta"),
            self._task_column("Done", done, "green"),
        ]
        self.console.print(Columns(cols, expand=True))

    def _task_column(self, title: str, tasks: List[TaskSpec], color: str) -> str:
        lines = [f"[bold {color}]{title}[/bold {color}]", ""]
        for t in tasks:
            status_icon = "✓" if t.status == TaskStatus.COMPLETED else "✗" if t.status == TaskStatus.FAILED else "○"
            lines.append(f"  {status_icon} {t.title} [{t.role.value}]")
        return "\n".join(lines)

    def print_quality_scores(self, scores: Dict) -> None:
        """Quality score table."""
        table = Table(title="Quality Scores", box=box.ROUNDED)
        table.add_column("Domain", style="bold")
        table.add_column("Score", style="cyan")
        table.add_column("Grade", style="green")
        for domain, info in scores.items():
            if isinstance(info, dict):
                score = info.get("score", 0)
                grade = info.get("grade", "-")
                table.add_row(domain, f"{score:.1%}", grade)
            else:
                table.add_row(domain, str(info), "-")
        self.console.print(table)

    def format_error(self, msg: str) -> str:
        """Format error message."""
        return f"[red]{msg}[/red]"

    def format_info(self, msg: str) -> str:
        """Format info message."""
        return f"[blue]{msg}[/blue]"

    def format_success(self, msg: str) -> str:
        """Format success message."""
        return f"[green]{msg}[/green]"
