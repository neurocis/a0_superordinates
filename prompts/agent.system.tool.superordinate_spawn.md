### superordinate_spawn
create a new persistent superordinate agent with its own visible chat context.
args: `name`, `profile`, `message`
- `name`: display name for the superordinate chat
- `profile`: agent profile name (developer, researcher, hacker, or custom)
- `message`: initial task message to send to the superordinate
the superordinate runs independently in its own chat context.
example:
~~~json
{
  "thoughts": ["I need a developer superordinate for this coding task."],
  "headline": "Spawning developer superordinate",
  "tool_name": "superordinate_spawn",
  "tool_args": {
    "name": "Code Builder",
    "profile": "developer",
    "message": "Build a REST API with FastAPI that manages a todo list."
  }
}
~~~
{{if agent_profiles}}
available profiles: {{agent_profiles}}
{{endif}}
