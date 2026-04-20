### superordinate_spawn
create a new persistent superordinate agent with its own visible chat context.
args: `profile`, `message`, `name`
- `profile`: agent profile name (developer, researcher, hacker, agent0, default, or custom) — determines the agent's specialization
- `message`: initial task message to send to the superordinate
- `name`: optional unique display name for the superordinate chat — if omitted, a human-friendly name starting with the same first letter as the profile is auto-generated (e.g. developer → Devvy, researcher → Rex, hacker → Hack)
the superordinate runs independently in its own chat context.
example with auto-name:
~~~json
{
  "thoughts": ["I need a developer superordinate for this coding task."],
  "headline": "Spawning developer superordinate",
  "tool_name": "superordinate_spawn",
  "tool_args": {
    "profile": "developer",
    "message": "Build a REST API with FastAPI that manages a todo list."
  }
}
~~~
example with explicit name:
~~~json
{
  "thoughts": ["I need a researcher superordinate named Ruby."],
  "headline": "Spawning researcher superordinate",
  "tool_name": "superordinate_spawn",
  "tool_args": {
    "profile": "researcher",
    "message": "Research AI trends.",
    "name": "Ruby"
  }
}
~~~
{{if agent_profiles}}
available profiles: {{agent_profiles}}
{{endif}}
