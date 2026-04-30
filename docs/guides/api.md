# Developer API

Spindrel exposes a comprehensive REST API for building integrations, dashboards, and custom clients. This guide covers authentication, endpoint discovery, the chat API, and streaming events.

## Interactive Documentation

Spindrel auto-generates OpenAPI docs from its route definitions:

| URL | Description |
|-----|-------------|
| `/docs` | Swagger UI — interactive endpoint explorer with "Try it out" |
| `/redoc` | ReDoc — readable reference documentation |
| `/openapi.json` | Raw OpenAPI 3.x schema (for code generation) |

All endpoints are visible, including admin routes. Authentication is still enforced — the docs just show what's available.

## Agent Entry Points

Agents that are discovering Spindrel from a running server should start with:

| URL | Purpose |
|-----|---------|
| `/llms.txt` | Agent-readable project summary, quickstart, concepts, and links |
| `/health` | Unauthenticated liveness/version probe |
| `/openapi.json` | Full OpenAPI schema |
| `/api/v1/discover` | Scoped endpoint catalog for the caller's API key |
| `/api/v1/system-health/runtime` | Authenticated build/process identity for live health triage |
| `/api/v1/agent-capabilities` | Runtime bot/channel/session capability manifest |
| `/api/v1/agent-status` | Runtime bot/channel/session status snapshot |
| `/api/v1/agent-activity` | Normalized replay log for bot activity and review evidence |
| `/api/v1/execution-receipts` | Durable receipts for approval-gated or agent-important actions |

Repo-dev agents working from the Git checkout should read `llms.txt`, `README.md`, `.agents/manifest.json`, and the relevant `.agents/skills/*/SKILL.md` files. Those repo-dev skills are not Spindrel runtime skills and are not visible to in-app channel agents unless a runtime bridge explicitly supplies them.

## Authentication

Spindrel supports three authentication methods:

### Static API Key

Set `API_KEY` in your `.env`. Pass it as a Bearer token:

```bash
curl -H "Authorization: Bearer your-api-key" \
  http://localhost:8000/api/v1/admin/bots
```

The static key has full access to all endpoints.

### Scoped API Keys

Scoped keys (prefixed `ask_`) grant access to specific endpoint groups. Create them via the admin UI (**Settings > API Keys**) or the API:

```bash
# Create a scoped key with chat + channel access
curl -X POST http://localhost:8000/api/v1/admin/api-keys \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-integration", "scopes": ["chat", "channels:read"]}'
```

The response includes the key (shown once) and its scopes.

#### Scope Reference

Scopes are defined in `app/services/api_keys.py` and exposed through the API-key admin endpoints. The current public groups are:

