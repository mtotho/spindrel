---
name: Bot-callable widget handlers
description: How to make a widget's @on_action handlers invokable from a bot's turn — declare them in widget.yaml `handlers:`, set `bot_callable: true`, and the framework surfaces each one as a `widget__<slug>__<handler>` tool automatically. Bots can then read or mutate widget state in chat ("mark laundry done", "what's on my todo list?") without bespoke per-widget tools.
triggers: bot-callable handler, bot call widget, bot tool for widget, agent controls widget, widget__todo, widget__<slug>, handlers: block, handler tool, bot mutate widget state, widget bot bridge, ask the bot to add a todo
category: core
---

# Bot-callable widget handlers

Widget handlers (`@on_action` in `widget.py`) are already callable from the iframe via `spindrel.callHandler`. **Opt a handler in for bots too, and the framework auto-registers it as a tool** named `widget__<slug>__<handler_name>`. No per-widget Python tool module to write, no manifest plumbing beyond one block.

## Opt in — one block in `widget.yaml`

```yaml
name: Todo
db:
  schema_version: 1
  migrations:
    - from: 0
      to: 1
      sql: |
        CREATE TABLE IF NOT EXISTS todos (...);
handlers:
  - name: add_todo
    description: Add a new todo item to this list.
    triggers: [add todo, remember to, i need to]
    args:
      title:
        type: string
        description: The todo text.
        required: true
    returns:
      type: object
      properties:
        id: {type: string}
        title: {type: string}
    bot_callable: true
    safety_tier: mutating
  - name: list_todos
    description: Return every todo on this pin.
    triggers: [show todos, what's on my list]
    returns:
      type: array
      items:
        type: object
    bot_callable: true
    safety_tier: readonly
```

Every field:

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | Must exactly match an `@on_action(name)` in `widget.py`. Lowercase snake_case. |
| `description` | yes when `bot_callable` is true | Drives LLM retrieval. Write it as *when to use*, not *what it does*. |
| `triggers` | no | Extra terms for the tool-RAG ranker. User-phrase fragments work best. |
| `args` | no | JSON-Schema fragment (`{prop: {type, description, required?}}`). Omit for parameter-less handlers. |
| `returns` | no but recommended | JSON-Schema of the return shape. Lets `get_tool_info` and `run_script` reason about output. |
| `bot_callable` | defaults to false | Explicit opt-in. False keeps the handler iframe-only. |
| `safety_tier` | defaults to `mutating` | `readonly` / `mutating` / `exec_capable`. Feeds the tool-policy approval gate. |

A handler with `bot_callable: true` must have a non-empty `description` — the ranker can't surface an unlabelled tool.

## How the tool appears to bots

Given a manifest `name: Todo` with `handlers: [{name: add_todo, bot_callable: true, ...}]`, a pinned instance on a channel surfaces as:

```
widget__todo__add_todo — [Todo] Add a new todo item to this list.
```

Names are `widget__<slug>__<handler>` where `<slug>` is the manifest name lowercased and stripped to `[a-z0-9-]` (OpenAI/Gemini tool names only allow `[a-zA-Z0-9_-]`, so `__` is the separator). Two pins of the same widget on the same view (rare) disambiguate with a short `__<hash>` suffix derived from the pin id.

## Visibility rules (who sees the tool)

The dynamic enumerator (`app/services/widget_handler_tools.py`) walks pins visible to `(bot_id, channel_id)`:

- **Channel-dashboard pins.** Every pin on `channel:<current_channel_id>` surfaces for the bot talking in that channel.
- **Bot-owned pins on other dashboards.** Any pin the calling bot authored (`source_bot_id == bot_id`) surfaces, wherever its dashboard lives — `global:...`, `user:...`, etc. Useful when your bot maintains a personal list the user reaches from any channel.

When a pin is removed or moved to a dashboard the bot can't see, its handler tool disappears from the pool on the very next turn. Stale tool-name references resolve to a friendly error rather than silently running on the wrong pin.

## Identity — the handler runs as the pin's bot, not the caller

Bot-callable handlers run under **`pin.source_bot_id`** — the same identity model as iframe dispatch, cron, and event subscribers. The calling bot's scopes don't widen the handler.

