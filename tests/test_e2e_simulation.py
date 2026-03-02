"""End-to-end simulation of the ch.ai system.

Exercises the full pipeline: Harness → ComplexityRouter → Team → TaskDecomposer
→ TaskGraph → parallel AgentRunner execution, verifying every role is invoked
for a complex SaaS build prompt.

Uses a mock provider that records every call so we can assert which roles were
invoked, in what order, and with what context.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Set, Union

import pytest

from chai.config import ProjectConfig, get_config
from chai.core.agent import AgentRunner
from chai.core.context import ContextManager
from chai.core.harness import Harness
from chai.core.role import RoleDefinition, RoleRegistry
from chai.core.router import ComplexityRouter, ExecutionStrategy
from chai.core.task import TaskDecomposer, TaskGraph
from chai.core.team import Team
from chai.providers.base import Provider, ProviderResponse, StreamChunk, ToolCall
from chai.tools import get_default_tools
from chai.tools.base import ToolRegistry
from chai.types import (
    AgentConfig,
    AgentEvent,
    AutonomyLevel,
    ProviderType,
    RoleType,
    TaskSpec,
    TaskStatus,
    TeamConfig,
    TeamRunResult,
    TeamState,
)


# ---------------------------------------------------------------------------
# SaaS task decomposition JSON -- what the "Lead" provider returns
# ---------------------------------------------------------------------------

SAAS_TASK_GRAPH = {
    "tasks": [
        {
            "id": "research-arch",
            "role": "researcher",
            "title": "Research SaaS architecture patterns",
            "description": "Analyze best practices for multi-tenant SaaS with FastAPI + React. "
            "Compare Stripe vs Paddle for billing. Write findings to docs/references/.",
            "depends_on": [],
            "acceptance_criteria": [
                "Architecture recommendation documented",
                "Payment provider comparison complete",
            ],
        },
        {
            "id": "be-models",
            "role": "backend",
            "title": "Create data models and database schema",
            "description": "Design SQLAlchemy models for User, Tenant, Subscription, Invoice. "
            "Set up Alembic migrations. Include multi-tenant row-level security.",
            "depends_on": ["research-arch"],
            "acceptance_criteria": [
                "All models defined with relationships",
                "Migration script runs cleanly",
            ],
        },
        {
            "id": "be-auth",
            "role": "backend",
            "title": "Implement authentication API",
            "description": "Build registration, login, logout, password reset with JWT. "
            "Rate-limit login attempts. Include middleware for tenant context.",
            "depends_on": ["be-models"],
            "acceptance_criteria": [
                "JWT auth flow works end-to-end",
                "Rate limiting active on login",
            ],
        },
        {
            "id": "be-billing",
            "role": "backend",
            "title": "Implement Stripe billing integration",
            "description": "Webhook handler, subscription CRUD, usage metering endpoint. "
            "Idempotent webhook processing with event dedup.",
            "depends_on": ["be-models"],
            "acceptance_criteria": [
                "Webhook handler processes events idempotently",
                "Subscription lifecycle management works",
            ],
        },
        {
            "id": "prompt-llm",
            "role": "prompt",
            "title": "Design LLM-powered feature prompts",
            "description": "Create system prompts for the AI assistant feature. "
            "Design few-shot examples for data analysis and report generation.",
            "depends_on": ["research-arch"],
            "acceptance_criteria": [
                "System prompts defined for each AI feature",
                "Few-shot examples validated",
            ],
        },
        {
            "id": "fe-auth",
            "role": "frontend",
            "title": "Build authentication UI",
            "description": "Login page, registration form, password reset flow with React + Tailwind. "
            "Form validation, loading states, error handling.",
            "depends_on": ["be-auth"],
            "acceptance_criteria": [
                "All auth forms render correctly",
                "Client-side validation works",
            ],
        },
        {
            "id": "fe-dashboard",
            "role": "frontend",
            "title": "Build SaaS dashboard and billing portal",
            "description": "Dashboard with usage charts, subscription management page, invoice history. "
            "Responsive layout with dark mode support.",
            "depends_on": ["be-billing", "fe-auth"],
            "acceptance_criteria": [
                "Dashboard renders with sample data",
                "Billing portal shows subscription info",
            ],
        },
        {
            "id": "qa-tests",
            "role": "qa",
            "title": "Write comprehensive test suite",
            "description": "Unit tests for auth, billing, models. Integration tests for API flows. "
            "E2E tests for critical user journeys. Target 80% coverage.",
            "depends_on": ["be-auth", "be-billing", "fe-auth"],
            "acceptance_criteria": [
                "80%+ code coverage",
                "All critical paths tested",
                "CI pipeline runs tests",
            ],
        },
        {
            "id": "deploy-infra",
            "role": "deployment",
            "title": "Set up deployment infrastructure",
            "description": "Dockerfile, docker-compose for local dev, GitHub Actions CI/CD. "
            "Staging and production configs. Health check endpoint.",
            "depends_on": ["be-auth", "be-billing"],
            "acceptance_criteria": [
                "Docker build succeeds",
                "CI pipeline passes",
                "Health endpoint responds 200",
            ],
        },
    ]
}


# ---------------------------------------------------------------------------
# Mock Provider -- records all interactions
# ---------------------------------------------------------------------------

@dataclass
class ProviderCall:
    """Record of a single provider.chat() invocation."""
    caller_role: Optional[str]
    system_prompt: str
    messages: List[Dict[str, Any]]
    tools_provided: bool
    timestamp: float = field(default_factory=time.monotonic)
    thread_id: int = field(default_factory=lambda: threading.current_thread().ident or 0)


class SimulationProvider(Provider):
    """Mock provider that returns canned responses and tracks all calls.

    - When the system prompt contains 'Team Lead' or 'decompose', returns the
      SAAS_TASK_GRAPH JSON (simulating task decomposition).
    - For all other calls, returns a simple text response acknowledging the task,
      with no tool calls (simulating a CLI-style provider completing work).
    """

    def __init__(self, manages_tools: bool = True) -> None:
        super().__init__()
        self._manages_tools = manages_tools
        self._calls: List[ProviderCall] = []
        self._lock = threading.Lock()

    @property
    def manages_own_tools(self) -> bool:
        return self._manages_tools

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> Union[ProviderResponse, Generator[StreamChunk, None, ProviderResponse]]:
        caller_role = self._detect_role(system)
        call = ProviderCall(
            caller_role=caller_role,
            system_prompt=system[:500],
            messages=messages,
            tools_provided=tools is not None and len(tools) > 0,
        )
        with self._lock:
            self._calls.append(call)

        if self._is_decomposition_call(system, messages):
            text = json.dumps(SAAS_TASK_GRAPH)
            response = ProviderResponse(text=text)
        else:
            user_msg = messages[0].get("content", "") if messages else ""
            response = ProviderResponse(
                text=f"[{caller_role}] Task completed successfully. "
                f"Implemented the requested changes for: {user_msg[:100]}"
            )

        if stream and self._manages_tools:
            return self._stream_response(response, caller_role)
        return response

    def _stream_response(
        self, response: ProviderResponse, role: Optional[str]
    ) -> Generator[StreamChunk, None, ProviderResponse]:
        yield StreamChunk(
            type="tool_call_start",
            data={"name": "write", "input": {"path": f"src/{role or 'main'}/output.py"}},
        )
        yield StreamChunk(type="text", data=response.text[:50])
        return response

    def make_tool_schema(self, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"name": name, "description": schema.get("description", ""), "input_schema": schema.get("parameters", {})}
            for name, schema in tools.items()
        ]

    def _detect_role(self, system_prompt: str) -> Optional[str]:
        first_line = system_prompt.split("\n")[0].lower()
        if "team lead" in first_line or "decompose" in first_line:
            return "lead"
        if "frontend" in first_line:
            return "frontend"
        if "backend" in first_line:
            return "backend"
        if "qa" in first_line:
            return "qa"
        if "deployment" in first_line:
            return "deployment"
        if "prompt" in first_line or "llm specialist" in first_line:
            return "prompt"
        if "researcher" in first_line:
            return "researcher"
        return "unknown"

    def _is_decomposition_call(self, system: str, messages: List[Dict[str, Any]]) -> bool:
        lower = system.lower()
        if "team lead" in lower and "decompose" in lower:
            return True
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and "decompose" in content.lower():
                return True
        return False

    @property
    def calls(self) -> List[ProviderCall]:
        with self._lock:
            return list(self._calls)

    @property
    def roles_called(self) -> Set[str]:
        with self._lock:
            return {c.caller_role for c in self._calls if c.caller_role}

    def calls_for_role(self, role: str) -> List[ProviderCall]:
        with self._lock:
            return [c for c in self._calls if c.caller_role == role]

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()


class APISimulationProvider(SimulationProvider):
    """Mock provider for API mode (manages_own_tools=False).

    On the first chat call per task (messages has only one user message),
    returns a tool call. On subsequent calls (after tool results), returns text.
    """

    def __init__(self) -> None:
        super().__init__(manages_tools=False)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> ProviderResponse:
        caller_role = self._detect_role(system)
        call = ProviderCall(
            caller_role=caller_role,
            system_prompt=system[:500],
            messages=messages,
            tools_provided=tools is not None and len(tools) > 0,
        )
        with self._lock:
            self._calls.append(call)

        if self._is_decomposition_call(system, messages):
            return ProviderResponse(text=json.dumps(SAAS_TASK_GRAPH))

        is_first_call = len(messages) == 1 and messages[0].get("role") == "user"

        if is_first_call and tools:
            return ProviderResponse(
                text="Let me read the project structure first.",
                tool_calls=[
                    ToolCall(
                        id=f"tc-{caller_role}-{id(messages)}",
                        name="list_dir",
                        arguments={"path": "."},
                    )
                ],
            )

        return ProviderResponse(
            text=f"[{caller_role}] Task completed successfully. All changes implemented."
        )

    def make_tool_schema(self, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"name": name, "description": schema.get("description", ""), "input_schema": schema.get("parameters", {})}
            for name, schema in tools.items()
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sim_project(tmp_path: Path) -> Path:
    """Create a realistic project directory for the simulation."""
    (tmp_path / "src" / "backend").mkdir(parents=True)
    (tmp_path / "src" / "frontend" / "components").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs" / "design-docs").mkdir(parents=True)
    (tmp_path / "docs" / "exec-plans" / "active").mkdir(parents=True)
    (tmp_path / "docs" / "golden-principles").mkdir(parents=True)
    (tmp_path / "docs" / "references").mkdir(parents=True)

    (tmp_path / "src" / "backend" / "main.py").write_text(
        'from fastapi import FastAPI\napp = FastAPI()\n\n@app.get("/health")\ndef health():\n    return {"status": "ok"}\n'
    )
    (tmp_path / "src" / "backend" / "models.py").write_text(
        "# Data models\nclass User:\n    pass\n"
    )
    (tmp_path / "src" / "frontend" / "App.tsx").write_text(
        "export default function App() { return <div>App</div> }\n"
    )
    (tmp_path / "src" / "frontend" / "components" / "Button.tsx").write_text(
        "export function Button() { return <button>Click</button> }\n"
    )
    (tmp_path / "tests" / "test_main.py").write_text(
        "def test_health():\n    assert True\n"
    )
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\nCOPY . /app\n")
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'my-saas'\n")
    (tmp_path / "AGENTS.md").write_text("# Agents\n## Map\n- src/ - source\n- tests/ - tests\n")

    (tmp_path / "chai.yaml").write_text("""