| Group | Scopes | Description |
|-------|--------|-------------|
| **Admin** | `admin` | Full access — bypasses all scope checks |
| **Channels** | `channels:read`, `channels:write` | Channel CRUD (broad — includes sub-scopes) |
| **Channels (granular)** | `channels.messages:read/write`, `channels.config:read/write`, `channels.heartbeat:read/write`, `channels.integrations:read/write` | Fine-grained channel sub-resources |
| **Chat** | `chat` | Send messages (blocking + streaming), cancel, submit tool results |
| **Sessions** | `sessions:read`, `sessions:write` | Session details and message history |
| **Bots** | `bots:read`, `bots:write`, `bots:delete` | Bot configuration management |
| **Tasks** | `tasks:read`, `tasks:write` | Scheduled/deferred task management |
| **Workspaces** | `workspaces:read/write`, `workspaces.files:read/write` | Workspace management and file operations |
| **Documents** | `documents:read`, `documents:write` | Ingested document search and management |
| **Todos** | `todos:read`, `todos:write` | Persistent work items |
| **Attachments** | `attachments:read`, `attachments:write` | File attachment management |
| **Logs** | `logs:read`, `logs:write` | Agent turns, tool calls, traces, server logs |
| **Tools** | `tools:read`, `tools:execute` | Tool listing and direct execution |
| **Providers** | `providers:read`, `providers:write` | LLM provider configuration |
| **Users** | `users:read`, `users:write` | User management |
| **Settings** | `settings:read`, `settings:write` | Server-wide settings |
| **Operations** | `operations:read`, `operations:write` | Backups, git pull, restart |
| **Usage** | `usage:read`, `usage:write` | Cost analytics and usage limits |
| **Workflows** | `workflows:read`, `workflows:write` | Deprecated workflow routes (see [Pipelines](pipelines.md)). Scope retained for historical API compatibility. |
| **LLM** | `llm:completions` | Direct LLM calls through the server's provider system |
| **API Keys** | `api_keys:read`, `api_keys:write` | Scoped API-key management |
| **Integrations** | `integrations:read`, `integrations:write` | Integration setup, settings, process control, and dependencies |
| **MCP Servers** | `mcp_servers:read`, `mcp_servers:write` | Model Context Protocol server configuration |
| **Skills** | `skills:read`, `skills:write` | Skill definitions and metadata |
| **Secrets** | `secrets:read`, `secrets:write` | Secret-value metadata and writes |
| **Webhooks** | `webhooks:read`, `webhooks:write` | Webhook configuration and delivery history |
| **Docker Stacks** | `docker_stacks:read`, `docker_stacks:write` | Docker stack configuration and control |
| **Alerts** | `alerts:read`, `alerts:write` | Spike alert configuration |
| **Notifications** | `notifications:read`, `notifications:write`, `notifications:send` | Notification targets and test sends |
| **Approvals** | `approvals:read`, `approvals:write` | Tool approval queue |
| **Tool Policies** | `tool_policies:read`, `tool_policies:write` | Tool-level permission policies |
| **Bot Hooks** | `bot_hooks:read`, `bot_hooks:write` | Bot lifecycle hooks |
| **Storage** | `storage:read`, `storage:write` | Storage usage and cleanup |
| **Push** | `push:send` | Web Push notification sends |

!!! note "Pipelines use `tasks:*` scopes"
    Task pipelines are stored as `Task` rows, so pipeline CRUD and run management are authorized by `tasks:read` / `tasks:write`. The `workflows:*` scope guards the legacy workflows router only.

**Hierarchy rules**: `channels:write` implies all `channels.*:write` sub-scopes. `admin` implies everything.

#### Presets

The admin UI offers one-click presets for common use cases:

| Preset | Use Case | Key Scopes |
|--------|----------|------------|
| **Messaging Integration** | Slack, Discord, etc. | `chat`, `bots:read`, `channels:read/write`, `channels.config:read/write`, `sessions:read/write`, `todos:read`, `llm:completions` |
| **Chat Client** | Custom chat frontends | `chat`, `bots:read`, `channels:read/write`, `sessions:read`, `attachments:read/write` |
| **Container Bot** | Bots in their container environment | `chat`, `bots:read`, `channels:read/write`, `tasks:read/write`, `documents:read/write`, `todos:read/write`, `workspaces.files:read/write`, `attachments:read/write`, `tools:read/execute` |
| **Read-Only Monitor** | Dashboards | `bots:read`, `channels:read`, `sessions:read`, `tasks:read`, `todos:read`, `attachments:read`, `logs:read` |
| **Admin User** | Full admin access for admin users | `admin` |
| **Member User** | Standard user API access | `chat`, `bots:read`, `channels:read/write`, `sessions:read`, `attachments:read/write`, `todos:read/write`, `approvals:read` |

### JWT (User Authentication)

The UI uses JWT tokens via Google OAuth. For API access, scoped keys are preferred.

### Widget Tokens (Short-Lived, Bot-Scoped)

Interactive HTML widgets (authored by bots via `emit_html_widget`) render in sandboxed iframes and need to call `/api/v1/...` endpoints without borrowing the viewing user's session. Spindrel mints **short-lived (15 min) bot-scoped JWTs** for this case via `POST /api/v1/widget-auth/mint` — payload `{source_bot_id, pin_id?}`, response `{token, expires_at, expires_in, bot_id, bot_name, scopes}`. The renderer re-mints every 12 min and pushes the new token into the live iframe so the widget never 401s mid-session.

Under the hood these are regular JWTs with `kind: "widget"` in the payload; the auth dependency has a dedicated branch that returns an `ApiKeyAuth` with the scopes inlined from the token (no per-request DB lookup). Scopes are copied from the bot's configured API key at mint time, so **the widget can only do what the bot could do** — not what the viewing user could do. See the [HTML Widgets guide](html-widgets.md) for the user-facing version.

