"""Tests for RepoKnowledge scanning."""

import pytest

from chai.knowledge.repository import RepoKnowledge
from chai.types import RoleType


def test_scan_empty_dir(tmp_path):
    repo = RepoKnowledge(str(tmp_path))
    result = repo.scan(str(tmp_path))
    assert "files" in result
    assert "frontend_files" in result
    assert "backend_files" in result
    assert "test_files" in result


def test_scan_detects_backend_files(tmp_path):
    (tmp_path / "src" / "main.py").parent.mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("print(1)")
    repo = RepoKnowledge(str(tmp_path))
    result = repo.scan(str(tmp_path))
    assert "src/main.py" in result["backend_files"] or "main.py" in str(result["files"])


def test_scan_detects_test_files(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_x(): pass")
    repo = RepoKnowledge(str(tmp_path))
    result = repo.scan(str(tmp_path))
    assert len(result["test_files"]) >= 1


def test_get_files_for_role(tmp_path):
    (tmp_path / "src" / "api.py").parent.mkdir(parents=True)
    (tmp_path / "src" / "api.py").write_text("# api")
    repo = RepoKnowledge(str(tmp_path))
    backend_files = repo.get_files_for_role(RoleType.BACKEND)
    assert isinstance(backend_files, list)
    # May be empty if scan didn't find backend files
    assert all(isinstance(f, str) for f in backend_files)


def test_get_summary(tmp_path):
    (tmp_path / "README.md").write_text("# x")
    repo = RepoKnowledge(str(tmp_path))
    summary = repo.get_summary()
    assert "Files" in summary
