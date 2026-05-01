---
tags: [spindrel, security, auth, scopes, reference]
status: reference
updated: 2026-04-19
---

# Scope Matrix

**Living reference.** Maps HTTP endpoints → required scope → presets that grant access. Built as part of [[user-management]] Phase 1 scope hygiene. Source of truth for the scope system is `app/services/api_keys.py:18-423` and `app/dependencies.py:230-264`.

## Enforcement model

Two concentric gates for admin routes:
1. **Router-level** — `app/routers/api_v1_admin/__init__.py:12` attaches `Depends(verify_admin_auth)` to every `/api/v1/admin/*` endpoint. JWT users must be `is_admin=True`; scoped API keys are authenticated here and authorization is deferred to the endpoint-level check.
2. **Endpoint-level** — each mutation uses `Depends(require_scopes("resource:action"))` to enforce fine-grained scopes.

Non-admin routes (`/api/v1/{channels, bots-hooks, approvals, ...}`) rely on `require_scopes` alone.

`has_scope()` semantics (`app/services/api_keys.py:518-566`):
- **Exact match** — `channels:write` matches `channels:write`
- **Write implies read** — `channels:write` covers `channels:read`
- **Parent covers child** — `channels:write` covers `channels.messages:write`, `channels.config:write`, etc.
- **Wildcard `*`** — matches everything
- **Admin bypass** — `admin` scope bypasses all checks

## Non-scope authentication endpoints

These are authenticated but not scope-gated. Intentional by design.

| Endpoint | Auth | Reason |
|---|---|---|
| `POST /api/v1/auth/{setup,login,google,refresh,logout}` | none (public) | Auth bootstrap. Setup rate-limited; login rate-limited; refresh needs refresh token. |
| `GET/PUT /api/v1/auth/me`, `POST /api/v1/auth/me/change-password` | `verify_user` (JWT) | User self-service. Request body is whitelisted (display_name/avatar_url/integration_config only — no `is_admin` field), so no privilege escalation path. Password change verifies current password. |
| `POST /api/v1/push/{subscribe,unsubscribe}` | `verify_user` (JWT) | User-owned subscriptions keyed to `user.id`. |
| `POST /api/v1/widget-actions`, `POST /api/v1/widget-actions/refresh` | `verify_auth_or_user` at router level | Per-dispatch authorization: `dispatch="tool"` runs tool dispatch's policy + approval pipeline; `dispatch="api"` proxies to an allowlisted endpoint which runs its own `require_scopes`; `dispatch="widget_config"` performs pin ownership check. Documented inline at `app/routers/api_v1_widget_actions.py:42-49`. |
| `POST /api/v1/widget-auth/mint` | `verify_auth_or_user` + `_caller_may_use_bot` | Ownership check — admin or `bot.user_id == user.id`. |
| `POST /api/v1/transcribe` | `require_scopes("chat")` | Voice transcription is treated as part of chat input. |

## Admin mutation endpoints by scope

All endpoints below sit under `/api/v1/admin/*`. The router-level `verify_admin_auth` establishes admin authentication; the listed scope is enforced at the endpoint level.

