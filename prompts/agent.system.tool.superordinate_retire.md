### superordinate_retire
retire (close) a persistent superordinate. mirrors the UI close-chat behavior — moves the agent under the 'Closed Chats' folder.
args: `name` or `superordinate_id`
- `name`: the unique name of the superordinate (preferred — easier to reference)
- `superordinate_id`: the context ID of the superordinate (alternative to name)
behavior:
- normal chat → moved under the 'Closed Chats' folder (created at root if missing)
- already under 'Closed Chats' → permanently deleted
- the 'Closed Chats' folder itself → folder and every descendant permanently deleted
example:
~~~json
{
  "thoughts": ["Devvy is done; I'll retire that superordinate."],
  "headline": "Retiring superordinate by name",
  "tool_name": "superordinate_retire",
  "tool_args": {
    "name": "Devvy"
  }
}
~~~
example by id:
~~~json
{
  "thoughts": ["Retire by raw context id."],
  "headline": "Retiring superordinate by id",
  "tool_name": "superordinate_retire",
  "tool_args": {
    "superordinate_id": "abc123XY"
  }
}
~~~
