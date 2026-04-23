"""API endpoint for drag-and-drop reparenting of superordinate contexts.

Accepts:
    child_id:      context ID being moved
    new_parent_id: target parent context ID (null/empty = make root)
    position:      integer index within new parent's children list
                   (also used for root-level ordering via _sup_root_order.json)

Performs cycle detection, updates sup_parent/sup_children on all
affected contexts, persists to disk, and maintains root-level ordering.
"""

import json
import os
import logging

log = logging.getLogger("a0.superordinates.reparent")

from agent import AgentContext
from helpers.api import ApiHandler, Request, Response
from helpers.persist_chat import save_tmp_chat

ROOT_ORDER_FILE = "/a0/usr/chats/_sup_root_order.json"


def _load_root_order() -> list[str]:
    """Load root-level ordering from disk."""
    if os.path.isfile(ROOT_ORDER_FILE):
        try:
            with open(ROOT_ORDER_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _build_complete_root_order() -> list[str]:
    """Build a complete root order including ALL root items.
    
    Saved items maintain their positions; unsaved root items are appended
    in sorted order for stability. This ensures position indices from the
    frontend match the backend's list.
    """
    saved = _load_root_order()
    chats_dir = os.path.dirname(ROOT_ORDER_FILE)  # /a0/usr/chats
    all_root_ids = set()
    
    # Scan all contexts to find root items
    # Use in-memory contexts first, then disk
    try:
        from agent import AgentContext as _AC
        for ctx in _AC.all():
            if ctx.id and not (ctx.data.get("sup_parent") if ctx.data else None):
                all_root_ids.add(ctx.id)
    except Exception:
        pass
    
    if os.path.isdir(chats_dir):
        for d in os.listdir(chats_dir):
            if d.startswith("_") or d in all_root_ids:
                continue  # Skip metadata files/dirs and already-seen contexts
            chat_file = os.path.join(chats_dir, d, "chat.json")
            if not os.path.isfile(chat_file):
                continue
            try:
                with open(chat_file, "r") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue  # Skip malformed chat files
                if not data.get("data", {}).get("sup_parent"):
                    all_root_ids.add(d)
            except (json.JSONDecodeError, OSError, KeyError):
                continue
    
    # Build complete list: saved items first (if still root), then unsaved
    complete = []
    for rid in saved:
        if rid in all_root_ids:
            complete.append(rid)
    for rid in sorted(all_root_ids):
        if rid not in complete:
            complete.append(rid)
    return complete


def _save_root_order(order: list[str]) -> None:
    """Persist root-level ordering to disk."""
    os.makedirs(os.path.dirname(ROOT_ORDER_FILE), exist_ok=True)
    with open(ROOT_ORDER_FILE, "w") as f:
        json.dump(order, f)


class SuperordinateReparent(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        child_id = input.get("child_id", "").strip()
        new_parent_id = input.get("new_parent_id", "") or None
        if new_parent_id:
            new_parent_id = new_parent_id.strip()
        position = input.get("position", -1)
        if position is None:
            position = -1

        # --- Validation ---
        if not child_id:
            return {"ok": False, "error": "Missing child_id"}

        child_ctx = AgentContext.get(child_id)
        if not child_ctx:
            child_ctx = self.use_context(child_id, create_if_not_exists=False)
        if not child_ctx:
            return {"ok": False, "error": f"Child context '{child_id}' not found"}

        new_parent_ctx = None
        if new_parent_id:
            new_parent_ctx = AgentContext.get(new_parent_id)
            if not new_parent_ctx:
                new_parent_ctx = self.use_context(new_parent_id, create_if_not_exists=False)
            if not new_parent_ctx:
                return {"ok": False, "error": f"Parent context '{new_parent_id}' not found"}

            # Cycle detection: walk up from new_parent; if we hit child_id, reject
            if self._would_create_cycle(child_id, new_parent_id):
                return {"ok": False, "error": "Cannot reparent: would create a cycle"}

        # Can't parent to self
        if new_parent_id and new_parent_id == child_id:
            return {"ok": False, "error": "Cannot parent a context to itself"}

        # --- Detach from old parent ---
        old_parent_id = child_ctx.data.get("sup_parent") or None
        was_root = not old_parent_id
        log.warning(f"[REPARENT] child={child_id}, new_parent={new_parent_id}, pos={position}, old_parent={old_parent_id}, was_root={was_root}")

        if old_parent_id:
            old_parent_ctx = AgentContext.get(old_parent_id)
            if not old_parent_ctx:
                try:
                    old_parent_ctx = self.use_context(old_parent_id, create_if_not_exists=False)
                except Exception:
                    old_parent_ctx = None
            if old_parent_ctx:
                old_children = old_parent_ctx.data.get("sup_children", [])
                old_parent_ctx.data["sup_children"] = [
                    c for c in old_children if c.get("ctxid") != child_id
                ]
                save_tmp_chat(old_parent_ctx)
                log.warning(f"[REPARENT] removed child from old parent sup_children, remaining: {[c.get('ctxid') for c in old_parent_ctx.data.get('sup_children', [])]}")
            else:
                # Old parent no longer exists — just clear the stale reference
                log.warning(f"[REPARENT] old parent '{old_parent_id}' not found, clearing stale sup_parent")
                child_ctx.data.pop("sup_parent", None)

        # --- Remove from root order if it was a root item ---
        if was_root:
            root_order = _build_complete_root_order()
            root_order = [r for r in root_order if r != child_id]
            _save_root_order(root_order)

        # --- Attach to new parent ---
        if new_parent_id and new_parent_ctx:
            child_ctx.data["sup_parent"] = new_parent_id

            # Build child entry for sup_children
            child_entry = self._make_child_entry(child_ctx)

            new_children = new_parent_ctx.data.get("sup_children", [])
            # Remove if already present (shouldn't be, but defensive)
            new_children = [c for c in new_children if c.get("ctxid") != child_id]

            # Insert at position
            if position < 0 or position >= len(new_children):
                new_children.append(child_entry)
            else:
                new_children.insert(position, child_entry)

            new_parent_ctx.data["sup_children"] = new_children
            save_tmp_chat(new_parent_ctx)
            log.warning(f"[REPARENT] inserted into new parent sup_children at pos={position}, order: {[c.get('ctxid') for c in new_children]}")
        else:
            # Moving to root - clear parent and update root order
            child_ctx.data.pop("sup_parent", None)
            root_order = _build_complete_root_order()
            # Remove if already present (defensive)
            root_order = [r for r in root_order if r != child_id]
            # Insert at position
            if position < 0 or position >= len(root_order):
                root_order.append(child_id)
            else:
                root_order.insert(position, child_id)
            _save_root_order(root_order)
            log.warning(f"[REPARENT] updated root_order: {root_order}")

        save_tmp_chat(child_ctx)

        return {"ok": True}

    def _would_create_cycle(self, child_id: str, new_parent_id: str) -> bool:
        """Walk up from new_parent_id; if we reach child_id, it's a cycle."""
        visited = set()
        current = new_parent_id
        while current:
            if current == child_id:
                return True
            if current in visited:
                break  # already a cycle in existing data
            visited.add(current)
            ctx = AgentContext.get(current)
            if not ctx:
                ctx = self.use_context(current, create_if_not_exists=False)
            if not ctx:
                break
            current = ctx.data.get("sup_parent") or None
        return False

    def _make_child_entry(self, child_ctx: AgentContext) -> dict:
        """Build a sup_children entry dict from a child context."""
        from datetime import datetime, timezone
        return {
            "ctxid": child_ctx.id,
            "profile": child_ctx.data.get("sup_profile", "agent0"),
            "name": child_ctx.name or f"Chat #{child_ctx.no}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
