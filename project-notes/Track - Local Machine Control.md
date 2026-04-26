---
tags: [agent-server, track, local-control, integrations]
status: active
created: 2026-04-23
updated: 2026-04-26 (api-v1 session lease route fix)
---
# Track — Local Machine Control

## Goal

Let a live signed-in admin grant one chat/session temporary control over one explicit machine target so the agent can inspect or execute on the user's real machine without pretending the server itself is local.

## Decisions Locked

- Machine control is a core subsystem, not a `local_companion` feature with bespoke core UI.
- Targets are addressed as `(provider_id, target_id)`.
- Shipped providers are `local_companion` with `driver="companion"` and `ssh` with `driver="ssh"`.
- Cross-provider readiness is based on a fresh provider probe or live-status check, not a companion-specific connection concept.
- One session can lease one target at a time. One target can be leased by only one session at a time.
- Lease-gated tools are denied unless there is a live JWT user, active presence, and a valid session lease for the same user.
- Lease state lives in `Session.metadata_["machine_target_lease"]`.
- Core owns the machine tools, admin APIs, session APIs, transcript/result UX, and admin machine center.
- Integrations implement a typed machine-control provider contract and may expose provider-specific transport/settings surfaces, but they do not own machine CRUD UX.
- Provider-level credentials and trust material live in app-managed integration settings so setup survives container rebuilds.

## Status

| Phase | Summary | Status |
|---|---|---|
| 1 | Backend target/lease model + companion bridge + lease-gated tools | ✅ shipped 2026-04-23 |
| 2 | Session APIs + initial chat/header lease surfaces | ✅ shipped 2026-04-23 |
| 3 | Non-interactive guardrails for bot/script surfaces | ✅ shipped 2026-04-23 |
| 4 | Canonical docs + architecture linking | ✅ shipped 2026-04-23 |
| 5A | Rich result UX, transcript grant flow, operator docs, agent skill | ✅ shipped 2026-04-23 |
| 6 | Core provider architecture, `/admin/machines`, renderer extraction, tool rename | ✅ shipped 2026-04-23 |
| 7 | Provider-generic readiness contract, SSH provider, probe UX | ✅ shipped 2026-04-24 |
| 8 | Transcript-first UX, header chrome removal, optional native widget | ✅ shipped 2026-04-24 |
| 9 | Generic provider profiles, SSH-first adoption, machine-center profile UI | ✅ shipped 2026-04-24 |
| 10 | Admin machine-center UI refresh against canonical control-surface standards | ✅ shipped 2026-04-24 |
| 11 | Guided machine-center flow, recoverable companion setup, reconnecting Linux user service | ✅ shipped 2026-04-25 |

## What Shipped

### Phase 1-3 — Core lease model and companion transport

- Core service now lives in `app/services/machine_control.py` and owns:
  - provider discovery
  - provider-aware target payloads
  - session lease grant/revoke
  - execution-policy validation
  - machine-access-required payloads
- `local_machine_control.py` compatibility shim **deleted 2026-04-23** (Ousterhout housekeeping — zero importers). All code lives in `app/services/machine_control.py`.
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
  - corrected a UI API regression where machine-control hooks were calling `/admin/machines` directly instead of `/api/v1/admin/machines`, which caused real browser 404s on enroll; paths are now centralized in a tested helper
  - corrected the companion bootstrap path again: setup surfaces now generate a real zero-repo `curl -fsSL {server}/integrations/local_companion/client.py -o /tmp/spindrel-local-companion.py && python /tmp/spindrel-local-companion.py ...` command instead of repo-dependent Python module invocations

### Phase 7 — SSH provider and provider-generic readiness

- Core provider contract no longer assumes every provider has a live connection object.
- Readiness is now provider-generic:
  - cached target status is rendered in the UI
  - lease grant and lease-gated execution require a fresh provider probe
- Target payloads and lease payloads now expose canonical readiness fields:
  - `ready`
  - `status`
  - `reason`
  - `checked_at`
  - `handle_id`
