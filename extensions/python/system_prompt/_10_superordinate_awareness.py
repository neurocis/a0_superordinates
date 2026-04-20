"""Inject prompt content about persistent superordinates into the agent's system prompt."""

from typing import Any
from helpers.extension import Extension
from agent import Agent, LoopData


class SuperordinateAwareness(Extension):

    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent:
            return
        context = self.agent.context

        parts = []

        # If this is a superordinate
        parent_id = context.data.get("sup_parent")
        if parent_id:
            parts.append(
                "## Superordinate Status\n"
                "You are a persistent superordinate agent. Your parent context is `{}`. "
                "You can receive messages from your parent and respond independently. "
                "Users can also chat with you directly in the UI.".format(parent_id)
            )

        # If this has superordinates
        children = context.data.get("sup_children", [])
        if children:
            sub_list = "\n".join(
                "- '{}' (profile: {})".format(c["name"], c["profile"])
                for c in children
            )
            parts.append(
                "## Persistent Superordinates\n"
                "You have {} persistent superordinate(s):\n{}\n"
                "Use `superordinate_message` with the `name` arg to communicate with them by name. "
                "Use `superordinate_list` to check their status.".format(
                    len(children), sub_list
                )
            )

        if parts:
            content = "\n\n".join(parts)
            loop_data.extras_persistent["superordinate_awareness"] = {
                "type": "text",
                "text": content,
            }
