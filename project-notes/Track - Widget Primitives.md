---
tags: [agent-server, track, widgets, yaml, integrations]
status: active
updated: 2026-04-24 (Phases 1–5 shipped including preset promotion)
---

# Track — Widget Primitives

## North Star

Integration-owned widgets should default to declarative YAML. The YAML component tree is the "native feel" surface for integrations — one author writes config, the platform renders against `docs/guides/ui-design.md`, design-system upgrades flow automatically, and integration authors stop re-implementing 80% of the design system in hand-rolled CSS.

**Contract design principle — entropy minimization.** Every new field, every enum value, every default is evaluated against: *"if I were a large language model emitting this YAML, does the contract leave me with one obvious choice?"* Mixed-type fields, implementation-leaking names, and optional-without-defaults are all entropy-raising — we reject them.

**Explicit carve-out.** Bot-authored widgets remain HTML+SDK (per `feedback_widget_library_ai_first`). The library is an AI-first surface; bots write HTML widgets via `file_ops` against `widget://{core|bot|workspace}/...`. This track does not touch that contract. The default flip to YAML applies only to **integration-owned** widgets (`integrations/<id>/` + declarative `integration.yaml`).

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | `image` v2 — aspect-ratio, auth: bearer, overlays, lightbox | ✅ shipped 2026-04-24 |
| 2 | `tiles` v2 — image-first mode, per-item action, status chip | ✅ shipped 2026-04-24 |
| 3 | `timeline` primitive — SVG lane-based event renderer | ✅ shipped 2026-04-24 |
| 4 | ISO-8601 canonicalization — server-side coercion helper, doc policy | ✅ shipped 2026-04-24 |
| 5 | Port frigate to YAML — three `template:` widgets + `widget_presets` + `bindings.py`; delete HTML files | ✅ shipped 2026-04-24 (Phase 5a–5c: all three widgets ported, HTML deleted, presets + bindings wired so widgets appear in the Presets tab) |
| 6 | Audit remaining integration HTML (openweather, browser_live, excalidraw) — port what fits, keep bespoke HTML where truly custom | 📋 queued |
| 7 | Flip `widget-system.md` decision table — YAML default for integration-owned; HTML first-class for bot-authored (unchanged) | 📋 rides Phase 5 |

## Phase detail

### Phase 1 — `image` v2

Canonical contract:

```yaml
- type: image
  url: "/api/v1/attachments/<id>/file"   # required
  alt: "Driveway camera"                  # optional, a11y
  aspect_ratio: "16 / 9"                  # CSS ratio string
  auth: bearer                            # "none" | "bearer" (default "none")
  lightbox: true                          # default false
  overlays:                               # optional; normalized 0..1 coords
    - {x: 0.12, y: 0.30, w: 0.18, h: 0.42, label: "person", color: accent}
```

Entropy-minimizing choices:
- `auth: bearer | none` — RFC 7235 vocabulary; every LLM has seen `Authorization: Bearer`. Rejected `fetch: blob` because it leaked implementation (blob URLs) and forced the model to guess why fetch mode affects auth.
- Overlay coords normalized — removes pixel-vs-percent ambiguity.
- `color: accent` uses existing `SemanticSlot` tokens — no new vocabulary.
- Unknown `auth` value rejected at parse time — loud failure, not silent fallback.

Work (shipped 2026-04-24):
- Extended `ImageNode` interface in `ui/src/components/chat/renderers/ComponentRenderer.tsx` with `aspect_ratio`, `auth`, `lightbox`, `overlays` fields + `ImageOverlayRect` shape.
- Rewrote `<ImageBlock>` + added `<OverlayRect>` + `<Lightbox>` sub-components. Blob-auth via new `useAuthedImageUrl` hook (uses `getAuthToken()` + `useAuthStore` serverUrl, fetches with `Authorization: Bearer`, creates object URL, revokes on unmount/url-change).
- Server schema: added `AUTH_MODES` / `AuthMode` validator + `_ImageOverlay` sub-model in `app/schemas/widget_components.py`. Overlay coords accept number or templated string (`"{{d.x}}"`); unknown `auth` values rejected at registration with `must be one of ['none', 'bearer']`.
- `docs/widget-templates.md` — added `image` primitive reference subsection with full field table + entropy note on `auth` vocabulary choice.
- Tests: `tests/unit/test_widget_components_image_v2.py` — 11 tests covering minimal shape, full v2 shape, auth enum rejection, templated auth, templated overlay coords, missing-field rejection, unknown-color rejection, extra-key rejection, full-body round-trip. All 11 pass. Regression sweep across `test_widget_package_validation.py` + `test_widget_templates.py` — 102 total, 0 regressions. UI `tsc --noEmit` clean.

