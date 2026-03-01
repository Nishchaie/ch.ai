"""Task graph (DAG) and task decomposition for ch.ai."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

from ..providers.base import Provider, ProviderResponse
from ..types import RoleType, TaskSpec, TaskStatus
from .role import RoleRegistry


class TaskGraph:
    """DAG of TaskSpec nodes with dependency tracking."""

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskSpec] = {}
        self._dependencies: Dict[str, List[str]] = {}  # task_id -> list of task_ids it depends on

    def add_task(self, task: TaskSpec) -> None:
        """Add a task to the graph. Overwrites if same id."""
        self._tasks[task.id] = task
        self._dependencies[task.id] = list(task.dependencies)

    def get_task(self, task_id: str) -> Optional[TaskSpec]:
        """Get a task by id."""
        return self._tasks.get(task_id)

    def get_ready_tasks(self) -> List[TaskSpec]:
        """Return tasks whose dependencies are all completed or failed."""
        ready: List[TaskSpec] = []
        for task_id, task in self._tasks.items():
            if task.status != TaskStatus.PENDING:
                continue
            deps = self._dependencies.get(task_id, [])
            if all(
                self._tasks.get(dep_id) and
                self._tasks[dep_id].status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                for dep_id in deps
            ):
                ready.append(task)
        return ready

    def mark_complete(self, task_id: str, result: str) -> None:
        """Mark a task as completed with result."""
        if task_id in self._tasks:
            self._tasks[task_id].status = TaskStatus.COMPLETED
            self._tasks[task_id].result = result
            self._tasks[task_id].error = None

    def mark_failed(self, task_id: str, error: str) -> None:
        """Mark a task as failed with error."""
        if task_id in self._tasks:
            self._tasks[task_id].status = TaskStatus.FAILED
            self._tasks[task_id].error = error
            self._tasks[task_id].result = None

    def mark_in_progress(self, task_id: str) -> None:
        """Mark a task as in progress."""
        if task_id in self._tasks:
            self._tasks[task_id].status = TaskStatus.IN_PROGRESS

    def is_complete(self) -> bool:
        """True if all tasks are completed or failed."""
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
            for t in self._tasks.values()
        )

    def get_status(self) -> Dict[str, int]:
        """Return counts per status."""
        counts: Dict[str, int] = {}
        for task in self._tasks.values():
            s = task.status.value
            counts[s] = counts.get(s, 0) + 1
        return counts

    def topological_sort(self) -> List[TaskSpec]:
        """Return tasks in topological order (dependencies before dependents)."""
        in_degree: Dict[str, int] = {tid: 0 for tid in self._tasks}
        for task_id, deps in self._dependencies.items():
            for dep in deps:
                if dep in self._tasks:
                    in_degree[task_id] += 1
        # Reverse: we want deps first, so dependents have higher in-degree from deps
        # Actually: in_degree[task_id] = number of deps. For topo sort we need
        # "dep comes before task" so we count how many deps each task has.
        # Kahn's: start with nodes that have 0 dependencies.
        indeg: Dict[str, int] = {}
        for task_id in self._tasks:
            indeg[task_id] = sum(1 for d in self._dependencies.get(task_id, []) if d in self._tasks)
        queue = [tid for tid, d in indeg.items() if d == 0]
        result: List[TaskSpec] = []
        while queue:
            n = queue.pop(0)
            result.append(self._tasks[n])
            for tid, deps in self._dependencies.items():
                if n in deps:
                    indeg[tid] -= 1
                    if indeg[tid] == 0:
                        queue.append(tid)
        # Any remaining (cycle) append at end
        for tid in self._tasks:
            if self._tasks[tid] not in result:
                result.append(self._tasks[tid])
        return result

    def all_tasks(self) -> List[TaskSpec]:
        """Return all tasks (unordered)."""
        return list(self._tasks.values())


class TaskDecomposer:
    """Decomposes high-level prompts into TaskGraph using Team Lead agent."""

    def __init__(self, role_registry: Optional[RoleRegistry] = None) -> None:
        self._registry = role_registry or RoleRegistry()

    def decompose(
        self,
        prompt: str,
        provider: Provider,
        system_prompt: Optional[str] = None,
        available_roles: Optional[List[RoleType]] = None,
    ) -> TaskGraph:
        """Call Team Lead agent to decompose prompt into structured TaskGraph."""
        lead = self._registry.get_role(RoleType.LEAD)
        sys_prompt = system_prompt or (lead.system_prompt_template if lead else "")

        roles_constraint = ""
        if available_roles:
            role_names = [r.value for r in available_roles if r != RoleType.LEAD]
            roles_constraint = (
                f"\n\nIMPORTANT: Only assign tasks to these available roles: "
                f"{', '.join(role_names)}. Do NOT use any other roles."
            )
        full_prompt = f"Decompose this request into a task graph:\n\n{prompt}{roles_constraint}"

        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": full_prompt},
        ]

        raw = provider.chat(
            messages=messages,
            system=sys_prompt,
            tools=None,
            max_tokens=8192,
            stream=False,
        )

        response: ProviderResponse
        if isinstance(raw, Generator):
            # Generator (stream=True case); consume and get final value
            try:
                while True:
                    next(raw)
            except StopIteration as e:
                response = e.value if e.value is not None else ProviderResponse(text="")
        else:
            response = raw

        text = response.text

        graph = TaskGraph()
        parsed = self._parse_json_output(text)
        if not parsed or "tasks" not in parsed:
            # Fallback: single task
            graph.add_task(TaskSpec(
                id="task-1",
                title="Execute request",
                description=prompt,
                role=RoleType.BACKEND,
            ))
            return graph

        for t in parsed["tasks"]:
            task_id = str(t.get("id", f"task-{len(graph.all_tasks()) + 1}"))
            role_str = str(t.get("role", "backend")).lower()
            try:
                role = RoleType(role_str)
            except ValueError:
                logger.warning("Unknown role %r for task %s, falling back to backend", role_str, task_id)
                role = RoleType.BACKEND
            if available_roles and role not in available_roles:
                fallback = RoleType.BACKEND if RoleType.BACKEND in available_roles else available_roles[0]
                logger.warning(
                    "Role %s not available for task %s, remapping to %s",
                    role.value, task_id, fallback.value,
                )
                role = fallback
            depends_on = t.get("depends_on") or t.get("dependencies") or []
            graph.add_task(TaskSpec(
                id=task_id,
                title=str(t.get("title", task_id)),
                description=str(t.get("description", "")),
                role=role,
                dependencies=list(depends_on),
                acceptance_criteria=list(t.get("acceptance_criteria") or []),
            ))
        return graph

    def _parse_json_output(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from model output (handles markdown code blocks)."""
        text = text.strip()
        # Try raw parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to extract ```json ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
        # Try first { ... }
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None
