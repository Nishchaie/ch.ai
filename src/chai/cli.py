"""Click-based CLI for ch.ai."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.prompt import Prompt, Confirm

from .config import get_config, reload_config, ProjectConfig, CONFIG_DIR, CONFIG_FILE
from .types import (
    AgentConfig,
    AgentEvent,
    AutonomyLevel,
    ProviderType,
    RoleType,
    TeamConfig,
    TaskStatus,
)


class ApiEventForwarder:
    """Pushes AgentEvents to the API server over WebSocket.

    Best-effort: if the server is not running the CLI works normally.
    Uses the ``websockets`` sync client so it can be called from the
    synchronous CLI event loop without an asyncio runtime.
    """

    def __init__(self, run_id: str, prompt: str, api_url: str = "ws://127.0.0.1:8000") -> None:
        self._run_id = run_id
        self._prompt = prompt
        self._url = f"{api_url}/api/runs/ingest"
        self._ws: Any = None

    def connect(self) -> bool:
        try:
            from websockets.sync.client import connect
            self._ws = connect(self._url, open_timeout=2)
            self._ws.send(json.dumps({
                "action": "start",
                "run_id": self._run_id,
                "prompt": self._prompt,
            }))
            return True
        except Exception:
            self._ws = None
            return False

    def send_event(self, evt: AgentEvent) -> None:
        if not self._ws:
            return
        try:
            self._ws.send(json.dumps({
                "action": "event",
                "run_id": self._run_id,
                "event": {
                    "type": evt.type,
                    "data": evt.data,
                    "role": evt.role.value if evt.role else None,
                    "task_id": evt.task_id,
                },
            }))
        except Exception:
            self._ws = None

    def close(self) -> None:
        if not self._ws:
            return
        try:
            self._ws.send(json.dumps({
                "action": "done",
                "run_id": self._run_id,
            }))
            self._ws.close()
        except Exception:
            pass
        self._ws = None


def _handle_incremental_state(evt: "AgentEvent", prompt: str) -> None:
    """Persist task state incrementally so the TaskBoard sees live updates."""
    from .state import save_tasks_initial, update_task_status

    data = evt.data if isinstance(evt.data, dict) else {}

    if evt.type == "info" and isinstance(data.get("tasks"), list):
        tasks = data["tasks"]
        if tasks and isinstance(tasks[0], dict):
            save_tasks_initial(
                project_dir=str(Path.cwd()),
                tasks=tasks,
                prompt=prompt,
            )
    elif evt.type == "status":
        if data.get("task_started"):
            update_task_status(str(data["task_started"]), "in_progress")
        elif data.get("task_completed"):
            update_task_status(str(data["task_completed"]), "completed")
    elif evt.type == "error" and evt.task_id:
        update_task_status(evt.task_id, "failed")


def _init_project(project_dir: Path) -> None:
    """Initialize project: chai.yaml, AGENTS.md, docs structure. Inline when knowledge modules unavailable."""
    # Try knowledge modules first
    try:
        from .knowledge.docs_manager import init_docs
        from .knowledge.agents_md import init_agents_md
        init_docs(str(project_dir))
        init_agents_md(str(project_dir))
        return
    except ImportError:
        pass

    # Inline initialization
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "docs").mkdir(parents=True, exist_ok=True)
    (project_dir / "docs" / "design-docs").mkdir(parents=True, exist_ok=True)
    (project_dir / "docs" / "exec-plans").mkdir(parents=True, exist_ok=True)
    (project_dir / "docs" / "golden-principles").mkdir(parents=True, exist_ok=True)
    (project_dir / "docs" / "references").mkdir(parents=True, exist_ok=True)

    chai_yaml = project_dir / "chai.yaml"
    if not chai_yaml.exists():
        chai_yaml.write_text("""# ch.ai project configuration
# See README for full reference

team:
  name: default
  max_concurrent_agents: 4
  default_provider: claude_code
  members:
    lead:
      provider: claude_code
      autonomy: high
    backend:
      provider: claude_code
    qa:
      provider: claude_code

validation:
  run_tests: true
  run_linter: true
  max_fix_iterations: 3

self_improvement:
  update_principles_after_run: true
  track_quality_scores: true
""", encoding="utf-8")
        click.echo(f"Created {chai_yaml}")

    agents_md = project_dir / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text("""# ch.ai Agent Guide

> Project-specific map for AI agents.

## Directory Map
- `src/` -- Source code
- `tests/` -- Tests
- `docs/` -- Documentation

