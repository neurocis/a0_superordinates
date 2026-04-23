"""Rename a superordinate chat context."""

from helpers.api import ApiHandler
from flask import Request, Response
from agent import AgentContext
from helpers.persist_chat import save_tmp_chat


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

        old_name = ctx.name or ""

        # Update the context name
        ctx.name = new_name

        # Ensure chat_rename doesn't override our name
        ctx.data["chat_rename_manual_lock"] = True

        # Update the name registry if old name was registered
        try:
            from usr.plugins.a0_superordinates.helpers.name_registry import (
                lookup_by_ctxid,
                unregister_name,
                register_name,
            )
            registered_name = lookup_by_ctxid(ctxid)
            if registered_name:
                unregister_name(registered_name)
                # Extract the base name (strip the profile suffix like " (developer)")
                # The registry uses the base name, not the display name
                register_name(new_name, ctxid)
        except Exception:
            pass  # Name registry is optional

        # Also update the sup_children entry on the parent context
        parent_ctxid = ctx.data.get("sup_parent", "")
        if parent_ctxid:
            parent_ctx = AgentContext.get(parent_ctxid)
            if parent_ctx:
                children = parent_ctx.data.get("sup_children", [])
                for child in children:
                    if child.get("ctxid") == ctxid:
                        child["name"] = new_name
                        break
                save_tmp_chat(parent_ctx)

        # Persist the renamed context
        save_tmp_chat(ctx)

        return {"ok": True, "old_name": old_name, "new_name": new_name}