### Phase 2 — `tiles` v2

Canonical contract:

```yaml
- type: tiles
  min_width: 220
  items:
    - label: "Driveway"                   # required
      value: "Live"                       # optional, large display
      caption: "1920×1080 · 5fps"         # optional, footer text
      image_url: "/api/v1/..."            # optional — presence flips tile to image-first
      image_aspect_ratio: "16 / 9"
      image_auth: bearer                  # same semantics as image.auth
      status: success                     # optional corner chip
      action:                             # optional on-click
        dispatch: tool
        tool: frigate_snapshot
        args: {camera: "driveway"}
```

Entropy-minimizing choices:
- One primitive, not two — `image_url` presence is the mode switch. Avoids `image_tiles` fragmentation and keeps LLMs on the same primitive when adding/removing images.
- `image_*` field names parallel the `image` primitive — consistent vocabulary.
- `action` reuses existing dispatch shape — no new grammar.

Work (shipped 2026-04-24):
- Extended `_TileItem` in `app/schemas/widget_components.py` — added `image_url`, `image_aspect_ratio`, `image_auth` (reuses `AuthMode`), `status` (reuses `SemanticColor`), and `action` (reuses `WidgetAction`). Extra-key rejection remains on — typos like `imageUrl` (camelCase) fail loudly.
- Rewrote `TilesBlock` in `ui/src/components/chat/renderers/ComponentRenderer.tsx` — split into `TextTile` + `ImageTile` sub-components. Image tiles render cover-fill with a bottom-gradient label overlay (matches the steal-from-frigate cameras pattern). Mixed text/image items in the same `items[]` work — grid tracks stay consistent; each tile picks its mode per-item. Added `StatusChip` (small dot, top-right, `SemanticSlot` color). Added `useTileAction` hook — wraps `useAction()` with busy state; entire tile becomes the button when `action` is set (role="button", Enter/Space key handling).
- `docs/widget-templates.md` — new `tiles` primitive reference subsection with full field table + entropy notes.
- Tests: `tests/unit/test_widget_components_tiles_v2.py` — 21 tests: text-only backward-compat, empty item shape, image-first full shape, all `AuthMode` values accepted, unknown `image_auth` rejected, templated `image_auth`, all `SemanticColor` status slots, unknown status rejected, `action` with tool/widget_config/unknown-dispatch, extra-key rejection (camelCase typo), mixed text+image items, full round-trip through `ComponentBody`. All 21 pass. Regression sweep across `test_widget_components_image_v2.py` + `test_widget_package_validation.py` + `test_widget_templates.py` = 123 total, 0 regressions. UI `tsc --noEmit` clean.

### Phase 3 — `timeline` primitive

Canonical contract:

```yaml
- type: timeline
  # omit `range` for auto-fit (span from events); set explicitly to fix the window:
  # range: {start: "2026-04-23T12:00:00Z", end: "2026-04-23T18:00:00Z"}
  lanes:                                  # optional; omit for flat timeline
    - {id: driveway, label: "Driveway"}
    - {id: backyard, label: "Backyard"}
  events:
    - id: "ev-123"                        # required — selection state needs stable ids
      start: "2026-04-23T14:00:12Z"       # required, ISO 8601
      end:   "2026-04-23T14:00:28Z"       # optional, defaults start + 2s
      lane_id: driveway                   # required when lanes present
      label: "person"
      color: accent                       # SemanticSlot
      subtitle: "score 0.91"              # optional hover/detail text
  on_event_click:                         # optional
    dispatch: widget_config
    config: {selected_event: "{{event.id}}"}
```

