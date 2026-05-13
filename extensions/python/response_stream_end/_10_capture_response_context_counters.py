"""Capture response token counters after response streaming completes."""
from __future__ import annotations

import json
import logging

from helpers.extension import Extension
from helpers.tokens import approximate_tokens
from usr.plugins.a0_superordinates.helpers.context_counters import get_configured_context_window, get_tokens, update_tokens

logger = logging.getLogger(__name__)


class CaptureSuperordinateResponseContextCounters(Extension):
    async def execute(self, **kwargs):
        loop_data = kwargs.get("loop_data")
        if loop_data is None:
            return

        try:
            context_id = getattr(getattr(self.agent, "context", None), "id", None)
            if not context_id:
                return

            response_text = ""
            if getattr(loop_data, "last_response", None):
                response_text = str(loop_data.last_response)

            if not response_text and hasattr(self.agent, "history"):
                try:
                    history_output = self.agent.history.output()
                    for msg in reversed(history_output or []):
                        if isinstance(msg, dict) and msg.get("ai"):
                            content = msg.get("content", "")
                            if isinstance(content, str):
                                response_text = content
                            elif content:
                                response_text = json.dumps(content)
                            if response_text:
                                break
                except Exception:
                    pass

            response_tokens = approximate_tokens(response_text) if response_text else 0
            existing = get_tokens(context_id) or {}

            update_tokens(
                context_id=context_id,
                system_tokens=existing.get("system_tokens", 0),
                context_tokens=existing.get("context_tokens", 0),
                prompt_tokens=existing.get("prompt_tokens", 0),
                response_tokens=response_tokens,
                context_window_tokens=existing.get("context_window_tokens", 0) or get_configured_context_window(self.agent),
            )
        except Exception as exc:
            logger.error("Error capturing Superordinates response counters: %s", exc, exc_info=True)
