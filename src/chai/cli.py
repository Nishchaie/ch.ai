"""Click-based CLI for ch.ai."""

from __future__ import annotations

import json
import signal
import sys
import threading
import time
import uuid
from collections import deque
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
    TeamRunResult,
    TaskStatus,
)


class ApiEventForwarder:
    """Pushes AgentEvents to the API server over WebSocket.

    Best-effort: if the server is not running the CLI works normally.
    Runs a background daemon thread that retries the connection with
    exponential backoff and buffers events while disconnected.
    """

    _MAX_BACKOFF = 8.0

    def __init__(self, run_id: str, prompt: str, api_url: str = "ws://127.0.0.1:8000") -> None:
        self._run_id = run_id
        self._prompt = prompt
        self._url = f"{api_url}/api/runs/ingest"
        self._buffer: deque[dict] = deque(maxlen=50_000)
        self._closing = threading.Event()
        self._has_items = threading.Event()
        self._ws: Any = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Launch the background forwarding thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _try_connect(self) -> bool:
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

    def _flush_buffer(self) -> bool:
        """Send all buffered messages. Returns False if the connection broke."""
        while self._buffer and self._ws:
            msg = self._buffer[0]
            try:
                self._ws.send(json.dumps(msg))
                self._buffer.popleft()
            except Exception:
                self._ws = None
                return False
        return True

    def _run_loop(self) -> None:
        backoff = 2.0
        while not self._closing.is_set():
            if not self._ws:
                if self._try_connect():
                    backoff = 2.0
                    if not self._flush_buffer():
                        continue
                else:
                    self._closing.wait(timeout=backoff)
                    backoff = min(backoff * 2, self._MAX_BACKOFF)
                    continue

            if not self._buffer:
                self._has_items.wait(timeout=0.25)
                self._has_items.clear()

            if not self._flush_buffer():
                continue

        # Shutting down: best-effort flush and send done
        if not self._ws:
            self._try_connect()
        self._flush_buffer()
        if self._ws:
            try:
                self._ws.send(json.dumps({"action": "done", "run_id": self._run_id}))
                self._ws.close()
            except Exception:
                pass

    def _serialize_event(self, evt: AgentEvent) -> dict:
        return {
            "action": "event",
            "run_id": self._run_id,
            "event": {
                "type": evt.type,
                "data": evt.data,
                "role": evt.role.value if evt.role else None,
                "task_id": evt.task_id,
            },
        }

    def send_event(self, evt: AgentEvent) -> None:
        self._buffer.append(self._serialize_event(evt))
        self._has_items.set()

    def close(self) -> None:
        self._closing.set()
        self._has_items.set()
        if self._thread:
            self._thread.join(timeout=5)


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
    forwarder.start()

    from .providers.base import cancel_active_providers

    cancel_event = threading.Event()
    original_sigint = signal.getsignal(signal.SIGINT)

    def _on_sigint(signum: int, frame: Any) -> None:
        cancel_event.set()
        cancel_active_providers()
        ui.console.print("\n[yellow]Cancelling… press Ctrl+C again to force quit.[/yellow]")
        signal.signal(signal.SIGINT, original_sigint)

    signal.signal(signal.SIGINT, _on_sigint)

    try:
        from .state import save_run, tasks_from_result

        factory = lambda p, m: _provider_factory(p, m)
        harness = Harness(provider_factory=factory)
        gen = harness.run(prompt, cancel_event=cancel_event)
        result = None
        event_count = 0
        ui.start_activity("Starting…")
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

        if cancel_event.is_set():
            Console().print("\n[yellow]Cancelled.[/yellow]")
        else:
            Console().print("\n[green]Done.[/green]")
    except KeyboardInterrupt:
        forwarder.close()
        ui.stop_activity()
        Console().print("\n[red]Force quit.[/red]")
        raise SystemExit(130)
    except Exception as e:
        forwarder.close()
        ui.stop_activity()
        ui.console.print(ui.format_error(str(e)))
        raise SystemExit(1)
    finally:
        signal.signal(signal.SIGINT, original_sigint)


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
    team_inst = harness.create_team()
    ui = TerminalUI()
    ui.print_welcome(cfg.default_provider, cfg.default_model)
    gen = team_inst.run_graph(tasks)
    result = None
    ui.start_activity("Starting\u2026")
    try:
        while True:
            evt = next(gen)
            ui.print_event(evt)
    except StopIteration as e:
        result = e.value
    finally:
        ui.stop_activity()

    if result:
        status_map = {
            t.id: t.status.value for t in result.tasks
        }
        mgr.update_plan_status(path, status_map)

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