## Key Concepts
- See project README for architecture and conventions.
""", encoding="utf-8")
        click.echo(f"Created {agents_md}")


def _provider_factory(provider_type: str, model: Optional[str] = None):
    """Lazy provider creation."""
    try:
        from .providers.factory import create_provider
        return create_provider(provider_type, model)
    except ImportError:
        from .providers.anthropic_api import AnthropicAPIProvider
        from .config import get_config
        cfg = get_config()
        key = cfg.get_api_key(provider_type)
        if provider_type == "anthropic_api" and key:
            return AnthropicAPIProvider(api_key=key, model=model or cfg.default_model)
        raise click.ClickException(
            f"Provider {provider_type} not available. Install dependencies and set API keys."
        )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """ch.ai - AI engineering team harness."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    if verbose:
        reload_config().verbose = True


@cli.command()
def init() -> None:
    """Initialize project: chai.yaml, AGENTS.md, docs structure."""
    project_dir = Path.cwd()
    _init_project(project_dir)
    Console().print("[green]Project initialized.[/green]")


@cli.command()
@click.argument("prompt", required=True)
@click.option("--provider", "-p", default=None, help="Provider (claude_code, anthropic_api, codex)")
@click.option("--model", "-m", default=None, help="Model name")
@click.option("--max-agents", type=int, default=None, help="Max concurrent agents")
def run(prompt: str, provider: Optional[str], model: Optional[str], max_agents: Optional[int]) -> None:
    """Run a team on a task."""
    cfg = get_config()
    provider = provider or cfg.default_provider
    model = model or cfg.default_model

    try:
        from .core.harness import Harness
        from .ui.terminal import TerminalUI
    except ImportError as e:
        raise click.ClickException(f"Import error: {e}")

    ui = TerminalUI()
    ui.print_welcome(provider, model)

    run_id = str(uuid.uuid4())
    forwarder = ApiEventForwarder(run_id, prompt)
    forwarder.connect()

    try:
        from .state import save_run, tasks_from_result

        factory = lambda p, m: _provider_factory(p, m)
        harness = Harness(provider_factory=factory)
        gen = harness.run(prompt)
        result = None
        event_count = 0
        ui.start_activity("Starting\u2026")
        try:
            while True:
                evt = next(gen)
                event_count += 1
                ui.print_event(evt)
                forwarder.send_event(evt)
                _handle_incremental_state(evt, prompt)
        except StopIteration as e:
            result = e.value
        finally:
            ui.stop_activity()
            forwarder.close()

        tasks = tasks_from_result(result)
        save_run(
            project_dir=str(Path.cwd()),
            tasks=tasks,
            prompt=prompt,
            events_count=event_count,
        )

        Console().print("\n[green]Done.[/green]")
    except Exception as e:
        forwarder.close()
        ui.stop_activity()
        ui.console.print(ui.format_error(str(e)))
        raise SystemExit(1)


@cli.command()
@click.option("--role", "-r", required=True, type=click.Choice([r.value for r in RoleType]))
@click.argument("prompt", required=True)
@click.option("--provider", "-p", default=None)
@click.option("--model", "-m", default=None)
def agent(role: str, prompt: str, provider: Optional[str], model: Optional[str]) -> None:
    """Run a single agent with a specific role (no team coordination)."""
    cfg = get_config()
    provider = provider or cfg.default_provider
    model = model or cfg.default_model

    try:
        from .core.harness import Harness
        from .core.team import Team
        from .core.task import TaskGraph
        from .types import TaskSpec
        from .ui.terminal import TerminalUI
    except ImportError as e:
        raise click.ClickException(f"Import error: {e}")

    role_type = RoleType(role)
    team_config = TeamConfig(
        name="single",
        members={
            role_type: AgentConfig(role=role_type, provider=ProviderType(provider)),
        },
    )
    ui = TerminalUI()
    ui.print_welcome(provider, model)

    try:
        factory = lambda p, m: _provider_factory(p, m)
        from .core.agent import AgentRunner
        from .core.role import RoleRegistry
        from .core.context import ContextManager
        from .tools import create_tool_registry
        lead_ac = team_config.members[role_type]
        provider_inst = factory(provider, model)
        role_reg = RoleRegistry()
        role_def = role_reg.get_role(role_type)
        if not role_def:
            from .core.role import RoleDefinition
            role_def = RoleDefinition(role_type=role_type, name=role, description="", system_prompt_template="{task}")
        tools = create_tool_registry(base_dir=str(Path.cwd()), role=role_type)
        ctx = ContextManager(str(Path.cwd()))
        task = TaskSpec(id="task-1", title=prompt, description="", role=role_type)
        context = ctx.get_context_for_role(role_def, task)
        runner = AgentRunner(role_def, provider_inst, tools, lead_ac, context)
        ui.start_activity("Starting\u2026")
        try:
            for evt in runner.run(task):
                ui.print_event(evt)
        finally:
            ui.stop_activity()
        Console().print("\n[green]Done.[/green]")
    except Exception as e:
        ui.stop_activity()
        ui.console.print(ui.format_error(str(e)))
        raise SystemExit(1)