| Scope | Endpoints |
|---|---|
| `api_keys:write` | `POST /api-keys`, `PUT /api-keys/{id}`, `DELETE /api-keys/{id}` |
| `attachments:write` | `DELETE /attachments/{id}`, `POST /attachments/purge` |
| `bots:write` | `POST /bots`, `PUT/PATCH /bots/{id}`, `POST /bots/{id}/memory-hygiene/trigger`, `POST /bots/{id}/memory-scheme`, `POST /bots/{id}/sandbox/recreate`, `POST /bots/{id}/enrolled-skills`, `DELETE /bots/{id}/enrolled-skills/{skill}`, `POST /bots/{id}/enrolled-tools`, `DELETE /bots/{id}/enrolled-tools/{tool}` |
| `bots:delete` | `DELETE /bots/{id}` |
| `carapaces:write` | `POST /carapaces`, `PUT /carapaces/{id}`, `DELETE /carapaces/{id}`, `POST /carapaces/{id}/export` |
| `channels:write` | `POST /channels/ensure-orchestrator`, `POST /channels/{id}/heartbeat/toggle`, `POST /channels/{id}/heartbeat/fire`, `POST /channels/{id}/heartbeat/infer`, `POST /channels/{id}/reindex-segments`, `POST /channels/{id}/backfill-sections`, `POST /channels/{id}/repair-section-periods`, `POST /channels/{id}/backfill-transcripts`, `POST /channels/{id}/pipelines`, `PATCH /channels/{id}/pipelines/{sub_id}`, `DELETE /channels/{id}/pipelines/{sub_id}` |
| `docker_stacks:write` | `POST /docker-stacks/{id}/start`, `POST /docker-stacks/{id}/stop`, `DELETE /docker-stacks/{id}` |
| `integrations:write` | `PUT /integrations/{id}/status`, `PUT /integrations/{id}/settings`, `DELETE /integrations/{id}/settings/{key}`, `POST /integrations/{id}/process/{start,stop,restart}`, `PUT /integrations/{id}/process/auto-start`, `POST /integrations/{id}/device-status`, `POST /integrations/{id}/install-{deps,npm-deps,system-deps}`, `POST /integrations/{id}/api-key`, `DELETE /integrations/{id}/api-key`, `POST /integrations/{id}/cancel-pending-tasks`, `POST /integrations/reload`, `PUT /integrations/{id}/yaml`, OAuth start/poll/disconnect endpoints |
| `logs:write` | `PUT /log-level` |
| `mcp_servers:write` | `POST /mcp-servers`, `PUT /mcp-servers/{id}`, `DELETE /mcp-servers/{id}`, `POST /mcp-servers/{id}/test`, `POST /mcp-servers/test-inline` |
| `operations:write` | `POST /backup`, `POST /pull`, `POST /restart`, `PUT /backup/config` |
| `providers:write` | all `/providers/*` mutations, model pull + sync-models + remote-model delete |
| `secrets:write` | `POST /secret-values`, `PUT /secret-values/{id}`, `DELETE /secret-values/{id}` |
| `settings:write` | `PUT /settings`, `DELETE /settings/{key}`, `PUT /global-fallback-models`, `PUT /global-model-tiers` |
| `skills:write` | `POST /skills`, `PUT /skills/{id}`, `DELETE /skills/{id}`, `POST /file-sync` |
| `alerts:write` | `PUT /spike-alerts/config`, `POST /spike-alerts/test` |
| `storage:write` | `POST /storage/purge` |
| `tasks:write` | `POST /tasks`, `POST /tasks/{id}/run`, `POST /tasks/{id}/steps/{i}/resolve`, `DELETE /tasks/{id}` |
| `tools:execute` | `POST /tools/{name}/execute` |
| `usage:write` | `POST /usage/limits`, `PUT /usage/limits/{id}`, `DELETE /usage/limits/{id}` |
| `users:write` | `POST /users`, `PUT /users/{id}`, `DELETE /users/{id}` |
| `webhooks:write` | all `/webhooks/*` mutations including `/rotate-secret` and `/test` |
| `workflows:write` | all `/workflows/*` mutations including run actions (`cancel`, `approve`, `skip`, `retry`) |
| *(read-only analytics / diagnostics use `require_scopes` with `:read` counterparts — not listed here)* | |

## Non-admin scoped endpoints

All outside `/api/v1/admin/*`. No router-level admin gate — `require_scopes` is the only enforcement.