You shouldn't typically call `/widget-auth/mint` yourself — it's automated by the widget renderer. It's documented here for completeness.

## Endpoint Discovery

The `/api/v1/discover` endpoint returns all accessible endpoints filtered by your key's scopes:

```bash
# List endpoints accessible with your key
curl -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/api/v1/discover

# Get full markdown API reference
curl -H "Authorization: Bearer $API_KEY" \
  "http://localhost:8000/api/v1/discover?detail=true"
```

The basic response includes method, path, description, and required scope for each endpoint. The bot-facing `list_api_endpoints` tool returns the same filtered catalog plus request parameters, request-body schema, response schema, and endpoint notes when those are available from OpenAPI.

### Agent Capability Manifest

Agents can inspect their full working surface through one manifest:

```bash
curl -H "Authorization: Bearer $API_KEY" \
  "http://localhost:8000/api/v1/agent-capabilities?bot_id=default&include_schemas=true"
```

The response includes scoped API endpoints, tool profiles and working-set state, enrolled skills, recommended skills to load now, missing skill-coverage candidates, Project/runtime readiness, runtime context budget, assigned Mission Control work, agent status, recent agent activity, harness status, widget authoring tools, integration readiness, and `doctor.findings` with concrete next actions. Bots normally call the same contract through `list_agent_capabilities`; `get_agent_context_snapshot` returns the compact runtime budget/recommendation view, `get_agent_work_snapshot` returns only assigned missions/Attention Items, `get_agent_status_snapshot` returns only current run/heartbeat status, `get_agent_activity_log` returns the normalized replay log, `publish_execution_receipt` records durable action outcomes, and `run_agent_doctor` returns only the readiness findings.

`list_agent_capabilities` and `run_agent_doctor` are baseline injected bot tools. Runtime context also includes a short self-inspection prompt rule: call the manifest before broad API, config, integration, widget, Project, harness, or readiness work; call Doctor when blocked or before asking a human to inspect settings; and follow `skills.recommended_now[*].first_action` before procedural work. Agent Readiness findings can recommend the runtime skill `agent_readiness/operator`. The prompt guides agent behavior, but Spindrel does not auto-call these tools every turn.

Readiness repair actions support dry-run preflight before mutation:

```bash
curl -X POST -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"bot_id":"default","action_id":"default:missing_api_scopes:workspace_bot"}' \
  "http://localhost:8000/api/v1/agent-capabilities/actions/preflight"
```

The response uses `agent-action-preflight.v1` and returns `status` (`ready`, `blocked`, `stale`, or `noop`), `can_apply`, `reason`, required/missing actor scopes, the current finding codes, and `would_change` field diffs. The bot-facing equivalent is `preflight_agent_repair(action_id=...)`. Preflight is read-only; approved repairs still go through the existing Bot update API/tool and then write an execution receipt.

Agents that cannot apply a ready repair can queue it for review instead:

```bash
curl -X POST -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"bot_id":"default","action_id":"default:missing_api_scopes:workspace_bot","rationale":"I need API grants to finish the assigned work."}' \
  "http://localhost:8000/api/v1/agent-capabilities/actions/request"
```

The response uses `agent-repair-request.v1`. When the current action still preflights as `ready`, Spindrel writes an `agent_readiness` execution receipt with `status: "needs_review"` and exposes it under `doctor.pending_repair_requests` in the capability manifest. `GET /api/v1/workspace/attention/brief` also returns these requests in `autofix_queue` with `summary.autofix`, so Mission Control Review can show requested readiness repairs beside owner decisions and fix packs. This endpoint requires `tools:execute`; it records the requester's missing apply scopes for reviewers, but it does not mutate bot configuration. The bot-facing equivalent is `request_agent_repair(action_id=..., rationale=...)`.

The `runtime_context` section normalizes the latest context budget into `tokens_used`, `tokens_remaining`, `total_tokens`, `percent_full`, `source`, `context_profile`, and a recommendation of `continue`, `summarize`, `handoff`, or `unknown`. Doctor findings flag `context_should_summarize` at 75-89% full and `context_should_handoff` at 90% or higher.

