"""Tests for TaskGraph and TaskDecomposer."""

import pytest

from chai.core.task import TaskGraph, TaskDecomposer
from chai.types import RoleType, TaskSpec, TaskStatus


class TestTaskGraph:
    """Test TaskGraph operations."""

    def test_add_and_get_task(self) -> None:
        g = TaskGraph()
        t = TaskSpec(id="t1", title="Task 1", role=RoleType.BACKEND)
        g.add_task(t)
        assert g.get_task("t1") is t
        assert g.get_task("t2") is None

    def test_get_ready_tasks_empty_deps(self) -> None:
        g = TaskGraph()
        t1 = TaskSpec(id="t1", title="T1", role=RoleType.BACKEND)
        g.add_task(t1)
        ready = g.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "t1"

    def test_get_ready_tasks_with_deps(self) -> None:
        g = TaskGraph()
        t1 = TaskSpec(id="t1", title="T1", role=RoleType.BACKEND)
        t2 = TaskSpec(id="t2", title="T2", role=RoleType.QA, dependencies=["t1"])
        g.add_task(t1)
        g.add_task(t2)
        ready = g.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "t1"
        g.mark_complete("t1", "done")
        ready = g.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "t2"

    def test_mark_complete(self) -> None:
        g = TaskGraph()
        t = TaskSpec(id="t1", title="T1", role=RoleType.BACKEND)
        g.add_task(t)
        g.mark_complete("t1", "result")
        assert g.get_task("t1").status == TaskStatus.COMPLETED
        assert g.get_task("t1").result == "result"

    def test_mark_failed(self) -> None:
        g = TaskGraph()
        t = TaskSpec(id="t1", title="T1", role=RoleType.BACKEND)
        g.add_task(t)
        g.mark_failed("t1", "error")
        assert g.get_task("t1").status == TaskStatus.FAILED
        assert g.get_task("t1").error == "error"

    def test_mark_in_progress(self) -> None:
        g = TaskGraph()
        t = TaskSpec(id="t1", title="T1", role=RoleType.BACKEND)
        g.add_task(t)
        g.mark_in_progress("t1")
        assert g.get_task("t1").status == TaskStatus.IN_PROGRESS

    def test_is_complete(self) -> None:
        g = TaskGraph()
        assert g.is_complete()
        t = TaskSpec(id="t1", title="T1", role=RoleType.BACKEND)
        g.add_task(t)
        assert not g.is_complete()
        g.mark_complete("t1", "ok")
        assert g.is_complete()

    def test_get_status(self) -> None:
        g = TaskGraph()
        g.add_task(TaskSpec(id="t1", title="T1", role=RoleType.BACKEND))
        g.add_task(TaskSpec(id="t2", title="T2", role=RoleType.QA))
        status = g.get_status()
        assert status["pending"] == 2
        g.mark_complete("t1", "ok")
        status = g.get_status()
        assert status["pending"] == 1
        assert status["completed"] == 1

    def test_topological_sort(self) -> None:
        g = TaskGraph()
        g.add_task(TaskSpec(id="a", title="A", role=RoleType.BACKEND))
        g.add_task(TaskSpec(id="b", title="B", role=RoleType.BACKEND, dependencies=["a"]))
        g.add_task(TaskSpec(id="c", title="C", role=RoleType.QA, dependencies=["b"]))
        order = g.topological_sort()
        ids = [t.id for t in order]
        assert ids.index("a") < ids.index("b")
        assert ids.index("b") < ids.index("c")

    def test_dependency_tracking(self) -> None:
        g = TaskGraph()
        t1 = TaskSpec(id="t1", title="T1", role=RoleType.BACKEND)
        t2 = TaskSpec(id="t2", title="T2", role=RoleType.QA, dependencies=["t1"])
        g.add_task(t1)
        g.add_task(t2)
        g.mark_failed("t1", "failed")
        ready = g.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "t2"


class TestTaskDecomposer:
    """Test TaskDecomposer (with mock provider)."""

    def test_decompose_fallback_on_invalid_json(self) -> None:
        from chai.providers.base import Provider, ProviderResponse

        class MockProvider(Provider):
            @property
            def manages_own_tools(self) -> bool:
                return True

            def chat(self, messages, system, tools=None, max_tokens=8192, stream=False):
                return ProviderResponse(text="not valid json")

            def make_tool_schema(self, tools):
                return []

        decomp = TaskDecomposer()
        graph = decomp.decompose("Do something", MockProvider())
        assert len(graph.all_tasks()) == 1
        assert graph.get_task("task-1").title == "Execute request"

    def test_decompose_parses_valid_json(self) -> None:
        from chai.providers.base import Provider, ProviderResponse

        class MockProvider(Provider):
            @property
            def manages_own_tools(self) -> bool:
                return True

            def chat(self, messages, system, tools=None, max_tokens=8192, stream=False):
                return ProviderResponse(
                    text='{"tasks": [{"id": "be-1", "role": "backend", "title": "Build API", "description": "Build endpoints", "depends_on": [], "acceptance_criteria": []}]}'
                )

            def make_tool_schema(self, tools):
                return []

        decomp = TaskDecomposer()
        graph = decomp.decompose("Build an API", MockProvider())
        assert len(graph.all_tasks()) == 1
        t = graph.get_task("be-1")
        assert t is not None
        assert t.title == "Build API"
        assert t.role == RoleType.BACKEND
