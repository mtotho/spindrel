# Integration System Design

This document captures the architectural decisions, design philosophy, known issues, and
remaining debt for the integration layer. It exists so future Claude sessions and contributors
don't re-litigate these decisions or re-introduce the same slop.

---

## Channel Binding Model

**Channels are Spindrel's primary object. Integrations are clients of the channel — not owners.**

Every channel may have zero, one, or many integration bindings. Bindings are stored as `ChannelIntegration` rows. The canonical resolver is:

```python
from app.services.dispatch_resolution import resolve_targets
targets: list[tuple[str, DispatchTarget]] = await resolve_targets(channel)
```

The legacy `Channel.client_id` / `Channel.integration` fields are 1:1 holdovers from the pre-multi-binding era. **Never** branch capability decisions on a single integration id derived from those fields — on a multi-bound channel (`slack` + default web is the common shape) that shortcut will silently pick whichever legacy field happens to be set and produce random per-environment behavior.

**Three hard rules** fall out of the binding model:

1. **Capabilities live on the binding.** `renderer.capabilities` is a frozenset per registered renderer. "What can this channel do" = union of `renderer.capabilities` across `resolve_targets(channel)`. Never treat capability as a property of the channel.
2. **Private / directed delivery is strict-scoped to one binding.** Events like `EPHEMERAL_MESSAGE` carry a `target_integration_id`; the dispatcher in `app/services/channel_renderers.py:IntegrationDispatcherTask._dispatch` silently drops the event on every other renderer. For durable delivery, `app/services/outbox_publish.py:enqueue_new_message_for_target` scopes a `NEW_MESSAGE` to one binding via the outbox row's `target_integration_id` column. If no binding can honor a directed tool call, the tool returns `unsupported` and the agent falls back to conversational Q&A. Do not broadcast as a fallback — that leaks content.
3. **Tool exposure is declaratively capability/integration-gated.** Tools declare what they need:

   ```python
   @register({...}, required_capabilities=frozenset({Capability.EPHEMERAL}))
   async def respond_privately(...): ...

   @register({...}, required_integrations=frozenset({"slack"}))
   async def slack_pin_message(...): ...
   ```

   `app/agent/capability_gate.py:build_view` assembles a `ChannelCapabilityView` from the bound renderers; `app/agent/context_assembly.py` filters the per-turn tool list so the LLM never sees tools the channel cannot honor. An unsupported tool cannot be called — the failure mode is "the tool isn't there", not "the tool errors at invocation time".

**When building a new integration feature**, the wrong model sounds like "if the channel is a Slack channel, do X" (singular integration check). The right model is "for each binding with `Capability.X`, deliver Y" — or equivalently, "if `renderer_registry.get(integration_id).capabilities` supports X, publish with `target_integration_id = integration_id`". Grep for `Channel.client_id.split(":"` in any new code — that pattern is always the wrong answer for capability decisions.

---

## Core Boundary

**`/app` is core. `/integrations` (root-level) is extending code.**

| Belongs in `/app` | Belongs in `/integrations` |
|---|---|
| Agent loop, RAG, tool system | Slack Bolt app, channel config logic |
| Task worker, scheduler | Slack-specific message formatting |
| Renderer registry + outbox drainer | Integration-specific renderers |
| DB models (generic) | Integration-specific config tables |
| `/api/v1/` public REST API | `/integrations/<name>/` routers |

**Rule**: `/app` must not import from `/integrations`. `/app` must not contain integration
brand names (like "slack") in business logic. The word "slack" is allowed only in:
- `app/config.py` — `SLACK_BOT_TOKEN`/`SLACK_DEFAULT_BOT` env var config (used by admin)

---

## Message Ingest Contract

When an integration receives a human-authored message and submits it to the
agent, it MUST pass the raw user text in `content` and put all routing,
identity, and platform-native data (mention tokens, channel ids, thread
summaries, etc.) in `msg_metadata`. The assembly layer composes the LLM's
`[Name]:` / `[Name (<@U…>)]:` prefix from metadata and injects
`thread_context` as a system block — integrations that bake their own
prefix into content cause double attribution, UI-regex arms races, and
drift from what the human actually said.

Full rule + worked examples for Slack / Discord / BlueBubbles:
**[Message Ingest Contract](message-ingest-contract.md)**.

The canonical metadata shape is
`app/routers/chat/_schemas.IngestMessageMetadata`; the composers live in
`app/agent/message_formatting.py`.

---

## Renderer Registry (Message Delivery)