The `work_state` section is read-only. It lists active Mission assignments and assigned Attention Items for the current bot, plus a compact `recommended_next_action` of `idle`, `advance_mission`, or `review_attention`. Mutations still go through the existing mission/attention tools and APIs.

The `agent_status` section is read-only. It derives `idle`, `scheduled`, `working`, `blocked`, `error`, or `unknown` from existing Tasks, HeartbeatRuns, ChannelHeartbeat config, sessions, and structured tool-call errors. Use `GET /api/v1/agent-status` or `get_agent_status_snapshot` when an agent needs to decide whether to wait, review a stale run, inspect the latest failure, or configure a heartbeat through the existing Channel Automation settings.

The `activity_log` section is read-only. It summarizes replayable activity already persisted elsewhere: tool calls, Attention Items, Mission updates, Project run receipts, widget agency receipts, and execution receipts. Use `GET /api/v1/agent-activity` or the `get_agent_activity_log` bot tool when an agent needs the actual items. Each item has a stable `kind`, normalized `actor`, `target`, `status`, `summary`, optional `next_action`, optional `trace.correlation_id`, and optional structured `error` fields.

The `skills.recommended_now` section is read-only. It points the agent at existing runtime skills with exact first actions such as `get_skill("diagnostics")` or `get_skill("agent_readiness/operator")`, especially for procedural workflows that smaller models may miss. Entries include audit fields (`coverage_status`, `nearest_existing_skill_ids`, `why_skill_shaped`, `small_model_reason`, and `suggested_owner`) so agents can reuse existing runtime skills before proposing new ones. `skills.creation_candidates` names missing or partially covered procedural coverage that may become a future runtime skill; it does not create bot-authored skills, import repo-dev `.agents` skills, enroll skills, or auto-inject skill bodies.

Execution receipts use `execution-receipt.v1`. They are not a second mutation path: the real change still goes through the existing Bot, Channel, Project, Widget, or Integration API/tool. The receipt records the outcome for later review with `actor`, `target`, `action_type`, `before_summary`, `after_summary`, `approval_required`, `approval_ref`, `result`, `rollback_hint`, and trace identifiers. Agent Readiness request receipts are review queue entries (`needs_review`, `requested_repair: true`); approved repairs later update the same idempotent receipt after preflight and bot patch execution, then recheck the capability manifest. Applied repair receipt `result` includes `preflight`, `doctor_status_before`, `doctor_status_after`, `finding_resolved`, `remaining_findings`, and any `verification_error`. Bots can publish equivalent receipts with `publish_execution_receipt` after agent-important actions.

Integration readiness is read-only in v1. The `integrations` section summarizes workspace-level setup health and current-channel activation/binding state; doctor actions route humans to existing Integration or Channel settings instead of enabling integrations, installing dependencies, starting processes, or writing secrets automatically.

`call_api` accepts either a JSON string or a structured JSON body. Prefer structured bodies so agents do not have to hand-escape JSON:

```json
{
  "method": "POST",
  "path": "/api/v1/channels",
  "body": {"name": "ops", "bot_id": "default"}
}
```

### System Health Triage

Daily health summaries remain available at `/api/v1/system-health/summaries/*`.
For on-demand triage, use:

- `GET /api/v1/system-health/runtime`
- `GET /api/v1/system-health/recent-errors?since=24h&services=&limit=50&include_attention=true`
- `POST /api/v1/system-health/recent-errors/promote`
- `POST /api/v1/workspace/attention/{id}/resolve`

`runtime` is the authenticated build/process identity preflight. It reports
safe fields such as package version, process start time, uptime, hostname,
best-effort container id, build commit/ref/time/source/deploy id when the
deployment supplied them, and stable feature flags. Use it to confirm which
build a live agent is talking to; keep `/health` for unauthenticated
liveness/readiness checks.
`spindrel pull`, `spindrel rebuild`, `scripts/install-service.sh`, and the e2e
image builders stamp Docker builds with this metadata automatically. Custom
deploy scripts can pass the same fields through `SPINDREL_BUILD_SHA`,
`SPINDREL_BUILD_REF`, `SPINDREL_BUILD_TIME`, `SPINDREL_BUILD_SOURCE`, and
`SPINDREL_DEPLOY_ID`.

