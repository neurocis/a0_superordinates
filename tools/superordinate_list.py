"""List all persistent superordinates of the current context, including all descendants."""

from helpers.tool import Tool, Response
from agent import AgentContext


class SuperordinateList(Tool):

    async def execute(self, **kwargs):
        children = self.agent.context.data.get("sup_children", [])

        if not children:
            return Response(
                message="No persistent superordinates found.",
                break_loop=False,
            )

        lines = []
        self._collect_tree(self.agent.context, children, lines, depth=0)

        alive_count = sum(
            1 for l in lines
            if "(status: running)" in l or "(status: idle)" in l
        )

        result = (
            "Persistent superordinates ({} alive):\n{}"
            "\n\nReference superordinates by name using "
            "superordinate_message with the 'name' arg."
        ).format(alive_count, "\n".join(lines))
        return Response(message=result, break_loop=False)

    def _collect_tree(self, owner_ctx, children, lines, depth):
        """Recursively collect tree lines and prune dead entries.

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
                "{}'{}'  (id: {}, profile: {}, status: {}, created: {})".format(
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
