"""Agent-to-agent review cycle (Ralph Wiggum loop)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..providers.base import Provider, ProviderResponse


class FeedbackLoop:
    """Agent produces work -> reviewer reviews -> fixes -> repeat until approved."""

    def __init__(
        self,
        max_review_rounds: int = 5,
        auto_approve_threshold: float = 0.9,
    ) -> None:
        self.max_review_rounds = max_review_rounds
        self.auto_approve_threshold = auto_approve_threshold

    def run_review_cycle(
        self,
        work_output: str,
        reviewer_prompt: str,
        provider: Provider,
        max_rounds: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Run review cycle. Returns (approved, feedback).

        Reviewer evaluates work_output. If not approved, can request fixes.
        Repeats until approved or max_rounds. Final feedback summarizes the review.
        """
        rounds = max_rounds or self.max_review_rounds
        current_work = work_output
        feedback_history: List[str] = []

        for round_num in range(rounds):
            review_prompt = self._build_review_prompt(
                work=current_work,
                reviewer_prompt=reviewer_prompt,
                round_num=round_num + 1,
                previous_feedback=feedback_history[-1] if feedback_history else None,
            )
            messages: List[Dict[str, Any]] = [
                {"role": "user", "content": review_prompt},
            ]
            raw = provider.chat(
                messages=messages,
                system="You are a thorough code reviewer. Output JSON: {\"approved\": true|false, \"feedback\": \"...\", \"changes_requested\": \"...\"}",
                tools=None,
                max_tokens=2048,
                stream=False,
            )
            response: ProviderResponse
            if hasattr(raw, "__iter__") and not isinstance(raw, (str, dict)):
                try:
                    it = iter(raw)
                    while True:
                        next(it)
                except StopIteration as e:
                    response = e.value if e.value is not None else ProviderResponse(text="")
            else:
                response = raw

            text = (response.text or "").strip()
            approved, feedback, changes = self._parse_review_response(text)

            feedback_history.append(feedback or "")

            if approved:
                return True, feedback or "Approved"
            if round_num == rounds - 1:
                return False, feedback or "Max rounds reached; not approved"

            if changes:
                fix_prompt = f"Original work:\n{current_work}\n\nReviewer requested changes:\n{changes}\n\nProvide the revised work."
                fix_messages: List[Dict[str, Any]] = [
                    {"role": "user", "content": fix_prompt},
                ]
                raw_fix = provider.chat(
                    messages=fix_messages,
                    system="You apply reviewer feedback to improve the work. Output the revised work only.",
                    tools=None,
                    max_tokens=8192,
                    stream=False,
                )
                fix_response: ProviderResponse
                if hasattr(raw_fix, "__iter__") and not isinstance(raw_fix, (str, dict)):
                    try:
                        it = iter(raw_fix)
                        while True:
                            next(it)
                    except StopIteration as e:
                        fix_response = e.value if e.value is not None else ProviderResponse(text="")
                else:
                    fix_response = raw_fix
                current_work = fix_response.text or current_work

        return False, feedback_history[-1] if feedback_history else "Max rounds reached"

    def _build_review_prompt(
        self,
        work: str,
        reviewer_prompt: str,
        round_num: int,
        previous_feedback: Optional[str] = None,
    ) -> str:
        parts = [
            reviewer_prompt,
            "",
            "Work to review:",
            "---",
            work,
            "---",
            "",
            "Evaluate and respond with JSON: {\"approved\": true|false, \"feedback\": \"summary\", \"changes_requested\": \"specific changes\"}",
        ]
        if previous_feedback:
            parts.insert(0, f"Previous feedback (round {round_num - 1}): {previous_feedback}\n")
        return "\n".join(parts)

    def _parse_review_response(self, text: str) -> Tuple[bool, str, Optional[str]]:
        """Parse reviewer JSON. Returns (approved, feedback, changes_requested)."""
        import json
        import re
        text = text.strip()
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                data = json.loads(match.group(0))
                approved = data.get("approved", False)
                feedback = data.get("feedback", "")
                changes = data.get("changes_requested") or data.get("changes")
                return bool(approved), str(feedback), str(changes) if changes else None
            except (json.JSONDecodeError, TypeError):
                pass
        if "approved" in text.lower() and "true" in text.lower():
            return True, text, None
        return False, text, None