@cli.group()
def team() -> None:
    """Team management commands."""


@team.command()
def create() -> None:
    """Interactive team creation (select roles and providers)."""
    console = Console()
    console.print("[bold]Interactive Team Creation[/bold]\n")
    roles = [r for r in RoleType if r != RoleType.CUSTOM]
    providers = ["claude_code", "anthropic_api", "codex"]
    members = {}
    for role in roles:
        if Confirm.ask(f"Include {role.value}?", default=(role == RoleType.LEAD or role == RoleType.BACKEND)):
            prov = Prompt.ask("  Provider", default="claude_code", choices=providers)
            model = Prompt.ask("  Model (optional)", default="")
            members[role] = AgentConfig(
                role=role,
                provider=ProviderType(prov),
                model=model or None,
            )
    if not members:
        console.print("[yellow]No roles selected. Exiting.[/yellow]")
        return
    name = Prompt.ask("Team name", default="default")
    team_config = TeamConfig(name=name, members=members)
    # Save to chai.yaml - simplified: just print and suggest manual edit
    console.print("\n[green]Team configuration:[/green]")
    console.print(f"  Name: {name}")
    for r, ac in members.items():
        console.print(f"  - {r.value}: {ac.provider.value}" + (f" ({ac.model})" if ac.model else ""))
    console.print("\nAdd this to your chai.yaml team.members section.")


@team.command()
def status() -> None:
    """Show current team status."""
    try:
        from .core.harness import Harness
        from .ui.terminal import TerminalUI
    except ImportError as e:
        raise click.ClickException(f"Import error: {e}")
    cfg = get_config()
    factory = lambda p, m: _provider_factory(p, m)
    harness = Harness(provider_factory=factory)
    team = harness.create_team()
    status_dict = team.get_status()
    ui = TerminalUI()
    ui.print_team_status(status_dict)


@cli.group()
def plan() -> None:
    """Execution plan commands."""


@plan.command("create")
@click.argument("prompt", required=True)
def plan_create(prompt: str) -> None:
    """Create an execution plan."""
    try:
        from .core.harness import Harness
        from .orchestration.planner import ExecutionPlanManager
        from .ui.terminal import TerminalUI
    except ImportError as e:
        raise click.ClickException(f"Import error: {e}")
    cfg = get_config()
    factory = lambda p, m: _provider_factory(p, m)
    harness = Harness(provider_factory=factory)
    team = harness.create_team()
    lead_config = team.get_members().get(RoleType.LEAD)
    if not lead_config:
        raise click.ClickException("Team has no Lead. Add a Lead agent.")
    provider = factory(lead_config.provider.value, lead_config.model)
    from .core.role import RoleRegistry
    from .core.task import TaskDecomposer
    decomposer = TaskDecomposer(RoleRegistry())
    graph = decomposer.decompose(prompt, provider)
    mgr = ExecutionPlanManager()
    path = mgr.create_plan(prompt, graph.all_tasks())
    click.echo(f"[green]Plan created: {path}[/green]")


@plan.command("run")
@click.argument("path", type=click.Path(exists=True))
def plan_run(path: str) -> None:
    """Execute a plan."""
    try:
        from .core.harness import Harness
        from .orchestration.planner import ExecutionPlanManager
        from .ui.terminal import TerminalUI
    except ImportError as e:
        raise click.ClickException(f"Import error: {e}")
    mgr = ExecutionPlanManager()
    plan_dict, tasks, err = mgr.load_plan(path)
    if err or not tasks:
        raise click.ClickException(err or "No tasks in plan")
    cfg = get_config()
    factory = lambda p, m: _provider_factory(p, m)
    harness = Harness(provider_factory=factory)
    team = harness.create_team()
    ui = TerminalUI()
    ui.print_welcome(cfg.default_provider, cfg.default_model)
    gen = team.run_graph(tasks)
    ui.start_activity("Starting\u2026")
    try:
        while True:
            evt = next(gen)
            ui.print_event(evt)
    except StopIteration:
        pass
    finally:
        ui.stop_activity()
    Console().print("\n[green]Done.[/green]")


