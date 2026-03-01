"""Team: roster of agents by role, task decomposition, and parallel execution."""

from __future__ import annotations

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
    TeamConfig,
    TeamRunResult,
    TeamState,
)
from .agent import AgentRunner
from .context import ContextManager
from .role import RoleDefinition, RoleRegistry
from .task import TaskDecomposer, TaskGraph


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

    def run_task(self, prompt: str) -> Generator[AgentEvent, None, TeamRunResult]:
        """Main flow: plan -> decompose -> execute (parallel) -> review."""
        events: list[AgentEvent] = []
        start = time.monotonic()
        graph = TaskGraph()
        results: Dict[str, str] = {}

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
                        # Drain queued events from worker threads
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

                    # Final drain after all futures in this batch are done
                    while True:
                        try:
                            evt = event_queue.get_nowait()
                            events.append(evt)
                            yield evt
                        except queue.Empty:
                            break

            self._state = TeamState.REVIEWING
            yield AgentEvent(type="status", data={"phase": "reviewing"})

            results = {
                t.id: (t.result or t.error or "")
                for t in graph.all_tasks()
                if t.status.value in ("completed", "failed")
            }
            self._state = TeamState.DONE

        except Exception as ex:
            self._state = TeamState.FAILED
            e = AgentEvent(type="error", data=str(ex))
            events.append(e)
            yield e

        return TeamRunResult(
            tasks=graph.all_tasks(),
            results=results,
            duration_seconds=time.monotonic() - start,
            events=events,
        )

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
        tools = ToolRegistry(base_dir=self._project_dir, role=task.role)
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
