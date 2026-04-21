---
name: widget.py handlers — @on_action, @on_cron, @on_event
description: Server-side Python handlers attached to a widget bundle. Covers `@on_action` (iframe-dispatched), `@on_cron` (scheduled), `@on_event` (channel-event subscriptions), the `ctx` surface (`ctx.db`, `ctx.tool`, `ctx.bot_id`, `ctx.notify_reload`), identity + scope, per-handler timeouts, hot reload, and the `autoReload` mount-and-reload loop.
triggers: widget.py, @on_action, @on_cron, @on_event, widget handler, server-side python widget, ctx.db, ctx.tool, ctx.notify_reload, autoReload, onReload, spindrel.callHandler
category: core
---

# `widget.py` — server-side Python handlers

A bundle can declare a sibling `widget.py` that exposes JS-callable handlers running in the server process under the pin's bot scope.

```python
# <bundle>/widget.py
from spindrel.widget import on_action, ctx

@on_action("save_item")
async def save(args):
    await ctx.db.execute(
        "insert into items(text, created_at) values (?, datetime('now'))",
        [args["text"]],
    )
    return {"ok": True}

@on_action("search")
async def search(args):
    env = await ctx.tool("web_search", query=args["q"])
    return env.get("results", [])[:5]
```

Call from iframe JS via `window.spindrel.callHandler`:

```js
const result = await window.spindrel.callHandler("save_item", { text: "hello" });
```

**Want bots to call this handler from chat?** Opt in via the `handlers:` block in `widget.yaml` — the framework then surfaces it as a `widget__<slug>__<name>` tool automatically. See `widgets/bot-callable-handlers.md`.

## Identity and scope

Each handler invocation resolves the pin's `source_bot_id` and sets `current_bot_id` / `current_channel_id` ContextVars for the duration. `ctx.tool(name, **kwargs)` dispatches through the exact same policy gate as LLM-driven tool calls (`_check_tool_policy`); a bot missing a tool's scope gets a `scope_denied` error surfaced as `{ok: false, error: "scope_denied: ..."}` in the JS response. **Handlers cannot elevate beyond the bot's own ceiling.**

## Manifest allowlist

If `widget.yaml` declares `permissions.tools: [...]`, `ctx.tool(name, ...)` refuses any name not in that list — fail-loud, before the policy evaluator even runs. Leave `permissions.tools` empty to allow any tool the bot can already call.

```yaml
# widget.yaml
permissions:
  tools: [web_search, fetch_url]
```

## Timeouts

Each `@on_action` handler runs under `asyncio.wait_for(..., timeout=30)` by default. Override per-handler:

```python
@on_action("slow", timeout=120)
async def slow_handler(args): ...
```

Long-running work should schedule a task via `ctx.tool("schedule_task", ...)` instead of blocking.

## Hot reload

Editing `widget.py` bumps its mtime; the next call re-imports the module — no server restart needed during development.

## `ctx` surface

| Attribute | Purpose |
|---|---|
| `ctx.db.query(sql, params?)` | Returns list of row dicts. Migrations from `widget.yaml` auto-apply on first access. |
| `ctx.db.execute(sql, params?)` | Returns `{lastInsertRowid, rowsAffected}`. Takes the per-path write lock. |
| `await ctx.tool(name, **kwargs)` | Policy-checked tool dispatch under the pin's bot. Result is the parsed JSON envelope. |
| `ctx.bot_id` / `ctx.channel_id` / `ctx.pin` | Read-only accessors for the current invocation. |
| `await ctx.notify_reload()` | Signal the iframe to re-run its reload handler. See `#reload-loop` below. |

## `@on_cron` — scheduled handlers

Declare a schedule in `widget.yaml` and the handler with the matching name in `widget.py`; the server's task scheduler fires the handler under the pin's `source_bot_id` each time `next_fire_at` falls due.

```python
# <bundle>/widget.py
from spindrel.widget import on_cron, ctx

@on_cron("hourly_roll")
async def hourly_roll():
    env = await ctx.tool("fetch_url", url="https://example.com/status")
    await ctx.db.execute("update state set last = ? where id = 1", [env["body"]])
```

```yaml
# <bundle>/widget.yaml
cron:
  - name: hourly_roll
    schedule: "0 * * * *"
    handler: hourly_roll
```

Per-handler timeout defaults to 5 minutes — override with `@on_cron("name", timeout=N)`. The scheduler advances `next_fire_at` BEFORE invoking, so a crashed handler cannot cause a re-fire storm. An invalid cron schedule disables its row (`enabled=False`) without failing the pin write.

## `@on_event` — channel event subscriptions

Subscribe a handler to a channel-event stream. One live `asyncio.Task` per `(pin, kind, handler)` row subscribes to `channel_events.subscribe(pin.source_channel_id)` and fires the handler with the event's serialised payload dict.

