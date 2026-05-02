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
import sys
from pathlib import Path


# Import Agent Zero framework modules defensively.  This plugin has a local
# helpers/ package, and when the plugin directory is the current/early sys.path
# entry it can shadow /a0/helpers.  agent.py imports top-level helpers.dotenv,
# so map API discovery can otherwise fail before returning JSON.
_FRAMEWORK_ROOT = Path("/a0").resolve()
_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_HELPERS = (_PLUGIN_ROOT / "helpers").resolve()
_ORIGINAL_SYS_PATH = list(sys.path)


def _path_resolves_to_plugin_root(entry: str) -> bool:
    try:
        candidate = Path(entry or os.getcwd()).resolve()
    except Exception:
        return False
    if candidate == _PLUGIN_ROOT:
        return True
    try:
        # Any user-plugin root on sys.path can expose a top-level helpers/
        # package that shadows Agent Zero's framework /a0/helpers package.
        return candidate.parent == Path("/a0/usr/plugins").resolve()
    except Exception:
        return False


def _module_file_is_plugin_helper(module: object) -> bool:
    try:
        module_file = Path(str(getattr(module, "__file__", "") or "/")).resolve()
    except Exception:
        return False
    try:
        framework_helpers = (_FRAMEWORK_ROOT / "helpers").resolve()
        if module_file == framework_helpers / "__init__.py" or module_file.is_relative_to(framework_helpers):
            return False
    except Exception:
        pass
    try:
        if module_file == _PLUGIN_HELPERS / "__init__.py" or module_file.is_relative_to(_PLUGIN_HELPERS):
            return True
    except Exception:
        pass
    try:
        user_plugins = Path("/a0/usr/plugins").resolve()
        return module_file.is_relative_to(user_plugins) and "helpers" in module_file.parts
    except Exception:
        return False


try:
    for _name in list(sys.modules):
        if _name == "helpers" or _name.startswith("helpers."):
            if _module_file_is_plugin_helper(sys.modules[_name]):
                sys.modules.pop(_name, None)

    _framework_root_str = str(_FRAMEWORK_ROOT)
    sys.path = [
        p for p in sys.path
        if p != _framework_root_str and not _path_resolves_to_plugin_root(p)
    ]
    sys.path.insert(0, _framework_root_str)

    # Import a framework helpers submodule first so sys.modules["helpers"] is
    # definitely /a0/helpers before agent.py imports models.py, which imports
    # top-level helpers.dotenv.
    from helpers.api import ApiHandler, Request, Response
    from agent import AgentContext
finally:
    sys.path = _ORIGINAL_SYS_PATH

from usr.plugins.a0_superordinates.helpers.static_name import sync_static_name_output


def _parse_indicator_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off", ""}:
            return False
    return default


def _empty_scheduler_indicators() -> dict[str, bool]:
    return {
        "has_calendar": False,
        "calendar_indicator": False,
        "has_prompts": False,
        "prompt_indicator": False,
        "has_json": False,
        "json_indicator": False,
    }


def _normalize_scheduler_indicators(result: object) -> dict[str, bool]:
    indicators = _empty_scheduler_indicators()
    if isinstance(result, dict):
        has_calendar = _parse_indicator_bool(
            result.get("has_calendar", result.get("calendar_indicator", False)),
            False,
        )
        has_prompts = _parse_indicator_bool(
            result.get(
                "has_prompts",
                result.get("prompt_indicator", result.get("has_json", result.get("json_indicator", False))),
            ),
            False,
        )
    else:
        # Backward compatibility with older scheduler builds that returned only
        # the calendar boolean.
        has_calendar = _parse_indicator_bool(result, False)
        has_prompts = False

    indicators.update({
        "has_calendar": has_calendar,
        "calendar_indicator": has_calendar,
        "has_prompts": has_prompts,
        "prompt_indicator": has_prompts,
        "has_json": has_prompts,
        "json_indicator": has_prompts,
    })
    return indicators


