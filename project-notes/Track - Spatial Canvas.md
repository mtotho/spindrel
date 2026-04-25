---
tags: [track, ui, spatial-canvas]
status: active
updated: 2026-04-26 (P1 backend shipped — model + migration 247 + service + endpoints + reserved-slug filtering + tests 10/10)
---

# Track — Spatial Canvas

## North Star

A workspace-scope **infinite plane** where every channel and every opt-in widget lives as a draggable tile. `/` becomes the canvas on desktop. `Ctrl+Shift+Space` (Cmd+Shift+Space on mac) toggles it as an overlay from any other page — it swaps the main content area; sidebar stays. Double-click a channel tile → animated zoom-dive into that channel's existing widget dashboard. Foundation for the "infinite widget canvas" vision; future dimensions (edges, activity pulses, more node types) stack on top.

Design intent: replace the throwaway `HomeGrid` (a "desktopified command palette") with a surface that *is* the workspace — channels networked in the middle, widgets living freely around them. Giant DND, semantic zoom, iframes-on-world-at-close-zoom, route-change-on-dive.

## Status

| Phase | Status | Description |
|---|---|---|
| P0 — Prototypes | ✅ shipped 2026-04-24 | `scratch/alt-ui-prototypes/spatial-canvas.html` + `gossamer-web.html`. Validated semantic zoom + pan/zoom feel. Gossamer parked as future HUD variant. |
| **P1.0 — Integration spike** | 🔬 scaffolded — verify | Code shipped 2026-04-26. `ui/src/components/spatial-canvas/SpatialCanvasOverlay.tsx` + `ui/src/hooks/useSpatialOverlayShortcut.ts` + UI store flag + AppShell wiring. `Ctrl+Shift+Space` toggles. Tiles seed from real `useChannels()`. **Manual verification still required** for all three proofs before unblocking P1: (a) open `/channels/:id` with a streaming reply, toggle overlay on/off — stream must NOT drop or refetch; (b) double-click a tile, 300ms scale-translate animation completes BEFORE `router.push` fires, no flash on route swap; (c) wheel-over-iframe-body zooms canvas while inactive, click-to-activate makes iframe scroll/click work, Esc deactivates. Wheel listener attached with `{ passive: false }` on the viewport ref (React's synthetic `onWheel` is passive — silent preventDefault was a tripwire). |
| P1 — Backend | ✅ shipped 2026-04-26 | `WorkspaceSpatialNode` (`app/db/models.py`) with nullable channel_id / widget_pin_id FKs (cascade delete) + CHECK constraint exactly-one + partial unique indexes per target + persisted `seed_index`. Migration 247 creates the table and seeds the reserved `workspace:spatial` dashboard row. Service (`app/services/workspace_spatial.py`): `list_nodes` (upserts missing channel rows on read with monotonic seed_index, golden-angle phyllotaxis math), `update_node_position`, `delete_node` (explicit child-then-parent delete for SQLite test parity), and atomic `pin_widget_to_canvas` that uses `create_pin(commit=False)` so pin + node land in one transaction. Reserved-slug helpers added: `WORKSPACE_SPATIAL_DASHBOARD_KEY` + `is_workspace_spatial_slug` + `is_reserved_listing_slug` on both backend and `ui/src/stores/dashboards.ts`. Endpoints at `/api/v1/workspace/spatial/{nodes,nodes/:id,widget-pins}`. React Query hooks in `ui/src/api/hooks/useWorkspaceSpatial.ts` (optimistic update, invalidate on settle). Tests: `tests/integration/test_workspace_spatial.py` 10/10 pass. |
| P1.5 — Canvas shell | ⬜ | `<SpatialCanvas />` mounted in AppShell center-slot overlay + at `/` on desktop. Pan/zoom built directly (~150 lines, proven in prototype); use `@dnd-kit/core` (already installed) for tile-drag. No `@use-gesture/react` dep added. Mobile keeps `HomeChannelsList`. Reserved-slug filtering: `WORKSPACE_SPATIAL_DASHBOARD_KEY` constant + `isWorkspaceSpatialSlug()` predicate exported from backend + frontend; add exclusion to `ui/src/stores/dashboards.ts` user-dashboard filter and every other dashboard-listing surface (tabs, picker, recents, sidebar). |
| P2 — Channel tiles | ⬜ | Three semantic-zoom levels: far dot → mid preview tile → close expanded snapshot. Phyllotaxis seed uses persisted `seed_index` on the node row (monotonic, never recomputed; see decision 6). Animated zoom-dive: animation runs to completion (~300ms scale+translate to tile rect) **before** `router.push` fires. Snapshot is static — **not** live chat. |
| P3 — Widget tiles | ⬜ | Three semantic-zoom levels: chip → chip+title → live iframe. Viewport + zoom culling (iframe only for visible tiles at scale ≥0.6). Iframe gesture handling: drag-handle chrome strip is always canvas-pan-eligible; iframe body is pointer-events-blocked by a transparent shield until the tile is "activated" (click); Esc / click-outside deactivates. Leverage `InteractiveHtmlRenderer.tsx` keepalive patterns — don't remount iframes on pan/cull/reactivate. "Pin to workspace canvas" action wired into widget library + any rendered widget's context menu, calls the atomic P1 service. |
| P4 — Overlay + chrome | ⬜ | `Ctrl+Shift+Space` global toggle. AppShell-level state (from P1.0 spike). `<Outlet />` stays mounted beneath — SSE streams, drafts, transient route state all survive open/close. Contextual camera on open (current route = `/channels/:id` → center on that tile; else last position from `localStorage`). Recenter button. Right-click context menus. Keyboard: `F` = fit all, `Esc` = close overlay, `+`/`-` = zoom. |
| P5 — Activity pulses | 🚧 backlog | SSE-driven tile pulses on real-time events. Requires a workspace-scope event stream (not just per-channel) and a good visual vocab — design work. |
| P6 — User-drawn edges | 🚧 backlog | Whiteboard-style draw-line gesture between two tiles. Purely informational — no layout force. |
| P7 — Minimap | 🚧 backlog | Corner minimap with viewport rect + activity glow. Reuses the `OmniPanel` "scaled mini-view" pattern. |
| P8 — Cmd+K integration | 🚧 backlog | Fuzzy-find a channel from Cmd+K → canvas flies camera to it (instead of route change). Replaces the day-1 muscle memory from HomeGrid. |
| P9 — Channel-dashboard mirrors | 🚧 backlog | Every widget pinned to a channel dashboard also auto-projects near its channel tile (Q3 Option #2). Revisit once users have lived with independent-pins. |
| P10 — Embedded live channel at max zoom | 🚧 backlog | Q4 Option #2 — deepest zoom dives into an embedded live channel page inside the canvas, no route change. Requires `ChannelDashboardMultiCanvas` / `ChatMessageArea` / composer to be embeddable under a CSS transform; probably a rewrite, scroll math is the hard part. |
| P11 — Mobile canvas | 🚧 backlog | Touch-native canvas. Desktop-only in Phase 1–4; `HomeChannelsList` is mobile home until then. |
| P12 — Whiteboard polish | 🚧 backlog | Multi-select, undo/redo, snap-to-grid, align commands. |
| P13 — More node types | 🚧 backlog | Files, bots, workflows, pinned sessions as first-class canvas citizens. `node_type` column already supports it. |
| P14 — Gossamer HUD variant | 🚧 backlog | Refined version of `scratch/alt-ui-prototypes/gossamer-web.html` packaged as a native widget (Standing Orders precedent) that ticks strand vibrations from the SSE event bus. Complementary to the canvas, not a replacement. |

## Design decisions (locked)

1. **Route model** — `/` IS the canvas on desktop. `HomeGrid` retires (preserved behind a dev flag if we want a rollback). Mobile keeps `HomeChannelsList`.
2. **Overlay model** — `Ctrl+Shift+Space` toggles canvas in an **AppShell-level layer** (`ui/src/components/layout/AppShell.tsx`) that renders **above** the route `<Outlet />` without unmounting it. The outlet stays mounted but inert (pointer-events off, aria-hidden) while the canvas is open. This keeps `useChannelEvents` / SSE streams, `useChannelChat` state, composer drafts, and transient route state alive across toggles. Transition: 180–220ms ease-out + slight scale-in from 0.96. Sidebar stays. Not a z-index overlay over the sidebar; occupies the same bounds as the main content area. ESC or same hotkey dismisses.
3. **Channel positioning** — Hybrid: deterministic **phyllotaxis (golden-angle)** seed on first appearance; user drag pins forever. No relayout on membership change. If a channel has no node row, one gets created at the next seed slot on first render.
4. **World pins are independent** — World-scope widget pins are their own rows. A widget can be pinned to both a channel dashboard AND the world (two `widget_dashboard_pins` rows, no coordinate projection). Channel-dashboard edits never touch the world.
5. **Channel zoom-in — animate-then-navigate** — On double-click, animation runs to completion first (~300ms CSS transform on canvas root to tile's rect), **then** `router.push('/channels/:id')` fires. The animation completes in the AppShell transition layer, which survives the route change, so there's no mid-animation unmount flash. Crossfade the channel page on enter. Channel page is **never** embedded in canvas; P10 reconsiders. (Earlier draft said "router.push mid-animation" — that would unmount `/` and kill the canvas before the transition finished.)
6. **Data model — nullable-FK shape, not polymorphic-target** — New `workspace_spatial_nodes` table:
   - `id` (pk)
   - `channel_id` (UUID, nullable, FK `channels.id` ON DELETE CASCADE)
   - `widget_pin_id` (UUID, nullable, FK `widget_dashboard_pins.id` ON DELETE CASCADE)
   - **CHECK constraint**: exactly one of `channel_id` / `widget_pin_id` is non-null
   - `world_x` / `world_y` / `world_w` / `world_h` (Float)
   - `z_index` (Int, default 0)
   - `seed_index` (Int, nullable) — monotonic counter written once on insert, used for deterministic phyllotaxis position; **never recomputed**. Guards against cross-tab races and post-delete shifts.
   - `pinned_at` / `updated_at` timestamps
   - Unique partial indexes on `channel_id` (WHERE NOT NULL) and `widget_pin_id` (WHERE NOT NULL) — one spatial node per target.

   Nullable-FK over polymorphic-`target_id` because the DB enforces referential integrity natively (cascade-on-delete handles channel deletions, dashboard pin deletions, and migration edge cases without application-side cleanup jobs). Future node types (`file`, `bot`) add new nullable FK columns + widen the CHECK — slightly more surface area in exchange for compiler-verified integrity.

   No coupling of `channels` or `widget_dashboard_pins` to spatial concerns — neither table gains columns for this.
7. **Auto-populate** — All channels auto-appear. Widgets are opt-in via explicit "Pin to workspace canvas" action. No data-derived edges.
8. **Edges** — None in Phase 1. User-drawn only when added (P6). No auto-edges from shared bots / shared integrations / cross-refs.
9. **Semantic zoom** — Channel tiles: `<0.4` colored dot, `0.4–1.0` preview tile, `>1.0` expanded snapshot. Widget tiles: `<0.4` chip, `0.4–0.6` chip+title, `≥0.6` live iframe. Live-iframe threshold doubles as the performance-culling threshold.
10. **Rendering stack** — Custom outer `<div>` with `transform: translate() scale()` for world pan/zoom. Tiles are absolutely-positioned children with their own `transform: translate()`. **Build pan/zoom gesture layer directly** (~150 lines, proven in the prototype) — no new dep. **Tile drag** uses `@dnd-kit/core` (already in `ui/package.json`). **No `@use-gesture/react`** (not installed; not worth the compatibility spike when 150 lines of wheel/pointer handlers does the job). **No react-flow** (edges aren't MVP, iframe-as-node content fights the lib). **No tldraw** (bundle size + wrong product shape). Widgets on world reuse existing `WidgetCard` component, iframe contract, SDK, theme — only the coordinate system and gesture-shield overlay change.
11. **Hotkey** — `Ctrl+Shift+Space` (Cmd on mac). Contextual camera: current route = `/channels/:id` → overlay opens centered on that tile with a short pan animation; else last camera position from `localStorage` (`spatial.camera.{x,y,scale}`).
12. **Scope today** — Single-workspace. `workspace_spatial_nodes` reserves a future `workspace_id` column but doesn't populate it yet.

## Key invariants

- **Route outlet never unmounts for the canvas.** Canvas lives in an AppShell-level layer. Opening/closing the overlay must not interrupt active SSE streams in `useChannelChat.ts`, widget event taps, composer drafts, or transient route state. Acceptance criterion, not an implementation detail.
- **`workspace:spatial` is a reserved dashboard slug.** Export `WORKSPACE_SPATIAL_DASHBOARD_KEY` from backend and `isWorkspaceSpatialSlug()` predicate from `ui/src/stores/dashboards.ts` and matching backend helper. Every surface that enumerates dashboards must exclude reserved slugs: `userList` in `dashboards.ts` (currently only filters `channel:*`), dashboard tabs, target pickers, recents, sidebar dashboard lists, anywhere `widget_dashboards.slug` is listed. Missing this is how the review caught it would leak.
- **Atomic pin + node creation.** One backend service method / endpoint creates the `widget_dashboard_pins` row and the `workspace_spatial_nodes` row in one transaction. The frontend never calls them separately. Failing the second call must roll back the first — no orphan pins on `workspace:spatial`.
- **Phyllotaxis seed is persisted, never recomputed.** Each new node row gets a `seed_index` on insert (monotonic counter, DB-side or a dedicated sequence). Position is derived from `seed_index` only. No "count rows + 1" logic. Safe across tabs; stable after deletes.
- **Iframe gesture handling is mandatory, not polish.** Live iframe tiles at scale ≥0.6 must not swallow canvas pan/zoom. Mechanism: drag-handle chrome strip always pans; iframe body has a transparent shield that blocks pointer events until tile is "activated" by click; Esc / click-outside deactivates. Reuse keepalive patterns from `InteractiveHtmlRenderer.tsx` so panning past / culling / reactivating doesn't force iframe remounts.
- `workspace_spatial_nodes` is the **one source of truth** for world positions. Don't let channel positions leak into `channels` columns. Don't let world widget positions leak into `widget_dashboard_pins.grid_layout`.
- World widget pins reuse existing `widget_dashboard_pins` plumbing: synthetic `workspace:spatial` dashboard slug, normal `envelope` / `widget_contract_snapshot` / `widget_presentation_snapshot` / `source_bot_id` / iframe auth. **No second widget host path.**
- Channel page (`ChannelDashboardMultiCanvas`, `ChatMessageArea`, composer, right dock) is never embedded in the canvas. Canvas always delegates via route change. P10 is the only phase allowed to revisit this.
- No live SSE-driven pulses in Phase 1–4. Unread counts come from cached channel state; no new event-bus subscriptions.
- No legacy framing. `HomeGrid` retirement is net-new-direction, not "deprecated" — new code paths are unconditional.
- Mobile is unchanged through Phase 4. The canvas is desktop-only until P11.

## Acceptance criteria (Phase 1 gate)

A Phase 1 ship requires all five to pass — by manual verification at minimum, with regression tests where feasible.

1. **Live stream continuity**: Open `/channels/:id` with an in-flight bot response. Toggle canvas overlay (Ctrl+Shift+Space) on, then off. The streaming response continues uninterrupted — no token gap, no re-request, no SSE reconnection.
2. **Zoom-dive no flash**: Double-click a channel tile. The 300ms zoom animation completes. Channel page appears after animation, not during. No black/white flash, no visible unmount.
3. **Iframe-with-pan**: With a live widget tile on the canvas at close zoom, wheel-over-the-widget-body pans/zooms the canvas (not scrolls the widget). After clicking into the tile to activate, wheel and click affect the widget. Esc deactivates; pan/zoom returns to canvas.
4. **Reserved slug isolation**: `workspace:spatial` row exists in `widget_dashboards` and is *not* visible in dashboard tabs, target pickers, recents, sidebar, or any API response that enumerates user dashboards.
5. **Orphan safety**: Delete a channel directly in the DB. The corresponding `workspace_spatial_nodes` row cascades out. Delete a world-pinned widget. The corresponding spatial node cascades out. No orphan rows; no app errors on next canvas load.

## References

- Prototypes: `scratch/alt-ui-prototypes/spatial-canvas.html`, `scratch/alt-ui-prototypes/gossamer-web.html`
- Existing home (to be replaced): `ui/src/components/home/HomeGrid.tsx`, `ui/app/(app)/index.tsx`
- Existing widget dashboard (model for widget rendering): `ui/app/(app)/widgets/ChannelDashboardMultiCanvas.tsx`
- Pin model: `app/db/models.py` → `WidgetDashboardPin`
- Widget system canonical: `docs/guides/widget-system.md`
- UI design canonical: `docs/guides/ui-design.md` (add "Spatial" as a third archetype when P1 lands)
- Precedent for native-widget-ticks-on-events: Standing Orders (2026-04-24)
- Precedent for scaled mini-view: OmniPanel

## Relationship to other work

- Extends the dashboard concept (P12 positional zones) to a **workspace-scope surface**. Channel dashboards remain the close-zoom destination.
- `Track - Integration Rich Results` — rich tool-result widgets that land on channel dashboards will be pinnable to the world canvas for free via P3's "Pin to workspace canvas" action.
- `Track - Automations` / Standing Orders — ticking-native-widget precedent; Gossamer HUD (P14) follows the same pattern.