```python
# <bundle>/widget.py
from spindrel.widget import on_event, ctx

@on_event("new_message")
async def on_msg(payload):
    await ctx.db.execute(
        "insert into log(ts, body) values (datetime('now'), ?)",
        [payload.get("message", {}).get("content", "")],
    )
```

```yaml
# <bundle>/widget.yaml
permissions:
  events: [new_message]              # ChannelEventKind allowlist — required
events:
  - kind: new_message
    handler: on_msg
```

Key behaviour:

- **Allowlist is fail-loud.** A handler declared for a `kind` not in `permissions.events` persists as `enabled=False` (visible in the DB, no task spawned). Missing from the allowlist ≠ oversight — widgets must declare what they listen to.
- **No replay.** Subscribers use `since=None`; handlers see only events that happen *after* pin creation / lifespan-startup registration. Events published before the server booted are not delivered.
- **Per-handler timeout** defaults to 30 s — override with `@on_event("kind", timeout=N)`. One slow or raising handler cannot stall the subscriber loop; exceptions are logged and the loop keeps listening.
- **Survives restarts.** On server boot, `app/main.py` lifespan iterates every pinned bundle with a manifest and re-registers its event subscribers. Shutdown cancels them cleanly.
- **Envelope update rebinds.** Swapping `source_path` (or the manifest behind it) cancels old subscriber tasks and respawns against the new manifest — no pin delete/recreate needed.

Valid `kind` values are everything in `app.domain.channel_events.ChannelEventKind` (common ones: `new_message`, `turn_started`, `turn_ended`, `tool_activity`, `heartbeat_tick`, `approval_requested`, `message_updated`). The manifest validator rejects unknown kinds at load time.

## Reload loop — `ctx.notify_reload()` + `spindrel.autoReload`

Handlers mutate bundle state (`ctx.db`, `ctx.state`) but the iframe doesn't know it changed. `ctx.notify_reload()` closes the loop: the pin's iframe re-runs whatever render function the widget registered, without a full unmount.

The **preferred DX is `spindrel.autoReload`** — one function that doubles as "initial render" and "reload handler", so mount and reload share one code path:

```html
<!-- <bundle>/index.html -->
<div id="list">Loading…</div>
<script>
  spindrel.autoReload(async () => {
    const rows = await spindrel.db.query("select ts, body from log order by ts desc limit 50");
    document.getElementById("list").innerHTML =
      rows.map(r => `<div>${r.ts} — ${r.body}</div>`).join("");
  });
</script>
```

```python
# <bundle>/widget.py
from spindrel.widget import on_event, ctx

@on_event("new_message")
async def on_msg(payload):
    await ctx.db.execute(
        "insert into log(ts, body) values (datetime('now'), ?)",
        [payload.get("message", {}).get("content", "")],
    )
    await ctx.notify_reload()
```

That's it. Every `new_message` → row inserted → iframe re-queries → DOM updates. No polling, no manual subscription.

If you need more control (e.g. conditionally skip reloads), use the lower-level `spindrel.onReload(cb)` — registers a callback only; you're responsible for the initial render. Returns an `unsubscribe()`.

Key behaviour:

- **Scope is per-pin.** `ctx.notify_reload()` publishes a `widget_reload` event carrying the pin's id; the iframe filters by `pin_id === self.dashboardPinId`. Peer pins of the same bundle on the same channel don't react to each other automatically — use `spindrel.bus.publish()` if you want cross-pin sync.
- **Fire-and-forget.** `ctx.notify_reload()` returns as soon as the event is on the bus. Safe to call from any handler flavor (`@on_action` / `@on_cron` / `@on_event`). Safe to call multiple times — each fires; if you're in a tight loop, debounce manually.
- **Rides existing SSE plumbing.** Widget iframes subscribe to `widget_reload` through the same `spindrel.stream` multiplexer the bus already exposes, so reconnect + replay-on-lapse are free.
- **Inline widgets (no `dashboardPinId`) are a no-op.** `autoReload` still runs once at mount; the subscription is just skipped.
- **Call `notify_reload` AFTER committing your DB work**, not before — otherwise the iframe's re-query races and sees stale data.

Quick-reference placement: `spindrel.onReload` and `spindrel.autoReload` live on `window.spindrel` alongside `stream` / `bus`. `ctx.notify_reload()` lives on the Python `ctx` alongside `ctx.db` / `ctx.tool`.

## See also

- `widgets/manifest.md` — `widget.yaml` schema (permissions, cron, events, db)
- `widgets/db.md` — `spindrel.db` / `ctx.db` SQL API
- `widgets/suites.md` — sharing a DB across multiple bundles
- `widgets/sdk.md` — `window.spindrel.callHandler`, `spindrel.stream`, `spindrel.bus`
