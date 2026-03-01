"""Real-time team dashboard using rich.live."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich import box

from ..types import AgentEvent, RoleType, TaskSpec, TaskStatus


def _role_color(role: Optional[RoleType]) -> str:
    colors = {
        RoleType.LEAD: "gold1",
        RoleType.FRONTEND: "cyan",
        RoleType.BACKEND: "green",
        RoleType.PROMPT: "magenta",
        RoleType.RESEARCHER: "blue",
        RoleType.QA: "red",
        RoleType.DEPLOYMENT: "yellow1",
        RoleType.CUSTOM: "white",
    }
    return colors.get(role, "white")


class TeamDashboard:
    """Real-time team dashboard: active agents, tasks, progress, recent output."""

    def __init__(self, refresh_per_second: float = 4) -> None:
        self._live: Optional[Live] = None
        self._refresh_rate = refresh_per_second
        self._state: Dict[str, Any] = {
            "phase": "idle",
            "active_agents": [],
            "tasks": [],
            "recent_events": [],
            "progress": 0,
        }

    def start(self) -> None:
        """Start the live display."""
        self._live = Live(
            self._render(),
            refresh_per_second=self._refresh_rate,
            console=None,
        )
        self._live.start()

    def stop(self) -> None:
        """Stop the live display."""
        if self._live:
            self._live.stop()
            self._live = None

    def update(self, events: List[AgentEvent], tasks: Optional[List[TaskSpec]] = None) -> None:
        """Update dashboard with new events and optionally tasks."""
        for evt in events:
            if evt.type == "status" and isinstance(evt.data, dict):
                self._state["phase"] = evt.data.get("phase", self._state["phase"])
            elif evt.type == "text" and evt.role:
                role = evt.role
                if role not in self._state["active_agents"]:
                    self._state["active_agents"].append(role)
                recent = self._state["recent_events"]
                text = str(evt.data)
                recent.append(
                    {"role": role, "text": text[:80] + "..." if len(text) > 80 else text}
                )
                self._state["recent_events"] = recent[-10:]
        if tasks is not None:
            self._state["tasks"] = tasks

        if self._live and self._live.is_live:
            self._live.update(self._render())

    def _render(self) -> Panel:
        """Render the current dashboard layout."""
        phase = self._state.get("phase", "idle")
        active = self._state.get("active_agents", [])
        tasks = self._state.get("tasks", [])
        recent = self._state.get("recent_events", [])

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=None,
        )
        progress.add_task(f"Phase: {phase}", total=None)

        agent_text = ", ".join(f"[{_role_color(r)}]{r.value}[/]" for r in active) if active else "[dim]None[/dim]"
        agents_panel = Panel(
            Text.from_markup(agent_text),
            title="Active Agents",
            border_style="cyan",
        )

        status_counts: Dict[str, int] = {}
        for t in tasks:
            s = t.status.value
            status_counts[s] = status_counts.get(s, 0) + 1
        counts_str = ", ".join(f"{k}: {v}" for k, v in status_counts.items()) or "No tasks"
        tasks_panel = Panel(
            counts_str,
            title="Tasks",
            border_style="green",
        )

        lines = []
        for r in recent[-5:]:
            role = r.get("role")
            color = _role_color(role) if role else "white"
            role_str = role.value if role else "?"
            text = r.get("text", "")[:60]
            lines.append(f"[{color}][{role_str}][/{color}] {text}")
        recent_panel = Panel(
            "\n".join(lines) if lines else "[dim]No output yet[/dim]",
            title="Recent Output",
            border_style="dim",
        )

        content = Group(
            progress,
            "",
            agents_panel,
            tasks_panel,
            recent_panel,
        )
        return Panel(content, title="[bold]ch.ai[/bold] Team Dashboard", border_style="blue", box=box.ROUNDED)
