"""Execution plan manager: create, parse, update plans in docs/exec-plans/."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..types import RoleType, TaskSpec, TaskStatus


MACHINE_PLAN_HEADER = "## Machine plan"
MACHINE_PLAN_RE = re.compile(
    r"## Machine plan\s*```json\s*(\{[\s\S]*?\})\s*```",
    re.DOTALL,
)
FRONTMATTER_RE = re.compile(r"^---\s*\n([\s\S]*?)\n---\s*\n", re.DOTALL)

EXEC_PLANS_DIR = "docs/exec-plans"


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "plan"


def _exec_plans_dir(base_dir: Optional[str] = None) -> str:
    base = Path(base_dir) if base_dir else Path.cwd()
    return str(base / EXEC_PLANS_DIR)


class ExecutionPlanManager:
    """Create, parse, and update execution plans stored as markdown in docs/exec-plans/."""

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self._base_dir = base_dir or str(Path.cwd())

    def create_plan(
        self,
        title: str,
        tasks: List[TaskSpec],
        base_dir: Optional[str] = None,
    ) -> str:
        """Create a new execution plan file. Returns the path to the created file."""
        base = base_dir or self._base_dir
        plans_dir = Path(base) / EXEC_PLANS_DIR
        plans_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        slug = _slugify(title)
        path = plans_dir / f"{date_str}--{slug}.md"

        task_list = [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "role": t.role.value,
                "dependencies": t.dependencies,
                "status": t.status.value,
                "acceptance_criteria": t.acceptance_criteria,
            }
            for t in tasks
        ]
        machine_plan = {
            "version": 1,
            "title": title,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "tasks": task_list,
        }

        frontmatter = f"""---
name: {title}
overview: Execution plan for {title}
---

# {title}

{title}

"""
        content = frontmatter + f"\n{MACHINE_PLAN_HEADER}\n```json\n{json.dumps(machine_plan, indent=2)}\n```\n"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def load_plan(self, path: str) -> Tuple[Optional[Dict[str, Any]], Optional[List[TaskSpec]], Optional[str]]:
        """Load a plan from path. Returns (plan_dict, tasks_as_TaskSpec, error)."""
        p = Path(path)
        if not p.exists():
            return None, None, f"Plan file not found: {path}"
        content = p.read_text(encoding="utf-8")

        # Extract machine plan JSON
        match = MACHINE_PLAN_RE.search(content)
        if not match:
            return None, None, "No JSON block found under '## Machine plan'"
        json_str = match.group(1).strip()
        try:
            plan = json.loads(json_str)
        except json.JSONDecodeError as e:
            return None, None, f"Invalid JSON in machine plan: {e}"

        tasks: List[TaskSpec] = []
        for t in plan.get("tasks", []):
            role_str = t.get("role", "backend")
            try:
                role = RoleType(role_str)
            except ValueError:
                role = RoleType.BACKEND
            status_str = t.get("status", "pending")
            try:
                status = TaskStatus(status_str)
            except ValueError:
                status = TaskStatus.PENDING
            tasks.append(
                TaskSpec(
                    id=str(t.get("id", "")),
                    title=str(t.get("title", "")),
                    description=str(t.get("description", "")),
                    role=role,
                    dependencies=list(t.get("dependencies", [])),
                    status=status,
                    acceptance_criteria=list(t.get("acceptance_criteria", [])),
                )
            )
        return plan, tasks, None

    def update_plan_status(
        self,
        path: str,
        status_map: Dict[str, str],
    ) -> str:
        """Update task statuses in the plan file. Returns updated markdown content."""
        p = Path(path)
        if not p.exists():
            return ""
        content = p.read_text(encoding="utf-8")

        match = MACHINE_PLAN_RE.search(content)
        if not match:
            return content
        json_str = match.group(1).strip()
        try:
            plan = json.loads(json_str)
        except json.JSONDecodeError:
            return content

        for task in plan.get("tasks", []):
            tid = task.get("id")
            if tid and tid in status_map:
                task["status"] = status_map[tid]

        new_json = json.dumps(plan, indent=2)
        start, end = match.span(1)
        updated = content[:start] + new_json + content[end:]
        p.write_text(updated, encoding="utf-8")
        return updated

    def find_latest_plan(self, base_dir: Optional[str] = None) -> Optional[str]:
        """Find the most recent plan file in docs/exec-plans/."""
        base = base_dir or self._base_dir
        plans_dir = Path(base) / EXEC_PLANS_DIR
        if not plans_dir.is_dir():
            return None
        candidates = list(plans_dir.glob("*.md"))
        if not candidates:
            return None
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        return str(latest)