- Added a shared core inspect validator so readonly shell semantics are enforced before provider dispatch.
- Added `POST /api/v1/admin/machines/providers/{provider_id}/targets/{target_id}/probe`.
- Shipped `integrations/ssh/` as the second provider:
  - provider-defined enrollment fields for `host`, `username`, `port`, and optional default `working_dir`
  - provider-level secrets in integration settings: private key, `known_hosts`, and timeout/output caps
  - strict non-interactive OpenSSH subprocess execution with one fresh session per probe/command
  - cached target metadata refresh for hostname, platform, readiness, and failure reason
- `Admin > Machines` now renders provider-defined enroll fields generically and exposes per-target `Probe`.
- SSH settings are stored in app-managed integration settings rather than ephemeral container filesystem state, so container rebuilds do not wipe setup.

### Phase 8 — Transcript-first machine UX and optional native widget

- Removed the default machine-control affordance from chat header chrome.
- Machine control is now explicitly transcript-first:
  - required grant/revoke flows stay in `core.machine_access_required`
  - status/result flows stay in `core.machine_target_status` and `core.command_result`
- Added `core/machine_control_native` as an optional channel-scoped native widget:
  - manual pin only
  - session-aware status + controls
  - per-target `Use`, `Revoke`, and `Probe`
  - no pinned-widget context export
- New invariant: machine control may appear in chat chrome only when intentionally pinned as a widget or rendered in transcript/result surfaces, not as a default top-right header icon.

### Phase 9 — Generic provider profiles, SSH-first adoption

- Added generic provider-profile support to the core machine-control contract:
  - provider summaries now expose `supports_profiles`, `profile_fields`, `profiles`, and `profile_count`
  - core admin profile APIs now exist under `/api/v1/admin/machines/providers/{provider_id}/profiles`
- `Admin > Machines` is now the canonical machine-profile surface:
  - profile CRUD is rendered generically from provider-declared `profile_fields`
  - target enrollment is gated until a required profile exists
  - profile-capable providers inject a required profile selector into target enrollment
- `Admin > Integrations > <provider>` machine section is now summary-only; it points back to `Admin > Machines` instead of acting as a shadow machine center.
- `ssh` is the first provider using profiles:
  - top-level `SSH_PRIVATE_KEY` / `SSH_KNOWN_HOSTS` runtime path removed
  - named SSH profiles now carry private key + `known_hosts`
  - each SSH target references one explicit `profile_id`
  - no provider-global ambient credential fallback remains
- Profiles and targets persist in provider-owned app settings, so SSH setup survives container rebuilds without requiring new core tables.

### Phase 10 — Admin machine-center UI refresh

- `/admin/machines` now uses the canonical low-chrome control-surface language from `docs/guides/ui-design.md`.
- Provider/profile/enroll/target groups moved onto shared Tailwind token controls; the route no longer uses `useThemeTokens()` or inline color styling.
- `Admin > Integrations > <machine provider>` remains summary/link-only, preserving Admin > Machines as the canonical profile/target lifecycle surface.

### Follow-up fix — Local Companion bootstrap URL

- The downloaded `local_companion` client now derives its WebSocket endpoint from the HTTP(S) `--server-url` emitted by the setup command, mapping `http -> ws` and `https -> wss` while preserving path prefixes. This keeps the `curl` bootstrap command copyable as-is and avoids passing an `http://.../ws` URI into `websockets.connect`.
- Startup tool discovery now loads `app/tools/local/machine_control.py` without a `ToolResultEnvelope` circular import while `app.agent.tool_dispatch` is still initializing; the machine-control tool lazily imports the envelope class inside its builder like the other envelope-producing tools.

### Phase 11 — Guided companion recovery and reconnect install

- Added a write-scoped target setup endpoint so Local Companion launch/install commands can be regenerated after the original enrollment response is gone; normal target list payloads stay token-redacted.
- `Admin > Machines` now explains Local Companion vs SSH, exposes per-target `Copy launcher`, `Install service`, and `Copy prompt` actions, and clarifies that session leases and exec approvals are separate gates.
- Machine status/access cards and the optional native widget now expose copyable starter prompts for the active session.
- Local Companion client now reconnects by default, supports `--once`, lazy-loads `websockets`, and can install itself as a Linux `systemd --user` service with its own venv.
- Integration list/detail surfaces now render manifest descriptions so provider purpose is visible outside setup instructions.

