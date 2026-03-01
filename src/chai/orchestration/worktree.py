"""Per-task git worktrees in .chai/worktrees/."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional


WORKTREES_DIR = ".chai/worktrees"


def _sanitize_task_id(task_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "-", task_id)[:32]


class WorktreeManager:
    """Creates per-task git worktrees, tears them down after completion."""

    def __init__(self, repo_path: Optional[str] = None) -> None:
        self._repo_path = repo_path or str(Path.cwd())

    def _git_root(self) -> Optional[str]:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def _worktrees_root(self) -> str:
        root = self._git_root() or self._repo_path
        return os.path.join(root, WORKTREES_DIR)

    def create_worktree(self, task_id: str) -> str:
        """Create a git worktree for the task. Returns the worktree path."""
        repo_root = self._git_root()
        if not repo_root:
            raise RuntimeError("Worktree requires a git repository")
        worktrees_root = os.path.join(repo_root, WORKTREES_DIR)
        os.makedirs(worktrees_root, exist_ok=True)
        safe_id = _sanitize_task_id(task_id)
        worktree_path = os.path.join(worktrees_root, safe_id)
        if os.path.isdir(worktree_path):
            return worktree_path
        branch_name = f"chai/{safe_id}"
        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, worktree_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or result.stdout.strip() or "git worktree add failed"
            )
        return worktree_path

    def remove_worktree(self, task_id: str) -> bool:
        """Remove the worktree for the task. Returns success."""
        worktrees_root = self._worktrees_root()
        safe_id = _sanitize_task_id(task_id)
        worktree_path = os.path.join(worktrees_root, safe_id)
        if not os.path.isdir(worktree_path):
            return True
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        branch_name = f"chai/{safe_id}"
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            capture_output=True,
            check=False,
        )
        return True

    def list_worktrees(self) -> List[str]:
        """List all ch.ai worktree paths."""
        worktrees_root = self._worktrees_root()
        if not os.path.isdir(worktrees_root):
            return []
        return [
            os.path.join(worktrees_root, name)
            for name in os.listdir(worktrees_root)
            if os.path.isdir(os.path.join(worktrees_root, name))
        ]

    def cleanup_all(self) -> int:
        """Remove all ch.ai worktrees. Returns count removed."""
        worktrees = self.list_worktrees()
        count = 0
        for path in worktrees:
            task_id = os.path.basename(path)
            if self.remove_worktree(task_id):
                count += 1
        return count