def _extract_run_summary(raw_prompt: str, result: Optional[TeamRunResult]) -> dict:
    """Build a session context entry from a completed run."""
    if result is None:
        return {"prompt": raw_prompt, "outcome": "Run failed or was cancelled."}
    parts: list[str] = []
    for task in result.tasks:
        status_str = task.status.value if hasattr(task.status, "value") else str(task.status)
        text = f"{task.title} [{status_str}]"
        task_result = getattr(task, "result", None) or ""
        if task_result:
            text += f": {str(task_result)[:500]}"
        parts.append(text)
    duration = f" ({result.duration_seconds:.1f}s)" if result.duration_seconds else ""
    outcome = "; ".join(parts) + duration if parts else f"No tasks{duration}"
    return {"prompt": raw_prompt, "outcome": outcome}


def _build_augmented_prompt(raw_prompt: str, session_context: list[dict]) -> str:
    """Prepend session history to the raw prompt for context threading."""
    if not session_context:
        return raw_prompt
    lines = ["[Session history - previous work in this session]"]
    for i, entry in enumerate(session_context, 1):
        outcome = entry.get("outcome", "")
        if len(outcome) > 500:
            outcome = outcome[:500] + "…"
        lines.append(f"{i}. User: \"{entry['prompt']}\" -> {outcome}")
    lines.append("")
    lines.append("[Current request]")
    lines.append(raw_prompt)
    return "\n".join(lines)


def _run_in_repl(
    harness: "Harness",
    ui: "TerminalUI",
    prompt: str,
    raw_prompt: str,
    cancel_event: threading.Event,
    console: Console,
    db: Any = None,
) -> Optional[TeamRunResult]:
    """Execute a prompt inside the REPL with event streaming and cancellation."""
    from .providers.base import cancel_active_providers
    from .state import save_run, tasks_from_result

    cancel_event.clear()

    ui.stop_activity()
    ui.start_activity("Routing…")
    try:
        routing = harness._router.classify(raw_prompt)
    finally:
        ui.stop_activity()

    original_sigint = signal.getsignal(signal.SIGINT)

    def _on_sigint(signum: int, frame: Any) -> None:
        cancel_event.set()
        cancel_active_providers()
        console.print("\n[yellow]Cancelling…[/yellow]")
        signal.signal(signal.SIGINT, original_sigint)

    signal.signal(signal.SIGINT, _on_sigint)

    run_id = str(uuid.uuid4())
    forwarder = ApiEventForwarder(run_id, raw_prompt)
    forwarder.start()

    result: Optional[TeamRunResult] = None
    ui.start_activity("Starting…")
    try:
        gen = harness.run(prompt, strategy_override=routing.strategy, cancel_event=cancel_event)
        event_count = 0
        try:
            while True:
                evt = next(gen)
                event_count += 1
                ui.print_event(evt)
                forwarder.send_event(evt)
                _handle_incremental_state(evt, raw_prompt)
        except StopIteration as e:
            result = e.value

        tasks = tasks_from_result(result)
        save_run(
            project_dir=str(Path.cwd()),
            tasks=tasks,
            prompt=raw_prompt,
            events_count=event_count,
        )

        if db is not None:
            try:
                import json as _json
                db.save_team_run(raw_prompt, _json.dumps(tasks), result.duration_seconds if result else 0.0)
            except Exception:
                pass

        if cancel_event.is_set():
            console.print("\n[yellow]Cancelled.[/yellow]")
        else:
            console.print("\n[green]Done.[/green]")
    except Exception as e:
        console.print(ui.format_error(str(e)))
    finally:
        ui.stop_activity()
        forwarder.close()
        signal.signal(signal.SIGINT, original_sigint)

    return result


