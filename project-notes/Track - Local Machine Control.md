---
tags: [agent-server, track, local-control, integrations]
status: active
created: 2026-04-23
updated: 2026-04-23 (phase 6 core provider architecture shipped)
---
# Track — Local Machine Control

## Goal

Let a live signed-in admin grant one chat/session temporary control over one explicit machine target so the agent can inspect or execute on the user's real machine without pretending the server itself is local.

## Decisions Locked

- Machine control is a core subsystem, not a `local_companion` feature with bespoke core UI.
- Targets are addressed as `(provider_id, target_id)`.
- v1 ships one provider: `local_companion` with `driver="companion"`.
- SSH is deferred as a second provider on the same contract.
- One session can lease one target at a time. One target can be leased by only one session at a time.
- Lease-gated tools are denied unless there is a live JWT user, active presence, and a valid session lease for the same user.
- Lease state lives in `Session.metadata_["machine_target_lease"]`.
- Core owns the machine tools, admin APIs, session APIs, transcript/result UX, and admin machine center.
- Integrations implement a typed machine-control provider contract and may expose provider-specific transport/settings surfaces, but they do not own machine CRUD UX.

## Status

| Phase | Summary | Status |
|---|---|---|
| 1 | Backend target/lease model + companion bridge + lease-gated tools | ✅ shipped 2026-04-23 |
| 2 | Session APIs + initial chat/header lease surfaces | ✅ shipped 2026-04-23 |
| 3 | Non-interactive guardrails for bot/script surfaces | ✅ shipped 2026-04-23 |
| 4 | Canonical docs + architecture linking | ✅ shipped 2026-04-23 |
| 5A | Rich result UX, transcript grant flow, operator docs, agent skill | ✅ shipped 2026-04-23 |
| 6 | Core provider architecture, `/admin/machines`, renderer extraction, tool rename | ✅ shipped 2026-04-23 |

## What Shipped

### Phase 1-3 — Core lease model and companion transport

- Core service now lives in `app/services/machine_control.py` and owns:
  - provider discovery
  - provider-aware target payloads
  - session lease grant/revoke
  - execution-policy validation
  - machine-access-required payloads
- `local_machine_control.py` is now just a compatibility shim.
- `integrations/local_companion/` now supplies:
  - `machine_control.py` provider implementation
  - `bridge.py` websocket bridge
  - `router.py` websocket transport only
  - `client.py` paired companion CLI/daemon
- Tool registry execution policies gate machine control through:
  - `interactive_user`
  - `live_target_lease`
- Non-interactive origins and direct bot/script execution surfaces hard-deny machine tools by default.

### Phase 4-5A — Native machine UX

- Core tools are now:
  - `machine_status`
  - `machine_inspect_command`
  - `machine_exec_command`
- Rich transcript/result views are core-owned:
  - `core.machine_target_status`
  - `core.command_result`
  - `core.machine_access_required`
- Inline transcript machine-access-required cards drive grant/revoke against the existing session lease APIs.
- Added operator/provider docs for `local_companion` and the generic `skills/machine_control.md` agent skill.

### Phase 6 — Provider architecture and admin machine center

- Machine control is now provider-backed rather than integration-owned.
- New core admin API:
  - `GET /api/v1/admin/machines`
  - `POST /api/v1/admin/machines/providers/{provider_id}/enroll`
  - `DELETE /api/v1/admin/machines/providers/{provider_id}/targets/{target_id}`
- New core admin page:
  - `Admin > Machines`
- Session lease API now requires `provider_id` when granting a lease.
- `local_*` tools were removed; there is no alias layer.
- `local_companion` integration no longer owns:
  - tool registration
  - machine CRUD admin endpoints
  - chat UX
- `RichToolResult.tsx` no longer defines machine renderers inline; they live under `ui/src/components/chat/renderers/machineControl/`.
- Follow-up polish on 2026-04-23:
  - integration discovery now exposes machine-control provider metadata to the generic integration detail page
  - `Admin > Integrations > Local Companion` now has a provider-aware quick-setup card that calls the same core enroll API and can generate a ready launch command
  - `/admin/machines` was moved onto the normal padded admin content width instead of rendering edge-to-edge

## Current Architecture Shape

- Core:
  - `app/services/machine_control.py`
  - `app/tools/local/machine_control.py`
  - `app/routers/api_v1_admin/machines.py`
  - `app/routers/sessions.py`
  - `/admin/machines`
  - transcript-native machine result renderers
- Provider implementation:
  - `integrations/local_companion/machine_control.py`
  - `integrations/local_companion/router.py`
  - `integrations/local_companion/bridge.py`
  - `integrations/local_companion/client.py`

## Deferred

- SSH provider on the same machine-control contract.
- Shared lease/consent model for `browser_live` if that path should converge.
- Richer machine capabilities beyond shell once the provider contract settles.
- Multi-worker/shared-broker support for live provider connection state.

## Verification

- `pytest tests/unit/test_local_machine_control_phase5a.py -q`
- `pytest tests/unit/test_machine_target_sessions.py -q`
- `cd agent-server/ui && node --test src/components/chat/renderArchitecture.test.ts 'app/(app)/channels/[channelId]/sessionHeaderChrome.test.ts'`
- `cd agent-server/ui && ./node_modules/.bin/tsc --noEmit --pretty false`
