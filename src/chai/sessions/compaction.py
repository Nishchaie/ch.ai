"""Context compaction: summarize middle of conversation when near context limit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..providers.base import Provider, ProviderResponse


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _serialize_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except TypeError:
        return str(content)


def estimate_message_tokens(message: Dict[str, Any]) -> int:
    role = message.get("role", "user")
    content = _serialize_content(message.get("content", ""))
    return _estimate_tokens(role + ":" + content) + 8


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)


def get_context_limit(
    provider_name: str,
    model: str,
    overrides: Optional[Dict[str, int]] = None,
) -> int:
    overrides = overrides or {}
    for key in (f"{provider_name}:{model}", model, provider_name, ""):
        if key and key in overrides and isinstance(overrides[key], int):
            return overrides[key]
    return 128_000


def _select_head_tail_indices(
    token_estimates: List[int],
    head_budget: float,
    tail_budget: float,
) -> Tuple[int, int]:
    head_end = -1
    total = 0
    for idx, tokens in enumerate(token_estimates):
        total += tokens
        head_end = idx
        if total >= head_budget:
            break
    tail_start = len(token_estimates)
    total = 0
    for idx in range(len(token_estimates) - 1, -1, -1):
        total += token_estimates[idx]
        tail_start = idx
        if total >= tail_budget:
            break
    return head_end, tail_start


def _build_summary_prompt() -> str:
    return (
        "You are summarizing a conversation to reduce context size.\n"
        "Summarize the middle portion only. Preserve: goals, constraints, decisions; "
        "file paths, APIs, commands; TODOs, errors, unresolved questions. "
        "Be concise and factual. Do not add new information."
    )


def _summarize_middle(
    provider: Provider,
    middle_messages: List[Dict[str, Any]],
    max_tokens: int,
) -> Optional[str]:
    if not middle_messages:
        return None
    raw = provider.chat(
        messages=middle_messages,
        system=_build_summary_prompt(),
        tools=None,
        max_tokens=max_tokens,
        stream=False,
    )
    if isinstance(raw, ProviderResponse):
        return (raw.text or "").strip() or None
    return None


def maybe_compact(
    provider: Provider,
    messages: List[Dict[str, Any]],
    config: Optional[Config] = None,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Summarize middle of conversation when near context limit.

    Returns (compacted: bool, new_messages: List).
    """
    from ..config import get_config

    cfg = config or get_config()
    context_limit = get_context_limit(
        cfg.default_provider,
        cfg.default_model,
        cfg.context_model_limits,
    )
    usable = max(context_limit - cfg.context_reserved_output_tokens, 1)
    message_tokens = estimate_messages_tokens(messages)
    ratio = message_tokens / usable

    if len(messages) < cfg.context_compact_min_messages:
        return False, messages
    if ratio < cfg.context_compact_threshold:
        return False, messages

    message_budget = max(usable, 0)
    if message_budget <= 0:
        return False, messages

    head_budget = message_budget * cfg.context_keep_head_ratio
    tail_budget = message_budget * cfg.context_keep_tail_ratio
    if head_budget + tail_budget >= message_budget:
        return False, messages

    token_estimates = [estimate_message_tokens(m) for m in messages]
    head_end, tail_start = _select_head_tail_indices(
        token_estimates, head_budget, tail_budget
    )
    if head_end < 0 or tail_start >= len(messages) or head_end >= tail_start:
        return False, messages

    head_messages = messages[: head_end + 1]
    tail_messages = messages[tail_start:]
    middle_messages = messages[head_end + 1 : tail_start]

    if not middle_messages:
        return False, messages

    summary_text = _summarize_middle(
        provider,
        middle_messages,
        max_tokens=cfg.context_compact_max_tokens,
    )
    if not summary_text:
        return False, messages

    summary_message = {
        "role": "user",
        "content": "[CONTEXT SUMMARY]\n" + summary_text,
    }
    new_messages = head_messages + [summary_message] + tail_messages
    return True, new_messages
