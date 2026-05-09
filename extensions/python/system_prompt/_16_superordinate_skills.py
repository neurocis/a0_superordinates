"""Inject resolved upward-flowing Superordinate skills into the system prompt."""
from __future__ import annotations

from typing import Any

from agent import LoopData
from helpers.extension import Extension


class SuperordinateSkillsPrompt(Extension):
    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent or not getattr(self.agent, "context", None):
            return

        try:
            from usr.plugins.a0_superordinates.helpers.skills import build_skills_prompt

            prompt = build_skills_prompt(self.agent.context.id)
        except Exception:
            prompt = ""

        if prompt:
            system_prompt.append(prompt)
