# Integration System Design

This document captures the architectural decisions, design philosophy, known issues, and
remaining debt for the integration layer. It exists so future Claude sessions and contributors
don't re-litigate these decisions or re-introduce the same slop.

---

## Core Boundary

**`/app` is core. `/integrations` (root-level) is extending code.**

| Belongs in `/app` | Belongs in `/integrations` |
|---|---|
| Agent loop, RAG, tool system | Slack Bolt app, channel config logic |
| Task worker, scheduler | Slack-specific message formatting |
| Dispatcher registry + core dispatchers | Integration-specific dispatchers |
| DB models (generic) | Integration-specific config tables |
| `/api/v1/` public REST API | `/integrations/<name>/` routers |

**Rule**: `/app` must not import from `/integrations`. `/app` must not contain integration
brand names (like "slack") in business logic. The word "slack" is allowed only in:
- `app/config.py` — `SLACK_BOT_TOKEN`/`SLACK_DEFAULT_BOT` env var config (used by admin)

---

## Dispatcher Registry

Dispatchers answer one question: **"Given a completed task result, where and how do I send it?"**

### How it works

`app/agent/dispatchers.py` is the registry:

```python
from app.agent.dispatchers import register, get

# Register a dispatcher for a dispatch_type
register("mytype", MyDispatcher())

# Look up a dispatcher (falls back to "none" if unknown)
dispatcher = get(task.dispatch_type)
await dispatcher.deliver(task, result_text, client_actions=...)
```

`tasks.py` uses `dispatchers.get()` — it has no knowledge of individual dispatchers.

### Core dispatchers (always available)

Registered in `app/agent/dispatchers.py` at import time:

| `dispatch_type` | Class | Behavior |
|---|---|---|
| `"none"` | `_NoneDispatcher` | Result stays in DB only; caller polls `get_task` |
| `"webhook"` | `_WebhookDispatcher` | HTTP POST `{task_id, result}` to `dispatch_config.url` |
| `"internal"` | `_InternalDispatcher` | Injects result into a parent session as a user message |

### Integration dispatchers (pluggable)

An integration registers its dispatcher by placing `dispatcher.py` in its folder.
`integrations/__init__.py` auto-imports it during `discover_integrations()`.

```
integrations/
└── slack/
    └── dispatcher.py   ← calls register("slack", SlackDispatcher()) at import time
```

The `SlackDispatcher` handles `chat.postMessage` + file uploads for the task path.
It is allowed to know about Slack — it's explicitly scoped to `dispatch_type="slack"`.
All its HTTP calls go through `integrations/slack/client.py` (for messages) and
`integrations/slack/uploads.py` (for files).

---

## Hook Registry

Hooks answer two questions: **"What metadata does this integration provide?"** and
**"What should happen when the agent does X?"**

### How it works

`app/agent/hooks.py` has two registries:

**Registry A — Integration metadata** (keyed by integration type):

```python
from app.agent.hooks import IntegrationMeta, register_integration

register_integration(IntegrationMeta(
    integration_type="slack",
    client_id_prefix="slack:",
    user_attribution=_user_attribution,       # returns {username, icon_emoji, icon_url}
    resolve_display_names=_resolve_display_names,  # returns {channel_id: "#name"}
))
```

Core code queries this registry dynamically instead of hardcoding integration-specific
logic. For example, `app/services/channels.py:is_integration_client_id()` calls
`get_all_client_id_prefixes()` instead of maintaining a hardcoded tuple.

**Registry B — Lifecycle hooks** (broadcast, fire-and-forget):

```python
from app.agent.hooks import HookContext, register_hook, fire_hook

register_hook("after_tool_call", my_callback)

# Core fires the event (in loop.py, context_assembly.py, etc.)
await fire_hook("after_tool_call", HookContext(bot_id=bot_id, extra={...}))
```

Events: `after_tool_call`, `after_response`, `before_context_assembly`. All errors
are swallowed and logged. Both sync and async callbacks work. Hooks run via
`asyncio.create_task` so they don't block the agent loop.

### What hooks replaced

Three places in core had hardcoded Slack imports:
- `app/routers/chat.py` — user attribution for message mirroring → now uses `get_user_attribution()`
- `app/services/channels.py` — client ID prefix detection → now uses `get_all_client_id_prefixes()`
- `app/routers/api_v1_admin/channels.py` — display name resolution → now uses `resolve_all_display_names()`

### Example: Slack hooks (`integrations/slack/hooks.py`)

Registers metadata (prefix, user attribution, channel name resolution) and
subscribes to lifecycle events:
- `after_tool_call` — adds emoji reactions on Slack messages (hourglass + tool-specific emoji)
- `after_tool_call` — posts tool usage to an audit channel (configured via `/audit` slash command)
- `after_response` — removes hourglass, adds checkmark

---

## Integration Process Discovery

Integrations that need a background process (e.g. Slack Bolt runs as a separate Python
process in socket mode) declare it in `process.py`:

```python
# integrations/slack/process.py
DESCRIPTION = "Slack Bolt bot (socket mode)"
CMD = ["python", "integrations/slack/slack_bot.py"]
REQUIRED_ENV = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]
```

`integrations/__init__.py` exposes `discover_processes()` which returns only processes
whose `REQUIRED_ENV` vars are all set. `scripts/dev-server.sh` calls
`scripts/list_integration_processes.py` to auto-start all declared processes:

```bash
# In dev-server.sh — no hardcoded integration names
while IFS= read -r cmd; do
    [[ "$cmd" == \#* ]] && continue
    eval "$cmd" &
    PIDS+=($!)
done < <(python scripts/list_integration_processes.py)
```

---

## `integrations/slack/client.py` and `integrations/slack/uploads.py`

All Slack HTTP calls live in `integrations/slack/`:

- **`client.py`** — `post_message()` and `bot_attribution()`: single source of truth for
  `chat.postMessage`. Used by `SlackDispatcher.deliver()`, `SlackDispatcher.post_message()`,
  and indirectly by `_fanout()` and `delegation.post_child_response()` via the dispatcher registry.
- **`uploads.py`** — file upload flow (files.getUploadURLExternal → upload →
  completeUploadExternal). Called by `SlackDispatcher.deliver()`.

**Known bug that was fixed**: `files.getUploadURLExternal` requires form-encoded body
(`data=`), NOT JSON (`json=`). Using `json=` silently fails with `missing_filename`.

---

## Bot Display Config

Bots have a **generic** display identity usable by any integration:

| Column | Purpose |
|---|---|
| `display_name` | How the bot signs its messages ("Aria", "DevBot") |
| `avatar_url` | URL to the bot's profile image (any integration can use this) |

**Slack emoji shortcodes** (`:robot_face:`) are Slack-specific. They live in
`Bot.integration_config JSONB` under `{"slack": {"icon_emoji": ":robot_face:"}}`.

The admin UI's bot edit page has a Slack subsection under Display for `icon_emoji`.

---

## `dispatch_config` JSONB

`dispatch_config` on `Task` holds the **delivery target** only — where to send the result:

```json
// Slack
{"channel_id": "C123", "token": "xoxb-...", "thread_ts": "1234.56", "reply_in_thread": true}

// Webhook
{"url": "https://example.com/hook"}

// Internal
{"session_id": "uuid"}
```

**What does NOT belong in `dispatch_config`** (resolved):

- Delegation bookkeeping (`notify_parent`, `parent_session_id`, `parent_bot_id`,
  `parent_client_id`) — moved to `Task.callback_config` JSONB (migrations 039+040).

- Webhook prompt injection (`system_preamble`, `skills`, `tools`) — lives in
  `Task.execution_config` JSONB. Set by integrations via `inject_message(execution_config=...)`.
  See [Creating an Integration](index.md#webhook-prompt-injection-execution_config) for details.

---

## Channel Config — Single Source of Truth

**Use `Channel` (`channels` table, migration 043).** `IntegrationChannelConfig` is a legacy
table kept for backwards compatibility but no longer read by core code.

| Column | Purpose |
|---|---|
| `id` | UUID primary key (derived from `client_id` via `derive_channel_id()`) |
| `client_id` | Format: `"slack:C123456"` |
| `integration` | `"slack"` (allows future: `"teams"`, `"discord"`) |
| `bot_id` | Which bot handles this channel |
| `require_mention` | Whether bot needs `@mention` to respond |
| `passive_memory` | Whether bot silently reads all messages for memory |
| `dispatch_config` | JSONB delivery target (channel_id, token, thread_ts) |

The Slack integration reads channel config via `/integrations/slack/config` (60s TTL cache),
served by `integrations/slack/router.py`. It does NOT query the DB directly.

---

## Integration Debt — Resolved

All known integration boundary violations have been resolved. Key completed items:

- Dispatcher registry is pluggable — `app/agent/dispatchers.py` + integration-level `dispatcher.py`
- Hook registry is pluggable — `app/agent/hooks.py` + integration-level `hooks.py`
- All Slack HTTP calls consolidated in `integrations/slack/`
- No `from integrations.slack` imports remain in `app/` — user attribution, client ID prefixes, and display name resolution all go through the hook registry
- Bot display config uses generic `display_name`/`avatar_url` (Slack-specific in `integration_config` JSONB)
- `dispatch_config` on Task is delivery-only; orchestration state lives in `callback_config`
- Channel config reads from `channels` table (single source of truth)

---

## External Integrations (Plugin Model)

Integrations can live **outside** the agent-server repo. Set `INTEGRATION_DIRS` (colon-separated
paths) in `.env` to point to directories containing integration folders. Each directory is
scanned the same way as the in-repo `integrations/` — any subfolder with `router.py`,
`dispatcher.py`, `tools/*.py`, `skills/*.md`, or `process.py` is auto-discovered.

This enables:
- **Private integrations** — keep personal/proprietary integrations in a separate repo
- **Shared plugins** — publish reusable integrations independently
- **Clean separation** — the agent-server repo ships only core integrations (slack, example)

For Docker deployments, mount external integration directories as volumes and set
`INTEGRATION_DIRS` to the mount path. See [Creating an Integration](index.md) for examples.

---

## Things That Are Fine — Don't Touch

- Agent loop (`app/agent/loop.py`) — clean, no integration coupling
- RAG system — clean
- Tool registry + discovery — clean
- Delegation framework (`app/services/delegation.py`) — clean, routes through dispatcher registry
- Provider abstraction — clean
- `/api/v1/` public API — reasonable
- `app/agent/dispatchers.py` — clean registry pattern
- `app/agent/hooks.py` — clean registry pattern (metadata + lifecycle)
