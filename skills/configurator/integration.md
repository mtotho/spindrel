---
name: Configurator — Integration Scope
description: >
  Sub-skill of `configurator` for integration-level changes — enable /
  disable and the narrow set of per-integration config keys in the allowlist.
use_when: >
  Parent `configurator` skill delegated to integration-scope work. User is
  turning an integration on/off or adjusting one of its documented settings.
triggers: integration config, disable integration, enable integration, integration setting, integration keeps failing
category: core
---

# Configurator — Integration scope

## Investigate

| User symptom | Investigate with |
|---|---|
| "Integration isn't working" | `list_integrations()` for install state + `get_trace(bot_id=..., event_type="tool_call", limit=10)` to see failures. |
| "Disable X" | `list_integrations()` to confirm installed + `get_integration_settings(slug=X)` to see current enable state. |
| "Adjust X config" | `get_integration_settings(slug=X)` — check which key the user means. |

## Propose — field allowlist

You may emit `propose_config_change(scope="integration", target_id="<slug>", ...)` with:

| Field | Type | Notes |
|---|---|---|
| `enabled` | `bool` | Toggle the whole integration on/off. Safe. |
| `config.<key>` | per-integration | Only fields declared in the integration's `setup.py:env_vars` or `integration.yaml` config schema. If you don't see the key in `get_integration_settings`, it's not in the allowlist. |

**Do not** propose changes to:

- `api_keys`, secrets, OAuth tokens — those move through the Secrets UI, not configurator.
- Integration source files, YAML definitions, or installed tools list — these are managed via the integration admin page.
- Scoping / per-channel bindings — use channel settings, not integration settings.

## Refuse examples

> User: "Rotate the Frigate API key."
> You: "That's a secret rotation — do it in Admin → Secrets → Frigate. I
> don't touch keys from here."

> User: "Add a new tool to the Frigate integration."
> You: "That's an integration-code change, not a config change. Edit
> `integrations/frigate/integration.yaml`."

## Rationale patterns

- "Integration has 4 tool_call failures with `timeout` in the last 10
  turns (correlation_ids …). Proposing `config.request_timeout_seconds: 30`
  (currently 10)."
- "User said 'turn off Google Drive'; current `enabled=true`. Proposing
  `enabled: false`."