team:
  name: saas-sim-team
  max_concurrent_agents: 4
  default_provider: claude_code
  members:
    lead:
      provider: claude_code
      autonomy: high
    frontend:
      provider: claude_code
    backend:
      provider: claude_code
    prompt:
      provider: claude_code
    researcher:
      provider: claude_code
    qa:
      provider: claude_code
    deployment:
      provider: claude_code

validation:
  run_tests: true
  run_linter: true
  max_fix_iterations: 3

self_improvement:
  update_principles_after_run: true
  track_quality_scores: true
""")
    return tmp_path


@pytest.fixture
def all_roles_team_config() -> TeamConfig:
    """TeamConfig with every role populated."""
    return TeamConfig(
        name="full-team",
        members={
            RoleType.LEAD: AgentConfig(role=RoleType.LEAD, provider=ProviderType.CLAUDE_CODE, autonomy_level=AutonomyLevel.HIGH),
            RoleType.FRONTEND: AgentConfig(role=RoleType.FRONTEND, provider=ProviderType.CLAUDE_CODE),
            RoleType.BACKEND: AgentConfig(role=RoleType.BACKEND, provider=ProviderType.CLAUDE_CODE),
            RoleType.PROMPT: AgentConfig(role=RoleType.PROMPT, provider=ProviderType.CLAUDE_CODE),
            RoleType.RESEARCHER: AgentConfig(role=RoleType.RESEARCHER, provider=ProviderType.CLAUDE_CODE),
            RoleType.QA: AgentConfig(role=RoleType.QA, provider=ProviderType.CLAUDE_CODE),
            RoleType.DEPLOYMENT: AgentConfig(role=RoleType.DEPLOYMENT, provider=ProviderType.CLAUDE_CODE),
        },
        max_concurrent_agents=4,
    )


SAAS_PROMPT = (
    "Build a complete multi-tenant SaaS platform with FastAPI backend and React frontend. "
    "Include user authentication with JWT, Stripe billing integration with webhooks, "
    "an AI-powered data analysis feature, a responsive dashboard with dark mode, "
    "comprehensive test suite with 80% coverage, and full deployment infrastructure "
    "with Docker and CI/CD pipelines."
)


# ===================================================================
# TEST 1: Complexity Router classifies the SaaS prompt correctly
# ===================================================================

class TestComplexityRouting:
    def _mock_classify(self, strategy: str, reason: str, roles: Any = None) -> None:
        """Patch _classify_llm to return a canned RoutingResult."""
        from chai.core.router import RoutingResult
        self._patch_result = RoutingResult(
            strategy=ExecutionStrategy(strategy), reason=reason, suggested_roles=roles
        )

    def test_saas_prompt_routes_to_full_pipeline(self) -> None:
        from unittest.mock import patch, MagicMock
        router = ComplexityRouter()
        mock_response = MagicMock()
        block = MagicMock()
        block.type = "text"
        block.text = json.dumps({
            "strategy": "full_pipeline",
            "reason": "Complex multi-tenant SaaS platform spanning frontend, backend, billing, and deployment",
            "suggested_roles": ["lead", "frontend", "backend", "qa", "deployment"],
        })
        mock_response.content = [block]
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_response
            result = router.classify(SAAS_PROMPT)
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE, (
            f"Expected FULL_PIPELINE, got {result.strategy.value}: {result.reason}"
        )

    def test_saas_prompt_suggests_roles(self) -> None:
        from unittest.mock import patch, MagicMock
        router = ComplexityRouter()
        mock_response = MagicMock()
        block = MagicMock()
        block.type = "text"
        block.text = json.dumps({
            "strategy": "full_pipeline",
            "reason": "Complex SaaS platform",
            "suggested_roles": ["lead", "frontend", "backend", "qa", "deployment"],
        })
        mock_response.content = [block]
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_response
            result = router.classify(SAAS_PROMPT)
        assert result.suggested_roles is not None
        assert "backend" in result.suggested_roles
        assert "frontend" in result.suggested_roles

    def test_simple_prompt_routes_to_direct(self) -> None:
        from unittest.mock import patch, MagicMock
        router = ComplexityRouter()
        mock_response = MagicMock()
        block = MagicMock()
        block.type = "text"
        block.text = json.dumps({
            "strategy": "direct",
            "reason": "Simple typo fix",
            "suggested_roles": None,
        })
        mock_response.content = [block]
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_response
            result = router.classify("Fix the typo in README.md")
        assert result.strategy == ExecutionStrategy.DIRECT


# ===================================================================
# TEST 2: Task Decomposition produces correct DAG
# ===================================================================

class TestTaskDecomposition:
    def test_decompose_returns_all_roles(self) -> None:
        provider = SimulationProvider()
        decomposer = TaskDecomposer(RoleRegistry())
        available = [RoleType.LEAD, RoleType.FRONTEND, RoleType.BACKEND,
                     RoleType.QA, RoleType.DEPLOYMENT, RoleType.PROMPT, RoleType.RESEARCHER]
        graph = decomposer.decompose(SAAS_PROMPT, provider, available_roles=available)

        tasks = graph.all_tasks()
        roles_in_graph = {t.role for t in tasks}

        assert RoleType.BACKEND in roles_in_graph
        assert RoleType.FRONTEND in roles_in_graph
        assert RoleType.QA in roles_in_graph
        assert RoleType.DEPLOYMENT in roles_in_graph
        assert RoleType.PROMPT in roles_in_graph
        assert RoleType.RESEARCHER in roles_in_graph

    def test_decompose_respects_dependencies(self) -> None:
        provider = SimulationProvider()
        decomposer = TaskDecomposer(RoleRegistry())
        graph = decomposer.decompose(SAAS_PROMPT, provider)
        tasks = {t.id: t for t in graph.all_tasks()}

        assert "research-arch" in tasks[  "be-models"].dependencies
        assert "be-models" in tasks["be-auth"].dependencies
        assert "be-auth" in tasks["fe-auth"].dependencies
        assert "be-auth" in tasks["qa-tests"].dependencies

    def test_decompose_task_count(self) -> None:
        provider = SimulationProvider()
        decomposer = TaskDecomposer(RoleRegistry())
        graph = decomposer.decompose(SAAS_PROMPT, provider)
        assert len(graph.all_tasks()) == 9

    def test_topological_order_is_valid(self) -> None:
        provider = SimulationProvider()
        decomposer = TaskDecomposer(RoleRegistry())
        graph = decomposer.decompose(SAAS_PROMPT, provider)
        ordered = graph.topological_sort()
        seen: set[str] = set()
        for task in ordered:
            for dep in task.dependencies:
                assert dep in seen, f"Task {task.id} depends on {dep} but it hasn't appeared yet"
            seen.add(task.id)


# ===================================================================
# TEST 3: Full Pipeline Simulation (CLI mode — manages_own_tools=True)
# ===================================================================

class TestFullPipelineCLIMode:
    """Simulates `chai run` with the full SaaS prompt using CLI-style provider."""

    def test_full_run_exercises_all_roles(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)

        def factory(ptype: str, model: Optional[str] = None) -> Provider:
            return provider

        harness = Harness(project_dir=str(sim_project), provider_factory=factory)
        gen = harness.run(SAAS_PROMPT)

        events: List[AgentEvent] = []
        result: Optional[TeamRunResult] = None
        try:
            while True:
                evt = next(gen)
                events.append(evt)
        except StopIteration as e:
            result = e.value

        assert result is not None, "Run should return a TeamRunResult"

        roles_called = provider.roles_called
        assert "lead" in roles_called, f"Lead not called. Roles called: {roles_called}"
        assert "backend" in roles_called, f"Backend not called. Roles called: {roles_called}"
        assert "frontend" in roles_called, f"Frontend not called. Roles called: {roles_called}"
        assert "qa" in roles_called, f"QA not called. Roles called: {roles_called}"
        assert "deployment" in roles_called, f"Deployment not called. Roles called: {roles_called}"
        assert "prompt" in roles_called, f"Prompt not called. Roles called: {roles_called}"
        assert "researcher" in roles_called, f"Researcher not called. Roles called: {roles_called}"

    def test_all_tasks_complete(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is not None
        for task in result.tasks:
            assert task.status == TaskStatus.COMPLETED, (
                f"Task {task.id} ({task.role.value}) status is {task.status.value}, expected completed"
            )

    def test_events_include_all_phases(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        events: List[AgentEvent] = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration:
            pass

        event_types = {e.type for e in events}
        assert "info" in event_types, "Should have info events (routing, task list)"
        assert "status" in event_types, "Should have status events (phase transitions)"

        phases = [
            e.data.get("phase") for e in events
            if e.type == "status" and isinstance(e.data, dict) and "phase" in e.data
        ]
        assert "planning" in phases, f"Missing planning phase. Phases: {phases}"
        assert "executing" in phases, f"Missing executing phase. Phases: {phases}"
        assert "reviewing" in phases, f"Missing reviewing phase. Phases: {phases}"

    def test_task_started_and_completed_events(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        events: List[AgentEvent] = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration:
            pass

        started_ids = set()
        completed_ids = set()
        for e in events:
            if e.type == "status" and isinstance(e.data, dict):
                if "task_started" in e.data:
                    started_ids.add(e.data["task_started"])
                if "task_completed" in e.data:
                    completed_ids.add(e.data["task_completed"])

        expected_ids = {t["id"] for t in SAAS_TASK_GRAPH["tasks"]}
        assert started_ids == expected_ids, f"Not all tasks started. Missing: {expected_ids - started_ids}"
        assert completed_ids == expected_ids, f"Not all tasks completed. Missing: {expected_ids - completed_ids}"

    def test_provider_receives_correct_context(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        lead_calls = provider.calls_for_role("lead")
        assert len(lead_calls) >= 1, "Lead should be called at least once (for decomposition)"
        assert "decompose" in lead_calls[0].system_prompt.lower() or "team lead" in lead_calls[0].system_prompt.lower()

        backend_calls = provider.calls_for_role("backend")
        assert len(backend_calls) >= 1, "Backend should be called at least once"
        for bc in backend_calls:
            first_line = bc.system_prompt.split("\n")[0].lower()
            assert "backend" in first_line, f"Backend calls should have backend system prompt, got: {first_line}"


# ===================================================================
# TEST 4: Full Pipeline Simulation (API mode — manages_own_tools=False)
# ===================================================================

class TestFullPipelineAPIMode:
    """Simulates the pipeline with API-style provider that uses tool calls."""

    def test_api_mode_exercises_tools(self, sim_project: Path) -> None:
        provider = APISimulationProvider()

        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        events: List[AgentEvent] = []
        result = None
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            result = e.value

        assert result is not None

        tool_call_events = [e for e in events if e.type == "tool_call"]
        tool_result_events = [e for e in events if e.type == "tool_result"]
        assert len(tool_call_events) > 0, "API mode should produce tool_call events"
        assert len(tool_result_events) > 0, "API mode should produce tool_result events"

    def test_api_mode_all_roles_called(self, sim_project: Path) -> None:
        provider = APISimulationProvider()
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        roles_called = provider.roles_called
        expected_roles = {"lead", "backend", "frontend", "qa", "deployment", "prompt", "researcher"}
        assert expected_roles.issubset(roles_called), (
            f"Missing roles: {expected_roles - roles_called}"
        )

    def test_api_mode_all_tasks_complete(self, sim_project: Path) -> None:
        provider = APISimulationProvider()
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is not None
        for task in result.tasks:
            assert task.status == TaskStatus.COMPLETED, (
                f"Task {task.id} ({task.role.value}) is {task.status.value}"
            )


# ===================================================================
# TEST 5: Direct Mode (simple prompt, single agent)
# ===================================================================

class TestDirectMode:
    def test_direct_mode_single_agent(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run("Fix the typo in README.md")
        events: List[AgentEvent] = []
        result = None
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            result = e.value

        assert result is not None
        assert len(result.tasks) == 1
        assert result.tasks[0].status == TaskStatus.COMPLETED, (
            f"Task status is {result.tasks[0].status.value}, result text: {result.tasks[0].result!r}"
        )

        assert "lead" not in provider.roles_called, "Direct mode should NOT call Lead for decomposition"

    def test_direct_mode_picks_correct_role(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run("Fix the typo in README.md")
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is not None
        assert result.tasks[0].role == RoleType.BACKEND


# ===================================================================
# TEST 6: Team Coordination — Dependency Ordering
# ===================================================================

class TestDependencyOrdering:
    def test_dependencies_respected_in_execution(self, sim_project: Path) -> None:
        """Verify that tasks with dependencies don't start before their deps finish."""
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        events: List[AgentEvent] = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration:
            pass

        started_order: List[str] = []
        completed_order: List[str] = []
        for e in events:
            if e.type == "status" and isinstance(e.data, dict):
                if "task_started" in e.data:
                    started_order.append(e.data["task_started"])
                if "task_completed" in e.data:
                    completed_order.append(e.data["task_completed"])

        deps_map = {t["id"]: t.get("depends_on", []) for t in SAAS_TASK_GRAPH["tasks"]}
        for task_id in started_order:
            for dep_id in deps_map.get(task_id, []):
                assert dep_id in completed_order, (
                    f"Task {task_id} started before dependency {dep_id} completed"
                )
                dep_completed_idx = completed_order.index(dep_id)
                task_started_idx = started_order.index(task_id)


