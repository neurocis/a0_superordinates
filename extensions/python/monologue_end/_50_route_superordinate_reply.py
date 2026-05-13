"""Route completed superordinate replies back at monologue_end.

Trigger: the monologue's user message contains a routed envelope beginning with
``{From: "Name" (ctxid) ...}``. The envelope's Reply value controls whether the
reverse delivery prompts the original sender: Reply=Info is context-only;
anything else prompts.
"""

from __future__ import annotations

import re
from helpers.extension import Extension
from agent import AgentContext, LoopData
from usr.plugins.a0_superordinates.tools.superordinate_message import SuperordinateMessage

_ENVELOPE_RE = re.compile(
    r"\{\s*From:\s*\"(?P<from_name>[^\"]+)\"\s*\((?P<from_id>[^)]+)\)"
    r"(?:\s*,\s*To:\s*\"(?P<to_name>[^\"]+)\"\s*\((?P<to_id>[^)]+)\))?"
    r"(?:\s*,\s*Reply:\s*(?P<reply>[^}\n]+))?\s*\}",
    re.MULTILINE,
)


def _message_text(message) -> str:
    if not message:
        return ""
    try:
        return message.output_text()
    except Exception:
        return str(getattr(message, "content", "") or "")


def _parse_inbound_route(text: str) -> dict[str, str] | None:
    if not text:
        return None
    match = _ENVELOPE_RE.search(text)
    if not match:
        return None
    from_id = (match.group("from_id") or "").strip()
    if not from_id:
        return None
    reply = (match.group("reply") or "Info").strip()
    reply = " ".join(reply.split()) or "Info"
    return {
        "from_name": (match.group("from_name") or "").strip(),
        "from_id": from_id,
        "reply": reply,
    }


class RouteSuperordinateReply(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        context = self.agent.context
        user_msg = getattr(loop_data, "user_message", None) or getattr(self.agent, "last_user_message", None)
        user_msg_id = getattr(user_msg, "id", "") or ""
        if not user_msg_id:
            return

        # Idempotency: monologue_end may be re-entered; route once per inbound message.
        if context.data.get("_superordinate_reply_routed_for_message_id") == user_msg_id:
            return

        route = _parse_inbound_route(_message_text(user_msg))
        if not route:
            return

        target_id = route["from_id"]
        if target_id == context.id:
            return

        response_record = context.data.get("_superordinate_last_response") or {}
        if response_record.get("user_message_id") != user_msg_id:
            return

        response_text = str(response_record.get("text") or "").strip()
        if not response_text:
            return

        target_context = AgentContext.get(target_id)
        if not target_context:
            try:
                context.log.log(
                    type="warning",
                    heading="Superordinate reply routing failed",
                    content=f"Original sender context '{target_id}' was not found.",
                )
            except Exception:
                pass
            return

        reply = route["reply"] or "Info"
        delivery_type = "Info" if reply.lower() == "info" else "Prompt"

        tool_args = {
            "superordinate_id": target_id,
            "message": response_text,
            "reply": reply,
            "Type": delivery_type,
        }
        tool = SuperordinateMessage(
            agent=self.agent,
            name="superordinate_message",
            method=None,
            args=tool_args,
            message="",
            loop_data=loop_data,
        )

        context.data["_superordinate_reply_routed_for_message_id"] = user_msg_id
        try:
            await tool.execute(**tool_args, _allow_unrelated_route=True)
        except Exception as exc:
            context.data.pop("_superordinate_reply_routed_for_message_id", None)
            try:
                context.log.log(
                    type="error",
                    heading="Superordinate reply routing failed",
                    content=str(exc),
                )
            except Exception:
                pass
