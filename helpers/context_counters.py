"""Per-context token counter state for A0 Superordinates.

This is intentionally local to the Superordinates plugin so the WebUI counters
work independently of the separate a0_context_monitor plugin.
"""
from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_token_data: dict[str, dict[str, int]] = {}


def get_configured_context_window(agent: Any = None, default: int = 0) -> int:
    """Return the configured chat model context window length, if available.

    This comes from Agent Zero's `_model_config` plugin (`chat.ctx_length`). It is
    the configured/model-budget value, not a provider-discovered live hard limit.
    """
    try:
        from plugins._model_config.helpers.model_config import get_chat_model_config

        cfg = get_chat_model_config(agent)
        value = int(cfg.get("ctx_length", default) or default)
        return max(0, value)
    except Exception:
        return max(0, int(default or 0))


def empty_tokens(agent: Any = None) -> dict[str, int]:
    """Return a zeroed token-count payload with configured context window."""
    return {
        "system_tokens": 0,
        "context_tokens": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "total_tokens": 0,
        "context_window_tokens": get_configured_context_window(agent),
    }


def update_tokens(
    context_id: str,
    system_tokens: int = 0,
    context_tokens: int = 0,
    prompt_tokens: int = 0,
    response_tokens: int = 0,
    context_window_tokens: int = 0,
) -> None:
    """Update the latest token breakdown for one context."""
    if not context_id:
        return
    with _lock:
        _token_data[context_id] = {
            "system_tokens": int(system_tokens or 0),
            "context_tokens": int(context_tokens or 0),
            "prompt_tokens": int(prompt_tokens or 0),
            "response_tokens": int(response_tokens or 0),
            "total_tokens": int(system_tokens or 0) + int(context_tokens or 0) + int(response_tokens or 0),
            "context_window_tokens": int(context_window_tokens or 0),
        }


def get_tokens(context_id: str) -> dict[str, int] | None:
    """Return the latest token breakdown for one context, if known."""
    if not context_id:
        return None
    with _lock:
        data = _token_data.get(context_id)
        return dict(data) if data is not None else None


def get_all_tokens() -> dict[str, dict[str, int]]:
    """Return token breakdowns for all known contexts."""
    with _lock:
        return {key: dict(value) for key, value in _token_data.items()}


def clear_tokens(context_id: str) -> None:
    """Clear the token breakdown for one context."""
    if not context_id:
        return
    with _lock:
        _token_data.pop(context_id, None)
