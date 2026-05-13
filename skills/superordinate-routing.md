# Superordinate Routing

Use `superordinate_roles` when deciding which descendant agent or branch is best suited to handle a question.

## Terminology directive

When a user references `superordinate`, `super`, `supers`, `super's`, or `hero`, treat these terms as synonymous with the name of a superordinate/context/agent unless the surrounding context clearly indicates another meaning.

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

## Roles Routing Directive (Compact)

When assessing an assignment to a superordinate, use an **evidence-first** policy:

1. If a tool is requested (e.g., `superordinate_roles`), **run it first** or explicitly state it is unavailable.
2. Base assignment on **verified role + availability**.
3. Prefer the **feature specialist** over generic owner fallback.
4. If no specialist is verified, return the best fallback and label it **Fallback (not fully verified)**.
5. Every recommendation must include: **Source tool**, **selected superordinate**, **confidence (Verified/Fallback)**.

**Tie-break rule:** Specialist > Owner fallback > Generalist.

**No unverified definitive routing claims.**
