---
tags: [agent-server, track, widgets, sdk, framework]
status: active
updated: 2026-04-19 (Phase A.2 complete — spindrel.state shipped; Phase B next)
---

# Track — Widget SDK (from scripts to a framework)

> **Phase A complete 2026-04-19.** Plans: `~/.claude/plans/drifting-purring-kahan.md` (A.1), `~/.claude/plans/witty-waddling-moonbeam.md` (A.2b). Sessions 25–30 collectively shipped the full iframe-only SDK: `bus`, `cache`, `notify`, `log`, `ui.status`, `ui.table`, `ui.chart`, `form`, `stream`, `state`, error boundary, host-chrome toast listener, Dev Panel "Widget log" subtab, and three showcase widgets (web_search rewrite, Context Tracker, Notes). Session 30 shipped the last A.2 slice — **`spindrel.state`** (versioned `data.load` + forward migrations + per-path in-iframe mutex + downgrade refusal) plus `app/tools/local/widgets/notes/` as the real showcase (pinned-channel scratchpad with v1→v2 schema migration from `{text}` to `{markdown, createdAt, updatedAt}`). Phase B (`widget.yaml` + `widget.py` handlers + `spindrel.db` SQLite + cron/event wiring) and Phase C (DX-5b unblock + integration widget catalog + Frigate dog-food) not started — do not close this track until Phase C's exit criteria land.

## North Star

HTML widgets become a real SDK: `window.spindrel` gets a framework's-worth of primitives (bus, stream, form, ui, db, cron), widget bundles gain server-side Python handlers (`widget.py`) running in the `run_script` sandbox under bot scopes, and integrations can ship widgets as first-class dashboard UI alongside their existing admin pages.

Three pressures:

1. Every integration that ships an HTML widget re-implements forms / tables / fetch-retry / error surfaces. No shared lib today.
2. Widget Dashboard track shipped the surface; we have dashboards but no way to build mini-apps for them.
3. User wants HTML widgets to eventually **be** the presentation layer of integrations — not just the decoration over tool results.

**End-state bundle shape**:

```
<bundle>/
├── widget.yaml          # manifest: tools, events, cron, schema_version, permissions
├── index.html           # presentation (frontmatter intact for catalog discovery)
├── widget.py            # backend handlers (optional, sandboxed under bot scopes)
├── data.sqlite          # structured store (auto-created, accessed via spindrel.db)
├── state.json           # simple K/V state (unchanged, still supported)
├── assets/              # binary
└── migrations/          # schema upgrades
```

## Decisions locked in (planning session)

1. **Scope** — full 3-phase vision in one Track, phased across sessions.
2. **Persistence** — server-side SQLite per bundle (`<bundle>/data.sqlite`), not browser IndexedDB.
3. **Handler model** — `widget.py` with `@on_action` / `@on_cron` / `@on_event` decorators, in the existing `run_script` sandbox.
4. **Integration UI posture** — widgets ship **alongside** existing admin pages. Additive, no forced migration.

## Status

