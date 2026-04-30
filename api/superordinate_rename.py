"""Rename a superordinate chat context."""

import json
import os

from helpers.api import ApiHandler
from flask import Request, Response
from agent import AgentContext
from helpers.persist_chat import save_tmp_chat
from usr.plugins.a0_superordinates.helpers.static_name import is_static_name_locked, parse_bool as _parse_bool


def _is_static_name_locked(ctx) -> bool:
    if is_static_name_locked(ctx):
        return True

    # Rare server-side fallback only: if a process somehow has an older loaded
    # context, still honor StaticName persisted in chat.json. The hot WebUI path
    # now uses normal context output_data instead of map-wide disk merging.
    ctxid = getattr(ctx, "id", None)
    if ctxid:
        chat_file = os.path.join("/a0/usr/chats", ctxid, "chat.json")
        try:
            with open(chat_file, "r") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                disk_data = raw.get("data") or {}
                disk_output = raw.get("output_data") or {}
                if _parse_bool(disk_output.get("StaticName", disk_output.get("static_name")), False):
                    return True
                if _parse_bool(disk_data.get("StaticName", disk_data.get("static_name")), False):
                    return True
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    return False


class SuperordinateRename(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        ctxid = input.get("ctxid", "")
        new_name = (input.get("new_name", "") or "").strip()

        if not ctxid:
            return {"ok": False, "error": "Missing ctxid"}
        if not new_name:
            return {"ok": False, "error": "Missing new_name"}

        ctx = AgentContext.get(ctxid)
        if not ctx:
            return {"ok": False, "error": f"Context {ctxid} not found"}

        if _is_static_name_locked(ctx):
            return {"ok": False, "error": "This agent has StaticName enabled and cannot be renamed"}

        old_name = ctx.name or ""

        # Refuse duplicate tool-facing names before mutating the context.
        try:
            from usr.plugins.a0_superordinates.helpers.name_registry import lookup_by_name
            existing = lookup_by_name(new_name)
            if existing and existing != ctxid:
                return {"ok": False, "error": f"A SuperOrdinate named '{new_name}' already exists"}
        except Exception:
            pass  # Registry is best-effort; the sync helper will retry/log below.

        # Update the context name
        ctx.name = new_name

        # Ensure chat_rename doesn't override our name
        ctx.data["chat_rename_manual_lock"] = True

        # Update canonical superordinate name, name registry, and the cached
        # parent sup_children entry from one shared code path.
        try:
            from usr.plugins.a0_superordinates.helpers.name_sync import sync_superordinate_name
            sync_result = sync_superordinate_name(ctx, new_name, force=True)
            if not sync_result.get("ok"):
                ctx.name = old_name
                return {"ok": False, "error": sync_result.get("error", "Failed to sync name registry")}
        except Exception as e:
            ctx.name = old_name
            return {"ok": False, "error": f"Failed to sync superordinate name metadata: {e}"}

        # Persist the renamed context
        save_tmp_chat(ctx)

        return {"ok": True, "old_name": old_name, "new_name": new_name}
