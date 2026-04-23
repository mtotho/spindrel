# Widget System

This is the canonical reference for how the widget system works.

If other docs, UI copy, or track notes disagree with this page, this page wins.

## The shortest correct model

There are three widget definition kinds:

| Public term | Internal/API term | Who authors it | User-addable |
|---|---|---|---|
| Tool widget | `tool_widget` | integration authors, admins, advanced users | yes |
| HTML widget | `html_widget` | bots, users, integrations | yes |
| Native widget | `native_widget` | core app only | no |

There are also several instantiation paths:

| Instantiation path | Internal/API term | What it means |
|---|---|---|
| Direct tool call | `direct_tool_call` | a tool widget rendered from a normal tool result |
| Preset | `preset` | a guided binding flow that instantiates a tool widget |
| Library pin | `library_pin` | a standalone HTML widget pinned from the library |
| Runtime emit | `runtime_emit` | a standalone HTML widget emitted at runtime, usually via `emit_html_widget` |
| Native catalog | `native_catalog` | a first-party native widget placed from the catalog |

The same placed thing can appear as:

- a rich result in chat
- a pinned dashboard widget
- a channel dashboard placement

That shared placement surface is real. The authoring model underneath is not one single thing.

## The four-layer model

Keep these layers separate:

1. `widget_contract` — the semantic/runtime kind
2. `widget_origin` — how this concrete instance or pin was created
3. `widget_presentation` — authored presentation intent
4. `resolved_host_policy` — the host's final rendering decision for one placement

The system is much easier to reason about if those are not collapsed together.

### `widget_contract`

This answers: "What is this widget, semantically?"

It covers things like:

- definition kind
- binding kind
- instantiation kind
- auth model
- state model
- refresh model
- theme model
- declared actions

### `widget_origin`

This answers: "Where did this pin come from?"

Examples:

- direct tool result pin
- preset-backed tool widget
- library HTML widget
- runtime-emitted HTML widget
- native catalog widget

### `widget_presentation`

This answers: "What kind of host surface was this authored for?"

Current fields include:

- `presentation_family` — `card`, `chip`, or `panel`
- `panel_title`
- `show_panel_title`
- `layout_hints`

### `resolved_host_policy`

This answers: "How should this specific placement render right now?"

It is derived from:

- placement zone
- authored `widget_presentation`
- dashboard chrome
- per-pin runtime overrides

## The two distinctions that matter

Most confusion comes from collapsing these questions together:

1. What kind of widget definition is this?
2. How did this particular widget instance get created?

Those are different.

### Definition kind

This is the durable authoring/runtime contract.

- `tool_widget`
- `html_widget`
- `native_widget`

### Instantiation kind

This is how one concrete widget instance got into the world.

- `direct_tool_call`
- `preset`
- `library_pin`
- `runtime_emit`
- `native_catalog`

A preset is therefore not a fourth widget kind. It is an instantiation path, usually for a tool widget.

## Tool widgets

Tool widgets are the YAML-backed lane.

They are defined under a tool and are bound to that tool's output contract. The current public contract for them is:

- `definition_kind = tool_widget`
- `binding_kind = tool_bound`
- `auth_model = server_context`
- `state_model = tool_result`

### What a tool widget is

A tool widget is:

- bound to one tool name
- rendered from that tool's result plus optional `widget_config`
- optionally refreshable via `state_poll`
- placeable as a rich tool result or as a pinned widget

### What a tool widget is not

A tool widget is not:

- a standalone widget bundle
- a free-form mini app
- a synonym for preset

### Important clarification: YAML tool widgets can render two ways

This is the subtle part that caused the most confusion.

A tool widget may render through:

- the component/template renderer via `template:`
- an HTML-backed renderer via `html_template:`
- a core semantic renderer via `view_key` plus renderer-neutral `data`

All three are still `tool_widget`.

`html_template` does not turn the definition into a standalone HTML widget. It only changes how that tool-bound widget renders.

`view_key` is different: it lets a tool widget opt into a first-party semantic renderer when the payload shape is generic enough for core to own. For example, Web Search uses `view_key: core.search_results` with `{query, count, results[]}` data. The integration still owns the tool and fallback component template; core owns the reusable search-results presentation for default and terminal chat modes.

