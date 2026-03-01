"""Validation gate: self-testing between task completion and review."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from ..config import ValidationConfig
from ..types import TaskSpec, ValidationResult
from ..quality.golden_principles import GoldenPrincipleChecker
from ..quality.linter import AgentLinter


class ValidationGate:
    """Self-testing gate. Runs tests, golden principles, optionally boot check."""

    def __init__(self, config: Optional[ValidationConfig] = None) -> None:
        self._config = config or ValidationConfig()
        self._golden = GoldenPrincipleChecker()
        self._linter = AgentLinter()

    def validate(
        self,
        task: TaskSpec,
        worktree_path: Optional[str] = None,
        config: Optional[ValidationConfig] = None,
    ) -> ValidationResult:
        """Run validation. Returns ValidationResult with passed, errors, remediation_tasks."""
        cfg = config or self._config
        base = worktree_path or task.worktree_path or str(Path.cwd())
        errors: list[str] = []
        tests_passed: Optional[bool] = None
        lint_passed: Optional[bool] = None
        boot_passed: Optional[bool] = None
        remediation_tasks: list[TaskSpec] = []

        if cfg.run_tests:
            tests_passed, test_errors = self._run_tests(base, cfg.test_command)
            if not tests_passed:
                errors.extend(test_errors)
                remediation_tasks.append(
                    TaskSpec(
                        id=f"fix-tests-{task.id}",
                        title="Fix failing tests",
                        description="Tests failed: " + "; ".join(test_errors[:3]),
                        role=task.role,
                    )
                )

        if cfg.run_linter:
            self._golden.load_principles(base)
            changed_files = self._get_changed_or_task_files(base, task)
            violations = self._golden.check_all(changed_files)
            lint_issues = []
            for p in changed_files:
                lint_issues.extend(self._linter.lint_file(p))
            if violations or lint_issues:
                lint_passed = False
                for v in violations:
                    errors.append(f"[{v.principle_name}] {v.message}")
                for li in lint_issues[:10]:
                    errors.append(f"[{li.code}] {li.message}")
                if lint_issues:
                    remediation_tasks.append(
                        TaskSpec(
                            id=f"fix-lint-{task.id}",
                            title="Fix lint issues",
                            description="Address golden principle and lint violations",
                            role=task.role,
                        )
                    )
            else:
                lint_passed = True

        if cfg.boot_app and cfg.boot_command:
            boot_passed = self._run_boot_check(cfg)
            if not boot_passed:
                errors.append("App failed to boot or health check failed")

        passed = (
            (tests_passed is not False if cfg.run_tests else True)
            and (lint_passed is not False if cfg.run_linter else True)
            and (boot_passed is not False if cfg.boot_app else True)
        )

        return ValidationResult(
            passed=passed,
            tests_passed=tests_passed,
            lint_passed=lint_passed,
            boot_passed=boot_passed,
            errors=errors,
            remediation_tasks=remediation_tasks,
        )

    def _run_tests(self, base: str, test_cmd: Optional[str]) -> tuple[bool, list[str]]:
        """Detect test framework and run tests. Returns (passed, errors)."""
        base_path = Path(base)
        if test_cmd:
            result = subprocess.run(
                test_cmd,
                shell=True,
                cwd=base,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return False, [result.stderr or result.stdout or "Tests failed"][:500].split("\n")[:5]
            return True, []

        if (base_path / "pyproject.toml").exists():
            content = (base_path / "pyproject.toml").read_text()
            if "pytest" in content:
                result = subprocess.run(
                    ["python", "-m", "pytest", "-x", "-q"],
                    cwd=base,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    err = (result.stderr or result.stdout or "")[:500]
                    return False, err.split("\n")[:5]
                return True, []

        if (base_path / "package.json").exists():
            for cmd in ("npm test", "npm run test", "yarn test"):
                result = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=base,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    return True, []
            return False, ["Frontend tests failed or not configured"]

        return True, []

    def _get_changed_or_task_files(self, base: str, task: TaskSpec) -> list[str]:
        """Get list of files to check (changed files or project source)."""
        base_path = Path(base)
        files: set[str] = set()
        for p in base_path.rglob("*.py"):
            if "__pycache__" in str(p) or ".venv" in str(p):
                continue
            files.add(str(p))
        for p in base_path.rglob("*.ts"):
            if "node_modules" in str(p):
                continue
            files.add(str(p))
        for p in base_path.rglob("*.tsx"):
            if "node_modules" in str(p):
                continue
            files.add(str(p))
        return list(files)[:50]

    def _run_boot_check(self, cfg: ValidationConfig) -> bool:
        """Boot app and optionally check health URL."""
        if not cfg.boot_command:
            return True
        result = subprocess.run(
            cfg.boot_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False
        if cfg.health_check_url:
            try:
                import urllib.request
                with urllib.request.urlopen(cfg.health_check_url, timeout=5) as r:
                    return r.status == 200
            except Exception:
                return False
        return True