`recent-errors` returns the same deduped `LogFinding` shape as
`get_recent_server_errors` and can annotate each finding with matching
Attention item id/status, resolution, note, `duplicate_of`, and a computed
`review_state` such as `open`, `resolved_duplicate`, or
`stale_resolved_reappeared`. Callers can focus the working set with
`review_state=open`, `review_state=stale_resolved_reappeared`, or
`exclude_review_state=resolved_duplicate`. `promote` creates or reuses system-authored
Attention items for selected findings; by default it promotes `error` and
`critical` findings while skipping findings already reviewed as
`resolved_duplicate` unless their `dedupe_key` is explicitly requested.
`resolve` still accepts an empty body, but may also store `resolution`, `note`,
and `duplicate_of` in Attention evidence for audit-friendly health triage.
Runtime agents should use `skills/diagnostics/health_triage.md`; repo-dev
agents should use `.agents/skills/spindrel-live-health-triage`.

## Chat API

### Blocking Request

```bash
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is the weather like?",
    "bot_id": "default",
    "channel_id": "your-channel-uuid"
  }'
```

Response:

```json
{
  "session_id": "uuid",
  "response": "The weather is...",
  "transcript": "",
  "client_actions": []
}
```

### Streaming Request

```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Write a haiku about coding",
    "bot_id": "default",
    "channel_id": "your-channel-uuid"
  }' --no-buffer
```

Returns Server-Sent Events (SSE). Each event is a JSON object on a `data:` line:

```
data: {"type": "tool_start", "name": "web_search", "args": {...}}

data: {"type": "tool_result", "name": "web_search", "result": "..."}

data: {"type": "assistant_text", "text": "Here's what I found..."}

data: {"type": "response", "text": "Full response text", "tools_used": ["web_search"]}
```

### Request Fields

| Field | Type | Description |
|-------|------|-------------|
| `message` | string | User message text |
| `channel_id` | uuid | Target channel (preferred) |
| `bot_id` | string | Bot ID (default: `"default"`) |
| `client_id` | string | Client identifier (default: `"default"`) |
| `audio_data` | string | Base64-encoded audio (for voice input) |
| `audio_format` | string | Audio format: `m4a`, `wav`, `webm` |
| `attachments` | array | Vision attachments (images) |
| `dispatch_type` | string | `"slack"`, `"webhook"`, `"internal"`, `"none"` |
| `dispatch_config` | object | Routing config for the dispatch type |
| `model_override` | string | Per-turn model override |
| `passive` | bool | Store message without running agent |

### SSE Event Types

Events emitted during streaming:

| Event Type | Description | Key Fields |
|------------|-------------|------------|
| `assistant_text` | Incremental text from LLM | `text` |
| `tool_start` | Tool call beginning | `name`, `args` |
| `tool_result` | Tool call completed | `name`, `result`, `duration_ms`; failures also include `error_code`, `error_kind`, `retryable`, `retry_after_seconds`, and `fallback` when available |
| `response` | Final response (always last) | `text`, `tools_used`, `client_actions` |
| `thinking_content` | Extended thinking (Claude models) | `text` |
| `error` | Processing error | `message` |
| `cancelled` | User cancelled the run | — |
| `queued` | Message queued (session locked or system paused) | `session_id`, `task_id`, `reason` |
| `passive_stored` | Passive message stored | `session_id` |
| `secret_warning` | Secret-like patterns detected in input | `patterns` |
| `rate_limit_wait` | Waiting on LLM rate limit | `wait_seconds` |
| `fallback` | Fallback model activated | `original_model`, `fallback_model` |
| `context_budget` | Context window utilization | `used`, `limit` |
| `rag_rerank` | RAG results reranked | — |
| `delegation_post` | Delegated to another bot | `target_bot` |
| `approval_request` | Waiting for tool approval | `request_id`, `tool_name` |
| `approval_resolved` | Approval decision received | `request_id`, `approved` |
| `transcript` | Audio transcription result | `text` |

Context assembly events (prefixed with source type) are also emitted during streaming but are primarily for debugging — clients typically only need `assistant_text`, `tool_start`, `tool_result`, and `response`.

