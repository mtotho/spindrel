# Widget System

This is the canonical overview of how widgets work in Spindrel.

If you only keep one mental model in your head, keep this one:

- There are **three runtime kinds** of widgets: **tool renderer widgets**, **HTML widgets**, and **native widgets**.
- There are several **authoring and entry surfaces** on top of those runtimes: **presets**, **tool renderers**, **library widgets**, and runtime HTML emission via `emit_html_widget`.
- Placement is unified: to the end user, all of them become **tool results** and **pins** that can live on the same dashboards.

This guide explains those layers, where they overlap, and where the current seams still show.

## The three axes

The product gets confusing if you mix these three questions together:

1. **What runtime draws the widget?**
2. **How was the widget created or configured?**
3. **Where is the widget placed?**

Spindrel is cleanest when you treat those as separate axes.

### 1. Runtime kinds

These are the actual widget substrates.

| Runtime kind | Public term | Internal/API term | Who authors it | User-addable | Primary rendering model |
|---|---|---|---|---|---|
| Tool renderer widget | Tool renderer | `template` | Integration authors, admins, advanced users | Yes | Declarative renderer over a tool result |
| HTML widget | HTML widget | `html` | Bots, users, integrations | Yes | Sandboxed iframe with widget SDK |
| Native widget | Native widget | `native_app` | Core app only | No | First-party React/native host renderer |

### 2. Authoring and entry surfaces

These are the ways a user or bot encounters and configures widgets.

| Surface | What it is | What runtime it usually lands on |
|---|---|---|
| Preset | Guided binding flow for a ready-made widget shape | Usually a tool renderer widget |
| Tool renderer | A definition of how one tool's output should render | Tool renderer widget |
| Library widget | A directly pinnable widget bundle in the catalog | Usually HTML, sometimes native |
| `emit_html_widget` | Runtime one-off HTML written by a bot | HTML widget |

### 3. Placement surfaces

This part is intentionally unified:

- chat rich results
- dashboard pins
- channel dashboard zones
- panel mode

The product tries hard to make placement feel like one system even though the runtime underneath may differ.

## Runtime kinds in detail

### Tool renderer widgets

Tool renderer widgets are the YAML-backed lane. They render the result of a specific tool call.

They are the right choice when:

- a tool already returns the right data shape
- the UI can be expressed with the component/template grammar
- you want server-side actions and `state_poll`
- you want the result to feel host-native rather than iframe-native

Important properties:

- They are **tool-bound**, not standalone bundles.
- The authoritative state is usually the **tool result plus per-pin `widget_config`**.
- Refresh is via **`state_poll`**, if declared.
- Actions dispatch back through the server-side widget/tool action pipeline.
- Presets often sit on top of this lane.

What they are not:

- not a free-form JS runtime
- not a fourth widget kind separate from presets

### HTML widgets

HTML widgets are the iframe lane.

They are the right choice when:

- the UI needs custom layout or bespoke visuals
- the widget wants local JS state
- the widget needs custom charts, canvas, timelines, or SDK helpers
- a bot is building something one-off at runtime

Important properties:

- They render in a sandboxed iframe.
- They use the widget SDK (`window.spindrel.*`).
- If they call the app API, they do so as the **source bot**, not the viewing user.
- State is generally **widget-owned**:
  - in widget JS
  - in workspace files
  - in suite storage / SQLite
  - in widget handlers
- Refresh is generally **widget-owned**:
  - widget JS polling
  - source-file edits
  - action-driven rerenders

HTML widgets come from two main places:

- **library widgets** discovered from core, integration, bot, workspace, or channel scopes
- **runtime emission** via `emit_html_widget`

Those are different authoring paths, but the same runtime lane.

### Native widgets

Native widgets are first-party host-rendered widgets such as Notes and Todo.

They are the right choice when:

- the app wants a deeply integrated core widget
- state should live in the app, not in an iframe bundle
- the widget should feel fully native to the host shell

Important properties:

- Native widgets are **first-party only**.
- They share the same placement and action model as the other lanes.
- Their authoritative state lives in **`widget_instances.state`**.
- Dashboard pin envelopes are cached presentation, not the source of truth.
- Actions dispatch through the native widget registry, not the HTML handler path.

What this means in practice:

- users can place them
- bots can invoke declared actions on them
- users and bots do **not** author new native widgets

## Presets are not a fourth runtime

This is the single most important taxonomy rule.

A **preset** is not a new widget substrate. It is a **guided binding/configuration flow** over the existing widget engine.

Example:

- "Home Assistant Light Card" is a preset
- the resulting pinned thing is usually still a **tool renderer widget**

Presets exist because many widgets need a user to bind a real object first:

- an entity
- a device
- a room
- a mailbox
- a feed

Without presets, that binding step leaks raw tool args and widget config into the user experience.

So the clean way to think about presets is:

- runtime kind: usually tool renderer
- authoring surface: preset
- placement: normal pin

## Tool renderers vs library widgets

These two are easy to blur together because both show up in the widget surfaces.

### Tool renderers

Use a tool renderer when:

- the widget exists to shape the output of **one tool**
- the tool call is the authoritative source of state
- refresh should come from `state_poll`

### Library widgets

Use a library widget when:

- the widget is a **directly pinnable asset**
- it should exist independently of a single tool call
- it behaves more like an applet/panel/bundle than a decorated tool result

Most library widgets today are HTML widgets. Native widgets also appear in the library. Tool renderers are discoverable in the same broad product area, but they are instantiated from a tool call or preset rather than pinned as standalone bundles.

## Tool results, pins, and the shared contract