Entropy-minimizing choices:
- Omit `range` = auto. Rejected `range: "auto" | {start, end}` because mixed-type fields trip LLMs.
- ISO 8601, not epoch seconds — self-documenting, LLM-reliable.
- `event.id` always required — without it, selection state can't survive re-renders. Loud failure, not silent.
- `lane_id` required when lanes present, absent when not — mirrors how a human thinks about timelines.

Work (shipped 2026-04-24):
- Schema: `TimelineNode`, `_TimelineLane`, `_TimelineRange`, `_TimelineEvent` in `app/schemas/widget_components.py`. `@model_validator(mode="after")` enforces the three lane invariants (lane_id required when lanes present / forbidden when absent / must match a declared lane). Templated `events` (each-block or templated string) bypass the invariant in schema — runtime enforces. Wired into `ComponentNode` union, `KNOWN_COMPONENT_TYPES`, `COMPONENT_MODELS`.
- Renderer: `TimelineBlock` in `ui/src/components/chat/renderers/ComponentRenderer.tsx`. SVG-based. `ResizeObserver` rescales on container resize. Computes viewBox from auto-fit or explicit range (with 4% pad on auto). Renders lane backgrounds + labels, ~4 tick axis labels, event pills with selection stroke. Flat-mode fallback when no lanes declared (single implicit `__flat__` lane). Selection: `selected_event_id` (author-controlled) OR local `useState` (fallback). Click → `on_event_click` dispatch with event id as value. Date parsing via `Date.parse` (accepts ISO 8601 natively).
- `docs/widget-templates.md` — new `timeline` primitive reference subsection with full field table + entropy notes.
- Tests: `tests/unit/test_widget_components_timeline.py` — 24 tests: flat shape, missing id/start rejection, explicit range, partial range rejection, lanes with matching ids, all three lane invariants (missing/forbidden/unknown), all `SemanticColor` slots + rejection, `on_event_click`, `selected_event_id` binding, extra-key rejection (event/lane/range), full round-trip through `ComponentBody`, templated events bypasses invariant. All 24 pass. Regression sweep across widget schema tests = 147 total, 0 regressions. UI `tsc --noEmit` clean on `ComponentRenderer.tsx` (two pre-existing errors on unrelated slash-command code remain).

### Phase 4 — ISO 8601 canonicalization

Companion to Phase 3. Write once, apply everywhere new.

Work (shipped 2026-04-24):
- `app/services/time_coercion.py::to_iso_z(value)` — accepts ISO 8601 strings (with or without tz), epoch seconds (< 1e12), epoch milliseconds (≥ 1e12), `datetime` (naive or aware). Naive strings/datetimes assume UTC; aware datetimes are converted to UTC. Returns `"YYYY-MM-DDTHH:MM:SSZ"` (microseconds dropped for stable output). `None` passes through. Raises `ValueError` on garbage — loud failure at transform time. Bool guard (bool is an int subclass in Python); NaN guard.
- `to_iso_z_or_none(value)` lenient variant — returns `None` instead of raising. Use in bulk map ops where one bad row shouldn't fail the widget.
- `docs/widget-templates.md` — new "Timestamp policy — ISO 8601 at the primitive boundary" subsection: example transform, policy explanation, pointer to helper.
- Tests: `tests/unit/test_time_coercion.py` — 22 tests covering all accepted types (None passthrough, epoch s int/float, epoch zero, epoch ms, threshold boundary, ISO with Z / offset / naive / microseconds, datetime aware UTC / non-UTC / naive), all rejection cases (empty/whitespace/garbage strings, NaN, bool, unsupported type), and the lenient variant. All 22 pass.
- Not called by schema — schema accepts bare strings. Helper is for integration transforms to call explicitly before shaping tool results into primitive-friendly data. Matches the "coerce at the edge" policy in the doc.

### Phase 5 — Port frigate to YAML

Replace the three HTML files with YAML widgets that compose from the new primitives.

