---
tags: [agent-server, track, widgets, dx]
status: active
updated: 2026-04-19
---
# Track — Widget System DX + Robustness

## North Star
Make the tool widget definition system a **first-class, documented, validated, and low-friction** surface — so adding a widget is a 10-minute task, malformed templates fail at registration (not runtime), and new features extend the system instead of bypassing it.

Reference doc: [[Widget Authoring]]. Implementation artifact: plan file at `~/.claude/plans/deep-plotting-mochi.md` (review + prioritized roadmap). Flagship catalog plan: `~/.claude/plans/happy-cuddling-noodle.md`.

## Status

| # | Phase | What | Status |
|---|-------|------|--------|
| P0-3 | Docs + track file | [[Widget Authoring]] reference + this file | **done** (2026-04-17) |
| P0-1 | Component-tree schema | Pydantic model + registration-time validation | **done** (2026-04-17) — JSON Schema artifact + TS hoist deferred (see §Follow-ups) |
| P0-2 | Tool output schemas | Declare `output_schema` on tools; static `{{var}}` resolution checks | deferred |
| P1-1 | Template fragments + state_poll default | `fragments:` block, `{type: fragment, ref}` resolver, `state_poll.template` defaults to `template` | **done** (2026-04-17) — `with:` overlays deferred (see §Follow-ups) |
| P1-2 | Expression grammar | `and` / `or` / `not` / ternary in `{{...}}` | deferred |
| P1-3 | Extensible pipe-filter registry | Integrations declare `widget_filters:` in manifest | deferred |
| P1-4 | Unify TaskRunEnvelope / InlineApprovalReview | Route task widgets through MIME dispatch | deferred |
| P2-1 | Separate `display_label` from key-carry | Add explicit `context:` block | deferred |
| P2-2 | `display: panel` end-to-end | Define panel host, route envelopes | deferred |
| P2-3 | Pinned-widget envelope write-back | Persist state_poll refresh into `channel.config.pinned_widgets` | deferred |
| P2-4 | Registration-time test harness | Render every `sample_payload`; CI guardrail | deferred |
| P2-5 | Hot-reload manifest widgets | Parity with DB-backed packages | deferred |
| P2-6 | Admin playground | In-app widget preview + live validation | deferred |

## Follow-ups (extracted from P0-1 / P1-1 shipping)

- **JSON Schema artifact** at `ui/src/types/widget-components.schema.json` generated from `ComponentBody.model_json_schema()` — enables future admin playground (P2-6) to lint YAML live. Small script under `scripts/`.
- **TS type hoist**: lift the `ComponentNode` union out of `ui/src/components/chat/renderers/ComponentRenderer.tsx` into `ui/src/types/widgets.ts` so the renderer imports from a single source of truth. Today Pydantic is the canonical schema for validation, but the TS is still a manual parallel.
- **`with:` overlays on fragments**: per-ref variable overrides (`{type: fragment, ref: X, with: {bot_id: "{{override}}"}}`). Not needed by the refactored `schedule_task`; add if a second widget wants the same fragment but against different keys.
- **Refactor `list_tasks` detail mode** to share fragments with `schedule_task` — large remaining duplication between the two.

## Phase detail

### P0-3 — Docs + Track (done)
Shipped [[Widget Authoring]] + this track file + Roadmap link. Covers: three pathways, component reference, pipe reference, `when`/`each`, `state_poll`, transforms, fragments, pinned widgets, testing, file layout.

### P0-1 — Component-tree schema (done)
- `app/schemas/widget_components.py` — Pydantic discriminated union over every renderer-supported type, permissive-where-templated / strict-on-structure (extra fields rejected, unknown types warn not error for forward-compat).
- `app/services/widget_package_validation.py` — new `_validate_parsed_definition()` helper + `_validate_component_list()` runs the tree.
- `app/services/widget_templates.py:_register_widgets` now calls the validator at boot; errors log + skip, warnings log + register.
- Tests added to `tests/unit/test_widget_package_validation.py` including a "validate every shipped core widget" smoke test.

