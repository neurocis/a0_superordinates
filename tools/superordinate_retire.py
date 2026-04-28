"""Retire (close) a persistent superordinate.

Mirrors the JS `closeChat` UI behavior in superordinate-store.js:
- If target is a normal chat: move it under the 'Closed Chats' folder
  (creating that folder at root if missing).
- If target is already under 'Closed Chats': permanently delete it.
- If target IS the 'Closed Chats' folder itself: permanently delete it
  along with every descendant (recursive bottom-up kill).

This is the programmatic equivalent of clicking the close (X) button
on a superordinate chat in the sidebar.
"""

import json
import os
from datetime import datetime, timezone

from helpers.tool import Tool, Response
from agent import AgentContext
from helpers import persist_chat, guids
from helpers.persist_chat import save_tmp_chat
from helpers.state_monitor_integration import mark_dirty_all


CHATS_DIR = "/a0/usr/chats"
ROOT_ORDER_FILE = "/a0/usr/chats/_sup_root_order.dat"
CLOSED_NAME = "Closed Chats"


# ── disk / context helpers ────────────────────────────────────────────────

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
    """All known context IDs (in-memory + on-disk)."""
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


def _get_data_for_ctxid(ctxid: str) -> dict:
    ctx = AgentContext.get(ctxid)
    if ctx:
        return ctx.data
    chat = _read_chat_json(ctxid)
    if chat:
        return chat.get("data", {}) or {}
    return {}


def _is_closed_name(name: str) -> bool:
    return bool(name) and name.strip().lower() == CLOSED_NAME.lower()


def _find_closed_chats_id():
    """Locate an existing 'Closed Chats' root context, or None."""
    for cid in _all_context_ids():
        if _is_closed_name(_get_name_for_ctxid(cid)):
            return cid
    return None


def _is_under_closed_chats(ctxid: str) -> bool:
    """Walk up sup_parent chain; True if any ancestor is named 'Closed Chats'."""
    visited = set()
    cur = ctxid
    while cur:
        data = _get_data_for_ctxid(cur)
        parent = data.get("sup_parent")
        if not parent or parent in visited:
            return False
        visited.add(parent)
        if _is_closed_name(_get_name_for_ctxid(parent)):
            return True
        cur = parent
    return False


# ── root order helpers (mirror superordinate_reparent.py) ─────────────────

