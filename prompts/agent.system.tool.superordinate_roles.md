### superordinate_roles
return the current agent's descendant superordinate roles and hierarchy as JSON so you can make routing decisions.

Use this when deciding which descendant agent or branch is best suited to answer a question or handle a task.

args:
- `ctxid` optional: context id to inspect. Defaults to the current/calling context.
- `context_id` optional alias for `ctxid`.

output is formatted JSON with:
- `caller`: the inspected context, including `ctxid`, `name`, `role`, `parent`, and `children`
- `descendants`: flat breadth-first list of descendants, each with `ctxid`, `name`, `role`, `parent`, `children`, `depth`, and `path`
- `tree`: nested descendant tree rooted at the caller

Routing guidance:
- Prefer the most specific descendant whose `role` directly matches the topic.
- Prefer closer descendants when multiple agents appear equally relevant.
- If no descendant clearly matches, keep the task or ask the parent/superior for direction.
- Use the returned `path` to understand where the selected agent sits in the hierarchy.

canonical tool name: `superordinate_roles`
compatibility aliases: `superordinte_roles`, `superordinite_roles`

example:
~~~json
{
  "thoughts": ["I need to choose the best descendant agent for this question, so I will inspect descendant roles and hierarchy."],
  "headline": "Inspecting descendant roles for routing",
  "tool_name": "superordinate_roles",
  "tool_args": {}
}
~~~
