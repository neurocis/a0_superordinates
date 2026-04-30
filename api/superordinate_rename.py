"""Rename a superordinate chat context."""

import json
import os

from helpers.api import ApiHandler
from flask import Request, Response
from agent import AgentContext
from helpers.persist_chat import save_tmp_chat


def _parse_bool(value, default: bool = False) -> bool:
    """Parse persisted boolean-ish values without making string 'false' truthy."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off", ""}:
            return False
    return default

def _is_static_name_locked(ctx) -> bool:
    data = getattr(ctx, "data", {}) or {}
    if _parse_bool(data.get("StaticName", data.get("static_name")), False):
        return True

    # Defensive disk fallback: if the process has an older in-memory context
    # without plugin metadata, still honor StaticName persisted in chat.json.
    ctxid = getattr(ctx, "id", None)
    if ctxid:
        chat_file = os.path.join("/a0/usr/chats", ctxid, "chat.json")
        try:
            with open(chat_file, "r") as f:
                raw = json.load(f)
            disk_data = (raw.get("data") or {}) if isinstance(raw, dict) else {}
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