Renderers answer one question: **"Given a channel event, how do I deliver it to the external service?"**

### How it works

`app/integrations/renderer_registry.py` is the registry. Integrations register their
renderer in `renderer.py`, which is auto-imported by `integrations/__init__.py`:

```python
from integrations.sdk import (
    ChannelRenderer, DeliveryReceipt, Capability,
    ChannelEvent, ChannelEventKind, DispatchTarget,
    renderer_registry,
)

class SlackRenderer(ChannelRenderer):
    integration_id = "slack"
    capabilities = frozenset({Capability.TEXT, Capability.RICH_TEXT, Capability.STREAMING_EDIT})

    async def render(
        self, event: ChannelEvent, target: DispatchTarget,
    ) -> DeliveryReceipt:
        # Handle NEW_MESSAGE (durable) and streaming events (best-effort)
        ...

renderer_registry.register(SlackRenderer())
```

### Core renderers (always available)

Registered in `app/integrations/core_renderers.py`:

| `dispatch_type` | Behavior |
|---|---|
| `"none"` | Result stays in DB only; caller polls `get_task` |
| `"webhook"` | HTTP POST event payload to `dispatch_config.url` |
| `"internal"` | Injects result into a parent session as a user message |
| `"web"` | Delivers to the web UI via SSE/WebSocket |

### Outbox durability

Events are not delivered directly. Instead, the channel-events bus publishes typed
`ChannelEvent` objects to the **outbox** (`app/services/outbox.py`). A background
**drainer** (`app/services/outbox_drainer.py`) pulls rows, routes through the renderer
registry, and handles retries:

- State machine: `pending` → `in_flight` → `delivered` (or `dead_letter` after 10 attempts)
- Only events matching the renderer's `CAPABILITIES` are delivered
- Capabilities declared in `integration.yaml` override the renderer's ClassVar

### Delivery Contract: Streaming vs. Durable

Channel events split into two delivery paths with different guarantees:

| Path | Events | Transport | Guarantees |
|------|--------|-----------|------------|
| **Durable** | `NEW_MESSAGE` | Outbox drainer | Retried on failure, dead-letter after 10 attempts. The message is always delivered. |
| **Ephemeral** | `TURN_STARTED`, `TURN_STREAM_TOKEN`, `TURN_STREAM_TOOL_START`, `TURN_STREAM_TOOL_RESULT`, `TURN_ENDED` | Channel-events bus | Best-effort. If missed, nothing retries. |

**`NEW_MESSAGE` is the sole durable delivery path.** This is the most important rule
for renderer authors. The outbox guarantees that every persisted assistant message
reaches every bound integration — if the renderer returns `DeliveryReceipt.failed(retryable=True)`,
the drainer retries. If it returns `.ok()` or `.skipped()`, the row is marked delivered.

