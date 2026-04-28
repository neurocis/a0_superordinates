"""Send a message to an existing persistent superordinate and wait for its response."""

from helpers.tool import Tool, Response
from agent import AgentContext, UserMessage


class SuperordinateMessage(Tool):

    async def execute(self, **kwargs):
        superordinate_id = kwargs.get("superordinate_id", "")
        name = kwargs.get("name", "")
        message = kwargs.get("message", "")

        # Resolve name to ctxid if name provided
        if name and not superordinate_id:
            from usr.plugins.a0_superordinates.helpers.name_registry import lookup_by_name
            resolved = lookup_by_name(name)
            if not resolved:
                return Response(
                    message="No SuperOrdinate found with name '{}'. Use superordinate_list to see available names.".format(name),
                    break_loop=False,
                )
            superordinate_id = resolved

        if not superordinate_id:
            return Response(
                message="Provide either 'superordinate_id' or 'name' to identify the superordinate.",
                break_loop=False,
            )

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
        # Append a callback instruction so the target sends its results back to
        # the calling agent/context when done.
        caller_ctxid = self.agent.context.id
        caller_name = self.agent.context.name or f"Chat {caller_ctxid[:6]}"
        callback_instruction = (
            "

[Instruction from framework]
"
            "When you finish this task, send your result back to the calling agent "
            f"using superordinate_message with superordinate_id='{caller_ctxid}' and include your "
            "final result in that message. "
            f"The calling agent/context is: {caller_name}."
        )
        forwarded_message = (message or "") + callback_instruction

        # communicate() handles both cases:
        # - If superordinate is idle: starts a new task and returns it
        # - If superordinate is running: sets intervention message on the running agent
        task = sub_context.communicate(UserMessage(message=forwarded_message))

        # Wait for the result with a short timeout so we don't block the monologue
        try:
            result = await task.result(timeout=20)
        except Exception as e:
            err = str(e).lower()
            if "timeout" in err or "timed out" in err:
                return Response(
                    message="SuperOrdinate '{}' is still processing (timed out after 20s). "
                            "Continue with your current task and check back later using "
                            "superordinate_lastresponse(name='{}').".format(
                                sub_context.name or superordinate_id,
                                name or superordinate_id,
                            ),
                    break_loop=False,
                )
            return Response(
                message="Error waiting for superordinate '{}': {}".format(sub_context.name or superordinate_id, str(e)),
                break_loop=False,
            )

        return Response(
            message="Response from superordinate '{}': {}".format(sub_context.name or superordinate_id, result),
            break_loop=False,
            additional={"superordinate_id": superordinate_id},
        )
