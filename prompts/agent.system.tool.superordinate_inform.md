### superordinate_inform
send an informational message to a related persistent superordinate context and wait for its response.

this is a convenience wrapper around `superordinate_message` with `reply` forced to `Info`, producing routed envelope `Type: Info`.

allowed targets, relative to the calling context:
- **descendant**: any superordinate spawned beneath you (children, grandchildren, ...); always enabled because this is the original/core behavior
- **ancestor**: your parent context, grandparent, etc.; controlled by the `Allow Parent / Ancestor Messaging` setting
- **sibling**: another context that shares your immediate `sup_parent`; controlled by the `Allow Sibling Messaging` setting

args: `superordinate_id` or `name`, `message`
- `superordinate_id`: the context ID of the target (from superordinate_list)
- `name`: the unique name of the target (preferred - easier to reference)
- `message`: the informational message to send

use `name` when you know the target's name, or `superordinate_id` for the raw context ID.

the recipient receives the standard routed envelope with `Type: Info`:

~~~text
{Type: Info,
 From: "SenderName" (senderCtxId),
   To: "TargetName" (targetCtxId) }

... message ...
~~~

example:
~~~json
{
  "thoughts": ["I need to inform a sibling superordinate without presenting this as a prompt."],
  "headline": "Informing sibling superordinate",
  "tool_name": "superordinate_inform",
  "tool_args": {
    "name": "Rex",
    "message": "FYI: I updated the shared plan document."
  }
}
~~~