All widget lanes converge on the same user-visible behaviors:

- a tool can return a rich result
- that result can often be pinned
- pinned widgets can expose actions
- pinned widgets can refresh

That shared surface is carried by a normalized envelope/action model, even when the runtime beneath it differs.

What is intentionally shared:

- one catalog/library surface
- one dashboard placement model
- one pin model
- one widget-actions plumbing surface
- one bot-facing action tool (`invoke_widget_action`)

What is intentionally **not** shared:

- HTML widget runtime internals
- template renderer internals
- native widget persistence internals

The contract is unified at the product boundary, not because every lane uses the same substrate.

## Rich tool results vs pinnable widgets

Some rich tool results are effectively "single-call widgets":

- a tool runs
- its result renders richly
- the result may support `state_poll`
- the result can often be pinned as-is

That is different from a general HTML widget bundle, which can be much more open-ended:

- local UI state
- multiple internal API calls
- custom polling
- bundle-owned storage

And it is also different from presets, which may compile down to a tool renderer widget but still feel like a guided "add widget" flow.

So there are really three different patterns living side-by-side:

| Pattern | Typical shape |
|---|---|
| Rich tool result that can be pinned | One tool call, maybe `state_poll` |
| Preset-backed widget | Guided binding over the renderer engine |
| HTML bundle/widget applet | Open-ended local JS + API calls + widget-owned state |

They share placement. They do not share the same authoring or lifecycle model.

## Auth and trust boundaries

This is load-bearing.

### HTML widgets run as the source bot

If an HTML widget calls the app API through the widget SDK, it does so as the **source bot** attached to the widget or pin.

It does **not** borrow the viewing user's session.

That prevents a bot-authored widget from silently escalating into the viewer's privileges.

### Tool renderer widgets act through server-side tool execution

Template/tool renderer widgets do not execute arbitrary JS in the browser. Their actions and polls route through server-side tool/action handling using the pin's stored bot/channel context.

### Native widgets are host-owned

Native widget actions are handled by the app directly. There is no iframe token and no public "author your own React widget" lane.

## State and refresh models

This is the second place where the runtime seams matter.

### Tool renderer widgets

- Authoritative state: tool output + `widget_config`
- Refresh: `state_poll`
- Best for: cards whose truth comes from re-running a tool

### HTML widgets

- Authoritative state: widget-owned
- Refresh: widget-owned
- Best for: custom mini-apps, custom JS, bundle/file-driven dashboards

### Native widgets

- Authoritative state: `widget_instances.state`
- Refresh: action results + instance reload
- Best for: core first-party widgets

If you try to explain all three with one sentence like "widgets poll tools and then rerender," the system becomes misleading. Only one lane really works that way.

## How to choose what to build

Use this order:

1. **Can this be a tool renderer widget?**
   - Prefer this first when one tool already owns the truth.
2. **Does the user need a guided binding flow?**
   - Add a preset on top of the renderer path.
3. **Does it need free-form custom UI or local JS state?**
   - Use an HTML widget.
4. **Is this a core, deeply integrated first-party widget?**
   - Consider a native widget.

Short version:

| Need | Best fit |
|---|---|
| Render a tool result cleanly | Tool renderer |
| Make a bindable "add widget" flow | Preset over a tool renderer |
| Build a custom interactive panel | HTML widget |
| Ship a core app-native widget | Native widget |

## Developer experience today

The system is strongest where placement and action plumbing are unified:

- one Add Widget experience
- one library
- one dashboard model
- one way for bots to invoke declared widget actions

The system is weaker where authoring models differ:

- presets, tool renderers, and library widgets still require different mental models
- some concepts are clearer in the runtime/API than in the human UI
- state authority differs significantly by lane

That is normal for the current system, but it should be documented honestly rather than hidden behind "all widgets are the same."

## Current limitations and rough edges

These are not theoretical. They are current design edges.

### Presets are intentionally thin

Presets are a guided binding layer, not a generic form-builder/runtime for arbitrary multi-step apps.

### Native widgets are core-only

There is no public React/native widget authoring surface. This is intentional for now.

### Template expression power is still limited

The template grammar still pushes some real branching into Python transforms because it lacks richer expression features such as broader boolean composition and ternary-style shaping.

### Theme parity is uneven

HTML widgets currently have the richest widget-theme story. Native widgets follow the host app theme. Tool renderer/theme parity is narrower than the HTML lane.

### HTML authoring is still split across multiple entry paths

Reusable library bundles and runtime `emit_html_widget` are the same runtime lane, but they are still different authoring paths with different ergonomics.

### Placement is more unified than creation

To the end user, placement feels like one system. To the author, creation still differs materially between:

- presets
- tool renderers
- library widgets
- runtime HTML emission

That split is acceptable, but it should remain explicit.

## Debugging and inspection

Today the best surfaces are:

- **Widget library preview** for live render, contract, source, and manifest
- **Developer panel** for calling tools, previewing renderers, and inspecting recent calls
- **Pin editing/inspection** for the saved pin contract and per-pin config
- **Widget inspector** for HTML runtime event traces

Use those surfaces to answer different questions:

| Question | Best surface |
|---|---|
| What kind of widget is this really? | Library contract view / pin contract view |
| What source code or manifest backs this? | Library source + manifest tabs |
| What tool output shape am I actually rendering? | Developer panel: Recent / Call tools |
| Why is this HTML widget failing at runtime? | Widget inspector |

## See also

- [Widget Templates](../widget-templates.md)
- [HTML Widgets](html-widgets.md)
- [Widget Dashboards](widget-dashboards.md)
- [Developer Panel](dev-panel.md)
