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

Spindrel defines **49 scopes** across **18 groups**:

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
| **Usage** | `usage:read` | Cost analytics and usage limits |
| **Carapaces** | `carapaces:read`, `carapaces:write` | Skill+tool bundle management |
| **Workflows** | `workflows:read`, `workflows:write` | Workflow definitions and run management |
| **Mission Control** | `mission_control:read`, `mission_control:write` | Dashboard data (kanban, journal, etc.) |

**Hierarchy rules**: `channels:write` implies all `channels.*:write` sub-scopes. `admin` implies everything.

#### Presets

The admin UI offers one-click presets for common use cases:

| Preset | Use Case | Key Scopes |
|--------|----------|------------|
| **Messaging Integration** | Slack, Discord, etc. | `chat`, `channels:read/write`, `sessions:read/write` |
| **Chat Client** | Custom chat frontends | `chat`, `channels:read/write`, `attachments:read/write` |
| **Workspace Bot** | Bots in containers | `chat`, `tasks:read/write`, `tools:read/execute`, `workspaces.files:read/write` |
| **Read-Only Monitor** | Dashboards | `bots:read`, `channels:read`, `logs:read`, `tasks:read` |
| **Mission Control** | MC dashboard | `channels:read`, `tasks:read/write`, `mission_control:read/write` |

### JWT (User Authentication)

The UI uses JWT tokens via Google OAuth. For API access, scoped keys are preferred.

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
