# Attention Beacons

Attention Beacons are Spindrel's shared attention and work-intake system.
The persisted domain object is an **Attention Item**. A **Beacon** is the
Spatial Canvas rendering of an active item.

This guide is the canonical home for Attention Item, Beacon, hub, assignment,
and bot-report mechanics. Keep future queue and command-center behavior here
instead of scattering it across spatial, heartbeat, observability, or chat docs.

## Core Model

`workspace_attention_items` owns attention state:

- source: `bot`, `system`, or `user`
- target: `channel`, `bot`, `widget`, or `system`
- severity: `info`, `warning`, `error`, or `critical`
- lifecycle: `open`, `acknowledged`, `responded`, `resolved`
- dedupe key and occurrence count
- message, next steps, and structured evidence
- response and resolution metadata
- optional assignment state: assigned bot, mode, status, instructions, task id,
  and report fields

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

User-authored items are first-class Attention Items. They are created from the
Attention Hub, use `source_type="user"`, and can be immediately assigned to a
bot or left as unassigned intake.

## Visibility

Bot-authored and user-authored channel items are visible to normal channel
viewers.

System-authored items are admin-only. They may include trace or runtime
failure details that are not appropriate for every channel viewer.

## Canvas And Hub Behavior

The Spatial Canvas renders active Attention Items as Beacons attached to
existing targets:

- bot-authored items render as warning badges
- system-authored structured failures render as asteroid-style markers
- user-authored items render with the same target-bound badge stack

Badges are rendered inside their target node or cluster shell with inverse-scale
styling. That keeps them screen-sized while moving and zooming exactly with the
bound channel, bot, or widget.

The **Attention Hub** is the global triage surface. It is reachable from:

- the start-zone spatial landmark above the seed center
- the canvas edge beacon
- the channel header attention count
- the command palette

The hub lists lanes for items needing reply, assigned work, system errors, and
recent/reported items. Clicking a Beacon opens the same hub drawer with message,
next steps, source, target, count, assignment state, report findings, evidence,
and actions.

## Reply And Resolve

Reply uses the existing channel chat path with attention metadata. A reply
marks the item `responded`; it does not resolve the item.

Acknowledgement consumes one counted occurrence of an item. If an item has
`occurrence_count > 1`, acknowledge decrements the count and leaves the item
open. If the count is `1`, acknowledge marks the item `acknowledged` and it
drops out of active lists. This is not suppression: a fresh occurrence with
the same dedupe key reopens the item.

Resolution is explicit. Humans can resolve items. A source bot can resolve
its own items through `resolve_attention_beacon`.

## Assignment

Assignment is workflow state around an Attention Item, not a replacement for
item lifecycle.

V1 has two modes:

- `next_heartbeat` — stores the assignment and injects a compact assignment
  block into the assigned bot's next heartbeat for that channel.
- `run_now` — creates a pending `Task` with `task_type="attention_assignment"`
  and a narrow tool surface containing `report_attention_assignment`.

Both modes are investigate/report only. The assignment prompt tells the bot not
to execute fixes as assignment semantics. Execution-oriented command handling
needs a later, separately permissioned mode.

Assigned bots report with `report_attention_assignment(item_id, findings)`.
The report is stored on the item, the assignment status becomes `reported`, and
the item lifecycle becomes `responded` unless it was already resolved. Immediate
task completion also reconciles the item through the same report path.
