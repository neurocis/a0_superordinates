"""Route Hero Mode UI input through the centralized superordinate_message tool."""

from __future__ import annotations

from helpers.api import ApiHandler, Request, Response
from agent import AgentContext
from usr.plugins.a0_superordinates.tools.superordinate_message import SuperordinateMessage


def _norm(value: object) -> str:
    return str(value or "").strip()


class SuperordinateHeroMessage(ApiHandler):
    """Send a focused-chat prompt as the designated Hero using tool semantics."""

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        hero_id = _norm(input.get("hero_id"))
        target_id = _norm(input.get("target_id"))
        message = _norm(input.get("message"))

        if not hero_id:
            return {"ok": False, "error": "Missing hero_id"}
        if not target_id:
            return {"ok": False, "error": "Missing target_id"}
        if not message:
            return {"ok": False, "error": "Missing message"}
        if hero_id == target_id:
            return {"ok": False, "error": "Hero Mode routing is only for non-Hero focused chats"}

        hero_context = AgentContext.get(hero_id)
        if not hero_context:
            return {"ok": False, "error": f"Hero context '{hero_id}' not found"}
        target_context = AgentContext.get(target_id)
        if not target_context:
            return {"ok": False, "error": f"Target context '{target_id}' not found"}

        tool_args = {
            "superordinate_id": target_id,
            "message": message,
            "Type": "Prompt",
        }
        tool = SuperordinateMessage(
            agent=hero_context.get_agent(),
            name="superordinate_message",
            method=None,
            args=tool_args,
            message="",
            loop_data=None,
        )
        result = await tool.execute(
            **tool_args,
            _allow_unrelated_hero_route=True,
        )

        return {
            "ok": True,
            "hero_id": hero_id,
            "target_id": target_id,
            "message": result.message,
            "break_loop": result.break_loop,
            "additional": result.additional or {},
        }
