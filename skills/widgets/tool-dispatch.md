---
name: Widget tool dispatch — /widget-actions + callTool
description: How widgets trigger backend work — `window.spindrel.callTool(name, args)` and the underlying `POST /api/v1/widget-actions` envelope. Covers three dispatch types (tool/api/widget_config), the envelope shape, truncation rules (callTool bypasses the 4KB cap), output-shape discovery, and when to reach for dispatch vs `spindrel.api`.
triggers: /widget-actions, widget tool dispatch, widget envelope, widget callTool pattern, dispatch tool, dispatch api, dispatch widget_config, envelope body plain_body, widget truncation, sample_payload
category: core
---

# Widget tool dispatch — `POST /api/v1/widget-actions` + `callTool`

Dashboards aren't just read surfaces. You trigger work from a widget by dispatching a **tool call** through the host, which runs the tool under your bot's scopes and pushes the fresh result back into the widget.

The endpoint is `POST /api/v1/widget-actions`. Three dispatch types:

| `dispatch` | Purpose |
|---|---|
| `"tool"` | Run a named tool (any tool your bot can call) |
| `"api"` | Call a whitelisted admin/channel endpoint (`/api/v1/admin/tasks` or `/api/v1/channels/*`) |
| `"widget_config"` | Patch this pin's `widget_config` (for declarative html_template widgets) |

## The tool-dispatch pattern

Use `window.spindrel.callTool(name, args, opts?)` — it wraps the endpoint, auto-fills `bot_id` + `channel_id`, and throws on failure so you can `try/catch` cleanly:

```js
document.getElementById("run").addEventListener("click", async () => {
  try {
    const env = await window.spindrel.callTool("fetch_url", {
      url: "https://example.com",
    });
    document.getElementById("out").textContent = env.body_text;
  } catch (e) {
    document.getElementById("out").textContent = "Failed: " + e.message;
  }
});
```

Returns the fresh envelope (same shape as `window.spindrel.toolResult`) on success, or `null` if the tool produced no envelope. Throws with the server's error message on non-ok response.

## The envelope shape

Every envelope — whether returned from `callTool`, pushed into `window.spindrel.toolResult`, or received via `onToolResult` — has the same fields:

| Field | Type | What it carries |
|---|---|---|
| `content_type` | string | MIME-ish type, e.g. `"application/json"`, `"text/markdown"`, `"text/plain"`, `"application/vnd.spindrel.html+interactive"` |
| `body` | string \| null | **The full tool output** as a string. JSON tools ship a JSON-encoded string — parse with `JSON.parse(env.body)`. |
| `plain_body` | string | Short preview (≤200 chars for default envelopes, ≤800 for opt-in). **Never** the full payload — don't parse it. |
| `display` | `"badge" \| "inline" \| "panel"` | Renderer hint for the chat bubble. Widgets can ignore. |
| `truncated` | boolean | `true` means `body` was dropped because the underlying payload exceeded the inline cap. **Never true for `callTool` results** (see below). |
| `byte_size` | integer | Actual UTF-8 size of the full payload, even when `body` is null. |
| `record_id` | string \| null | Persisted `tool_calls` row id. Not addressable from widget auth — informational only. |
| `tool_name` | string | The tool that produced this envelope. |

**`body` vs `plain_body`** — `body` is what you parse; `plain_body` is a short human-readable preview for the chat badge. They are not interchangeable. `JSON.parse(env.plain_body)` will fail on any non-trivial payload because `plain_body` is truncated by design.

## Truncation — does not apply to `callTool`

The LLM turn loop caps envelope `body` at 4 KB to protect the model's context window. When that cap fires, `body` becomes `null`, `truncated` becomes `true`, and the UI lazy-fetches the full content through a session-scoped endpoint.

**`callTool` bypasses this cap.** Widget-actions dispatch returns the full `body` regardless of size — widgets can always `JSON.parse(env.body)` without worrying about truncation. Two consequences:

- Your widget can safely call `callTool` against tools that return large JSON (directory listings, API dumps, many-row queries) without seeing `body: null`.
- **Don't defensively handle `truncated: true` on `callTool` results.** If you see it, it's a bug worth reporting — not an expected state.

The only content type that was already exempt from the cap — `application/vnd.spindrel.html+interactive` — stays exempt everywhere.

## `opts.extra` — passing through extra fields

