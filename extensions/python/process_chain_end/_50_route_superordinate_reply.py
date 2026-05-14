"""Route completed superordinate replies back at process_chain_end.

Trigger: the completed agent has pending superordinate route metadata for
the inbound message id, falling back to parsing a routed envelope beginning
with ``{From: "Name" (ctxid) ...}``. The envelope's Reply value controls whether
the reverse delivery prompts the original sender: Reply=Info is context-only;
anything else prompts.

This uses ``process_chain_end`` instead of ``monologue_end`` because Agent Zero's
core only calls named ``monologue_end`` extensions while the context task is
still alive. In practice, routed target tasks can already be considered complete
by then, so ``monologue_end`` may be skipped. ``process_chain_end`` is called by
``AgentContext.process`` after the full chain returns, making it the reliable
completion hook for this feature.
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


def _pending_route(context, user_msg_id: str) -> dict[str, str] | None:
    routes = context.data.get("_superordinate_pending_reply_routes") or {}
    if isinstance(routes, dict):
        route = routes.get(user_msg_id)
        if isinstance(route, dict) and route.get("from_id"):
            return {
                "from_name": str(route.get("from_name") or ""),
                "from_id": str(route.get("from_id") or ""),
                "reply": str(route.get("reply") or "Info"),
            }
    return None


def _response_text(agent, context, user_msg_id: str) -> str:
    response_record = context.data.get("_superordinate_last_response") or {}
    if response_record.get("user_message_id") == user_msg_id:
        text = str(response_record.get("text") or "").strip()
        if text:
            return text

    loop_data = getattr(agent, "loop_data", None)
    text = str(getattr(loop_data, "last_response", "") or "").strip()
    if text:
        return text

    try:
        history_output = agent.history.output() or []
        for item in reversed(history_output):
            if getattr(item, "ai", False):
                text = str(item.output_text() or "").strip()
                if text:
                    return text
    except Exception:
        pass
    return ""


class RouteSuperordinateReplyOnProcessEnd(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        agent = self.agent
        if not agent:
            return

        context = agent.context
        user_msg = getattr(agent, "last_user_message", None)
        user_msg_id = getattr(user_msg, "id", "") or ""
        if not user_msg_id:
            return

        # Idempotency: process_chain_end can be re-entered; route once per inbound message.
        if context.data.get("_superordinate_reply_routed_for_message_id") == user_msg_id:
            return

        route = _pending_route(context, user_msg_id) or _parse_inbound_route(_message_text(user_msg))
        if not route:
            return

        target_id = route["from_id"]
        if target_id == context.id:
            return

        response_text = _response_text(agent, context, user_msg_id)
        if not response_text:
            try:
                context.log.log(
                    type="warning",
                    heading="Superordinate reply routing skipped",
                    content=f"No completed response text was found for routed message {user_msg_id}.",
                )
            except Exception:
                pass
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

        # Preserve the original sender display label for reverse replies. When
        # Hero Handler mode rendered the inbound prompt as e.g.
        # `{From: "neurocis" (HeroCtxID)}`, the replying agent's local
        # `{To: ...}` observer copy should keep `neurocis` instead of falling
        # back to the Hero context's stored chat name.
        target_display_name = str(route.get("from_name") or "").strip()

        # Rule 5: replies ALWAYS post the full response to chat + memory of the
        # original sender. For non-Info replies, we additionally prompt the
        # original sender with a small stub body so they pick up that something
        # new is in their context — but the stub itself must NOT trigger another
        # reverse-reply, otherwise we get an infinite ping-pong of routed
        # messages. We deliver this as two separate calls.
        info_args = {
            "superordinate_id": target_id,
            "message": response_text,
            "reply": "Info",
            "Type": "Info",
        }
        if target_display_name:
            info_args["_target_display_name_override"] = target_display_name
        info_tool = SuperordinateMessage(
            agent=agent,
            name="superordinate_message",
            method=None,
            args=info_args,
            message="",
            loop_data=loop_data,
        )

        context.data["_superordinate_reply_routed_for_message_id"] = user_msg_id
        try:
            await info_tool.execute(
                **info_args,
                _allow_unrelated_route=True,
                _verified_superordinate_reply=True,
                _skip_reverse_route=True,
            )

            if delivery_type == "Prompt":
                stub_args = {
                    "superordinate_id": target_id,
                    "message": "Check context memory for details.",
                    "reply": reply,
                    "Type": "Prompt",
                }
                if target_display_name:
                    stub_args["_target_display_name_override"] = target_display_name
                stub_tool = SuperordinateMessage(
                    agent=agent,
                    name="superordinate_message",
                    method=None,
                    args=stub_args,
                    message="",
                    loop_data=loop_data,
                )
                await stub_tool.execute(
                    **stub_args,
                    _allow_unrelated_route=True,
                    _verified_superordinate_reply=True,
                    _skip_reverse_route=True,
                    _hidden=True,
                )

            routes = context.data.get("_superordinate_pending_reply_routes")
            if isinstance(routes, dict):
                routes.pop(user_msg_id, None)
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