**Shipped 2026-04-24 (all three widgets):**
- **`frigate_snapshot`** → YAML `template:` with `image` v2 (`auth: bearer`, `aspect_ratio: "16 / 9"`, `lightbox: true`). Stays a `tool_widget`. Same `state_poll` + widget_config bbox toggle; bbox toggle no longer inline (flipped via the pin config panel) because the template engine has no `!` / negation operator and adding two `when:`-gated buttons would need a pre-substitution transform this widget doesn't otherwise use.
- **`frigate_get_events`** → YAML `template:` with `timeline` primitive. Two cooperating transforms in a new `integrations/frigate/widget_transforms.py`: `_reshape_events(parsed) -> dict` is the single reshape core (epoch → ISO 8601 via `app.services.time_coercion.to_iso_z_or_none`; SemanticSlot color per label; lanes derived from distinct cameras, alphabetized; events missing id or with unparseable `start_time` are dropped). `events_view(raw, meta) -> dict` is the state-poll signature wrapper; `render_events_widget(data, components) -> list[dict]` is the widget-level code-transform wrapper that builds the components list directly (since the template engine's single-pass substitution can't re-shape raw data into the primitive shape — it's the HA `render_single_entity_widget` pattern). Stays a `tool_widget`. Top-level `template.components: []` placeholder; state_poll has its own substitutable template.
- **`frigate_list_cameras`** → YAML `template:` with `tiles` v2. Drill-down grid, not a live wall: each tile carries `label` / `caption` (`WxH · Nfps`) / `status` (`success` enabled, `muted` disabled), and `action.dispatch: "tool"` opens `frigate_snapshot` for that camera inline. The old HTML did per-tile 10s snapshot polling with object-URL blobs; that pattern required either per-tile `state_poll` (not in primitive scope) or tool-side attachment fan-out (one N-sized DB write burst every 10s per viewer). Dropped both in favor of the primitive-aligned drill-down — users who want the monitor-wall aesthetic pin N `frigate_snapshot` widgets on a dashboard, which is what dashboards are for. The transform pair mirrors the events pipeline: `_reshape_cameras(parsed, widget_config) -> dict` is the reshape core (tile build, summary string, error passthrough); `cameras_view` / `render_cameras_widget` are the state-poll / widget-level adapters. `widget_config.show_bbox` threads into each tile's action `args.bounding_box` so the grid's bbox pref applies to the snapshot opened from it.
- Deleted all three: `frigate_snapshot.html`, `frigate_events_timeline.html`, `frigate_list_cameras.html`. `integrations/frigate/widgets/` now empty (directory kept; scanner no-ops on empty).
- Tests: `tests/unit/test_frigate_widget_transforms.py` — 35 tests (17 events + 18 cameras) covering reshape cores, state-poll/initial-render parity, error passthrough, empty payloads, widget_config threading, drop-on-missing-name / drop-on-unparseable-start_time, label→color mapping, summary pluralization. Smoke-tested both initial render + state_poll refresh via `apply_widget_template` / `apply_state_poll`: envelopes produce correct component trees with bounding-box flag correctly reflecting `widget_config.show_bbox`. `test_widget_flagship_catalog.TestFrigateListCamerasWidget` updated for components+json content type. Full regression: 228 widget-adjacent tests pass.

**Also shipped 2026-04-24 (Phase 5c — preset promotion):**

The three ported tool_widgets only render envelopes on tool calls. To appear in the widget builder's Presets tab (same surface as HA's Entity Chip / Light Card / Sensor Card), each needed a `widget_presets:` entry with a `binding_schema` + `binding_sources` + `default_config`. Without this, Library → Integrations showed "0 widgets" because the scanner explicitly excludes `tool_widgets` and the widgets dir was empty after Phase 5a/5b.

- **`integrations/frigate/bindings.py`** (new): `camera_options(raw, context)` turns `frigate_list_cameras` output into picker options (label/description/group with `enabled_only` param to hide disabled cams for snapshot bindings); `label_options(raw, context)` returns a curated set of Frigate detection labels matching `_LABEL_COLOR` in `widget_transforms`. Docstring notes the two must evolve together.
- **`integration.yaml` → `tool_families: frigate`** declared so preset dependency validation stays inside one family.
- **`integration.yaml` → `widget_presets:`** three entries:
  - `frigate-camera` — binds one camera + `show_bbox`, wraps `frigate_snapshot`. Picker source `frigate.cameras` → `camera_options` with `enabled_only: true`.
  - `frigate-events` — optional camera / label filters + `limit`, wraps `frigate_get_events`. Two binding sources (`frigate.cameras` + `frigate.labels`). `label_options` ignores `raw_result` but the field is required by the binding-source shape; noted in the docstring.
  - `frigate-cameras-grid` — wraps `frigate_list_cameras`, only `show_bbox` default (no required config). `binding_sources: {}`.