## LLM Completions API

A thin proxy that lets integrations make LLM calls through the server's multi-provider infrastructure without needing to know about provider URLs, API keys, or routing. Usage is recorded as a TraceEvent for cost tracking.

**Scope**: `llm:completions`

### Request

```bash
curl -X POST http://localhost:8000/api/v1/llm/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini/gemini-2.5-flash",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Summarize this text: ..."}
    ],
    "temperature": 0.7
  }'
```

### Request Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | No | Model ID (LiteLLM format). Defaults to `DEFAULT_MODEL`. |
| `messages` | array | Yes | OpenAI-format messages (`role` + `content`). |
| `temperature` | float | No | 0–2. |
| `max_tokens` | int | No | Max completion tokens. |
| `extra` | object | No | Provider-specific params passed through to the LLM call (e.g. Gemini `safety_settings`). |

### Response

```json
{
  "content": "Here is a summary...",
  "model": "gemini/gemini-2.5-flash",
  "usage": {
    "prompt_tokens": 42,
    "completion_tokens": 128,
    "total_tokens": 170
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `content` | string | LLM response text (empty string if model returned no content). |
| `model` | string | Actual model used. |
| `usage` | object \| null | Token counts (null if provider didn't report usage). |

### Notes

- The model is resolved through the server's provider system — the caller doesn't need to know which provider or API key to use.
- All calls are recorded as TraceEvents with caller identity, model, token counts, duration, and cost (when available from LiteLLM).
- Used by the ingestion pipeline's safety classifier and available to any integration with a scoped API key.

## Channel State, Widgets, and Dashboards

These endpoints support the chat rehydration flow, interactive widget actions, and widget dashboards — the user-facing surfaces documented in the [Chat History](chat-history.md), [Widget Dashboards](widget-dashboards.md), and [HTML Widgets](html-widgets.md) guides.

### Channel State Snapshot

`GET /api/v1/channels/{channel_id}/state`

Returns a point-in-time snapshot used to rehydrate the chat UI on reconnect: `{active_turns, pending_approvals}`. Active turns include any turn that started within the last 10 minutes and hasn't emitted a terminal `Message`. Pending approvals are the channel-scoped rows from `tool_approvals` that are still `awaiting_approval`, with any orphaned rows (no matching ToolCall) filtered out. Scope: `channels.messages:read`.

### Widget Actions

`POST /api/v1/widget-actions`

Dispatches an action emitted by an interactive widget (HTML or component). The body carries a `dispatch` field (`tool` | `api` | `widget_config`) and the payload each mode requires. Authorization is delegated to the dispatched target — tool calls go through the tool policy + approval pipeline, API proxying through the proxied endpoint's own `require_scopes`, and `widget_config` patches require ownership of the pin. See `app/routers/api_v1_widget_actions.py` for the exact schema.

`POST /api/v1/widget-actions/refresh`

Re-runs a pin's declared `state_poll` and returns the refreshed envelope. Same authorization shape as `/widget-actions`.

### Widget Dashboards

`GET /api/v1/widgets/dashboard?slug=<slug>`

Returns a dashboard (implicit channel dashboards use the slug shape `channel:<uuid>`). Response includes the dashboard row + its `widget_dashboard_pins` rows with `grid_layout` coordinates.

Additional endpoints under `/api/v1/widgets/dashboard` (see `app/routers/api_v1_dashboard.py`) cover: create/rename dashboards, CRUD pins, bulk `POST /pins/layout` to persist grid coordinates on drag-end, `PATCH /pins/{id}` for per-pin fields (display_label, widget_config, source_bot_id), and `DELETE /pins/{id}`.

### Widget Library

`GET /api/v1/widgets/library-widgets`

Returns reusable widget-library bundles across three scopes:

- `core`
- `bot`
- `workspace`

Without `bot_id`, only `core` is guaranteed. Supplying `?bot_id=<id>` lets the server resolve that bot's workspace roots and enumerate bot/workspace-authored bundles too. This is the endpoint that powers the dashboard add-sheet's **Library** tab.

### Panel-mode endpoints

`POST /api/v1/widgets/dashboard/pins/{pin_id}/promote-panel`

Marks a pin as the dashboard's main panel and flips the dashboard into panel mode.

`DELETE /api/v1/widgets/dashboard/pins/{pin_id}/promote-panel`

Clears `is_main_panel` from that pin. If no panel pin remains, the dashboard falls back to grid mode.

### Widget Auth (bot-scoped tokens)

`POST /api/v1/widget-auth/mint`

Described above in [Widget Tokens](#widget-tokens-short-lived-bot-scoped). Reserved for the widget renderer — clients don't normally call this directly.

### Favicon Proxy

`GET /api/v1/favicon?domain=<host>`

Thin server-side proxy that fetches a favicon for the given host. Used by widgets that render link cards (web_search, custom HTML dashboards) so cross-origin icon loads stay inside the CSP.

## Scratch sessions

These routes back the cross-device scratch-sub-session flow described in [Task Sub-Sessions](task-sub-sessions.md).

### Current scratch session

`GET /api/v1/sessions/scratch/current?parent_channel_id=<uuid>&bot_id=<bot>`

Resolves or spawns the authenticated user's current scratch session for a `(channel, user)` pair. Scope: `chat`.

### Reset scratch

`POST /api/v1/sessions/scratch/reset`

Archives the current scratch session for that `(channel, user)` pair and creates a fresh one. Scope: `chat`.

### Scratch history

`GET /api/v1/sessions/scratch/list?parent_channel_id=<uuid>`

Lists current + archived scratch sessions for the authenticated user/channel pair, newest first with the current scratch pinned to the top. Scope: `chat`.

## Browser Live admin endpoints

The `browser_live` integration also exposes a small operator surface outside `/api/v1/...`:

### Status

`GET /integrations/browser_live/admin/status`

Lists currently paired browser connections. Admin auth required.

### Rotate pairing token

`POST /integrations/browser_live/admin/token/rotate`

Generates a new global pairing token for the integration. Rotating the token disconnects existing paired browsers until they re-pair. Admin auth required.

## Admin status endpoints

These endpoints back operator dashboards and recent release-facing admin surfaces.

### Provider health

`GET /api/v1/admin/usage/provider-health`

Returns provider/model health and fallback state used by the admin usage/provider UI. Admin auth required.

### Refresh provider models now

`POST /api/v1/admin/providers/{provider_id}/refresh-now`

Triggers an immediate model-catalog refresh for one provider. Admin auth required.

### Memory Observatory

`GET /api/v1/admin/learning/memory-observatory`

Returns the spatial-canvas memory observatory payload: hot memory-file bodies, bot lanes, recent write activity, and search/inspection metadata. Admin auth required.

### Harness runtimes

`GET /api/v1/admin/harnesses`

Lists registered external-agent harness runtimes and their auth status. Used by `/admin/harnesses` to expose commands such as `claude login`. Admin auth required.

## Machine control endpoints

Machine control is a core subsystem with provider-backed admin APIs plus session lease APIs.

### List providers and targets

`GET /api/v1/admin/machines`

Lists machine-control providers with their enrolled targets and current connection state. Scope: `integrations:read`.

### Enroll target for a provider

`POST /api/v1/admin/machines/providers/{provider_id}/enroll`

Creates a new target enrollment through the selected provider and returns target metadata plus provider-specific launch details. Scope: `integrations:write`.

### Remove target for a provider

`DELETE /api/v1/admin/machines/providers/{provider_id}/targets/{target_id}`

Removes an enrolled target through the selected provider and clears any active session lease that still points at it. Scope: `integrations:write`.

### Session machine-target state

`GET /api/v1/sessions/{session_id}/machine-target`

Returns the current session's machine lease, if any, plus the visible target list.

### Grant lease

`POST /api/v1/sessions/{session_id}/machine-target/lease`

Grants the session a lease for one target after provider validation confirms it is ready. Body:

```json
{
  "provider_id": "local_companion",
  "target_id": "uuid",
  "ttl_seconds": 900
}
```

### Probe target

`POST /api/v1/admin/machines/providers/{provider_id}/targets/{target_id}/probe`

Refreshes cached readiness/status for one enrolled machine target.

### Revoke lease

`DELETE /api/v1/sessions/{session_id}/machine-target/lease`

Clears the active lease for that session.

### Local companion websocket

`WS /integrations/local_companion/ws?target_id=<id>&token=<token>`

Provider transport endpoint used by the paired local companion process after enrollment. This is not the machine-management API surface; it is the provider's live transport socket.

## Common Patterns

### Create a Channel and Send a Message

```python
import requests

