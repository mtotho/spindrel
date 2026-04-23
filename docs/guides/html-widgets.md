# HTML Widgets — Standalone Live Dashboards

For the canonical overview of how HTML widgets relate to presets, tool widgets, native widgets, and shared placement, start with [Widget System](widget-system.md). This guide goes deep on the standalone HTML-widget lane only.

Any bot with tool access can author a **live, interactive standalone widget** that renders in your chat and optionally pins to your dashboard. Ask for "a little panel that shows X" or "a chart of Y over time" and you'll get back an HTML card that runs in a sandboxed iframe, reads from Spindrel's own API, and updates in real time.

These widgets can:

- Run JavaScript (fetch data, handle clicks, redraw)
- Call the same `/api/v1/...` endpoints the bot can call from tools
- Re-render automatically when the underlying workspace file changes

Think Grafana-like panels, but authored conversationally and scoped to whichever bot you asked.

This guide is about standalone HTML widgets only. A YAML-defined tool widget that uses `html_template` is still a tool widget, not this lane.

## How it works, end to end

1. **You ask.** "Build me a widget that shows the last 10 messages in this channel."
2. **The bot writes HTML + JS** and calls `emit_html_widget`. The tool result is an interactive card.
3. **You pin it** (star icon on the card) to the channel's dashboard, the global dashboard, or both.
4. **It keeps working.** The widget's JS runs every time you view the dashboard, fetches fresh data, and renders. When it's backed by a workspace file, editing that file updates the widget within a few seconds.

## Asking for one

There's no special command — just describe what you want. Good prompts:

- "Build me a little dashboard with three panels: recent messages, running tasks, and bot count."
- "Make a widget that shows the last 20 tool calls and their status."
- "Give me a chart of my token spend by day this week."
- "I want a pinned card with a 'Start overnight run' button that kicks off task pipeline X."

The bot will one-shot the HTML, render it in chat, and you decide whether to pin.

## The security model — widgets run as the bot, not as you

This is the part that matters most. **A widget's JavaScript executes with the emitting bot's permissions — not yours.**

Concretely:

- Every widget is stamped with `source_bot_id` at emit time.
- When the iframe renders, Spindrel mints a **short-lived (15 min) bearer token scoped to that bot's API key** and injects it into the widget's helper.
- Every API call the widget makes carries that bearer — so scoped endpoints enforce the bot's scopes, not yours.

**Why it matters:** if a widget could use your session, then any bot you use could effectively write JavaScript that runs with your privileges when you view the widget — including admin routes you never intended to let it touch. That's an unacceptable class of footgun, so we closed it by design.

**Where you see it:** look for the `🤖 @botname` chip in the bottom-left corner of every HTML widget card. That's the bot the widget is acting as. Hover for the full tooltip.

**What this means for permissions:**

- If a widget you asked for returns "Widget auth failed", the bot has no API key configured. Go to **Admin → Bots → this bot → API Permissions** and provision one with the scopes the widget needs.
- If a widget returns 403 on some endpoint, the bot's key doesn't have that scope. Broaden the bot's scopes (not yours) and refresh.
- Admin scope on *your* user account does **not** lend admin powers to widgets. This is intentional.

Token rotation is automatic and transparent: the renderer re-mints every 12 min so long-running widgets keep working, and screenshots of devtools expire quickly.

## Two modes: inline vs workspace-backed

| Mode | What it is | When to use |
|---|---|---|
| **Inline** | The bot writes the full HTML body in one shot. Static snapshot. | One-off views ("show me a quick breakdown of…"). |
| **Path** | The bot saves a full HTML file in the channel workspace (e.g. `dashboards/cpu.html`) and points the widget at it. | Iterative dashboards — you tweak, bot edits the file, widget refreshes in ~3 s. |

For anything you expect to evolve, ask for the path-mode flavor. "Save this as `dashboards/morning-standup.html` so I can tweak it" is enough of a hint.

## Where widgets live

Widgets can be pinned in three places:

- **Inline in chat** — right where the bot emitted them; scrolls with the transcript.
- **Channel dashboard** — the channel's own pinboard (left rail in the OmniPanel + full grid via the `LayoutDashboard` icon in the channel header).
- **Global dashboard (`/widgets/default`)** — your cross-channel board. Widgets here still authenticate as their originating bot and still show the `@botname` chip.

Regardless of where you pin a widget, it continues to act as the bot that emitted it — context travels with the envelope, not with the render host.

## When to use what

| You want | Best tool |
|---|---|
| A standalone mini-app, chart, table, or custom dashboard | HTML widget |
| A rich card that is not naturally one tool's result | HTML widget (usually path mode) |
| A tool-bound entity detail / toggle / status card | Tool widget (see [Widget Templates](../widget-templates.md)) |
| A YAML-defined tool widget that needs custom visuals | Tool widget with `html_template`, not a standalone HTML widget |
| A one-off textual answer | Just a normal reply |
| A reusable parameterized widget across many channels | Not yet — HTML widgets v1 is per-emission; roadmap item |

## Troubleshooting

| Symptom | Usual cause | Fix |
|---|---|---|
| `Widget auth failed: Bot X has no API key configured` banner | The bot has no scoped key to authenticate as | Admin UI → Bots → provision an API key with the scopes the widget needs |
| `API 403` errors in the widget body | Bot's key is missing the scope the endpoint requires | Broaden the bot's scopes (not your user's) |
| `API 422` errors on `/api/v1/channels/null/...` | The bot didn't stamp channel context into the widget | Usually a bot bug — the bot should bake `window.spindrel.channelId` or a literal UUID into the fetch URL. Report the prompt so we can fix the authoring skill. |
| Widget never shows fresh data | The widget isn't polling — ask the bot to add a `setInterval` or to use path mode with a file that gets edited |
| "Updated Xm ago" chip keeps ticking but nothing changes | The widget is polling an endpoint that hasn't moved. Normal. |

## Further reading

- [Widget Dashboards](widget-dashboards.md) — how named dashboards and channel dashboards work, the OmniPanel rail, grid presets, and editing. HTML widgets pin onto the same boards as component widgets.
- [Widget Templates](../widget-templates.md) — for tool widgets authored from YAML, including tool widgets that render through `html_template`.
- [Developer API](api.md) — the endpoints widgets can call (anything your bot's scoped key can hit).
- [Custom Tools & Extensions](custom-tools.md) — if you want to ship HTML widget skills with your own integration.
