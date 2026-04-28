"""Inject AGENT_SELF_NAME into read_prompt kwargs so prompt templates can
reference the spawned superordinate's assigned name (e.g. 'Devvy') instead
of falling back to 'Agent Zero'.

Uses agent.context.name (the display name, e.g. 'Devvy (Developer)') because
it is available at the moment agent_init fires (passed via AgentContext
constructor's name= argument). The context.data['sup_name'] is set by
superordinate_spawn AFTER the AgentContext is constructed, so it is not yet
available when the initial_message extension renders fw.initial_message.md.

Falls back to 'Agent Zero' for non-superordinate contexts.
"""

from helpers.extension import Extension


class InjectSelfName(Extension):

    def execute(self, **kwargs):
        data = kwargs.get("data")
        if not data:
            return

        agent = self.agent
        if not agent or not getattr(agent, "context", None):
            return

        # Resolve self-name: prefer sup_name (post-init), fall back to parsed
        # context.name (available during agent_init), else 'Agent Zero'.
        ctx = agent.context
        ctx_data = getattr(ctx, "data", None) or {}
        self_name = ctx_data.get("sup_name")
        if not self_name:
            ctx_name = getattr(ctx, "name", "") or ""
            if ctx_name and "(" in ctx_name:
                self_name = ctx_name.split("(", 1)[0].strip()
            elif ctx_name:
                self_name = ctx_name.strip()
        if not self_name:
            self_name = "Agent Zero"

        prompt_kwargs = data.get("kwargs")
        if isinstance(prompt_kwargs, dict):
            prompt_kwargs.setdefault("AGENT_SELF_NAME", self_name)