BASE = "http://localhost:8000"
HEADERS = {"Authorization": "Bearer your-api-key"}

# 1. Create a channel
ch = requests.post(f"{BASE}/api/v1/admin/channels", headers=HEADERS, json={
    "name": "my-project",
    "bot_id": "default",
}).json()

channel_id = ch["id"]

# 2. Send a message (blocking)
resp = requests.post(f"{BASE}/chat", headers=HEADERS, json={
    "message": "Hello!",
    "channel_id": channel_id,
}).json()

print(resp["response"])
```

### Stream a Response (Python)

```python
import json
import requests

resp = requests.post(
    f"{BASE}/chat/stream",
    headers=HEADERS,
    json={"message": "Explain Docker", "channel_id": channel_id},
    stream=True,
)

for line in resp.iter_lines():
    if line and line.startswith(b"data: "):
        event = json.loads(line[6:])
        if event["type"] == "assistant_text":
            print(event["text"], end="", flush=True)
        elif event["type"] == "response":
            print()  # final newline
```

## Python Client

The `agent` CLI can also be used as a library:

```bash
cd client && pip install -e .
```

```python
from agent.client import AgentClient

client = AgentClient(base_url="http://localhost:8000", api_key="your-key")
response = client.chat("Hello!", bot_id="default")
print(response.text)
```

## CORS

To allow browser-based clients, set `CORS_ORIGINS` in your `.env`:

```
CORS_ORIGINS=http://localhost:3000,https://my-dashboard.example.com
```

## Rate Limiting

!!! note "This limits requests to the Spindrel API itself"
    These limits control how fast clients can call **your Spindrel server**. They do **not** affect outbound calls to LLM providers (OpenAI, Anthropic, etc.) — those have their own rate limits handled by the agent's retry/backoff logic.

Opt-in rate limiting protects against runaway clients hammering your server. Enable in `.env`:

```
RATE_LIMIT_ENABLED=true
RATE_LIMIT_DEFAULT=100/minute    # all Spindrel API endpoints
RATE_LIMIT_CHAT=30/minute        # /chat and /chat/stream (stricter)
```

When rate-limited, the server returns HTTP 429 with a `Retry-After` header.

Limits are per API key (or per client IP if no key is provided). The rate limiter uses an in-memory token bucket — limits reset on server restart. You can also configure these at runtime from **Settings > API Rate Limiting** in the admin UI.

## Error Handling

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 401 | Missing or invalid API key |
| 403 | Insufficient scopes for this endpoint |
| 404 | Resource not found |
| 409 | Conflict (e.g., session locked) |
| 422 | Validation error (check `detail` field) |
| 429 | Rate limited (check `Retry-After` header) |
| 500 | Server error |

Error responses follow this format:

```json
{
  "detail": "Human-readable error message"
}
```

Validation errors (422) include field-level details:

```json
{
  "detail": [
    {"loc": ["body", "message"], "msg": "field required", "type": "value_error.missing"}
  ]
}
```

Bot-facing tool errors keep a top-level `error` string for compatibility and
add the shared agent error contract when possible:

```json
{
  "error": "HTTP 429",
  "error_code": "http_429",
  "error_kind": "rate_limited",
  "retryable": true,
  "retry_after_seconds": 12,
  "fallback": "Wait for retry_after_seconds when provided, then retry with backoff."
}
```

The contract is published in `/api/v1/agent-capabilities` under
`tool_error_contract`. `/api/v1/tool-calls` exposes the persisted fields and
can filter by `error_kind` or `retryable`. `/api/v1/agent-status` and
`/api/v1/agent-activity` include the same fields on run/replay items whose
source has structured error evidence.
Mission Control Review consumes the same fields to suppress one-off benign
setup/input failures, keep repeated benign failures as low-priority findings,
and distinguish retryable outages from platform/tool bugs.
