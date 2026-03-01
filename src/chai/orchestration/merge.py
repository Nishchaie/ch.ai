"""Git operations for branches, commits, and merging."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    from git import Repo
    from git.exc import GitCommandError
    GITPYTHON_AVAILABLE = True
except ImportError:
    GITPYTHON_AVAILABLE = False


class MergeManager:
    """Git operations using gitpython."""

    def __init__(self, repo_path: Optional[str] = None) -> None:
        self._repo_path = repo_path or str(Path.cwd())
        self._repo: Optional["Repo"] = None

    @property
    def repo(self) -> "Repo":
        if not GITPYTHON_AVAILABLE:
            raise RuntimeError("gitpython is required for MergeManager")
        if self._repo is None:
            self._repo = Repo(self._repo_path)
        return self._repo

    def create_branch(self, name: str) -> str:
        """Create and checkout a new branch. Returns branch name."""
        repo = self.repo
        branch = repo.create_head(name)
        branch.checkout()
        return name

    def commit_changes(self, message: str, paths: Optional[list] = None) -> Optional[str]:
        """Stage and commit changes. Returns commit sha or None if nothing to commit."""
        repo = self.repo
        if paths:
            repo.index.add(paths)
        else:
            repo.index.add("*")
        if not repo.index.diff("HEAD"):
            return None
        commit = repo.index.commit(message)
        return commit.hexsha

    def merge_branch(self, source: str, target: str) -> bool:
        """Merge source branch into target. Checkouts target, merges source. Returns success."""
        repo = self.repo
        try:
            target_ref = repo.heads[target] if target in repo.heads else repo.create_head(target)
            target_ref.checkout()
            repo.git.merge(source)
            return True
        except GitCommandError:
            return False

    def get_diff(self, branch: Optional[str] = None) -> str:
        """Get diff between current branch and given branch (or working tree vs HEAD)."""
        repo = self.repo
        if branch:
            try:
                return repo.git.diff(branch + "..HEAD")
            except GitCommandError:
                return repo.git.diff()
        return repo.git.diff()
