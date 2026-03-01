"""Quality score API for CLI and API server."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .quality_score import QualityScorer


def _score_to_grade(score: float) -> str:
    if score >= 0.9:
        return "A"
    if score >= 0.8:
        return "B"
    if score >= 0.7:
        return "C"
    if score >= 0.5:
        return "D"
    return "F"


def get_quality_scores(project_dir: str | None = None) -> Dict[str, Dict[str, Any]]:
    """Return quality scores per domain with score and grade. Used by CLI and API.

    Only returns scores when an explicit quality analysis has been saved
    (docs/QUALITY_SCORE.md exists). Heuristic scores are merged in to
    fill gaps but won't appear on their own.
    """
    base = project_dir or str(Path.cwd())
    scorer = QualityScorer(base)
    loaded = scorer.load_scores(base)
    if not loaded:
        return {}
    raw = scorer.score(base)
    for k, v in loaded.items():
        raw[k] = v
    return {
        domain: {"score": s, "grade": _score_to_grade(s)}
        for domain, s in raw.items()
    }
