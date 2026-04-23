---
tags: [agent-server, reference, widgets]
status: reference
updated: 2026-04-22
---
# Widget Authoring

This vault note is no longer the canonical system overview.

Use the repo docs for the real reference:

- `agent-server/docs/guides/widget-system.md` — canonical system model
- `agent-server/docs/widget-templates.md` — tool-widget grammar
- `agent-server/docs/guides/html-widgets.md` — HTML widget lane
- `agent-server/docs/guides/widget-dashboards.md` — placement and pins
- `agent-server/docs/guides/dev-panel.md` — authoring/inspection workbench

Why this changed:

- the older vault note had drifted toward a stale `*.widgets.yaml`-centric story
- the current system now needs a clean separation between definition kinds, instantiation paths, and placement
- repo docs are the public canonical home for widget behavior; the vault should stop competing with them

Internal-only reminders:

- **Presets are not a fourth widget kind.** They are guided binding flows over the existing widget engine, usually the tool-widget lane.
- **A YAML tool widget using `html_template` is still a tool widget.** It is not the same thing as a standalone HTML widget.
- **Native widgets are first-party only.** Public/UI term is "Native widget"; internal/API term stays `native_app`.
- **Expression grammar is still a real DX constraint.** Branchy integration widgets still spill logic into transforms until P1-2 lands.
- **Placement is cleaner than creation.** End users get one placement model; authors still have distinct flows for presets, tool widgets, library HTML widgets, and runtime HTML emission.

Driving track remains [[Track - Widgets]].
