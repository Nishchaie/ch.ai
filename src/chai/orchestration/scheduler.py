"""Task scheduler with priority queue and dependency awareness."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, List, Optional

from ..types import RoleType, TaskSpec, TaskStatus


class TaskScheduler:
    """Priority queue with dependency awareness. Per-role queues. Yields ready tasks."""

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskSpec] = {}
        self._completed: set[str] = set()
        self._failed: set[str] = set()
        self._pending_deps: Dict[str, List[str]] = {}  # task_id -> list of dep ids not yet done
        self._per_role: Dict[RoleType, List[str]] = defaultdict(list)  # role -> task_ids

    def add_tasks(self, tasks: List[TaskSpec]) -> None:
        """Add tasks to the scheduler. Dependencies must be in tasks or already done."""
        for task in tasks:
            self._tasks[task.id] = task
            deps = [d for d in task.dependencies if d in self._tasks or d in self._completed]
            remaining = [d for d in task.dependencies if d not in self._completed and d not in self._failed]
            self._pending_deps[task.id] = remaining
            self._per_role[task.role].append(task.id)

    def get_next_ready(self) -> Optional[TaskSpec]:
        """Return the next task that has all dependencies satisfied, or None if none ready."""
        for role in RoleType:
            for task_id in self._per_role[role]:
                if task_id in self._completed or task_id in self._failed:
                    continue
                task = self._tasks.get(task_id)
                if not task:
                    continue
                if not self._pending_deps.get(task_id):
                    return task
        return None

    def get_all_ready(self) -> List[TaskSpec]:
        """Return all tasks that are ready to run (dependencies satisfied)."""
        ready: List[TaskSpec] = []
        seen = set()
        for role in RoleType:
            for task_id in self._per_role[role]:
                if task_id in self._completed or task_id in self._failed or task_id in seen:
                    continue
                task = self._tasks.get(task_id)
                if not task:
                    continue
                if not self._pending_deps.get(task_id):
                    ready.append(task)
                    seen.add(task_id)
        return ready

    def mark_done(self, task_id: str) -> None:
        """Mark a task as completed. Unblocks dependents."""
        self._completed.add(task_id)
        # Unblock dependents that were waiting on this task
        for tid, pending in list(self._pending_deps.items()):
            if task_id in pending:
                pending.remove(task_id)

    def mark_failed(self, task_id: str) -> None:
        """Mark a task as failed. Unblocks dependents (they may fail due to missing input)."""
        self._failed.add(task_id)
        for tid, pending in list(self._pending_deps.items()):
            if task_id in pending:
                pending.remove(task_id)

    def is_done(self, task_id: str) -> bool:
        """Check if task is marked done."""
        return task_id in self._completed

    def is_failed(self, task_id: str) -> bool:
        """Check if task is marked failed."""
        return task_id in self._failed

    def has_pending(self) -> bool:
        """True if there are any tasks not yet completed or failed."""
        for task_id in self._tasks:
            if task_id not in self._completed and task_id not in self._failed:
                return True
        return False
