"""Create a persistent superordinate agent with its own AgentContext."""

from helpers.tool import Tool, Response
from agent import AgentContext, UserMessage
from initialize import initialize_agent
from helpers import guids, projects
from helpers.state_monitor_integration import mark_dirty_all


class SuperordinateSpawn(Tool):

    async def execute(self, **kwargs):
        name = kwargs.get("name", "Superordinate")
        profile = kwargs.get("profile", "")
        message = kwargs.get("message", "")

        # Check for duplicate name
        from usr.plugins.a0_superordinates.helpers.name_registry import name_exists, register_name
        if name_exists(name):
            return Response(
                message="A SuperOrdinate named '{}' already exists. Please choose a different name.".format(name),
                break_loop=False,
            )

        # Generate new context ID
        new_ctxid = guids.generate_id()

        # Register name BEFORE creating context (so we don't leak if something fails)
        if not register_name(name, new_ctxid):
            return Response(
                message="Failed to register name '{}'. It may have just been taken.".format(name),
                break_loop=False,
            )

        # Create config and set profile BEFORE creating context
        config = initialize_agent()
        if profile:
            config.profile = profile

        # Create new AgentContext with its own config
        # Set display name as "Name (Role)" for the chat
        profile_role = profile or "default"
        display_name = "{} ({})".format(name, profile_role)
        new_context = AgentContext(config=config, id=new_ctxid, name=display_name)

        # Store hierarchy metadata on child
        new_context.data["sup_parent"] = self.agent.context.id
        new_context.data["sup_profile"] = profile or "default"

        # Store hierarchy metadata on parent
        from usr.plugins.a0_superordinates.helpers.hierarchy import add_child
        add_child(self.agent.context.id, new_ctxid, profile or "default", name)

        # Copy project data from parent to child (same pattern as chat_create.py)
        proj_data = self.agent.context.get_data(projects.CONTEXT_DATA_KEY_PROJECT)
        if proj_data:
            new_context.set_data(projects.CONTEXT_DATA_KEY_PROJECT, proj_data)
        proj_output = self.agent.context.get_output_data(projects.CONTEXT_DATA_KEY_PROJECT)
        if proj_output:
            new_context.set_output_data(projects.CONTEXT_DATA_KEY_PROJECT, proj_output)

        # Send initial message to superordinate (fire and forget)
        new_context.communicate(UserMessage(message=message))

        # Trigger UI refresh so the new chat appears in sidebar
        mark_dirty_all(reason="superordinate_spawn")

        return Response(
            message="Persistent superordinate '{}' created with context ID {}. Profile: {}. The superordinate is running independently in its own chat context. You can reference it by name: '{}'".format(
                name, new_ctxid, profile or "default", name
            ),
            break_loop=False,
            additional={"superordinate_id": new_ctxid, "profile": profile or "default", "name": name},
        )
