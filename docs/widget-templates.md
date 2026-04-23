# Widget Templates

For the overall taxonomy and how tool widgets fit alongside presets, standalone HTML widgets, native widgets, and dashboard pins, read [Widget System](guides/widget-system.md) first. This document is the detailed reference for the tool-widget lane only.

Tool results in Spindrel can render as rich, interactive widgets — status
chips, toggles, sliders, tables, charts — instead of plain JSON. Each tool
has a *widget template package* that pairs a YAML template with optional
Python transform code. The active package for a tool is resolved at the
widget rendering time and produces a `ToolResultEnvelope` the UI renders
via `ComponentRenderer`.

Packages are editable in the admin UI at **Tools → Widget Library**.

## Product terms

The system-level explanation lives in [Widget System](guides/widget-system.md); this section is just the local vocabulary needed for the tool-widget lane.

| Term | Meaning |
|---|---|
| Widget preset | A ready-to-pin guided binding flow. Example: "Home Assistant Light Card" where the user only selects an entity. |
| Tool widget | A YAML-defined widget contract bound to one tool's output. This is what this document describes. |
| Tool renderer / template | Legacy internal wording for the tool-widget lane. |
| Native widget | A first-party React widget like Notes or Todo with host-owned actions and persistence. |
| HTML widget | A standalone iframe/bundle widget, either library-backed or emitted at runtime via `emit_html_widget`. This is distinct from a tool widget that happens to use `html_template`. |

Use a **preset** when the product should guide the user through binding a real object like an entity, device, or task feed. Use a **tool widget** when you are authoring how one tool's output should render once the tool has already been called.

## Picking a mode

There are three ways a tool-related experience can become a rendered card. They coexist and target different problems:

| Mode | Who authors | When to use |
|---|---|---|
| Component template (YAML `template:`) | Integration author — declarative | A tool widget whose UI fits the component grammar (status, toggle, slider, tiles, properties, tables). |
| HTML template (YAML `html_template:`) | Integration author — bundled HTML file | Still a tool widget, but rendered through HTML because the tool's output wants richer visuals or layout. |
| Runtime `emit_html_widget` | Bot author — HTML written at chat time | A standalone HTML widget, not a tool widget. Useful for one-off dashboards and custom mini-apps. See [HTML Widgets guide](guides/html-widgets.md). |

If you want every call to a tool to render the same way, pick **HTML template**. If each call emits its own bespoke standalone widget, use **`emit_html_widget`** instead.

!!! tip "Looking for standalone HTML widgets?"
    The system on this page is for **tool widgets** — including tool widgets that render through `html_template`. If you want a standalone HTML mini-app, chart, or dashboard that is not bound to one tool definition, see the [HTML Widgets guide](guides/html-widgets.md).

!!! tip "Where these widgets live"
    Both component widgets and HTML widgets pin onto the same dashboards — named user boards and per-channel boards. See [Widget Dashboards](guides/widget-dashboards.md) for dashboard creation, the OmniPanel rail, grid presets, and editing.

## Package model

A package has three things:

1. **YAML template** — declarative shape of the widget (required).
2. **Python transform code** — optional post-processing logic.
3. **Sample payload** — JSON blob used for live preview (optional).

There are two sources:

| Source | What it is | Editable? |
|---|---|---|
| `seed` | Hydrated from `integration.yaml`'s `tool_widgets` section or `app/tools/local/*.widgets.yaml` on every boot. | Read-only. Fork to edit. |
| `user` | Created or forked in the UI. | Editable. |

Exactly **one** package per tool is `is_active` at any time. The active
user package overrides the seed; deleting a user package falls back to the
newest non-orphan seed.

Seeds re-hydrate on every boot — if an integration updates its shipped
template, the seed row is refreshed in place, **but your active user
package is not touched.** If you'd like the new seed, switch back to it or
re-fork.

## YAML template reference

Minimum valid body:

```yaml
template:
  v: 1
  components: []
```

