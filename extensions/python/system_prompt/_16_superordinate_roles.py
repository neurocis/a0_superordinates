"""Inject resolved upward-flowing Superordinate roles into the system prompt."""
from __future__ import annotations

from typing import Any

from agent import LoopData
from helpers.extension import Extension


class SuperordinateRolesPrompt(Extension):
    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent or not getattr(self.agent, "context", None):
            return

        try:
            from usr.plugins.a0_superordinates.helpers.roles import build_roles_prompt

            prompt = build_roles_prompt(self.agent.context.id)
        except Exception:
            prompt = ""

        if prompt:
            system_prompt.append(prompt)