| # | Phase | What | Status |
|---|-------|------|--------|
| 0 | Promote to vault Track | This file + Roadmap entry + mark plan executed | **done** (2026-04-19) |
| A.1 | JS SDK core helpers | `spindrel.bus` (BroadcastChannel, channel-scoped), `spindrel.cache` (TTL + inflight dedup), `spindrel.notify` (host-chrome toasts), `spindrel.log` (ring buffer + forward), `spindrel.ui.status`, `spindrel.ui.table`, `spindrel.form` (declarative + validation), iframe error boundary (postMessage to host), host-side receiver + toast stack + Reload button on widget-error banner. Skill doc updated with a new "SDK framework" section + anti-patterns. Python presence-snapshot test (34 cases) pins helper names. QA smoke widget at `app/tools/local/widgets/examples/sdk-smoke/index.html` exercises form + bus + notify + log + cache + ui.status + ui.table + sync-throw + async-reject. | **done** (2026-04-19, QA smoke added session 26 — see [[#Phase A.1 detail]]) |
| A.2a | web_search rewrite — **exit criterion** | Converted `integrations/web_search/widgets/web_search.html` to `spindrel.form` / `ui.status` / `callTool` / `bus`. 226 → 155 lines (31.4% reduction). New behavior: starred state syncs across multiple pinned copies via `spindrel.bus.publish("web_search:starred_changed", ...)`. Persist failures use `spindrel.notify("error", …)` (host chrome toast) instead of an inline banner. | **done** (2026-04-19 session 26) |
| A.2b.stream | `spindrel.stream(kind, filter, cb)` | New `GET /api/v1/widget-actions/stream` SSE multiplexer (`app/services/widget_action_stream.py`), reuses existing `channel_events.subscribe()` + replay ring + backpressure. Client uses `fetch()` + `ReadableStream` (not `EventSource`) so the widget bearer rides in the `Authorization` header. Overloaded call forms (single kind, array, opts object). Auto-reconnects with `since=lastSeq`. First real showcase: `app/tools/local/widgets/context_tracker/index.html`. 47 tests (10 new service + 37 presence-snapshot). | **done** (2026-04-19 session 27) |
| A.2b.state | `spindrel.state` versioning + migrations | Layered on `spindrel.data` — `schema_version` + ordered `{from, to, apply}` migrations. Per-path in-iframe mutex (`__stateLocks[path]`) serialises concurrent `load`/`save`/`patch`. File's `__schema_version__` field is the source of truth; missing = v1, newer than declared = throws (downgrade refusal). Cross-iframe RMW inherits the existing `data.patch` limitation (documented; Phase B's `spindrel.db` is the durable fix). Showcase: `app/tools/local/widgets/notes/` — a pinned-channel scratchpad whose schema upgrades `{text}` → `{markdown, createdAt, updatedAt}`. | **done** (2026-04-19 session 30) |
| A.2b.chart | `spindrel.ui.chart` | Minimal inline-SVG line / bar / area helper. Sparkline-first defaults (40px tall, no axis, `spindrel.theme.accent`, fills container width via `viewBox` + `vector-effect="non-scaling-stroke"`). Accepts `number[]`, `{y}[]`, or `{x,y}[]`. Opts: `type`, `height`, `color`, `min`/`max`, `showAxis`, `strokeWidth`, `format`, `emptyMessage`, `label`. Context Tracker extended with a rolling 20-point utilization sparkline under the gauge. | **done** (2026-04-19 session 28) |
| A.2b.log | Dev Panel "Widget log" subtab | New Zustand store (`ui/src/stores/widgetLog.ts`, cap 500) consumes the existing `spindrel.log` postMessage contract. Host handler in `InteractiveHtmlRenderer.tsx` enriches each entry with `{pinId, channelId, botId, botName, widgetPath}` via a ref (so the one-time `useEffect` doesn't stale-close over token-late `botName`) before calling `pushWidgetLog(...)`. New `ui/app/(app)/widgets/dev/WidgetLogView.tsx` rendered via a segmented "Tool calls / Widget log" toggle in RecentTab — two-pane list/detail, level filter (All/Info/Warn/Error), Clear button, per-pin attribution row. Skill doc's log section + common-mistakes row updated to point at the new subtab. | **done** (2026-04-19 session 29) |
| B | Backend process layer | `widget.yaml` manifest, `widget.py` handler dispatch via `run_script` sandbox, `spindrel.db` SQLite per bundle, cron → Task scheduler, event subscriptions → channel bus, `widget_reload` SSE signal. | not started |
| C | Integration presentation layer | DX-5b unblock (non-channel `/workspace/widgets/<slug>/` root), integration widget catalog, "Widgets" tab on integration admin pages with one-click pin, version-bump notifications + auto-migrations. Dog-food: Frigate. | not started |
| D | Widget → Integration promotion | *Documented only, not built here.* Future track: one-click promote a pinned widget into `integrations/<slug>/` with seeded `integration.yaml`. | deferred |

## Phase detail

### Phase A.1 detail (shipped 2026-04-19)

**Files touched.** Single UI file (`ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx`) plus two doc/test adds. No schema changes, no backend changes.

- `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx` — bootstrap IIFE grew ~270 LOC of new helpers; `window.spindrel` now exposes `bus` / `cache` / `notify` / `log` / `ui` / `form`. Component gained `toasts` / `widgetError` / `reloadNonce` state, a `message` listener scoped to `iframeRef.current.contentWindow`, a toast stack rendered top-left above the iframe (auto-dismiss 4s, click-to-dismiss), and a widget-error banner with a **Reload** button that bumps `reloadNonce` (iframe `key` includes it → clean remount without affecting parent state).
- `skills/html_widgets.md` — new "SDK framework — Phase A helpers" section with copy-paste examples for every helper; table of new anti-patterns ("hand-rolling a form", "swallowing errors", etc.); `window.spindrel` API quick-reference expanded with the new entries.
- `tests/unit/test_widget_preamble_helpers.py` — presence-snapshot: 34 cases pin every helper function definition, every `window.spindrel.*` export, the error-boundary wiring, the host-side receiver, and that the skill doc documents each new helper. Backstop until a Vitest/Jest runner lands in `ui/`.

**Scope / non-goals.**

- **Pure client-side.** No new endpoints, no schema migrations, no run-script sandbox reach. Everything lives in the iframe preamble + host React component.
- **`bus` is channel-scoped only** — `BroadcastChannel("spindrel:bus:" + (channelId || "global"))`. User-dashboard cross-widget pubsub needs the dashboard slug threaded through the iframe (not done; deferred to Phase B along with `spindrel.stream` since both require plumbing through new props).
- **`log` forwards but nothing consumes yet.** Host receiver swallows `log` messages intentionally. The Dev Panel "Widget log" subtab is Phase A.2 — the postMessage contract is already stable.
- **`ui.chart` is explicitly NOT shipped.** Called out in "What's NOT in Phase A" section of the skill doc so bots don't assume it's there.
- **`spindrel.state` (versioning + migrations) NOT shipped.** Tooling pattern is easy to sketch but correct semantics around concurrent migrators + migration failure modes needs more thought. `spindrel.data.*` continues to work.

**Known risk areas for the QA pass.**

- **BroadcastChannel browser support.** Guarded with `typeof BroadcastChannel !== "undefined"` — silent no-op on older browsers. Chrome/Firefox/Safari ≥15.4 are fine. Edge cases where the iframe is torn down mid-publish won't throw (try/catch around postMessage).
- **Iframe reload via `key={`widget-iframe-${reloadNonce}`}`** — destroys the iframe DOM entirely, so anything the widget held in its window is gone. State in `state.json` / `widget_config` survives. Document-side state inside the iframe (scroll, focus, open modals) is lost; that's the trade for clean crash recovery.
- **Toast stack capped at 5** (`prev.slice(-4)` + new one). Notifications older than the cap drop without warning — keep notify messages terse.
- **Host receiver filters by `event.source !== iframe.contentWindow`.** If any ancestor page opens another iframe that also posts `{__spindrel: true}` messages, they're ignored — but a malicious widget could spoof the envelope shape. Since widgets are same-origin and bot-authored anyway, the check is an isolation guard, not a security boundary.
- **`spindrel.form` does its own render on every input event is NOT done.** Input events only update `state.values`; the form only re-renders on submit (for the submitting/disabled state flip) or on external `set()` / `reset()` calls. That's intentional — re-rendering on every keystroke would lose focus. If per-field real-time validation is wanted, it belongs on the `input` listener hook rather than a full re-render.
- **`spindrel.cache` error path** — on fetcher throw, the entry is deleted rather than kept with an error state. Next call re-fetches cold. If a widget's upstream is flapping, this can hammer — cap retries at the widget layer.

**Verification done this session.**

- Python: `pytest tests/unit/test_widget_preamble_helpers.py -v` → 34/34 passed.
- Python regression: `pytest tests/unit/test_emit_html_widget.py tests/unit/test_widget_flagship_catalog.py tests/unit/test_html_widget_scanner.py tests/unit/test_widget_actions_state_poll.py -q` → 72/72 passed.
- UI: `cd ui && npx tsc --noEmit` → clean (exit 0, no output).
- **NOT done session 25**: `npx vite build`, manual smoke in a pinned widget, behavior verification in a real channel. These are Phase A.1 QA.

### Phase A.1 QA smoke widget (shipped 2026-04-19 session 26)

- `app/tools/local/widgets/examples/sdk-smoke/index.html` — 165-line single-file bundle exercising every A.1 helper in one surface: `spindrel.form` (level + message), `spindrel.bus.publish/subscribe` on topic `smoke:ping` (requires 2 pinned copies to see the round-trip — BroadcastChannel does not echo to the same window), `spindrel.notify` across all four levels, `spindrel.log` with dump-to-console + clear controls, `spindrel.cache.get` with a 3s TTL on `Date.now()` rendered in the header chip, `spindrel.ui.status("empty")` for the received-table empty state, `spindrel.ui.table` for the received log, sync-throw button (`throw new Error` → `error` postMessage → red banner + Reload), async-reject button (`Promise.reject` → `unhandledrejection` → same banner).
- Frontmatter: `SDK smoke` card with `qa / sdk / smoke` tags + activity icon so it's findable in the Add-widget catalog after being copied to a channel workspace.
- Placement under `app/tools/local/widgets/examples/` is a reference-bundle convention — the scanner walks channel workspaces, so to smoke-test a bot needs to either inline-emit the content or copy it into `data/widgets/sdk-smoke/` on a channel.

### Phase A.2b.stream detail — `spindrel.stream` + Context Tracker (shipped 2026-04-19 session 27)

**Files shipped.**

- `app/services/widget_action_stream.py` — new 100-line async generator that wraps `channel_events.subscribe()`, filters by `ChannelEventKind`, always passes control frames (`SHUTDOWN`, `REPLAY_LAPSED`), fires 15s keepalives, and tears down cleanly. `parse_kinds_csv()` helper validates the query-string kind list with a clear `ValueError` for unknowns.
- `app/routers/api_v1_widget_actions.py` — new `GET /stream` endpoint. Auth via the router's existing `verify_auth_or_user` dep (widget JWT or user JWT). Unknown kinds → 400. `StreamingResponse(media_type="text/event-stream")` with `Cache-Control: no-cache` + `X-Accel-Buffering: no`.
- `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx` — `window.spindrel.stream` added to the bootstrap IIFE. Uses `apiFetch()` + `ReadableStream.getReader()` + `TextDecoder` (NOT `EventSource`) so the widget bearer rides in the `Authorization` header rather than leaking into a query string. Mirror of the approach in `ui/src/api/hooks/useChannelEvents.ts:178-225`.
- `app/tools/local/widgets/context_tracker/index.html` — **first real showcase widget**. Live context-window gauge for the pinned channel: renders `ContextBudgetPayload` (consumed / total / utilization / model) as an `sd-progress` bar with `warning` / `danger` color transitions, per-bot latest snapshot table, running activity list of the last 8 turns. Status dot pulses green during `turn_started`, turns amber with the tool name on `turn_stream_tool_start`, clears on `turn_ended`. Subscribes once via `spindrel.stream(["context_budget", "turn_started", "turn_ended", "turn_stream_tool_start"], cb)`; no polling.
- `skills/html_widgets.md` — "SDK framework" section gains a full `spindrel.stream` subsection with examples, the `stream` vs `bus` contrast, auto-reconnect + `replay_lapsed` semantics, and a pointer to the Context Tracker bundle. Quick-reference + Common Mistakes rows extended.
- `tests/unit/test_widget_action_stream.py` — new, 10 tests: CSV parser (5), kind filter drops non-matching events (1), no-filter passes every kind (1), `SHUTDOWN` bypasses filter + closes generator (1), `since=N` replays buffered events from the ring (1), `aclose()` unregisters the subscriber (1).
- `tests/unit/test_widget_preamble_helpers.py` — `HELPER_DEFINITIONS` += `function stream` / `function __streamNormalizeArgs`; `SPINDREL_KEYS` += `stream:`.

**API surface (final).**

```js
spindrel.stream("new_message", cb)                       // one kind
spindrel.stream(["turn_started", "turn_ended"], cb)      // several
spindrel.stream(["tool_activity"], filterFn, cb)         // + predicate
spindrel.stream({ kinds, channelId, since }, filterFn?, cb)  // full form
// returns unsubscribe()
```

**Key behaviours.**

- Client-side kind whitelist mirrors the `ChannelEventKind` enum; typos throw before any network call.
- Auto-reconnect: exponential backoff 1s → 30s, capped at 10 retries, always passes `since=lastSeq` so the bus replay ring fills the gap without widget-side bookkeeping.
- `replay_lapsed` → host toast ("Stream replay lapsed — some events may be missing") **and** the callback fires so the widget can refetch baseline state if it needs to.
- `shutdown` sentinel → stream closes without reconnect. When the server comes back up the widget's next `spindrel.api()` call will re-mint.
- Generator teardown uses the exact same cancel-pending / await-cancellation / `aclose` dance as `api_v1_channels.channel_events`, avoiding the "asynchronous generator is already running" race.

**Auth posture.**

- Router dep = `verify_auth_or_user`. Widget JWTs work (carry bot scopes). User JWTs work. No extra scope gate in this slice — bot visibility over the channel + `channels:read` scope on the bot's API key are the ceiling. Per-pin capability scoping lands in Phase B when `widget.yaml` declares `permissions:`.
- Channel ownership is trusted from the query string the same way `callTool` trusts its `channel_id` arg today. If the bot's token can't see the channel it just won't see the events.

**Showcase widget notes.**

- `context_tracker` reads `ContextBudgetPayload` fields straight off the wire: `bot_id`, `consumed_tokens`, `total_tokens`, `utilization`, `model`. Source: `app/domain/payloads.py:313`.
- Multi-bot channels: each `bot_id` gets its own row in the "Per-bot latest" section, sorted by most-recent-update.
- On first pin with no traffic the gauge shows "awaiting first turn…" — there's no initial REST fetch because the bus doesn't persist the last `context_budget` value. Acceptable — the next turn fills it in. If this becomes annoying, `GET /api/v1/channels/{id}/state` is the place to add a "latest context budget" field.
- Stale-dot self-heal: a 10s interval softens the status back to "idle" if no turns are in flight. Covers a hypothetical case where a `turn_ended` event races past us.

**Verification.**

- `pytest tests/unit/test_widget_action_stream.py tests/unit/test_widget_preamble_helpers.py -v` → 47/47 passed.
- `pytest tests/unit/test_emit_html_widget.py tests/unit/test_widget_flagship_catalog.py tests/unit/test_html_widget_scanner.py tests/unit/test_widget_actions_state_poll.py -q` → green.
- `cd ui && npx tsc --noEmit` → clean.
- **NOT done**: manual smoke on test server. User handles deploy cycle.

### Phase A.2b.state detail — `spindrel.state` + Notes showcase (shipped 2026-04-19 session 30)

**Files shipped.**

- `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx` — three new helpers in the bootstrap IIFE: `stateLoad(path, spec)`, `stateSave(path, object)`, `statePatch(path, patch, spec)` (~150 LOC), plus `__stateLocks` per-path mutex (`__withStateLock(path, fn)`) that chains awaitable callers on a `Promise`. Exposed at `window.spindrel.state`. Internal `stateLoadInner` avoids re-entering the mutex when called from inside `statePatch`.
- `app/tools/local/widgets/notes/index.html` — new showcase (~170 LOC). Pinned-channel scratchpad with markdown edit/save, toggle between render + edit modes, keyboard affordances (Cmd/Ctrl-Enter saves, Escape cancels). Schema history: v1 `{text}` → v2 `{markdown, createdAt, updatedAt}`; the migration fills `markdown` from `text`, initialises `createdAt` if absent, stamps `updatedAt`. `display_label: Notes` + icon + tags for catalog discovery.
- `tests/unit/test_widget_preamble_helpers.py` — `HELPER_DEFINITIONS` += `function stateLoad|stateSave|statePatch`; `SPINDREL_KEYS` += `state:`; skill-doc assertion += `window.spindrel.state`.
- `skills/html_widgets.md` — quick-reference block gains three `window.spindrel.state.*` lines; new prose subsection `### state — versioned data.load with schema migrations` under `ui.chart` with a full v1→v2 example, the migration contract (idempotent, one-hop, deep-cloned), downgrade-refusal note, and the concurrency caveat pointing at Phase B's `spindrel.db`. `spindrel.state` removed from the "What's NOT in Phase A" list. Common-Mistakes row on `state.json` rewritten to steer toward `spindrel.state.load` when the shape might drift.

**API surface (final).**

```js
// Load + auto-migrate (persists the upgraded state back to disk):
const state = await spindrel.state.load("./state.json", {
  schema_version: 3,
  defaults: { items: [] },
  migrations: [
    { from: 1, to: 2, apply: (s) => { s.items = s.tasks; delete s.tasks; return s; } },
    { from: 2, to: 3, apply: (s) => ({ ...s, createdAt: s.createdAt || Date.now() }) },
  ],
});

// Save (preserves __schema_version__ from disk when the caller omits it):
await spindrel.state.save("./state.json", { ...state, items: [...] });

// RMW deep-merge patch with migrations:
await spindrel.state.patch("./state.json", { items: [...] }, spec);
```

**Key behaviours.**

- **`__schema_version__` stamped on every persisted object.** Missing field on disk → treated as v1 (so a brand-new bundle deployed with `schema_version: 2` migrates `{}` → `{..., __schema_version__: 2}` on first read).
- **One-hop migrations only.** Each step declares `from: N, to: N+1`; the runner looks up `migrations.find(m => m.from === v)` and advances. Missing a step throws — bundle-upgrade mistakes fail loud rather than silently dropping fields.
- **Downgrade refusal.** If `file_version > declared`, throws: `"spindrel.state: <path> was written by schema vN but the bundle declares vM — refusing to downgrade"`. Prevents a rolled-back bundle from silently truncating user data.
- **Per-path in-iframe mutex.** `__stateLocks[path]` is a chained `Promise`. Kicking off two `state.load("./state.json", ...)` concurrently inside one iframe waits for the first to finish before the second reads — the second sees the already-migrated state.
- **Cross-iframe RMW inherits `data.patch`'s race.** Documented in the skill; the Phase B `spindrel.db` layer is the durable fix. In practice, most pinned widgets have channel-unique state paths and this isn't hit.
- **Migrations run on a deep-cloned object.** Return `state` to mutate in place, or a fresh object to replace wholesale. The return value is what gets persisted.

**Showcase — Notes widget notes worth pinning.**

- The widget declares `schema_version: 2` and ships one migration. A user who pinned an older v1 copy of the widget (with `{text: "..."}`) auto-upgrades on first load — no manual intervention.
- `spindrel.renderMarkdown` is already in the SDK; the Notes widget uses it for the render-mode view. The edit-mode `<textarea>` stays markdown-source; render flips back on save.
- `spindrel.log.info("notes: saved", n, "chars")` goes to the Dev Panel Widget log subtab — lets an author watching the dev panel see saves land in real time without console noise.
- On load failure, the widget renders `spindrel.ui.status(root, "error", { message })` rather than going silent. Downgrade refusals surface there too.

**Verification.**

- `pytest tests/unit/test_widget_preamble_helpers.py tests/unit/test_widget_action_stream.py tests/unit/test_emit_html_widget.py tests/unit/test_widget_flagship_catalog.py tests/unit/test_html_widget_scanner.py tests/unit/test_widget_actions_state_poll.py -q` → **130/130 passed** (+9 over session 29: 3 new `HELPER_DEFINITIONS` rows × stateLoad/Save/Patch, 1 new `SPINDREL_KEYS` row × state, 1 new `SKILL_DOC` assertion, plus widget-catalog regressions re-validated with the new Notes bundle).
- `cd ui && npx tsc --noEmit` → clean (exit 0). Hook-enforced on every edit.
- **NOT done**: manual smoke — pin Notes on a channel, edit markdown, confirm save + reload round-trips; manually prepare a v1 `state.json` and watch the migration run on load. User handles deploy.

### Phase A.2b.log detail — Dev Panel "Widget log" subtab (shipped 2026-04-19 session 29)

**Files shipped.**

- `ui/src/stores/widgetLog.ts` — new Zustand store. `WidgetLogEntry` = `{id, ts, level, message, pinId, channelId, botId, botName, widgetPath}`. Ring buffer capped at 500 entries (oldest drop when full). Exposes `push(entry)` and `clear()` actions, plus a `pushWidgetLog(entry)` convenience helper that calls `getState().push(entry)` without requiring the caller to pull from React context.
- `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx` — host-side message handler's `data.type === "log"` branch now routes to the store instead of swallowing. New `logContextRef` pattern: a `useRef` captures `{pinId, channelId, botId, botName, widgetPath}` on render; a second `useEffect` keeps the ref current as those props change; the one-time message-handler `useEffect` reads `logContextRef.current` for every incoming message. Necessary because the handler's `useEffect` uses `[]` deps by design (one listener registration per mount) — without the ref, `botName` (which arrives ~1s after mount from the `widget-auth/mint` query) would stale-close to `null` forever and every log entry would record "unknown bot".
- `ui/app/(app)/widgets/dev/WidgetLogView.tsx` — new 194-LOC sibling component. Two-pane layout mirrors RecentTab's tool-calls view (`flex-1 flex flex-col md:flex-row`, `md:w-[340px]` left rail). Left column: level-filter segmented control (All / Info / Warn / Error), entry count, Clear button, scrollable list (divide-y, newest first, level dot + message preview + bot/channel/pin row). Right column: selected-entry detail pane with a `<pre>` of the full message + a `{Bot, Channel, Pin, Widget path, Timestamp}` `<dl>`. Extracted to its own file to keep `RecentTab.tsx` well under the 1000-line split threshold (currently ~720 after the splice).
- `ui/app/(app)/widgets/dev/RecentTab.tsx` — added `view: "calls" | "log"` state + segmented toggle strip (Tool calls vs `Widget log (N)`) above the existing two-pane; body is a ternary between the new `<WidgetLogView />` and the original UI. `useWidgetLogStore` selector pulls just `entries.length` for the tab's count badge — keeps re-renders narrow.
- `tests/unit/test_widget_preamble_helpers.py` — `test_host_receiver_wired` now also asserts `pushWidgetLog` is called inside the handler and that the import `from "../../../stores/widgetLog"` is present in the renderer. Locks in the routing contract end-to-end.
- `skills/html_widgets.md` — `log` quick-reference line rewritten from "… for Dev Panel (coming)" to "… + live in Widgets → Dev → Recent → 'Widget log'". The prose subsection reflows to describe the new surface (filter, click-to-expand, per-pin attribution, 500-entry host cap). Common-Mistakes row's "visible without opening devtools" hint extended to call out per-pin attribution.

**UX details worth pinning.**

- **Newest-first order.** `filtered = pool.slice().reverse()` — the store pushes newest-to-tail for O(1) cap enforcement, but the human reads newest-to-top. The view owns the reversal, not the store.
- **Filter applies to a snapshot, not a live subscription.** Selecting a level doesn't purge other levels from the store; flipping back to "All" restores everything. Clear is the only destructive action.
- **No level gating on what gets captured.** `spindrel.log.info` / `warn` / `error` all arrive; the host's handler is level-agnostic. The filter is a view concern.
- **Tab-badge count.** `Widget log (23)` uses the full store size, not the filtered count. A widget spamming errors shouldn't be able to hide entries by virtue of the user having the "Info" filter active.
- **Empty-state copy is shaped as a tutorial.** "No widget logs yet. A pinned widget calling `spindrel.log.info(...)` will appear here." — someone arriving at the tab cold needs to know what produces entries.

**Authorization + privacy posture.**

- Widget logs never leave the browser. The postMessage contract is intra-iframe → same-origin parent window; no network hop. There's no backend store, no cross-user visibility, no persistence across reload. Two Dev Panel tabs open in different windows each see only the logs from widgets rendered in their own window.
- The Dev Panel itself is admin-gated via the existing tab's route guard. No bot-scope plumbing needed for this slice.

**Verification.**

- `pytest tests/unit/test_widget_preamble_helpers.py tests/unit/test_widget_action_stream.py tests/unit/test_emit_html_widget.py tests/unit/test_widget_flagship_catalog.py tests/unit/test_html_widget_scanner.py tests/unit/test_widget_actions_state_poll.py -q` → **121/121 passed** (49 preamble + 10 stream + 62 regression, all green).
- `cd ui && npx tsc --noEmit` → clean (exit 0). Hook-enforced automatically on every UI file edit.
- **NOT done**: manual smoke (pin the Context Tracker, call `spindrel.log.info("hello")` from devtools, see it arrive). User handles the deploy cycle.

### Phase A.2b.chart detail — `spindrel.ui.chart` + Context Tracker sparkline (shipped 2026-04-19 session 28)

**Files shipped.**

- `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx` — `function uiChart(...)` (~95 LOC) added to the bootstrap IIFE, exposed on `window.spindrel.ui.chart`. Pure iframe preamble work — no backend, no schema, no new endpoints.
- `app/tools/local/widgets/context_tracker/index.html` — extended with a rolling 20-point utilization series (`util[]`, cap `UTIL_CAP=20`) that renders through `sp.ui.chart(..., { type: "area", min: 0, max: 1 })` under the gauge. `pushUtil(u)` called on every `context_budget` event. Sparkline appears only once we have ≥2 points so the first turn still reads "awaiting first turn…" without a flat line under it.
- `skills/html_widgets.md` — new `### ui.chart — sparkline / line / bar / area` subsection with examples (sparkline, with-axis, points-form), options table, data-shape list, a "not in Phase A" list (tooltips, multi-series, palettes). Quick-reference line added. Common-Mistakes row: "Inlining Chart.js or hand-writing SVG for a small sparkline → use `ui.chart`". `ui.chart` removed from the "What's NOT in Phase A" list.
- `tests/unit/test_widget_preamble_helpers.py` — `HELPER_DEFINITIONS` += `function uiChart`; new `test_ui_chart_exposed_on_ui_namespace` asserts `chart:` is present inside the nested `ui: {}` block (the top-level `SPINDREL_KEYS` check only sees `ui:` itself); `test_skill_doc_documents_phase_a_helpers` now also asserts `window.spindrel.ui.chart` appears in the skill doc.

**API surface (final).**

```js
spindrel.ui.chart(el, numbers)                           // sparkline line, auto min/max
spindrel.ui.chart(el, numbers, { type: "area", min: 0, max: 1 })
spindrel.ui.chart(el, [{x,y}, ...], { type: "bar", showAxis: true, format: (v) => v.toLocaleString() })
```

Options: `type` (`"line"` default, `"bar"`, `"area"`), `height` (40), `color` (`spindrel.theme.accent`), `min`/`max` (auto), `strokeWidth` (1.5), `showAxis` (false; reserves 28px for min/max ticks when true), `format` (axis label formatter), `emptyMessage`, `label` (SVG `<title>`).

**Key behaviours.**

- **Fills container width.** `viewBox="0 0 200 <height>"` + `width="100%"` + `preserveAspectRatio="none"`. Strokes stay crisp at any width because every `<path>` / `<rect>` carries `vector-effect="non-scaling-stroke"`.
- **Flat series handled.** If `minY === maxY`, `maxY = minY + 1` so the line sits mid-band instead of collapsing to zero height.
- **Empty series** → `<div class="sd-empty">No data</div>` (or `emptyMessage`).
- **Single-point series** → centred in the inner width; no divide-by-zero in `sx`.
- **Re-render on update.** No retained state — widgets just re-call `ui.chart(el, values, opts)` after mutating their series. Cheap: one SVG rebuild per call.
- **Area fill** draws the line path closed back along the baseline with `fill-opacity="0.18"` — matches the accent-colour tint used in the sd-progress system.

**Non-goals (deferred explicitly).** Tooltips on hover, axes beyond min/max ticks, multi-series overlays, categorical colour palettes for bars, animated transitions. These don't belong in the "sparkline under a stat card" slice; if they ever become load-bearing, Phase B's `widget.py` can inline a third-party lib without changing the SDK contract.

**Showcase.** Context Tracker gains a rolling sparkline under the gauge that visualises the last 20 `context_budget` utilization values. Meta row shows `<n> pts · <latest %>`. The sparkline appears once ≥2 points are collected so the idle first-paint stays clean. Anchors to a fixed `0..1` domain so the line's altitude tracks true fill across an entire session rather than auto-fitting each window.

**Verification.**

- `pytest tests/unit/test_widget_preamble_helpers.py tests/unit/test_widget_action_stream.py -v` → 49/49 passed (new `test_ui_chart_exposed_on_ui_namespace` included).
- `pytest tests/unit/test_emit_html_widget.py tests/unit/test_widget_flagship_catalog.py tests/unit/test_html_widget_scanner.py tests/unit/test_widget_actions_state_poll.py -q` → 72/72 passed (regression guard on the broader widget surface).
- `cd ui && npx tsc --noEmit` → clean (exit 0).
- **NOT done**: manual browser smoke on a pinned Context Tracker. User handles the deploy cycle.

### Phase A.2a detail — web_search rewrite (shipped 2026-04-19 session 26)

**File touched.** `integrations/web_search/widgets/web_search.html` — full rewrite, no backend changes, same envelope + config shape.

**LOC delta.** 226 → 155 lines (-71 lines, -31.4%). Exit criterion ≥ 30% met.

**Surface changes (behavior).**

- **Starred-state persistence** — unchanged. Still dispatches `POST /api/v1/widget-actions` with `dispatch: "widget_config"` + `dashboard_pin_id`.
- **Cross-pin sync** — NEW. `spindrel.bus.publish("web_search:starred_changed", { starred })` on every toggle; peer subscriptions `applyStarred(next) + render()`. Pin the widget twice on the same channel dashboard and starring in one instantly reflects in the other.
- **Summarize** — now uses `spindrel.callTool("fetch_url", { url })` instead of hand-rolled `/api/v1/widget-actions` fetch. On failure, `spindrel.notify("error", msg)` fires a host-chrome toast in addition to the inline summary-panel error.
- **Persist failures** — `spindrel.notify("error", …)` instead of a sticky inline banner. Cleaner UX; the user can dismiss it without re-rendering.
- **Empty / error / "No results"** — `spindrel.ui.status(listEl, "empty"|"error", { message })` replaces the hand-rolled `emptyEl.hidden = false` + `errEl` dance.
- **`openUrl` fallback simplified** — dropped the no-op `window.open(url, "_blank")` fallback (the sandbox explicitly blocks popups); only `window.top.postMessage({ type: "spindrel:open-url", url })` remains.

**CSS reorg.** Inline per-element styles extracted into a `<style>` block with `#ws-list` scoping — net zero on bytes but the card HTML dropped ~15 lines of repeated inline style attributes.

**Tests.** No new unit tests — the widget has no backend seam to pin. Behavior verification is manual: pin in a channel, verify search renders + star toggles + summarize + the new cross-pin bus sync.

### Phase A — JS SDK framework (iframe-only)

**Goal.** Every pattern integrations re-implement becomes a one-liner in `window.spindrel.*`. Zero schema changes, zero new services. Pure work in the iframe preamble and the postMessage bridge.

**New helpers**

| Helper | Purpose | Mechanism |
|---|---|---|
| `spindrel.bus` | Widget ↔ widget pubsub on the same dashboard | `BroadcastChannel("spindrel:dashboard:<slug>")` — scoped per dashboard. `bus.publish(topic, data)`, `bus.subscribe(topic, cb)` returns unsubscribe |
| `spindrel.stream(kind, filter, cb)` | Live updates — subscribe to existing channel event bus | SSE to new `GET /api/v1/widget-actions/stream?kinds=...`. Reuses `app/domain/channel_events.py`. Filter by kind + optional args. Returns unsubscribe |
| `spindrel.form(el, spec)` | Declarative forms | Renders `sd-*` styled form from `{fields: [{name, label, type, required, options, validate}], onSubmit}`. Handles validation, error surfaces, submit disable/loading |
| `spindrel.ui.table(rows, cols)` | Tables | DOM-fragment helper with `sd-*` classes. Built-in empty state + skeleton |
| `spindrel.ui.chart(el, data, opts)` | Simple charts | SVG line/bar/area. Uses `window.spindrel.theme.accent`. Not Chart.js — covers 80% case |
| `spindrel.ui.status(el, state)` | Loading / error / empty / ready | Standardizes the fetch → render dance |
| `spindrel.cache` | TTL cache | `cache.get(key, ttl_ms, fetcher)`. Dedupes concurrent fetches |
| `spindrel.notify(level, msg)` | Surface status to host chrome | `postMessage` to host → toast on pinned widget card. info / warn / error |
| `spindrel.log` | Structured widget log ring buffer | Buffered; host exposes in Dev Panel RecentTab "Widget log" subtab |
| `spindrel.state` (alias for `spindrel.data` + versioning) | Versioned state.json | Adds `schema_version` + `migrations` parameter to `data.load`. First run applies migrations in order. RMW-safe |

**Error boundary** — wrap iframe `error` + `unhandledrejection`, forward via `postMessage`, host renders inline banner with "Reload" action.

**Files touched**
- `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx` (preamble expansion + error forwarding)
- `ui/src/components/chat/renderers/WidgetChromeToasts.tsx` (new — host-side toast listener)
- `app/routers/api_v1_widget_actions.py` (add `GET /stream` SSE multiplexer)
- `app/services/widget_action_stream.py` (new — channel_events → SSE bridge)
- `skills/html_widgets.md` (new section per helper, update Common Mistakes)

**Tests**
- `tests/unit/test_widget_action_stream.py` — SSE filter by kind + bot scope
- `tests/unit/test_widget_preamble_helpers.py` — snapshot / presence assertions per helper

**Exit criteria**
- ~~`integrations/web_search/widgets/web_search.html` rewritten with `spindrel.form` + `spindrel.ui.table` — net LOC reduction ≥ 30%, behavior preserved~~ — **done** 2026-04-19 session 26 (226 → 155 lines, 31.4% reduction; adds cross-pin starred sync via `spindrel.bus`)
- Dev Panel Widget log subtab renders structured logs from a live widget

### Phase B — Backend process layer

**Goal.** A widget bundle declares (and ships) its own Python handlers, SQLite schema, cron, event subscriptions. All run server-side under the bot's scopes — same sandbox as `run_script`.

**`widget.yaml` manifest**
```yaml
name: Project Status
version: 1.2.0
description: Live phase tracker
state_schema_version: 2
permissions:
  tools: [fetch_url, generate_image]        # whitelist; enforced at dispatch
  events: [channel_message_created]          # whitelist; widget.py can only subscribe to these
cron:
  - name: hourly_refresh
    schedule: "0 * * * *"
    handler: hourly_refresh
events:
  - kind: channel_message_created
    handler: on_new_message
db:
  migrations:
    - 001_init.sql
    - 002_add_priority.sql
```

**`widget.py` handler dispatch**
```python
from spindrel.widget import on_action, on_cron, on_event, ctx

@on_action("save_item")
def save_item(args):
    ctx.db.execute("insert into items (text, created) values (?, datetime('now'))", [args["text"]])
    ctx.bus.publish("items_changed", {})
    return {"ok": True, "id": ctx.db.last_insert_rowid()}

@on_cron("hourly_refresh")
def hourly_refresh():
    env = ctx.tool("fetch_url", url="https://example.com/api/status")
    ctx.db.execute("update state set last_fetched = ? where id = 1", [env["body"]])
    ctx.notify_reload()

@on_event("channel_message_created")
def on_new_message(evt):
    ctx.db.execute("insert into log(ts, text) values (?, ?)", [evt["ts"], evt["text"]])
```

- Dispatched via `POST /widget-actions` with `dispatch: "widget_handler"`, `handler`, `args`.
- Executes in `run_script` sandbox with a restricted `spindrel.widget` module providing `ctx.db`, `ctx.tool`, `ctx.bus`, `ctx.notify_reload`, `ctx.state`.
- Bot scope is the ceiling — `ctx.tool("x")` only works if the bot has `x` in its allowlist.
- Timeout: 30s. Long work goes through `schedule_task`.

**`spindrel.db` — server SQLite per bundle**
- Backed by `<bundle>/data.sqlite` in the channel workspace (or global workspace post-DX-5b).
- Access via `POST /widget-actions/db` with `{op: "exec"|"query", sql, params}`.
- WAL mode + serving-level `asyncio.Lock` keyed by file path.
- JS: `await spindrel.db.exec(...)`, `await spindrel.db.query(...)`, `await spindrel.db.migrate(version, [{from, to, sql}])`.
- Python: `ctx.db.execute(...)`, `ctx.db.query(...)`.
- Migrations auto-run on first access after version bump. Transactional.

**Cron + event wiring**
- Cron declarations register at manifest-load time into the existing Task Pipeline scheduler. Each entry becomes a scheduled `Task` invoking the widget handler. Fires under pin's `source_bot_id`.
- Event subscriptions register a listener on the channel event bus. Handler runs on match.
- Both respect `permissions:` whitelist. Subscribing to an undeclared event → manifest validation error at load time.

**Reload signal** — `ctx.notify_reload()` pushes `widget_reload` with `{pin_id}`. Iframe auto-subscribes via `spindrel.stream("widget_reload", {pin_id: self}, ...)`; re-fetches envelope without full reload.

**Files touched**
- `app/services/widget_manifest.py` (new — YAML parser + validator)
- `app/services/widget_handler_dispatch.py` (new — sandbox invocation)
- `app/services/widget_db.py` (new — connection pool per bundle, migration runner)
- `app/routers/api_v1_widget_actions.py` — new dispatch types `widget_handler`, `db_exec`, `db_query`
- `app/tools/local/run_script.py` — "widget mode" injects `spindrel.widget` module
- Task scheduler — register widget cron entries as Tasks
- `app/services/channel_events.py` — register widget event subscriptions
- `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx` — `spindrel.db`, `spindrel.callHandler`, auto-subscribe to `widget_reload`
- `app/tools/local/emit_html_widget.py` — validate manifest if present; surface errors
- `skills/html_widgets.md`

**Migration**
- Pin envelope already carries `source_path`; manifest loader walks up to `<bundle>/widget.yaml`.
- No DB changes on `widget_dashboard_pins`.
- Pin deletion cascades: drop cron Tasks + event subscriptions + do NOT delete `data.sqlite` (bundle file, survives unpin).

**Tests**
- `tests/unit/test_widget_manifest.py` — schema validation, permissions, migrations
- `tests/unit/test_widget_db.py` — concurrent writes, migration runner, schema_version
- `tests/unit/test_widget_handler_dispatch.py` — sandbox isolation, bot scope enforcement, ctx.*
- `tests/integration/test_widget_cron.py` — cron → Task → handler → DB → SSE → iframe
- `tests/integration/test_widget_event_subscription.py` — channel event → handler → DB

**Exit criteria**
- New reference widget `app/tools/local/widgets/examples/project-status/` (30-line widget.py + 10-line widget.yaml + 40-line index.html) — polls API on cron, stores history in SQLite, form-driven row add, live table via `spindrel.stream("widget_reload")`, cross-widget bus ping
- `integrations/web_search/widgets/web_search.html` rewritten to use SQLite for `starred[]` (currently `widget_config`)

### Phase C — Integration presentation layer

**Goal.** Integrations ship widgets as first-class UI. Widgets can live outside a channel workspace. Integration admin pages gain a "Widgets" tab with one-click pin.

**Primitives**
- **DX-5b unblock** — `/workspace/widgets/<slug>/` resolves to bot-scoped channel-agnostic root. Resolver in `app/services/workspace.py` + new workspace-file endpoint + iframe `resolvePath` grammar extension. Already planned in `skills/html_widgets.md` (search DX-5b).
- **Integration widget catalog** — `integrations/<name>/widgets/<slug>/{widget.yaml, index.html, widget.py?}` auto-scanned at boot into an in-memory registry (mirrors `integration_registry.py`, no DB).
- **Admin UI — Widgets tab on integration pages.** Lists catalog; "Pin to dashboard" uses existing `DashboardTargetPicker`. Pin copies bundle to channel workspace (channel dashboard) or global root (user dashboard).
- **Version notification.** Pinned widget's `version:` vs integration's current. On mismatch: hover pill "Update available"; one-click upgrades bundle + runs migrations.

**Dog-food.** Frigate — already has a hand-rolled widget + React admin page. Widget absorbs the dashboard-side functions once it has DB + handlers + cron. Admin page stays (creds, settings).

**Files touched**
- `app/services/workspace.py` — resolve `/workspace/widgets/<slug>/`
- `app/tools/local/emit_html_widget.py` — accept `/workspace/widgets/<slug>/index.html` path form
- `app/services/integration_widget_catalog.py` (new)
- `app/routers/api_v1_admin/integrations.py` — catalog + pin endpoint
- `ui/app/(app)/admin/integrations/[integrationId]/WidgetsTab.tsx` (new)
- `integrations/frigate/widgets/<primary>/` — real dog-food bundle

**Tests**
- `tests/unit/test_integration_widget_catalog.py`
- `tests/integration/test_widget_pin_from_integration.py`
- `tests/integration/test_widget_version_upgrade.py`

**Exit criteria**
- Frigate admin page has a Widgets tab; primary widget pinnable one-click
- Pinned widget survives integration restart; upgrades smoothly on integration version bump
- One global-scope widget (not tied to a channel) renders on a user dashboard

### Phase D — Widget → Integration promotion (documented, not built)

Deferred to a future track. The architecture above is designed to make promotion feasible:

- `widget.yaml` and `integration.yaml` share frontmatter (name, version, permissions, cron)
- `widget.py` handlers resemble integration tool functions — same sandbox, same `ctx`
- Future `/admin/widgets/<slug>/promote` button copies bundle into `integrations/<slug>/` + seeds `integration.yaml` from the widget manifest

## Key invariants

- **One Track, phased across sessions.** Plan agent set this direction; don't split.
- **No schema changes in Phase A.** Pure iframe-preamble work. If Phase A requires a DB migration, the plan is wrong.
- **Bot scope is the authorization ceiling.** `ctx.tool(...)` and `dispatch:"widget_handler"` both inherit the emitting bot's scopes. No viewer-credential leakage.
- **state.json stays.** `spindrel.data.*` is not removed. `spindrel.db` is additive.
- **No "legacy" framing.** Additive SDK; existing widgets keep working.
- **Skill doc is the user-facing reference.** `skills/html_widgets.md` updated same-session as each phase ships.

## Critical files

- `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx:169-628` — spindrel bootstrap (Phase A major touch)
- `app/routers/api_v1_widget_actions.py` — dispatcher (Phase A stream + Phase B handlers)
- `app/tools/local/run_script.py` — sandbox reused for `widget.py`
- `app/tools/local/emit_html_widget.py` — path grammar + manifest validation hook
- `app/domain/channel_events.py` — event kinds for subscriptions
- `app/services/html_widget_scanner.py` — catalog discovery (extend for integration widgets in Phase C)
- `app/services/dashboard_pins.py` — pin lifecycle; add cron+event cleanup on delete

## References

- Plan: `~/.claude/plans/drifting-purring-kahan.md` (status: executed for Phase 0 only)
- [[Track - Widget Dashboard]] — dashboard surface this track builds on
- [[Track - Widgets]] — underlying tool-renderer system (YAML templates); this track does NOT touch that
- [[Architecture Decisions#Interactive HTML Widgets Authenticate as the Emitting Bot]] — auth invariant carried into `widget.py`
- `skills/html_widgets.md` — user-facing reference, updated per phase