### Follow-up fix — API v1 session lease routes

- Fixed the optional native widget / transcript grant path calling `/api/v1/sessions/{session_id}/machine-target/lease` and receiving 404 because the machine-target session endpoints only existed on the legacy `/sessions` router. `app/routers/api_v1_sessions.py` now exposes GET/POST/DELETE machine-target routes with the same admin-only lease behavior.
- Added a focused route-table + direct async forwarding test for the API-v1 lease path. A full `TestClient` version hit the already-known local machine-router stall pattern, so the regression avoids that harness while still pinning the missing route.

## Current Architecture Shape

- Core:
  - `app/services/machine_control.py`
  - `app/tools/local/machine_control.py`
  - `app/routers/api_v1_admin/machines.py`
  - `app/routers/api_v1_sessions.py`
  - `app/routers/sessions.py`
  - `/admin/machines`
  - transcript-native machine result renderers
- Provider implementation:
  - `integrations/local_companion/machine_control.py`
  - `integrations/local_companion/router.py`
  - `integrations/local_companion/bridge.py`
  - `integrations/local_companion/client.py`
  - `integrations/ssh/machine_control.py`

## Deferred

- macOS and Windows companion service/install packaging; Linux/systemd user service is the current robust path.
- Shared lease/consent model for `browser_live` if that path should converge.
- Richer machine capabilities beyond shell once the provider contract settles.
- Multi-worker/shared-broker support for live provider connection state.
- Better pytest reliability around the `test_machine_admin_routes_drift.py` stall pattern so router-level machine-profile tests can be left in the normal aggregate slice instead of file-by-file verification.
- Browser visual review of the refreshed `/admin/machines` surface in light and dark mode.

## Verification

- `pytest tests/unit/test_local_machine_control_phase5a.py -q`
- `pytest tests/unit/test_machine_target_sessions.py -q`
- `pytest tests/unit/test_machine_control_drift.py tests/unit/test_local_companion_provider.py tests/unit/test_ssh_provider.py tests/unit/test_integration_setup.py::TestDiscoverSetupStatus::test_local_companion_exposes_machine_control_metadata tests/unit/test_integration_setup.py::TestDiscoverSetupStatus::test_ssh_exposes_machine_control_metadata -q`
- `timeout 30s pytest tests/unit/test_ssh_provider.py -q`
- `timeout 30s pytest tests/unit/test_machine_target_sessions.py -q`
- `timeout 30s pytest tests/unit/test_machine_control_drift.py -q`
- `cd agent-server/ui && node --test src/components/chat/renderArchitecture.test.ts 'app/(app)/channels/[channelId]/sessionHeaderChrome.test.ts'`
- `cd agent-server/ui && node --test src/lib/machineControlSetup.test.ts`
- `cd agent-server/ui && node --test src/lib/machineControlApiPaths.test.ts`
- `cd agent-server/ui && ./node_modules/.bin/tsc --noEmit --pretty false`
- `cd agent-server/ui && npx tsc --noEmit` after the admin machine-center UI refresh.
- `pytest tests/unit/test_local_companion_provider.py -q`
- `PYTHONPYCACHEPREFIX=/tmp/agent-server-pycache python -m py_compile integrations/local_companion/client.py`
- `pytest tests/unit/test_local_machine_control_phase5a.py -q`
- `PYTHONPYCACHEPREFIX=/tmp/agent-server-pycache python -m py_compile app/tools/local/machine_control.py tests/unit/test_local_machine_control_phase5a.py`
- `pytest tests/unit/test_api_v1_machine_target_routes.py -q`
- `pytest tests/unit/test_machine_target_sessions.py tests/unit/test_api_v1_machine_target_routes.py -q`
