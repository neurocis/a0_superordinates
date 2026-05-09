"""Inject resolved upward-flowing Superordinate occupations into the system prompt."""
from __future__ import annotations

from typing import Any

from agent import LoopData
from helpers.extension import Extension


class SuperordinateOccupationsPrompt(Extension):
    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent or not getattr(self.agent, "context", None):
            return

        try:
            from usr.plugins.a0_superordinates.helpers.occupations import build_occupations_prompt

            prompt = build_occupations_prompt(self.agent.context.id)
        except Exception:
            prompt = ""

        if prompt:
            system_prompt.append(prompt)
