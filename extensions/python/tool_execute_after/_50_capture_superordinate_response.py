"""Capture final response-tool text for superordinate reply routing."""

from helpers.extension import Extension
from agent import LoopData


class CaptureSuperordinateResponse(Extension):

    async def execute(self, response=None, tool_name: str = "", loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent or tool_name != "response" or response is None:
            return

        context = self.agent.context
        user_msg = getattr(self.agent, "last_user_message", None)
        user_msg_id = getattr(user_msg, "id", "") or ""
        text = getattr(response, "message", "") or ""
        if not user_msg_id or not text:
            return

        context.data["_superordinate_last_response"] = {
            "user_message_id": user_msg_id,
            "text": text,
        }
