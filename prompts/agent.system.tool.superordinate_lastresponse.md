### superordinate_lastresponse
retrieve responses from a persistent superordinate's chat log. reads directly from disk — does not block or await any current processing.
args: `name` or `superordinate_id`, optional `count`, optional `with_prompts`
- `name`: the unique name of the superordinate (preferred)
- `superordinate_id`: the context ID of the superordinate (alternative to name)
- `count`: how many entries to retrieve (default `-1`)
  - `-1`: last entry only (default)
  - `0`: all entries in the chat
  - `N`: last N entries
- `with_prompts`: when `true`, return paired user-prompt + response cycles instead of responses only (default `false`)
behavior:
- default mode (`with_prompts=false`): walks `type=response` log entries and returns the response text only
- paired mode (`with_prompts=true`): walks the chat log in order, pairs each `response` with the most recent preceding `user` prompt, and returns them as `[USER]` / `[RESPONSE]` cycles
returns response (or cycle) entries from the superordinate's chat. if no responses yet, indicates the superordinate may still be processing.
example:
~~~json
{
  "thoughts": ["I want to check what Devvy last responded with."],
  "headline": "Getting last response from superordinate",
  "tool_name": "superordinate_lastresponse",
  "tool_args": {
    "name": "Devvy"
  }
}
~~~
example with count:
~~~json
{
  "thoughts": ["I want to see all of Devvy's responses."],
  "headline": "Getting all responses from superordinate",
  "tool_name": "superordinate_lastresponse",
  "tool_args": {
    "name": "Devvy",
    "count": "0"
  }
}
~~~
example with paired prompts:
~~~json
{
  "thoughts": ["I want the last 3 prompt+response cycles to review the conversation flow."],
  "headline": "Getting paired prompt+response cycles",
  "tool_name": "superordinate_lastresponse",
  "tool_args": {
    "name": "Devvy",
    "count": "3",
    "with_prompts": "true"
  }
}
~~~