- If the handler calls `ctx.tool(...)`, `ctx.api(...)`, or `spindrel.callTool(...)`, the pin's bot's API key scopes are the ceiling.
- If your widget needs to read privileged data (admin endpoints, cross-channel state), grant those scopes on the pin's bot via the admin UI — don't try to work around it by broadening the caller.
- The approval card (when one fires) shows the calling bot as the actor; the handler trace records the pin's bot as the executor. Both are audit-relevant.

## Describing handlers well

Descriptions are the LLM's primary signal. Two rules from the rest of the tool catalog apply:

1. **Lead with the trigger, not the implementation.** "Mark a todo done by id" beats "update the done column on the todos table". Tell the ranker when to choose this tool over neighbours.
2. **Disambiguate overlapping handlers.** If both `toggle_done` and `mark_complete` exist, spell out the difference. "Flip the checkbox — toggles in both directions" vs. "One-way: mark done, never undoes".

`triggers:` are an index, not documentation. Good entries are the exact user phrases you expect ("remember to", "mark X done"). Skip verbs that appear in every todo app ("add", "delete") — they're already in the name.

## `safety_tier` and the approval gate

The tool-policy pipeline treats widget-handler tools exactly like any other tool — the manifest's `safety_tier` feeds `get_tool_safety_tier` and flows into the default action resolver.

- `readonly` — no side effects. Think `list_todos`, `get_status`, `peek`. `TOOL_POLICY_AUTO_READONLY` auto-approves these when enabled.
- `mutating` — changes state inside the widget's DB. Think `add_todo`, `toggle_done`, `delete_todo`. Hits the approval gate under the default policy.
- `exec_capable` — runs arbitrary code or external commands (rare inside widget handlers; reserve for intentional escape hatches).

If a readonly handler keeps hitting approval cards for your bot, the fix is a tool-policy rule, not re-tagging the handler as lower-tier than it actually is.

## Minimal pattern — the Todo reference widget

The in-repo Todo bundle (`app/tools/local/widgets/todo/`) is the canonical example:

```python
# widget.py
from spindrel.widget import ctx, on_action

@on_action("add_todo")
async def add_todo(args):
    title = ((args or {}).get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    ...
    await ctx.notify_reload()
    return {"id": todo_id, "title": title}

@on_action("list_todos")
async def list_todos(args):
    rows = await ctx.db.query("SELECT id, title, done, position FROM todos ...")
    return [{"id": r["id"], "title": r["title"], "done": bool(r["done"])} for r in rows]
```

```yaml
# widget.yaml handlers:
- name: add_todo
  description: Add a new todo item to this list.
  triggers: [add todo, remember to, i need to]
  args: {title: {type: string, description: The todo text., required: true}}
  returns: {type: object, properties: {id: {type: string}, title: {type: string}}}
  bot_callable: true
  safety_tier: mutating
- name: list_todos
  description: Return every todo on this pin. Not-done items first.
  triggers: [show todos, what's on my list]
  returns: {type: array, items: {type: object}}
  bot_callable: true
  safety_tier: readonly
```

From the bot's seat: "remember to buy cheese" → `widget__todo__add_todo({title: "Buy cheese"})` → (optional approval) → INSERT → `ctx.notify_reload()` → iframe re-renders within the `autoReload` interval.

## When a handler should stay iframe-only

Keep `bot_callable: false` (or just omit `handlers:`) when:

- The handler's args aren't naturally expressible as user speech (pixel coordinates, drag deltas, client-only state).
- The handler exists solely to hydrate the iframe (`get_initial_state`, `preload_assets`) — bots can query the DB directly via a different handler.
- The handler is a debug / diagnostic tool the widget author wants to keep out of the agent's reach.

Every bot-callable handler is an agent-reachable surface. Declaring only what bots should operate on keeps the tool pool clean and the approval gate meaningful.

## Cross-links

- `widgets/handlers.md` — how `@on_action`, `@on_cron`, `@on_event` work and what `ctx` exposes.
- `widgets/manifest.md` — the full `widget.yaml` schema (the `handlers:` block is documented here and there).
- `widgets/errors.md` — "tool not found after pinning" / "approval always fires" entries.
