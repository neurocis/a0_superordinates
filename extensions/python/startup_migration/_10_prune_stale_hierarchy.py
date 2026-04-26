"""Startup pruning of stale hierarchy references.

Runs once at framework startup. Scans all chat directories on disk and:
- Removes sup_parent references to non-existent contexts
- Prunes sup_children entries pointing to non-existent contexts
- Cleans _sup_root_order.json of non-existent context IDs
- Unregisters dead names from the name registry
"""

import json
import os
import logging

from helpers.extension import Extension

log = logging.getLogger("a0.superordinates.startup_prune")

CHATS_DIR = "/a0/usr/chats"
# NOTE: Use .dat (NOT .json) - the framework's _convert_v080_chats() in
# helpers/persist_chat.py runs at startup and moves any *.json file at the top
# of CHATS_DIR into <name>/chat.json (legacy v0.8.0 chat migration). This
# silently destroys our root order file. Using .dat sidesteps that scan.
ROOT_ORDER_FILE = os.path.join(CHATS_DIR, "_sup_root_order.dat")
LEGACY_ROOT_ORDER_JSON = os.path.join(CHATS_DIR, "_sup_root_order.json")
LEGACY_ROOT_ORDER_ARTIFACT = os.path.join(CHATS_DIR, "_sup_root_order", "chat.json")
LEGACY_ROOT_ORDER_ARTIFACT_DIR = os.path.join(CHATS_DIR, "_sup_root_order")


def _migrate_legacy_root_order():
    """Recover root order from legacy locations and clean up artifacts.

    Three possible legacy states (any may exist on startup):
    1. ``_sup_root_order.json`` at top of chats dir (will be eaten by v080
       migration unless we move it to .dat first).
    2. ``_sup_root_order/chat.json`` directory (the v080 migration artifact
       from a previous startup).
    3. Nothing (file already migrated, or never existed).

    Strategy: pick the freshest valid order from any legacy source, write it
    to the new .dat path, then remove the legacy files/dir.
    """
    candidates = []  # (mtime, order, source_path)
    for src in (LEGACY_ROOT_ORDER_JSON, LEGACY_ROOT_ORDER_ARTIFACT):
        if os.path.isfile(src):
            try:
                with open(src, "r") as f:
                    order = json.load(f)
                if isinstance(order, list):
                    candidates.append((os.path.getmtime(src), order, src))
            except (json.JSONDecodeError, OSError):
                pass

    if candidates:
        # If new .dat doesn't exist, or legacy is newer, use legacy
        candidates.sort(key=lambda x: x[0], reverse=True)
        newest_mtime, newest_order, newest_src = candidates[0]
        write_dat = True
        if os.path.isfile(ROOT_ORDER_FILE):
            try:
                if os.path.getmtime(ROOT_ORDER_FILE) >= newest_mtime:
                    write_dat = False
            except OSError:
                pass
        if write_dat:
            try:
                with open(ROOT_ORDER_FILE, "w") as f:
                    json.dump(newest_order, f)
                log.warning(
                    f"[PRUNE] Migrated root order from legacy {newest_src} to {ROOT_ORDER_FILE}"
                )
            except OSError as e:
                log.warning(f"[PRUNE] Failed to migrate root order: {e}")

    # Clean up legacy artifacts (whether or not we migrated)
    try:
        if os.path.isfile(LEGACY_ROOT_ORDER_JSON):
            os.remove(LEGACY_ROOT_ORDER_JSON)
            log.warning(f"[PRUNE] Removed legacy {LEGACY_ROOT_ORDER_JSON}")
    except OSError as e:
        log.warning(f"[PRUNE] Failed to remove legacy json: {e}")
    try:
        if os.path.isfile(LEGACY_ROOT_ORDER_ARTIFACT):
            os.remove(LEGACY_ROOT_ORDER_ARTIFACT)
        if os.path.isdir(LEGACY_ROOT_ORDER_ARTIFACT_DIR):
            # Only remove if empty (defensive - should be empty after removing chat.json)
            try:
                os.rmdir(LEGACY_ROOT_ORDER_ARTIFACT_DIR)
                log.warning(f"[PRUNE] Removed legacy artifact dir {LEGACY_ROOT_ORDER_ARTIFACT_DIR}")
            except OSError:
                pass
    except OSError as e:
        log.warning(f"[PRUNE] Failed to remove legacy artifact: {e}")

