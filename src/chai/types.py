"""Shared types used across all ch.ai modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class RoleType(str, Enum):
    LEAD = "lead"
    FRONTEND = "frontend"
    BACKEND = "backend"
    PROMPT = "prompt"
    RESEARCHER = "researcher"
    QA = "qa"
    DEPLOYMENT = "deployment"
    CUSTOM = "custom"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AutonomyLevel(str, Enum):
    READ_ONLY = "read_only"
    MEDIUM = "medium"
    HIGH = "high"
    FULL = "full"


class TeamState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    DONE = "done"
    FAILED = "failed"


class ProviderType(str, Enum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    ANTHROPIC_API = "anthropic_api"
    OPENAI_API = "openai_api"
    CUSTOM = "custom"


@dataclass
class AgentConfig:
    """Configuration for a single agent in a team."""

    role: RoleType
    provider: ProviderType = ProviderType.CLAUDE_CODE
    model: Optional[str] = None
    autonomy_level: AutonomyLevel = AutonomyLevel.MEDIUM
    allowed_tools: Optional[List[str]] = None
    system_prompt_override: Optional[str] = None
    max_iterations: int = 50
    context_filters: Optional[List[str]] = None


@dataclass
class TeamConfig:
    """Configuration for an engineering team."""

    name: str
    members: Dict[RoleType, AgentConfig] = field(default_factory=dict)
    max_concurrent_agents: int = 4
    default_provider: ProviderType = ProviderType.CLAUDE_CODE
    default_model: Optional[str] = None
    workspace_mode: str = "worktree"


@dataclass
class TaskSpec:
    """Specification for a single task in the task graph."""

    id: str
    title: str
    description: str = ""
    role: RoleType = RoleType.BACKEND
    dependencies: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    acceptance_criteria: List[str] = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None
    worktree_path: Optional[str] = None


@dataclass
class ValidationResult:
    """Result from the validation gate."""

    passed: bool
    tests_passed: Optional[bool] = None
    lint_passed: Optional[bool] = None
    boot_passed: Optional[bool] = None
    browser_passed: Optional[bool] = None
    review_passed: Optional[bool] = None
    errors: List[str] = field(default_factory=list)
    remediation_tasks: List[TaskSpec] = field(default_factory=list)


@dataclass
class AgentEvent:
    """Event emitted during agent execution."""

    type: str  # text, text_chunk, tool_call, tool_result, error, info, waiting, status, activity
    data: Any
    role: Optional[RoleType] = None
    task_id: Optional[str] = None


@dataclass
class TeamRunResult:
    """Result of a full team run."""

    tasks: List[TaskSpec] = field(default_factory=list)
    results: Dict[str, str] = field(default_factory=dict)
    duration_seconds: float = 0.0
    quality_score: Optional[float] = None
    validation: Optional[ValidationResult] = None
    events: List[AgentEvent] = field(default_factory=list)


ClarifyCallback = Callable[[str, str, str], str]
"""(question, default, field) -> answer. Lets the system ask the operator a question."""


def default_clarify(question: str, default: str = "", field: str = "") -> str:
    """Non-interactive fallback: always returns the default."""
    return default