Common top-level keys:

| Key | Type | Notes |
|---|---|---|
| `content_type` | string | Defaults to `application/vnd.spindrel.components+json`. |
| `display` | `inline` \| `panel` \| `modal` | How the UI positions the widget. |
| `template.v` | literal `1` | Schema version. |
| `template.components` | list | Component tree (see below). |
| `transform` | `"module:func"` or `"self:func"` | Optional post-substitution hook. |
| `display_label` | string | Templated label used by pinned widgets. |
| `state_poll` | object | Optional live-refresh config (see below). |
| `default_config` | object | Merged under user `widget_config` as `{{config.*}}`. |
| `config_schema` | object | Optional JSON Schema for editing runtime widget config. Must be an object schema. |

### Substitution syntax

Anywhere inside the template, `{{...}}` expressions are substituted from
the parsed tool result JSON plus any `config` overlay:

| Expression | Meaning |
|---|---|
| `{{name}}` | Simple key lookup. |
| `{{a.b.c}}` | Nested dot-path. |
| `{{items[0].id}}` | Array index + dot-path. |
| `{{state == 'on'}}` | Equality → boolean. |
| `{{items \| pluck: name}}` | Extract a field from each item. |
| `{{items \| map: {label: name, value: id}}}` | Map array into new shape. |
| `{{items \| where: type=entity}}` | Filter array items. |
| `{{items \| first}}` | First item from a list. |
| `{{items \| join: , }}` | Join with a separator. |
| `{{items \| count}}` | Length of a list/dict. |
| `{{name \| default: Untitled}}` | Fallback if null. |
| `{{state \| in: on,idle}}` | Membership test → boolean. |
| `{{error \| not_empty}}` | Truthy test → boolean. |
| `{{error \| not}}` | Boolean inverse. |
| `{{status \| status_color}}` | Map status strings to color names (`success`, `danger`, etc.). |
| `{{ts \| date_relative}}` | ISO 8601 timestamp → compact relative string (`5m ago`, `Apr 18`). |

Pipes chain left-to-right with `" | "` (with spaces): `{{items | pluck: name | join: , }}`.

### Component-level directives

| Directive | Notes |
|---|---|
| `when: "{{expr}}"` | Gate a component on a boolean expression. |
| `each: "{{array}}"` + `template: [...]` | Expand an array into multiple components. Current item is `{{_}}` / `{{_.field}}`. |

### Component design language

Component templates render as native low-chrome dashboard controls. Treat
the component tree as user-facing UI, not as a visualized YAML/debug dump:

- Prefer card-sized templates for normal dashboard, rail/dock, builder,
  and chat placement. Chips are explicit chip presets/templates, not an
  automatic collapse target for every card.
- Use object labels, not action labels. A toggle label should be
  `Office Light Switch` with `on_label` / `off_label`, not a generic
  `Power` row.
- Keep internal identifiers (`entity_id`, database ids, raw tool ids) out
  of normal content. If they are useful, mark them as
  `properties.variant: metadata` / `priority: metadata` so compact cards
  can hide them first.
- The host passes layout and measured grid size to the renderer. Cards
  adapt across `compact`, `standard`, and `expanded` density by collapsing
  metadata/details first; a card placed too small should be resized or
  expanded, not squeezed into a chip.

Useful optional fields:

| Component | Field | Notes |
|---|---|---|
| any | `priority: primary \| secondary \| metadata` | Collapse ordering hint. Compact cards hide metadata first. |
| `properties` | `variant: default \| metadata` | Metadata rows are quieter and hidden in compact density. |
| `toggle` | `description` | Secondary text under the subject label. |
| `toggle` | `on_label` / `off_label` | State text when `description` is not provided. |

### State polling

Add a `state_poll` block to refresh a pinned widget's state by calling
another tool:

```yaml
state_poll:
  tool: GetLiveContext
  args: {}
  transform: self:state_poll_transform     # optional
  refresh_interval_seconds: 10
  template:
    v: 1
    components:
      - type: status
        text: "{{state}}"
```

