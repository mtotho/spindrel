# Widget Inventory

This is the canonical inventory of shipped widget definitions and preset-backed widget entry points.

For the system model, read [Widget System](../guides/widget-system.md). This document answers a different question: **what widgets do we currently ship, where are they defined, and how aligned are they with the current standard?**

Last audited: 2026-04-23.

## Status Rubric

| Status | Meaning |
|---|---|
| Current | Matches the current widget contract model and has the expected metadata for its lane. |
| Partial | Works, but is missing a current-standard affordance such as `sample_payload`, `config_schema`, manifest metadata, or explicit provenance. |
| Legacy | Kept for compatibility, examples, or debugging; not the preferred production path for new placements. |
| Needs audit | Requires a focused follow-up before we should call it current. |

## Current Standard Checklist

Use this checklist when adding or modernizing a widget.

### All Widget Definitions

- Uses canonical language: tool widget, HTML widget, or native widget.
- Surfaces through the normalized `widget_contract` path.
- Declares callable actions with schemas before exposing them to bots.
- Has enough metadata for the library/dev surfaces to explain what it is.

### Tool Widgets

- Lives under `tool_widgets:` or a local `widgets/<tool>/template.yaml`.
- Uses `template:`, `html_template:`, or a core semantic `view_key` with a renderer-neutral `data` payload. A tool widget using `html_template` is still a tool widget.
- Component templates follow the low-chrome component design language: object labels over generic action labels, metadata marked as metadata, and chip-vs-card chosen explicitly.
- Has `sample_payload` unless there is a strong reason it cannot.
- Uses `state_poll` when pinned state should refresh.
- Provides `config_schema` whenever it exposes editable `default_config` / `widget_config` keys.

### Standalone HTML Widgets

- Lives as a bundle with an `index.html`.
- Has YAML frontmatter or `widget.yaml` with name, description, version, and display metadata.
- Uses `widget.yaml` when it needs handlers, DB, layout hints, bot-callable action schemas, or `config_schema`.
- Uses widget SDK auth as the source bot, not viewer auth.

### Native Widgets

- Lives in `app/services/native_app_widgets.py`.
- Has a native registry spec, action schemas, default state, supported scopes, and catalog metadata.
- Remains first-party only.

## Summary

| Area | Count | Notes |
|---|---:|---|
| Native widgets | 2 | First-party, current-standard. |
| Core/local tool widgets | 6 | Mostly current; all have sample payloads. |
| Core/local standalone HTML widgets | 2 | One active, one QA/example. Legacy HTML Notes was deleted; new Notes placements use native. |
| Integration tool widgets | 17 | Current-standard metadata is now present across the audited shipped set. |
| Preset entry points | 4 | All Home Assistant; official HA MCP lane only, with preset dependency validation. |

## Native Widgets

| Widget | Definition kind | Source | Status | Notes |
|---|---|---|---|---|
| `core/notes_native` | `native_widget` | `app/services/native_app_widgets.py` | Current | First-party native Notes with persistent instance state and bot-callable action schemas. Replaces legacy HTML Notes for new placements. |
| `core/todo_native` | `native_widget` | `app/services/native_app_widgets.py` | Current | First-party native Todo with instance state and explicit add/toggle/rename/delete/reorder/clear actions. |

## Core/Local Tool Widgets

These are YAML-defined tool widgets shipped with local tools.

| Widget / tool | Render mode | Source | Status | Notes |
|---|---|---|---|---|
| `generate_image` | `html_template` | `app/tools/local/widgets/generate_image/template.yaml` | Current | HTML-backed tool widget with sample payload. Static result renderer; no config schema needed today. |
| `get_system_status` | `template` | `app/tools/local/widgets/get_system_status/template.yaml` | Current | Component tool widget with sample payload. Already updated away from the payload `config` collision. |
| `get_task_result` | `template` | `app/tools/local/widgets/get_task_result/template.yaml` | Current | Component tool widget with sample payload. |
| `list_tasks` | `template` | `app/tools/local/widgets/list_tasks/template.yaml` | Current | Component tool widget with sample payload and task actions. |
| `manage_bot_skill` | `template` | `app/tools/local/widgets/manage_bot_skill/template.yaml` | Current | Component tool widget with sample payload. |
| `schedule_task` | `template` | `app/tools/local/widgets/schedule_task/template.yaml` | Current | Component tool widget with sample payload and `state_poll`. |

## Core/Local Standalone HTML Widgets

| Widget | Definition kind | Source | Status | Notes |
|---|---|---|---|---|
| `context_tracker` | `html_widget` | `app/tools/local/widgets/context_tracker/index.html` | Current | Active standalone HTML widget with frontmatter and SDK usage. Could grow `widget.yaml` later if it needs config schema or actions. |
| `examples/sdk-smoke` | `html_widget` | `app/tools/local/widgets/examples/sdk-smoke/index.html` | Legacy | QA/example widget for SDK smoke testing. Useful as a reference, not a product widget. |

## Integration Tool Widgets

These are integration-defined `tool_widgets:` entries. HTML files under `integrations/*/widgets/` listed here are backing files for tool widgets, not standalone HTML widgets.

