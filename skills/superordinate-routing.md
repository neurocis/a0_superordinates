# Superordinate Routing

Use `superordinate_roles` when deciding which descendant agent or branch is best suited to handle a question.

The tool returns JSON containing:

- `caller`: the calling/current context, its role, parent, and children
- `descendants`: a flat breadth-first list of descendant contexts
- `tree`: a nested hierarchy rooted at the caller

Each descendant includes:

- `ctxid`
- `name`
- `role` from `/a0/usr/chats/<ctxid>/superordinate/roles.md`
- `parent`
- `children`
- `depth`
- `path` from the caller to that descendant

## Routing guidance

- Prefer the most specific descendant whose role directly matches the topic.
- Prefer closer descendants when multiple descendants appear equally relevant.
- If no descendant clearly matches, keep the task or ask the parent/superior for direction.
- Use the returned `path` to understand where the target agent sits in the hierarchy.
- Use `superordinate_message` with the selected agent name or context id after choosing a route.

Canonical tool name:

```text
superordinate_roles
```
