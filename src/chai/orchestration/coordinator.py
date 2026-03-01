"""Team coordinator: dispatches tasks to agents, tracks progress, yields events."""

from __future__ import annotations

import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Generator, List, Optional

from ..types import AgentEvent, TaskSpec, TaskStatus


AgentFactory = Callable[[str], Any]  # task_id -> AgentRunner-like instance


class _EventOrResult:
    """Sentinel: either an event to yield or a task completion."""

    def __init__(self, event: Optional[AgentEvent] = None, task_id: Optional[str] = None, success: Optional[bool] = None, output: Optional[str] = None):
        self.event = event
        self.task_id = task_id
        self.success = success
        self.output = output


def _run_task_and_queue_events(
    runner: Any,
    task: TaskSpec,
    event_queue: queue.Queue,
) -> None:
    """Run task, put all events in queue, then put completion sentinel."""
    try:
        gen = runner.run(task)
        result = None
        try:
            while True:
                evt = next(gen)
                event_queue.put(_EventOrResult(event=evt))
        except StopIteration as e:
            result = str(e.value) if e.value is not None else ""
        event_queue.put(_EventOrResult(task_id=task.id, success=True, output=result or "Completed"))
    except Exception as e:
        event_queue.put(_EventOrResult(task_id=task.id, success=False, output=str(e)))


class TeamCoordinator:
    """Receives a TaskGraph, dispatches ready tasks via ThreadPoolExecutor, yields AgentEvent."""

    def __init__(self) -> None:
        pass

    def run(
        self,
        task_graph: List[TaskSpec],
        agent_factory: AgentFactory,
        max_workers: int = 4,
    ) -> Generator[AgentEvent, None, None]:
        """Run all tasks in the graph. Yields AgentEvent as tasks progress."""
        task_map = {t.id: t for t in task_graph}
        completed: set[str] = set()
        failed: set[str] = set()
        in_flight: set[str] = set()
        event_queue: queue.Queue = queue.Queue()

        def deps_satisfied(task: TaskSpec) -> bool:
            for dep in task.dependencies:
                if dep not in completed and dep not in failed:
                    return False
            return True

        def get_ready() -> List[TaskSpec]:
            return [
                t for t in task_graph
                if t.id not in completed
                and t.id not in failed
                and t.id not in in_flight
                and deps_satisfied(t)
            ]

        def drain_until_completion(target_task_id: Optional[str] = None) -> Generator[AgentEvent, None, None]:
            """Drain queue, yield events, and yield completion event when target_task_id done."""
            while True:
                try:
                    item = event_queue.get_nowait()
                except queue.Empty:
                    return
                if item.event:
                    yield item.event
                elif item.task_id is not None:
                    in_flight.discard(item.task_id)
                    task = task_map.get(item.task_id)
                    if item.success:
                        completed.add(item.task_id)
                        if task:
                            task.status = TaskStatus.COMPLETED
                            task.result = item.output
                        yield AgentEvent(
                            type="status",
                            data={"task_id": item.task_id, "status": "completed", "result": item.output},
                            task_id=item.task_id,
                            role=task.role if task else None,
                        )
                    else:
                        failed.add(item.task_id)
                        if task:
                            task.status = TaskStatus.FAILED
                            task.error = item.output
                        yield AgentEvent(
                            type="error",
                            data={"task_id": item.task_id, "error": item.output},
                            task_id=item.task_id,
                            role=task.role if task else None,
                        )
                    if target_task_id is None or item.task_id == target_task_id:
                        return

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: dict[Any, str] = {}

            while True:
                ready = get_ready()
                slots = max(0, max_workers - len(in_flight))
                for task in ready[:slots]:
                    if task.id in in_flight:
                        continue
                    runner = agent_factory(task.id)
                    if runner is None:
                        continue
                    t_copy = TaskSpec(
                        id=task.id,
                        title=task.title,
                        description=task.description,
                        role=task.role,
                        dependencies=task.dependencies,
                        status=TaskStatus.IN_PROGRESS,
                        acceptance_criteria=task.acceptance_criteria,
                    )
                    fut = executor.submit(_run_task_and_queue_events, runner, t_copy, event_queue)
                    futures[fut] = task.id
                    in_flight.add(task.id)
                    yield AgentEvent(
                        type="status",
                        data={"task_id": task.id, "status": "in_progress"},
                        task_id=task.id,
                        role=task.role,
                    )

                if not futures:
                    if not get_ready() and not in_flight:
                        break
                    break

                # Wait for at least one future to complete; drain events while waiting
                done_futures = []
                for future in as_completed(futures):
                    done_futures.append(future)
                    break

                for future in done_futures:
                    task_id = futures.pop(future)
                    try:
                        future.result()
                    except Exception:
                        pass
                    yield from drain_until_completion(task_id)
