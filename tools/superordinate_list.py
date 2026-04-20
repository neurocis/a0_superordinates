"""List all persistent superordinates of the current context."""

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

            lines.append("- '{}' (id: {}, profile: {}, status: {}, created: {})".format(
                name, ctxid, profile, status, created_at
            ))

        # Prune dead children and clean up name registry
        if len(alive) < len(children):
            self.agent.context.data["sup_children"] = alive
            from usr.plugins.a0_superordinates.helpers.name_registry import unregister_name
            for child in children:
                if child not in alive:
                    unregister_name(child.get("name", ""))

        result = "Persistent superordinates ({}):\n{}\n\nReference superordinates by name using superordinate_message with the 'name' arg.".format(
            len(alive), "\n".join(lines)
        )
        return Response(message=result, break_loop=False)
