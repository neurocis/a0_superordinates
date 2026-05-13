"""API endpoint exposing A0 Superordinates context token counters."""
from __future__ import annotations

from helpers.api import ApiHandler, Request, Response
from usr.plugins.a0_superordinates.helpers import context_counters


class SuperordinateContextCounters(ApiHandler):
    """Return the latest token breakdown captured by Superordinates hooks."""

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        action = str(input.get("action") or "token_counts").strip() if isinstance(input, dict) else "token_counts"
        if action != "token_counts":
            return {"error": f"Unknown action: {action}", "status": 400}

        context_id = str(input.get("context_id") or "").strip() if isinstance(input, dict) else ""
        if context_id:
            result = context_counters.get_tokens(context_id)
            if result is None:
                return {"context_id": context_id, "found": False, **context_counters.empty_tokens()}
            if not result.get("context_window_tokens"):
                result = {**result, "context_window_tokens": context_counters.get_configured_context_window()}
            return {"context_id": context_id, "found": True, **result}

        return {"contexts": context_counters.get_all_tokens()}