`args` values are templated from the pin's `widget_meta` (`display_label`,
`config`), allowing per-pin args like `{{display_label}}`.

## HTML template mode

For tools whose result needs rendering beyond the component grammar (live
camera snapshots, canvas overlays, custom timelines), an integration can
ship a bundled HTML file instead of a component tree. The tool's JSON
result flows into the iframe as `window.spindrel.toolResult` and the
widget's own JS owns the render.

```yaml
tool_widgets:
  frigate_snapshot:
    content_type: application/vnd.spindrel.html+interactive
    display: inline
    display_label: "Snapshot — {{camera}}"
    html_template:
      path: widgets/frigate_snapshot.html   # relative to the integration dir
    default_config:
      show_bbox: true
    state_poll:
      tool: frigate_snapshot
      args:
        camera: "{{display_label}}"
        bounding_box: "{{config.show_bbox}}"
      refresh_interval_seconds: 60
```

Two key rules:

- `template:` and `html_template:` are mutually exclusive. Pick one.
- `state_poll.template` is **not** used in HTML mode. The poll re-invokes
  the tool and the new `toolResult` is pushed into the iframe — the HTML
  file itself re-renders. No sub-template to author.

### `html_template` shape

| Form | When to use |
|---|---|
| `html_template: { path: "widgets/foo.html" }` | Integration seeds. The seeder reads the file at boot and inlines its body into the stored YAML. Edits to the file land on restart. |
| `html_template: { body: "…" }` | User-forked DB packages authored via the admin UI. Inline HTML as a YAML block scalar. |

Paths are resolved against the integration's directory (for seeds) or the
core `app/tools/local/` dir. Path traversal is blocked.

### The injected data preamble

Before the HTML body runs, the renderer prepends:

```html
<script>
  window.spindrel = window.spindrel || {};
  window.spindrel.toolResult = {/* tool JSON result, including merged config under toolResult.config */};
</script>
```

Widget JS reads `window.spindrel.toolResult` synchronously at load:

```js
const { attachment_id, filename, config } = window.spindrel.toolResult;
document.querySelector("h3").textContent = filename;
if (config.show_bbox) {
  document.body.dataset.showBbox = "true";
}
```

### Responding to refreshes

State polling re-invokes the tool and pushes the new JSON in without
reloading the iframe — `srcDoc` stays stable, so scroll position, focused
form fields, running animations, and any other in-iframe state survive
the refresh. Subscribe with a custom event:

```js
window.addEventListener("spindrel:toolresult", (ev) => {
  render(ev.detail);  // ev.detail === window.spindrel.toolResult
});
render(window.spindrel.toolResult);  // initial paint
```

### Auth, scopes, CSP

Same as runtime HTML widgets — iframes authenticate as the emitting bot
via a short-lived JWT, NOT as the viewing user. Use one of two helpers:

- **`window.spindrel.api(path, options?)`** — JSON-in / JSON-or-text-out.
  Throws on `!ok`, returns the parsed body. Right choice for most calls.
- **`window.spindrel.apiFetch(path, options?)`** — bearer-attached
  `fetch` that returns the raw `Response`. Use it for binary payloads
  (images, video, downloads) or when you want to stream or inspect
  headers yourself.

```js
// JSON
const stats = await window.spindrel.api("/api/v1/tools");

// Binary — image from an attachment
const r = await window.spindrel.apiFetch("/api/v1/attachments/" + id,
  { headers: { Accept: "image/*" } });
if (!r.ok) throw new Error("HTTP " + r.status);
img.src = URL.createObjectURL(await r.blob());
```

Raw `fetch()` is unauthenticated and will 401 on scoped endpoints. Both
helpers pick up the same auto-rotating bot token, so long-running widgets
keep working without re-authenticating.