def _load_root_order():
    if os.path.isfile(ROOT_ORDER_FILE):
        try:
            with open(ROOT_ORDER_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_root_order(order):
    os.makedirs(os.path.dirname(ROOT_ORDER_FILE), exist_ok=True)
    with open(ROOT_ORDER_FILE, "w") as f:
        json.dump(order, f)


# ── create / detach / attach / kill ───────────────────────────────────────

def _create_closed_chats() -> str:
    """Create a 'Closed Chats' root context and return its ctxid."""
    from initialize import initialize_agent
    new_id = guids.generate_id()
    config = initialize_agent()
    ctx = AgentContext(config=config, id=new_id, name=CLOSED_NAME)
    # Lock the name so chat_rename plugin can't re-title it
    ctx.data["chat_rename_manual_lock"] = True
    save_tmp_chat(ctx)

    order = _load_root_order()
    if new_id not in order:
        order.append(new_id)
        _save_root_order(order)
    return new_id


def _detach_from_parent(child_ctx):
    """Remove child from its current parent's sup_children (or root order)."""
    old_parent_id = child_ctx.data.get("sup_parent")
    if old_parent_id:
        old_parent = AgentContext.get(old_parent_id)
        if old_parent:
            children = old_parent.data.get("sup_children", [])
            old_parent.data["sup_children"] = [
                c for c in children if c.get("ctxid") != child_ctx.id
            ]
            save_tmp_chat(old_parent)
        child_ctx.data.pop("sup_parent", None)
    else:
        order = _load_root_order()
        order = [r for r in order if r != child_ctx.id]
        _save_root_order(order)


def _attach_to_parent(child_ctx, parent_ctx):
    """Set sup_parent on child and append child entry to parent's sup_children."""
    child_ctx.data["sup_parent"] = parent_ctx.id
    children = parent_ctx.data.get("sup_children", [])
    children = [c for c in children if c.get("ctxid") != child_ctx.id]
    children.append({
        "ctxid": child_ctx.id,
        "profile": child_ctx.data.get("sup_profile", "agent0"),
        "name": child_ctx.name or f"Chat #{getattr(child_ctx, 'no', '?')}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    parent_ctx.data["sup_children"] = children
    save_tmp_chat(parent_ctx)
    save_tmp_chat(child_ctx)


def _kill_chat(ctxid: str) -> None:
    """Permanently delete a chat. Equivalent to api/chat_remove.RemoveChat."""
    # Cancel any scheduled tasks tied to this context
    try:
        from helpers.task_scheduler import TaskScheduler
        scheduler = TaskScheduler.get()
        scheduler.cancel_tasks_by_context(ctxid, terminate_thread=True)
    except Exception:
        pass

    ctx = AgentContext.get(ctxid)
    if ctx:
        # Stop any running monologue
        try:
            ctx.reset()
        except Exception:
            pass
        # Detach so dangling references in parent's sup_children are cleaned
        try:
            _detach_from_parent(ctx)
        except Exception:
            pass

    # Unregister name from registry if present
    try:
        from usr.plugins.a0_superordinates.helpers.name_registry import (
            lookup_by_ctxid,
            unregister_name,
        )
        nm = lookup_by_ctxid(ctxid)
        if nm:
            unregister_name(nm)
    except Exception:
        pass

    AgentContext.remove(ctxid)
    persist_chat.remove_chat(ctxid)


def _collect_descendants(ctxid: str):
    """Depth-first descendants of ctxid, deepest first (safe bottom-up kill)."""
    result = []
    data = _get_data_for_ctxid(ctxid)
    children = data.get("sup_children", []) or []
    for c in children:
        cid = (c or {}).get("ctxid")
        if cid:
            result.extend(_collect_descendants(cid))
            result.append(cid)
    return result


# ── tool entry point ──────────────────────────────────────────────────────

class SuperordinateRetire(Tool):

    async def execute(self, **kwargs):
        name = (kwargs.get("name") or "").strip()
        ctxid = (kwargs.get("superordinate_id") or "").strip()

        # Resolve name → ctxid
        if name and not ctxid:
            from usr.plugins.a0_superordinates.helpers.name_registry import lookup_by_name
            resolved = lookup_by_name(name)
            if not resolved:
                # Fallback: case-insensitive context-name search
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
                message="Provide either 'name' or 'superordinate_id' to identify the superordinate to retire.",
                break_loop=False,
            )

        target_name = _get_name_for_ctxid(ctxid) or ctxid

        # Case 1: target IS the 'Closed Chats' folder → kill folder + descendants
        if _is_closed_name(target_name):
            descendants = _collect_descendants(ctxid)
            killed = 0
            for did in descendants:
                try:
                    _kill_chat(did)
                    killed += 1
                except Exception:
                    pass
            try:
                _kill_chat(ctxid)
            except Exception:
                pass
            mark_dirty_all(reason="superordinate_retire.kill_closed_chats")
            return Response(
                message="Closed Chats folder and {} descendant chat(s) permanently removed.".format(killed),
                break_loop=False,
            )

        # Case 2: target already lives under 'Closed Chats' → permanent delete
        if _is_under_closed_chats(ctxid):
            _kill_chat(ctxid)
            mark_dirty_all(reason="superordinate_retire.kill")
            return Response(
                message="SuperOrdinate '{}' was already retired and has now been permanently removed.".format(target_name),
                break_loop=False,
                additional={"superordinate_id": ctxid, "deleted": True},
            )

        # Case 3: normal retire → move under 'Closed Chats'
        target_ctx = AgentContext.get(ctxid)
        if not target_ctx:
            # Force-load context from disk so we can mutate sup_parent
            try:
                persist_chat.load_tmp_chats()
                target_ctx = AgentContext.get(ctxid)
            except Exception:
                target_ctx = None
        if not target_ctx:
            return Response(
                message="Context '{}' could not be loaded; cannot retire.".format(ctxid),
                break_loop=False,
            )

        closed_id = _find_closed_chats_id()
        if not closed_id:
            try:
                closed_id = _create_closed_chats()
            except Exception as e:
                return Response(
                    message="Failed to create 'Closed Chats' folder: {}".format(e),
                    break_loop=False,
                )

        closed_ctx = AgentContext.get(closed_id)
        if not closed_ctx:
            return Response(
                message="'Closed Chats' folder could not be loaded (id={}).".format(closed_id),
                break_loop=False,
            )

        # Prevent reparenting onto self/own descendant (defensive)
        if closed_id == ctxid:
            return Response(
                message="Cannot retire a context onto itself.",
                break_loop=False,
            )

        try:
            _detach_from_parent(target_ctx)
            _attach_to_parent(target_ctx, closed_ctx)
        except Exception as e:
            return Response(
                message="Retire failed during reparent: {}".format(e),
                break_loop=False,
            )

        mark_dirty_all(reason="superordinate_retire.move")

        return Response(
            message="SuperOrdinate '{}' has been retired and moved under 'Closed Chats'.".format(target_name),
            break_loop=False,
            additional={"superordinate_id": ctxid, "closed_chats_id": closed_id, "deleted": False},
        )
