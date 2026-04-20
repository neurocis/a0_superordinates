# A0 Superordinates

An Agent Zero plugin that creates **persistent, visible superordinate agents** — each running in its own chat context, visible in the sidebar, and surviving across restarts.

## Why?

The built-in `call_subordinate` tool creates ephemeral subordinates that share the parent's `AgentContext` — they're invisible in the UI, can only run one at a time, and are lost when the conversation moves on.

**A0 Superordinates** gives each agent its **own `AgentContext`**, making it:

- ✅ **Visible** as a separate chat in the sidebar
- ✅ **Persistent** across framework restarts
- ✅ **Concurrent** — spawn multiple superordinates at once
- ✅ **Navigable** — click to drill into any superordinate's chat
- ✅ **Hierarchical** — tree view in the sidebar showing parent-child relationships

## Features

| Feature | `call_subordinate` (built-in) | `a0_superordinates` (this plugin) |
|---|---|---|
| Context | Shares parent's | Own `AgentContext` |
| Sidebar visible | ❌ | ✅ Separate chat |
| Persists restarts | ❌ Ephemeral | ✅ Via `context.data` |
| UI hierarchy | None | ✅ Tree panel |
| Communication | Synchronous (blocks) | Async spawn or sync message |
| Multi-subordinate | One at a time | Multiple concurrent |

## Tools

### `superordinate_spawn`

Create a new persistent superordinate with its own chat context.

```json
{
  "tool_name": "superordinate_spawn",
  "tool_args": {
    "name": "Devvy",
    "profile": "developer",
    "message": "Build a REST API with FastAPI."
  }
}
```

### `superordinate_message`

Send a message to an existing superordinate and await the response.

```json
{
  "tool_name": "superordinate_message",
  "tool_args": {
    "superordinate_id": "lvAuHzx7",
    "message": "How is the API coming along?"
  }
}
```

### `superordinate_list`

List all superordinates with their status (running/idle/closed).

```json
{
  "tool_name": "superordinate_list",
  "tool_args": {}
}
```

## Shortcut Syntax

Add a `.promptinclude.md` file to your project with:

```markdown
# SuperOrdinate Spawn Shortcuts

Format: `Name,profile` → expands to `superordinate_spawn`

- `Devvy,developer` → spawns Devvy with developer profile
- `Rex,researcher` → spawns Rex with researcher profile
```

## Architecture

### Persistence

Hierarchy metadata is stored in `AgentContext.data` using non-underscore-prefixed keys that survive serialization:

| Key | Type | Description |
|---|---|---|
| `sup_parent` | `str` | Parent context ID |
| `sup_children` | `list[dict]` | `[{ctxid, profile, name, created_at}]` |
| `sup_profile` | `str` | Profile name of this superordinate |

### API Endpoint

`POST /api/plugins/a0_superordinates/superordinate_hierarchy`

Input: `{"context": "<ctxid>"}` → Returns full hierarchy tree

### WebUI

- **Sidebar extension**: Hierarchy tree panel under `sidebar-chats-list-end`
- **Alpine store**: `$store.superordinates` with auto-refresh (5s)
- **Profile badges** and expand/collapse for nested hierarchies

## Installation

### From Plugin Hub

Find **A0 Superordinates** in the Plugin Hub and click Install.

### From Git

```bash
cd /a0/usr/plugins
git clone https://github.com/neurocis/a0_superordinates.git
```

Then restart the Agent Zero framework.

## Development

```bash
cd /a0/usr/plugins/a0_superordinates
# Make changes, then restart framework to test
```

## License

MIT License — see [LICENSE](LICENSE)
