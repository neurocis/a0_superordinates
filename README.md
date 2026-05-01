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

## Agent Calendar / ICS Editing

On the `feat/agent-ics` branch, the plugin also adds a **Calendar** button to the chat input action bar.

Each agent context has a writable calendar folder on the webserver:

```text
/a0/usr/chats/<ctxid>/calendar/
```

The Calendar panel can:

- List local `.ics` files for the selected agent context
- Create a new local `.ics` file
- Add or remove remote ICS subscription links
- Open a local `.ics` file in the browser
- Add, edit, and delete `VEVENT` entries through a form
- Create and edit recurring events with `RRULE`, `RDATE`, and `EXDATE`
- Preserve existing recurrence metadata and non-form event properties during form edits

The backing API is:

```text
POST /api/plugins/a0_superordinates/agent_calendar
```

Supported actions include:

- `list`
- `create_ics`
- `read_ics`
- `save_ics`
- `upsert_event`
- `delete_event`
- `add_subscription`
- `remove_subscription`

For safety, file operations are constrained to sanitized `.ics` filenames inside the selected context's calendar directory.

Recurring event support includes simple minute/hour/day/week/month/year controls, custom `RRULE` editing, and advanced `RDATE`/`EXDATE` textareas. Existing complex recurrence rules and non-form `VEVENT` metadata such as attendees, alarms, URLs, and `X-*` properties are preserved when editing ordinary form fields.

Local `.ics` files are stored as **single-component resources**: each file contains at most one `VEVENT` *or* one `VTODO`. Saving a raw ICS payload with multiple components is rejected; create a separate `.ics` file per component instead. The Calendar editor lets you switch the file between Event and Todo modes; saving rewrites the file as the selected component type.

When an Agent has at least one local `.ics` file or Web ICS subscription, the plugin persists and reconciles a `has_calendar` indicator for that Agent. The Superordinates sidebar suffixes that Agent's display name with `📅`; the icon is removed automatically when the last calendar source is deleted.

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
