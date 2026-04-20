"""Clean up dead SuperOrdinate references before each monologue.

When a chat is closed/killed, the parent still has stale references in
sup_children and the name registry. This extension prunes dead entries
at the start of every agent turn, ensuring the hierarchy stays consistent.
"""

import os
from helpers.extension import Extension
from agent import Agent, LoopData
from helpers.state_monitor_integration import mark_dirty_all


def _context_alive(ctxid: str) -> bool:
    """Check if a context still exists (in memory or on disk)."""
    from agent import AgentContext
    if AgentContext.get(ctxid) is not None:
        return True
    chat_file = os.path.join("/a0/usr/chats", ctxid, "chat.json")
    return os.path.isfile(chat_file)


def _cleanup_children(context) -> list[str]:
    """Remove dead children from sup_children and unregister their names.
    Returns list of removed child names."""
    children = context.data.get("sup_children", [])
    if not children:
        return []

    alive = []
    removed_names = []
    for child in children:
        ctxid = child.get("ctxid", "")
        if _context_alive(ctxid):
            alive.append(child)
        else:
            name = child.get("name", "")
            removed_names.append(name)

    if len(alive) < len(children):
        context.data["sup_children"] = alive
        # Unregister dead names
        try:
            from usr.plugins.a0_superordinates.helpers.name_registry import unregister_name
            for name in removed_names:
                if name:
                    unregister_name(name)
        except Exception:
            pass

    return removed_names


def _cleanup_parent(context) -> bool:
    """If this context's parent is dead, clear the parent reference.
    Returns True if parent was cleaned."""
    parent_id = context.data.get("sup_parent")
    if not parent_id:
        return False

    if not _context_alive(parent_id):
        context.data.pop("sup_parent", None)
        return True

    return False


def _cleanup_name_registry():
    """Remove name registry entries whose contexts no longer exist."""
    try:
        from usr.plugins.a0_superordinates.helpers.name_registry import cleanup_dead
        cleanup_dead()
    except Exception:
        pass


class SuperordinateCleanup(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        context = self.agent.context
        dirty = False

        # Clean up dead children
        removed = _cleanup_children(context)
        if removed:
            dirty = True

        # Clean up dead parent reference
        if _cleanup_parent(context):
            dirty = True

        # Periodically clean the global name registry
        _cleanup_name_registry()

        # Trigger UI refresh if anything changed
        if dirty:
            mark_dirty_all(reason="superordinate_cleanup")
