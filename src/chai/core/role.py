"""Role definitions and registry for ch.ai agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from ..types import AutonomyLevel, RoleType
from ..tools.base import ROLE_TOOL_ACCESS


@dataclass
class RoleDefinition:
    """Definition of an agent role with prompts and capabilities."""

    role_type: RoleType
    name: str
    description: str
    system_prompt_template: str
    allowed_tools: Optional[Set[str]] = None
    default_autonomy: AutonomyLevel = AutonomyLevel.MEDIUM
    context_filters: List[str] = field(default_factory=list)


def _lead_system_prompt() -> str:
    return """You are the Team Lead for an AI engineering team. Your job is to decompose high-level user requests into a structured task graph (DAG) that can be executed by specialized agents.

When given a task, analyze it and output a JSON object with this exact structure:
{"tasks": [{"id": "<unique_id>", "role": "<role>", "title": "<title>", "description": "<description>", "depends_on": ["<task_id>", ...], "acceptance_criteria": ["<criterion>", ...]}]}

Roles: lead, frontend, backend, prompt, researcher, qa, deployment.
- Use depends_on to express dependencies (e.g. qa depends on backend).
- Each task id must be unique (e.g. be-api, fe-ui, qa-e2e).
- ALWAYS include a final task (id: "docs-readme") assigned to the "deployment" role that creates \
or updates README.md at the project root. The README must cover: project overview, prerequisites, \
installation/setup steps, how to run the project, environment variables, and any relevant configuration. \
This task should depend on all other implementation tasks so it can accurately document the final state.
- Output ONLY valid JSON, no markdown or extra text."""


def _frontend_prompt(stack: str = "React, TypeScript") -> str:
    return f"""You are the Frontend specialist. You implement UI, components, styling, and client-side logic.

Task: {{task}}

Focus on: {stack}, accessibility, responsive design, component structure. Use the provided context files to understand the codebase."""


def _backend_prompt(stack: str = "Python, FastAPI") -> str:
    return f"""You are the Backend specialist. You implement APIs, data models, business logic, and server-side services.

Task: {{task}}

Focus on: {stack}, database patterns, API design, error handling. Use the provided context files to understand the codebase."""


def _prompt_prompt() -> str:
    return """You are the Prompt/LLM specialist. You design and refine prompts, system instructions, and LLM integration logic.

Task: {task}

Focus on: prompt engineering, few-shot examples, output formatting, safety constraints. Use the provided context files."""


def _researcher_prompt() -> str:
    return """You are the Researcher. You search for information, evaluate options, and synthesize findings for the team.

Task: {task}

Focus on: web search, documentation review, comparative analysis, summarization. You have read-only and search tools."""


def _qa_prompt(stack: str = "pytest") -> str:
    return f"""You are the QA specialist. You write tests, run validation, and ensure quality standards are met.

Task: {{task}}

Focus on: {stack}, unit tests, integration tests, linting, acceptance criteria validation. Use the provided context files."""


def _deployment_prompt(stack: str = "Python venv + npm dev") -> str:
    return f"""You are the Deployment specialist. You handle build, release, infrastructure, and CI/CD.

Task: {{task}}

Focus on: {stack}, scripts, environment config, deployment pipelines. Use the provided context files."""


class RoleRegistry:
    """Registry of role definitions with lookup and registration."""

    def __init__(self, stack: Optional["StackConfig"] = None) -> None:
        self._roles: Dict[RoleType, RoleDefinition] = {}
        self._register_defaults(stack)

    def _register_defaults(self, stack: Optional["StackConfig"] = None) -> None:
        """Pre-register all 7 default roles."""
        from ..config import StackConfig

        s = stack or StackConfig()
        defaults = [
            RoleDefinition(
                role_type=RoleType.LEAD,
                name="Team Lead",
                description="Decomposes tasks into a DAG and coordinates the team",
                system_prompt_template=_lead_system_prompt(),
                allowed_tools=ROLE_TOOL_ACCESS.get(RoleType.LEAD),
                default_autonomy=AutonomyLevel.HIGH,
                context_filters=["**/*.md", "**/AGENTS.md", "**/ARCHITECTURE.md", "**/docs/**"],
            ),
            RoleDefinition(
                role_type=RoleType.FRONTEND,
                name="Frontend",
                description="Implements UI, components, and client-side logic",
                system_prompt_template=_frontend_prompt(s.frontend),
                allowed_tools=ROLE_TOOL_ACCESS.get(RoleType.FRONTEND),
                default_autonomy=AutonomyLevel.MEDIUM,
                context_filters=["**/*.tsx", "**/*.ts", "**/*.jsx", "**/*.js", "**/frontend/**", "**/components/**"],
            ),
            RoleDefinition(
                role_type=RoleType.BACKEND,
                name="Backend",
                description="Implements APIs, data models, and server-side logic",
                system_prompt_template=_backend_prompt(s.backend),
                allowed_tools=ROLE_TOOL_ACCESS.get(RoleType.BACKEND),
                default_autonomy=AutonomyLevel.MEDIUM,
                context_filters=["**/*.py", "**/api*.py", "**/models/**", "**/src/**"],
            ),
            RoleDefinition(
                role_type=RoleType.PROMPT,
                name="Prompt Engineer",
                description="Designs prompts and LLM integration",
                system_prompt_template=_prompt_prompt(),
                allowed_tools=ROLE_TOOL_ACCESS.get(RoleType.PROMPT),
                default_autonomy=AutonomyLevel.MEDIUM,
                context_filters=["**/*prompt*", "**/prompts/**", "**/templates/**"],
            ),
            RoleDefinition(
                role_type=RoleType.RESEARCHER,
                name="Researcher",
                description="Searches and synthesizes information",
                system_prompt_template=_researcher_prompt(),
                allowed_tools=ROLE_TOOL_ACCESS.get(RoleType.RESEARCHER),
                default_autonomy=AutonomyLevel.MEDIUM,
                context_filters=["**/*.md", "**/docs/**", "**/references/**"],
            ),
            RoleDefinition(
                role_type=RoleType.QA,
                name="QA",
                description="Writes tests and validates quality",
                system_prompt_template=_qa_prompt(s.qa),
                allowed_tools=ROLE_TOOL_ACCESS.get(RoleType.QA),
                default_autonomy=AutonomyLevel.MEDIUM,
                context_filters=["**/test*.py", "**/*_test.*", "**/tests/**", "**/*.py"],
            ),
            RoleDefinition(
                role_type=RoleType.DEPLOYMENT,
                name="Deployment",
                description="Handles build, release, and CI/CD",
                system_prompt_template=_deployment_prompt(s.deployment),
                allowed_tools=ROLE_TOOL_ACCESS.get(RoleType.DEPLOYMENT),
                default_autonomy=AutonomyLevel.MEDIUM,
                context_filters=["**/Dockerfile*", "**/.github/**", "**/Makefile", "**/pyproject.toml"],
            ),
        ]
        for rd in defaults:
            self._roles[rd.role_type] = rd

    def register_role(self, role: RoleDefinition) -> None:
        """Register or overwrite a role definition."""
        self._roles[role.role_type] = role

    def get_role(self, role_type: RoleType) -> Optional[RoleDefinition]:
        """Get a role definition by type."""
        return self._roles.get(role_type)

    def list_roles(self) -> List[RoleDefinition]:
        """List all registered roles."""
        return list(self._roles.values())

    def has_role(self, role_type: RoleType) -> bool:
        """Check if a role is registered."""
        return role_type in self._roles
