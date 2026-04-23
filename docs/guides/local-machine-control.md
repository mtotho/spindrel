# Local Machine Control

This is the canonical document for Spindrel's "operate on a real machine" architecture.

If the provider contract, lease rules, tool names, admin surfaces, or local companion role change, update this file first and then update the shorter summaries that point at it.

## What this is for

Spindrel runs on a server. That server is not automatically the same machine as the user's workstation, laptop, or other boxes on their network.

Machine control exists for cases where the useful action is:

- inspect the user's actual local checkout
- run a command in the user's real shell environment
- check local git/process/config state
- later, operate on other explicit machines such as LAN boxes over a different driver

The feature exists to preserve that trust boundary rather than blur it with ordinary server-side execution.

## Current design in one sentence

Machine control is a core subsystem with pluggable providers. A live signed-in admin user grants one session a temporary lease for one explicit machine target, and the selected provider executes the work on that target.

## Core mental model

| Term | Meaning |
|---|---|
| `machine target` | A controllable machine endpoint identified by `(provider_id, target_id)` |
| `provider` | The implementation/transport behind the target |
| `driver` | The provider's transport family such as `companion` now, `ssh` later |
| `connection` | The provider's current live transport handle for a connected target |
| `lease` | A session-scoped grant allowing one session to control one target temporarily |
| `execution_policy` | A runtime guard layered on top of normal tool policy |

Important distinctions:

- a target is the machine
- a connection is the provider's current live link to that machine
- a lease is the user's explicit permission for one session to use that target

Spindrel never routes by recency. The target is always explicit.

## Why this is core-owned

Machine control is not just "an integration with some tools."

The app needs native, provider-agnostic surfaces for:

- session lease state
- transcript grant/revoke flows
- rich tool results
- admin machine management
- future provider expansion

If those lived under `local_companion`, every future provider would have to tunnel through someone else's product surface. That would violate the app/integration boundary in the wrong direction.

So the split is:

- core owns the abstraction, tools, leases, admin page, session APIs, and result renderers
- integrations implement a typed machine-control provider contract

## Current architecture

```text
chat or plan session
    │
    │ uses machine_* tool
    ▼
execution-policy gate
    │
    ├── requires live JWT user
    ├── requires active presence
    ├── requires valid session lease
    └── requires connected leased target
    ▼
core machine-control service
    │
    │ dispatch(provider_id, target_id, op, args)
    ▼
provider implementation
    │
    ├── local_companion today
    └── ssh or other providers later
    ▼
target machine
```

## Current shipped pieces

### 1. Core service and provider registry

`app/services/machine_control.py` is the core service.

It owns:

- provider discovery
- provider-aware target payloads
- provider-aware lease grant/revoke
- execution-policy validation
- admin machines aggregation
- helper payloads for session and transcript surfaces

Providers are discovered from integrations that declare machine control through:

- `provides: ["machine_control"]`
- an optional `machine_control:` block in `integration.yaml`
- a runtime module at `integrations/<id>/machine_control.py`

### 2. Provider contract

Each provider implements a machine-control contract that exposes:

- identity metadata: `provider_id`, `label`, `driver`
- target enumeration and lookup
- connection lookup
- optional enrollment/removal
- command execution methods

This keeps core UI and APIs provider-agnostic while still letting providers add metadata.

### 3. Session lease state

The active session lease lives in:

- `Session.metadata_["machine_target_lease"]`

Current stored fields:

- `lease_id`
- `provider_id`
- `target_id`
- `user_id`
- `granted_at`
- `expires_at`
- `capabilities`
- `connection_id`

Load-bearing invariants:

- one session may lease one target
- one target may be leased by one session
- leases are always explicit and session-scoped

### 4. Execution policies

Machine tools use runtime execution policies in addition to normal tool policy.

Current policy values:

| Policy | Meaning |
|---|---|
| `normal` | no extra runtime gate |
| `interactive_user` | requires a live signed-in user with active presence |
| `live_target_lease` | requires the above plus a valid session lease for a connected target |

Current core machine tools:

| Tool | Tier | Execution policy |
|---|---|---|
| `machine_status` | `readonly` | `interactive_user` |
| `machine_inspect_command` | `readonly` | `live_target_lease` |
| `machine_exec_command` | `exec_capable` | `live_target_lease` |

These are core tools in `app/tools/local/machine_control.py`. They are not owned by `local_companion`.

### 5. Core APIs and UI surfaces

Current core APIs:

- Session lease/state:
  - `GET /api/v1/sessions/{id}/machine-target`
  - `POST /api/v1/sessions/{id}/machine-target/lease`
  - `DELETE /api/v1/sessions/{id}/machine-target/lease`
- Admin machine center:
  - `GET /api/v1/admin/machines`
  - `POST /api/v1/admin/machines/providers/{provider_id}/enroll`
  - `DELETE /api/v1/admin/machines/providers/{provider_id}/targets/{target_id}`

Current core UI:

- `Admin > Machines` for provider/target management
- transcript-native `core.machine_access_required` grant UI
- transcript/native result views:
  - `core.machine_target_status`
  - `core.command_result`
  - `core.machine_access_required`
- a lightweight session-scoped `MachineTargetChip` in chat header chrome

### 6. `local_companion` as the first provider

`integrations/local_companion/` is the first shipped provider.

It owns:

- `machine_control.py` provider implementation
- `bridge.py` live websocket bridge
- `router.py` websocket endpoint at `/integrations/local_companion/ws`
- `client.py` companion process run on the target machine

It no longer owns:

- the machine tools
- the machine admin center
- the session lease APIs

The current provider uses `driver="companion"`.

## Current request flow

### Enroll a target

1. Admin calls `POST /api/v1/admin/machines/providers/local_companion/enroll`.
2. Core resolves the provider and asks it to enroll a target.
3. The provider creates target state and returns launch information.
4. The response includes the example companion launch command.

### Connect the companion

1. The user runs the companion on the target machine.
2. The companion connects outbound to `/integrations/local_companion/ws`.
3. The provider updates connection metadata for that `target_id`.
4. Core machine status now reports the target as connected.

### Grant a session lease

1. A live signed-in admin chooses a connected target for a session.
2. The session API stores a lease in `Session.metadata_`.
3. Conflict checks ensure no other session already owns that target.

### Execute a machine tool

1. A chat or plan session calls `machine_inspect_command` or `machine_exec_command`.
2. The execution-policy gate verifies:
   - live signed-in user
   - active presence
   - current session id
   - valid unexpired lease
   - current leased target is connected
3. Core dispatches the operation through the selected provider.
4. The provider talks to its transport and returns the result.
5. The tool emits a structured rich result envelope.

## How to use it now

### Operator flow

1. Go to `Admin > Machines`, or use the quick-setup helper on `Admin > Integrations > Local Companion`.
2. Enroll a target under the `Local Companion` provider.
3. Copy the returned launch command.
4. Run that command on the machine you want to control.
5. Confirm the machine appears as connected in `Admin > Machines`.

### Session flow

1. Open the session you want to use.
2. Call `machine_status` or let the transcript surface the inline access-required card.
3. Grant a lease for the target you want to use.
4. Use `machine_inspect_command` for discovery first.
5. Use `machine_exec_command` when you really need execution on that machine.
6. Revoke the lease or let it expire.

## Safety model

Machine control is intentionally fail-closed.

### Required by default

- a live signed-in admin user
- active user presence
- a valid session lease
- a connected leased target

### Denied by default

These origins do not get to use machine-control tools just because they can call tools:

- tasks
- heartbeats
- hygiene/background runs
- subagents
- bot-key `/api/v1/internal/tools/exec`
- other non-interactive surfaces without a live user context

### Provider-side guardrails still matter

Core lease checks are not the only defense.

For `local_companion`, the target-side process still enforces local limits such as:

- allowed roots
- inspect-command restrictions
- blocked patterns
- timeouts
- output caps

That matters because the target machine remains the final trust boundary.

## Current limits

- `local_companion` is the only shipped provider.
- The bridge is in-memory; multi-worker deployments need shared coordination before this becomes horizontally safe.
- The current provider is shell-first.
- `browser_live` has not yet been moved onto this same lease model.
- SSH is not shipped yet.

## Planned next steps

- Add an SSH provider on the same machine-control contract.
- Unify other machine-adjacent control surfaces such as `browser_live` onto the same live-user lease model where appropriate.
- Expand provider capabilities beyond shell only after the provider/lease contract stays stable.

## Source map

Use these as the main code anchors for the current architecture:

- `app/services/machine_control.py`
- `app/tools/local/machine_control.py`
- `app/routers/api_v1_admin/machines.py`
- `app/routers/sessions.py`
- `integrations/local_companion/machine_control.py`
- `integrations/local_companion/router.py`
- `integrations/local_companion/bridge.py`
- `ui/app/(app)/admin/machines/index.tsx`
- `ui/app/(app)/channels/[channelId]/MachineTargetChip.tsx`
- `ui/src/components/chat/renderers/machineControl/`
