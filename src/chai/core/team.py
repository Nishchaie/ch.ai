"""Team: roster of agents by role, task decomposition, and parallel execution."""

from __future__ import annotations

import logging
import queue
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Dict, Generator, List, Optional

from ..config import ProjectConfig
from ..providers.base import Provider
from ..tools.base import ToolRegistry
from ..types import (
    AgentConfig,
    AgentEvent,
    RoleType,
    TaskSpec,
    TaskStatus,
    TeamConfig,
    TeamRunResult,
    TeamState,
)
from .agent import AgentRunner
from .context import ContextManager
from .role import RoleDefinition, RoleRegistry
from .task import TaskDecomposer, TaskGraph

logger = logging.getLogger(__name__)


def _default_provider_factory(provider_type: str, model: Optional[str] = None) -> Provider:
    """Raise until concrete providers are wired in."""
    raise NotImplementedError(f"No provider implementation for {provider_type}. Install and configure a provider.")


class Team:
    """Manages a roster of agents by role. Coordinates task decomposition and execution."""

    def __init__(
        self,
        config: TeamConfig,
        project_config: ProjectConfig,
        project_dir: Optional[str] = None,
        provider_factory: Optional[Callable[[str, Optional[str]], Provider]] = None,
        tool_registry: Optional[ToolRegistry] = None,
        role_registry: Optional[RoleRegistry] = None,
    ) -> None:
        self._config = config
        self._project_config = project_config
        self._project_dir = project_dir or "."
        self._provider_factory = provider_factory or _default_provider_factory
        self._tools = tool_registry or ToolRegistry(base_dir=self._project_dir)
        self._role_registry = role_registry or RoleRegistry()
        self._context = ContextManager(self._project_dir)
        self._state = TeamState.IDLE

    @property
    def state(self) -> TeamState:
        return self._state

    def add_member(self, agent_config: AgentConfig) -> None:
        """Add or replace a team member by role."""
        self._config.members[agent_config.role] = agent_config

    def remove_member(self, role: RoleType) -> None:
        """Remove a team member by role."""
        if role in self._config.members:
            del self._config.members[role]

    def get_members(self) -> Dict[RoleType, AgentConfig]:
        """Get all team members."""
        return dict(self._config.members)

    def get_status(self) -> Dict:
        """Return team state and per-agent status."""
        return {
            "state": self._state.value,
            "name": self._config.name,
            "members": {
                r.value: {
                    "provider": ac.provider.value,
                    "model": ac.model,
                    "autonomy": ac.autonomy_level.value,
                }
                for r, ac in self._config.members.items()
            },
            "max_concurrent_agents": self._config.max_concurrent_agents,
        }

    def run_direct(self, prompt: str, role: Optional[RoleType] = None) -> Generator[AgentEvent, None, TeamRunResult]:
        """Fast path: skip decomposition, run a single agent immediately."""
        events: list[AgentEvent] = []
        start = time.monotonic()
        result = ""
        target_role = role or self._pick_best_role(prompt)
        task = TaskSpec(
            id="direct-1",
            title=prompt,
            description="",
            role=target_role,
        )

        try:
            self._state = TeamState.EXECUTING
            yield AgentEvent(type="status", data={"phase": "executing", "mode": "direct"})

            runner = self._make_runner(task)
            started = AgentEvent(
                type="status",
                data={"task_started": task.id, "title": task.title},
                role=task.role,
                task_id=task.id,
            )
            events.append(started)
            yield started

            gen = runner.run(task)
            try:
                while True:
                    evt = next(gen)
                    events.append(evt)
                    yield evt
            except StopIteration as e:
                result = e.value or ""

            task.status = TaskStatus.COMPLETED if result else TaskStatus.FAILED
            task.result = result

            done_evt = AgentEvent(
                type="status",
                data={"task_completed": task.id},
                role=task.role,
                task_id=task.id,
            )
            events.append(done_evt)
            yield done_evt

            self._state = TeamState.DONE

        except Exception as ex:
            self._state = TeamState.FAILED
            e = AgentEvent(type="error", data=str(ex))
            events.append(e)
            yield e

        return TeamRunResult(
            tasks=[task],
            results={task.id: result},
            duration_seconds=time.monotonic() - start,
            events=events,
        )

    def run_task(
        self,
        prompt: str,
        use_worktrees: bool = False,
    ) -> Generator[AgentEvent, None, TeamRunResult]:
        """Full flow: decompose -> execute (parallel, optionally in worktrees) -> review."""
        events: list[AgentEvent] = []
        start = time.monotonic()
        graph = TaskGraph()
        results: Dict[str, str] = {}
        worktree_mgr = None

        try:
            self._state = TeamState.PLANNING
            yield AgentEvent(type="status", data={"phase": "planning"})

            lead_config = self._config.members.get(RoleType.LEAD)
            if not lead_config:
                self._state = TeamState.FAILED
                err = AgentEvent(type="error", data="Team has no Lead. Add a Lead agent.")
                events.append(err)
                yield err
                return TeamRunResult(
                    tasks=[],
                    events=events,
                    duration_seconds=time.monotonic() - start,
                )

            provider = self._provider_factory(lead_config.provider.value, lead_config.model)
            decomposer = TaskDecomposer(self._role_registry)
            available_roles = list(self._config.members.keys())
            graph = decomposer.decompose(prompt, provider, available_roles=available_roles)
            yield AgentEvent(type="info", data={"tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "role": t.role.value,
                    "status": t.status.value,
                    "dependencies": list(t.dependencies),
                    "description": t.description or "",
                }
                for t in graph.all_tasks()
            ]})

            # Set up worktrees when requested and in a git repo
            if use_worktrees:
                worktree_mgr = self._init_worktrees(graph)
                if worktree_mgr:
                    yield AgentEvent(type="info", data={"worktrees": "enabled"})

            yield from self._execute_graph(graph, events, worktree_mgr)

        except Exception as ex:
            self._state = TeamState.FAILED
            e = AgentEvent(type="error", data=str(ex))
            events.append(e)
            yield e
        finally:
            if worktree_mgr:
                self._cleanup_worktrees(worktree_mgr, graph)

        return TeamRunResult(
            tasks=graph.all_tasks(),
            results=results,
            duration_seconds=time.monotonic() - start,
            events=events,
        )

    def run_graph(self, tasks: List[TaskSpec]) -> Generator[AgentEvent, None, TeamRunResult]:
        """Execute a pre-built list of tasks (e.g. from a loaded plan), skipping decomposition."""
        events: list[AgentEvent] = []
        start = time.monotonic()
        graph = TaskGraph()

        for task in tasks:
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                graph.add_task(task)
            else:
                task.status = TaskStatus.PENDING
                graph.add_task(task)

        yield AgentEvent(type="info", data={"tasks": [
            {
                "id": t.id,
                "title": t.title,
                "role": t.role.value,
                "status": t.status.value,
                "dependencies": list(t.dependencies),
                "description": t.description or "",
            }
            for t in graph.all_tasks()
        ]})

        try:
            yield from self._execute_graph(graph, events)
        except Exception as ex:
            self._state = TeamState.FAILED
            e = AgentEvent(type="error", data=str(ex))
            events.append(e)
            yield e

        results = {
            t.id: (t.result or t.error or "")
            for t in graph.all_tasks()
            if t.status.value in ("completed", "failed")
        }

        return TeamRunResult(
            tasks=graph.all_tasks(),
            results=results,
            duration_seconds=time.monotonic() - start,
            events=events,
        )

    # -- internal helpers --------------------------------------------------

    def _pick_best_role(self, prompt: str) -> RoleType:
        """Heuristic: choose the best single role for a prompt."""
        lower = prompt.lower()
        if any(kw in lower for kw in ("test", "spec", "assert", "coverage")):
            if RoleType.QA in self._config.members:
                return RoleType.QA
        if any(kw in lower for kw in ("component", "css", "tsx", "jsx", "react", "ui", "frontend", "page")):
            if RoleType.FRONTEND in self._config.members:
                return RoleType.FRONTEND
        if any(kw in lower for kw in ("deploy", "docker", "ci", "cd", "pipeline", "infra")):
            if RoleType.DEPLOYMENT in self._config.members:
                return RoleType.DEPLOYMENT
        if any(kw in lower for kw in ("prompt", "system message", "llm")):
            if RoleType.PROMPT in self._config.members:
                return RoleType.PROMPT
        if RoleType.BACKEND in self._config.members:
            return RoleType.BACKEND
        return next(iter(self._config.members), RoleType.BACKEND)

    def _execute_graph(
        self,
        graph: TaskGraph,
        events: list[AgentEvent],
        worktree_mgr: Optional[object] = None,
    ) -> Generator[AgentEvent, None, None]:
        """Shared execution loop for run_task and run_graph."""
        self._state = TeamState.EXECUTING
        yield AgentEvent(type="status", data={"phase": "executing"})

        max_workers = max(
            1,
            min(
                self._config.max_concurrent_agents,
                len(graph.all_tasks()),
            ),
        )

        event_queue: queue.Queue[AgentEvent] = queue.Queue()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            active_futures: Dict[Future, tuple[str, RoleType]] = {}

            while not graph.is_complete():
                ready = graph.get_ready_tasks()
                for task in ready:
                    graph.mark_in_progress(task.id)
                    runner = self._make_runner(task)

                    started = AgentEvent(
                        type="status",
                        data={"task_started": task.id, "title": task.title},
                        role=task.role,
                        task_id=task.id,
                    )
                    events.append(started)
                    yield started

                    future = executor.submit(
                        self._run_and_stream, runner, task, event_queue
                    )
                    active_futures[future] = (task.id, task.role)

                if not active_futures:
                    break

                while active_futures:
                    while True:
                        try:
                            evt = event_queue.get_nowait()
                            events.append(evt)
                            yield evt
                        except queue.Empty:
                            break

                    newly_done = [f for f in active_futures if f.done()]
                    for future in newly_done:
                        task_id, role = active_futures.pop(future)
                        try:
                            result = future.result()
                            graph.mark_complete(task_id, result)
                            done_evt = AgentEvent(
                                type="status",
                                data={"task_completed": task_id},
                                role=role,
                                task_id=task_id,
                            )
                            events.append(done_evt)
                            yield done_evt
                        except Exception as ex:
                            graph.mark_failed(task_id, str(ex))
                            e = AgentEvent(
                                type="error", data=str(ex), role=role, task_id=task_id
                            )
                            events.append(e)
                            yield e

                    if active_futures and not newly_done:
                        time.sleep(0.05)

                while True:
                    try:
                        evt = event_queue.get_nowait()
                        events.append(evt)
                        yield evt
                    except queue.Empty:
                        break

        # Merge worktree branches if applicable
        if worktree_mgr:
            self._merge_worktree_branches(graph)

        self._state = TeamState.REVIEWING
        yield AgentEvent(type="status", data={"phase": "reviewing"})

        self._state = TeamState.DONE

    def _init_worktrees(self, graph: TaskGraph) -> Optional[object]:
        """Create per-task worktrees. Returns the WorktreeManager or None on failure."""
        try:
            from ..orchestration.worktree import WorktreeManager
        except ImportError:
            logger.warning("WorktreeManager not available, running in shared workspace")
            return None

        mgr = WorktreeManager(repo_path=self._project_dir)
        try:
            for task in graph.all_tasks():
                wt_path = mgr.create_worktree(task.id)
                task.worktree_path = wt_path
            return mgr
        except RuntimeError as exc:
            logger.warning("Could not create worktrees (%s), falling back to shared workspace", exc)
            for task in graph.all_tasks():
                task.worktree_path = None
            return None

    def _merge_worktree_branches(self, graph: TaskGraph) -> None:
        """Merge completed worktree branches back to the current branch."""
        try:
            from ..orchestration.merge import MergeManager
            from ..orchestration.worktree import _sanitize_task_id
        except ImportError:
            return

        merger = MergeManager(repo_path=self._project_dir)
        try:
            import subprocess
            current_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self._project_dir,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip() or "main"
        except Exception:
            current_branch = "main"

        for task in graph.all_tasks():
            if task.status == TaskStatus.COMPLETED and task.worktree_path:
                branch_name = f"chai/{_sanitize_task_id(task.id)}"
                try:
                    merger.merge_branch(branch_name, current_branch)
                except Exception as exc:
                    logger.warning("Failed to merge branch %s: %s", branch_name, exc)

    def _cleanup_worktrees(self, worktree_mgr: object, graph: TaskGraph) -> None:
        """Remove worktrees after execution completes."""
        try:
            from ..orchestration.worktree import WorktreeManager
            if isinstance(worktree_mgr, WorktreeManager):
                worktree_mgr.cleanup_all()
        except Exception as exc:
            logger.warning("Worktree cleanup failed: %s", exc)

    def _make_runner(self, task: TaskSpec) -> AgentRunner:
        """Build an AgentRunner for the task's role, falling back to default provider."""
        ac = self._config.members.get(task.role)
        if not ac:
            ac = AgentConfig(
                role=task.role,
                provider=self._config.default_provider,
                model=self._config.default_model,
            )
        role_def = self._role_registry.get_role(task.role)
        if not role_def:
            role_def = RoleDefinition(
                role_type=task.role,
                name=task.role.value,
                description="",
                system_prompt_template="{task}",
            )
        provider = self._provider_factory(ac.provider.value, ac.model)
        base_dir = task.worktree_path or self._project_dir
        tools = ToolRegistry(base_dir=base_dir, role=task.role)
        for name in self._tools.list_tools():
            t = self._tools.get(name)
            if t:
                tools.register(t)
        context = self._context.get_context_for_role(role_def, task)
        return AgentRunner(role_def, provider, tools, ac, context)

    def _run_and_stream(
        self,
        runner: AgentRunner,
        task: TaskSpec,
        event_queue: queue.Queue[AgentEvent],
    ) -> str:
        """Run agent, streaming events into the shared queue. Returns the result string."""
        result = ""
        try:
            gen = runner.run(task)
            while True:
                try:
                    evt = next(gen)
                    event_queue.put(evt)
                except StopIteration as e:
                    result = e.value or ""
                    break
        except Exception as ex:
            event_queue.put(
                AgentEvent(type="error", data=str(ex), role=task.role, task_id=task.id)
            )
            result = str(ex)
        return result
