# Attention Beacons

Attention Beacons are Spindrel's shared attention and work-intake system.
The persisted domain object is an **Attention Item**. A **Beacon** is the
Spatial Canvas rendering of an active item.

This guide is intentionally small for v1. Add future assignment, queue, and
bot-report mechanics here instead of scattering them across spatial,
heartbeat, observability, or chat docs.

## Core Model

`workspace_attention_items` owns attention state:

- source: `bot` or `system`
- target: `channel`, `bot`, `widget`, or `system`
- severity: `info`, `warning`, `error`, or `critical`
- lifecycle: `open`, `acknowledged`, `responded`, `resolved`
- dedupe key and occurrence count
- message, next steps, and structured evidence
- response and resolution metadata

`workspace_spatial_nodes` does not store attention state. It remains the
source of truth for canvas positions only.

## Sources

Bot-authored items are created through policy-gated spatial tools:

- `place_attention_beacon`
- `resolve_attention_beacon`

The channel bot policy field is `allow_attention_beacons`. Defaults are off.
If a bot omits a target, the item attaches to the source channel. Source bots
can update or resolve only their own items.

System-authored items come from persisted structured failures:

- failed `ToolCall`
- error-like `TraceEvent`
- failed `HeartbeatRun`

Raw server logs are not a direct v1 source. They may become supporting
evidence later when linked by correlation id or trace context.

## Visibility

Bot-authored channel items are visible to normal channel viewers.

System-authored items are admin-only. They may include trace or runtime
failure details that are not appropriate for every channel viewer.

## Canvas Behavior

The Spatial Canvas renders active Attention Items as Beacons attached to
existing targets:

- bot-authored items render as warning badges
- system-authored structured failures render as asteroid-style markers

Clicking a Beacon opens the Attention drawer with message, next steps,
source, target, count, evidence, and actions.

## Reply And Resolve

Reply uses the existing channel chat path with attention metadata. A reply
marks the item `responded`; it does not resolve the item.

Resolution is explicit. Humans can resolve items. A source bot can resolve
its own items through `resolve_attention_beacon`.

## Future Assignment

Assignment is future workflow state around an Attention Item, not a
replacement for item lifecycle.

The intended first assignment mode is `investigate_report`: assign the item
to a bot, surface it on the next heartbeat, and let the bot reply with
findings. Execution-oriented assignment should be a later, separately
permissioned mode.
