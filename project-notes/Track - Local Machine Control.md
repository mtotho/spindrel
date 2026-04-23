---
tags: [agent-server, track, local-control, integrations]
status: active
created: 2026-04-23
updated: 2026-04-23 (phase 5A rich-result UX + docs/skill shipped)
---
# Track — Local Machine Control

## Goal

Let a live signed-in admin grant one chat/session temporary control over one explicit machine target, so the agent can inspect or execute on the user's own computer without pretending the server itself is local.

## Decisions Locked

- Machine access is modeled as a generic **machine target**, not a one-off localhost hack.
- v1 ships `driver="companion"` only. SSH is deferred as a second driver on the same abstraction.
- One session can lease one target at a time. One target can be leased by only one session at a time.
- Lease-gated tools are denied unless there is a live JWT user, active presence, and a valid session lease for the same user.
- Lease state lives in `Session.metadata_["machine_target_lease"]`; enrolled companion targets live in the `local_companion` integration settings JSON. No new tables.
- Default route is never "most recent connection". The user must explicitly lease a target.

## Status

| Phase | Summary | Status |
|---|---|---|
| 1 | Backend target/lease model + companion bridge + local tools | ✅ shipped 2026-04-23 |
| 2 | Session APIs + channel-header machine chip + enrollment flow | ✅ shipped 2026-04-23 |
| 3 | Guardrails on non-interactive surfaces (`run_script`, admin tool execute, widget-style direct dispatch) | ✅ partial 2026-04-23 |
| 4 | Canonical docs + architecture linking | ✅ shipped 2026-04-23 |
| 5 | Rich result UX, inline grant/revoke flow, operator docs, and generic machine-control skill | ✅ partial 2026-04-23 |

## What Shipped

### Phase 1 — Backend machine targets + companion bridge

- New `app/services/local_machine_control.py` owns:
  - target enrollment/lookup/status
  - session lease grant/revoke payloads
  - execution-policy validation (`interactive_user`, `live_target_lease`)
- New `integrations/local_companion/`:
  - `integration.yaml`
  - `router.py` admin/status + enroll + websocket RPC bridge
  - `bridge.py` target-id keyed live connection map
  - `client.py` paired local companion CLI/daemon entrypoint
  - `tools/local_companion.py` (`local_status`, `local_inspect_command`, `local_exec_command`)
- Companion metadata is stable per install (`target_id`) and ephemeral per socket (`connection_id`).
- Companion enrollment auto-enables the integration and loads/indexes tools on first use.

### Phase 2 — Session lease APIs + chat UI

- New session endpoints:
  - `GET /api/v1/sessions/{id}/machine-target`
  - `POST /api/v1/sessions/{id}/machine-target/lease`
  - `DELETE /api/v1/sessions/{id}/machine-target/lease`
- Admin/JWT only in v1; each endpoint refreshes user presence before lease work.
- Channel header now exposes a desktop `MachineTargetChip` with:
  - current lease state
  - connected target list
  - enroll/remove target actions
  - session lease grant/revoke actions
- Enroll response returns a companion launch command with the current server base URL.

### Phase 3 — Execution guards

- Tool registry now carries `execution_policy`.
- `dispatch_tool_call()` enforces the machine-control gate before normal policy/approval handling.
- Lease-gated tools bypass tier-default approval prompts when the lease is already the explicit consent surface; explicit policy rules still win.
- Direct bot/script surfaces now hard-deny machine tools before execution:
  - `POST /api/v1/internal/tools/exec`
  - `execute_tool_with_context()` callers such as admin tool execute / dashboard execution helpers
- Revoking a target clears any session leases pointing at it so the UI cannot hold stale control state.

### Phase 4 — Canonical docs

- Added `agent-server/docs/guides/local-machine-control.md` as the canonical detailed doc for:
  - machine targets
  - leases
  - companion transport
  - execution-policy gating
  - current limits and follow-up work
- Linked the docs guide from:
  - `docs/reference/architecture.md`
  - vault `Architecture Decisions.md`
  - MkDocs navigation

### Phase 5A — Native-feeling result UX + packaging

- Local machine-control tools now render as semantic rich results instead of generic JSON blobs:
  - `local_status` -> `core.machine_target_status`
  - `local_inspect_command` / `local_exec_command` -> `core.command_result`
- Execution-policy denials in chat now return a `core.machine_access_required` envelope with:
  - denial reason
  - connected target list
  - inline grant/revoke actions backed by the existing session lease endpoints
  - deep link to the local companion integration when no targets are connected
- Added `tool_widgets` metadata for the local companion tools so widget contracts/catalog surfaces understand the result views.
- Added `integrations/local_companion/README.md` for operator setup/use and `skills/machine_control.md` for agent-facing behavior on the machine-target abstraction.
- Updated docs parity:
  - `docs/setup.md`
  - `docs/guides/api.md`
  - `docs/reference/widget-inventory.md`
  - canonical local-machine-control guide to reflect transcript-native grant/status/result UX

## Deferred

- `driver="ssh"` for headless LAN/server targets.
- Applying the same lease abstraction to `browser_live` and any future desktop/file automation drivers.
- Companion-side richer capabilities beyond shell (`files`, `browser`, `input`, screenshots).
- Better integrations/settings management surfaces for target enrollment and long-lived machine administration.

## Verification

- `python -m py_compile` on the new/edited backend files
- `pytest tests/unit/test_registry.py tests/integration/test_internal_tools_exec.py tests/integration/test_machine_target_sessions.py -q`
- `pytest tests/unit/test_local_machine_control_phase5a.py -q`
- `cd agent-server/ui && npx tsc --noEmit --pretty false`