### P1-1 — Template fragments + state_poll default (done)
- `app/services/widget_fragments.py` — resolver inlines `{type: fragment, ref: <name>}` nodes (list bodies spread, dict bodies replace 1:1) at registration time; cycle-detected.
- Validator validates fragment bodies as components so typos don't slip through.
- `_register_widgets` now: (a) validates, (b) resolves fragments, (c) defaults `state_poll.template` to `template` when omitted, (d) caches expanded definition.
- `app/tools/local/tasks.widgets.yaml:schedule_task` refactored to use `cancel_task_button` + `edit_task_links` fragments in both `template` and `state_poll.template`.
- 22 new unit tests across `tests/unit/test_widget_fragments.py` and `tests/unit/test_widget_templates.py::TestRegisterWidgetsFragments`. Full widget test suite (135 tests) passes.

## Key invariants
- **MIME dispatch stays the seam.** New content types route cleanly; interactive widgets stay on `application/vnd.spindrel.components+json`.
- **Backwards-compatible additions only** — existing `*.widgets.yaml` and integration manifests keep working without edits.
- **No runtime surprises** — every widget either validates at registration or is flagged `is_invalid`.
- **Schema has one source of truth** — Pydantic drives the JSON Schema which drives the TS types. If they drift, CI fails.

---

## Flagship Catalog (Phase 0 + Phase 1+)

Widgets that showcase what HTML buys over components (SVG charts, media viewers, free-form layout, fine animation, brushing/filtering). Prioritized for the post-`frigate_snapshot` era.

### Phase 0 — Widget theme / DX layer (done, 2026-04-19)

Shipped so every HTML widget inherits the app's design language automatically — no more hand-rolled hex colors, dark-mode-correct by default.

- `ui/src/components/chat/renderers/widgetTheme.ts` (new) — `buildWidgetThemeCss` emits `--sd-*` CSS variables + `sd-*` utility/component classes (card / btn / chip / stack / grid / tile / progress / spinner / skeleton / input). `buildWidgetThemeObject` exposes tokens to SVG/canvas widgets as `window.spindrel.theme`.
- `InteractiveHtmlRenderer.tsx` — reads `useThemeStore`, injects `<style id="__spindrel_theme">` + `<html class="dark">` + theme object into iframe bootstrap.
- `skills/html_widgets.md` — new **Styling** section documenting the `sd-*` vocabulary + Do/Don't table. Common Mistakes extended with "inline hex colors" entry.
- `integrations/frigate/widgets/frigate_snapshot.html` — migrated as the canonical reference (14 lines of inline CSS → 0).

### Phase 1 status

| # | Widget | Tool | Status |
|---|--------|------|--------|
| 1 | **Frigate events timeline** | `frigate_get_events` | **done** (2026-04-19) — `integrations/frigate/widgets/frigate_events_timeline.html` — SVG time-axis with per-camera lanes, label-colored pills, filter chips (`sd-chip-*` palette), detail panel on click, refresh dispatch, state_poll every 60s. |
| 2 | HA room dashboard v1 | `GetLiveContext` | **blocked** — existing component widget (integration.yaml:228-307) is comprehensive; upgrade replaces it (design call). Also: HTML mode doesn't run top-level transforms (only state_poll transforms) — widget_templates.py:502-511. One-line engine fix, but needs user sign-off on the replace-vs-add-new-tool-variant decision. |
| 3 | `get_trace` waterfall | `get_trace` | **blocked** — detail mode returns text, not JSON. widget_templates.py silently skips non-JSON tool results. Needs additive `format: "text"\|"json"` param on the tool with state_poll.args.format="json". Low-risk but touches a core tool. |

Bug fixes shipped alongside Phase 1 (from user testing the first flagship):

