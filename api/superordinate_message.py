"""Route messages through the centralized superordinate_message tool."""

from __future__ import annotations

from helpers.api import ApiHandler, Request, Response
from agent import AgentContext
from usr.plugins.a0_superordinates.tools.superordinate_message import SuperordinateMessage as SuperordinateMessageTool


def _norm(value: object) -> str:
    return str(value or "").strip()


class SuperordinateMessage(ApiHandler):
    """Send a context-to-context message using centralized tool semantics."""

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        source_id = _norm(input.get("source_id") or input.get("from_id"))
        target_id = _norm(input.get("target_id") or input.get("to_id"))
        message = _norm(input.get("message"))
        message_type = _norm(input.get("reply") or "Prompt") or "Prompt"

        if not source_id:
            return {"ok": False, "error": "Missing source_id"}
        if not target_id:
            return {"ok": False, "error": "Missing target_id"}
        if not message:
            return {"ok": False, "error": "Missing message"}
        if source_id == target_id:
            return {"ok": False, "error": "Cannot route a superordinate_message to the same source context"}

        source_context = AgentContext.get(source_id)
        if not source_context:
            return {"ok": False, "error": f"Source context '{source_id}' not found"}
        target_context = AgentContext.get(target_id)
        if not target_context:
            return {"ok": False, "error": f"Target context '{target_id}' not found"}

        tool_args = {
            "superordinate_id": target_id,
            "message": message,
            "reply": message_type,
        }
        tool = SuperordinateMessageTool(
            agent=source_context.get_agent(),
            name="superordinate_message",
            method=None,
            args=tool_args,
            message="",
            loop_data=None,
        )
        result = await tool.execute(
            **tool_args,
            _allow_unrelated_route=True,
        )

        return {
            "ok": True,
            "source_id": source_id,
            "target_id": target_id,
            "message": result.message,
            "break_loop": result.break_loop,
            "additional": result.additional or {},
        }
