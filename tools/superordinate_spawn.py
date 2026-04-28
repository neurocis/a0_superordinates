"""Create a persistent superordinate agent with its own AgentContext."""

from helpers.tool import Tool, Response
from agent import AgentContext, UserMessage
from initialize import initialize_agent
from helpers import guids, projects
from helpers.state_monitor_integration import mark_dirty_all

# Human-friendly name pools, keyed by first letter of profile
NAME_POOLS = {
    "d": ["Devvy", "Dexter", "Dana", "Dax", "Dara", "Delphi", "Drake", "Dusk"],
    "r": ["Rex", "Ruby", "Remy", "Rowan", "Raven", "Rhea", "Rio", "Rigel"],
    "h": ["Hack", "Harley", "Hazel", "Hunter", "Hex", "Hawk", "Hera", "Haze"],
    "a": ["Axel", "Ada", "Ash", "Aura", "Atlas", "Aero", "Abel", "Azura"],
}


def _generate_name(profile: str) -> str:
    """Auto-generate a human-friendly name starting with the same letter as the profile.
    Picks the first unused name from the pool, or appends a number if all taken."""
    from usr.plugins.a0_superordinates.helpers.name_registry import name_exists

    letter = (profile or "d")[0].lower()
    pool = NAME_POOLS.get(letter, [])

    # Try each name in the pool until we find one that's not taken
    for candidate in pool:
        if not name_exists(candidate):
            return candidate

    # All pool names taken — append incrementing number
    base = (pool[0] if pool else profile.capitalize())
    n = 2
    while name_exists("{}{}".format(base, n)):
        n += 1
    return "{}{}".format(base, n)


class SuperordinateSpawn(Tool):

    async def execute(self, **kwargs):
        requested_profile = (kwargs.get("profile", "") or "").strip()
        parent_ctx = self.agent.context
        inherited_profile = (
            parent_ctx.data.get("sup_profile")
            or (parent_ctx.config.profile if parent_ctx.config else "")
            or "agent0"
        )
        profile = requested_profile if requested_profile and requested_profile != "default" else inherited_profile
        name = kwargs.get("name", "")
        message = kwargs.get("message", "")

        # Auto-generate name if not provided
        if not name:
            name = _generate_name(profile)
        else:
            # Check for duplicate name when explicitly provided
            from usr.plugins.a0_superordinates.helpers.name_registry import name_exists
            if name_exists(name):
                return Response(
                    message="A SuperOrdinate named '{}' already exists. Please choose a different name.".format(name),
                    break_loop=False,
                )

        # Generate new context ID
        new_ctxid = guids.generate_id()

        # Register name BEFORE creating context
        from usr.plugins.a0_superordinates.helpers.name_registry import register_name
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
        display_name = "{} ({})".format(name, profile.capitalize())
        new_context = AgentContext(config=config, id=new_ctxid, name=display_name)

        # Store hierarchy metadata on child
        new_context.data["sup_parent"] = self.agent.context.id
        new_context.data["sup_profile"] = profile


        # Inherit parent's LLM Profile (chat_model_override) so child uses same model
        parent_model_override = self.agent.context.data.get("chat_model_override")
        if parent_model_override:
            new_context.data["chat_model_override"] = parent_model_override

        # Lock the chat name to prevent chat_rename plugin from overriding it
        new_context.data["chat_rename_manual_lock"] = True
        # Store hierarchy metadata on parent
        from usr.plugins.a0_superordinates.helpers.hierarchy import add_child
        add_child(self.agent.context.id, new_ctxid, profile, name)

        # Copy project data from parent to child (same pattern as chat_create.py)
        proj_data = self.agent.context.get_data(projects.CONTEXT_DATA_KEY_PROJECT)
        if proj_data:
            new_context.set_data(projects.CONTEXT_DATA_KEY_PROJECT, proj_data)
        proj_output = self.agent.context.get_output_data(projects.CONTEXT_DATA_KEY_PROJECT)
        if proj_output:
            new_context.set_output_data(projects.CONTEXT_DATA_KEY_PROJECT, proj_output)

        # Send initial message to superordinate (fire and forget)
        if message:
            new_context.communicate(UserMessage(message=message))

        # Trigger UI refresh so the new chat appears in sidebar
        mark_dirty_all(reason="superordinate_spawn")

        return Response(
            message="Persistent superordinate '{}' created with context ID {}. Profile: {}. The superordinate is running independently in its own chat context. You can reference it by name: '{}'".format(
                name, new_ctxid, profile, name
            ),
            break_loop=False,
            additional={"superordinate_id": new_ctxid, "profile": profile, "name": name},
        )