The iframe CSP allows `img-src data: blob: 'self'` and `connect-src
'self'` — any cross-origin URL (e.g. a direct `http://frigate:5000/...`
stream) is blocked. Route media through the app's attachment or
widget-accessible endpoints.

### CSP and HTML size

HTML widgets are **exempt from the 4KB inline body cap**. Declarative
templates routinely carry styles + markup + JS in one file. Runtime
bot-authored HTML widgets get the same exemption.

### Authoring checklist

- File lives under the integration dir (e.g. `integrations/frigate/widgets/my.html`).
- `integration.yaml` declares `tool_widgets.<tool>.html_template.path` as a relative path.
- HTML is a fragment — no `<!doctype>` or outer `<html>`/`<body>`. The renderer wraps.
- `<style>` and `<script>` tags inside the fragment are fine.
- Widget JS reads `window.spindrel.toolResult` for initial state and subscribes to `spindrel:toolresult` for refreshes.
- API calls go through `window.spindrel.api()` (JSON) or `window.spindrel.apiFetch()` (binary / raw Response).
- Images/media use same-origin URLs (the app's attachment or file-content endpoints).

## Python transform code

Optional. If present, it's compiled into a synthetic module at load time
and exposed to the template via the `self:` prefix.

Conventions:

```python
def transform(data: dict, components: list[dict]) -> list[dict]:
    """Post-substitution hook for the main template.

    data       — the parsed tool result JSON plus {"config": {...}}
    components — the list of components after {{...}} substitution
    Returns    — the new components list
    """
    return components


def state_poll_transform(raw_result: str, widget_meta: dict) -> dict:
    """Reshape a state_poll result before template substitution.

    raw_result  — the poll tool's raw JSON string
    widget_meta — {"display_label": ..., "config": ...}
    Returns     — a dict used as the substitution data
    """
    return {}
```

Reference either function from YAML:

```yaml
transform: self:transform
state_poll:
  transform: self:state_poll_transform
```

Any Python is allowed — imports, helper functions, module-level constants.
The module runs once per `(package_id, version)` and is cached; a version
bump (on save) re-execs it.

### Failure behavior

- If YAML is invalid on save, the API returns 422 — nothing is persisted.
- If Python fails to compile on save, same — 422.
- If Python raises at runtime, the existing transform fallback kicks in
  (substitution result is used as-is, warning logged).
- If a package is active but the loader fails to exec it at boot, the
  package is marked `is_invalid` and the tool falls back to the newest
  non-orphan seed. Activating an invalid package returns 409.

## Live preview

The editor runs the full substitution + transform pipeline against your
**sample payload** on each keystroke (debounced). The preview renders with
real `ComponentRenderer`, so you see exactly what users see — except
button/toggle dispatches are no-op'd ("Preview mode — actions disabled").

A good sample payload matches the shape of what your tool actually
returns. Capture one from a recent invocation, or paste by hand.

## Trust model

Python code in a package executes **unsandboxed** in the server process,
with full network and filesystem access. This is intentional — package
authoring is admin-only, and it's the same trust level as editing any
other integration's Python source on disk.

Do not install community packages from sources you don't trust.

## Operational notes

- **Multi-process deploys**: the in-memory registry is per-process. An
  activation on pod A won't reach pod B until the next boot. A follow-up
  will add LISTEN/NOTIFY or per-request version re-check.
- **MCP-prefixed tools** (`homeassistant-HassTurnOn`): store the package
  under the bare tool name (`HassTurnOn`). The resolver tries the full
  name first, then strips the prefix.
- **Preview side effects**: your transform can make network calls during
  preview. Keep them idempotent, or shell out behind a guard.

## See also

- `app/services/widget_templates.py` — template engine + substitution filters.
- `app/services/widget_package_loader.py` — synthetic Python module loader.
- `app/services/widget_packages_seeder.py` — boot-time seeding from YAML.
- `ui/src/components/chat/renderers/ComponentRenderer.tsx` — the UI renderer.
