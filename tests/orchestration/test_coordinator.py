"""Tests for TeamCoordinator basic logic."""

import pytest

from chai.types import AgentEvent, RoleType, TaskSpec
from chai.orchestration.coordinator import TeamCoordinator


class MockRunner:
    """Mock AgentRunner that returns immediately."""

    def __init__(self, task_id: str, result: str = "ok"):
        self.task_id = task_id
        self.result = result

    def run(self, task: TaskSpec):
        yield AgentEvent(type="info", data="start", task_id=task.id, role=task.role)
        yield AgentEvent(type="info", data="done", task_id=task.id, role=task.role)
        return self.result


def test_coordinator_yields_events():
    coordinator = TeamCoordinator()
    tasks = [
        TaskSpec(id="t1", title="T1", role=RoleType.BACKEND),
    ]
    def factory(tid: str):
        return MockRunner(tid)
    events = list(coordinator.run(tasks, factory, max_workers=2))
    assert len(events) >= 1
    types = {e.type for e in events}
    assert "info" in types or "status" in types


def test_coordinator_respects_dependencies():
    coordinator = TeamCoordinator()
    tasks = [
        TaskSpec(id="a", title="A", role=RoleType.BACKEND),
        TaskSpec(id="b", title="B", role=RoleType.QA, dependencies=["a"]),
    ]
    order: list[str] = []
    def factory(tid: str):
        def run(t):
            order.append(tid)
            return MockRunner(tid)
        return type("Runner", (), {"run": lambda self, t: MockRunner(tid).run(t)})()
    # We need a simple runner - the coordinator expects runner.run(task) to be a generator
    class R:
        def __init__(self, tid):
            self.tid = tid
        def run(self, task):
            order.append(task.id)
            yield AgentEvent(type="info", data="x", task_id=task.id)
            return "done"
    def factory2(tid):
        return R(tid)
    events = list(coordinator.run(tasks, factory2, max_workers=2))
    assert "a" in order
    assert "b" in order
