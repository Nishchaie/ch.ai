"""Shared run state persisted in ~/.chai/state.json.

Both the CLI and the API server read/write this file so that run results
(tasks, project directory, events) are visible regardless of which process
produced them or which directory it was started from.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import CONFIG_DIR

STATE_FILE = CONFIG_DIR / "state.json"


def _read_raw() -> Dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_raw(data: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# -- Public API ---------------------------------------------------------------

def save_run(
    *,
    project_dir: str,
    tasks: List[Dict[str, Any]],
    prompt: str = "",
    events_count: int = 0,
) -> None:
    """Persist the result of a run."""
    state = _read_raw()
    state["last_run"] = {
        "project_dir": project_dir,
        "tasks": tasks,
        "prompt": prompt,
        "events_count": events_count,
        "timestamp": time.time(),
    }
    _write_raw(state)


def get_last_run() -> Optional[Dict[str, Any]]:
    """Return the most recent run, or None."""
    return _read_raw().get("last_run")


def get_tasks() -> List[Dict[str, Any]]:
    """Return tasks from the most recent run."""
    run = get_last_run()
    if run:
        return run.get("tasks", [])
    return []


def get_project_dir() -> Optional[str]:
    """Return the project directory from the most recent run."""
    run = get_last_run()
    if run:
        return run.get("project_dir")
    return None


def save_tasks_initial(
    *,
    project_dir: str,
    tasks: List[Dict[str, Any]],
    prompt: str = "",
) -> None:
    """Persist an initial set of tasks at the start of a run (all pending)."""
    state = _read_raw()
    state["last_run"] = {
        "project_dir": project_dir,
        "tasks": tasks,
        "prompt": prompt,
        "events_count": 0,
        "timestamp": time.time(),
    }
    _write_raw(state)


def update_task_status(task_id: str, status: str) -> None:
    """Update a single task's status in the persisted state."""
    state = _read_raw()
    run = state.get("last_run")
    if not run:
        return
    for task in run.get("tasks", []):
        if task.get("id") == task_id:
            task["status"] = status
            break
    _write_raw(state)


def tasks_from_result(result: Any) -> List[Dict[str, Any]]:
    """Extract a serialisable task list from a TeamRunResult."""
    if not result or not hasattr(result, "tasks") or not result.tasks:
        return []
    return [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description or "",
            "role": t.role.value if hasattr(t.role, "value") else str(t.role),
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "dependencies": list(t.dependencies) if t.dependencies else [],
        }
        for t in result.tasks
    ]
