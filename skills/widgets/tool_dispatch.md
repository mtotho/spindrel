---
name: Widget tool dispatch — /widget-actions + callTool
id: widgets/tool-dispatch
description: How widgets trigger backend work — `window.spindrel.callTool(name, args)` and the underlying `POST /api/v1/widget-actions` envelope. Covers three dispatch types (tool/api/widget_config), the envelope shape, truncation rules (callTool bypasses the 4KB cap), output-shape discovery, and when to reach for dispatch vs `spindrel.api`.
triggers: /widget-actions, widget tool dispatch, widget envelope, widget callTool pattern, dispatch tool, dispatch api, dispatch widget_config, envelope body plain_body, widget truncation, sample_payload
category: core
---

# Widget tool dispatch — `POST /api/v1/widget-actions` + `callTool`

This skill is about frontend dispatch from inside an HTML widget.

Do not confuse it with the bot-facing widget action interface:

- widget JS uses `window.spindrel.callTool(...)` or `window.spindrel.api("/api/v1/widget-actions", ...)`
- bots use `invoke_widget_action(...)`

They share backend plumbing, but they are different interfaces for different actors.

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

Returns the fresh envelope on success, or `null` if the tool produced no envelope. Throws with the server's error message on non-ok response.

## Important: `callTool` does NOT auto-rerender the widget

This is the behavior people get wrong when building HA-style control panels.

`window.spindrel.callTool(name, args)`:

- dispatches the tool
- returns the fresh envelope to the caller
- emits debug events for the Inspector
- does **not** overwrite `window.spindrel.result` / `window.spindrel.widgetConfig`
- does **not** fire a magic re-render for your widget

If the widget should visually update after a click, your JS must do it deliberately.

Preferred pattern for control widgets:

```js
const state = {
  entities: new Map(),   // local source of truth for the rendered controls
  busy: new Set(),
};

function renderEntity(entityId) {
  const row = document.querySelector(`[data-entity="${entityId}"]`);
  const entity = state.entities.get(entityId);
  const busy = state.busy.has(entityId);
  row.querySelector(".js-state").textContent = entity.state;
  row.querySelectorAll("button").forEach((btn) => {
    btn.disabled = busy;
    btn.classList.toggle("is-active", btn.dataset.target === entity.state);
  });
}

async function setEntity(entityId, tool, args) {
  state.busy.add(entityId);
  renderEntity(entityId);                  // only the touched row goes busy
  try {
    const env = await window.spindrel.callTool(tool, args);
    // Either extract the next state directly from the returned envelope...
    // ...or do a follow-up state read if the mutation tool returns a thin ack.
    const fresh = await window.spindrel.callTool("ha_get_state", { entity_id: entityId });
    state.entities.set(entityId, fresh.data);
    renderEntity(entityId);                // only the touched row rerenders
  } finally {
    state.busy.delete(entityId);
    renderEntity(entityId);
  }
}
```

### What to optimize for

- **Immediate local feedback** — disable or highlight only the clicked control.
- **Targeted rerender** — update one row/card/section, not the whole widget root.
- **Reconciliation** — after the mutation returns, fetch or extract the real new state and patch local state.
- **Host refresh as backup** — `onToolResult()` / `onReload()` are for later consistency, not for the primary button-response path.

### Control dashboards — split state by surface, not by "one big refresh"

For HA-style dashboards, keep separate local slices for each visual surface:

- `lightsById` / `busyLights` for toggle rows
- `climate` for temperature/humidity cards
- `cameraUrlsById` for snapshots
- `featuredCameraId` for the hero image

Then give each surface its own render function:

```js
const state = {
  lightsById: new Map(),
  busyLights: new Set(),
  climate: null,
  cameraUrlsById: new Map(),
  featuredCameraId: "kitchen",
};

function renderLightRow(lightId) { /* patch one row */ }
function renderOfficeSummary() { /* patch one summary card */ }
function renderClimate() { /* patch climate card only */ }
function renderFeaturedCamera() { /* patch hero image only */ }
function renderCameraTile(cameraId) { /* patch one thumbnail only */ }
```

Light-toggle flow:

1. mark only that light busy
2. optimistically patch only that row (and any summary card derived from it)
3. run `callTool(...)`
4. do a follow-up `ha_get_state(...)` if needed
5. patch only that light's local state
6. rerender only that row / summary card

Do **not** handle a light click by rerunning:

- `refreshLights()` that rebuilds the entire list
- `init()` for the whole dashboard
- camera refresh functions
- featured-image fetches

