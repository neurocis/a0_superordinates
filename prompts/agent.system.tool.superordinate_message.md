### superordinate_message
send a message to a related persistent superordinate context. Prompt deliveries return immediately; the recipient response is routed back automatically from `process_chain_end`.
allowed targets, relative to the calling context:
- **descendant**: any superordinate spawned beneath you (children, grandchildren, ...); always enabled because this is the original/core behavior
- **ancestor**: your parent context, grandparent, etc.; controlled by the `Allow Parent / Ancestor Messaging` setting
- **sibling**: another context that shares your immediate `sup_parent`; controlled by the `Allow Sibling Messaging` setting
args: `superordinate_id` or `name`, `message`, optional `reply`, optional `Type`
- `superordinate_id`: the context ID of the target (from superordinate_list)
- `name`: the unique name of the target (preferred - easier to reference)
- `message`: the message to send
- `reply`: optional reply label for the routed envelope; defaults to `Prompt`. The recipient sees `Reply: <value>` only when `reply` is not `Info`. On completion, this same value controls reverse delivery: `reply: Info` logs the response back without prompting; non-Info replies prompt the original sender.
- `Type`: optional delivery type; defaults to `Prompt`. When `Type` is `Info`, `reply` is forced to `Info` and the final target receives visible/history context only; it is not prompted.
use `name` when you know the target's name, or `superordinate_id` for the raw context ID.
the response payload includes a `relationship` field (`descendant`, `ancestor`, or `sibling`) so the caller knows which way the message went.
the tool does not wait synchronously for prompted target processing. When the target finishes, the `process_chain_end` hook detects the inbound `{From: ...}` envelope and routes the final response back in reverse. The inbound `reply` value controls that reverse delivery: `Info` is context-only; any other value prompts the original sender.
Hero Mode direct prompts use the centralized API path. When the `Set replies to the Hero from a prompted Superordinate to Informational` setting is enabled, those Hero-routed prompts use `reply: "Info"`, so the focused non-Hero superordinate is still prompted but its completed response returns to the Hero as informational memory/context rather than prompting the Hero.
if sibling messaging is disabled in the `a0_superordinates` settings, ordinary sibling messages are still delivered as full context-only `Info` messages: the sibling sees the message and receives it in memory-channel context, but it is not prompted. If sibling messaging is enabled, sibling messages are delivered normally without this downgrade.
if parent/ancestor messaging is disabled, ordinary descendant messages to any ancestor/addressee in their hierarchy are still delivered as full context-only `Info` messages: the addressed ancestor sees the message and receives it in memory-channel context, but it is not prompted. Verified reverse replies to an earlier routed message bypass these downgrades and are delivered according to their original `Reply`/`Type` semantics. Unrelated contexts are rejected.
recipient envelope format for prompted delivery (`Type: "Prompt"`, the default):
~~~text
{From: "SenderName" (senderCtxId), Reply: Prompt}

... message ...
~~~
when `Type` is `Info`, `reply` is forced to `Info`, the `Reply` field is omitted, and the final target is logged/added to context without prompt processing:
~~~text
{From: "SenderName" (senderCtxId)}

... message ...
~~~
the source agent always gets an informational copy logged into its visible chat plus `memory`-channel context only; it is not dispatched as a prompt. When the `Keep everybody in the loop` setting is enabled, hierarchy intermediates between source and target also get informational copies. For the source agent, `From` is omitted as redundant. `Reply` is included only when `reply` is not `Info`:
~~~text
{To: "TargetName" (targetCtxId), Reply: Prompt}

... message ...
~~~
for hierarchy intermediates, both endpoints are included. `Reply` is included only when `reply` is not `Info`:
~~~text
{From: "SenderName" (senderCtxId), To: "TargetName" (targetCtxId), Reply: Prompt}

... message ...
~~~
for `reply: "Info"`, observer copies omit `Reply`:
~~~text
{To: "TargetName" (targetCtxId)}
{From: "SenderName" (senderCtxId), To: "TargetName" (targetCtxId)}
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
    "reply": "Prompt",
    "Type": "Prompt"
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
