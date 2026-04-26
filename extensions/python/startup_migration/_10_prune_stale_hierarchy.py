"""Startup pruning of stale hierarchy references.

Runs once at framework startup. Scans all chat directories on disk and:
- Removes sup_parent references to non-existent contexts
- Prunes sup_children entries pointing to non-existent contexts
- Cleans _sup_root_order.json of non-existent context IDs
- Unregisters dead names from the name registry
"""

import json
import os
import sys
import logging
import traceback

from helpers.extension import Extension

log = logging.getLogger("a0.superordinates.startup_prune")

CHATS_DIR = "/a0/usr/chats"
ROOT_ORDER_FILE = os.path.join(CHATS_DIR, "_sup_root_order.json")

# DEBUG: install a process-wide audit hook to trace writes to ROOT_ORDER_FILE
_AUDIT_INSTALLED = False


def _install_write_audit_hook():
    global _AUDIT_INSTALLED
    if _AUDIT_INSTALLED:
        return
    _AUDIT_INSTALLED = True

    def _audit(event, args):
        try:
            if event == "open":
                path = args[0] if args else None
                mode = args[1] if len(args) > 1 else None
                if isinstance(path, str) and path.endswith("_sup_root_order.json") and isinstance(mode, str) and ("w" in mode or "a" in mode):
                    from datetime import datetime as _dt
                    stack = "".join(traceback.format_stack(limit=30))
                    with open("/tmp/sup_map_debug.log", "a") as _df:
                        _df.write(f"\n!!! AUDIT WRITE EVENT {_dt.now().isoformat()} mode={mode} path={path} !!!\n")
                        _df.write(stack)
                        _df.write("!!! END AUDIT !!!\n\n")
        except Exception:
            pass

    try:
        sys.addaudithook(_audit)
    except Exception:
        pass


_install_write_audit_hook()


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
    """Remove non-existent context IDs from _sup_root_order.json."""
    # DEBUG: log everything we see and do
    def _dbg(msg):
        try:
            from datetime import datetime as _dt
            with open('/tmp/sup_map_debug.log', 'a') as _df:
                _df.write(f"[PRUNE {_dt.now().isoformat()}] {msg}\n")
        except Exception:
            pass

    if not os.path.isfile(ROOT_ORDER_FILE):
        _dbg(f"file does not exist: {ROOT_ORDER_FILE}")
        return
    try:
        with open(ROOT_ORDER_FILE, "r") as f:
            order = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _dbg(f"failed to load file: {e}")
        return

    _dbg(f"loaded order: {order}")

    if not isinstance(order, list):
        _dbg(f"order is not a list, skipping")
        return

    # Check existence for each ctxid and log
    existence_check = {ctxid: _context_exists_on_disk(ctxid) for ctxid in order}
    _dbg(f"existence check: {existence_check}")

    pruned = [ctxid for ctxid in order if _context_exists_on_disk(ctxid)]
    _dbg(f"pruned result: {pruned} (len={len(pruned)} vs order len={len(order)})")

    if len(pruned) < len(order):
        removed = set(order) - set(pruned)
        log.warning(f"[PRUNE] Root order: removed {len(removed)} stale entries: {removed}")
        _dbg(f"WRITING file with pruned: {pruned}")
        try:
            with open(ROOT_ORDER_FILE, "w") as f:
                json.dump(pruned, f)
        except OSError as e:
            log.warning(f"[PRUNE] Failed to save root order: {e}")
            _dbg(f"OSError on write: {e}")
    else:
        _dbg("no changes needed, NOT writing file")


class PruneStaleHierarchy(Extension):

    def execute(self, **kwargs):
        _prune_all_chats()
