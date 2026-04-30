"""Synchronize superordinate display-name changes into lookup metadata.

Superordinates keep name data in more than one place:
- ``AgentContext.name``: the chat/sidebar display name
- ``context.data.sup_name``: canonical tool-facing superordinate name
- ``name_registry.json``: name -> ctxid lookup used by superordinate_* tools
- parent ``data.sup_children[*].name``: cached hierarchy/list label

When a chat name changes outside the dedicated superordinate_rename API (for
example via the framework's automatic chat renamer), those auxiliary structures
can go stale.  This module centralizes the repair so every rename path can call
one function after the context name is finalized.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from agent import AgentContext
from helpers.persist_chat import save_tmp_chat

log = logging.getLogger("a0.superordinates.name_sync")

CHATS_DIR = "/a0/usr/chats"


def _chat_json_path(ctxid: str) -> str:
    return os.path.join(CHATS_DIR, ctxid, "chat.json")


def _load_chat_json(ctxid: str) -> dict[str, Any] | None:
    path = _chat_json_path(ctxid)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _save_chat_json(ctxid: str, payload: dict[str, Any]) -> bool:
    path = _chat_json_path(ctxid)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
        return True
    except OSError as e:
        log.warning(f"[NAME_SYNC] failed to save {path}: {e}")
        return False


def _ctx_participates_in_superordinate_metadata(ctx: AgentContext, registered_name: str | None = None) -> bool:
    """Return True if this context is part of the superordinate hierarchy.

    We intentionally include root superordinate containers (contexts with
    children but no parent) and contexts that are only known through the name
    registry. Plain non-superordinate chats should not be registered just
    because the global chat renamer ran.
    """
    if not ctx or not getattr(ctx, "id", None):
        return False
    data = getattr(ctx, "data", None) or {}
    return bool(
        data.get("sup_parent")
        or data.get("sup_children")
        or data.get("sup_name")
        or registered_name
    )


_PROFILE_SUFFIX_RE = re.compile(r"^(.*?)\s*\([^)]*\)\s*$")


def _display_name_matches_canonical(display_name: str, canonical_name: str) -> bool:
    """Return True if a sidebar display name still represents canonical_name.

    Spawned superordinates commonly use a display name like ``Devvy
    (Developer)`` while tools address them by canonical ``Devvy``. Reconcile
    logic must not mistake that profile suffix for a user rename.
    """
    display_name = (display_name or "").strip()
    canonical_name = (canonical_name or "").strip()
    if not display_name or not canonical_name:
        return False
    if display_name == canonical_name:
        return True
    m = _PROFILE_SUFFIX_RE.match(display_name)
    return bool(m and m.group(1).strip() == canonical_name)


def _canonical_name_for_reconcile(ctx: AgentContext, registered_name: str | None = None) -> str:
    """Choose the safest canonical lookup name during passive reconciliation.

    If ``data.sup_name`` exists and the visible chat name is merely
    ``<sup_name> (<profile>)``, keep ``sup_name``. If the visible name no
    longer matches that convention, treat it as an external completed rename
    and promote the visible name to the canonical lookup name.
    """
    data = getattr(ctx, "data", None) or {}
    stored = (data.get("sup_name") or "").strip()
    display = (getattr(ctx, "name", "") or "").strip()
    registered = (registered_name or "").strip()

    if stored:
        if display and not _display_name_matches_canonical(display, stored):
            return display
        return stored
    return display or registered


def _sync_parent_child_entry(ctxid: str, parent_id: str, new_name: str) -> bool:
    """Update the cached child name in parent.data.sup_children.

    Tries in-memory parent first, then falls back to editing the parent's
    chat.json on disk so offline parent contexts are repaired too.
    """
    if not parent_id:
        return False

    parent_ctx = AgentContext.get(parent_id)
    if parent_ctx:
        children = parent_ctx.data.get("sup_children", []) or []
        changed = False
        for child in children:
            if isinstance(child, dict) and child.get("ctxid") == ctxid:
                if child.get("name") != new_name:
                    child["name"] = new_name
                    changed = True
                break
        if changed:
            parent_ctx.data["sup_children"] = children
            save_tmp_chat(parent_ctx)
        return changed

    parent_payload = _load_chat_json(parent_id)
    if not parent_payload:
        return False
    parent_data = parent_payload.get("data", {})
    if not isinstance(parent_data, dict):
        return False
    children = parent_data.get("sup_children", []) or []
    changed = False
    for child in children:
        if isinstance(child, dict) and child.get("ctxid") == ctxid:
            if child.get("name") != new_name:
                child["name"] = new_name
                changed = True
            break
    if not changed:
        return False
    parent_data["sup_children"] = children
    parent_payload["data"] = parent_data
    return _save_chat_json(parent_id, parent_payload)


def sync_superordinate_name(ctx: AgentContext, new_name: str | None = None, *, force: bool = False) -> dict[str, Any]:
    """Sync a completed context-name change into superordinate metadata.

    Args:
        ctx: AgentContext whose ``name`` has already been changed, or is about
            to be changed to ``new_name`` by the caller.
        new_name: Optional explicit canonical name. Defaults to ``ctx.name``.
        force: If False, only sync contexts that already look like
            superordinates. If True, sync regardless of metadata presence.

    Returns a diagnostic dict. ``ok`` is False only when a registry conflict
    prevented the name from being registered. Parent-entry updates are best
    effort and reported separately.
    """
    ctxid = getattr(ctx, "id", "") or ""
    name = (new_name if new_name is not None else (getattr(ctx, "name", "") or "")).strip()
    if not ctxid or not name:
        return {"ok": False, "error": "missing ctxid or name", "ctxid": ctxid, "name": name}

    from usr.plugins.a0_superordinates.helpers.name_registry import (
        lookup_by_ctxid,
        set_name_for_ctxid,
    )

    registered_name = lookup_by_ctxid(ctxid)
    if not force and not _ctx_participates_in_superordinate_metadata(ctx, registered_name):
        return {"ok": True, "skipped": True, "reason": "not superordinate metadata", "ctxid": ctxid, "name": name}

    old_sup_name = (ctx.data.get("sup_name") if isinstance(ctx.data, dict) else None) or registered_name

    registry_ok = set_name_for_ctxid(ctxid, name)
    if not registry_ok:
        return {
            "ok": False,
            "error": f"name '{name}' is already registered to another context",
            "ctxid": ctxid,
            "name": name,
            "old_name": old_sup_name,
        }

    if isinstance(ctx.data, dict):
        ctx.data["sup_name"] = name

    parent_changed = False
    parent_id = ctx.data.get("sup_parent") if isinstance(ctx.data, dict) else None
    if parent_id:
        parent_changed = _sync_parent_child_entry(ctxid, parent_id, name)

    return {
        "ok": True,
        "ctxid": ctxid,
        "old_name": old_sup_name,
        "new_name": name,
        "registry_changed": old_sup_name != name,
        "parent_changed": parent_changed,
    }


def reconcile_superordinate_name(ctx: AgentContext) -> dict[str, Any]:
    """Repair name metadata for a context after any completed name change.

    This is intended for passive/background use (startup/monologue cleanup).
    It safely preserves spawned names such as ``Devvy`` when the chat display
    name is ``Devvy (Developer)``, but promotes the display name when it no
    longer matches the stored canonical name, which indicates an external
    rename occurred outside ``superordinate_rename``.
    """
    ctxid = getattr(ctx, "id", "") or ""
    if not ctxid:
        return {"ok": False, "error": "missing ctxid"}

    from usr.plugins.a0_superordinates.helpers.name_registry import lookup_by_ctxid

    registered_name = lookup_by_ctxid(ctxid)
    if not _ctx_participates_in_superordinate_metadata(ctx, registered_name):
        return {"ok": True, "skipped": True, "reason": "not superordinate metadata", "ctxid": ctxid}

    canonical_name = _canonical_name_for_reconcile(ctx, registered_name)
    if not canonical_name:
        return {"ok": False, "error": "missing canonical name", "ctxid": ctxid}

    return sync_superordinate_name(ctx, canonical_name, force=True)
