"""Stop a persistent superordinate from further processing.

Mirrors the UI behavior of clicking the stop/pause control on a running
chat. Calls `context.kill_process()` on the target which kills any
currently running deferred task without resetting chat history.

If the target context isn't running, the call is a safe no-op and reports
that the superordinate was already idle.
"""

import json
import os

from helpers.tool import Tool, Response
from agent import AgentContext
from helpers.state_monitor_integration import mark_dirty_all


CHATS_DIR = "/a0/usr/chats"


def _read_chat_json(ctxid: str):
    chat_file = os.path.join(CHATS_DIR, ctxid, "chat.json")
    if not os.path.isfile(chat_file):
        return None
    try:
        with open(chat_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _all_context_ids():
    ids = set()
    try:
        for ctx in AgentContext.all():
            if ctx.id:
                ids.add(ctx.id)
    except Exception:
        pass
    if os.path.isdir(CHATS_DIR):
        for d in os.listdir(CHATS_DIR):
            if d.startswith("_"):
                continue
            if os.path.isfile(os.path.join(CHATS_DIR, d, "chat.json")):
                ids.add(d)
    return ids


def _get_name_for_ctxid(ctxid: str) -> str:
    ctx = AgentContext.get(ctxid)
    if ctx and ctx.name:
        return ctx.name
    chat = _read_chat_json(ctxid)
    if chat:
        return chat.get("name", "") or ""
    return ""


class SuperordinateStop(Tool):

    async def execute(self, **kwargs):
        name = (kwargs.get("name") or "").strip()
        ctxid = (kwargs.get("superordinate_id") or "").strip()

        # Resolve name → ctxid
        if name and not ctxid:
            from usr.plugins.a0_superordinates.helpers.name_registry import lookup_by_name
            resolved = lookup_by_name(name)
            if not resolved:
                lower = name.lower()
                for cid in _all_context_ids():
                    cn = (_get_name_for_ctxid(cid) or "").strip().lower()
                    if cn == lower:
                        resolved = cid
                        break
            if not resolved:
                return Response(
                    message="No SuperOrdinate found with name '{}'. Use superordinate_list to see available names.".format(name),
                    break_loop=False,
                )
            ctxid = resolved

        if not ctxid:
            return Response(
                message="Provide either 'name' or 'superordinate_id' to identify the superordinate to stop.",
                break_loop=False,
            )

        target_ctx = AgentContext.get(ctxid)
        if not target_ctx:
            return Response(
                message="Context '{}' is not loaded; nothing to stop (it isn't currently processing).".format(ctxid),
                break_loop=False,
                additional={"superordinate_id": ctxid, "was_running": False},
            )

        target_name = target_ctx.name or ctxid
        was_running = False
        try:
            was_running = target_ctx.is_running()
        except Exception:
            was_running = bool(getattr(target_ctx, "task", None))

        # Kill any running monologue/task. Safe no-op if nothing is running.
        try:
            target_ctx.kill_process()
        except Exception as e:
            return Response(
                message="Failed to stop SuperOrdinate '{}': {}".format(target_name, e),
                break_loop=False,
            )

        # Clear paused flag so the UI reflects an idle, non-paused state.
        try:
            target_ctx.paused = False
        except Exception:
            pass

        # Log a small note inside the target chat for visibility.
        try:
            target_ctx.log.log(
                type="info",
                content="Processing stopped by superordinate_stop.",
            )
        except Exception:
            pass

        mark_dirty_all(reason="superordinate_stop")

        if was_running:
            msg = "SuperOrdinate '{}' was running and has been stopped.".format(target_name)
        else:
            msg = "SuperOrdinate '{}' was already idle; no running task to stop.".format(target_name)

        return Response(
            message=msg,
            break_loop=False,
            additional={"superordinate_id": ctxid, "was_running": was_running},
        )