@plan.command("status")
@click.argument("path", type=click.Path(exists=True))
def plan_status(path: str) -> None:
    """Check plan progress."""
    try:
        from .orchestration.planner import ExecutionPlanManager
        from .ui.terminal import TerminalUI
    except ImportError as e:
        raise click.ClickException(f"Import error: {e}")
    mgr = ExecutionPlanManager()
    plan_dict, tasks, err = mgr.load_plan(path)
    if err:
        raise click.ClickException(err)
    ui = TerminalUI()
    ui.print_task_board(tasks)


@cli.group()
def config() -> None:
    """Configuration commands."""


@config.command("show")
def config_show() -> None:
    """Show current config."""
    cfg = get_config()
    from rich.table import Table
    from rich import box
    table = Table(title="ch.ai Config", box=box.ROUNDED)
    table.add_column("Key", style="bold")
    table.add_column("Value", style="cyan")
    table.add_row("config_file", str(CONFIG_FILE))
    table.add_row("default_provider", cfg.default_provider)
    table.add_row("default_model", cfg.default_model)
    table.add_row("verbose", str(cfg.verbose))
    table.add_row("theme", cfg.theme)
    table.add_row("max_concurrent_agents", str(cfg.max_concurrent_agents))
    Console().print(table)


@config.command("set")
@click.argument("key", required=True)
@click.argument("value", required=True)
def config_set(key: str, value: str) -> None:
    """Set a config value."""
    cfg = get_config()
    if key == "default_provider":
        cfg.default_provider = value
    elif key == "default_model":
        cfg.default_model = value
    elif key == "theme":
        cfg.theme = value
    elif key == "verbose":
        cfg.verbose = value.lower() in ("true", "1", "yes")
    elif key == "max_concurrent_agents":
        cfg.max_concurrent_agents = int(value)
    else:
        raise click.BadParameter(f"Unknown key: {key}")
    cfg.save()
    click.echo(f"[green]Set {key}={value}[/green]")


@cli.command()
def quality() -> None:
    """Show quality scores."""
    try:
        from .quality.scorer import get_quality_scores
        scores = get_quality_scores()
    except ImportError:
        scores = {"overall": {"score": 0.0, "grade": "N/A"}}
    ui = TerminalUI()
    ui.print_quality_scores(scores)


@cli.command()
def garden() -> None:
    """Run the doc gardener."""
    try:
        from .knowledge.gardener import run_gardener
        run_gardener()
    except ImportError:
        click.echo("[yellow]Doc gardener not yet implemented. Use chai init to scaffold docs.[/yellow]")


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind")
@click.option("--port", type=int, default=8000, help="Port to bind")
@click.option("--project-dir", "-d", default=None, type=click.Path(exists=True, file_okay=False),
              help="Project directory (defaults to cwd)")
def api(host: str, port: int, project_dir: Optional[str]) -> None:
    """Start the API server for the web frontend."""
    from .api import serve
    serve(host=host, port=port, project_dir=project_dir)


@cli.command()
def interactive() -> None:
    """Interactive REPL mode with slash commands."""
    console = Console()
    console.print("[bold]ch.ai Interactive[/bold] - Type /help for commands, /quit to exit.\n")

    def handle_cmd(line: str) -> bool:
        line = line.strip()
        if not line or not line.startswith("/"):
            return True
        cmd = line.split()[0].lower() if line.split() else ""
        if cmd == "/quit" or cmd == "/exit":
            return False
        elif cmd == "/team":
            try:
                from .core.harness import Harness
                from .ui.terminal import TerminalUI
                harness = Harness(provider_factory=lambda p, m: _provider_factory(p, m))
                team = harness.create_team()
                ui = TerminalUI()
                ui.print_team_status(team.get_status())
            except Exception as e:
                console.print(f"[red]{e}[/red]")
        elif cmd == "/plan":
            try:
                from .orchestration.planner import ExecutionPlanManager
                from .ui.terminal import TerminalUI
                mgr = ExecutionPlanManager()
                path = mgr.find_latest_plan()
                if path:
                    _, tasks, _ = mgr.load_plan(path)
                    ui = TerminalUI()
                    ui.print_task_board(tasks or [])
                else:
                    console.print("[yellow]No plans found.[/yellow]")
            except Exception as e:
                console.print(f"[red]{e}[/red]")
        elif cmd == "/config":
            config_show()
        elif cmd == "/quality":
            quality()
        elif cmd == "/help":
            console.print("Commands: /team, /plan, /config, /quality, /help, /quit")
        return True

    while True:
        try:
            line = Prompt.ask("[chai]")
            if not handle_cmd(line):
                break
        except (EOFError, KeyboardInterrupt):
            break
    console.print("[dim]Goodbye.[/dim]")
