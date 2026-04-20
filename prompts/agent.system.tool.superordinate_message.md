### superordinate_message
send a message to an existing persistent superordinate and wait for its response.
args: `superordinate_id`, `message`
- `superordinate_id`: the context ID of the superordinate (from superordinate_list)
- `message`: the message to send
example:
~~~json
{
  "thoughts": ["I need to check on my developer superordinate."],
  "headline": "Messaging superordinate",
  "tool_name": "superordinate_message",
  "tool_args": {
    "superordinate_id": "abc123",
    "message": "How is the API coming along?"
  }
}
~~~