If the click was "Kitchen lights off", the camera wall should not blink, refetch, or rebuild its DOM.

### What causes the "whole thing is reloading" feel

- Re-running `init()` on every click and rebuilding the entire DOM tree.
- Replacing `root.innerHTML` for the whole widget after every button press.
- Rebuilding a whole section (`lights-list`, `camera-grid`, etc.) just to update one control.
- Refetching unrelated data (camera snapshots, featured image, weather card) after a light toggle.
- Using `location.reload()` or forcing iframe reloads instead of local rerender.
- Waiting for a host-driven refresh before updating button state at all.

For tiny widgets that is survivable; for multi-card dashboards it feels broken.

If the mutation tool's envelope is just an ack and not the next live state, use a two-step pattern:

1. optimistic/local busy state now
2. mutation via `callTool(...)`
3. immediate follow-up state read
4. patch local state and rerender just the affected controls

## The envelope shape

Every envelope returned from `callTool(...)` has the same fields:

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
    widget_config: { units: "metric" },  // current pin config for {{widget_config.*}} substitution
    dashboard_pin_id: window.spindrel.dashboardPinId,
    source_record_id: someRecordId,
  }
});
```

**Working exemplars in-tree** — read these before writing yours:

- `app/tools/local/widgets/generate_image/image.html` — regen buttons dispatch `generate_image` with mutated prompts.

(These were written before `callTool` shipped; they build the body by hand. The behavior is identical — `callTool` is the shorter way.)

## Constraints

- Tool runs under your bot's scopes. If the tool needs a capability your bot doesn't have, the dispatch fails cleanly — don't try to work around it.
- The `state_poll` cache (for declarative widgets) has a 30 s TTL keyed by `(tool, args)`; mutations invalidate it.
- `dispatch:"api"` is **whitelisted** to `/api/v1/admin/tasks` and `/api/v1/channels/*`. For any other endpoint, use `spindrel.api()` directly. `callTool` is only for tool dispatch — for `dispatch:"api"` or `dispatch:"widget_config"`, use `spindrel.api("/api/v1/widget-actions", ...)` directly.

## When not to use this skill

If the question is about:

- how a bot should operate a pinned widget
- how to inspect what actions a widget supports
- how native Notes or other first-party widgets should be invoked

then use the shared bot flow instead:

- `widget_library_list`
- `pin_widget`
- `describe_dashboard`
- `invoke_widget_action`

## Knowing the output shape before you call

Widgets are authored ahead of any real invocation, so you don't know the envelope shape until the tool actually runs. **Don't guess. Don't write fallback chains like `env.data.state || env.body.data.state || env.result.data.state`** — those are the primary cause of broken widgets. Pick one of two ground-truth paths, in this order:

1. **`spindrel.toolSchema(name)`** — for local tools that register a `returns=` schema this returns `{input_schema, returns_schema}` with a concrete return shape. Code against it. Many core tools have it; MCP tools don't (no slot in the protocol), in which case `returns_schema` is `null`.
2. **Inspect the real response** (the debug loop — see [`widgets/errors.md#inspecting-a-pinned-widget--the-debugging-recipe`](errors.md#inspecting-a-pinned-widget--the-debugging-recipe)):
   - Emit widget v1. Optionally add `spindrel.log.info("shape", await callTool(...))` on first iteration so the shape is logged even before you code extraction against it.
   - Pin it.
   - Call `inspect_widget_pin(pin_id)` from a bot turn, or open the Inspector (pin menu → Bug icon) in the UI.
   - Read the `response` field on the most recent `tool-call` event.
   - Rewrite extraction against the confirmed path and re-emit.

**Canonical envelope shapes for commonly-called tools** are indexed in [`widgets/errors.md#envelope-shape-index--canonical-tool-responses`](errors.md#envelope-shape-index--canonical-tool-responses). For any tool not in that index, run the debug loop once — first invocation is the authoritative source.

A fully-working snapshot widget:

```js
const env = await window.spindrel.callTool("frigate_snapshot", { camera: "kitchen" });
const url = await window.spindrel.loadAttachment(env.attachment_id);
document.querySelector("img").src = url;
```

A fully-working HA state widget:

```js
const env = await window.spindrel.callTool("ha_get_state", { entity_id: "sensor.kitchen_temperature" });
document.getElementById("value").textContent =
  env.data.state + " " + env.data.attributes.unit_of_measurement;
```

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