- **Frigate snapshot dup** — `_download_media` in `integrations/frigate/tools/frigate.py` was creating an attachment AND returning `client_action`, producing two image copies in the web UI (one inline via orphan-linking, one in the widget). Fix: when a widget is registered for the tool, `create_attachment` is called with `channel_id=None` so persist_turn's orphan-linking skips it. `client_action` stays untouched (Slack / Discord / BlueBubbles consume it via a separate channel that never rendered widgets).
- **Widget auth UX** — `app/routers/api_v1_widget_auth.py` mint endpoint now names the bot by `display_name` and points at `Admin → Bots → {name} → Permissions` instead of generic "admin UI". `ApiError` exported from `ui/src/api/client.ts` with a `.detail` getter that extracts FastAPI's `{detail: "..."}` body. `InteractiveHtmlRenderer` surfaces the backend detail in the auth banner with a **Retry** button (`tokenQuery.refetch()`) so users don't wait for the 12-min react-query interval after granting scopes.
- **Preamble strip orphan `<script>`** (latent, surfaced by the dup-suppression fix) — `TOOL_RESULT_PREAMBLE_RE` in `InteractiveHtmlRenderer.tsx` only matched `window.spindrel.toolResult = ...;</script>`, leaving an orphan `<script>window.spindrel = window.spindrel || {};` opening tag in the iframe body. The browser saw an unclosed script and parsed the following HTML as JS — `Uncaught SyntaxError: Unexpected token '<' at about:srcdoc:2:1` in console, empty widget body. The old behavior was masked because the inline image attachment was rendering the snapshot. Fix: widened the regex to `<script>\s*window\.spindrel\s*=\s*window\.spindrel\s*\|\|\s*\{\};\s*window\.spindrel\.toolResult\s*=\s*([\s\S]+?);\s*<\/script>` — tightly anchored on the exact init signature so it can't accidentally swallow bot-authored script tags that happen to mention `window.spindrel.toolResult`.
- **Token race — 422 on widget initial fetch** — `window.spindrel.apiFetch` fired the iframe's initial-paint fetches synchronously at iframe load, but the bot widget-auth JWT is minted async by react-query AFTER mount. First fetch went out without `Authorization` → 422 Unprocessable Entity at `/api/v1/attachments/{id}`. User saw "Image fetch failed (check bot's attachments:read scope)" even though scopes were granted. Fix: added a `tokenReady` promise inside the `spindrelBootstrap` script. `apiFetch` awaits it when `state.token` is null. `__setToken` resolves it on first mint arrival. Single mount delay (~100ms), no perceptible pause; subsequent fetches are synchronous because the promise is already resolved.

### Phase 2 status

Top four shipped 2026-04-19. Plan: `~/.claude/plans/memoized-gathering-abelson.md`.

| # | Widget | Tool | Status |
|---|--------|------|--------|
| 1 | **`generate_image`** | `generate_image` | **done** (2026-04-19) — `app/tools/local/widgets/image.html` — responsive gallery (1/2/auto-fit grid), click-to-lightbox, three regen buttons ("Try again", "Brighter", "Different angle", "More detail") that dispatch `generate_image` with mutated prompts via `/api/v1/widget-actions`. Tool now returns `prompt` + canonical `images: [{attachment_id, filename}]` in the JSON so the widget can show thumbnails without unwrapping `client_action`. Widget-aware attachment suppression added: when a widget is registered, `create_attachment` uses `channel_id=None` (same pattern as `frigate_snapshot`) so the web orphan-linker doesn't double-display. |
| 2 | **`get_weather`** | `get_weather` | **done** (2026-04-19) — `integrations/openweather/widgets/get_weather.html` — replaces the component widget in `openweather/integration.yaml:110-126`. SVG hourly chart (640×180) with temp curve + precip bars + y-axis grid + x-axis hour ticks, daily forecast `.sd-tiles` (7-day), alerts `.sd-error` banner, `°F`/`°C` + "Feels like" toggles in header. State_poll keeps `include_daily` + `include_hourly` on and respects per-pin `units`. |
| 3 | **`web_search`** | `web_search` | **done** (2026-04-19) — `integrations/web_search/widgets/web_search.html` — per-result cards with favicon (via new `/api/v1/favicon?domain=` proxy), domain chip, 2-line snippet clamp, star-to-save button (RMW on `widget_config.starred[]` via `dashboard_pin_id`), "★ Starred only" filter, Summarize button that dispatches `fetch_url` and expands an inline panel. `_search_result()` skips the `_envelope` components-JSON opt-in when the widget template is registered; without a widget the `links` fallback still works. |
| 4 | **`frigate_list_cameras`** | `frigate_list_cameras` | **done** (2026-04-19) — `integrations/frigate/widgets/frigate_list_cameras.html` — 2×N camera wall (220px min-tile auto-fill), per-tile 10s snapshot refresh via dispatched `frigate_snapshot` calls (JS parses the attachment_id out of the returned HTML envelope preamble), click→full-bleed lightbox. Header controls: bounding-box toggle + pause-polling toggle. State_poll (300s) refreshes the camera list itself to catch add/remove. Completes the Frigate story (pairs with the events-timeline widget). |
| 5 | **`create_excalidraw` / `mermaid_to_excalidraw`** | Excalidraw | **done** (2026-04-19) — `integrations/excalidraw/widgets/create_excalidraw.html` — shared widget (both tools return the same shape: attachment_id + filename + mime). Renders via `apiFetch(/api/v1/attachments/{id})` → blob → `<img>`, click→lightbox, header Download button. `_deliver()` refactored to return `attachment_id` + use the new `create_widget_backed_attachment` helper so web orphan-linking is suppressed (previously the rendered diagram appeared twice: once from the orphan-linked attachment, once from the widget). Validated the pattern is now reusable — this was the extraction trigger. |

