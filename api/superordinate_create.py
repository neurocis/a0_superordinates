"""API endpoint to create a new chat context with a name pre-set.

Combines chat creation + naming in a single call so the context
never appears as 'Chat #XX' in the UI.

Accepts:
    name:       display name for the new context (optional)
    parent_id:  parent context ID to nest under (optional)
    position:   position within parent's children (optional, default 0)
"""

import logging

from agent import AgentContext
from helpers.api import ApiHandler, Request, Response
from helpers.persist_chat import save_tmp_chat
from helpers import guids

log = logging.getLogger("a0.superordinates.create")


class SuperordinateCreate(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        name = (input.get("name") or "").strip()
        parent_id = (input.get("parent_id") or "").strip() or None
        position = input.get("position", 0)
        if position is None:
            position = 0

        # Generate a new context ID
        new_ctxid = guids.generate_id()

        # Create the context
        new_ctx = self.use_context(new_ctxid)
        if not new_ctx:
            return {"ok": False, "error": "Failed to create context"}

        # Set the name immediately
        if name:
            new_ctx.name = name
            # Lock against auto-rename
            new_ctx.data["chat_rename_manual_lock"] = True

        # If parent_id specified, set up parent-child relationship
        if parent_id:
            parent_ctx = AgentContext.get(parent_id)
            if not parent_ctx:
                try:
                    parent_ctx = self.use_context(parent_id, create_if_not_exists=False)
                except Exception:
                    parent_ctx = None

            if parent_ctx:
                new_ctx.data["sup_parent"] = parent_id

                # Build child entry
                child_entry = {
                    "ctxid": new_ctxid,
                    "name": name,
                }

                children = parent_ctx.data.get("sup_children", [])
                # Remove if already present (defensive)
                children = [c for c in children if c.get("ctxid") != new_ctxid]

                if position < 0 or position >= len(children):
                    children.append(child_entry)
                else:
                    children.insert(position, child_entry)

                parent_ctx.data["sup_children"] = children
                save_tmp_chat(parent_ctx)
            else:
                log.warning(f"[CREATE] Parent '{parent_id}' not found, creating as root")

        # Save the new context
        save_tmp_chat(new_ctx)

        # Trigger UI refresh
        from helpers.state_monitor_integration import mark_dirty_all
        mark_dirty_all(reason="superordinate_create")

        log.info(f"[CREATE] Created context '{new_ctxid}' with name='{name}', parent='{parent_id}'")

        return {
            "ok": True,
            "ctxid": new_ctxid,
            "name": name,
        }
