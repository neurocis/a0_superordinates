### superordinate_getresponse
retrieve responses from a persistent superordinate's chat log. reads directly from disk — does not block or await any current processing.
args: `name` or `superordinate_id`, optional `count`, optional `with_prompts`
- `name`: the unique name of the superordinate (preferred)
- `superordinate_id`: the context ID of the superordinate (alternative to name)
- `count`: how many entries to retrieve (default `-1`)
  - `-1`: last response only, response text only by default
  - `0`: all prompt+response cycles by default
  - `N`: last N responses, response text only by default
  - `-N` where `N > 1`: last N prompt+response cycles by default (for example, `-3` means last 3 cycles with prompts)
- `with_prompts`: optional override. when explicitly `true`, return paired user-prompt + response cycles; when explicitly `false`, return responses only. if omitted, prompt inclusion follows the `count` rules above.
behavior:
- response-only mode: walks `type=response` log entries and returns the response text only
- paired mode: walks the chat log in order, pairs each `response` with the most recent preceding `user` prompt, and returns them as `[USER]` / `[RESPONSE]` cycles
returns response (or cycle) entries from the superordinate's chat. if no responses yet, indicates the superordinate may still be processing.
example:
~~~json
{
  "thoughts": ["I want to check what Devvy last responded with."],
  "headline": "Getting response from superordinate",
  "tool_name": "superordinate_getresponse",
  "tool_args": {
    "name": "Devvy"
  }
}
~~~
example with count=0, which includes prompts by default:
~~~json
{
  "thoughts": ["I want to see all of Devvy's prompt+response cycles."],
  "headline": "Getting all prompt+response cycles from superordinate",
  "tool_name": "superordinate_getresponse",
  "tool_args": {
    "name": "Devvy",
    "count": "0"
  }
}
~~~
example with negative count shorthand for prompt+response cycles:
~~~json
{
  "thoughts": ["I want the last 3 prompt+response cycles by default."],
  "headline": "Getting recent prompt+response cycles",
  "tool_name": "superordinate_getresponse",
  "tool_args": {
    "name": "Devvy",
    "count": "-3"
  }
}
~~~
example with paired prompts:
~~~json
{
  "thoughts": ["I want the last 3 prompt+response cycles to review the conversation flow."],
  "headline": "Getting paired prompt+response cycles",
  "tool_name": "superordinate_getresponse",
  "tool_args": {
    "name": "Devvy",
    "count": "3",
    "with_prompts": "true"
  }
}
~~~