| Endpoint | Scope |
|---|---|
| `POST /api/v1/chat`, `/api/v1/chat/stream`, `/api/v1/chat/cancel`, `/api/v1/chat/tool_result` | `chat` |
| `POST /api/v1/channels`, `PUT /api/v1/channels/{id}`, `DELETE /api/v1/channels/{id}` | `channels:write` |
| `POST /api/v1/channels/{id}/messages`, `/reset`, `/compact`, `/switch-session` | `channels.messages:write` |
| `POST /api/v1/channels/{id}/integrations`, `DELETE /api/v1/channels/{id}/integrations/{binding_id}`, `POST .../adopt`, `/activate`, `/deactivate`, `PATCH .../config` | `channels.integrations:write` |
| `POST /api/v1/channels/{id}/bot-members`, `DELETE .../bot-members/{bot_id}`, `PATCH .../bot-members/{bot_id}/config` | `channels:write` |
| `POST /api/v1/channels/{id}/pins`, `DELETE .../pins` | `channels:write` |
| `POST /api/v1/approvals/{id}/decide` | `approvals:write` |
| `POST /api/v1/attachments/upload` | `attachments:write` |
| `POST /api/v1/bot-hooks`, `PUT .../{id}`, `DELETE .../{id}` | `bot_hooks:write` |
| `POST /api/v1/carapaces`, `PUT .../{id}`, `DELETE .../{id}` | `carapaces:write` |
| `POST /api/v1/channels/{id}/workspace/files/*`, `PUT /files/content`, `DELETE /files`, `POST /files/{move,restore,upload}` | `channels:write` (broad) |
| `POST /api/v1/dashboards`, `PATCH .../{slug}`, `DELETE .../{slug}`, `/dashboard/pins*` | `channels:write` |
| `POST /api/v1/documents`, `DELETE .../{id}` | `documents:write` |
| `POST /api/v1/llm/completions` | `llm:completions` |
| `POST /api/v1/modals/{callback_id}/{submit,cancel}` | `channels.integrations:write` (Slack modals) |
| `POST /api/v1/prompt-templates`, `PUT .../{id}`, `DELETE .../{id}` | `prompt_templates:write` (via chat preset) |
| `POST /api/v1/push/send` | `push:send` |
| `POST /api/v1/search/memory` | `mission_control:read` |
| `POST /api/v1/sessions`, `POST /api/v1/sessions/ephemeral`, `POST /api/v1/sessions/{id}/messages` | `sessions:write` |
| `DELETE /api/v1/sessions/{id}`, plans status, summarize | `sessions:write` |
| `POST /api/v1/todos`, `PATCH .../{id}`, `DELETE .../{id}` | `todos:write` |
| `PUT /api/v1/tool-policies/settings`, `POST /test`, `POST /rules`, `PUT /rules/{id}`, `DELETE /rules/{id}` | `tool_policies:write` |
| `POST /api/v1/workspaces`, `DELETE .../{id}`, `POST .../bots`, `DELETE .../bots/{bot_id}` | `workspaces:write` |
| `PUT /api/v1/workspaces/{id}/files/content`, `POST .../mkdir`, `DELETE .../files`, `POST .../move`, `POST .../upload`, `POST .../reindex` | `workspaces.files:write` |

## Preset → scope mapping

`app/services/api_keys.py:326-423`.

| Preset | Purpose | Scopes (abbreviated) |
|---|---|---|
| `admin_user` | Admin user account (auto-provisioned) | `admin` |
| `member_user` | Non-admin user account (auto-provisioned) | `chat`, `bots:read`, `channels:read/write`, `sessions:read`, `attachments:read/write`, `todos:read/write`, `mission_control:read/write`, `approvals:read` |
| `chat_client` | External chat-only clients | `chat`, `bots:read`, `channels:read/write`, `sessions:read`, `attachments:read/write` |
| `slack_integration` | Messaging integrations (Slack, Discord, BlueBubbles, etc.) | `chat`, `bots:read`, `channels:read/write`, `channels.config:read/write`, `sessions:read/write`, `todos:read`, `llm:completions` |
| `workspace_bot` | Bots calling the server from their container | `chat`, `bots:read`, `channels:read/write`, `sessions:read`, `tasks:read/write`, `documents:read/write`, `todos:read/write`, `workspaces.files:read/write`, `attachments:read/write`, `carapaces:read/write`, `tools:read/execute` |
| `read_only` | Dashboards / monitors | `bots:read`, `channels:read`, `sessions:read`, `tasks:read`, `todos:read`, `attachments:read`, `logs:read` |
| `mission_control` | MC dashboard container | `bots:read`, `channels:read`, `sessions:read`, `tasks:read/write`, `todos:read/write`, `workspaces:read`, `workspaces.files:read/write`, `attachments:read`, `logs:read`, `mission_control:read/write`, `carapaces:read` |

