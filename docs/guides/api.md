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

Spindrel defines **51 scopes** across **22 groups**:

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
| **Knowledge** | `knowledge:read`, `knowledge:write` | Bot knowledge entries (deprecated — prefer workspace files) |
| **Todos** | `todos:read`, `todos:write` | Persistent work items |
| **Attachments** | `attachments:read`, `attachments:write` | File attachment management |
| **Logs** | `logs:read`, `logs:write` | Agent turns, tool calls, traces, server logs |
| **Tools** | `tools:read`, `tools:execute` | Tool listing and direct execution |
| **Providers** | `providers:read`, `providers:write` | LLM provider configuration |
| **Users** | `users:read`, `users:write` | User management |
| **Settings** | `settings:read`, `settings:write` | Server-wide settings |
| **Operations** | `operations:read`, `operations:write` | Backups, git pull, restart |
| **Usage** | `usage:read` | Cost analytics and usage limits |
| **Workflows** | `workflows:read`, `workflows:write` | Deprecated workflow routes (see [Pipelines](pipelines.md)). Scope retained for historical API compatibility. |
| **LLM** | `llm:completions` | Direct LLM calls through the server's provider system |
| **Mission Control** | `mission_control:read`, `mission_control:write` | Dashboard data (kanban, journal, etc.) |

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
| **Mission Control** | MC dashboard | `bots:read`, `channels:read`, `sessions:read`, `tasks:read/write`, `todos:read/write`, `workspaces:read`, `workspaces.files:read/write`, `attachments:read`, `logs:read`, `mission_control:read/write` |

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

The basic response includes method, path, description, and required scope for each endpoint.

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
| `tool_result` | Tool call completed | `name`, `result`, `duration_ms` |
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

## Local Companion endpoints

The `local_companion` integration exposes both operator endpoints and session lease endpoints.

### Admin status

`GET /integrations/local_companion/admin/status`

Lists enrolled machine targets plus live connection state. Admin auth required.

### Enroll target

`POST /integrations/local_companion/admin/enroll`

Creates a new companion target enrollment and returns the target metadata, token, websocket path, and example launch command. Admin auth required.

### Revoke target

`DELETE /integrations/local_companion/admin/targets/{target_id}`

Removes an enrolled target and clears any active session lease that still points at it. Admin auth required.

### Session machine-target state

`GET /api/v1/sessions/{session_id}/machine-target`

Returns the current session's machine lease, if any, plus the visible target list.

### Grant lease

`POST /api/v1/sessions/{session_id}/machine-target/lease`

Grants the session a lease for one connected target. Body:

```json
{
  "target_id": "uuid",
  "ttl_seconds": 900
}
```

### Revoke lease

`DELETE /api/v1/sessions/{session_id}/machine-target/lease`

Clears the active lease for that session.

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
