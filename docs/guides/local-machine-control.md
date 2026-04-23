# Local Machine Control

This is the canonical document for the current "run on my computer" architecture in Spindrel.

If the machine-target model, lease rules, companion transport, execution-policy guards, or planned SSH follow-up change, update this file first and then update shorter vault summaries that point at it.

---

## What this is for

Spindrel is a web app running on a server. That server is not your laptop or desktop.

Sometimes the useful thing is not "run a command on the server", but:

- inspect the files on the machine the user is actively sitting at
- run a command in the user's real local checkout
- check local git state, processes, config, or working tree
- eventually, operate on a different machine on the user's network

That requires a different trust model from normal server-side tools.

The local-machine-control design exists to support those use cases without pretending that "server exec" and "my own computer" are the same boundary.

---

## Current design in one sentence

Spindrel models local access as an explicit **machine target** leased to a specific session by a live signed-in admin user, with the actual work executed by a paired **local companion** process running on that machine.

---

## Mental model

There are four core concepts:

| Term | Meaning |
|---|---|
| `machine target` | A controllable machine endpoint, identified explicitly by `target_id` |
| `driver` | The transport/implementation behind that target; v1 ships `companion`, future work adds `ssh` |
| `lease` | Session-scoped permission allowing one session to control one target temporarily |
| `execution policy` | A runtime gate on top of normal tool policy, used to require a live user and/or lease |

Important distinction:

- a **target** is the machine
- a **connection** is the current live socket from that machine
- a **lease** is the user's explicit permission for one session to use that target

Spindrel never routes by "whichever companion connected most recently". The target must be explicit.

---

## Why the architecture looks like this

### Why not reuse server-side `exec_command`

Server-side command execution already exists for server-owned workspaces. That is a different capability.

If Spindrel used the same mental model for local-machine access, it would blur two very different trust boundaries:

- "the server can run this"
- "the user's current computer can run this"

The whole point of this feature is preserving that distinction.

### Why not start with SSH

SSH is a good fit for headless boxes and LAN/server management. It is not the best first fit for:

- the user's actively used workstation
- developer machines behind NAT
- quick pairing with a self-hosted web app
- future desktop-oriented capabilities beyond shell

So v1 ships a paired companion driver first and keeps SSH as a future second driver on the same abstraction.

### Why session leases instead of a global "local mode"

A global mode is too ambient. The user needs to know:

- which session currently has access
- which machine it is talking to
- whether that access is still active
- when it expires

A session-scoped lease makes that explicit and inspectable.

---

## Current architecture

```text
chat session / plan session
    │
    │ uses lease-gated local tool
    ▼
execution-policy gate
    │
    ├── requires live JWT user
    ├── requires active presence
    ├── requires valid session lease
    └── requires connected leased target
    ▼
local_companion bridge
    │
    │ request(target_id, op, args)
    ▼
paired local companion process
    │
    ├── inspect-command validation
    ├── allowed-root enforcement
    ├── blocked-pattern checks
    └── timeout/output caps
    ▼
local shell on the target machine
```

---

## Current components

### 1. Tool registry execution policies

Tool registration now carries `execution_policy` in addition to the existing safety tier.

Current values:

| Policy | Meaning |
|---|---|
| `normal` | No extra runtime gate beyond normal tool policy |
| `interactive_user` | Requires a live signed-in user with active presence |
| `live_target_lease` | Requires the above plus a valid lease for the current session |

This is used for the current local tools:

| Tool | Tier | Execution policy |
|---|---|---|
| `local_status` | `readonly` | `interactive_user` |
| `local_inspect_command` | `readonly` | `live_target_lease` |
| `local_exec_command` | `exec_capable` | `live_target_lease` |

These gates run before normal tool execution and before default approval behavior.

### 2. `current_user_id` in agent context

The runtime now carries `current_user_id` alongside the usual bot/session/channel context.

That matters because machine-control tools are intentionally tied to:

- an actual signed-in user
- not just a bot key
- not just a session id
- not just a generic tool call

Without `current_user_id`, the runtime cannot prove that a live user is the source of the action.

### 3. Machine-target state

Current state is intentionally lightweight.

#### Enrolled targets

Enrolled companion targets live in the `local_companion` integration settings JSON:

- integration id: `local_companion`
- key: `LOCAL_COMPANION_TARGETS_JSON`

Each target stores metadata such as:

- `target_id`
- `driver`
- `label`
- `hostname`
- `platform`
- `capabilities`
- `token`
- `enrolled_at`
- `last_seen_at`

This avoids adding new tables for a still-evolving feature.

#### Session lease

The active lease lives in:

- `Session.metadata_["machine_target_lease"]`

It stores:

- `lease_id`
- `target_id`
- `user_id`
- `granted_at`
- `expires_at`
- `capabilities`
- `connection_id`

Key invariant:

- one session can lease one target
- one target can be leased by one session

### 4. Local companion integration

`integrations/local_companion/` is the v1 transport.

It provides:

- `router.py`
  - `GET /integrations/local_companion/admin/status`
  - `POST /integrations/local_companion/admin/enroll`
  - `DELETE /integrations/local_companion/admin/targets/{target_id}`
  - `WS /integrations/local_companion/ws?...`
- `bridge.py`
  - target-id keyed live connection registry
  - request/reply RPC handling
- `client.py`
  - the paired local companion process
