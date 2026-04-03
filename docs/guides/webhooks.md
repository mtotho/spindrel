# Webhooks

Spindrel can POST signed JSON payloads to your endpoints on key lifecycle events — LLM calls, tool executions, agent responses, task completions, and more. Use these for monitoring, cost analytics, audit logging, and alerting.

## Setup

1. Go to **Admin > Developer > Webhooks**
2. Click **New Webhook**
3. Enter a name, URL, and optionally select which events to subscribe to
4. Click **Save** — copy the signing secret immediately (it's shown only once)
5. Use the **Send Test Event** button to verify your endpoint receives payloads

Each webhook endpoint has its own signing secret for HMAC verification, event filtering, delivery tracking with retry, and an active/inactive toggle.

## Payload Format

Every webhook delivery includes these headers:

| Header | Value |
|--------|-------|
| `Content-Type` | `application/json` |
| `X-Spindrel-Signature` | `sha256=<HMAC-SHA256 hex digest>` |
| `X-Spindrel-Event` | Event name (e.g. `after_llm_call`) |

The JSON body has this structure:

```json
{
  "event": "after_llm_call",
  "timestamp": "2026-04-03T14:30:00.123456+00:00",
  "context": {
    "bot_id": "default",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "channel_id": "660e8400-e29b-41d4-a716-446655440000",
    "client_id": "slack:C01234567",
    "correlation_id": null
  },
  "data": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event` | string | Event name (see table below) |
| `timestamp` | string | ISO 8601 UTC timestamp |
| `context.bot_id` | string | Bot that triggered the event |
| `context.session_id` | string\|null | Active session UUID |
| `context.channel_id` | string\|null | Channel UUID |
| `context.client_id` | string\|null | Integration client ID (e.g. `slack:C01234567`) |
| `context.correlation_id` | string\|null | Task/workflow correlation ID |
| `data` | object | Event-specific fields (see below) |

## Signature Verification

Every payload is signed with HMAC-SHA256 using your endpoint's secret. Verify the `X-Spindrel-Signature` header to ensure payloads are authentic.

### Python

```python
import hashlib
import hmac

def verify_signature(body: bytes, secret: str, signature_header: str) -> bool:
    """Verify a Spindrel webhook signature."""
    # Header format: "sha256=<hex digest>"
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

### Node.js

```javascript
const crypto = require("crypto");

function verifySignature(body, secret, signatureHeader) {
  const expected =
    "sha256=" +
    crypto.createHmac("sha256", secret).update(body).digest("hex");
  return crypto.timingSafeEqual(
    Buffer.from(expected),
    Buffer.from(signatureHeader)
  );
}
```

## Event Types

| Event | When It Fires | `data` Fields |
|-------|---------------|---------------|
| `before_context_assembly` | Before assembling LLM context | `user_message` |
| `before_llm_call` | Before each LLM API call | `model`, `message_count`, `tools_count`, `provider_id`, `iteration` |
| `after_llm_call` | After each LLM API call | `model`, `duration_ms`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `tool_calls_count`, `fallback_used`, `fallback_model`, `iteration`, `provider_id` |
| `before_tool_execution` | Before a tool executes | `tool_name`, `tool_type`, `args`, `iteration` |
| `after_tool_call` | After a tool completes | `tool_name`, `tool_args`, `duration_ms` |
| `after_response` | After agent produces final response | `response_length`, `tool_calls_made` (or `error: true` on failure) |
| `after_task_complete` | After a scheduled/deferred task finishes | `task_id`, `task_type`, `status` |
| `after_workflow_step` | After a workflow step completes | `workflow_id`, `run_id`, `step_index` |
| `before_transcription` | Before audio transcription | `audio_format`, `audio_size_bytes` |

## Retry Behavior

Failed deliveries (5xx responses or connection errors) are retried up to 3 times:

| Attempt | Delay |
|---------|-------|
| 1 | Immediate |
| 2 | 30 seconds |
| 3 | 120 seconds |

4xx responses (client errors) are **not** retried — they indicate a problem with the receiver.

All delivery attempts are recorded in the delivery log, visible in the admin UI under each webhook endpoint.

## Delivery Log

Each endpoint tracks delivery history including:
- Event name
- HTTP status code (or error message)
- Number of attempts
- Response time in milliseconds
- Response body (first 1KB)

View the delivery log in **Admin > Developer > Webhooks > [endpoint] > Recent Deliveries**. Old deliveries are automatically cleaned up by the data retention system.

## Use Cases

**Latency monitoring** — Track `after_llm_call` → `duration_ms` to detect slow providers.

**Cost analytics** — Aggregate `after_llm_call` → `prompt_tokens` + `completion_tokens` by `model` and `bot_id`.

**Tool audit** — Log `after_tool_call` events to track which tools bots use and how long they take.

**Fallback alerting** — Monitor `after_llm_call` → `fallback_used` to detect primary model failures.

**Task monitoring** — Track `after_task_complete` → `status` to alert on failed scheduled tasks.

## Migration from HOOK_WEBHOOK_URLS

The old `HOOK_WEBHOOK_URLS` environment variable has been replaced by the DB-backed webhook system. To migrate:

1. Create a webhook endpoint in the admin UI for each URL you had configured
2. Copy the signing secret and update your receiver to verify signatures
3. Remove `HOOK_WEBHOOK_URLS` from your `.env` file
