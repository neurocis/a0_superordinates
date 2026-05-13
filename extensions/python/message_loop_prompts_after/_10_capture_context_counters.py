"""Capture prompt token counters after the message-loop prompt is assembled."""
from __future__ import annotations

import json
import logging

from helpers.extension import Extension
from helpers.tokens import approximate_tokens
from usr.plugins.a0_superordinates.helpers.context_counters import get_configured_context_window, get_tokens, update_tokens

logger = logging.getLogger(__name__)


class CaptureSuperordinateContextCounters(Extension):
    async def execute(self, **kwargs):
        loop_data = kwargs.get("loop_data")
        if loop_data is None:
            return

        try:
            context_id = getattr(getattr(self.agent, "context", None), "id", None)
            if not context_id:
                return

            system_tokens = 0
            for sys_str in getattr(loop_data, "system", None) or []:
                if isinstance(sys_str, str) and sys_str:
                    system_tokens += approximate_tokens(sys_str)

            context_tokens = 0
            for msg in getattr(loop_data, "history_output", None) or []:
                content = msg.get("content", "") if isinstance(msg, dict) else ""
                if isinstance(content, str) and content:
                    context_tokens += approximate_tokens(content)
                elif content:
                    try:
                        context_tokens += approximate_tokens(json.dumps(content))
                    except (TypeError, ValueError):
                        pass

            existing = get_tokens(context_id) or {}
            response_tokens = existing.get("response_tokens", 0)

            update_tokens(
                context_id=context_id,
                system_tokens=system_tokens,
                context_tokens=context_tokens,
                prompt_tokens=system_tokens + context_tokens,
                response_tokens=response_tokens,
                context_window_tokens=get_configured_context_window(self.agent),
            )
        except Exception as exc:
            logger.error("Error capturing Superordinates context counters: %s", exc, exc_info=True)
