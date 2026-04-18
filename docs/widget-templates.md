# Widget Templates

Tool results in Spindrel can render as rich, interactive widgets — status
chips, toggles, sliders, tables, charts — instead of plain JSON. Each tool
has a *widget template package* that pairs a YAML template with optional
Python transform code. The active package for a tool is resolved at the
widget rendering time and produces a `ToolResultEnvelope` the UI renders
via `ComponentRenderer`.

Packages are editable in the admin UI at **Tools → Widget Library**.

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