Component-template widgets follow the shared low-chrome component design
language in [Widget Templates](../widget-templates.md#component-design-language).
Cards adapt across compact/standard/expanded dashboard sizes; chip widgets
remain explicit chip presets/templates rather than automatic card collapse.

That means a YAML-defined Home Assistant card can feel visually native or custom, but it is still fundamentally:

- tool-bound
- state-from-tool-result
- instantiated from a tool call or preset

## HTML widgets

HTML widgets are the standalone iframe/widget-SDK lane.

Their public contract is:

- `definition_kind = html_widget`
- `binding_kind = standalone`
- `state_model = bundle_runtime`
- `refresh_model = widget_runtime`

They are the right lane when the widget should behave like a small app rather than a decorated tool result.

### Typical ways HTML widgets appear

- a library widget bundle discovered from core, bot, workspace, or channel scope
- a runtime-emitted widget from `emit_html_widget`

Those are different instantiation paths over the same definition kind.

### What makes HTML widgets different

HTML widgets own more of their own lifecycle:

- local JS state
- custom fetches
- custom polling
- custom layout and rendering
- bundle-owned storage or workspace-file coordination

They are not tool-bound by default, even if they happen to call tools or APIs internally.

## Native widgets

Native widgets are first-party host-rendered widgets.

Their public contract is:

- `definition_kind = native_widget`
- `binding_kind = standalone`
- `auth_model = host_native`
- `state_model = instance_state`

They are used for core widgets such as Notes and Todo where the app wants:

- host-owned persistence
- host-owned actions
- deep shell integration

Native widgets are not a public authoring lane.

## Presets

Presets are guided binding flows.

They are not a separate definition kind and they are not interchangeable with tool widgets.

The clean mental model is:

- preset = guided setup flow
- tool widget = the underlying definition that actually renders

Example:

- "Home Assistant Light Card" can be a preset
- the resulting pinned thing is usually still a `tool_widget`

### Why presets exist

Some widgets need the user to bind a real object before they make sense:

- an entity
- a device
- a mailbox
- a room
- a feed

Without presets, users would be dropped into raw tool args and ad hoc config.

### Presets versus rich tool results

A preset usually compiles a known binding into a reusable pinned widget flow.

A direct rich tool result usually comes from:

- one tool call
- maybe a `state_poll`
- pinning the resulting card as-is

Both can land on the dashboard. They are not the same DX path.

### Preset dependency contract

Presets may use more than one tool during setup and operation: a binding source can discover options, the backing tool can render, and action tools can mutate state.

That power has a hard boundary: a preset that declares `tool_family` must keep all declared dependencies inside that family. Registration now fails if a preset mixes incompatible tool families. Home Assistant uses this to keep official HA MCP presets on `GetLiveContext` / `Hass*` tools and away from community `ha_get_state`, so a user with only one HA MCP server does not get a broken "simple" preset.

Preset responses expose this as `dependency_contract`:

- `tool_family` is the declared family id/label/tool set when present.
- `tools` is the normalized set of tools the preset depends on.

## Concrete examples

| Scenario | Definition kind | Instantiation kind |
|---|---|---|
| Call a tool and get a YAML-rendered result card | `tool_widget` | `direct_tool_call` |
| Add a Home Assistant preset and pick one entity | `tool_widget` | `preset` |
| Pin a reusable bot-authored HTML bundle from the library | `html_widget` | `library_pin` |
| Have a bot emit a one-off custom HTML dashboard in chat | `html_widget` | `runtime_emit` |
| Place Notes from the built-in catalog | `native_widget` | `native_catalog` |

## The shared public contract

The system now exposes a normalized `widget_contract` object so humans and code do not need to infer behavior from manifest details or source paths.

Current fields:

| Field | Meaning |
|---|---|
| `definition_kind` | `tool_widget`, `html_widget`, or `native_widget` |
| `binding_kind` | whether the widget is tool-bound or standalone |
| `instantiation_kind` | how this concrete widget instance was created |
| `auth_model` | who the widget ultimately acts as |
| `state_model` | where authoritative state lives |
| `refresh_model` | how refresh/update is expected to happen |
| `theme_model` | which theming lane it participates in |
| `supported_scopes` | which scopes the definition claims to support |
| `actions` | declared callable actions exposed by the widget |

This is now surfaced in:

- widget library entries
- preset previews
- tool preview responses
- pinned widget serialization
- native catalog entries

`widget_contract` should stay semantic. Presentation-family concerns belong in `widget_presentation`, even if some compatibility fields still overlap today.

## Presentation families versus placement zones

This distinction is now load-bearing.

### Placement zones

Zones are host surfaces:

- `rail`
- `header`
- `dock`
- `grid`

They answer: "Where is this pin placed?"

### Presentation families

Presentation families are rendering intent:

- `card`
- `chip`
- `panel`

They answer: "What kind of host surface was this widget authored for?"

Important rules:

- `header` is a zone, not a synonym for chip
- `chip` is a presentation family, not a persisted dashboard zone
- any widget may be placed in any zone
- only a matching family is guaranteed to fit cleanly

Compatibility note:

- `preferred_zone: chip` remains a compatibility alias that resolves to header placement defaults for compact widgets

## Config surfaces

There are three different config-shaped things in the system. They should not be conflated.

### `binding_schema`

This is preset-only.

It describes the guided user inputs needed to instantiate a preset, such as:

- entity selection
- device selection
- display mode choice

### `default_config`

This is the widget's default runtime config.

It seeds per-instance `widget_config` values for a tool widget or preset-backed tool widget.

Namespace rule:

- `result.*` = raw tool result
- `widget_config.*` = runtime widget config
- `binding.*` = preset setup inputs when present
- `pin.*` = pin/runtime metadata when present
- `config.*` = deprecated compatibility alias to `widget_config.*`

### `config_schema`

This is the editable runtime config contract.

It describes which config keys are valid for the placed widget instance. It now ships on:

- tool widgets
- preset responses derived from the preset `binding_schema`
- HTML widget manifests
- native widget catalog entries
- pins

The dashboard editor uses it to render schema-backed fields where possible instead of forcing raw JSON for everything.

## Pin provenance

Pins now persist canonical origin metadata instead of depending only on envelope heuristics.

Each pin may carry:

- `widget_origin`
- `provenance_confidence`
- `widget_contract_snapshot`
- `config_schema_snapshot`
- `widget_presentation_snapshot`

Read-path rule:

- resolve fresh metadata from `widget_origin` when possible
- fall back to snapshots when the live source is missing or ambiguous

Pins created with an explicit caller-supplied `widget_origin` are written as `authoritative`. Inferred rows remain `inferred`, and legacy rows self-heal the same way on read.

## Host rendering policy

The host should render from one resolved policy, not from scattered booleans.

The current resolver combines:

- placement zone
- authored `widget_presentation`
- dashboard chrome
- per-pin runtime config overrides such as title visibility and wrapper surface

The resulting host policy decides things like:

- wrapper surface (`surface` vs `plain`)
- title mode (`hidden`, generic host title, or panel title)
- hover-scrollbar behavior
- whether the tile should fill host height

This matters because the same pin can appear in chat, the channel dashboard editor, the runtime header rail, the OmniPanel rail, and a named dashboard. Host policy is what keeps those placements coherent without mutating the underlying authored definition.

## Auth and trust boundaries

This remains load-bearing.

### Tool widgets

Tool widgets execute through server-side tool execution and widget action handling. They do not run arbitrary browser JS as the viewer.

### HTML widgets

Standalone HTML widgets run through the widget SDK and act as the source bot when bot-scoped. They do not silently inherit the viewing user's privileges.

In catalog contexts without a concrete source bot yet, the surfaced contract may show a more generic auth model because the final runtime authority is not resolved until instantiation.

### Native widgets

Native widgets are host-owned. There is no public React/native authoring lane.

## What is implemented soundly

Two parts of the current system are in good shape and are worth keeping stable:

### Placement is genuinely unified

No matter which definition kind produced it, the end-user experience converges on the same broad placement model:

- rich result
- pin
- dashboard placement
- widget action surface

That part should stay shared.

### The contract surface is finally explicit

The system no longer needs humans to reverse-engineer a widget from source paths, manifest shape, or special cases in the UI.

The addition of `widget_contract` and `config_schema` is the right direction for both DX and debugging.

## Current limitations and real gaps

These are current limitations, not theoretical ones.

### 1. Preset dependency validation is structural, not capability discovery

Preset manifests now fail fast when a `tool_family` preset declares dependencies outside that family.

What it does not do yet:

- verify the user's configured bot actually has that MCP server enabled
- express intentional multi-family presets with a richer compatibility matrix
- explain missing runtime capability in the preset picker before execution

Recommended fix:

- add preset availability checks against the selected bot's enabled tools/MCP servers
- only introduce explicit multi-family presets with a first-class manifest shape and UI explanation

### 2. Tool widget terminology still has historical drag

The code is now converging on `tool_widget`, but older docs and some UI still use:

- template
- tool renderer
- tool result template

Those are close enough to be dangerous.

Recommended fix:

- use "Tool widget" as the canonical public term
- keep legacy terms only as parenthetical implementation notes
- keep `widget_config` as the canonical runtime config name and treat bare `config` as compatibility language only

## How to choose the right lane

Use this order:

1. If one tool owns the truth and the widget should render that tool's output, use a tool widget.
2. If users need a guided binding/setup experience for that tool widget, add a preset.
3. If the widget should be a standalone mini app with its own runtime, use an HTML widget.
4. If it should be a first-party host feature, use a native widget.

## Invariants we should keep stable

- Preset is an instantiation path, not a definition kind.
- A YAML-defined widget that uses `html_template` is still a tool widget.
- Standalone HTML widgets and tool widgets are different contracts even if both may render through HTML.
- Native widgets remain core-only.
- Placement stays unified even though definition/runtime internals are not.
- `widget_contract` and `config_schema` are the public inspection surfaces and should be expanded, not bypassed.

## See also

- [Widget Inventory](../reference/widget-inventory.md)
- [Widget Templates](../widget-templates.md)
- [HTML Widgets](html-widgets.md)
- [Widget Dashboards](widget-dashboards.md)
- [Developer Panel](dev-panel.md)