```js
await window.spindrel.callTool("web_search", { query: "docs" }, {
  extra: {
    display_label: "Docs search",        // lets state_poll fetch fresh state after
    widget_config: { starred: [...] },   // current pin config for {{config.*}} substitution
    dashboard_pin_id: window.spindrel.dashboardPinId,
    source_record_id: someRecordId,
  }
});
```

**Working exemplars in-tree** — read these before writing yours:

- `integrations/web_search/widgets/web_search.html` — Summarize button dispatches `fetch_url`.
- `app/tools/local/widgets/generate_image/image.html` — regen buttons dispatch `generate_image` with mutated prompts.

(These were written before `callTool` shipped; they build the body by hand. The behavior is identical — `callTool` is the shorter way.)

## Constraints

- Tool runs under your bot's scopes. If the tool needs a capability your bot doesn't have, the dispatch fails cleanly — don't try to work around it.
- The `state_poll` cache (for declarative widgets) has a 30 s TTL keyed by `(tool, args)`; mutations invalidate it.
- `dispatch:"api"` is **whitelisted** to `/api/v1/admin/tasks` and `/api/v1/channels/*`. For any other endpoint, use `spindrel.api()` directly. `callTool` is only for tool dispatch — for `dispatch:"api"` or `dispatch:"widget_config"`, use `spindrel.api("/api/v1/widget-actions", ...)` directly.

## Knowing the output shape before you call

There's no dedicated output-schema field on tools today, but three practical ways to learn what a tool returns:

1. **Widget-template `sample_payload`** — tool packs declare a `sample_payload` block in per-widget `template.yaml` files under `app/tools/local/widgets/<tool_name>/` (e.g. `app/tools/local/widgets/list_tasks/template.yaml`, `app/tools/local/widgets/get_system_status/template.yaml`). When present, it's the de facto output contract — the shape the template's `{{field}}` substitutions expect. Read it from the bot turn before emitting the widget.
2. **`GET /api/v1/admin/tools/{tool_name}`** — returns the input schema + description + the active widget package name; use that name to locate the template.yaml above. Input-shape authoritative, output-shape indirect.
3. **Call it once from the bot turn, inspect, then write the widget.** The most reliable path: dispatch the tool in the same conversation before authoring the widget, copy the JSON structure out of the envelope body, and shape your widget around it. Live output trumps any doc.

For MCP tools, the upstream protocol only ships `inputSchema` — `outputSchema` isn't exposed. Fall back to path (3).

## Discovering what endpoints your widget can hit

Don't guess URLs or copy examples blindly — **call `list_api_endpoints` BEFORE writing the widget** and use the result as ground truth. It returns only the endpoints your bot's scoped API key can hit.

```
list_api_endpoints(scope="channels")   # → all channel endpoints in your scope
list_api_endpoints(scope="admin")       # → admin endpoints (if you have them)
list_api_endpoints()                    # → everything your bot can touch
```

Then inside the widget, use those exact paths with `window.spindrel.api()`:

```js
const state = await window.spindrel.api(
  "/api/v1/channels/" + window.spindrel.channelId + "/state"
);
```

Note the division of labor:

- **`spindrel.api()`** = read state, call regular endpoints.
- **`/api/v1/widget-actions` (dispatch:"tool")** = trigger a tool. Use this when you'd otherwise be wishing for a REST endpoint that "runs X for me".

## When to use `/widget-actions` vs `spindrel.api()`

| Need | Use |
|---|---|
| Read state (`GET /api/v1/...`) | `spindrel.api()` directly |
| Trigger a tool / mutate through a tool | `spindrel.callTool(name, args)` — returns fresh envelope |
| Patch this pin's `widget_config` | `POST /api/v1/widget-actions` with `dispatch:"widget_config"` |
| Hit one of the whitelisted admin endpoints | Either works; `dispatch:"api"` keeps scopes tight |
| Raw response (blob, stream, binary) | `spindrel.apiFetch()` |
| Read/write a workspace file | `spindrel.readWorkspaceFile` / `writeWorkspaceFile` |

## See also

- `widgets/sdk.md` — full `window.spindrel` surface
- `widgets/handlers.md` — `callHandler` for server-side Python (alternative to `callTool`)
- `widgets/errors.md` — 422 / `body: null` / `scope_denied` troubleshooting
