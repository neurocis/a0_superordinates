"""Core hierarchy management for persistent superordinates.

Context.data keys (NOT underscore-prefixed, so they survive serialization):
- sup_parent (str): parent context ID
- sup_children (list[dict]): [{ctxid, profile, name, created_at}]
- sup_profile (str): profile name of this superordinate
"""

from datetime import datetime, timezone
from agent import AgentContext

def get_children(parent_ctxid: str) -> list[dict]:
    """Return list of child context info for the given parent."""
    parent = AgentContext.get(parent_ctxid)
    if not parent:
        return []
    children = parent.data.get("sup_children", [])
    # Filter to only contexts that still exist
    return [c for c in children if AgentContext.get(c.get("ctxid", "")) is not None]

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
    child = AgentContext.get(child_ctxid)
    if not child:
        return None
    return child.data.get("sup_parent")

def get_hierarchy(ctxid: str) -> dict:
    """Return full subtree for UI rendering, starting from the root of ctxid's tree."""
    # Walk up to root
    root_id = ctxid
    while True:
        parent_id = get_parent(root_id)
        if parent_id is None:
            break
        root_id = parent_id

    # Walk down building tree
    return _build_tree(root_id)

def _build_tree(ctxid: str) -> dict:
    """Recursively build a hierarchy tree node."""
    ctx = AgentContext.get(ctxid)
    if not ctx:
        return {"ctxid": ctxid, "name": "(unknown)", "profile": "", "children": []}

    node = {
        "ctxid": ctxid,
        "name": ctx.name or f"Chat #{ctx.no}",
        "profile": ctx.data.get("sup_profile", "agent0"),
        "children": [],
    }

    children = ctx.data.get("sup_children", [])
    for child_info in children:
        child_ctxid = child_info.get("ctxid", "")
        if AgentContext.get(child_ctxid):
            node["children"].append(_build_tree(child_ctxid))

    return node
