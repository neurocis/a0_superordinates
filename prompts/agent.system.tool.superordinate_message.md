### superordinate_message
send a message to an existing persistent superordinate and wait for its response.
args: `superordinate_id` or `name`, `message`
- `superordinate_id`: the context ID of the superordinate (from superordinate_list)
- `name`: the unique name of the superordinate (preferred - easier to reference)
- `message`: the message to send
use `name` when you know the superordinate's name, or `superordinate_id` for the raw context ID.
example:
~~~json
{
  "thoughts": ["I need to check on my developer superordinate."],
  "headline": "Messaging superordinate by name",
  "tool_name": "superordinate_message",
  "tool_args": {
    "name": "Devvy",
    "message": "How is the API coming along?"
  }
}
~~~
