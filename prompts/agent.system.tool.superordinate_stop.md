### superordinate_stop
stop a persistent superordinate from further processing. mirrors the UI stop behavior — kills any currently running monologue/task on the named superordinate without resetting chat history.
args: `name` or `superordinate_id`
- `name`: the unique name of the superordinate (preferred — easier to reference)
- `superordinate_id`: the context ID of the superordinate (alternative to name)
behavior:
- target was running → its task is killed and the agent goes idle
- target was already idle → safe no-op, returns notice that nothing was running
- chat history and context state are preserved (use superordinate_retire to close)
example:
~~~json
{
  "thoughts": ["Devvy is stuck in a loop; I'll stop further processing."],
  "headline": "Stopping superordinate by name",
  "tool_name": "superordinate_stop",
  "tool_args": {
    "name": "Devvy"
  }
}
~~~
example by id:
~~~json
{
  "thoughts": ["Stop by raw context id."],
  "headline": "Stopping superordinate by id",
  "tool_name": "superordinate_stop",
  "tool_args": {
    "superordinate_id": "abc123XY"
  }
}
~~~
