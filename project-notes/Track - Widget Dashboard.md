---
tags: [agent-server, track, widgets, dashboard, dev-panel]
status: active
updated: 2026-04-23 (native widget file-route contract)
---
<!-- session: 20 — P5 code shipped, UNTESTED; session 22 — cohesiveness + mobile polish pass landed (does NOT close P5-qa); session 2026-04-19 — P7 sandbox context + grouping -->

# Track — Widget Dashboard + Developer Panel

> **⚠️ SESSION HANDOFF — P5 code shipped but NOT yet user-tested.** Automated tests are green (112 across dashboard + widget-packages), tsc + vite build clean. User manual QA still pending and fix-up sessions expected. Do **NOT** close the track, remove it from Roadmap Active, or file it under Completed Tracks until the testing checklist below is signed off. The Completed Tracks entry appended in session 20 was premature and has been moved back; if you see a stray "Widget Dashboard" block in `Completed Tracks.md`, delete it.
>
> **When resuming**: read [[#Testing checklist — P5]] first, then the [[#P5 known risk areas]] list before debugging anything. Plan: `~/.claude/plans/ancient-churning-bubble.md` (status: executed).

> **2026-04-21 perf note — remounts are not refreshes.** P0 request-storm cleanup landed in the widget host path after dashboard↔chat switching started re-triggering the same iframe setup work. `InteractiveHtmlRenderer` now gives `/widget-auth/mint` and path-mode HTML content real React Query lifetimes (`staleTime`/`gcTime`, no refetch-on-mount/reconnect), and `PinnedToolWidget` keeps a session-local "recently refreshed" timestamp per pin so a just-polled widget does not immediately hit `/widget-actions/refresh` again on route remount. New invariant: switching surfaces inside the same session should reuse fresh iframe inputs unless an explicit timer/event invalidates them.
>
> Follow-up in the same session: persisted chat turns now act as an explicit invalidation source for library-backed HTML widgets. `MessageBubble` inspects persisted `file` tool calls; when a bot writes/moves/restores paths under `widget://bot/<name>/...` or `widget://workspace/<name>/...`, the UI invalidates only the matching `interactive-html-widget-content` query keys for that library ref. New invariant: library widget HTML should re-fetch because the bot changed that widget bundle, not because the iframe remounted or the host wanted to "check again."
>
> **2026-04-21 widget bundle versioning follow-up.** Bot/workspace-authored library bundles are now git-backed at the bundle-library root (`<ws_root>/.widget_library/.git`, `<shared_root>/.widget_library/.git`). The `file` tool creates one revision per successful mutating tool call that touches a `widget://bot/...` or `widget://workspace/...` bundle, `widget_library_list` now surfaces `versioned` + `head_revision`, and bots can inspect/restore source history through `widget_version_history` / `rollback_widget_version`. `describe_dashboard` also reports `bundle_revision` for library-backed pins. New invariant: widget source history is bundle-scoped, append-only, and rollback is implemented as a new restore commit rather than a history rewrite.
>
> Follow-up after that: pinned HTML widgets now keep the iframe document itself alive across dashboard↔chat switches. `InteractiveHtmlRenderer` parks dashboard-pin iframes in a hidden document-level lot keyed by `dashboardPinId`, then reattaches the same DOM node when the pin renders again. New invariant: route switches should not tear down the widget's in-iframe JS state unless the widget HTML actually changes or the user explicitly reloads it.
>
> Safety bound added immediately after: the parked iframe lot is not unbounded. Idle parked iframes now evict after 5 minutes, and the pool only keeps up to 12 parked entries before evicting the oldest parked ones. New invariant: keepalive is for quick surface switches, not indefinite background retention.
>
> Dashboard overflow follow-up on 2026-04-21: the full dashboard page now owns vertical overflow instead of the individual rail/grid/dock canvases. `ui/app/(app)/widgets/index.tsx` keeps the page surface on `overflow-auto`, and `ui/app/(app)/widgets/ChannelDashboardMultiCanvas.tsx` no longer clamps the three edit-mode columns to a shared viewport height or gives rail/dock their own `overflow-y-auto` containers. New invariant: if any dashboard column grows taller than the viewport, the only vertical scrollbar should sit at the page edge, not inside a column.
>
> Editor-geometry follow-up on 2026-04-21: the channel dashboard edit surface body is now one unified zone-aware canvas instead of three sibling canvases. Header stays separate, but rail + center grid + dock now render into a single measured CSS grid with fixed outer tracks (`300px` rail, `320px` dock) around the existing center 12/24-column grid. New invariant: center pins keep their existing `grid_layout.x/w` semantics, while rail/dock pins stay visually aligned with chat without needing separate drag/drop surfaces.
>
> Same-day edit affordance follow-up: dashboard edit mode now treats the host header/title lane as the primary drag handle instead of requiring a precise grab on the tiny grip icon, while keeping header action buttons outside the drag surface. Transparent/plain widgets also get a faint host-owned dashed frame in edit mode so resize edges remain legible even when the widget body has no visible panel chrome. New invariant: edit-mode affordances must be visible and forgiving even for HTML widgets that render with minimal internal framing.
>
> Host-header parity follow-up: rail/dock widgets no longer get forced into the floating overlay-chrome path just because of their zone. If a widget is eligible for a host-rendered title/header, it should render equivalently in the center grid and side rails; overlay chrome is now reserved for edit-mode cases where titles are intentionally hidden.
>
> Same-day fix after UI verification: panel-surface widgets now fall back to the generic host title row when they do not explicitly request an authored `panel_title`. New invariant: `panelSurface` changes the preferred title mode, but it must not suppress the host header entirely for rail/dock tiles that lack `show_panel_title`.
>
> Unified-canvas reorder follow-up: rail/dock list drops now use the same insertion-index repack path for both same-zone and cross-zone moves. New invariant: dragging within a side rail must rewrite that list's sequential `y` layout, not early-return just because the pin stayed in the same zone.
>
> Same-day correction after user validation: rail/dock are not compact sortable lists in the unified editor; they are one-column absolute-`y` zones. Drop handling now snaps the dragged pin to the released row in that column and only pushes overlapping siblings downward, preserving intentional empty space. New invariant: a rail/dock pin must be draggable to any valid vertical slot in its column without being compacted back upward.
>
> Drag-overlay keepalive follow-up: the edit-mode drag overlay no longer mounts a second live `PinnedToolWidget` for the active pin. It now renders a lightweight static preview so iframe-backed HTML widgets keep their pooled document attached to the real tile during drag. New invariant: drag-preview chrome must never compete with the real widget host for the same `dashboardPinId` iframe.
>
> Edit-mode persistence follow-up: dashboard layout mutation is now explicit-mode only. Channel-dashboard drag tiles are disabled when `?edit` is absent, chat-side rail/dock mirrors are read-only, and chat↔dashboard navigation preserves the `edit=true` query so only the dashboard's own toggle changes mode. New invariant: view mode must be inert, and edit state must persist only through explicit URL/button changes rather than accidental drags.
>
> Top-bar polish follow-up: destructive/maintenance actions should not compete with primary navigation affordances. `Reset layout` moved out of the dashboard action row into the settings drawer, and the empty header-slot hint is now chip-sized instead of using the generic tall canvas placeholder. New invariant: the header drop target should preserve chat-chip height, and the top-right action cluster should stay focused on mode/navigation rather than maintenance.
>
> **2026-04-21 edit-layout follow-up.** Dragging a widget on `/widgets` could blank an interactive HTML pin until full page refresh even though the tile shell stayed mounted. Root cause: the dashboard pin keepalive path reattached a pooled iframe after `react-grid-layout` remounts, but reused iframes do not reliably emit a second `spindrel:ready` handshake. `PinnedToolWidget` was still waiting on that signal before dropping its preload gate, so the widget stayed visually empty. `InteractiveHtmlRenderer` now treats pooled-iframe reuse as ready immediately after reattachment (plus a next-frame confirmation). New invariant: reattaching a parked dashboard-pin iframe must restore visibility without requiring a fresh iframe boot cycle or manual refresh.
>
> Same-day follow-up: the resize fix needed the same invariant for cross-panel moves inside `/widgets/channel/:id`. The header editor renders the runtime chat-chip scope even though the widget is still a dashboard pin, so `PinnedToolWidget` now keys readiness off the pooled dashboard-pin identity for every pinned-widget surface, not just dashboard-scope renders. New invariant: moving an interactive HTML widget between grid, rail, dock, and header must reuse the parked iframe without waiting on a fresh `spindrel:ready`.
>
> Header layout is intentionally reduced for now: the channel-dashboard header editor is a single centered chip slot that mirrors the actual chat header footprint. No intra-header reorder, no resize, no alternate widths. Dropping into the slot always snaps to the fixed layout; dropping onto an occupied slot replaces the current header widget and demotes the displaced pin back into the main grid at default size. Backend normalization now clamps stale header coords to that one canonical layout so old data cannot resurrect the previous "funky strip" behavior.
>
> **2026-04-21 localhost→remote dev follow-up.** Interactive HTML widgets were still assuming same-origin API routing inside the iframe preamble: `window.spindrel.apiFetch()` called `fetch(path)` directly, so running the UI at `http://localhost:5173` against a remote server sent widget traffic to Vite (`/api/v1/widget-actions`, `/widget-debug/events`, `/widget-actions/stream`) and exploded in 404s. The main app already used auth-store `serverUrl`; the iframe SDK now does too. `InteractiveHtmlRenderer` injects the configured `serverUrl` into `window.spindrel`, resolves app-relative widget SDK requests against it, and keeps absolute URLs untouched. New invariant: widget iframe API traffic must follow the configured backend origin, not the browser origin hosting the UI shell.
>
> **2026-04-21 CSP follow-up.** After routing iframe SDK requests to auth-store `serverUrl`, localhost→remote dev still failed because widget CSP only trusted `'self'`. The iframe policy builder now auto-appends the configured backend origin to central app-safe directives (`connect-src`, `img-src`, `media-src`, `frame-src`) instead of requiring per-widget `extra_csp`. `extra_csp` remains for third-party services; the first-party agent-server backend is now implicit. New invariant: if the UI is configured against a backend origin, interactive widgets may talk to that backend without per-widget CSP declarations.
>
> **2026-04-21 inspector polish follow-up.** `WidgetInspector.tsx` had drifted from the app's theme + clipboard patterns: the row-level "Copy JSON" action was calling `navigator.clipboard.writeText(...)` directly, which fails in plain-HTTP / denied-clipboard contexts and never surfaced success/failure, and the drawer error banner was still using raw `red-*` Tailwind classes. It now uses the shared `writeToClipboard()` fallback helper, shows transient copied/error button states, and keeps the detail/error surfaces on semantic theme tokens. Verification for this pass was `cd agent-server/ui && npx tsc --noEmit`; there is still no repo-wired UI test harness for a small drawer interaction regression test.

> **2026-04-21 shared HTML widget SDK styling pass.** Tightened the authorship contract for interactive HTML widgets: the host owns the outer dashboard tile shell, while the widget owns its inner composition. `InteractiveHtmlRenderer` now stamps `data-sd-host="pinned|inline"` and `data-sd-layout="grid|rail|dock|chip"` onto the iframe document/root so shared CSS can adapt by context without widget JS guessing. `widgetTheme.ts` was retuned toward an embed-first dashboard look: subtler inner panels, calmer spacing/type rhythm, stronger shared button/input/chip defaults, new `sd-label`, and `sd-card` repositioned as an optional inner panel primitive plus `sd-card--flat` for host-led layouts. Guidance updated in `skills/widgets/{styling,dashboards,html}.md`, and bundled examples (`sdk-smoke`, `context_tracker`) were refreshed to teach the new section/panel split. Verification: `cd agent-server/ui && npx tsc --noEmit`.

> **2026-04-22 scratch-session menu follow-up.** The `Sessions` menu's `New session` action no longer archives the current scratch session if that session is still an untouched empty draft. `ScratchSessionMenu.tsx` now waits for the current scratch-session lookup to resolve, detects the "blank accidental draft" case (`message_count=0`, `section_count=0`, no title/summary/preview), and reopens that existing session instead of calling `/sessions/scratch/reset`. New invariant: repeated accidental clicks on `New session` should not leave a trail of empty "new session" rows behind.
>
> Same-day UI cleanup: session rename inside the `Sessions` menu no longer uses the browser `window.prompt()` modal. It now edits inline in the selected row with native save/cancel controls, so the menu stays in-context and themed. The mini-chat dock's desktop resize target remains, but the visible dark corner glyph was removed; if the affordance cannot look intentional, the invisible hit-area is preferable to noisy chrome.
>
> **2026-04-22 focus-first chat panels follow-up.** Chat runtime panels now keep dashboard placement canonical while improving collapse/open behavior. The dashboard still owns `zone` + `grid_layout`; chat only resolves visibility. New shared panel geometry defaults both left workbench and right dock to 320px, and the channel dashboard editor imports the same constant so authoring preview does not drift. Per-channel panel prefs now own left/right open state, pin-open intent, widths, left tab, focus-mode restore state, mobile drawer state, and mobile expanded widget id; legacy global panel values only seed first-use defaults. Runtime layout protects chat width: right dock collapses first, single wide preferred panels degrade to overlay instead of squeezing chat, and collapsed panels now use full-height header-surface spines in their actual panel slots with direct Widgets/Files/Jump/Dock actions. The open right dock uses a slim dock-level top strip for collapse instead of a width-consuming control rail or duplicate edit button. Mobile drawer widgets now render as a compact widget deck with one expanded widget at a time. New invariant: panel state changes visibility/chrome only, never widget placement; closed-panel spines must never disappear.
>
> **2026-04-23 widget scrollbar + runtime rail chrome follow-up.** Hover-only scrollbars are now the dashboard chrome default (`hover_scrollbars: false` is the opt-out), and the interactive HTML iframe theme actually keys scrollbar CSS off `data-hover-scrollbars="1"` for root/body/nested scroll containers. Chat runtime rail/dock widgets now suppress host title/edit/debug/refresh/unpin chrome, including loading skeleton title rows; dashboard remains the edit/debug surface. The open right dock collapse affordance sits in a slim dock-level top strip so it is visible without overlaying widget content. New invariant: when host chrome says hover scrollbars, both the outer tile and the widget document should be quiet at rest and reveal scrollbars on hover/focus; chat rails mirror dashboard placement but do not reserve dashboard-authoring chrome.
>
> Same-day HTML SDK follow-up: the shared iframe `sd-*` theme was retuned again toward the newer native-widget language. Radii are tighter, chips/tags are no longer pill-shaped, buttons/inputs/menu surfaces carry less chrome, and `data-sd-host-surface="surface"` now quiets inner HTML panels further so pinned widgets do not look like nested mini-cards inside the host tile. New invariant: the host owns the visible outer frame; HTML widget CSS should default to low-chrome interior composition.

> **2026-04-23 context-tracker session-route follow-up.** Pinned native widgets on `/channels/:channelId/session/:sessionId` now treat the route `sessionId` as the viewed session for the matching channel instead of requiring the legacy `?scratch=true` marker. Session transcript rendering also passes `parentChannelId` into message bubbles, so native/tool widgets embedded in a non-main session can still resolve channel-scoped context while using the message's own `session_id`. New invariant: channel-scoped widgets must receive both the parent channel and viewed session on channel routes and channel-session routes; query params are only fallbacks, not the primary route contract.

> **2026-04-23 native file-widget follow-up.** Channel-facing widgets now open the file explorer through a durable route contract instead of local callback plumbing. New query params `files_path` and `open_file` are consumed by the channel page on `/channels/:channelId` and `/channels/:channelId/session/:sessionId`; when present, the page opens the Files panel, seeds the remembered folder, optionally opens the target file through the existing dirty-file guard, then scrubs the params. The same contract is used from `/widgets/channel/:channelId` during scratch-session detours, where `scratch_session_id` still maps back to `/channels/:channelId/session/:sessionId?scratch=true`. `channelExplorerPaths` now persists across reloads, so the Files tab and native file widget stay aligned on the same browsed folder. New invariant: file-navigation intent must travel through URL + shared explorer state, not ad-hoc widget-to-panel callbacks.
>
> **2026-04-23 channel file-panel UX follow-up.** Mobile Jump selections now clear the destination channel's persisted `mobileDrawerOpen` state before navigation, so jumping to another channel always lands in chat instead of reopening the OmniPanel. Mobile file selection is parent-owned: selecting a file now closes the drawer through the file-select action itself, fixing the old open-then-immediately-clear path caused by `onClose` reusing the "close explorer" handler. Desktop file viewing stays chat-first by default: the old triple-column auto-split is gone, the viewer's leading control is always `Back to chat`, split view is an explicit toggle, and split state resets when the file closes or the user changes channels. When file-only mode owns the width budget, the right dock spine stays visible but locked/disabled instead of silently failing. The left OmniPanel outer gutter was removed, and the Files tab header/tree now use tighter native chrome with clearer active-file and drag/upload affordances. New invariant: closing a panel never clears the current file; mobile file open closes the drawer via the select transition, not via a generic close path.

> 🚩 **SYSTEMIC — Dev panel bypasses the content_type dispatcher.** Surfaced 2026-04-18 (session 21). Every render point under `/widgets/dev/*` hardcodes `ComponentRenderer` instead of the mimetype-keyed `RichToolResult`. Any tool whose envelope isn't `application/vnd.spindrel.components+json` silently blanks in Recent / Tools / Editor — even though the same envelope renders correctly in chat. This makes the entire dev panel a **false oracle**: a tool that works in conversation can look broken in its own preview surface with zero signal why.
>
> Three call sites, all feed `<ComponentRenderer body={envelope.body} />`:
> - `ui/app/(app)/widgets/dev/ToolsSandbox.tsx:376`
> - `ui/app/(app)/widgets/dev/RecentTab.tsx:485`
> - `ui/app/(app)/widgets/dev/editor/PreviewPane.tsx:286`
>
> Content types affected today: `text/markdown`, `text/html`, `application/json`, `application/vnd.spindrel.diff+text`, `application/vnd.spindrel.file-listing+json`, `application/vnd.spindrel.html+interactive`, `text/plain` — i.e. everything except components-json. Caught during `emit_html_widget` QA because its envelope is `html+interactive`; the dev panel couldn't preview it even though chat could.
>
> Fix is scoped: replace the three call sites with `<RichToolResult envelope={envelope} ... />` (pass the full envelope, not just body, so content_type dispatch works). `NOOP_DISPATCHER` still wraps via `WidgetActionContext.Provider`. Recent tab additionally needs a short-circuit: when `rawResult._envelope` is present, skip `previewWidgetForTool`/`genericRenderWidget` and use the tool's own envelope — those endpoints flatten non-components content types into empty component trees.
>
> Related: [[#Tool output format hinting (`result_mime_type` / `output_schema`) — user-surfaced 2026-04-18]] felt necessary in large part because this bypass was hiding the fact that `RichToolResult` already handles every declared content_type. With the dispatcher reconnected in the dev panel, the mime-type hint work is mostly about getting tools to *declare* the content type they already imply by convention.

## Testing checklist — P5

Run these in order. Check off as you go. Bugs surfaced here feed into **P5-qa** in the Status table.

### Slice 1 — dashboard grid layout (biggest risk)

- [ ] **Migration 211 applies cleanly** on a DB with existing pins. `alembic upgrade head` in a container that was on 210; verify `grid_layout` column present and backfilled with non-empty `{x, y, w, h}` for every row (check via `select grid_layout from widget_dashboard_pins`). Backfill formula: `x = (position % 2) * 6`, `y = (position / 2) * 6`, `w = 6`, `h = 6`.
- [ ] **`/widgets` renders pins** with saved layout after hard refresh. Position the browser at desktop (≥1200px) — should see 12-col grid.
- [ ] **View mode is calm** — no drag handle (GripVertical), no pencil, no resize corner visible on any card. Cards hoverable but not draggable.
- [ ] **Edit layout toggle** (page header button, lucide `Move` icon) — click it, button flips to "Done" with `Check` icon and accent background. Every pin now shows grip + pencil + corner resize handle.
- [ ] **Drag to move** — grab a card by the GripVertical handle, drop in a new cell. Snaps to the 12-col grid. Other cards auto-compact vertically to close gaps. Drop fires `POST /pins/layout` within 400ms (watch Network panel).
- [ ] **Resize by corner** — drag bottom-right corner, card snaps to grid cells. `minW: 2, minH: 3, maxW: 12` enforced. Resize stop fires a layout commit.
- [ ] **Layout persists** across hard refresh (F5). Pin positions + sizes identical.
- [ ] **New pin added during edit mode** — pin from Tools sandbox, navigate back to dashboard — new pin auto-packs into first free slot, doesn't clobber existing layout.
- [ ] **Mobile / narrow width** — resize browser to <480px. Grid collapses to 2 cols (xxs breakpoint). Edit toggle still works.
- [ ] **Channel-scope OmniPanel pins still work** — open a channel with pinned widgets. They still render with the 350px max height cap, reorder still uses dnd-kit (NOT react-grid-layout). GripVertical visible. This is the regression risk from `PinnedToolWidget` scope-branching.

### Slice 2 — Edit Pin drawer

- [ ] **Pencil icon** only visible in edit mode, only on dashboard-scope pins.
- [ ] **Drawer opens** from the right with backdrop. Clicking backdrop closes it. X button closes it.
- [ ] **Display label rename** — type a label, Save — card header updates immediately; refresh — still there. Empty/whitespace label clears to NULL (header falls back to envelope-resolved name).
- [ ] **Widget config JSON editor** — current config pretty-printed on open. Edit, Save — `PATCH /pins/{id}/config` with `merge: false`. Refresh — persisted config identical to what was typed.
- [ ] **Invalid JSON** — red border on textarea, disabled Save, inline error text "Invalid JSON".
- [ ] **Reset to {}** link wipes config to empty object (still needs Save to commit).
- [ ] **"Saved." flash** on successful save (1.8s).
- [ ] **Action-dispatched button flips still work** — on a pin whose template has a toggle/config-dispatch button, clicking the button still merges (doesn't replace) via the action path.

### Slice 3 — Recent tab

- [ ] `/widgets/dev#recent` renders two-pane.
- [ ] **List populates** — at least recent tool calls from the last 24h show up.
- [ ] **Filter chips** — 1h / 24h / 7d / all — switching them refetches and list changes.
- [ ] **Tool filter dropdown** — narrows to just that tool.
- [ ] **Bot filter dropdown** — narrows to that bot.
- [ ] **Errors only toggle** — only red-dotted rows remain.
- [ ] **Row selection** — click a row, detail pane fills with args + result.
- [ ] **Rendered tab** — auto-tries template (if any), falls back to generic render. Shows the widget correctly.
- [ ] **Raw tab** — plain JSON tree OR stringified text.
- [ ] **"Import into Templates"** — navigates to Templates tab, `tool_name` + `sample_text` prefilled with this call's args/result. Refresh of Templates tab does **NOT** re-import (store is consumed once).
- [ ] **"Pin generic view"** — writes a dashboard pin, button flips to green "Pinned" with check icon for ~2.5s. Back on `/widgets` the pin is there with generic view rendered.
- [ ] **Session link** in the footer goes to the right `/admin/sessions/...`.

### Slice 4 — sample_payload seeds

- [ ] Open `/widgets/dev#library` on a fresh DB (or run the seeder). Pick `list_tasks`, `schedule_task`, `get_task_result`, `manage_bot_skill`, `get_system_status` — preview pane renders a populated widget on first open (not a blank "start typing").
- [ ] Edit a seed's sample_payload — Save → reload — custom payload sticks (user edit wins, reseed doesn't clobber on same content_hash).

### Cross-cutting

- [ ] **Existing users' pins** survive migration 211 without blank cards.
- [ ] **Broadcast sync still works** — toggle an HA light from a chat channel, dashboard pin reflects the change (and vice-versa).
- [ ] **Refresh intervals still work** — pins with `state_poll.refresh_interval_seconds` still auto-refresh at their cadence.
- [ ] **Pin from Tools sandbox** still works (P3 flow) — pin success chip, new pin lands on dashboard with a sensible default tile size (6x6).

## P5 known risk areas

Read before debugging — these are the places where the session-20 implementation made non-trivial decisions that could easily be wrong.

- **`PinnedToolWidget` scope-branching** — same component now has two sizing modes (`isDashboard ? "h-full flex flex-col" : ""` on outer; flex-1 body vs max-h[350px] body). A regression in OmniPanel rendering is the most likely fallout. Check `ui/app/(app)/channels/[channelId]/PinnedToolWidget.tsx` lines ~328+ if channel pins look wrong.
- **`useSortable` still called in dashboard scope** — the dnd-kit hook is called unconditionally (React hooks rule) but does nothing useful without a DndContext. The `sortableStyle` (transform/transition) is still applied via `style={sortableStyle}` — this *should* be a no-op but could collide with react-grid-layout's own transform if both try to animate the same node. If cards "jump" or double-animate during drag, that's the suspect.
- **`.widget-drag-handle` className** — now carried on the GripVertical in *both* scopes. react-grid-layout's `draggableHandle` selector matches it on dashboard; on channel-scope it's just a CSS hook with no handler. Harmless if nothing else in the app uses that class.
- **Layout backfill formula** — uses `(position % 2)` and `(position / 2)` to place in a 2-wide stack. This matches `_default_grid_layout()` in the service. If pin counts exceed expectations, rows may feel dense.
- **`react-grid-layout/legacy` import path** — 2.x's main `index.d.ts` uses v2 composable API; we're using the v1-compat `/legacy` subpath. If anyone bumps RGL to 3.x or later, this path may disappear — watch for import errors after dep upgrades. Also `@types/react-grid-layout` was uninstalled intentionally (v1 types shadow the bundled 2.x types); don't reinstall it.
- **`LayoutBulkRequest` pydantic validation** — silently coerces `"0"` → `0` but `"0.5"` → 400. If the server log shows parse errors here during drag, we're over-sanitizing.
- **`useWidgetImportStore.consume()`** runs once on WidgetEditor mount (`useEffect(..., [])`). If the editor is remounted by hash changes (e.g. `#templates` ↔ `#library`) it'll consume a stale payload. Watch for the Templates tab unexpectedly overwriting tool_name/sample when you didn't just click "Import into Templates".
- **`parseResult`** in `RecentTab.tsx` best-effort-parses `detail.result` as JSON and falls back to the string. Some tools emit JSON-with-a-trailing-newline or `[obj, obj]` arrays — the rendered tab may show unexpected output if the raw isn't a plain JSON object. If Rendered looks wrong, flip to Raw to see the actual body.
- **`sample_payload` strip** — seeder pops the key before YAML dump. An existing DB row whose `yaml_template` predates P5 will *still* have `sample_payload:` baked into the stored YAML body until a content_hash change forces a reseed. If you see `sample_payload:` appearing inside a Library editor's YAML pane for a seed widget, the content hash hasn't changed — minor cosmetic issue, fixes itself on next YAML edit.
- **Migration 211 downgrade** drops `grid_layout` — pin layout is lost on rollback. Expected; flagged here so no one is surprised.

## What IS known-good (tested pre-handoff)

- All migrations up through 211 apply in a fresh SQLite in-memory test DB.
- 112 automated tests green across `test_dashboard_pins.py`, `test_dashboard_pins_service.py`, `test_widget_packages_seeder.py`, `test_widget_package_validation.py`, `test_widget_packages_api.py`, `test_widget_preview_inline.py`, `test_tool_execute_api.py`.
- `npx tsc --noEmit` clean.
- `npx vite build` clean (bundle sizes noted in session log).
- Legacy RGL types vs. bundled types resolved (see risk notes).

## North Star
A **chat-less home for widgets** and a **Home-Assistant-style developer panel**. Two surfaces: `/widgets` (grid of pinned widgets, live via `state_poll`) and `/widgets/dev` (three tabs — Tools / Templates / Recent — for building and testing widgets without an LLM turn). Ad-hoc tool runs can pin directly to the dashboard.

Original plan: `~/.claude/plans/warm-inventing-planet.md`. Companion plans: `~/.claude/plans/generic-orbiting-fountain.md` (P2), `~/.claude/plans/frolicking-singing-penguin.md` (P3), `~/.claude/plans/concurrent-greeting-dahl.md` (P6).

Related: [[Track - Widgets]] (widget DX/robustness — the underlying system this surface consumes), [[Widget Authoring]] (reference), [[Widget Authoring Gaps]] (future `Track - Widget Authoring UX` seed).

## Status

| # | Phase | What | Status |
|---|-------|------|--------|
| P1 | Generic preview + dev panel skeleton | `/preview-inline` + `/preview-for-tool` endpoints; `/widgets/dev#tools` sandbox with list → args form → Run → raw JSON + rendered widget | **done** (2026-04-18 session 10) |
| P2 | Dashboard read path | Migration 210 `widget_dashboard_pins` + `/api/v1/widgets/dashboard` CRUD + `/widgets` grid + add-from-channel sheet + scope-aware `PinnedToolWidget` | **done** (2026-04-18 session 11) |
| P3 | Pinning from dev panel + MCP tool exec | Pin to dashboard button in `ToolsSandbox.tsx`; `admin_execute_tool` extended to dispatch MCP tools via `call_mcp_tool` (admin keys only) | **done** (2026-04-18 session 17) |
| P6 | Generic JSON widget (auto-pick, pin-only) | `app/services/generic_widget_view.py` + `POST /widget-packages/generic-render`; sandbox auto-falls-back to generic view when no template exists, pinnable as static card with `widget_config.generic_view: true` sentinel | **done** (2026-04-18 session 18) |
| P4 | Templates tab + Library consolidation | `#templates` as canonical widget editor (new/edit/fork via URL), `#library` as fourth sub-tab reusing existing list, Pin as card + Save to library, old `/admin/widget-packages/[id]` retired to redirect, Widget Library tab removed from `/admin/tools`. Preview-before-save unblocked as side effect. | **done** (2026-04-18 session 19) |
| P5 | Recent + Polish | `#recent` tab (ToolCall loader + "Import from real call"), **HA-style grid layout** (react-grid-layout, per-tile {x,y,w,h}, drag + resize), per-pin `widget_config` edit in place, sample_payload seeds for core shipped widgets | **code shipped, UNTESTED** (2026-04-18 session 20) |
| P5-qa | Manual QA + follow-up polish | User manual smoke across all four slices; fix-ups for regressions, mis-sizing, edge cases; track drop-ins from what surfaces during testing | not started |
| P5-polish | Cohesiveness + mobile pass | Dark-mode dropdown invariant fix, Library hierarchy, "Tools"→"Call tools", row-level "New"→hover-Plus icon, overlay standardization (4 surfaces), edit-mode visual affordance, DashboardTabs touch targets, mobile drag-disable + collapsible CTAs, dashboard danger-token sweep | **done** (2026-04-18 session 22) |
| P7 | Sandbox bot/channel context + grouping | `requires_bot_context` / `requires_channel_context` flags on `@register(...)`; always-visible BotPicker + ChannelPicker in `ToolsSandbox.tsx` (sticky via localStorage); `admin_execute_tool` accepts `bot_id`/`channel_id`, validates against flags, sets/resets ContextVars; `_do_state_poll` propagates pin's `source_bot_id`/`source_channel_id` so dashboard refresh respects identity; tool sidebar grouped collapsibly by `source_integration` with `Bot`/`Hash` icons for required-context tools; pin gating blocks Pin until bot/channel selected when required | **done** (2026-04-19) |
| P8 | Add-panel TLC + dev-panel dashboard context | Phase A: tool-calls endpoint surfaces `channel_id`, RecentTab propagates it on pin (kills "source_channel_id required" 400). Phase B: `DashboardTargetPicker` in `/widgets/dev` header — rich dropdown listing user + channel dashboards, `?from=<slug>` seed from Developer-panel link, localStorage persistence. Phase C: new `GET /widgets/dashboards/channel-pins` batch endpoint; "From channel" tab now reads `widget_dashboard_pins` (post-213) and hides on channel dashboards. Phase D: minimal-chrome pass on `AddFromChannelSheet` (drop panel/header/tab `border-b/l`). 4 new integration tests for batch endpoint. | **done** (2026-04-19) |
| P9 | Kiosk / fullscreen mode | `useKioskMode` hook drives `?kiosk=1` URL param; AppShell suppresses Sidebar/DetailPanel/CommandPalette/toasts; `/widgets/:slug` suppresses DashboardTabs / Breadcrumb; floating `KioskExitChip` (top-right, fades at 20% opacity after 3s idle). Best-effort Fullscreen API + Wake Lock + cursor-hide-on-idle all fire on a fresh user gesture from the toggle; Esc exits fullscreen AND kiosk. Desktop-only (hidden on mobile, also hidden in edit mode to prevent mid-drag accidents). | **done** (2026-04-19) |
| P10 | Panel-mode HTML widget | Migration 224 adds `widget_dashboard_pins.is_main_panel` + partial unique index (one panel pin per dashboard); `promote_pin_to_panel` / `demote_pin_from_panel` service helpers atomically clear-then-set + flip `grid_config.layout_mode`; `POST/DELETE /api/v1/widgets/dashboard/pins/{id}/promote-panel` endpoints; `emit_html_widget` gains `display_mode="inline"|"panel"` kwarg; `ToolResultEnvelope.display_mode` field round-trips through `_build_envelope_from_optin` + `compact_dict`. UI: `EditPinDrawer` Promote/Demote button (only on `html+interactive` envelopes); `WidgetsDashboardPage` branches into a 2-column `PanelModeView` when `layout_mode === 'panel'` AND a panel pin exists; mobile collapses to single column with the panel above the rail strip. Deleting a panel pin auto-reverts the dashboard back to `'grid'` mode. 8 new tests. | **done** (2026-04-19) |
| P11-a | RGL guardrails (layout DX, small) | Size-preset chips S/M/L/XL on `GridPreset` drive `applyLayout` from `EditPinDrawer`; Full-width toggle sets `w = cols.lg`, `x = 0` and falls back to M on un-toggle; Reset-layout button in edit-mode action bar with two-click confirm, uses `defaultLayoutForIndex` to repack every pin; edit-mode grid guides now render on all dashboards (not just channel ones — user dashboards had no cell lines before); column-index tick row appears while dragging; rail divider thickens + glows when the drag is inside the rail zone. No migration, no backend change. | **done** (2026-04-19) |
| P12 | Chat-screen positional zones | Channel dashboard IS the chat layout editor. Three positional chat zones: leftmost cols → `rail` (existing OmniPanel), rightmost `dockRightCols` (new, default 3/6) → `dock_right`, top row between them → `header_chip`. No `chat_zone` key — position alone drives membership; moving a tile via `apply_layout_bulk` shifts its zone on the next read. New `app/services/channel_chat_zones.py::classify_pin` + `resolve_chat_zones`; `GET /channels/{id}/chat-zones`; Python/TS preset parity guard in `tests/unit/test_grid_preset_parity.py`. Frontend: `ChatZone` union, `classifyPin` helper, `useChannelChatZones` selector, generalized `EditModeGridGuides` with three bands (rail / dock / header) that light up on drag intersection, `WidgetDockRight.tsx` (right-side dock, 320px default, localStorage width), `ChannelHeaderChip.tsx` (chip row with `+N` popover, singleton-free), `PinnedToolWidget` gains `compact: "chip"` scope (180×32 body, header hidden), `EditPinDrawer` gets read-only "Chat placement" readout. OmniPanel's rail filter swapped to the unified `useChannelChatZones.rail` — zero behavior change. Drive-by: tuned `focus:border-accent` → `/40` across 16 input-heavy files. 25 new tests + 19 passing green. Plan: `~/.claude/plans/wild-cuddling-eich.md`. | **superseded by P13** (2026-04-20) |
| P13 | Multi-canvas channel dashboard (replaces P12 mental model) | **The P12 positional model was invisible** — users couldn't predict which chat surface a widget would land on without opening a per-pin drawer. Replaced with four real canvases on the channel dashboard, each matching a chat-side surface 1:1: **Header Row · Rail · Main Grid · Dock**. `widget_dashboard_pins.zone` (enum `rail/header/dock/grid`, NOT NULL) is authored by which canvas the tile lives in; migration 226 backfills existing channel pins by inlining the old classifier rules once + rewriting coords to canvas-local. Runtime classifier + `rail_zone_cols` / `dock_right_cols` preset fields deleted. Cross-canvas moves via per-tile `ZoneChip` dropdown (extracted to its own file to avoid circular imports). Bucket names shortened on the API: `rail / header / dock` (dropped `dock_right` / `header_chip`). Fixed a React #310 hook-order bug in `EditPinDrawer` (useMemo below an early return) that was crashing the pencil button. 45/45 targeted tests green. Plan: `~/.claude/plans/crispy-wishing-sparkle.md`. | **done** (2026-04-20) |
| P11-b | Multi-canvas DnD polish | Ghost target-cell overlay in the grid canvas tracks live pointer and snaps to destination; padding-aware `pointerToCell` kills the 12px edge-bias; `pin-flash` pulse after every commit. Resize handles land bottom-LEFT + left-edge (`sw` / `w` added to `ResizeEdge`); `ResizeHandles.initial` upgraded to full `TileBox` so west-edge drags solve `x + w` together and the tile visually slides left as the pointer pulls; handles sit at ~40% opacity in edit mode instead of hover-only. Cross-canvas drops pointer-aware via DOM-measured insertion index (`insertionIndexByY` / `insertionIndexByX`) — drops land at the pointer's midline, not position 0. Default tile bumped to `6×10` (standard) / `12×20` (fine) on both UI preset + server `_default_grid_layout`. `WidgetDockRight` reserves its gutter the instant ≥1 dock pin exists, with a 220 ms width transition so late-arriving envelopes don't shove chat sideways. Stripped `surface/cc + backdrop-blur` from `channelHeaderBlock` — header, HUD strip, launchpad now sit on the page surface like rail/dock. 73/73 targeted tests green. Plan: `~/.claude/plans/vectorized-dancing-allen.md`. | **done** (2026-04-20) |
| P14 | Focus-first chat runtime panels | Dashboard placement remains canonical; chat gained shared panel geometry, per-channel runtime panel prefs, adaptive collapse/overlay resolution, full-height header-surface collapsed panel spines with direct panel destinations, wider remembered panel widths, palette/hotkey actions for collapse/restore/toggle/pin, hover-only widget scrollbars by default, and a mobile widget deck. Dashboard editor only imports the shared width constant to preserve runtime-preview parity. | **done** (2026-04-22; follow-up 2026-04-23) |

## Phase detail

### P1 — Generic preview + dev panel skeleton (done)
- `POST /api/v1/admin/widget-packages/preview-inline` — package-less preview; body `{yaml_template, python_code?, sample_payload, widget_config?, tool_name?}` → rendered envelope.
- `POST /api/v1/admin/widget-packages/preview-for-tool` — `{tool_name, sample_payload, widget_config?}`; resolves active DB package, falls back to in-memory registry for integration-declared widgets.
- Rail icon `LayoutDashboard` between Tasks and Bots; routes `/widgets` + `/widgets/dev`.
- `ToolsSandbox` + `ToolArgsForm` — three-pane tool sandbox.
- Session log: `vault/Sessions/agent-server/2026-04-18-10-widget-dashboard-dev-panel-p1.md`.

### P2 — Dashboard read/write + grid + add-from-channel (done)
- Migration 210 `widget_dashboard_pins`. Columns mirror `channel.config.pinned_widgets[]` shape. `dashboard_key='default'` reserved for multi-dashboard later.
- `WidgetDashboardPin` model; `app/services/dashboard_pins.py` CRUD; `app/routers/api_v1_dashboard.py` REST.
- `PinnedToolWidget` refactored: `channelId: string` → `scope: WidgetScope` discriminated union (`{kind:'channel', channelId} | {kind:'dashboard'}`). Reads both stores unconditionally (React hooks rule), routes writes by scope.
- `useDashboardPinsStore` parallel to `usePinnedWidgetsStore`. `broadcastEnvelope` cross-notifies — toggling a HA light in chat flips the dashboard card.
- `WidgetActionRequest` + `WidgetRefreshRequest` gained `dashboard_pin_id`. Scope-aware widget_config dispatch + refresh write-back.
- `AddFromChannelSheet` — copy semantics (channel pin stays; same entity can show on both surfaces).
- Session log: `vault/Sessions/agent-server/2026-04-18-11-widget-dashboard-p2.md`.

### P3 — Pin to Dashboard + MCP Tool Execution (done — this session)
- **Pin to dashboard** in `ToolsSandbox.tsx`: compact `PinActionBar` on the Rendered widget section header — label input (placeholder = tool display name) + `Pin to dashboard` primary button. Enter submits; on mobile the row stacks. Refresh hint under the input reads "Auto-refreshes every Ns." when `envelope.refreshable`, else "Static snapshot — will not auto-refresh." Pin success swaps the bar to a green pill `Pinned · Open dashboard →` for ~4s; click navigates to `/widgets`. Error surfaces inline above the rendered widget. Tool-switch resets pin state.
- Pin body shape: `{source_kind:'adhoc', source_bot_id:null, source_channel_id:null, tool_name, tool_args, widget_config:{}, envelope, display_label}`. No backend change — `CreatePinRequest` already accepts it.
- **MCP execute extension** — `app/routers/api_v1_admin/tools.py::admin_execute_tool` grew a branch: local tools preserve the bot-scoped permission check; MCP tools dispatch to `call_mcp_tool` but only for admin keys (bot-scoped keys receive 403 with a "admin keys only from this endpoint" hint). Signature-compatible (`call_mcp_tool(tool_name, arguments_json) -> str`), no session/bot/channel context needed. Unknown tool still 404s cleanly.
- Tests: `tests/unit/test_tool_execute_api.py` gained `test_execute_mcp_tool_admin`, `test_execute_mcp_tool_error_passthrough`, `test_execute_mcp_tool_bot_scoped_forbidden`. 13/13 green. Existing local-tool tests untouched.
- Backend verification reused in planning: `refresh_dashboard_pin` resolves `poll_cfg` by tool name alone; adhoc pins (no source bot) refresh fine when the widget template declares `state_poll:`. `PinnedToolWidget` already hides refresh affordances when `envelope.refreshable === false`.

### P4 — Templates tab + Library consolidation (done — session 19)

The original P4 spec called Templates a "stateless YAML evaluator." User rejected that framing during planning: it would have been ~80% duplicate of the mature Library editor at `/admin/widget-packages/[packageId]/`. Consolidated instead. Widget Dashboard dev panel is now **the** authoring surface.

- **Templates tab is canonical editor.** `/widgets/dev#templates` mounts `WidgetEditor` — lifted from the old admin route. Three modes via URL state:
  - no params → blank draft; Save creates a package and transitions to `?id=<newId>#templates`.
  - `?id=X` → load package X; editable unless `is_readonly`. Save PATCHes in place.
  - Fork is called from Library tab's `PackageCard` — mutation runs, navigates to `?id=<newId>#templates`.
- **Library tab is new `#library` sub-tab.** `LibraryTab` thin wrapper mounts the existing `WidgetLibraryTab` (reused verbatim from `admin/tools/library/` — no move). Shares the filter/source/grouping UI the user liked.
- **Tab order + default**: Library | Templates | Tools | Recent. Library is the landing board per user direction ("dashboard/dev panel seems like a good launching board").
- **Preview-before-save unblocked.** `PreviewPane` now branches on `isNew || !packageId`: calls `previewWidgetInline()` for drafts, `previewWidgetPackage()` for saved. Fixes item 8 of [[Widget Authoring Gaps]] in the same pass. Blank YAML shows a friendly "Start typing a YAML template" empty state instead of the old "Save the package first" gate.
- **Pin as card from Templates.** PreviewPane gained a Pin button in its toolbar (wired via `onPin?: (envelope) => Promise<void>` prop). TemplatesTab owns the dashboard store call; pin body stamps `widget_config: { draft_template: true, yaml, sample }` as a forward-compat sentinel for future live-refresh. Disabled with tooltip ("Set a tool name before pinning") until `tool_name` is set — a template pin needs a tool identity. Static v1 mirrors P6's pin semantics.
- **PreviewPane toolbar polish.** Added **Copy envelope JSON** button (addresses Dev Panel UX debt item: no copy affordance). Refresh button gained labeled responsive behaviour.
- **Save renamed to "Save to library"** in new-draft mode — matches the new mental model.
- **"Unsaved" chip** surfaces dirty state in the header.
- **Old routes retired:**
  - `/admin/widget-packages/[packageId]` → redirect stub in router.tsx (new `AdminWidgetPackageRedirect` component, reads `:packageId`, `<Navigate to=/widgets/dev?id=X#templates replace />`).
  - `/admin/widget-packages` (collection) → redirect to `/widgets/dev#library`.
  - Widget Library tab removed from `/admin/tools`. That page is now single-surface.
- **Navigation rewires:** `PackageCard` Edit/Fork, `ToolGroup` "New", `ToolWidgetSection` (all 5 links), `LibraryHero` gained a "+ New template" CTA. Admin `ToolsTab`'s `onOpenLibrary` now routes to `/widgets/dev?tool=X#library`.
- **Admin nav** loses "Widget Library" as a discoverable tab; discovery lives in the dev panel.

**Files changed**
- New: `widgets/dev/editor/{EditorPane,PreviewPane,WidgetPackageHeader,WidgetEditor}.tsx` (lifted + polished).
- New: `widgets/dev/TemplatesTab.tsx`, `widgets/dev/LibraryTab.tsx`.
- Updated: `widgets/dev/index.tsx` (4 tabs, Library default), `admin/tools/library/PackageCard.tsx`, `admin/tools/library/ToolGroup.tsx`, `admin/tools/library/LibraryHero.tsx`, `admin/tools/index.tsx`, `admin/tools/[toolId]/ToolWidgetSection.tsx`, `router.tsx`.
- Deleted: `admin/widget-packages/[packageId]/` (entire directory).

**Tests**: no backend changes → existing coverage stands (`test_widget_preview_inline.py`, `test_dashboard_pins.py`, `test_generic_widget_view.py`). tsc clean.

**Plan**: `~/.claude/plans/glimmering-tumbling-sky.md`.

### P5 — Recent + polish (done — session 20)

Four slices shipped together, all four of the Deferred/Known gaps are now closed:

**Dashboard grid layout (HA/Grafana-style).** Replaces `repeat(auto-fill, minmax(320px, 1fr))` with `react-grid-layout` (legacy v1-compat entrypoint). 12-col responsive (`lg:12, md:10, sm:6, xs:4, xxs:2`), 30px row height, `compactType: 'vertical'`. Each pin carries `{x, y, w, h}` in a new JSONB `grid_layout` column (migration 211), defaulted on create via `_default_grid_layout(position)` and backfilled on upgrade into a 2×N layout. View mode has no drag/resize handles — the new **"Edit layout"** header toggle turns them on (lucide `Move` / `Check`). `onLayoutChange` debounces commits 400ms into `POST /api/v1/widgets/dashboard/pins/layout` (atomic bulk write, rejects unknown ids). `PinnedToolWidget` scope-branches so channel-scope OmniPanel pins keep their `useSortable` + 350px cap; dashboard-scope fills the tile (`h-full flex flex-col`, body flex-1) and uses `.widget-drag-handle` selector for react-grid-layout to pick up.

**In-place per-pin edit.** New `EditPinDrawer.tsx` — right-side 420px drawer, backdrop, opens from the pencil icon that only shows in Edit mode. Two fields: `display_label` text input (backed by new `PATCH /api/v1/widgets/dashboard/pins/{id}`) and `widget_config` JSON textarea (uses existing `/config` endpoint with `merge: false` — Save replaces, not merges, since we're editing intent not flipping a button). Invalid JSON → red border + disabled Save; empty label clears to NULL; "Reset to {}" wipes config.

**Recent tab.** New `RecentTab.tsx`, two-pane mirror of `ToolsSandbox`. Left: filter bar (1h/24h/7d/all-time chips, tool picker, bot picker, errors-only toggle, refresh) + scrollable list of tool-call rows (cleaned tool name, server badge, bot, duration, relative timestamp, red `AlertCircle` for errors). Right: selected-call detail with arguments (`JsonTreeRenderer`), result tabs (Raw JSON / Rendered widget — tries `previewWidgetForTool` first, falls back to `genericRenderWidget`), two actions: **Import into Templates** and **Pin generic view**. Hands off to Templates via new `useWidgetImportStore` zustand store (tool name + sample payload — consumed once on editor mount so refreshes don't re-apply). Pin action writes `widget_config.imported_from_call` sentinel for future promotion bridge.

**`sample_payload` seeds.** `widget_packages_seeder._extract_sample_payload` pops the top-level `sample_payload:` key before the YAML is dumped into `yaml_template` and persists it to the DB column instead. Updated `tasks.widgets.yaml`, `bot_skills.widgets.yaml`, `admin.widgets.yaml` with realistic samples covering every `{{var}}` each template references. Reseed overwrites the DB sample when the YAML changes (same hash-diff path the template body already uses).

**Files**
- Backend: `migrations/versions/211_dashboard_pin_grid_layout.py` (new), `app/db/models.py`, `app/services/dashboard_pins.py` (+_default_grid_layout, +rename_pin, +apply_layout_bulk, extended serializer), `app/routers/api_v1_dashboard.py` (+`POST /pins/layout`, +`PATCH /pins/{id}`), `app/services/widget_packages_seeder.py`.
- Frontend: `ui/app/(app)/widgets/index.tsx` (react-grid-layout, edit mode, drawer host), `ui/app/(app)/widgets/EditPinDrawer.tsx` (new), `ui/app/(app)/widgets/dev/RecentTab.tsx` (new), `ui/app/(app)/widgets/dev/index.tsx` (mount Recent), `ui/app/(app)/widgets/dev/editor/WidgetEditor.tsx` (consume import store), `ui/app/(app)/channels/[channelId]/PinnedToolWidget.tsx` (scope-branch, pencil, drag-handle class), `ui/src/stores/dashboardPins.ts` (+applyLayout, +renamePin, +replaceWidgetConfig), `ui/src/stores/widgetImport.ts` (new), `ui/src/types/api.ts` (+GridLayoutItem).
- Seeds: `app/tools/local/tasks.widgets.yaml`, `bot_skills.widgets.yaml`, `admin.widgets.yaml`.

**Tests**: `tests/integration/test_dashboard_pins.py` (+5 layout/metadata tests), `tests/unit/test_dashboard_pins_service.py` (+4 rename/layout tests), `tests/integration/test_widget_packages_seeder.py` (+2 sample_payload tests). 112 green across the dashboard + widget-packages modules.

**Plan**: `~/.claude/plans/ancient-churning-bubble.md`.

**Notes**
- Legacy entrypoint: `react-grid-layout@2.2.3` ships its own types now. Its `@types/*` package is stale (v1 shape with `export = namespace`); I uninstalled it. Use `import { Responsive, WidthProvider, Layout, LayoutItem } from "react-grid-layout/legacy"` — v1-compat flat-props API. `Layout` in 2.x is `readonly LayoutItem[]`; individual tiles are `LayoutItem`.
- Resize handles come from `react-grid-layout/css/styles.css`; no separate `react-resizable/css/styles.css` import needed in 2.x.
- `position` column is retained as the fallback order used by older code paths (and by the migration backfill formula).

### P5-polish — Cohesiveness + mobile pass (done — session 22)

UI/UX pass over every widget surface (`/widgets` + `/widgets/dev` + 4 overlays + PinnedToolWidget). Plan: `~/.claude/plans/indexed-enchanting-crane.md`. Does **not** close P5-qa — manual smoke checklist still pending.

**Critical correctness**
- `LibraryFilterBar` was using `bg-input-bg` — not a real Tailwind class (canonical is `bg-input` per `tailwind.config.cjs`). The "All sources" dropdown was silently falling through to no background, making it dark-mode-unsafe. Same bug in `EditPinDrawer` JSON textarea + label input. Fixed.
- `WidgetEditor` modal used `z-[1000]/[1001]` arbitrary values; standardized on `z-50`/`z-[60]` and bumped backdrop to canonical `bg-black/60 backdrop-blur-[2px]`.
- `DashboardSkeleton` had inline `style={{ gridTemplateColumns }}`; converted to Tailwind `grid-cols-[repeat(auto-fill,minmax(320px,1fr))]`.
- `widgets/index.tsx` was using raw `red-500` Tailwind classes for layout-error / load-error banners; swapped to semantic `danger` token.
- `EditDashboardDrawer` + `CreateDashboardSheet` + `AddFromChannelSheet` had `text-red-400 / bg-red-500/10 / border-red-500/40` in error banners and the destructive Delete button. All converted to `danger` semantic token.
- `EditPinDrawer` "Saved." flash used hardcoded `text-emerald-400` — switched to `text-success`.
- `WidgetLibraryTab` had two `style={{ color: t.* }}` inline-style violations in the empty-state block; converted to Tailwind classes.

**Library — diagnosis-driven clarity**
User feedback: "I wasn't quite clear what I was looking at — that's a diagnosis in itself, and don't add chrome."
- `LibraryHero` description rewritten + "Read the docs" inlined into the same paragraph (one line saved). New copy: *"How tool results render as interactive widgets. Grouped below by the tool each template extends — one default per tool is active at a time."*
- `ToolGroup` header restyled: tool name now `uppercase tracking-wider text-[11px] text-text-muted font-medium` so it reads as a section header (not as another item-row). Count compressed to `(N)` instead of `(N packages)` — same data, less noise.
- Filter bar: "All sources" → "All integrations" (clearer term).
- Row-level "New" text button → icon-only `Plus` with `opacity-0 group-hover:opacity-100` reveal + `aria-label`/title `"New template for {toolName}"`. 44px hit area via `before:` pseudo-element extension. Same navigation behavior; one less visible CTA per row.

**Dev panel naming + tab focus**
- Tab "Tools" → "Call tools" (LABELS map only — hash key stays `#tools`, no link breakage).
- Tab buttons: `focus-visible:ring-2 focus-visible:ring-accent/40` for keyboard a11y. Active tab adds `font-semibold` for color-blind redundancy. `role="tablist"` / `role="tab"` / `aria-selected`.

**Overlay surface standardization** (4 sheets)
Single canonical pattern applied to `EditPinDrawer`, `EditDashboardDrawer`, `CreateDashboardSheet`, `AddFromChannelSheet`:
- Backdrop: `bg-black/60 backdrop-blur-[2px]` (was mixed: 40 opacity vs 60-with-blur).
- Width: `w-full sm:w-[440px]` (was mixed: 420 vs 440 vs `w-[440px] max-w-[92vw]`).
- Close button: `p-1.5 rounded-md text-text-muted hover:bg-surface-overlay hover:text-text transition-colors` + `<X size={16} />` + `aria-label="Close"`.

**Dashboard polish**
- **Edit-mode affordance** — when toggle ON, the entire `ResponsiveGridLayout` is wrapped in a dashed-border accent-tinted container (`border border-dashed border-accent/40 bg-accent/[0.03] p-2`). Communicates "you are now editing." Hidden in view mode and on mobile.
- **DashboardTabs round buttons** (+ New / Edit dashboard): `h-7 w-7` → `h-9 w-9` visual + `before:absolute before:inset-[-4px]` to extend touch hit area to ~44px without visual change. WCAG-compliant.
- **Active dashboard tab** adds `font-semibold` for color-blind redundancy.
- **Drag handle visibility** — `PinnedToolWidget` `GripVertical`: view mode `opacity-50 group-hover:opacity-100` (was `opacity-30 hover:opacity-70` — too faint), edit mode `opacity-80 hover:opacity-100`. Removed `style={{ color }}` inline style; uses `text-text-muted` Tailwind class.

**Mobile-friendliness pass** (core: dashboards)
- Viewport tracker (`window.matchMedia("(max-width: 767px)")`) on the dashboard page.
- `layoutEditable = editMode && !isMobile` — drag/resize is force-disabled on mobile even when edit mode is on. When user toggles edit on mobile, a status banner appears: *"Layout editing is desktop-only. View pins as configured."*
- Header CTAs ("Edit layout" / "Add widget" / "Developer panel") collapse to icon-only below `sm` via `hidden sm:inline` on text labels. `aria-label` keeps screen readers informed.
- `LibraryHero` "New template" CTA collapses text below `sm` too.
- `WidgetEditor` capture-sample modal: `max-h-[80vh]` → `max-h-[85svh]` so iOS keyboard doesn't push content off-screen.
- Dev panel tab strip: `overflow-x-auto` + `shrink-0` per tab so 4 tabs scroll horizontally on phones.
- Dashboard padding: `p-6` → `p-4 md:p-6` so dashboards aren't clipped on phones.

**Files touched**
- `ui/app/(app)/widgets/{index,DashboardTabs,EditPinDrawer,EditDashboardDrawer,CreateDashboardSheet,AddFromChannelSheet}.tsx`
- `ui/app/(app)/widgets/dev/index.tsx`, `ui/app/(app)/widgets/dev/editor/WidgetEditor.tsx`
- `ui/app/(app)/admin/tools/library/{LibraryHero,LibraryFilterBar,WidgetLibraryTab,ToolGroup}.tsx`
- `ui/app/(app)/channels/[channelId]/PinnedToolWidget.tsx`

**Out of scope (deferred — see [[Loose Ends]])**
- Shared `<Tabs>` / `<Drawer>` / `<Button>` primitives — biggest cohesiveness lever but expands beyond widgets.
- Mobile stacking of `RecentTab` (340px sidebar) and `ToolsSandbox` (260px+ side panels) — both two-pane layouts that don't fit on a phone.

**Tests**: `npx tsc --noEmit` clean. UI-only; no backend tests touched.

### P7 — Sandbox bot/channel context + tool grouping (done — 2026-04-19)

Closes the dev-panel false-oracle bug for tools needing agent identity (`list_api_endpoints`, `exec_command`, workspace tools, screenshot, file_ops, etc.) and adds preflight signal so the user sees what context each tool needs before running it.

**Registry contract.** Two new optional kwargs on `@register(...)` (`app/tools/registry.py`): `requires_bot_context: bool = False`, `requires_channel_context: bool = False`. New accessor `get_tool_context_requirements(name) -> (bool, bool)`. Annotated 35 local-tool decorators + 10 integration-tool decorators by auditing every `current_bot_id.get()` / `current_channel_id.get()` call site. `ToolOut` (admin tools API) emits both flags so the frontend can badge tools and gate Run/Pin.

**Execute endpoint** (`app/routers/api_v1_admin/tools.py`). `ToolExecuteRequest` grew `bot_id` + `channel_id`. Pre-call validation: required-flag missing → 400; unknown bot id → 400; non-UUID channel id → 400. Provided values set `current_bot_id` / `current_channel_id` ContextVars via `.set()` token, reset in `finally` (mirrors `step_executor.py:826` pattern). Bot-scoped key permission check unchanged — still capped to bot's `local_tools` + carapace tools.

**Sandbox UI** (`ui/app/(app)/widgets/dev/ToolsSandbox.tsx`). Always-visible "Run as" panel between tool description and args form: BotPicker + ChannelPicker (both with `allowNone`, persisted to `localStorage["spindrel:widgets:dev:context"]` so refreshes survive). Per-context `Required` / `Optional` chip — Required goes red when unset. Run button disabled with reason caption when required context missing. Pin button disabled with tooltip until bot/channel selected (when required). Selected bot/channel pass through both `executeTool({bot_id, channel_id})` and `pinWidget({source_bot_id, source_channel_id})`. Picker selection is sticky across tool switches — iterating against one bot persona is the common flow.

**Tool sidebar grouping.** Bucketed by `source_integration` with "Built-in" (`app/tools/local`) first, others alphabetical. Section headers collapsible (state persisted in localStorage). Per-tool row badges: `Bot` icon (10px, text-text-dim) when `requires_bot_context`, `Hash` icon when `requires_channel_context` — tooltips spelled out.

**Refresh path** (`app/routers/api_v1_widget_actions.py`). `_do_state_poll` gained `bot_id` / `channel_id` kwargs and ContextVar setup around the `call_local_tool` / `call_mcp_tool` invocation. Three callers updated: `_dispatch_tool` (forwards from `WidgetActionRequest`), `refresh_widget_state` (looks up `WidgetDashboardPin.source_bot_id` / `source_channel_id` when `dashboard_pin_id` set, falls back to request fields for inline channel widgets), `_dispatch_widget_config` (pulls from the patched pin's serialized dict, parses channel UUID defensively). Frontend already passed `dashboard_pin_id`; no UI hook changes needed.

**Tests** — 73 green across the targeted slice:
- `tests/unit/test_tool_execute_api.py` +5 (`test_execute_sets_bot_and_channel_context`, `test_execute_requires_bot_context_400`, `test_execute_requires_channel_context_400`, `test_execute_unknown_bot_id_400`, `test_execute_invalid_channel_uuid_400`).
- `tests/unit/test_widget_actions_state_poll.py` +2 (`test_bot_and_channel_context_set_during_call`, `test_context_unset_when_no_bot_passed`).
- `tests/unit/test_registry.py` +3 (default-false, round-trip, unknown-tool).
- `tests/integration/test_dashboard_pins.py` regression — all 16 still green.

**Files**
- Backend: `app/tools/registry.py`, `app/routers/api_v1_admin/tools.py`, `app/routers/api_v1_widget_actions.py`.
- Backend annotations (45 files): `app/tools/local/{emit_html_widget,api_access,discovery,experiment_tools,pipelines,subagents,responses,forms,todos,workspace,tasks,send_file,plans,search_history,image,manage_hooks,pin_panel,heartbeat_tools,file_ops,exec_tool,exec_command,delegation,docker_stacks,bot_skills,capabilities,attachments,conversation_history,skills,channel_workspace,memory_files,summarize_channel}.py`; `integrations/{slack/tools/{scheduled,bookmarks,pins},frigate/tools/frigate,excalidraw/tools/excalidraw,bluebubbles/tools/bluebubbles,claude_code/tools/run_claude_code,google_workspace/tools/gws}.py`.
- Frontend: `ui/app/(app)/widgets/dev/ToolsSandbox.tsx`, `ui/src/api/hooks/useTools.ts`.
- Tests: `tests/unit/{test_tool_execute_api,test_widget_actions_state_poll,test_registry}.py`.

**Plan**: `~/.claude/plans/linear-marinating-hammock.md` (executed).

**Out of scope** (intentional)
- DB columns / migration for the flags — registry is the source of truth, served live via `_to_out`. No reindex needed.
- EditPinDrawer "set bot after the fact" field — strict gate (block pinning until bot selected) per user direction. Add later if the gate proves too strict.
- Generic-view fallback for tools that need context but the caller doesn't supply it — they hard-error in the sandbox now (which surfaces the issue instead of silently degrading).
- Skills tagged in `discovery.py::get_skill_list` — left unflagged since it gracefully no-ops without bot context (filters private skills only).

### P6 — Generic JSON widget (done — session 18)
- **Backend**: new `app/services/generic_widget_view.py::render_generic_view(raw_result, *, tool_name, config)`. Deterministic JSON → component-tree auto-picker. Rules: top-level scalars → `properties`; homogeneous-object arrays → `table` (columns union, capped at 8, rows at 50); scalar arrays → indexed `properties`; one-level-nested objects → `heading` + `properties`; deeper nesting collapsed to "+N more sections". Body capped at 50 KB — oversized payloads render a "Result too large" status block instead. Returns an envelope with `content_type: application/vnd.spindrel.components+json`, `refreshable: false`, `display: inline`. Accepts raw strings (best-effort JSON parse) and primitives.
- **Endpoint**: `POST /api/v1/admin/widget-packages/generic-render` (admin scope). Body: `{tool_name, raw_result, config?}`. Returns the standard `PreviewOut` shape so it slots into the existing frontend `PreviewResponse` type. Colocated with `preview-inline` / `preview-for-tool` in `app/routers/api_v1_admin/widget_packages.py`.
- **Frontend**: `ToolsSandbox.tsx::handleRun` now falls back to `genericRenderWidget()` when `previewWidgetForTool` returns no envelope (no template for this tool). The returned envelope flows into the existing render + pin UI unchanged. A new `isGenericView` flag drives two things: a small "Generic view" pill next to the "Rendered widget" section header (with tooltip pointing at the authoring track), and stamping `widget_config: { generic_view: true }` on pin for forward-compat when v1.1 introduces configurable generic views. Tool-switch resets the flag.
- **What this unlocks**: every local and MCP tool without a widget template can now be pinned as a static dashboard card. No picker UI, no YAML authoring required. Plan deliberately kept minimal per the authoring-surface reframe — see [[Widget Authoring Gaps]].
- **Non-goals (still)**: no auto-application in chat (channels still show raw JSON for untemplated tools); no refresh (generic pins are static snapshots); no picker UI in the pin flow (sophistication belongs in the template builder).
- Tests: `tests/unit/test_generic_widget_view.py` (17 cases) + `tests/integration/test_widget_generic_render.py` (5 cases). 22/22 green. Regression sweep across `test_tool_execute_api`, `test_widget_preview_inline`, `test_dashboard_pins` — 53/53 green.
- Plan: `~/.claude/plans/concurrent-greeting-dahl.md`.

### P9 — Kiosk / Fullscreen Mode (done — 2026-04-19)

Landing phase from the four-part presentation/authoring plan (`~/.claude/plans/typed-bubbling-hoare.md`). Smallest + fully independent slice — no schema, no backend. Ships a presentation-grade view of any dashboard at `/widgets/:slug` and `/widgets/channel/:channelId`.

**Behavior.** A new `Kiosk` toggle in the dashboard actions bar flips `?kiosk=1` on the current URL. When set, `AppShell` suppresses the Sidebar, DetailPanel, StreamingToast, ApprovalToast, ActiveWorkflowsHud, ToastHost, and CommandPalette; `WidgetsDashboardPage` suppresses the `DashboardTabs` / `ChannelDashboardBreadcrumb` top bar. The dashboard grid fills the viewport edge-to-edge. A floating `KioskExitChip` (top-right, z-50, fades to 20% opacity after 3s idle, full opacity on hover) provides the exit path; Esc (via fullscreen exit) also exits kiosk. Desktop-only (hidden on mobile — fullscreen API is flaky on touch, and there's no sidebar worth hiding there) and hidden while editing (prevents mid-drag accidents).

**Kiosk hook (`ui/src/hooks/useKioskMode.ts`).** Single primitive — reads `?kiosk=1` from `useSearchParams`, exposes `enter` / `exit` / `idle`. Side-effects are all best-effort so the hook degrades cleanly on platforms without the APIs:
- **Fullscreen**: calls `document.documentElement.requestFullscreen()` on enter (fresh user gesture from the toggle click). Esc → `fullscreenchange` listener also clears `?kiosk=1` so Esc behaves as "exit kiosk", not "exit fullscreen-but-keep-chrome-hidden".
- **Wake Lock**: `navigator.wakeLock.request("screen")` on enter; re-acquired on `visibilitychange` → visible (spec: locks auto-release when the tab is hidden); released on exit/unmount. Ignores permission errors silently.
- **Idle cursor hide**: 3-second timer that sets `idle = true`. Consumer applies `cursor-none` on the dashboard wrapper via Tailwind. Any mousemove/keydown/touchstart resets.

**Files changed.**
- New: `ui/src/hooks/useKioskMode.ts` (191 LOC), `ui/app/(app)/widgets/KioskExitChip.tsx` (31 LOC).
- Modified: `ui/src/components/layout/AppShell.tsx` (reads `KIOSK_PARAM`, wraps chrome elements in `!kiosk` guards — unmount not `display:none` since none of those components carry warm state worth preserving), `ui/app/(app)/widgets/index.tsx` (new actions-bar toggle, suppresses top bar, applies `cursor-none` wrapper class, mounts exit chip).

**Tests.** UI has no vitest harness set up; `npx tsc --noEmit` clean. Manual smoke checklist: `/widgets/default?kiosk=1` direct URL (shareable), toggle in + out, Esc exits, Wake Lock held through ~5 min (screen doesn't dim on Linux/Chrome), cursor fades after 3s idle + reappears on mousemove, no regression on existing dashboard edit flow.

**Out of scope (intentional).** No per-dashboard kiosk settings, no auto-rotation between dashboards, no kiosk-only pin subset. The feature is "show this dashboard as-is, full-bleed" — deliberately minimal.

### P10 — Panel-mode HTML widget (done — 2026-04-19)

Second slice of `~/.claude/plans/typed-bubbling-hoare.md` (P9 was the first). Lets a single HTML widget pin claim the dashboard's main area while every other pin renders in a rail strip alongside it. Useful for self-contained mini-apps (status board, dashboard chrome, single-pane reports) that shouldn't be faked as a 12-wide × 30-tall RGL tile.

**Schema.** Migration 224 adds `widget_dashboard_pins.is_main_panel boolean NOT NULL DEFAULT FALSE` + a partial unique index (`uq_widget_dashboard_pins_main_panel`) keyed on `dashboard_key WHERE is_main_panel = TRUE` so at most one panel pin can exist per dashboard. The index uses both `postgresql_where` and `sqlite_where` predicates — SQLite ≥3.8.0 supports partial indexes, so the same constraint enforces in both runtimes. `WidgetDashboard.grid_config` JSONB carries the new key `layout_mode: "grid" | "panel"` (default `grid`); no DB migration needed since it's just a JSONB key.

**Service layer.** `app/services/dashboard_pins.py::promote_pin_to_panel(pin_id)` — atomically clears `is_main_panel` on every other pin in the same dashboard, sets it on this one, and flips `grid_config.layout_mode='panel'`. The clear-then-set order matters under the partial unique index: a single statement that flipped two rows would briefly violate the constraint. `demote_pin_from_panel(pin_id)` clears the flag and reverts `layout_mode` to `'grid'` (key removed) when no panel pin remains. `delete_pin` was extended to fire the same revert when the deleted pin was the panel pin — without it, the dashboard would render as an empty main area.

**Routes.** `POST /api/v1/widgets/dashboard/pins/{pin_id}/promote-panel` and `DELETE` counterpart, both gated on `channels:write`. Both return the serialized pin so the optimistic-rollback loop on the client has the canonical post-state.

**Tool layer.** `emit_html_widget` gained `display_mode: "inline" | "panel" = "inline"`. When `"panel"`, the envelope carries `display_mode: "panel"` (only — `"inline"` is the default and not serialized). `ToolResultEnvelope.display_mode` field added; `compact_dict` only emits the key when non-default; `_build_envelope_from_optin` parses + validates incoming envelope payloads and discards anything that isn't `"inline"` or `"panel"`. The hint exists so the pinning UI can default the Promote checkbox to ON without a manual click — the user still confirms via EditPinDrawer.

**Frontend.** `EditPinDrawer.tsx` gained a Promote/Demote button block visible only when `pin.envelope.content_type === 'application/vnd.spindrel.html+interactive'`. `WidgetsDashboardPage` computes `layoutMode = currentDashboard?.grid_config?.layout_mode ?? 'grid'` and `panelPin = pins.find(p => p.is_main_panel)`; when both line up, the page renders `PanelModeView` instead of `ResponsiveGridLayout`. `PanelModeView` is a flex 2-col layout (`flex-col-reverse lg:flex-row`): rail strip on the left (320px), panel pin filling the remainder. The rail strip is a plain flex stack rather than a sub-RGL — `w/h` lose meaning when the column is fixed-width; reordering moves to `EditPinDrawer` if that ever becomes necessary. Mobile collapses to a single column with the panel above the rail (headline content stays first-paint visible). The page's outer container switches from `overflow-auto` to `overflow-hidden flex flex-col min-h-0` in panel mode so the panel pin's iframe can fill the viewport edge-to-edge.

**Store.** `useDashboardPinsStore.promotePinToPanel` / `demotePinFromPanel` do optimistic local writes (clear all `is_main_panel` flags + set the target's, or flip false), call the new endpoints, and trigger a `useDashboardsStore.hydrate()` so the dashboard's `grid_config.layout_mode` refreshes without a full reload. Lazy import of `dashboards` store breaks the load-time cycle.

**Files**
- Backend: `migrations/versions/224_widget_dashboard_pin_main_panel.py` (new), `app/db/models.py`, `app/services/dashboard_pins.py` (+`promote_pin_to_panel`, +`demote_pin_from_panel`, +`_set_dashboard_layout_mode`, extended `delete_pin` + `serialize_pin`), `app/routers/api_v1_dashboard.py` (2 new endpoints), `app/tools/local/emit_html_widget.py` (+`display_mode` schema/kwarg), `app/agent/tool_dispatch.py` (`ToolResultEnvelope.display_mode` + opt-in parse + compact serialize).
- Frontend: `ui/app/(app)/widgets/index.tsx` (panel-mode branch + `PanelModeView`), `ui/app/(app)/widgets/EditPinDrawer.tsx` (Promote/Demote button block), `ui/src/stores/dashboardPins.ts` (+ promote/demote actions), `ui/src/stores/dashboards.ts` (`grid_config.layout_mode` typed), `ui/src/types/api.ts` (+ `is_main_panel` on `WidgetDashboardPin`, + `display_mode` on `ToolResultEnvelope`).

**Tests** — 8 new + adjacent regression sweep green:
- `tests/integration/test_dashboard_panel_mode.py` (7 cases): promote sets flag + flips `layout_mode`, promote clears prior panel pin, demote reverts `layout_mode`, deleting the panel pin reverts mode, default `is_main_panel=False`, 404 on unknown pin, sibling pins survive promote.
- `tests/unit/test_emit_html_widget.py` (5 new under `TestDisplayMode`): default omits the field, `display_mode="panel"` stamps it, invalid value errors, opt-in envelope round-trip, `inline` not serialized in `compact_dict`.
- Adjacent suite (test_dashboard_pins, test_dashboard_pins_service, test_widget_packages_seeder, test_widget_preview_inline, test_tool_execute_api, test_widget_packages_api) — 70 green.

**Plan**: `~/.claude/plans/typed-bubbling-hoare.md` (P10 row).

**Out of scope (intentional)**
- Panel-mode kiosk wrapper — kiosk + panel-mode happen to play well together since both clip chrome, but no bespoke combined treatment.
- Reorderable rail strip in panel mode — flex stack keeps it simple; if reorder becomes needed, drag-handles + dnd-kit are the upgrade path (sibling to channel-OmniPanel).
- Auto-resize of pin `{x, y, w, h}` when promoting — coordinates persist as-is so the user can demote back without losing their grid layout. The rail strip ignores `w/h` since width is fixed.
- Migration 224 backfill — every existing pin defaults to `is_main_panel=FALSE`; existing dashboards stay in grid mode unless someone explicitly promotes.

### P11-a — RGL guardrails (done — 2026-04-19)

First slice of the P11 layout-DX trio from `~/.claude/plans/typed-bubbling-hoare.md`. Keeps the free-form RGL grid working, adds the small quality-of-life wins that were missing, and fixes a drive-by bug where user dashboards had no cell-grid lines in edit mode.

**Size presets.** `GridPreset` gained `sizePresets: SizePreset[]` — preset-specific S/M/L/XL tuples. Standard runs `{3×6, 4×8, 6×10, 12×12}`; fine runs `{6×12, 8×16, 12×20, 24×24}` (same physical areas at twice the snap resolution). `EditPinDrawer` renders them as a chip row that calls the store's `applyLayout` on click, preserving the pin's `{x, y}` except when the chip is XL/full-width — there we snap `x=0` so the tile can actually fit.

**Full-width toggle.** Separate button in the same Size panel that sets `w = preset.cols.lg` and `x = 0` while preserving `y` and `h`. When the pin is already full-width, the button label flips to "Full width · on" and a click falls back to the M preset at the same `{x, y}` — the only state that's preserved between toggles is the row position, not a prior width.

**Reset layout.** New button in the edit-mode action bar (hidden outside edit mode, hidden on mobile). Two-click confirm — first click swaps the label to "Confirm reset?" with a danger-token border for 4s; second click runs `applyLayout` with `defaultLayoutForIndex(idx, preset)` for every pin. Arm state clears on exiting edit mode so it never lingers across sessions. Undo lives in P11-b; until then the confirm is the only guardrail.

**Drag guides generalized.** `EditModeGridGuides` was previously gated on `isChannelScoped` — user dashboards had no cell grid, no column reference, nothing. Gate removed; cell grid now renders on every dashboard in edit mode at `lg` breakpoint. New `showRailDivider` prop keeps the rail/Sidebar chrome channel-only since the rail zone is a channel-specific OmniPanel concept. New `dragging` prop renders a column-index tick row (1..N) above the grid while a drag is in flight, and the rail divider thickens (2px) + picks up an accent drop-shadow when the drag sits inside the rail zone.

**Files**
- `ui/src/lib/dashboardGrid.ts` — `SizePreset` type + `sizePresets` on both `GridPreset` entries.
- `ui/app/(app)/widgets/EditPinDrawer.tsx` — Size panel (chips + Full-width button), `preset` prop, `applyTileSize` helper, `sizeBusy` state.
- `ui/app/(app)/widgets/index.tsx` — `resetArmed` state + `handleResetLayout`, Reset button in action bar, `preset` passed to `EditPinDrawer`, `EditModeGridGuides` rendered unconditionally in edit mode.
- `ui/app/(app)/widgets/EditModeGridGuides.tsx` — `dragging` + `showRailDivider` props, column-index tick row, intensified rail divider during drag.

**Tests.** No new tests — the slice is UI polish on top of existing persisted layouts via the already-tested `applyLayout` store action and `/api/v1/widgets/dashboard/pins/layout` endpoint. `npx tsc --noEmit` clean.

**Plan**: `~/.claude/plans/typed-bubbling-hoare.md` (Phase P11 — P11-a row).

**Not in scope (deferred to P11-b / P11-c)**
- Layout versioning + Undo (P11-b) — the Reset button assumes no undo exists; P11-b adds a snapshot ring and ctrl-Z.
- HA-style Sections mode (P11-c) — third `layout_mode` value on top of `grid` / `panel`. Independent of P11-a.

## Key invariants

- **Copy semantics on dashboard add** — channel pin stays put; same entity can show on both surfaces.
- **Scope prop, not parallel components** — one `PinnedToolWidget` covers both surfaces. Stores are parallel (channel keyed by channelId, dashboard flat) but broadcasts cross-notify.
- **No channel context leak** — dashboard pins live in their own table. `app/services/widget_context.py` stays untouched; dashboard pins never inject into a channel's system prompt.
- **State_poll cache reuse** — cache key is `(tool, args_json)`; dashboard + channel pins for the same entity share cache hits. One upstream call refreshes both surfaces.
- **MCP from sandbox is admin-only** — P3 intentionally didn't touch MCP permissioning for bot-scoped API keys. That's a separate auth story (belongs with the future shared auth design), not this track.

## References

### Backend
- `app/routers/api_v1_dashboard.py` — dashboard CRUD + refresh
- `app/services/dashboard_pins.py` — service helpers
- `app/routers/api_v1_admin/widget_packages.py::_render_preview` + preview-inline / preview-for-tool
- `app/routers/api_v1_admin/tools.py::admin_execute_tool` — local + MCP dispatch
- `app/routers/api_v1_widget_actions.py::_do_state_poll` — tool-name-keyed refresh
- `migrations/versions/210_widget_dashboard_pins.py`

### Frontend
- `ui/app/(app)/widgets/index.tsx` — dashboard grid
- `ui/app/(app)/widgets/AddFromChannelSheet.tsx`
- `ui/app/(app)/widgets/dev/index.tsx` — 3-tab shell
- `ui/app/(app)/widgets/dev/ToolsSandbox.tsx` — Tools tab + pin flow (this session)
- `ui/app/(app)/widgets/dev/ToolArgsForm.tsx`
- `ui/src/stores/dashboardPins.ts` — `useDashboardPinsStore`
- `ui/src/api/hooks/useDashboardPins.ts` — hydration
- `ui/app/(app)/channels/[channelId]/PinnedToolWidget.tsx` — scope-aware rendering

### Tests
- `tests/integration/test_dashboard_pins.py` — CRUD, config merge/replace, refresh, position, 404s (10 cases)
- `tests/unit/test_dashboard_pins_service.py` — service-layer (11 cases)
- `tests/integration/test_widget_preview_inline.py` — preview routes (7 cases)
- `tests/unit/test_tool_execute_api.py` — local + MCP + bot-scoped (13 cases)

## Ideas / Future phases

### Bot-authored ephemeral widgets from tool calls (user-surfaced 2026-04-18)
Let the LLM, after invoking a tool, emit a **component-tree widget directly as part of its response** — no YAML template in the database. The widget is ephemeral (lives on that tool call's envelope only), rendered inline in chat just like templated widgets. The user can **pin it** to the dashboard, and from the dashboard they can **promote it to a saved template** so future invocations render the same way for any bot / integration user. Three progressive surfaces:

1. **Ephemeral widget** — the bot produces a component tree for this one tool call. Valid for this turn, disappears otherwise. Same render path (`ComponentRenderer`), no persistence cost.
2. **Pinned ephemeral** — the user clicks "Pin to dashboard" (existing P3 flow). The envelope + tool_args + widget_config get written to `widget_dashboard_pins` as a static card (similar to P6 generic view pins — not refreshable unless the bot re-attaches a `state_poll` shape).
3. **Promoted to template** — from the dashboard (or from the chat turn) the user clicks "Save as template" → the component tree becomes the seed YAML for a new `WidgetTemplatePackage` row via the Library editor (see [[Widget Authoring Gaps]] for the missing bridge this needs).

**Why this matters for integration users.** Today only the bot that invoked the tool sees a rich render; every other user/bot hitting the same tool in the same channel / integration gets raw JSON. Promoting an ephemeral widget to a template *makes it reusable across all callers* — one promotion turns a one-off bot rendering into shared infrastructure. Before promotion it's scoped to that one call; after promotion it's how everyone sees the tool.

**How the bot emits it.** Two shapes to decide between (defer to that phase's plan):
- A new **skill/tool** like `emit_widget(components=[...])` that the bot calls right after the tool it's annotating. The output pipe assembles the ephemeral envelope and attaches it to the prior tool call's message.
- A **response schema extension** — the LLM can return `{tool_result, widget: {components: [...]}}` for supported tools. Adds a structured-output step.

**LLM-driven widget builder surface.** Open question: do we expose an explicit **ephemeral session window** for authoring widgets chat-style? User opens `/widgets/dev#builder`, a scoped LLM sees the sample payload + component grammar + live preview, the user iterates ("put the temp first, add a toggle for fan") and on commit the template lands in the Library. Conceptually sibling to `/widgets/dev#templates` (YAML) but chat-driven. Would reuse the same `preview-inline` endpoint + `render_generic_view` starter. Decide whether this is a separate phase from (1)–(3) above or the same phase.

**Shared backend across modes.** Everything funnels through the same primitives:
- `app/services/generic_widget_view.py` — heuristic starter tree (P6, shipped)
- Component tree format (`{v:1, components:[...]}`) — already the lingua franca
- `ComponentRenderer` (frontend) — unchanged, renders whether the tree came from YAML / LLM / generic heuristic / builder chat
- `preview-inline` — validates ad-hoc trees
- `widget_dashboard_pins` — stores pinned ephemeral envelopes
- Library editor — receives promoted templates via the sandbox→library bridge from [[Widget Authoring Gaps]]

So: no new storage, no new render path; what's new is (a) a way for bots to emit component trees and (b) a way to promote any rendered tree (generic / ephemeral / pinned) into a saved package. The sandbox→library bridge from [[Widget Authoring Gaps]] is a **prerequisite** for (b).

Likely sequencing: ship the Widget Authoring UX track first (sandbox→library bridge, "Import from real call"), then build bot emission on top — so promotion is already wired when bots start producing component trees.

### Generic JSON widget fallback — shipped as P6 (2026-04-18)
Shipped as a **minimal auto-pick, pin-only** implementation — see the P6 row in Status and the Phase detail above. During planning a reframe emerged: a sophisticated configurable version would become a parallel templating language, so sophistication belongs in the Library editor instead (see [[Widget Authoring Gaps]]). v1 has no picker UI, does not auto-apply in chat, and pins are static snapshots. Forward-compat sentinel `widget_config: { generic_view: true }` is set on pin so a future v1.1 can persist field selections (`{fields: [{path, label, style}]}`) without a new schema.

### Tool output format hinting (`result_mime_type` / `output_schema`) — user-surfaced 2026-04-18
Every tool returns a raw `str` today; author convention is the only thing distinguishing structured JSON (`list_tasks`, most MCP tools) from prose (`get_skill_list`, `read_skill`). Modern LLMs parse both fine, but **every downstream consumer** (generic view auto-renderer, widget templates, machine parsing, citations, evaluator scoring) wants JSON. That's why `get_skill_list` renders as one sad "Value: long string" in the generic view — the tool isn't wrong, the renderer just can't do anything meaningful with 2 KB of prose.

**Reframe**: don't force one format. Let each tool declare its format; the renderer dispatches.

- **v1 — `result_mime_type` hint in the tool schema**: `application/json` | `text/markdown` | `text/plain`. `render_generic_view` branches: JSON → current structured auto-picker (tables / properties / headings); markdown → render as markdown inline; plain → single text block with monospace wrap. Cheap to add, zero migration cost (unset = inferred from `json.loads` success, same as today). Surfaces as a badge next to the tool name in the Tools sandbox so authors can see what they emit.
- **v2 — full `output_schema` on tools**: deferred P0-2 from [[Track - Widgets]]. Broader scope — enables static `{{var}}` validation against shipped templates and machine-readable tool output contracts. This is the "real" version; `result_mime_type` is a strict subset of it.

**Why not standardize to one format.** Forcing JSON bloats narrative tools (skills/docs/etc.) and hurts LLM comprehension on "read-and-summarize" use cases. Forcing prose loses everything structured (widgets, citations, evals). Mixed is the right answer; declared + dispatched is the right mechanism.

Relationship to P6: the generic renderer already handles the JSON branch well. This adds markdown/text branches and — critically — a way for the sandbox to say "this tool returned prose, here's why generic view looks sparse" instead of silently giving up. Prereq for any real quality bar on the Tools tab.

### Better dashboard rendering — multiple dashboards + column layouts (user-surfaced 2026-04-18)

> **P5 (session 20) addressed this partially via `react-grid-layout`** — 12-col responsive, per-pin `{x, y, w, h}`, drag + resize, auto-compact. Row-height stretch is solved; free-placement grid is in. What remains from this bullet:

- ~~**Row-height bug**: CSS grid with `auto-fill, minmax(320px, 1fr)` forces all cards in a row to match the tallest one. Short cards (a toggle, a status pill) get stretched awkwardly next to a tall card (a forecast table, a chart). Needs a masonry-style layout or explicit column/row spans.~~ **Resolved P5.**
- ~~**Definable column layouts (Home Assistant inspired)**: per-pin column/row span + size class (small/medium/large/full-width); dashboard layout saved per user/dashboard. Home Assistant's Lovelace card config is the reference.~~ **Resolved P5** (as arbitrary `{w, h}` rather than named size classes — add S/M/L presets later if needed).
- ~~Or and the dashboard is a grid like 100x100 or whatever and we can expand widgets to any size~~ **Resolved P5** (12 × n-rows at 30px, fine-grained enough in practice; 24-col mode is a future toggle if we want).
- **Multi-dashboard**: the schema already has `dashboard_key` ready for this — UI doesn't use it yet. Add a dashboard picker in the rail / page header, support create/rename/delete. Pins belong to exactly one dashboard at a time (or can be cloned across). **Still open.**
- **Named size presets (S/M/L/XL)** — one-click tile sizing on top of the raw RGL grid. `widget_config.size_preset` drives the {w, h}. Nice-to-have quality-of-life layer; not a replacement for the arbitrary grid.
- **Per-dashboard breakpoint overrides** — right now mobile collapses to 2 cols uniformly. Dashboards with a lot of full-width tiles could want a different breakpoint set.

### HTML widget output — v1 shipped 2026-04-18 (inline + path-backed)

**v1 SHIPPED** as a parallel-session effort alongside P5 QA. A bot can now emit an interactive HTML widget (JS + same-origin fetch to `/api/v1/...`) as a tool result, either with raw HTML inline or by pointing at a workspace file that auto-updates the rendered widget when the file changes.

**What shipped:**

- New tool `emit_html_widget(html? | path?, js?, css?, display_label?)` at `app/tools/local/emit_html_widget.py`. Exactly-one-of enforcement. `readonly` safety tier.
- New envelope `content_type: "application/vnd.spindrel.html+interactive"`. Distinct from `text/html` so strict-sandbox file previews (`SandboxedHtmlRenderer` for pinned workspace `.html` files) are unaffected.
- `ToolResultEnvelope` extended with `source_path` + `source_channel_id` fields (`app/agent/tool_dispatch.py`). `_build_envelope_from_optin` now also forwards `display_label`, `refreshable`, `refresh_interval_seconds` — previously dropped from opt-in payloads (latent bug; fixed same-edit).
- Frontend renderer `InteractiveHtmlRenderer.tsx` at `ui/src/components/chat/renderers/`. `sandbox="allow-scripts allow-same-origin"`, relaxed CSP (`default-src 'self'; connect-src 'self'` — cross-origin network blocked). Dispatch wired in `RichToolResult.tsx` alongside the strict `text/html` case.
- Path-mode freshness: `useQuery` against `/api/v1/channels/{source_channel_id}/workspace/files/content?path=...` with relaxed polling for mutable sources plus React Query caching so remounts do not behave like hard reloads. No new SSE wiring yet — explicit widget reload events already cover "show me now" after edits, and mutable path-mode files still get periodic revalidation. Small "updated Xs ago" chip overlays when path-mode.
- 11 unit tests in `tests/unit/test_emit_html_widget.py` cover both modes, validation (both/neither rejected, whitespace-only html treated as unset), no-context errors, file-not-found, plus the envelope round-trip through `_build_envelope_from_optin` + `compact_dict`. Full 23-test envelope slice + 75-test adjacent slice green. UI tsc clean.

**Explicitly out of scope (deferred):**

- Library / saved parameterized HTML templates (`widget_template_packages.template_kind` column) — ephemeral only for now. `widget_template_packages` stays components-only.
- `state_poll` for HTML widgets — path-mode polling covers auto-refresh; inline-mode is static by design.
- postMessage bridge + action allowlist — not needed once same-origin fetch is accepted.
- Per-pin `allow_scripts` flag / user approval gate — bot's explicit `emit_html_widget` call IS the opt-in; raw `text/html` envelopes from other tools still land in the strict renderer.

**Rationale summary.** The big up-front design fork was sandbox posture. Self-hosted single-user threat model: the bot already has tool-dispatch power, so an iframe that can hit `/api/v1/...` is a *weaker* attack surface than what the bot holds through its normal tool list. Accepting `allow-scripts allow-same-origin` + relaxed CSP collapses the feature to: new content_type, new renderer, new tool. postMessage bridges, allowlists, and trust indicators belong to a multi-tenant threat model this project doesn't have. Plan: `~/.claude/plans/fluttering-roaming-neumann.md` (status: executed).

**Follow-ups / possible next phase (not started):**

- `widget_template_packages.template_kind` — promote reusable HTML widgets to parameterized templates (same row shape with `{{var}}` substitution + `sample_payload`).
- Stop path-mode polling entirely for library/template edits that already have an explicit invalidation path.
- Consider `PINNED_FILE_UPDATED`/template-version invalidation for dashboard-scope pins so mutable HTML can become fully event-driven.
- Dashboard edit-layout remount guard: resize commits can remount a tile without changing its pin id. `PinnedToolWidget` now seeds its interactive-HTML ready state from the pooled iframe registry (`dashboard-pin:<id>`) so the preload skeleton does not stay over a live reused iframe after resize/move; this is a host-ready gating fix, not widget cache invalidation.

## Deferred / Known gaps

All P1–P6 items shipped. Remaining debt lives elsewhere:

- Dev panel UX polish (args form, copy/download, keyboard shortcuts, run history, tool metadata badges, narrow-screen layout) → [[Loose Ends#Widget Dev Panel UX debt]] (args/keyboard/history/badges items, not polish in general).
- Broader MCP permissioning for bot-scoped keys → separate auth story, out of this track.
- Multi-dashboard picker + per-pin size presets → moved into "Future phases" above as ideas, not P5 scope.
- Promoted-from-pin → template bridge (bot-authored ephemeral widgets) → "Future phases" above.

Recent polish note:

- Channel chat header now uses `Sessions` for the scratch launcher label and drops the extra `Ready` status badge / bordered-pill styling. The control still opens the same session menu, but it should read like standard header chrome instead of a separate warning/status chip.
- The session menu itself now uses `Session`/`Sessions` language instead of `Scratch session`, explains the feature as a separate session inside the channel, renames the ambiguous mini-chat action to `Open current session in mini chat`, and softens the `New session` button chrome so it reads like a normal header action instead of a primary pill.
- Follow-up correction: the menu no longer implies a special “current scratch session” state in the user-facing copy. The side-panel action now says `Open latest session in side panel`, the viewed session badge says `Viewing`, and the explainer explicitly contrasts recent channel sessions with the main channel chat.
- Follow-up correction: removed the generic desktop side-panel shortcut from the session menu. On desktop, `New session` and recent-session row clicks now open the explicitly selected session in the side panel; on mobile and full-page session routes they still navigate directly. The row buttons also advertise pointer affordance.
- Follow-up polish: scratch/session modal and dock headers now surface the selected session's own title/summary plus a quiet timestamp/message/section metadata line, using the same session-history data already shown in the menu. The intent is identity/context, not extra control chrome.
- Follow-up transcript polish: terminal-mode persisted tool rows now keep file reads/edits in the same transcript flow instead of switching to a boxed card treatment. File rows render their read body or diff inline with a quiet line-number gutter, and `Loaded skill` rows append the resolved skill ref in muted parens when the args/result payload exposes it.
