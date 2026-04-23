"""Shadowed core chat-rename extension.

This replaces the core _60_rename_chat.py to add manual-lock awareness.
When chat_rename_manual_lock is set on a context (e.g. by superordinate_spawn
or inline rename), the auto-rename is skipped so the user's chosen name is
preserved.  All other behavior is identical to the core extension.
"""
from __future__ import annotations

import asyncio

from agent import LoopData
from helpers import persist_chat, tokens
from helpers.extension import Extension


MANUAL_LOCK_DATA_KEY = "chat_rename_manual_lock"
MAX_AUTO_CHAT_NAME_LENGTH = 40


def _is_manual_name_locked(context) -> bool:
    """Check whether the context's name was manually set and should not be
    overwritten by the automatic renamer."""
    getter = getattr(context, "get_data", None)
    if callable(getter):
        return bool(getter(MANUAL_LOCK_DATA_KEY))
    data = getattr(context, "data", None)
    if isinstance(data, dict):
        return bool(data.get(MANUAL_LOCK_DATA_KEY))
    return False


class RenameChat(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        asyncio.create_task(self.change_name())

    async def change_name(self):
        if not self.agent:
            return

        # Skip auto-rename when the chat name was manually set
        if _is_manual_name_locked(self.agent.context):
            return

        try:
            from plugins._model_config.helpers.model_config import (
                get_utility_model_config,
            )

            util_cfg = get_utility_model_config(self.agent)

            history_text = self.agent.history.output_text()
            ctx_length = min(
                int(util_cfg.get("ctx_length", 128000) * 0.7),
                5000,
            )
            history_text = tokens.trim_to_tokens(history_text, ctx_length, "start")

            system = self.agent.read_prompt("fw.rename_chat.sys.md")
            current_name = self.agent.context.name
            message = self.agent.read_prompt(
                "fw.rename_chat.msg.md",
                current_name=current_name,
                history=history_text,
            )

            new_name = await self.agent.call_utility_model(
                system=system,
                message=message,
                background=True,
            )

            if new_name:
                if len(new_name) > MAX_AUTO_CHAT_NAME_LENGTH:
                    new_name = new_name[:MAX_AUTO_CHAT_NAME_LENGTH] + "..."
                self.agent.context.name = new_name
                persist_chat.save_tmp_chat(self.agent.context)

        except Exception:
            pass  # non-critical