### Bot-authored dashboard DX — DX-1 shipped, DX-2 through DX-5 queued (2026-04-19)

Skill-driven effort to turn bot-authored HTML widgets into pro-grade dashboards. Plan: `~/.claude/plans/memoized-mixing-teapot.md`.

- **Skill rewrite** — `skills/html_widgets.md` (416 → 690 lines): bundle layout conventions (`/workspace/channels/<id>/data/widgets/<slug>/` vs `/workspace/widgets/<slug>/`), tool dispatch via `/api/v1/widget-actions` as a first-class section, the `state.json` RMW pattern, four dashboard archetypes (status / feed / control panel / KB reader), `/widget-actions` vs `spindrel.api()` decision table, DX roadmap appendix.
- **DX-1 — `window.spindrel.renderMarkdown(text)`** shipped. Minimal CommonMark-ish renderer (headings, bold/italic, inline code, fenced code, lists, blockquotes, links, paragraphs) baked into `spindrelBootstrap` in `ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx`. HTML-escapes source first; safe for bot-authored prose. 16/16 extraction tests pass via node eval. UI tsc clean.
- **DX-2 — `window.spindrel.callTool(name, args, opts?)`** shipped. One-line wrapper over `POST /api/v1/widget-actions` dispatch:"tool"; auto-fills `bot_id` + `channel_id`; `opts.extra` flows `display_label` / `widget_config` / `source_record_id` / `dashboard_pin_id` through; returns fresh envelope or throws. Skill's control-panel archetype now uses it; Tool Dispatch section rewritten around it. 4/4 extraction tests pass (basic, opts.extra, missing-name, server-error). UI tsc clean.
- **DX-3 — `window.spindrel.data` helper** shipped. `load(path, defaults?)` / `patch(path, patch, defaults?)` / `save(path, object)` with deep-merge semantics (arrays replaced, not concatenated). First-run-safe (missing file → defaults clone); throws on invalid JSON; `patch` reads fresh each time so two open copies stay coherent. Collapses the state-dashboard boilerplate to three methods. Skill's `state.json` pattern section rewritten around it. 8/8 extraction tests pass (missing+defaults, save/load round-trip, no-defaults, deep-merge patch, patch-on-missing, array replacement, invalid-JSON, defaults immutability). UI tsc clean.
- **DX-4 — event subscription wrappers** shipped. `onToolResult(cb)` + `onTheme(cb)` wrap the existing `spindrel:toolresult` / `spindrel:theme` DOM events and return unsubscribe fns. `onConfig(cb)` is sugar over `toolresult` that debounces on actual `toolResult.config` change (JSON-stringify compare) so callbacks don't fire on every envelope refresh. Skill's "Reacting to live updates" section replaces the old raw-addEventListener guidance. 6/6 extraction tests pass (basic fire, unsubscribe removal, onTheme, onConfig debounce semantics, non-function callbacks throw for both wrappers). UI tsc clean.
- **DX-5a — relative-path resolution in helpers** shipped. `window.spindrel.widgetPath` is set to the envelope's `source_path` (null for inline); `readWorkspaceFile`, `writeWorkspaceFile`, and `data.*` accept `./foo` / `../foo` and resolve against `dirname(widgetPath)`. New `window.spindrel.resolvePath(input)` exposed for bookkeeping. Added `normalizePath` (strips `./`, collapses `..`, rejects workspace-root escape) + `resolvePath` (path-grammar dispatcher) to the bootstrap. `/workspace/...` absolute paths currently throw with a clear DX-5b pointer. `sourcePath` threaded `wrapHtml` → `spindrelBootstrap`. 13/13 extraction tests pass (plain, redundant segments, relative resolution, deep parent traversal, escape-throws, absolute rejected, inline-widget guards, empty/non-string guards, root-widget relative). UI tsc clean.
- **DX-5b — non-channel workspace root (`/workspace/widgets/<slug>/`)** — deferred (not a quick slice). Needs cross-cutting backend work: new non-channel root in `app/services/workspace.py`, non-channel-scoped workspace-file endpoint, path resolver in `emit_html_widget.py`, extending the iframe file-polling query beyond channel scope, and making the `file` tool (currently channel-scoped) write into the new root. Best as its own session with a proper plan — too easy to cause silent bugs.
- **DX-5c — bundled asset loading via `loadAsset`** shipped. `window.spindrel.loadAsset(path)` + `revokeAsset(url)` in the bootstrap. Fetches via `apiFetch` against the existing channel `/workspace/files/raw` endpoint, blobs the response, returns a `blob:` object URL. Same-origin by construction (no CSP changes). Supports the full `resolvePath` grammar (relative paths against widget bundle). Skill's "Bundled assets" section documents `<img>` / `<video>` / `<audio>` use. 5/5 extraction tests pass (basic load, revoke, revoke-unknown-ignored, 404-throws, absolute path). UI tsc clean.
- **DX-5c-full — `<base href>` native asset loading** — deferred. "Drop `<img src="assets/logo.svg" />` and have it work" needs a signed-URL token pattern OR a service worker to inject `Authorization` headers OR a public asset endpoint. All three are real security design calls. `loadAsset` shipped as the pragmatic unlock that doesn't commit us to a stance.