### What `member_user` CAN do

- Send/read chat, create & edit channels, read bot configs
- Manage own todos, attachments, approvals
- Use Mission Control

### What `member_user` CANNOT do (relevant to this track)

- Write bots (`bots:write`) → Phase 5 adds `bot_grants` for delegated access
- Manage integration bindings (`channels.integrations:write`, `integrations:write`) → Phase 6 keeps admin-only
- Edit channel config (`channels.config:write`) → covered by parent `channels:write` ✱
- User management (`users:write`), settings (`settings:write`), providers (`providers:write`), API keys (`api_keys:write`)

✱ Note the parent-covers-child relationship: `channels:write` (granted to members) transitively covers `channels.config:write`, `channels.integrations:write`, `channels.heartbeat:write`, `channels.messages:write`. **This means the current preset already grants members the ability to bind integrations via the non-admin `/api/v1/channels/{id}/integrations` route.** This will need closing in Phase 6 — either (a) tighten `has_scope`'s parent-covers-child to exclude `channels.integrations:*` when parent is `channels:write`, (b) split `channels:write` into narrower sub-scopes in the `member_user` preset, or (c) add an explicit admin check inside the non-admin integration routes. Decision deferred to Phase 6.

## Phase 1 audit findings

Scope hygiene pass ran 2026-04-19. 120+ mutation endpoints classified. Three items surfaced:

1. ~~**`POST /api/v1/transcribe`** — authenticated but not scope-gated (`app/routers/transcribe.py:68`).~~ Resolved before the 2026-04-30 security refresh: the route now uses `require_scopes("chat")`, and `tests/integration/test_voice_audio.py::TestTranscribeAuth` pins the denial/allowance paths.

2. ~~**Widget actions router authenticates only, delegates authorization** — `POST /api/v1/widget-actions` + `/refresh` sat behind router-level `verify_auth_or_user` while relying on implicit downstream checks.~~ Resolved in the 2026-04-30 security pass: `app/services/widget_action_auth.py` is now the shared boundary for action dispatch, refresh, refresh-batch, and event-stream authorization; `tests/unit/test_widget_actions_authorization.py` pins widget-token pin scoping, channel-owner checks, API allowlist denial, and route wiring.

3. ~~**`require_scopes` fails OPEN for JWT users with no `_resolved_scopes`**~~ ✅ **RESOLVED 2026-04-19.** Changed to fail closed for non-admin users; admins keep the bypass via the `is_admin` flag so a broken admin provisioning doesn't lock the server out. New regression tests replace the prior backcompat pin. See [[fix-log#2026-04]] entry for `require_scopes` fail-closed.

No mutation endpoint was found without some form of enforcement. The scope system is consistently applied across 120+ mutation endpoints. No endpoint-level fixes shipped in Phase 1.

## Verifying the matrix

Regenerate the endpoint → scope map any time:

```bash
cd /home/mtoth/personal/spindrel
python3 -c "
import ast, pathlib, re
for p in sorted(pathlib.Path('app/routers').rglob('*.py')):
    src = p.read_text()
    for m in re.finditer(r'@router\.(post|put|patch|delete)\([^)]*\)', src, re.DOTALL):
        decorator = m.group(0)
        # Find the function definition that follows
        tail = src[m.end():m.end()+600]
        scope_m = re.search(r'require_scopes\(\"([^\"]+)\"', tail)
        print(f'{p}:{m.start()}  {decorator.splitlines()[0]}  scope={scope_m.group(1) if scope_m else \"-\"}')" | head -80
```

## Related

- [[user-management]] — the track this doc was built for
- [[architecture-decisions#Scope System]] — the design decisions behind the scope grammar
- Backend source: `app/services/api_keys.py`, `app/dependencies.py`
- Frontend scope-awareness (Phase 2): `ui/src/hooks/useScope.ts` (NEW)
