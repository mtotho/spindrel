---
name: emit_html_widget — entry point
description: Routing skill for `emit_html_widget`. Three source modes (`library_ref` / `html` / `path`), bundle layout, YAML frontmatter, `widget://` path grammar, CSP sandbox + `extra_csp`, and the bot-scoped auth model live at `get_doc("reference/widgets/html")`.
triggers: emit_html_widget, preview_widget, inline html widget, path html widget, widget bundle, workspace widget, extra_csp, widget sandbox, widget frontmatter, display_mode panel, widget path grammar, widget dry run
category: core
---

# `emit_html_widget` — entry point

`emit_html_widget` ships an HTML widget into the channel. A widget is a **folder, not a file** — author the bundle under a `widget://` path, then emit it by `library_ref`. Inline `html=...` and explicit `path=...` modes exist for one-off cases.

**The full reference moved out of skills.** It's now a doc:

```
get_doc("reference/widgets/html")
```

The reference covers: bundle layout, the YAML frontmatter contract (`name`, `display_label`, `panel_title`, `version`, `tags`, `icon`, `suite`/`package`), the `widget://` path grammar (bot / workspace / core scopes), the three source modes with worked examples, `preview_widget` dry-runs, the CSP sandbox + `extra_csp` directives, the bot-scoped auth model, panel titles, scroll, and layout/sizing.

## Decide the source mode first

| Mode | Signature | When | Auto-updates |
|---|---|---|---|
| **library_ref** (default) | `emit_html_widget(library_ref="<name>", display_label?)` | You authored a bundle under `widget://bot|workspace|core/<name>/`. Pinned widget refreshes when bundle files change. | Yes |
| **inline** | `emit_html_widget(html=..., js?, css?)` | One-off snapshot built from data already in hand. | No |
| **path** | `emit_html_widget(path="/workspace/.../index.html")` | Ad-hoc workspace file outside the library. Polls every 3s. | Yes |

Exactly one of `library_ref` / `html` / `path` is required.

## Workflow rules of thumb

1. **Author bundles under `widget://bot/<name>/...`** with `file(create, ...)`. Name pattern: `[a-zA-Z0-9_-]+`. Don't encode channel IDs in paths.
2. **Frontmatter goes inside an HTML comment at the very top** — only `name` is required; without a frontmatter block the card title falls back to the slug. Bump `version` whenever you change the widget.
3. **Always run `check_html_widget_authoring(library_ref=..., include_runtime=true, include_screenshot=true)`** after writing or editing — wraps `preview_widget` + manifest/CSP check + real browser load.
4. **Use `preview_widget(...)` for cheap dry-runs** during iteration; structured `{ok, envelope?, errors[]}` output catches bad paths, manifest errors, CSP rejections.
5. **`extra_csp` is per-widget and additive** — concrete `https://host[:port]` only, max 10 origins per directive, snake_case keys (`script_src`, `connect_src`, `img_src`, `style_src`, `font_src`, `media_src`, `frame_src`, `worker_src`).
6. **Widgets run as the emitting bot, not the viewer.** Use `window.spindrel.api(path)`, not raw `fetch` (raw fetch lacks the bearer). Your bot's scopes are the ceiling.
7. **`display_mode="panel"` is rare.** Default `inline` (grid tile). Only set `panel` when the widget IS the dashboard.

## See also

- `get_doc("reference/widgets/html")` — full mode/bundle/sandbox/auth reference + worked examples
- skill `widgets` — decision tree across tool/HTML/native widget kinds
- skill `widgets/sdk` — `window.spindrel.api`, `callTool`, workspace files, streams
- skill `widgets/styling` — `sd-*` vocabulary + theme
- skill `widgets/manifest` — `widget.yaml` for backend-capable bundles
- skill `widgets/errors` — widget-not-rendering / 422 / CSP-blocked lookup