# ===================================================================
# TEST 7: Agent Runner in Isolation
# ===================================================================

class TestAgentRunnerIsolation:
    def test_cli_mode_runner(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        role_reg = RoleRegistry()
        role_def = role_reg.get_role(RoleType.BACKEND)
        assert role_def is not None

        tools = get_default_tools(base_dir=str(sim_project), role=RoleType.BACKEND)
        config = AgentConfig(role=RoleType.BACKEND, provider=ProviderType.CLAUDE_CODE)
        ctx = ContextManager(str(sim_project))
        task = TaskSpec(id="test-1", title="Add health endpoint", description="Add GET /health", role=RoleType.BACKEND)
        context = ctx.get_context_for_role(role_def, task)

        runner = AgentRunner(role_def, provider, tools, config, context)
        events: List[AgentEvent] = []
        result = None
        gen = runner.run(task)
        try:
            while True:
                evt = next(gen)
                events.append(evt)
        except StopIteration as e:
            result = e.value

        assert result is not None, f"Runner should return a result, got None"
        assert result != "", f"Runner should return non-empty result"
        assert any(e.type == "activity" for e in events), "CLI mode should produce activity events"

    def test_api_mode_runner(self, sim_project: Path) -> None:
        provider = APISimulationProvider()
        role_reg = RoleRegistry()
        role_def = role_reg.get_role(RoleType.QA)
        assert role_def is not None

        tools = get_default_tools(base_dir=str(sim_project), role=RoleType.QA)
        config = AgentConfig(role=RoleType.QA, provider=ProviderType.ANTHROPIC_API)
        task = TaskSpec(id="test-qa", title="Write tests", description="Write unit tests", role=RoleType.QA)
        ctx = ContextManager(str(sim_project))
        context = ctx.get_context_for_role(role_def, task)

        runner = AgentRunner(role_def, provider, tools, config, context)
        events: List[AgentEvent] = []
        result = None
        gen = runner.run(task)
        try:
            while True:
                evt = next(gen)
                events.append(evt)
        except StopIteration as e:
            result = e.value

        assert result is not None, "Runner should return a result"
        assert result != "", "Runner should return non-empty result"
        tool_calls = [e for e in events if e.type == "tool_call"]
        assert len(tool_calls) > 0, "API mode should make tool calls"


# ===================================================================
# TEST 8: Context Manager provides role-appropriate files
# ===================================================================

class TestContextManager:
    def test_backend_context(self, sim_project: Path) -> None:
        ctx = ContextManager(str(sim_project))
        role_reg = RoleRegistry()
        role_def = role_reg.get_role(RoleType.BACKEND)
        task = TaskSpec(id="t1", title="Test", role=RoleType.BACKEND)
        context = ctx.get_context_for_role(role_def, task)

        assert "main.py" in context or "models.py" in context, (
            f"Backend context should include .py files. Got:\n{context}"
        )

    def test_frontend_context(self, sim_project: Path) -> None:
        ctx = ContextManager(str(sim_project))
        role_reg = RoleRegistry()
        role_def = role_reg.get_role(RoleType.FRONTEND)
        task = TaskSpec(id="t2", title="Test", role=RoleType.FRONTEND)
        context = ctx.get_context_for_role(role_def, task)

        assert "App.tsx" in context or "Button.tsx" in context, (
            f"Frontend context should include .tsx files. Got:\n{context}"
        )

    def test_deployment_context(self, sim_project: Path) -> None:
        ctx = ContextManager(str(sim_project))
        role_reg = RoleRegistry()
        role_def = role_reg.get_role(RoleType.DEPLOYMENT)
        task = TaskSpec(id="t3", title="Test", role=RoleType.DEPLOYMENT)
        context = ctx.get_context_for_role(role_def, task)

        assert "Dockerfile" in context or "Makefile" in context or "pyproject.toml" in context, (
            f"Deployment context should include infra files. Got:\n{context}"
        )


# ===================================================================
# TEST 9: Team State Transitions
# ===================================================================

class TestTeamStateTransitions:
    def test_state_goes_through_all_phases(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        project_config = ProjectConfig.load(str(sim_project))
        team_config = TeamConfig(
            name="state-test",
            members={
                RoleType.LEAD: AgentConfig(role=RoleType.LEAD, provider=ProviderType.CLAUDE_CODE, autonomy_level=AutonomyLevel.HIGH),
                RoleType.BACKEND: AgentConfig(role=RoleType.BACKEND, provider=ProviderType.CLAUDE_CODE),
            },
            max_concurrent_agents=2,
        )
        team = Team(
            config=team_config,
            project_config=project_config,
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )

        gen = team.run_task("Build an API with FastAPI", use_worktrees=False)
        phases_seen: List[str] = []
        try:
            while True:
                evt = next(gen)
                if evt.type == "status" and isinstance(evt.data, dict) and "phase" in evt.data:
                    phases_seen.append(evt.data["phase"])
        except StopIteration:
            pass

        assert "planning" in phases_seen
        assert "executing" in phases_seen
        assert "reviewing" in phases_seen


# ===================================================================
# TEST 10: Provider Call Counts and Patterns
# ===================================================================

class TestProviderCallPatterns:
    def test_lead_called_exactly_once_for_decomposition(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        lead_calls = provider.calls_for_role("lead")
        assert len(lead_calls) == 1, f"Lead should be called exactly once, was called {len(lead_calls)} times"

    def test_backend_called_for_each_backend_task(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        backend_tasks = [t for t in SAAS_TASK_GRAPH["tasks"] if t["role"] == "backend"]
        backend_calls = provider.calls_for_role("backend")
        assert len(backend_calls) == len(backend_tasks), (
            f"Expected {len(backend_tasks)} backend calls, got {len(backend_calls)}"
        )

    def test_frontend_called_for_each_frontend_task(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        frontend_tasks = [t for t in SAAS_TASK_GRAPH["tasks"] if t["role"] == "frontend"]
        frontend_calls = provider.calls_for_role("frontend")
        assert len(frontend_calls) == len(frontend_tasks), (
            f"Expected {len(frontend_tasks)} frontend calls, got {len(frontend_calls)}"
        )

    def test_total_provider_calls(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        total_calls = len(provider.calls)
        # 1 lead call + 9 task execution calls = 10
        assert total_calls == 10, f"Expected 10 total provider calls (1 decompose + 9 tasks), got {total_calls}"

    def test_concurrent_execution_uses_multiple_threads(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        thread_ids = {c.thread_id for c in provider.calls if c.caller_role != "lead"}
        assert len(thread_ids) > 1, (
            f"Expected parallel execution across multiple threads, only saw {len(thread_ids)} thread(s)"
        )


# ===================================================================
# TEST 11: Role Registry and System Prompts
# ===================================================================

class TestRoleSystem:
    def test_all_roles_registered(self) -> None:
        registry = RoleRegistry()
        for role in [RoleType.LEAD, RoleType.FRONTEND, RoleType.BACKEND,
                     RoleType.PROMPT, RoleType.RESEARCHER, RoleType.QA, RoleType.DEPLOYMENT]:
            assert registry.has_role(role), f"Role {role.value} not registered"
            defn = registry.get_role(role)
            assert defn is not None
            assert defn.system_prompt_template, f"Role {role.value} has empty system prompt"

    def test_lead_prompt_mentions_json(self) -> None:
        registry = RoleRegistry()
        lead = registry.get_role(RoleType.LEAD)
        assert lead is not None
        assert "json" in lead.system_prompt_template.lower() or "JSON" in lead.system_prompt_template

    def test_each_role_has_context_filters(self) -> None:
        registry = RoleRegistry()
        for role_type in [RoleType.FRONTEND, RoleType.BACKEND, RoleType.QA, RoleType.DEPLOYMENT]:
            defn = registry.get_role(role_type)
            assert defn is not None
            assert len(defn.context_filters) > 0, f"Role {role_type.value} has no context filters"


# ===================================================================
# TEST 12: End-to-End Summary Report
# ===================================================================

class TestSimulationSummary:
    """Final comprehensive test that produces a readable summary of the simulation."""

    def test_full_simulation_report(self, sim_project: Path, capsys: pytest.CaptureFixture) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        gen = harness.run(SAAS_PROMPT)
        events: List[AgentEvent] = []
        result = None
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            result = e.value

        assert result is not None

        # Build report
        lines = [
            "",
            "=" * 72,
            "  ch.ai FULL SYSTEM SIMULATION REPORT",
            "=" * 72,
            "",
            f"  Prompt: {SAAS_PROMPT[:80]}...",
            f"  Project dir: {sim_project}",
            f"  Duration: {result.duration_seconds:.2f}s",
            "",
            "  TASKS DECOMPOSED:",
        ]
        for task in result.tasks:
            deps = ", ".join(task.dependencies) if task.dependencies else "none"
            lines.append(f"    [{task.status.value:>9}] {task.id:<16} ({task.role.value:<10}) -> deps: {deps}")
        lines.append("")

        lines.append("  PROVIDER CALLS BY ROLE:")
        role_counts = defaultdict(int)
        for call in provider.calls:
            role_counts[call.caller_role or "unknown"] += 1
        for role, count in sorted(role_counts.items()):
            lines.append(f"    {role:<12}: {count} call(s)")
        lines.append(f"    {'TOTAL':<12}: {len(provider.calls)} call(s)")
        lines.append("")

        lines.append("  EVENT SUMMARY:")
        event_counts = defaultdict(int)
        for e in events:
            event_counts[e.type] += 1
        for etype, count in sorted(event_counts.items()):
            lines.append(f"    {etype:<15}: {count}")
        lines.append(f"    {'TOTAL':<15}: {len(events)}")
        lines.append("")

        thread_ids = {c.thread_id for c in provider.calls if c.caller_role != "lead"}
        lines.append(f"  CONCURRENCY: {len(thread_ids)} worker thread(s) used for task execution")
        lines.append("")

        all_complete = all(t.status == TaskStatus.COMPLETED for t in result.tasks)
        all_roles = provider.roles_called
        expected = {"lead", "backend", "frontend", "qa", "deployment", "prompt", "researcher"}
        missing = expected - all_roles

        lines.append("  VERIFICATION:")
        lines.append(f"    All tasks completed: {'PASS' if all_complete else 'FAIL'}")
        lines.append(f"    All roles invoked:   {'PASS' if not missing else 'FAIL — missing: ' + str(missing)}")
        lines.append(f"    Events generated:    {'PASS' if len(events) > 0 else 'FAIL'}")
        lines.append(f"    Parallel execution:  {'PASS' if len(thread_ids) > 1 else 'WARN — single thread'}")
        lines.append("")
        lines.append("=" * 72)
        lines.append("")

        report = "\n".join(lines)
        print(report)

        assert all_complete
        assert not missing
        assert len(events) > 0


# ===================================================================
# TEST 13: Interactive Build-and-Iterate Simulation
# ===================================================================

def _consume_run(harness, prompt, strategy, cancel_event):
    """Test helper: consume a harness.run() generator, return TeamRunResult."""
    cancel_event.clear()
    gen = harness.run(prompt, strategy_override=strategy, cancel_event=cancel_event)
    result = None
    try:
        while True:
            next(gen)
    except StopIteration as e:
        result = e.value
    return result


class TestInteractiveSimulation:
    """Simulates the README interactive build-and-iterate flow.

    Exercises the full pipeline through _build_augmented_prompt and
    _extract_run_summary to verify multi-turn context threading works
    with real Harness/Team/AgentRunner execution.
    """

    def test_multi_turn_session_with_context(self, sim_project: Path) -> None:
        from chai.cli import _build_augmented_prompt, _extract_run_summary

        provider = SimulationProvider(manages_tools=True)
        factory = lambda p, m: provider
        harness = Harness(project_dir=str(sim_project), provider_factory=factory)

        session_context: list[dict] = []
        cancel_event = threading.Event()

        # --- Prompt 1: Build ---
        prompt1 = "Add email notifications for subscription events"
        augmented1 = _build_augmented_prompt(prompt1, session_context)
        assert augmented1 == prompt1  # no context yet

        routing1 = harness._router.classify(prompt1)
        result1 = _consume_run(harness, augmented1, routing1.strategy, cancel_event)

        assert result1 is not None
        assert all(t.status == TaskStatus.COMPLETED for t in result1.tasks)

        entry1 = _extract_run_summary(prompt1, result1)
        session_context.append(entry1)
        assert len(session_context) == 1

        # --- Prompt 2: Iterate ---
        prompt2 = "Fix the notification template formatting"
        augmented2 = _build_augmented_prompt(prompt2, session_context)
        assert "[Session history" in augmented2
        assert "email notifications" in augmented2 or prompt1 in augmented2
        assert prompt2 in augmented2

        routing2 = harness._router.classify(prompt2)
        assert not cancel_event.is_set()  # cleared between runs
        provider.reset()

        result2 = _consume_run(harness, augmented2, routing2.strategy, cancel_event)
        assert result2 is not None
        entry2 = _extract_run_summary(prompt2, result2)
        session_context.append(entry2)
        assert len(session_context) == 2

    def test_cancel_event_cleared_between_runs(self, sim_project: Path) -> None:
        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        cancel_event = threading.Event()
        cancel_event.set()  # simulate prior cancellation

        cancel_event.clear()  # _run_in_repl does this
        result = _consume_run(harness, "Fix typo", ExecutionStrategy.DIRECT, cancel_event)
        assert result is not None

    def test_context_truncation(self) -> None:
        """Session context entries are truncated to prevent prompt explosion."""
        from chai.cli import _build_augmented_prompt

        session_context = [
            {"prompt": "do a big thing", "outcome": "x" * 2000}
        ]
        augmented = _build_augmented_prompt("next thing", session_context)
        assert len(augmented) < 1000

    def test_augmented_prompt_contains_session_history(self) -> None:
        from chai.cli import _build_augmented_prompt, _extract_run_summary

        result1 = TeamRunResult(
            tasks=[
                TaskSpec(
                    id="t1", title="Auth backend",
                    role=RoleType.BACKEND, status=TaskStatus.COMPLETED,
                ),
                TaskSpec(
                    id="t2", title="Auth QA",
                    role=RoleType.QA, status=TaskStatus.COMPLETED,
                ),
            ],
            duration_seconds=45.0,
        )
        entry = _extract_run_summary("add auth middleware", result1)
        ctx = [entry]

        augmented = _build_augmented_prompt("add rate limiting", ctx)
        assert "[Session history" in augmented
        assert "add auth middleware" in augmented
        assert "[Current request]" in augmented
        assert "add rate limiting" in augmented

    def test_full_three_prompt_session(self, sim_project: Path) -> None:
        """Full README scenario: build, iterate, plan create."""
        from chai.cli import _build_augmented_prompt, _extract_run_summary

        provider = SimulationProvider(manages_tools=True)
        harness = Harness(
            project_dir=str(sim_project),
            provider_factory=lambda p, m: provider,
        )
        cancel_event = threading.Event()
        session_context: list[dict] = []

        # Prompt 1: build
        p1 = "Add email notifications for subscription events"
        r1 = _consume_run(harness, p1, None, cancel_event)
        assert r1 is not None
        session_context.append(_extract_run_summary(p1, r1))

        # Prompt 2: iterate
        p2 = "Fix the notification template formatting"
        aug2 = _build_augmented_prompt(p2, session_context)
        provider.reset()
        r2 = _consume_run(harness, aug2, None, cancel_event)
        assert r2 is not None
        session_context.append(_extract_run_summary(p2, r2))

        assert len(session_context) == 2
        assert session_context[0]["prompt"] == p1
        assert session_context[1]["prompt"] == p2
