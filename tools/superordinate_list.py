"""List visible persistent superordinate relationships for the current context.

Visibility follows the same relationship settings as ``superordinate_message``:
- descendants are always visible (original/core behavior)
- parent/ancestor visibility follows ``allow_parent_messaging``
- sibling visibility follows ``allow_sibling_messaging``
"""

from helpers.tool import Tool, Response
from agent import AgentContext


def _get_config(agent) -> dict:
    """Read a0_superordinates config, falling back safely to defaults."""
    try:
        from helpers import plugins
        config = plugins.get_plugin_config("a0_superordinates", agent=agent) or {}
        return config if isinstance(config, dict) else {}
    except Exception:
        return {}


def _setting_enabled(config: dict, key: str, default: bool = True) -> bool:
    """Return boolean config value with permissive string handling."""
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


class SuperordinateList(Tool):

    async def execute(self, **kwargs):
        config = _get_config(self.agent)
        show_parents = _setting_enabled(config, "allow_parent_messaging", True)
        show_siblings = _setting_enabled(config, "allow_sibling_messaging", True)

        sections = []
        alive_count = 0

        if show_parents:
            parent_lines = []
            parent_alive = self._collect_ancestors(self.agent.context, parent_lines)
            if parent_lines:
                sections.append(
                    "Parent / ancestor superordinates (visible; parent messaging enabled):\n{}".format(
                        "\n".join(parent_lines)
                    )
                )
                alive_count += parent_alive

        if show_siblings:
            sibling_lines = []
            sibling_alive = self._collect_siblings(self.agent.context, sibling_lines)
            if sibling_lines:
                sections.append(
                    "Sibling superordinates (visible; sibling messaging enabled):\n{}".format(
                        "\n".join(sibling_lines)
                    )
                )
                alive_count += sibling_alive

        children = self.agent.context.data.get("sup_children", []) or []
        descendant_lines = []
        self._collect_tree(self.agent.context, children, descendant_lines, depth=0)
        descendant_alive = sum(
            1 for line in descendant_lines
            if "(status: running)" in line or "(status: idle)" in line
        )
        if descendant_lines:
            sections.append(
                "Descendant superordinates (children/grandchildren; always visible):\n{}".format(
                    "\n".join(descendant_lines)
                )
            )
            alive_count += descendant_alive

        if not sections:
            disabled_notes = []
            if not show_parents:
                disabled_notes.append("parent/ancestor visibility disabled")
            if not show_siblings:
                disabled_notes.append("sibling visibility disabled")
            suffix = ""
            if disabled_notes:
                suffix = " ({}).".format(", ".join(disabled_notes))
            return Response(
                message="No visible persistent superordinates found{}".format(suffix),
                break_loop=False,
            )

        settings_note = (
            "Visibility: descendants always shown; parent/ancestor visibility is {}; "
            "sibling visibility is {}."
        ).format("enabled" if show_parents else "disabled", "enabled" if show_siblings else "disabled")

        result = (
            "Visible persistent superordinates ({} alive):\n{}"
            "\n\n{}"
            "\n\nReference visible superordinates by name using "
            "superordinate_message with the 'name' arg."
        ).format(alive_count, "\n\n".join(sections), settings_note)
        return Response(message=result, break_loop=False)

    def _collect_ancestors(self, ctx, lines, max_depth=64):
        """Collect parent, grandparent, ... lines for the current context."""
        alive_count = 0
        current = ctx
        seen = set()
        depth = 0

        while current and depth < max_depth:
            if current.id in seen:
                break
            seen.add(current.id)

            parent_id = current.data.get("sup_parent")
            if not parent_id:
                break

            parent_ctx = AgentContext.get(parent_id)
            if not parent_ctx:
                lines.append(
                    "{}'{}'  (id: {}, profile: {}, status: closed, relationship: {})".format(
                        "  " * depth + "- ",
                        self._lookup_child_name(parent_id, current.id) or f"Chat {parent_id[:6]}",
                        parent_id,
                        "unknown",
                        "parent" if depth == 0 else "ancestor",
                    )
                )
                break

            status = "running" if parent_ctx.is_running() else "idle"
            alive_count += 1
            lines.append(
                "{}'{}'  (id: {}, profile: {}, status: {}, relationship: {})".format(
                    "  " * depth + "- ",
                    parent_ctx.name or f"Chat {parent_id[:6]}",
                    parent_id,
                    parent_ctx.data.get("sup_profile", "default"),
                    status,
                    "parent" if depth == 0 else "ancestor",
                )
            )

            current = parent_ctx
            depth += 1

        return alive_count

    def _collect_siblings(self, ctx, lines):
        """Collect sibling lines from the current context's immediate parent."""
        parent_id = ctx.data.get("sup_parent")
        if not parent_id:
            return 0

        parent_ctx = AgentContext.get(parent_id)
        if not parent_ctx:
            return 0

        alive = []
        children = parent_ctx.data.get("sup_children", []) or []
        alive_count = 0

        for child in children:
            ctxid = child.get("ctxid", "") if isinstance(child, dict) else ""
            if not ctxid or ctxid == ctx.id:
                if ctxid == ctx.id:
                    alive.append(child)
                continue

            name = child.get("name", "Unnamed") if isinstance(child, dict) else "Unnamed"
            profile = child.get("profile", "default") if isinstance(child, dict) else "default"
            created_at = child.get("created_at", "unknown") if isinstance(child, dict) else "unknown"

            sibling_ctx = AgentContext.get(ctxid)
            if sibling_ctx:
                status = "running" if sibling_ctx.is_running() else "idle"
                alive.append(child)
                alive_count += 1
            else:
                status = "closed"

            lines.append(
                "- '{}'  (id: {}, profile: {}, status: {}, relationship: sibling, created: {})".format(
                    name, ctxid, profile, status, created_at
                )
            )

        # Prune dead sibling entries from the parent's list, preserving this context.
        if len(alive) < len(children):
            parent_ctx.data["sup_children"] = alive
            self._prune_names(children, alive)

        return alive_count

    def _lookup_child_name(self, parent_id, child_id):
        """Best-effort lookup of a child's cached name in a parent's sup_children list."""
        parent_ctx = AgentContext.get(parent_id)
        if not parent_ctx:
            return ""
        for child in parent_ctx.data.get("sup_children", []) or []:
            if isinstance(child, dict) and child.get("ctxid") == child_id:
                return child.get("name", "")
        return ""

    def _collect_tree(self, owner_ctx, children, lines, depth):
        """Recursively collect descendant tree lines and prune dead entries.

        Args:
            owner_ctx: The AgentContext whose sup_children list we are iterating.
            children: The sup_children list from owner_ctx.data.
            lines: Accumulator for formatted output lines.
            depth: Current tree depth (for indentation).
        """
        prefix = "  " * depth + "- "
        alive = []

        for child in children:
            ctxid = child.get("ctxid", "")
            name = child.get("name", "Unnamed")
            profile = child.get("profile", "default")
            created_at = child.get("created_at", "unknown")

            # Check if context still exists
            sub_ctx = AgentContext.get(ctxid)
            if sub_ctx:
                status = "running" if sub_ctx.is_running() else "idle"
                alive.append(child)
            else:
                status = "closed"

            lines.append(
                "{}'{}'  (id: {}, profile: {}, status: {}, relationship: descendant, created: {})".format(
                    prefix, name, ctxid, profile, status, created_at
                )
            )

            # Recurse into this child's own children if context exists
            if sub_ctx:
                grandchildren = sub_ctx.data.get("sup_children", [])
                if grandchildren:
                    self._collect_tree(sub_ctx, grandchildren, lines, depth + 1)

        # Prune dead children at this level
        if len(alive) < len(children):
            owner_ctx.data["sup_children"] = alive
            self._prune_names(children, alive)

    def _prune_names(self, children, alive):
        """Unregister names of dead children."""
        try:
            from usr.plugins.a0_superordinates.helpers.name_registry import unregister_name
            for child in children:
                if child not in alive:
                    unregister_name(child.get("name", ""))
        except Exception:
            pass