def _context_exists_on_disk(ctxid: str) -> bool:
    """Check if a context's chat directory exists on disk."""
    if not ctxid:
        return False
    return os.path.isfile(os.path.join(CHATS_DIR, ctxid, "chat.json"))


def _load_chat_data(ctxid: str) -> dict | None:
    """Load chat.json data for a context."""
    chat_file = os.path.join(CHATS_DIR, ctxid, "chat.json")
    if not os.path.isfile(chat_file):
        return None
    try:
        with open(chat_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_chat_data(ctxid: str, data: dict) -> None:
    """Save chat.json data for a context."""
    chat_file = os.path.join(CHATS_DIR, ctxid, "chat.json")
    try:
        with open(chat_file, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        log.warning(f"[PRUNE] Failed to save {chat_file}: {e}")


def _prune_all_chats():
    """Scan all chats and prune stale hierarchy references."""
    if not os.path.isdir(CHATS_DIR):
        return

    total_pruned_parents = 0
    total_pruned_children = 0
    dead_names = []

    for entry in os.listdir(CHATS_DIR):
        if entry.startswith("_") or entry.startswith("."):
            continue
        chat_dir = os.path.join(CHATS_DIR, entry)
        if not os.path.isdir(chat_dir):
            continue

        data = _load_chat_data(entry)
        if not data or not isinstance(data, dict):
            continue

        ctx_data = data.get("data", {})
        if not isinstance(ctx_data, dict):
            continue

        modified = False

        # Prune stale sup_parent
        sup_parent = ctx_data.get("sup_parent")
        if sup_parent and not _context_exists_on_disk(sup_parent):
            log.warning(f"[PRUNE] Context '{entry}': clearing stale sup_parent '{sup_parent}'")
            ctx_data.pop("sup_parent", None)
            modified = True
            total_pruned_parents += 1

        # Prune stale sup_children
        sup_children = ctx_data.get("sup_children", [])
        if sup_children:
            alive = []
            for child in sup_children:
                child_id = child.get("ctxid", "")
                if _context_exists_on_disk(child_id):
                    alive.append(child)
                else:
                    name = child.get("name", "")
                    log.warning(f"[PRUNE] Context '{entry}': removing dead child '{child_id}' (name='{name}')")
                    if name:
                        dead_names.append(name)
                    total_pruned_children += 1

            if len(alive) < len(sup_children):
                ctx_data["sup_children"] = alive
                modified = True

        if modified:
            data["data"] = ctx_data
            _save_chat_data(entry, data)

    # Prune root order
    _prune_root_order()

    # Unregister dead names
    if dead_names:
        try:
            from usr.plugins.a0_superordinates.helpers.name_registry import unregister_name
            for name in dead_names:
                unregister_name(name)
        except Exception as e:
            log.warning(f"[PRUNE] Failed to unregister dead names: {e}")

    # Clean name registry of dead entries
    try:
        from usr.plugins.a0_superordinates.helpers.name_registry import cleanup_dead
        cleanup_dead()
    except Exception as e:
        log.warning(f"[PRUNE] Failed to cleanup name registry: {e}")

    if total_pruned_parents or total_pruned_children:
        log.warning(f"[PRUNE] Startup cleanup: pruned {total_pruned_parents} stale parents, {total_pruned_children} stale children")
    else:
        log.info("[PRUNE] Startup cleanup: no stale hierarchy references found")


def _prune_root_order():
    """Remove non-existent context IDs from _sup_root_order.dat."""
    if not os.path.isfile(ROOT_ORDER_FILE):
        return
    try:
        with open(ROOT_ORDER_FILE, "r") as f:
            order = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    if not isinstance(order, list):
        return

    pruned = [ctxid for ctxid in order if _context_exists_on_disk(ctxid)]
    if len(pruned) < len(order):
        removed = set(order) - set(pruned)
        log.warning(f"[PRUNE] Root order: removed {len(removed)} stale entries: {removed}")
        try:
            with open(ROOT_ORDER_FILE, "w") as f:
                json.dump(pruned, f)
        except OSError as e:
            log.warning(f"[PRUNE] Failed to save root order: {e}")


class PruneStaleHierarchy(Extension):

    def execute(self, **kwargs):
        _migrate_legacy_root_order()
        _prune_all_chats()
