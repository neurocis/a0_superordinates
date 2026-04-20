"""Core hierarchy management for persistent superordinates.

Context.data keys (NOT underscore-prefixed, so they survive serialization):
- sup_parent (str): parent context ID
- sup_children (list[dict]): [{ctxid, profile, name, created_at}]
- sup_profile (str): profile name of this superordinate
"""

import json
import os
from datetime import datetime, timezone
from agent import AgentContext


def _read_chat_json(ctxid: str) -> dict | None:
    """Read context data from chat.json file on disk."""
    chat_file = os.path.join("/a0/usr/chats", ctxid, "chat.json")
    if not os.path.isfile(chat_file):
        return None
    try:
        with open(chat_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _get_context_data(ctxid: str) -> dict:
    """Get context.data, using in-memory context or falling back to disk."""
    ctx = AgentContext.get(ctxid)
    if ctx:
        return ctx.data
    # Fallback: read from chat.json on disk
    chat = _read_chat_json(ctxid)
    if chat:
        return chat.get("data", {})
    return {}


def _get_context_name(ctxid: str) -> str:
    """Get context name from in-memory context or disk fallback."""
    ctx = AgentContext.get(ctxid)
    if ctx:
        return ctx.name or f"Chat #{ctx.no}"
    chat = _read_chat_json(ctxid)
    if chat:
        return chat.get("name", f"Chat {ctxid[:6]}")
    return f"Chat {ctxid[:6]}"


def _context_exists(ctxid: str) -> bool:
    """Check if a context exists (in memory or on disk)."""
    if AgentContext.get(ctxid) is not None:
        return True
    chat_file = os.path.join("/a0/usr/chats", ctxid, "chat.json")
    return os.path.isfile(chat_file)


def get_children(parent_ctxid: str) -> list[dict]:
    """Return list of child context info for the given parent."""
    data = _get_context_data(parent_ctxid)
    children = data.get("sup_children", [])
    # Filter to only contexts that still exist
    return [c for c in children if _context_exists(c.get("ctxid", ""))]


def add_child(parent_ctxid: str, child_ctxid: str, profile: str, name: str) -> None:
    """Register a child context under a parent."""
    parent = AgentContext.get(parent_ctxid)
    if not parent:
        return
    children = parent.data.get("sup_children", [])
    entry = {
        "ctxid": child_ctxid,
        "profile": profile,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    children.append(entry)
    parent.data["sup_children"] = children


def remove_child(parent_ctxid: str, child_ctxid: str) -> None:
    """Unregister a child context from a parent."""
    parent = AgentContext.get(parent_ctxid)
    if not parent:
        return
    children = parent.data.get("sup_children", [])
    parent.data["sup_children"] = [
        c for c in children if c.get("ctxid") != child_ctxid
    ]


def get_parent(child_ctxid: str) -> str | None:
    """Return parent ctxid for the given child, or None."""
    data = _get_context_data(child_ctxid)
    return data.get("sup_parent")


def get_hierarchy(ctxid: str) -> dict:
    """Return full subtree for UI rendering, starting from the root of ctxid's tree."""
    # Walk up to root
    root_id = ctxid
    visited = set()
    while True:
        if root_id in visited:
            break  # Prevent infinite loops
        visited.add(root_id)
        parent_id = get_parent(root_id)
        if parent_id is None:
            break
        root_id = parent_id

    # Walk down building tree
    return _build_tree(root_id)


def _build_tree(ctxid: str) -> dict:
    """Recursively build a hierarchy tree node."""
    if not _context_exists(ctxid):
        return {"ctxid": ctxid, "name": "(unknown)", "profile": "", "children": []}

    data = _get_context_data(ctxid)
    node = {
        "ctxid": ctxid,
        "name": _get_context_name(ctxid),
        "profile": data.get("sup_profile", "agent0"),
        "children": [],
    }

    children = data.get("sup_children", [])
    for child_info in children:
        child_ctxid = child_info.get("ctxid", "")
        if _context_exists(child_ctxid):
            node["children"].append(_build_tree(child_ctxid))

    return node