- Each preset declares `tool_family: frigate` + `tool_dependencies:` matching the underlying runtime tools. `runtime.tool_args` references `{{binding.*}}` so preview + first render use the user-selected values.
- Tests: new `tests/unit/test_frigate_bindings.py` — 7 tests (grouping, enabled_only filtering, description formatting, non-JSON handling, row-drop on missing name, label set). All 251 in the widget-adjacent sweep (preset + drift + manifest + flagship + scanner + templates + frigate pair) pass in Docker.
- Pre-existing failures outside my scope: `test_presets_list_can_inline_binding_options` + `test_bluebubbles_sender_metadata::test_one_to_one_still_uses_binding_fallback` fail with OR without my changes (verified by stashing yaml + re-running) — left as-is.

**Deferred (genuinely out of this phase):**
- The original spec called for `frigate_get_events` + `frigate_list_cameras` to move out of `tool_widgets:` into `widget_presets:` with `binding_sources`. Not done this session — the primary value of Phase 5 is the primitive port and HTML deletion, and the preset promotion changes the *activation surface* (users pin presets differently than tool widget results) which is a separate UX shift worth its own phase. `integrations/frigate/bindings.py` therefore not created yet.

### Phase 6 — Audit remaining integration HTML widgets

Walk `integrations/{openweather,browser_live,excalidraw}/widgets/*.html`. For each:
- Can it be expressed with current primitives (post-Phases 1–3)? → port to YAML.
- Genuinely bespoke (custom canvas, exotic interaction) → keep HTML, document why in the integration's README.

Excalidraw is likely the one genuinely-HTML case (embedded drawing canvas). Openweather and browser_live are probably portable.

### Phase 7 — Flip `widget-system.md` default

Update the "How to choose the right lane" decision table:
- **Integration-owned widgets** → default `template:` (YAML component tree). HTML is the escape hatch, not the default.
- **Bot-authored widgets** → unchanged. HTML+SDK is the primary lane (AI-first library contract). No reframing, no "legacy" framing.
- Cross-reference `feedback_widget_library_ai_first` so nobody misreads this as "YAML for bots."

## Key invariants

1. **Entropy test on every field addition.** New primitives or new fields on existing primitives must pass the "LLM emitting this has one obvious choice" bar. Document the choice + rejected alternatives in the primitive's reference entry (as phase detail entries do above).
2. **No `template` + `html_template` fragmentation at the preset layer.** A `widget_preset` points at a tool widget via `tool_name`; whatever rendering that tool_widget declares is what the preset uses. Preset authoring stays single-shape.
3. **Bot-authored HTML is never reframed as legacy.** `feedback_no_legacy_framing` — the AI-first library is the current, correct authoring surface for bots. This track adds YAML as a lane for integration authors; it does not subtract HTML from bot authors.
4. **Design-token vocabulary only.** No hex codes, no rolled-own colors in new primitives. `SemanticSlot` (accent/success/warning/danger/info/muted) + design-token CSS vars are the entire palette.

## References

- Canonical guide: `agent-server/docs/guides/widget-system.md`
- Design spec: `agent-server/docs/guides/ui-design.md`
- Existing primitives: `agent-server/ui/src/components/chat/renderers/ComponentRenderer.tsx`
- Widget preset engine: `agent-server/app/services/widget_presets.py`
- Frigate port target: `agent-server/integrations/frigate/`
- Entropy principle origin: conversation 2026-04-24 — "if I were a large language model, is this the yaml binding contract that maximally reduces my entropy"
- Related: [[Track - Widgets]], [[Track - Widget Dashboard]], [[Track - Integration Contract]]
