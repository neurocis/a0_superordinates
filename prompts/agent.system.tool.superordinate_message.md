### superordinate_message
send a message to a related persistent superordinate context and wait for its response.
allowed targets, relative to the calling context:
- **descendant**: any superordinate spawned beneath you (children, grandchildren, ...); always enabled because this is the original/core behavior
- **ancestor**: your parent context, grandparent, etc.; controlled by the `Allow Parent / Ancestor Messaging` setting
- **sibling**: another context that shares your immediate `sup_parent`; controlled by the `Allow Sibling Messaging` setting
args: `superordinate_id` or `name`, `message`
- `superordinate_id`: the context ID of the target (from superordinate_list)
- `name`: the unique name of the target (preferred - easier to reference)
- `message`: the message to send
use `name` when you know the target's name, or `superordinate_id` for the raw context ID.
the response payload includes a `relationship` field (`descendant`, `ancestor`, or `sibling`) so the caller knows which way the message went.
if ancestor or sibling messaging is disabled in the `a0_superordinates` settings, attempts to message those relationship types are rejected with a clear settings-disabled response.
example (messaging a child/descendant):
~~~json
{
  "thoughts": ["I need to check on my developer superordinate."],
  "headline": "Messaging child superordinate by name",
  "tool_name": "superordinate_message",
  "tool_args": {
    "name": "Devvy",
    "message": "How is the API coming along?"
  }
}
~~~
example (replying upward to a parent/ancestor):
~~~json
{
  "thoughts": ["I am a child superordinate reporting completion to my parent."],
  "headline": "Messaging parent superordinate by id",
  "tool_name": "superordinate_message",
  "tool_args": {
    "superordinate_id": "1ofcTily",
    "message": "Task complete. Result: ..."
  }
}
~~~
example (messaging a sibling under the same parent):
~~~json
{
  "thoughts": ["I want to coordinate with a sibling superordinate."],
  "headline": "Messaging sibling superordinate by name",
  "tool_name": "superordinate_message",
  "tool_args": {
    "name": "Rex",
    "message": "Can you share your latest research findings?"
  }
}
~~~
