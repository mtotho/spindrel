---
name: Configurator — Channel Scope
description: >
  Sub-skill of `configurator` for channel-scope changes — pipeline_mode,
  layout_mode, widget_theme_ref, and channel.config JSONB keys covered by the allowlist.
use_when: >
  Parent `configurator` skill delegated to channel-scope work. User's ask
  is about a channel's behavior / noise level / layout, not about a bot.
triggers: channel config, too noisy, too quiet, turn off automations, channel layout, pipeline_mode, layout_mode, widget theme, dashboard theme
category: core
---

# Configurator — Channel scope

## Investigate

| User symptom | Investigate with |
|---|---|
| "Too noisy / too quiet" / unwanted automation firing | `get_channel_settings(X)` + `list_tasks(channel_id=X, parent_task_id=null, limit=10)` to see what's actually firing. |
| Layout / widget strip complaints | `get_channel_settings(X)` — check `layout_mode` + `pinned_widgets` count. |
| Heartbeat / cron complaints | `get_channel_settings(X)` + `list_tasks(channel_id=X, task_type="scheduled", limit=5)`. |

## Propose — field allowlist

You may emit `propose_config_change(scope="channel", ...)` with:

| Field | Type | Notes |
|---|---|---|
| `pipeline_mode` | `"auto"` / `"on"` / `"off"` | Controls whether the pipeline launchpad renders in this channel. `"auto"` shows only when subscriptions exist. |
| `layout_mode` | `"full"` / `"rail-header-chat"` / `"rail-chat"` / `"dashboard-only"` | Chat-screen zone layout. Full is default. |
| `widget_theme_ref` | `null` / `"custom/<slug>"` | HTML widget SDK theme override for this channel. `null` inherits the global default. `builtin/default` should usually be treated as inherit/reset, not a bespoke override. |
| `config.pinned_widgets` | `list[dict]` | Legacy widget pins. Prefer the dashboard editor for this; only touch via `propose_config_change` when explicitly asked. |
| `config.heartbeat_interval_minutes` | `int` | Minutes between heartbeat fires. |
| `config.heartbeat_context_lookback` | `int` | Messages included in heartbeat context. |

## Refuse

Bot membership, integration bindings, ownership, API keys. Point at Admin →
Channels → {channel} for those.

## Rationale patterns

- "Channel currently shows 3 awaiting-review findings from automations
  subscribed here; user asked to quiet this channel down. Proposing
  `pipeline_mode: off`."
- "No widgets pinned, no heartbeat configured — `layout_mode: full` wastes
  the right column. Proposing `layout_mode: rail-chat`."
- "User wants this room's widgets to look like the light Home Assistant panel. Proposing `widget_theme_ref: custom/home-assistant-light`."
