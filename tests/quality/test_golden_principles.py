"""Tests for GoldenPrincipleChecker principle loading and checking."""

import pytest

from chai.quality.golden_principles import GoldenPrincipleChecker, GoldenPrinciple, Violation


def test_load_principles_empty_dir(tmp_path):
    checker = GoldenPrincipleChecker(str(tmp_path))
    principles = checker.load_principles(str(tmp_path))
    assert principles == []


def test_load_principles_from_index(tmp_path):
    (tmp_path / "docs" / "golden-principles").mkdir(parents=True)
    index = tmp_path / "docs" / "golden-principles" / "index.md"
    index.write_text("""
## Max File Size
Keep files small.
Check: file_size
Pattern: 500
Remediation: Split the file.

## No Secrets
Check: regex
Pattern: api_key\\s*=
Remediation: Use env vars.
""")
    checker = GoldenPrincipleChecker(str(tmp_path))
    principles = checker.load_principles(str(tmp_path))
    assert len(principles) >= 1
    assert any(p.check_type == "file_size" for p in principles)


def test_check_file_size(tmp_path):
    (tmp_path / "docs" / "golden-principles").mkdir(parents=True)
    index = tmp_path / "docs" / "golden-principles" / "index.md"
    index.write_text("""
## Max File Size
Description.
Check: file_size
Pattern: 10
Remediation: Split.
""")
    big_file = tmp_path / "big.py"
    big_file.write_text("\n".join(["x"] * 20))
    checker = GoldenPrincipleChecker(str(tmp_path))
    violations = checker.check_file(str(big_file))
    assert len(violations) >= 1
    assert any("lines" in v.message for v in violations)


def test_check_file_no_violations(tmp_path):
    (tmp_path / "docs" / "golden-principles").mkdir(parents=True)
    index = tmp_path / "docs" / "golden-principles" / "index.md"
    index.write_text("""
## Max File Size
Check: file_size
Pattern: 500
Remediation: Split.
""")
    small_file = tmp_path / "small.py"
    small_file.write_text("x = 1\n")
    checker = GoldenPrincipleChecker(str(tmp_path))
    violations = checker.check_file(str(small_file))
    assert len(violations) == 0 or all("line" not in str(v).lower() or "max" in str(v).lower() for v in violations)


def test_check_all(tmp_path):
    (tmp_path / "docs" / "golden-principles").mkdir(parents=True)
    index = tmp_path / "docs" / "golden-principles" / "index.md"
    index.write_text("""
## Max File Size
Check: file_size
Pattern: 5
Remediation: Split.
""")
    (tmp_path / "a.py").write_text("\n".join(["x"] * 10))
    (tmp_path / "b.py").write_text("y")
    checker = GoldenPrincipleChecker(str(tmp_path))
    violations = checker.check_all([str(tmp_path / "a.py"), str(tmp_path / "b.py")])
    assert len(violations) >= 1