### Phase 0.5 — Engine addition: `widget_config` rides into `toolResult.config` (done, 2026-04-19)

Slice 0 of the plan. Previously `apply_widget_template` computed `data_with_config` but only passed `data` into `_build_html_widget_body` — HTML widgets couldn't read their own pin config. Changed both call sites (`widget_templates.py:511` + `widget_templates.py:641` in `apply_state_poll`) to pass `data_with_config`, so widget JS now reads `window.spindrel.toolResult.config.*` natively. No renderer changes needed.

`InteractiveHtmlRenderer.tsx` also gained a `dashboardPinId?: string` prop; `RichToolResult` threads it through from `PinnedToolWidget` so widget JS can read `window.spindrel.dashboardPinId` and target `widget_config` dispatches at the correct pin. Inline chat widgets leave it undefined — config changes stay local-only.

Test update: `tests/unit/test_widget_templates_html.py::test_preamble_excludes_widget_config` inverted to `test_preamble_includes_merged_widget_config` + added `test_preamble_uses_default_config_when_no_pin_overrides`. Adjacent test `test_preamble_carries_tool_result_json` loosened to check tool-result fields individually + assert `config` present.

### Phase 2 — Tier 2+ remaining candidates (unscheduled)

Ordered roughly by projected value-per-token. Each is a standalone session.

