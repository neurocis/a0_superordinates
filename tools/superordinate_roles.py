"""Return descendant superordinate roles and hierarchy for routing decisions."""
from __future__ import annotations

import json
from collections import deque
from typing import Any

from agent import AgentContext
from helpers.tool import Response, Tool
from usr.plugins.a0_superordinates.helpers.inheritance import (
    CHATS_DIR,
    get_context_data,
    get_context_name,
)
from usr.plugins.a0_superordinates.helpers.roles import (
    MAX_ROLES_NODES,
    read_roles_file,
)
from usr.plugins.a0_superordinates.helpers.routing_matcher import decide_route


def _context_exists(ctxid: str) -> bool:
    """Return whether a context exists in memory or on disk."""
    if not ctxid:
        return False
    try:
        if AgentContext.get(ctxid) is not None:
            return True
    except Exception:
        pass

    try:
        import os

        return os.path.isfile(os.path.join(CHATS_DIR, ctxid, "chat.json"))
    except Exception:
        return False


def _all_context_ids() -> list[str]:
    """Return known context ids from memory and persisted chat directories."""
    ids: set[str] = set()

    try:
        for ctx in getattr(AgentContext, "_contexts", {}).values():
            ctxid = getattr(ctx, "id", "")
            if ctxid:
                ids.add(ctxid)
    except Exception:
        pass

    try:
        import os

        for name in os.listdir(CHATS_DIR):
            if os.path.isfile(os.path.join(CHATS_DIR, name, "chat.json")):
                ids.add(name)
    except OSError:
        pass

    return sorted(ids)


def _parent_of(ctxid: str) -> str | None:
    """Return the authoritative parent ctxid for a context, if present."""
    parent = get_context_data(ctxid).get("sup_parent")
    if isinstance(parent, str) and parent.strip():
        return parent.strip()
    return None


def _children_by_authoritative_parent() -> dict[str, list[str]]:
    """Build parent -> children map from each child's authoritative sup_parent.

    This is intentionally derived from child data rather than a parent's cached
    sup_children list, so the routing payload stays defensive when in-memory
    context data and persisted chat metadata disagree.
    """
    children_by_parent: dict[str, list[str]] = {}
    for candidate in _all_context_ids():
        parent = _parent_of(candidate)
        if parent:
            children_by_parent.setdefault(parent, []).append(candidate)

    for parent, children in children_by_parent.items():
        children.sort(key=lambda child: (get_context_name(child).lower(), child))
    return children_by_parent


def _node(
    ctxid: str,
    parent: str | None,
    children: list[str],
    *,
    depth: int | None = None,
    path: list[str] | None = None,
) -> dict[str, Any]:
    """Build one flat routing node."""
    data: dict[str, Any] = {
        "ctxid": ctxid,
        "name": get_context_name(ctxid),
        "role": read_roles_file(ctxid),
        "parent": parent,
        "children": children,
    }
    if depth is not None:
        data["depth"] = depth
    if path is not None:
        data["path"] = path
    return data


def _tree_node(
    ctxid: str,
    children_by_parent: dict[str, list[str]],
    visited: set[str],
) -> dict[str, Any]:
    """Build nested tree representation with cycle protection."""
    if ctxid in visited:
        return {
            "ctxid": ctxid,
            "name": get_context_name(ctxid),
            "role": read_roles_file(ctxid),
            "children": [],
            "cycle": True,
        }

    visited.add(ctxid)
    children = children_by_parent.get(ctxid, [])
    return {
        "ctxid": ctxid,
        "name": get_context_name(ctxid),
        "role": read_roles_file(ctxid),
        "children": [
            _tree_node(child, children_by_parent, visited.copy())
            for child in children
        ],
    }


def _routing_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return candidates usable by the routing matcher.

    The matcher primarily routes among descendants, but the caller is included
    as a fallback/default-owner candidate so A0 can be selected when it is the
    current/default owner and no descendant matches confidently.
    """
    candidates: list[dict[str, Any]] = []
    caller = payload.get("caller")
    if isinstance(caller, dict):
        candidates.append(caller)
    descendants = payload.get("descendants")
    if isinstance(descendants, list):
        candidates.extend(candidate for candidate in descendants if isinstance(candidate, dict))
    return candidates


def add_routing_decision(payload: dict[str, Any], query: str) -> dict[str, Any]:
    """Attach a skill-first/name-failover routing decision for *query*."""
    if not isinstance(query, str) or not query.strip():
        return payload
    decision = decide_route(query.strip(), _routing_candidates(payload))
    payload["routing_decision"] = decision.to_dict()
    return payload


def build_superordinate_roles_payload(ctxid: str) -> dict[str, Any]:
    """Build routing JSON for caller plus descendants."""
    children_by_parent = _children_by_authoritative_parent()
    caller_children = children_by_parent.get(ctxid, [])

    descendants: list[dict[str, Any]] = []
    queue: deque[tuple[str, str, int, list[str]]] = deque(
        (child, ctxid, 1, [ctxid, child]) for child in caller_children
    )
    seen: set[str] = {ctxid}

    while queue and len(descendants) < MAX_ROLES_NODES:
        current, parent, depth, path = queue.popleft()
        if not current or current in seen:
            continue
        seen.add(current)

        children = children_by_parent.get(current, [])
        descendants.append(
            _node(current, parent, children, depth=depth, path=path)
        )

        for child in children:
            if child not in seen:
                queue.append((child, current, depth + 1, [*path, child]))

    return {
        "caller": _node(ctxid, _parent_of(ctxid), caller_children),
        "descendants": descendants,
        "tree": _tree_node(ctxid, children_by_parent, set()),
    }


class SuperordinateRoles(Tool):
    """List descendant roles and hierarchy as JSON for routing decisions."""

    async def execute(self, **kwargs):
        ctxid = kwargs.get("ctxid") or kwargs.get("context_id") or self.agent.context.id
        if not isinstance(ctxid, str) or not ctxid.strip():
            return Response(
                message=json.dumps(
                    {
                        "error": "Unable to determine caller context id.",
                        "caller": None,
                        "descendants": [],
                        "tree": None,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                break_loop=False,
            )

        ctxid = ctxid.strip()
        if not _context_exists(ctxid):
            return Response(
                message=json.dumps(
                    {
                        "error": f"Context not found: {ctxid}",
                        "caller": None,
                        "descendants": [],
                        "tree": None,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                break_loop=False,
            )

        payload = build_superordinate_roles_payload(ctxid)
        query = kwargs.get("query") or kwargs.get("request") or kwargs.get("target")
        if isinstance(query, str) and query.strip():
            add_routing_decision(payload, query)
        return Response(
            message=json.dumps(payload, indent=2, sort_keys=True),
            break_loop=False,
        )
