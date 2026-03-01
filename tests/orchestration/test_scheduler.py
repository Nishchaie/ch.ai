"""Tests for TaskScheduler."""

import pytest

from chai.types import RoleType, TaskSpec
from chai.orchestration.scheduler import TaskScheduler


def test_add_tasks_and_get_next_ready():
    scheduler = TaskScheduler()
    tasks = [
        TaskSpec(id="a", title="A", role=RoleType.BACKEND),
        TaskSpec(id="b", title="B", role=RoleType.QA, dependencies=["a"]),
        TaskSpec(id="c", title="C", role=RoleType.FRONTEND),
    ]
    scheduler.add_tasks(tasks)
    ready = scheduler.get_next_ready()
    assert ready is not None
    assert ready.id in ("a", "c")  # a and c have no deps


def test_mark_done_unblocks_dependents():
    scheduler = TaskScheduler()
    tasks = [
        TaskSpec(id="a", title="A", role=RoleType.BACKEND),
        TaskSpec(id="b", title="B", role=RoleType.QA, dependencies=["a"]),
    ]
    scheduler.add_tasks(tasks)
    first = scheduler.get_next_ready()
    assert first.id == "a"
    scheduler.mark_done("a")
    next_ready = scheduler.get_next_ready()
    assert next_ready is not None
    assert next_ready.id == "b"


def test_mark_failed_removes_from_pending_deps():
    scheduler = TaskScheduler()
    tasks = [
        TaskSpec(id="a", title="A", role=RoleType.BACKEND),
        TaskSpec(id="b", title="B", role=RoleType.QA, dependencies=["a"]),
    ]
    scheduler.add_tasks(tasks)
    scheduler.mark_failed("a")
    next_ready = scheduler.get_next_ready()
    assert next_ready is not None
    assert next_ready.id == "b"


def test_has_pending():
    scheduler = TaskScheduler()
    tasks = [TaskSpec(id="a", title="A", role=RoleType.BACKEND)]
    scheduler.add_tasks(tasks)
    assert scheduler.has_pending()
    scheduler.mark_done("a")
    assert not scheduler.has_pending()


def test_get_all_ready():
    scheduler = TaskScheduler()
    tasks = [
        TaskSpec(id="a", title="A", role=RoleType.BACKEND),
        TaskSpec(id="b", title="B", role=RoleType.FRONTEND),
        TaskSpec(id="c", title="C", role=RoleType.QA, dependencies=["a", "b"]),
    ]
    scheduler.add_tasks(tasks)
    ready = scheduler.get_all_ready()
    assert len(ready) == 2
    ids = {r.id for r in ready}
    assert ids == {"a", "b"}