| Integration | Widget / tool | Render mode | Source | Status | Notes |
|---|---|---|---|---|---|
| `browser_live` | `browser_screenshot` | `html_template` | `integrations/browser_live/integration.yaml` | Current | HTML-backed static screenshot renderer with sample payload. |
| `browser_live` | `browser_status` | `html_template` | `integrations/browser_live/integration.yaml` | Current | HTML-backed status renderer with `state_poll` and sample payload. |
| `excalidraw` | `create_excalidraw` | `html_template` | `integrations/excalidraw/integration.yaml` | Current | HTML-backed result renderer with sample payload. |
| `excalidraw` | `mermaid_to_excalidraw` | `html_template` | `integrations/excalidraw/integration.yaml` | Current | HTML-backed result renderer with sample payload. |
| `frigate` | `frigate_snapshot` | `html_template` | `integrations/frigate/integration.yaml` | Current | HTML-backed snapshot renderer with sample payload, `state_poll`, and `config_schema` for bbox display. |
| `frigate` | `frigate_get_events` | `html_template` | `integrations/frigate/integration.yaml` | Current | HTML-backed timeline renderer with sample payload and `state_poll`. |
| `frigate` | `frigate_list_cameras` | `html_template` | `integrations/frigate/integration.yaml` | Current | HTML-backed camera-list renderer with sample payload and `state_poll`. |
| `github` | `github_get_pr` | `template` | `integrations/github/integration.yaml` | Current | Component renderer with sample payload. |
| `github` | `github_get_issue` | `template` | `integrations/github/integration.yaml` | Current | Component renderer with sample payload. |
| `homeassistant` | `HassTurnOn` | `template` | `integrations/homeassistant/integration.yaml` | Current | Official HA MCP action-result widget with sample payload and `state_poll`. |
| `homeassistant` | `HassTurnOff` | `template` | `integrations/homeassistant/integration.yaml` | Current | Official HA MCP action-result widget with sample payload and `state_poll`. |
| `homeassistant` | `HassLightSet` | `template` | `integrations/homeassistant/integration.yaml` | Current | Official HA MCP action-result widget with sample payload and `state_poll`. |
| `homeassistant` | `ha_get_state` | `template` | `integrations/homeassistant/integration.yaml` | Current | Community ha-mcp single-entity widget with sample payload, `config_schema`, and `state_poll`. No longer used by the official HA presets. |
| `homeassistant` | `ha_search_entities` | `template` | `integrations/homeassistant/integration.yaml` | Current | Community ha-mcp search-result component widget with sample payload. |
| `homeassistant` | `GetLiveContext` | `template` | `integrations/homeassistant/integration.yaml` | Current | Official HA MCP full-home summary plus single-entity preset backing widget, with sample payload, `config_schema`, and `state_poll`. |
| `openweather` | `get_weather` | `html_template` | `integrations/openweather/integration.yaml` | Current | HTML-backed weather renderer with sample payload, `state_poll`, and `config_schema`. |
| `web_search` | `web_search` | `core.search_results` + `template` fallback | `integrations/web_search/integration.yaml` | Current | Semantic core search-results renderer with a component fallback and sample payload. No Web Search-specific React registration or iframe widget. |

## Preset Entry Points

Presets are not widget definitions. They are guided instantiation paths. Current Home Assistant presets are intentionally locked to the official HA MCP family and render through `GetLiveContext`; they do not depend on community `ha_get_state`.

| Preset | Backing widget | Source | Status | Notes |
|---|---|---|---|---|
| `homeassistant-entity-toggle-chip` | `GetLiveContext` | `integrations/homeassistant/integration.yaml` | Current | Official HA MCP guided chip flow. Declares `tool_family: official` and validates dependencies at registration. |
| `homeassistant-entity-chip` | `GetLiveContext` | `integrations/homeassistant/integration.yaml` | Current | Official HA MCP guided entity chip. Preset `config_schema` comes from its binding schema. |
| `homeassistant-light-card` | `GetLiveContext` | `integrations/homeassistant/integration.yaml` | Current | Official HA MCP guided light card with friendly-name action targets for official action tools. |
| `homeassistant-sensor-card` | `GetLiveContext` | `integrations/homeassistant/integration.yaml` | Current | Official HA MCP guided sensor card. |

## Explicit Non-Inventory Items

The following are not counted as standalone shipped widgets:

- Integration files under `integrations/*/widgets/*.html` when referenced by `html_template`; those are backing files for tool widgets.
- Runtime widgets emitted by bots with `emit_html_widget(html=...)`; those are per-instance artifacts, not shipped definitions.
- User/bot/workspace widgets under live `widget://bot` or `widget://workspace` storage; those are runtime library contents, not repo-shipped definitions.
- `__pycache__` leftovers under old widget folders.

## Modernization Queue

Highest-value follow-ups:

1. Decide whether `GetLiveContext` should remain directly pinnable as a full-home summary or become primarily preset/support infrastructure.
2. Persist canonical bundle identity / manifest metadata for HTML pins so schema recovery is not context-sensitive.
3. Backfill explicit instantiation provenance for older non-preset pin paths.
4. Keep pruning stale "template/tool renderer/tool result template" wording in docs and UI in favor of "tool widget."