**Streaming events are for progressive UX only.** Integrations that support real-time
updates (e.g. Slack's "thinking..." placeholder) can subscribe to streaming events to
provide a richer experience, but these events are inherently lossy:

- `TURN_STARTED` — post a "thinking..." placeholder (best-effort)
- `TURN_STREAM_TOKEN` — update the placeholder with accumulated text (best-effort)
- `TURN_ENDED` — finalize the placeholder with the complete response text (best-effort)

If any streaming event fails (API error, rate limit, process crash), the message is
not lost — `NEW_MESSAGE` delivers it durably via the outbox.

**Anti-pattern: relying on `TURN_ENDED` for delivery.** Do not post new messages from
`TURN_ENDED`. Its job is updating an existing placeholder. If you need to post the
final message, that's `NEW_MESSAGE`'s responsibility. The Slack renderer learned this
the hard way — when `TURN_ENDED` was responsible for delivery and the outbox was told
to skip, messages were silently lost on any transient failure.

#### DeliveryReceipt semantics

| Receipt | When to use | Outbox behavior |
|---------|-------------|-----------------|
| `.ok(external_id=...)` | Delivery succeeded. `external_id` is the external message ID (e.g. Slack `ts`). | Row marked `DELIVERED`. |
| `.skipped(reason)` | Renderer intentionally chose not to deliver (echo prevention, unsupported kind, etc.). | Row marked `DELIVERED` with reason logged. |
| `.failed(error, retryable=True)` | Transient failure (5xx, 429, network error). | Row retried (up to 10 attempts), then `DEAD_LETTER`. |
| `.failed(error, retryable=False)` | Permanent failure (invalid auth, channel not found). | Row immediately `DEAD_LETTER`. |

#### Placeholder handoff pattern (optional, for streaming integrations)

Integrations that support streaming edits (e.g. Slack `chat.update`) can implement
the placeholder handoff:

1. `TURN_STARTED` → post a placeholder message, store its ID in a turn context
2. `TURN_STREAM_TOKEN` → update the placeholder with accumulated text (debounced)
3. `TURN_ENDED` → finalize the placeholder with the complete response (best-effort update only)
4. `NEW_MESSAGE` → if a placeholder exists for this turn (via `msg.correlation_id`),
   update it with the final text (idempotent). Otherwise post as a new message.
   Post overflow chunks and tool blocks. Clean up the turn context.

The key: `NEW_MESSAGE` owns the final state. If `TURN_ENDED` already updated the
placeholder, `NEW_MESSAGE`'s update is idempotent. If `TURN_ENDED` failed, `NEW_MESSAGE`
still delivers the message. No message is ever lost.

### Which base class?

| Use case | Base class | Import |
|----------|-----------|--------|
| Most integrations (no streaming) | `SimpleRenderer` | `from integrations.sdk import SimpleRenderer` |
| Streaming (thinking placeholders, live token updates) | `ChannelRenderer` Protocol | `from integrations.sdk import ChannelRenderer` |

**`SimpleRenderer`** (recommended for new integrations): encodes the delivery contract
automatically. You implement `send_text(target, text) -> bool` and optionally
`send_error()`. The base class handles:

- `NEW_MESSAGE` → echo prevention + role filtering + calls `send_text()`
- `TURN_ENDED` → no-op (non-streaming renderers have no placeholder to finalize)
- `handle_outbound_action` → skipped by default (override to support uploads)
- `delete_attachment` → `False` by default

**`ChannelRenderer` Protocol** (Slack, Discord, or any integration with live editing):
full control. You handle all event kinds yourself. Must follow the delivery contract
manually — see the [Anti-pattern](#delivery-contract-streaming-vs-durable) above.

### Target Registry (Typed Dispatch Targets)

Each renderer receives events with a typed **target** — a frozen dataclass describing
where to deliver. Targets are registered in `app/domain/target_registry.py`.

Integrations can declare targets in `integration.yaml` (auto-generates a dataclass)
or in `target.py` (for custom logic):

```yaml
# integration.yaml — auto-generates SlackTarget
target:
  type: slack
  fields:
    channel_id: string
    token: string
    thread_ts: string?
```

```python
# target.py — manual registration
from integrations.sdk import BaseTarget, target_registry

class SlackTarget(BaseTarget, dispatch_type="slack"):
    channel_id: str
    token: str
    thread_ts: str | None = None

target_registry.register(SlackTarget)
```

### Historical: Dispatcher Registry (removed)

The dispatcher registry (`app/agent/dispatchers.py`) was the original delivery mechanism.
It was replaced by the renderer + outbox system in the Integration Delivery Layer Refactor
(Phases A-G, completed 2026-04-11). The module has been deleted; integrations no longer
need `dispatcher.py` files.

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
process in socket mode) declare it in `integration.yaml` (preferred) or `process.py`:

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

- Renderer registry is pluggable — `app/integrations/renderer_registry.py` + integration-level `renderer.py`
- Hook registry is pluggable — `app/agent/hooks.py` + integration-level `hooks.py`
- All Slack HTTP calls consolidated in `integrations/slack/`
- No `from integrations.slack` imports remain in `app/` — user attribution, client ID prefixes, and display name resolution all go through the hook registry
- Bot display config uses generic `display_name`/`avatar_url` (Slack-specific in `integration_config` JSONB)
- `dispatch_config` on Task is delivery-only; orchestration state lives in `callback_config`
- Channel config reads from `channels` table (single source of truth)

---

## External Integrations (Plugin Model)

Integrations can live **outside** the Spindrel repo. Set `INTEGRATION_DIRS` (colon-separated
paths) in `.env` to point to directories containing integration folders. Each directory is
scanned the same way as the in-repo `integrations/` — any subfolder with `router.py`,
`tools/*.py`, `skills/*.md`, `integration.yaml`, or `process.py` is auto-discovered.

This enables:
- **Private integrations** — keep personal/proprietary integrations in a separate repo
- **Shared plugins** — publish reusable integrations independently
- **Clean separation** — the Spindrel repo ships only core integrations (slack, example)

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
- `app/integrations/renderer_registry.py` — clean registry pattern (replaced dispatchers)
- `app/agent/hooks.py` — clean registry pattern (metadata + lifecycle)