def _persist_scheduler_indicators_optional(ctxid: str) -> dict[str, bool] | None:
    """Return scheduler-owned sidebar indicators when a0_scheduler is installed.

    A0 Superordinates must not hard-require the scheduler plugin.  When the
    scheduler plugin is absent, disabled, or unhealthy, map rendering fails
    closed for badges instead of raising a 500 or trusting stale metadata.
    """
    try:
        from usr.plugins.a0_scheduler.helpers.agent_calendar import persist_calendar_indicator

        try:
            result = persist_calendar_indicator(ctxid, return_details=True)
        except TypeError:
            result = persist_calendar_indicator(ctxid)
        return _normalize_scheduler_indicators(result)
    except Exception:
        return None



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
                    # Cheap in-memory normalization only: if an already-loaded
                    # context has data.StaticName from an older plugin version,
                    # mirror it into output_data so the regular context snapshot
                    # exposes the lock to the WebUI. No chat.json reread here.
                    sync_static_name_output(ctx)
                    all_ctx_data[ctx.id] = ctx.data if ctx.data else {}
                    seen_ids.add(ctx.id)
        except Exception:
            pass  # AgentContext.all() may not exist in all versions

        # 1b. Disk fallback only for contexts not loaded in memory.
        # In-memory contexts are the freshest source for hierarchy movement.
        # Per-agent StaticName is intentionally exposed through normal context
        # output_data/snapshot now, so map.py no longer rereads every chat.json
        # just to merge plugin lock metadata.
        if os.path.isdir(chats_dir):
            for d in os.listdir(chats_dir):
                if d.startswith("_"):
                    continue  # Skip metadata files/dirs
                if d in seen_ids:
                    continue
                chat_file = os.path.join(chats_dir, d, "chat.json")
                if not os.path.isfile(chat_file):
                    continue
                try:
                    with open(chat_file, "r") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        continue  # Skip malformed chat files
                    all_ctx_data[d] = data.get("data", {}) or {}
                    seen_ids.add(d)
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
        # Calendar indicators are owned by a0_scheduler and are read only via
        # an optional import.  No scheduler network sync is triggered here.
        scheduler_indicators: dict[str, dict[str, bool]] = {}
        for ctxid in all_ctx_data:
            scheduler_indicator = _persist_scheduler_indicators_optional(ctxid)
            # Scheduler state is now owned by a0_scheduler. If that plugin is
            # absent, disabled, or unhealthy, fail closed instead of trusting
            # stale pre-extraction metadata or raising a sidebar-map 500.
            scheduler_indicators[ctxid] = (
                scheduler_indicator if scheduler_indicator is not None else _empty_scheduler_indicators()
            )

        def _has_inheritance_file(ctxid: str) -> bool:
            try:
                from usr.plugins.a0_superordinates.helpers.inheritance import read_inheritance_file

                return bool(read_inheritance_file(ctxid).strip())
            except Exception:
                return False

        def indicator_payload(ctxid: str) -> dict[str, bool]:
            payload = dict(scheduler_indicators.get(ctxid, _empty_scheduler_indicators()))
            payload["has_inheritance"] = _has_inheritance_file(ctxid)
            payload["inheritance_indicator"] = payload["has_inheritance"]
            return payload

        hierarchy_map: dict[str, dict] = {}

        # Add all contexts that have a parent
        for ctxid, par_id in parent_of.items():
            hierarchy_map[ctxid] = {
                "parent": par_id,
                "children": children_of.get(ctxid, []),
                **indicator_payload(ctxid),
            }

        # Add all contexts that have children (even if they have no parent)
        for ctxid, kids in children_of.items():
            if ctxid not in hierarchy_map:
                hierarchy_map[ctxid] = {
                    "parent": parent_of.get(ctxid),
                    "children": kids,
                    **indicator_payload(ctxid),
                }
            # If already added (context is both parent and child), ensure
            # children list is set from our derived data
            else:
                hierarchy_map[ctxid]["children"] = kids
                hierarchy_map[ctxid].update(indicator_payload(ctxid))


        # Add standalone/root contexts too so every visible chat is represented.
        for ctxid in all_ctx_data:
            if ctxid not in hierarchy_map:
                hierarchy_map[ctxid] = {
                    "parent": parent_of.get(ctxid),
                    "children": children_of.get(ctxid, []),
                    **indicator_payload(ctxid),
                }

        # Include name registry for name-based lookups
        from usr.plugins.a0_superordinates.helpers.name_registry import get_all_names
        names = get_all_names()

        return {"map": hierarchy_map, "names": names, "root_order": root_order}
