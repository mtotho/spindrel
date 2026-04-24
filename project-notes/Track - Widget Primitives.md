---
tags: [agent-server, track, widgets, yaml, integrations]
status: active
updated: 2026-04-24 (Phase 1 shipped)
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
| 2 | `tiles` v2 — image-first mode, per-item action, status chip | 📋 queued |
| 3 | `timeline` primitive — SVG lane-based event renderer | 📋 queued |
| 4 | ISO-8601 canonicalization — server-side coercion helper, doc policy | 📋 queued (rides Phase 3) |
| 5 | Port frigate to YAML — three `template:` widgets + `widget_presets` + `binding_sources`; delete HTML files | 📋 queued |
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

Work:
- Extend `TilesNode` / item shape in `ComponentRenderer.tsx`.
- Image-first render: image fills tile, label overlay on bottom-gradient (matches existing frigate cameras pattern — steal that styling).
- Per-item `action` dispatch wiring (tool / widget_config / refresh).
- Tests: text-only tiles unchanged, image-first tiles render, mixed modes in the same `items[]` work.

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

Work:
- New `TimelineNode` interface + `<TimelineBlock>` React component.
- SVG layout: axis ticks (~4 evenly spaced), lane backgrounds, event pills, selection stroke. Borrow layout math from `frigate_events_timeline.html` (`renderAll` function).
- Click handler → dispatch.
- Responsive: rescale on container resize.
- Server-side schema validation.
- Tests: auto-range from events, explicit range, flat-lane fallback, selection stroke persists across data updates, click dispatch fires with event id.

### Phase 4 — ISO 8601 canonicalization

Companion to Phase 3. Write once, apply everywhere new.

- New helper `app/services/time_coercion.py::to_iso_z(value)` — accepts ISO 8601, epoch seconds, epoch ms, datetime object; returns ISO 8601 UTC string with `Z` suffix.
- Primitive schemas call this on any `*_time` / `start` / `end` / timestamp field before rendering.
- Document in `docs/guides/widget-system.md`: "Primitive timestamps are ISO 8601. Integration transforms coerce native formats at the edge."
- Legacy integrations (no migration forced) — their tool-result JSON can keep epoch seconds; the primitive layer coerces on the way in.

### Phase 5 — Port frigate to YAML

Replace the three HTML files with YAML widgets that compose from the new primitives:

- **`frigate_snapshot`** → `template:` with `image` v2 (overlays for bbox, `auth: bearer`, lightbox, aspect-ratio). Stays a `tool_widget` — arg-driven per-camera.
- **`frigate_list_cameras`** → `template:` with `tiles` v2 (image-first tiles, each tile's `image_url` points at a fresh snapshot attachment). `widget_preset` with `binding_sources: frigate.cameras` for optional subset filter. Moves out of `tool_widgets:`, lives in library.
- **`frigate_events_timeline`** → `template:` with `timeline` primitive. `widget_preset` with label-filter + time-window picker. Moves out of `tool_widgets:`.
- New `integrations/frigate/widget_transforms.py` — reshape `frigate_list_cameras` / `frigate_get_events` tool output into the primitive-friendly shape (tiles items, timeline events with ISO timestamps).
- New `integrations/frigate/bindings.py` — `frigate.cameras` binding source (returns `[{value, label}]` from `frigate_list_cameras`).
- Delete `integrations/frigate/widgets/frigate_*.html`.

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