- **`list_attachments`** — masonry gallery, type-filter chips, full-screen lightbox with arrow-key nav. Per-item "Describe" button dispatches `describe_attachment`.
- **`github_get_pr`** — inline diff viewer (Prism.js inlined), file-tree sidebar, review/merge/close action bar. Component widget already exists → HTML upgrade replaces it.
- **`list_tasks`** — week-view calendar with scheduled runs as draggable bars; past-run status bubbles below. Drag dispatches `update_task`.
- **`search_history` / `read_conversation_history`** — threaded transcript with author avatars, timestamp clustering, click-to-jump (postMessage up to parent channel).
- **`sonarr_calendar`** — month/week grid with poster thumbs per day; click → wanted status + "search now".
- **`sonarr_series` / `radarr_movies` (search)** — TMDB/TVDB poster grid with year / genres / rating overlay + "Add" dispatch.
- **`check_gmail_status`** — inbox preview rows (sender / subject / snippet), per-row Reply (modal) / Archive (dispatch) / Open in Gmail.
- **`sonarr_queue` / `radarr_queue`** — smooth-animated progress bars, ETA countdown tickers, per-item Cancel / Prioritize dispatch. (Originally proposed as alternative Tier 1 pick — lives here until a self-hoster with an active queue validates live.)

### Phase 3 — Supporting widgets

Smaller targets — ship opportunistically when touching the area.

- `file` (list) — tree viewer, size + mtime, icon by type
- `file` (read diff) — side-by-side diff pane with Prism highlighting
- `search_workspace` / `search_channel_workspace` — matches with line context + jump-to-file
- `list_pipelines` — catalog with "Run" buttons + last-run status dots
- `bot_skills` — skill ring chart + "enroll/unenroll" actions (component widget exists → HTML upgrade)
- `fetch_url` — reader-mode with table-of-contents sidebar

### Widget-engine gaps surfaced by this catalog

These are ENGINE changes (fit [[Track - Widgets]] proper, not the catalog):

- **HTML mode top-level transform** — currently only state_poll transforms run in HTML mode (widget_templates.py:502-511). Blocks widgets that need server-side data reshaping on first render (e.g. HA dashboard parsing the YAML text).
- **JSON-format mode for text tools** — widgets silently skip tools returning non-JSON. Either widen the engine to accept `{text: str}` wrapping, or document that widget-backed tools must emit JSON. Affects `get_trace` waterfall.
- **Widget-aware attachment suppression** — extracted 2026-04-19. Helper `app/services/attachments.py::create_widget_backed_attachment(*, tool_name, ...)` checks `get_widget_template(tool_name)` and forwards to `create_attachment` with `channel_id=None` whenever a widget is registered. Three call sites converted: `integrations/frigate/tools/frigate.py::_download_media` (snapshot + event_snapshot + event_clip), `app/tools/local/image.py::generate_image_tool`, `integrations/excalidraw/tools/excalidraw.py::_deliver` (both excalidraw tools). `client_action` stays on in all three — Slack/Discord consume it as their rendering path. Unit test: `tests/unit/test_widget_backed_attachment.py`.
- **Favicon proxy** — shipped 2026-04-19 at `/api/v1/favicon?domain=` for the `web_search` widget. Thin LRU-cached httpx GET against `www.google.com/s2/favicons`. Requires `chat` scope. First general-purpose proxy for widget use; future widgets can consume it too.

---

## References
- Engine: `app/services/widget_templates.py`
- Envelope: `app/agent/tool_dispatch.py` (`ToolResultEnvelope`, three-path dispatch)
- DB seeding: `app/services/widget_packages_seeder.py`, model: `app/db/models.py:WidgetTemplatePackage`
- Renderer: `ui/src/components/chat/renderers/ComponentRenderer.tsx`
- Card (polling + pinning + dispatch): `ui/src/components/chat/WidgetCard.tsx`
- Dispatcher: `ui/src/components/chat/RichToolResult.tsx`
- Bypass examples: `ui/src/components/chat/TaskRunEnvelope.tsx`, `ui/src/components/chat/InlineApprovalReview.tsx`
- Tests: `tests/unit/test_widget_templates.py`, `test_widget_package_validation.py`, `test_widget_package_loader.py`, `test_widget_context.py`, `test_widget_actions_state_poll.py`