@cli.command()
def interactive() -> None:
    """Interactive REPL mode with slash commands."""
    try:
        from .core.harness import Harness
        from .ui.terminal import TerminalUI
    except ImportError as e:
        raise click.ClickException(f"Import error: {e}")

    console = Console()
    factory = lambda p, m: _provider_factory(p, m)
    harness = Harness(provider_factory=factory)
    ui = TerminalUI(console=console)
    cancel_event = threading.Event()
    session_context: list[dict] = []
    session_messages: list[dict] = []
    db: Any = None

    try:
        from .sessions.db import Database
        db = Database()
        db.create_session()
    except Exception:
        pass

    cfg = get_config()
    console.print("[bold]ch.ai Interactive[/bold] - Type /help for commands, /quit to exit.\n")

    def _do_run(raw_prompt: str) -> None:
        """Run a prompt and update session context."""
        if db is not None:
            try:
                db.save_message("user", raw_prompt)
            except Exception:
                pass

        augmented = _build_augmented_prompt(raw_prompt, session_context)
        result = _run_in_repl(harness, ui, augmented, raw_prompt, cancel_event, console, db=db)
        entry = _extract_run_summary(raw_prompt, result)
        session_context.append(entry)

        session_messages.append({"role": "user", "content": raw_prompt})
        summary_text = entry.get("outcome", "")
        session_messages.append({"role": "assistant", "content": summary_text})

        if db is not None:
            try:
                db.save_message("assistant", summary_text)
            except Exception:
                pass

        _try_compact(session_messages, db)

    def _try_compact(messages: list[dict], database: Any) -> None:
        """Compact session messages if approaching token limits."""
        try:
            from .sessions.compaction import maybe_compact
            provider = factory(cfg.default_provider, cfg.default_model)
            compacted, new_messages = maybe_compact(provider, messages)
            if compacted:
                messages.clear()
                messages.extend(new_messages)
                if database is not None and database._current_session_id:
                    try:
                        database.rewrite_session_with_summary(
                            database._current_session_id,
                            new_messages[:1],
                            new_messages[-1:],
                            new_messages[1]["content"] if len(new_messages) > 1 else "",
                        )
                    except Exception:
                        pass
        except Exception:
            pass

    def handle_cmd(line: str) -> bool:
        """Handle a REPL input line. Returns False to exit."""
        line = line.strip()
        if not line:
            return True

        if not line.startswith("/"):
            _do_run(line)
            return True

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit"):
            return False

        elif cmd == "/run":
            if not args:
                console.print("[yellow]Usage: /run <prompt>[/yellow]")
            else:
                _do_run(args)

        elif cmd == "/plan":
            sub_parts = args.split(maxsplit=1) if args else []
            sub_cmd = sub_parts[0].lower() if sub_parts else ""

            if sub_cmd == "create":
                plan_prompt = sub_parts[1].strip() if len(sub_parts) > 1 else ""
                if not plan_prompt:
                    console.print("[yellow]Usage: /plan create <prompt>[/yellow]")
                else:
                    try:
                        from .orchestration.planner import ExecutionPlanManager
                        from .core.role import RoleRegistry
                        from .core.task import TaskDecomposer
                        team_inst = harness.create_team()
                        lead_config = team_inst.get_members().get(RoleType.LEAD)
                        if not lead_config:
                            console.print("[red]Team has no Lead. Add a Lead agent.[/red]")
                        else:
                            provider = factory(lead_config.provider.value, lead_config.model)
                            decomposer = TaskDecomposer(RoleRegistry())
                            graph = decomposer.decompose(plan_prompt, provider)
                            mgr = ExecutionPlanManager()
                            plan_path = mgr.create_plan(plan_prompt, graph.all_tasks())
                            console.print(f"[green]Plan created: {plan_path}[/green]")
                    except Exception as e:
                        console.print(ui.format_error(str(e)))

            elif sub_cmd == "run":
                plan_path = sub_parts[1].strip() if len(sub_parts) > 1 else ""
                if not plan_path:
                    console.print("[yellow]Usage: /plan run <path>[/yellow]")
                else:
                    try:
                        from .orchestration.planner import ExecutionPlanManager
                        mgr = ExecutionPlanManager()
                        plan_dict, tasks, err = mgr.load_plan(plan_path)
                        if err or not tasks:
                            console.print(f"[red]{err or 'No tasks in plan'}[/red]")
                        else:
                            cancel_event.clear()
                            team_inst = harness.create_team()
                            team_inst._cancel_event = cancel_event
                            ui.stop_activity()
                            ui.start_activity("Running plan…")
                            plan_result = None
                            try:
                                gen = team_inst.run_graph(tasks)
                                try:
                                    while True:
                                        evt = next(gen)
                                        ui.print_event(evt)
                                except StopIteration as e:
                                    plan_result = e.value
                            finally:
                                ui.stop_activity()
                            if plan_result:
                                status_map = {t.id: t.status.value for t in plan_result.tasks}
                                mgr.update_plan_status(plan_path, status_map)
                            console.print("[green]Plan execution complete.[/green]")
                    except Exception as e:
                        console.print(ui.format_error(str(e)))
            else:
                try:
                    from .orchestration.planner import ExecutionPlanManager
                    mgr = ExecutionPlanManager()
                    path = mgr.find_latest_plan()
                    if path:
                        _, tasks, _ = mgr.load_plan(path)
                        ui.print_task_board(tasks or [])
                    else:
                        console.print("[yellow]No plans found.[/yellow]")
                except Exception as e:
                    console.print(f"[red]{e}[/red]")

        elif cmd == "/history":
            if session_context:
                console.print("[bold]Session History[/bold]")
                for i, entry in enumerate(session_context, 1):
                    outcome = entry.get("outcome", "")
                    if len(outcome) > 120:
                        outcome = outcome[:120] + "…"
                    console.print(f"  {i}. [cyan]{entry['prompt']}[/cyan] -> {outcome}")
            else:
                console.print("[dim]No runs in this session yet.[/dim]")

        elif cmd == "/new":
            session_context.clear()
            session_messages.clear()
            if db is not None:
                try:
                    db.create_session()
                except Exception:
                    pass
            console.print("[green]New session started.[/green]")

        elif cmd == "/clear":
            session_context.clear()
            session_messages.clear()
            console.print("[green]Session context cleared.[/green]")

        elif cmd == "/team":
            try:
                team_inst = harness.create_team()
                ui.print_team_status(team_inst.get_status())
            except Exception as e:
                console.print(f"[red]{e}[/red]")

        elif cmd == "/config":
            config_show()

        elif cmd == "/quality":
            quality()

        elif cmd == "/help":
            console.print(
                "Commands:\n"
                "  /run <prompt>         Run a prompt explicitly\n"
                "  /plan                 Show latest plan\n"
                "  /plan create <prompt> Create an execution plan\n"
                "  /plan run <path>      Execute a plan\n"
                "  /history              Show session history\n"
                "  /new                  Start a new session\n"
                "  /clear                Clear session context\n"
                "  /team                 Show team status\n"
                "  /config               Show config\n"
                "  /quality              Show quality scores\n"
                "  /help                 Show this help\n"
                "  /quit                 Exit interactive mode"
            )
        else:
            console.print(f"[yellow]Unknown command: {cmd}. Type /help for commands.[/yellow]")
        return True

    while True:
        try:
            line = Prompt.ask("[chai]")
            if not handle_cmd(line):
                break
        except KeyboardInterrupt:
            console.print("\n[dim]Use /quit to exit.[/dim]")
            continue
        except EOFError:
            break
    console.print("[dim]Goodbye.[/dim]")
