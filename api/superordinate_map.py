"""API endpoint returning hierarchy map for ALL chats.

Returns {ctxid: {parent: str|null, children: [ctxid]}} for every chat
that has hierarchy data, plus a name→ctxid registry for name-based lookup.

Fixes applied:
- Issue A: Reads in-memory AgentContext objects FIRST, falls back to disk
  only for contexts not loaded in memory. This prevents stale data when
  add_child() has modified in-memory state but chat.json hasn't been
  persisted yet.
- Issue D: Uses sup_parent as the SOLE authoritative source for
  parent-child relationships. Children lists are derived by scanning all
  contexts' sup_parent values rather than reading sup_children arrays
  which may be stale.
"""

import json
import os

from agent import AgentContext
from helpers.api import ApiHandler, Request, Response


class SuperordinateMap(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        chats_dir = "/a0/usr/chats"

        # Phase 1: Collect context data from ALL sources.
        # In-memory AgentContext objects take priority over disk.
        # Key = ctxid, Value = context data dict
        all_ctx_data: dict[str, dict] = {}
        seen_ids: set[str] = set()

        # 1a. In-memory contexts (authoritative, most up-to-date)
        try:
            for ctx in AgentContext.all():
                if ctx.id and ctx.id not in seen_ids:
                    all_ctx_data[ctx.id] = ctx.data if ctx.data else {}
                    seen_ids.add(ctx.id)
        except Exception:
            pass  # AgentContext.all() may not exist in all versions

        # 1b. Disk fallback for contexts not currently loaded in memory
        if os.path.isdir(chats_dir):
            for d in os.listdir(chats_dir):
                if d.startswith("_") or d in seen_ids:
                    continue  # Skip metadata files/dirs and already-loaded contexts
                chat_file = os.path.join(chats_dir, d, "chat.json")
                if not os.path.isfile(chat_file):
                    continue
                try:
                    with open(chat_file, "r") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        continue  # Skip malformed chat files
                    all_ctx_data[d] = data.get("data", {})
                except (json.JSONDecodeError, OSError, KeyError):
                    continue

        # Phase 2: Build hierarchy map using sup_parent as sole authority
        # for WHICH items are children, but sup_children from the parent
        # to determine the ORDER of those children.
        parent_of: dict[str, str | None] = {}  # ctxid -> parent ctxid
        children_set: dict[str, set[str]] = {}  # ctxid -> set of child ctxids (from sup_parent)

        # First pass: extract every context's declared parent
        for ctxid, ctx_data in all_ctx_data.items():
            parent = ctx_data.get("sup_parent") or None
            if parent is not None:
                parent_of[ctxid] = parent
                if parent not in children_set:
                    children_set[parent] = set()
                children_set[parent].add(ctxid)

        # Second pass: build ORDERED children lists using sup_children from parent
        children_of: dict[str, list[str]] = {}  # ctxid -> ordered [child ctxids]
        for par_id, child_ids in children_set.items():
            # Get the parent's sup_children array for ordering
            par_data = all_ctx_data.get(par_id, {})
            sup_children = par_data.get("sup_children", [])
            # Extract ordered ctxids from sup_children entries
            ordered = []
            for entry in sup_children:
                cid = entry.get("ctxid") if isinstance(entry, dict) else None
                if cid and cid in child_ids:
                    ordered.append(cid)
            # Append any children found via sup_parent but not in sup_children
            for cid in child_ids:
                if cid not in ordered:
                    ordered.append(cid)
            children_of[par_id] = ordered

        # Phase 2b: Root-level ordering.
        # Load saved root order, then build a COMPLETE list that includes
        # all current root items (not just those explicitly saved).
        root_order_file = os.path.join(chats_dir, "_sup_root_order.dat")  # NOT .json - framework's _convert_v080_chats() migrates *.json files at startup
        saved_root_order: list[str] = []
        if os.path.isfile(root_order_file):
            try:
                with open(root_order_file, "r") as f:
                    saved_root_order = json.load(f)
            except (json.JSONDecodeError, OSError):
                saved_root_order = []
        # Identify all root items: contexts that exist AND have no parent
        # (or whose parent doesn't exist in our data)
        all_root_ids = set()
        for ctxid in all_ctx_data:
            par = all_ctx_data[ctxid].get("sup_parent") or None
            if par is None or par not in all_ctx_data:
                all_root_ids.add(ctxid)

        # Build complete root_order: saved items first (if still root),
        # then unsaved root items appended in sorted order for stability
        root_order: list[str] = []
        for rid in saved_root_order:
            if rid in all_root_ids:
                root_order.append(rid)
        for rid in sorted(all_root_ids):
            if rid not in root_order:
                root_order.append(rid)

        # NOTE: map.py is intentionally READ-ONLY for the persistence file.
        # Only superordinate_reparent.py writes _sup_root_order.json, in response
        # to explicit user drag-and-drop reordering. This prevents accidental
        # state loss if some other process transiently wipes the file at startup
        # (which would otherwise cause map.py to lock in a wrong order on the
        # next fetchMap call).

        # Phase 3: Assemble the final hierarchy map.
        # Include any context that is either a parent or a child.
        hierarchy_map: dict[str, dict] = {}

        # Add all contexts that have a parent
        for ctxid, par_id in parent_of.items():
            hierarchy_map[ctxid] = {
                "parent": par_id,
                "children": children_of.get(ctxid, []),
            }

        # Add all contexts that have children (even if they have no parent)
        for ctxid, kids in children_of.items():
            if ctxid not in hierarchy_map:
                hierarchy_map[ctxid] = {
                    "parent": parent_of.get(ctxid),
                    "children": kids,
                }
            # If already added (context is both parent and child), ensure
            # children list is set from our derived data
            else:
                hierarchy_map[ctxid]["children"] = kids

        # Include name registry for name-based lookups
        from usr.plugins.a0_superordinates.helpers.name_registry import get_all_names
        names = get_all_names()

        return {"map": hierarchy_map, "names": names, "root_order": root_order}
