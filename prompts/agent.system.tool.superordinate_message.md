### superordinate_message
send a message to a related persistent superordinate context and wait for its response.
allowed targets, relative to the calling context:
- **descendant**: any superordinate spawned beneath you (children, grandchildren, ...); always enabled because this is the original/core behavior
- **ancestor**: your parent context, grandparent, etc.; controlled by the `Allow Parent / Ancestor Messaging` setting
- **sibling**: another context that shares your immediate `sup_parent`; controlled by the `Allow Sibling Messaging` setting
args: `superordinate_id` or `name`, `message`, optional `reply`
- `superordinate_id`: the context ID of the target (from superordinate_list)
- `name`: the unique name of the target (preferred - easier to reference)
- `message`: the message to send
- `reply`: optional reply label for the routed envelope; defaults to `Prompt`. The recipient sees `Reply: <value>` only when `reply` is not `Info`.
use `name` when you know the target's name, or `superordinate_id` for the raw context ID.
the response payload includes a `relationship` field (`descendant`, `ancestor`, or `sibling`) so the caller knows which way the message went.
the tool waits up to the configured `reply_wait_seconds` value for a reply before returning a check-later timeout response; the default is 5 seconds.
if sibling messaging is disabled in the `a0_superordinates` settings, sibling attempts are rejected with a clear settings-disabled response.
if parent/ancestor messaging is disabled, descendant messages to any ancestor/addressee in their hierarchy use notification fallback: the addressed ancestor receives only `{ContextID} has sent you a message`, while the full message/conclusion is returned locally in the sender context instead of being sent upward. Unrelated contexts are rejected.
recipient envelope format:
~~~text
{From: "SenderName" (senderCtxId), Reply: Prompt}

... message ...
~~~
for informational messages (`reply: "Info"`), the `Reply` field is omitted:
~~~text
{From: "SenderName" (senderCtxId)}

... message ...
~~~
when source and target are separated by hierarchy intermediates, each intermediate gets an informational copy logged into its visible chat/history context only; it is not dispatched as a prompt. The final target is restored and no `Reply` field is included:
~~~text
{From: "SenderName" (senderCtxId), To: "TargetName" (targetCtxId)}

... message ...
~~~
example (messaging a child/descendant):
~~~json
{
  "thoughts": ["I need to check on my developer superordinate."],
  "headline": "Messaging child superordinate by name",
  "tool_name": "superordinate_message",
  "tool_args": {
    "name": "Devvy",
    "message": "How is the API coming along?",
    "reply": "Prompt"
  }
}
~~~
example (replying upward to a parent/ancestor, when parent/ancestor messaging is enabled):
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
example (finishing upward when parent/ancestor messaging is disabled):
~~~json
{
  "thoughts": ["Parent messaging is disabled, but I should still pass my real conclusion to the tool. The tool will notify my parent and return my conclusion locally."],
  "headline": "Completing with parent notification fallback",
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
