"""Send a message to an existing persistent superordinate and wait for its response."""

from helpers.tool import Tool, Response
from agent import AgentContext, UserMessage


class SuperordinateMessage(Tool):

    async def execute(self, **kwargs):
        superordinate_id = kwargs.get("superordinate_id", "")
        message = kwargs.get("message", "")

        # Get superordinate context
        sub_context = AgentContext.get(superordinate_id)
        if not sub_context:
            return Response(
                message="Superordinate context '{}' not found. It may have been closed.".format(superordinate_id),
                break_loop=False,
            )

        # Verify it is actually a child of current context
        parent_id = sub_context.data.get("sup_parent")
        if parent_id != self.agent.context.id:
            return Response(
                message="Context '{}' is not a superordinate of this context.".format(superordinate_id),
                break_loop=False,
            )

        # Send message to superordinate
        # communicate() handles both cases:
        # - If superordinate is idle: starts a new task and returns it
        # - If superordinate is running: sets intervention message on the running agent
        task = sub_context.communicate(UserMessage(message=message))

        # Wait for the result (with timeout handling)
        try:
            result = await task.result(timeout=300)  # 5 minute timeout
        except Exception as e:
            return Response(
                message="Error waiting for superordinate '{}': {}".format(sub_context.name or superordinate_id, str(e)),
                break_loop=False,
            )

        return Response(
            message="Response from superordinate '{}': {}".format(sub_context.name or superordinate_id, result),
            break_loop=False,
            additional={"superordinate_id": superordinate_id},
        )
