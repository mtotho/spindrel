---
tags: [agent-server, reference, widgets]
status: reference
updated: 2026-04-17
---
# Widget Authoring

Reference for building tool-result widgets. Read this before editing `*.widgets.yaml` or adding `tool_widgets:` to an integration manifest.

Driving track: [[Track - Widgets]].

---

## Your first widget in 10 minutes

1. Your tool returns JSON: `{"tasks": [{"id": "1", "title": "Do the thing", "status": "pending"}], "count": 1}`.
2. Pick where the template lives:
   - **Core tool** → create `app/tools/local/<tool>.widgets.yaml` (co-located with the Python tool file).
   - **Integration** → add under `tool_widgets:` in `integrations/<name>/integration.yaml`.
3. Author the template (see below). Minimum viable:
   ```yaml
   list_tasks:
     display: inline
     template:
       v: 1
       components:
         - type: heading
           text: "Tasks ({{count}})"
           level: 3
         - type: table
           columns: ["Title", "Status"]
           rows:
             each: "{{tasks}}"
             template: ["{{_.title}}", "{{_.status}}"]
   ```
4. Restart the server. The widget is active — invoke the tool in a channel to see it.
5. Hitting the limits of declarative templates? Reach for a [Python transform](#code-extension-python-transforms) or declare `_envelope` directly in the tool return (see [three pathways](#three-pathways)).

---

## Three pathways

When a tool returns, the dispatcher (`app/agent/tool_dispatch.py:dispatch_tool_call`) picks **one** of three rendering pathways:

| # | Path | When | Who authors |
|---|------|------|-------------|
| A | `_envelope` opt-in | Tool returns `{"_envelope": {...}, ...}` as the top-level key | Tool author (imperative, full control) |
| B | Widget template | A registered template exists for `tool_name` | Template author (declarative, recommended) |
| C | Default envelope | Neither of the above — dispatcher sniffs content (JSON → json tree, markdown-ish → markdown, else plaintext) | No-one — automatic |

Path B is the 95% case. Only reach for Path A when you need a one-off envelope shape that doesn't fit the component vocabulary, or when the tool already knows the right content type for its payload (e.g. a raw diff, a file listing).

---

## Template file shape

### `app/tools/local/<tool>.widgets.yaml`

```yaml
# Top-level keys are tool names (without server prefix for MCP tools).
# Keys starting with "_" are treated as YAML anchors and skipped.
list_tasks:
  content_type: application/vnd.spindrel.components+json   # optional, default shown
  display: inline                                          # badge | inline | panel  (panel not yet hosted)
  display_label: "{{id}}"                                  # optional, see [pinning & state_poll]
  default_config: {}                                       # optional, merged into data as {{config.*}}
  transform: "module.path:func"                            # optional, see [transforms]
  template:                                                # REQUIRED
    v: 1                                                   # schema version (only 1 today)
    components: [...]                                      # list of ComponentNode — see [Component reference]
  state_poll:                                              # optional, see [state_poll]
    tool: list_tasks
    args: {task_id: "{{display_label}}"}
    transform: "module.path:func"
    refresh_interval_seconds: 10
    template: {...}
```

### `integrations/<name>/integration.yaml`

```yaml
tool_widgets:
  github_get_pr:
    display: inline
    template: {...}
```

Registration priority: integrations first, then `*.widgets.yaml`. **First-registered wins** — the loader will log-and-skip duplicates (see `app/services/widget_templates.py:_register_widgets`).

---

## Component reference

Components live under `template.components[]`. Interactive primitives (`button`, `toggle`, `select`, `input`, `form`, `slider`) require a `WidgetAction` (see [Actions](#actions)).

Every component supports a top-level `when:` expression — if it evaluates falsy, the component is removed from the output before rendering.

### Display primitives

| `type` | Required | Optional | Notes |
|--------|----------|----------|-------|
| `heading` | `text` | `level: 1\|2\|3` (default 2) | Top-level title; level 3 is muted. |
| `text` | `content` | `style: default\|muted\|bold\|code`, `markdown: bool` | Set `markdown: true` to render with `MarkdownContent`. |
| `status` | `text` | `color: SemanticColor` | Pill-shaped status badge. |
| `divider` | — | `label` | Horizontal rule, optionally labeled. |
| `code` | `content` | `language` | Monospace block with scroll cap (~300px). |
| `image` | `url` | `alt`, `height` (default 400) | No layout effects beyond fixed border. |

### Grouping

| `type` | Required | Optional | Notes |
|--------|----------|----------|-------|
| `section` | `children: [Node]` | `label`, `collapsible: bool`, `defaultOpen: bool` | Max nesting depth 2 — deeper renders as flat summary. |
| `properties` | `items: [{label, value, color?}]` | `layout: vertical\|inline` | Inline = wrapped chips; vertical = grid. |
| `table` | `columns: [str]`, `rows: [[str]]` | `compact: bool` | See [each: iteration](#each-iteration) for how `rows` is usually built. |
| `links` | `items: [{url, title, subtitle?, icon?}]` | — | `icon`: `github \| web \| email \| file \| link`. |
| `tiles` | `items: [{label?, value?, caption?}]` | `min_width` (default 84), `gap` (default 6) | Responsive auto-fill grid. |

### Interactive

| `type` | Required | Optional | Notes |
|--------|----------|----------|-------|
| `button` | `label`, `action` | `variant: default\|primary\|danger`, `disabled`, `subtle` | `subtle` = opacity-25 until enclosing `group` hovered. |
| `toggle` | `label`, `value: bool`, `action` | `color: SemanticColor` | Switch; dispatches on flip. |
| `select` | `value: str`, `options: [{value, label}]`, `action` | `label` | Native `<select>`; dispatches on change. |
| `input` | `value: str`, `action` | `label`, `placeholder` | Text input; dispatches on Enter. |
| `slider` | `value: num`, `action` | `label`, `min`, `max`, `step`, `unit`, `color` | Range; debounced 300ms. |
| `form` | `children: [Node]`, `submit_action` | `submit_label` (default "Submit") | Wraps children in a submit container. |

### SemanticColor values
`default` · `muted` · `accent` · `success` · `warning` · `danger` · `info`

Background and text tones are paired (e.g. `danger` text over a subtle red bg). Don't reach for hex — if you need a new tone, add it in `ui/src/theme/tokens.ts`.

### Unknown types
Unknown `type:` values render as a dashed `Unknown: <type>` block with a JSON dump. Forward-compatible but ugly — treat as a registration-time smell.

---

## Template syntax

All string values inside a template can contain `{{...}}` expressions. Substitution happens recursively through nested dicts and lists.

### Variable paths

```
{{key}}           → data["key"]
{{a.b.c}}         → data["a"]["b"]["c"]
{{a[0].b}}        → data["a"][0]["b"]
{{_.field}}       → current item field (inside each: blocks — see below)
{{config.key}}    → merged default_config + per-pin config (see [Pinning & per-pin config])
```

If the **entire string** is a single `{{...}}` expression, the result keeps its native type (bool, list, dict). If the string is mixed (`"Hello {{name}}"`), the result is always a string — bools stringify as `"true"`/`"false"`, None becomes `""`.

### Equality

```
{{status == 'complete'}}   → bool
```

No `!=`, no `&&`/`||`. For booleans use `| not`. Need more? File under P1-2 or use a Python transform.

### Pipe transforms

Chain with `" | "` (space-pipe-space):

| Pipe | Signature | Example |
|------|-----------|---------|
| `default: <value>` | value → fallback if None | `{{x | default: —}}` |
| `not_empty` | → bool (truthy) | `{{tasks | not_empty}}` |
| `not` | bool → bool | `{{flag | not}}` |
| `count` | list\|dict → int | `{{items | count}}` |
| `in: a,b,c` | value → bool | `{{status | in: pending,active,running}}` |
| `status_color` | str → SemanticColor | `{{status | status_color}}` |
| `first` | list → first item | `{{tasks | first}}` |
| `pluck: key` | [{...}] → [key values] | `{{items | pluck: name}}` |
| `join: sep` | list → joined str (default `, `) | `{{tags | join: , }}` |
| `where: key=value` | list → filtered list | `{{rooms | where: type=entity}}` |
| `map: {out: src, ...}` | [{...}] → [{out: item.src}] | `{{rooms | map: {label: name, value: id}}}` |

`status_color` known strings: `active→accent`, `running→info`, `complete/completed/done→success`, `failed/error→danger`, `cancelled/canceled/skipped/closed→muted`, `pending→warning`, `open→success`, `merged→accent`. Unknown → `muted`.

### `when:` — conditional components

Add to any component. If falsy, the component is removed before rendering.

```yaml
- type: status
  text: "{{error}}"
  color: danger
  when: "{{error | not_empty}}"
```

Truthiness rules: `None`/empty string/`"false"`/`"null"`/`"0"` → false; empty list/dict → false; zero → false; everything else → true.

### `each:` iteration

Inside a list position (e.g. `rows`, `items`, top-level `components`), a dict with `each:` + `template:` expands:

```yaml
rows:
  each: "{{tasks}}"
  template: ["{{_.title}}", "{{_.status}}"]     # applied per item; `_` = current item
```

Scope: `_` is the current item; all outer keys remain visible. No index variable, no nested parent access beyond outer data.

---

## Actions

Interactive components carry a `WidgetAction`:

```yaml
action:
  dispatch: tool | api | widget_config
  tool: cancel_task                 # for dispatch: tool
  endpoint: /admin/tasks/{{id}}     # for dispatch: api
  method: POST | PUT | PATCH | DELETE
  args: {task_id: "{{id}}"}         # substituted from current data
  value_key: selected_value         # where to inject user input into args
  config: {include_daily: true}     # for dispatch: widget_config (shallow-merges into pin config)
  optimistic: true                  # flip client state before server confirms (rollback on error)
```

Dispatch path ends up at `POST /widget-actions` → processes the action → returns a fresh `ToolResultEnvelope` that replaces the widget in place (and broadcasts to all pinned instances).

---

## `state_poll` — live refresh

Make a widget refresh on an interval:

```yaml
schedule_task:
  display_label: "{{id}}"            # carry the task ID forward
  template: {v: 1, components: [...]}
  state_poll:
    tool: list_tasks                 # read-only tool to re-invoke
    args: {task_id: "{{display_label}}"}
    transform: "app.tools.local.task_widget_transforms:task_detail"   # optional
    refresh_interval_seconds: 10
    template: {...}                  # separate display template for poll results
```

**Current caveats** (tracked in [[Track - Widgets]]):
- `state_poll.args` can reference `{{display_label}}` only — not full template data scope. Use `display_label` as the ID-carry channel.
- If you omit `state_poll.template`, nothing renders on poll today. P1-1 will make it default to `template`.
- Envelopes stored on pinned widgets are **not** written back when state_poll refreshes — pinned-context injection uses the last stored `plain_body` (tracked as P2-3).

Poll cache is keyed by `(tool, args_json)`, 30s server-side TTL. Concurrent polls for the same key are deduped.

---

## Pinning & per-pin config

Users can pin a widget from a message to a channel's "pinned widgets" rail.

`default_config:` on the widget provides the base. Per-pin overrides (via `dispatch: widget_config`) shallow-merge on top. The merged result is exposed in both `template:` and `state_poll.args` as `{{config.*}}`:

```yaml
openweather_current:
  default_config: {include_daily: false}
  template:
    v: 1
    components:
      - type: button
        label: "{{config.include_daily ? 'Hide' : 'Show'}} forecast"   # NOTE: ternary not yet supported — use two gated buttons today
        subtle: true
        action: {dispatch: widget_config, config: {include_daily: true}}
  state_poll:
    tool: openweather_current
    args: {include_daily: "{{config.include_daily}}"}
    refresh_interval_seconds: 600
    template: {...}
```

Today the "ternary" above isn't legal — author two buttons, each `when:`-gated. P1-2 adds ternary/inline boolean composition.

### Context injection (2026-04-17)
Pinned widgets' `plain_body` + `display_label` inject into the LLM context as a plain-English block right after the temporal block. Caps: 12 pins, 250 char/pin, 2000 char total. Foreign-bot pins and "updated ~Xm ago" are annotated. No synchronous refresh — stale-but-OK. Implementation: `app/services/widget_context.py`; integrated in `app/agent/context_assembly.py`.

---

## Code extension: Python transforms

Two kinds of transform hooks, each declared by a `"module.path:function_name"` string.

### Main template transform (`transform:`)
Runs after template substitution, rewrites the `components` list.

```python
def my_transform(data: dict, components: list[dict]) -> list[dict]:
    return components  # free to mutate
```

### State-poll transform (`state_poll.transform:`)
Runs before template substitution, reshapes the raw poll result into a dict.

```python
def my_poll_transform(raw_result: str, widget_meta: dict) -> dict:
    parsed = json.loads(raw_result)
    return {**parsed, "formatted_time": iso_to_relative(parsed["run_at"])}
```

Failures log a warning and fall back (main-transform: returns components untouched; poll-transform: returns `{}`). If your transform is silently doing nothing, check the log.

Example: `app/tools/local/task_widget_transforms.py:task_detail`.

---

## Fragments

Declare `fragments:` at the top of a widget definition and reference them from the component tree via `{type: fragment, ref: <name>}`. Resolution runs once at registration time; the cached template is already expanded so runtime substitution is unchanged.

A fragment body can be **a dict** (replaces 1:1) or **a list of components** (spreads at the parent list position). Fragments may reference other fragments; cycles are detected and rejected.

```yaml
schedule_task:
  fragments:
    cancel_task_button:
      type: button
      label: Cancel
      variant: danger
      when: "{{status | in: pending,active,running}}"
      action:
        dispatch: tool
        tool: cancel_task
        args:
          task_id: "{{id}}"
  template:
    v: 1
    components:
      - type: heading
        text: "{{title | default: Task}}"
      - {type: fragment, ref: cancel_task_button}
  state_poll:
    tool: list_tasks
    args: {task_id: "{{display_label}}"}
    refresh_interval_seconds: 10
    # template: omitted → defaults to template above
```

### `state_poll.template` defaulting
If `state_poll:` is present without a `template:` child, the loader copies `template:` into it. Use this when the poll result matches the main shape (most refreshable widgets).

### `with:` overlays
Not shipped. If a fragment needs per-ref variable overrides (e.g. two call sites with different key paths), the ref can carry `with: {key: "{{override}}"}` — see [[Track - Widgets]] follow-ups. Today, duplicate the fragment or pull the shared bits lower.

---

## Testing your widget

### Template engine tests
`tests/unit/test_widget_templates.py` covers substitution, `each:`, `when:`, pipes. Add a case here if you're extending the engine.

### Registration tests
`tests/unit/test_widget_package_validation.py` validates the Pydantic component schema (ships with P0-1). Add coverage when you add a new component type.

### Sample payload
Set `sample_payload:` on the widget definition (or on `WidgetTemplatePackage.sample_payload` for DB-backed packages). P2-4 will make a CI harness that asserts every widget renders its sample payload with zero unresolved `{{...}}` and no exceptions.

### Manual smoke
Simplest: open the bot in a channel, call the tool, see the widget. For state_poll, pin the widget and wait one interval.

---

## File layout

```
app/
  agent/
    tool_dispatch.py                 # envelope dataclass, three-path dispatcher
  services/
    widget_templates.py              # engine: loader, substitution, pipes, state_poll
    widget_packages_seeder.py        # DB seeding, orphaning
    widget_context.py                # pinned-widget → LLM context
  tools/
    local/
      *.widgets.yaml                 # core tool templates (co-located)
      task_widget_transforms.py      # transform hook example
  db/models.py                       # WidgetTemplatePackage
  schemas/
    widget_components.py             # (P0-1) Pydantic component-tree schema

integrations/
  <name>/
    integration.yaml                 # tool_widgets: lives here

ui/src/
  components/chat/
    RichToolResult.tsx               # MIME dispatch
    WidgetCard.tsx                   # pinning + polling + dispatch
    renderers/
      ComponentRenderer.tsx          # the ~15 primitives
  types/
    api.ts                           # ToolResultEnvelope, WidgetAction
    widget-components.schema.json    # (P0-1) generated JSON Schema
    widgets.ts                       # (P0-1) TS types mirroring Pydantic

tests/unit/
  test_widget_templates.py
  test_widget_package_validation.py
  test_widget_package_loader.py
  test_widget_context.py
  test_widget_actions_state_poll.py
```

---

## Common smells to avoid

- **Unscoped `{{field}}` inside an `each:` block** — use `{{_.field}}`. Outside `each:`, `_` is undefined.
- **Duplicating `template:` under `state_poll.template:`** — this is the canonical motivation for P1-1 fragments. For now, accept it; once P1-1 lands, refactor.
- **Stringly-typed status color** — use `{{status | status_color}}` instead of ad-hoc mapping, unless your statuses are domain-specific (then request a pipe registry extension as P1-3).
- **Leaking display semantics into `display_label`** — `display_label` is currently doing double duty (user-facing title + `state_poll.args` carry channel). Keep values stable and human-readable; don't stuff JSON into it. P2-1 will separate the concerns.
- **Reaching for `_envelope` opt-in when a template would do** — prefer Path B. The only good reasons for Path A are: non-component content types, tool-specific rendering you can't express declaratively, or imperative short-circuits (error envelopes).