- `tools/local_companion.py`
  - the local control tools exposed to bots/sessions

### 5. Companion client

The companion is a small Python process running on the target machine.

It connects outbound to the server over WebSocket and identifies itself with:

- `target_id`
- token
- label / hostname / platform
- capability list

The current client supports two operations:

- `inspect_command`
- `exec_command`

It also owns defense-in-depth configuration such as:

- allowed roots
- inspect command prefixes
- blocked command patterns
- timeout
- max output size

That means the server lease is not the only guardrail. The target machine can still locally restrict what the companion will do.

---

## Request flow in detail

### Enroll

1. Admin calls `POST /integrations/local_companion/admin/enroll`.
2. Server creates a new target record with `target_id` + token.
3. Server auto-enables the integration and loads/indexes its tools if needed.
4. Response includes a launch command for the companion.

### Connect

1. Companion connects to `/integrations/local_companion/ws`.
2. Server validates `target_id` + token.
3. Companion sends a `hello` payload with metadata/capabilities.
4. Server updates stored target metadata and registers a live bridge connection.

### Lease

1. Live admin user opens a chat session.
2. UI calls `POST /api/v1/sessions/{id}/machine-target/lease`.
3. Server verifies:
   - admin JWT user
   - active presence
   - target exists
   - target is connected
   - target is not leased by another session
4. Server writes the lease into session metadata.

### Execute

1. Session calls `local_inspect_command` or `local_exec_command`.
2. Execution policy gate verifies:
   - live user exists
   - user is active
   - user is admin
   - session exists
   - lease exists and is unexpired
   - lease belongs to that user
   - target is still connected
3. Server sends RPC to the leased `target_id`.
4. Companion validates and runs the operation locally.
5. Result returns through the bridge into the tool result.

### Revoke / expire

Leases stop working when:

- the user revokes them
- the TTL expires
- the target is removed
- the target disconnects

Revoking a target also clears any session lease that still points at it.

---

## Current safety model

This feature is intentionally fail-closed.

### Allowed by default

The happy path is:

- live JWT user
- admin user
- active web presence
- active session
- explicit target lease
- connected target

### Denied by default

Machine-control tools are denied when any of those are missing.

They are also denied for autonomous origins such as:

- `heartbeat`
- `task`
- `subagent`
- hygiene-style/background runs

### Why presence matters

Presence is the current proxy for "an explicit live user is here right now".

Without it, a remembered session or leaked context variable could look interactive when it is not.

### Why bot/script surfaces are blocked

Bot-authored scripts and other direct execution surfaces are not treated as live user intent.

So these paths hard-deny machine tools:

- `POST /api/v1/internal/tools/exec`
- `execute_tool_with_context()` callers such as admin tool execute / dashboard tool helpers

This is deliberate. If the product wants a future exception, that exception should be explicit and separately designed.

---

## UI model

Current UI is a desktop `MachineTargetChip` in the channel header.

It shows:

- current lease state
- connected enrolled targets
- lease/revoke actions
- enroll/remove actions
- copyable companion launch command

Important UX choice:

- machine control is session chrome, not a hidden background state

That keeps the control surface close to the conversation that is using it.

---

## What this architecture is not

It is not:

- a replacement for server-side command execution
- a silent global localhost tunnel
- a generic automation trigger for background jobs
- an SSH manager
- multi-worker-safe yet

It is a v1 explicit-control path for one live session controlling one paired machine.

---

## Current limitations

### Transport limitations

- bridge state is in-memory
- current implementation assumes a single server process for the live bridge
- multi-worker deployments would need an external connection broker

### Capability limitations

- shell only in v1
- no first-class file sync / browser / desktop input yet
- no SSH driver yet

### UX limitations

- machine control is exposed in the header chip, but denied tool results do not yet render a dedicated inline "Grant machine access" card
- desktop-first UI; no mobile-first lease UX yet

---

## Why the target abstraction matters

The important design choice is not "companion vs SSH". It is the layer above that.

By making **machine target** the core abstraction now:

- local companion is the first driver
- SSH can be the second driver later
- browser/desktop/file capabilities can reuse the same lease contract
- the user does not need a different consent model for every machine-adjacent feature

That is the part meant to last.

---

## Planned next steps

These are the natural next slices from the current architecture.

### 1. Add `driver="ssh"`

Use the same:

- target registry
- lease semantics
- session UI
- execution policies

But back the target with SSH for headless LAN/server machines.

### 2. Add an inline transcript grant flow

When a machine tool returns `local_control_required`, the transcript should offer a direct "Grant machine access" action instead of just showing a generic tool error.

### 3. Reuse the lease model for other live-control surfaces

`browser_live` currently has its own pairing/selection model. It should eventually adopt the same live-user lease semantics rather than remaining a parallel exception.

### 4. Expand companion capabilities carefully

Possible additions:

- file operations
- browser launch/control on the paired machine
- screenshots
- desktop input automation

But only on top of the same target + lease model.

### 5. Decide whether any non-interactive pathway ever gets an exception

Current answer is no. That should remain the default unless there is a very explicit, reviewable reason to widen it.

---

## See also

- [Browser Live](browser-live.md)
- [Command Execution](command-execution.md)
- [Programmatic Tool Calling](programmatic-tool-calling.md)
- [Architecture](../reference/architecture.md)
