# Integration Layer — Debt Paydown Plan

This document explains the remaining technical debt in the integration layer: what the current
code does, why it's a problem, what the fix achieves, and how to implement it. Ordered by
impact.

---

## 1. Consolidate `_post_to_slack()` into `app/services/slack_client.py`

### How it works now

There are **three independent implementations** of `chat.postMessage`:

| Location | Used for | What it does |
|---|---|---|
| `app/services/delegation.py` — `DelegationService._post_to_slack()` | Immediate delegation — child bot posts to Slack inline during a streaming turn | Full bot attribution (username, icon_emoji, icon_url from `bot.integration_config`) |
| `integrations/slack/dispatcher.py` — `SlackDispatcher.deliver()` | Task worker — delivers completed task result to Slack | Full bot attribution + image uploads via `slack_uploads.py` |
| `app/routers/api_v1_sessions.py` — `_post_to_slack()` + `_fanout()` | API v1 message injection fan-out — notifies Slack when a message is injected externally | Plain text only, no attribution |

All three use a module-level `httpx.AsyncClient`. The delegation one is particularly subtle:
it uses a 60s timeout (because it may fire during a long streaming turn) while the others use
shorter timeouts. The api_v1 one doesn't pass bot attribution at all — it just posts raw text.

### Why it's a problem

- **Divergence**: Bug fixes (e.g. error handling, retry logic) have to be applied in three places.
- **No attribution in fan-out**: When a message is injected via `/api/v1/sessions/{id}/messages`
  and Slack is notified, the message appears with the bot's default Slack identity, not the
  configured `display_name`/`icon_emoji`. This is inconsistent with the task path.
- **Core boundary violation**: `app/services/delegation.py` is in core (`/app`) but contains
  Slack HTTP call logic that belongs in an integration service. Core should not know about
  Slack wire formats.

### What the fix achieves

A single `app/services/slack_client.py` with:

```python
async def post_message(
    token: str,
    channel_id: str,
    text: str,
    thread_ts: str | None = None,
    username: str | None = None,
    icon_emoji: str | None = None,
    icon_url: str | None = None,
    reply_broadcast: bool = False,
) -> dict:
    ...
```

- One place to fix retry logic, error handling, and timeout policy
- `delegation.py` no longer contains Slack wire calls — it calls `post_message()` if available, but better: it delegates posting to the dispatcher (see item 3)
- Fan-out in api_v1 can optionally pass bot attribution
- `slack_uploads.py` stays separate (file upload is a distinct multi-step protocol)

### Implementation steps

1. Create `app/services/slack_client.py` with `post_message()`. Use 30s timeout.
2. Replace `DelegationService._post_to_slack()` with a call to `slack_client.post_message()`.
   The `post_child_response()` method still stays in `delegation.py` but no longer has raw httpx.
3. Replace the `_post_to_slack()` in `api_v1_sessions.py` with `slack_client.post_message()`.
4. Update `integrations/slack/dispatcher.py` to use `slack_client.post_message()` for its
   text posting step (it can keep `slack_uploads.py` for file uploads).
5. Remove the three module-level `_http = httpx.AsyncClient(...)` instances in the affected files.

**Note**: `app/services/slack_client.py` is technically a core file with "slack" in the name.
That's acceptable — `DESIGN.md` already carves out this exception. The rule is no Slack logic
in *business logic* (loop, tasks, delegation decisions), not in service adapters.

---

## 2. Add `Task.callback_config` JSONB — separate orchestration from delivery

### How it works now

`Task.dispatch_config` is supposed to hold the **delivery target** — where to send the result:

```json
{"channel_id": "C123", "token": "xoxb-...", "thread_ts": "1234.56"}
```

In practice it's been polluted with **orchestration bookkeeping**:

```json
{
  "channel_id": "C123",
  "token": "xoxb-...",
  "thread_ts": "1234.56",
  "_notify_parent": true,
  "_parent_bot_id": "default",
  "_parent_session_id": "uuid",
  "_parent_client_id": "slack:C123",
  "trigger_rag_loop": false
}
```

And for harness tasks, it also holds **execution config**:

```json
{
  "harness_name": "run_tests",
  "working_directory": "/src",
  "sandbox_instance_id": "uuid",
  "output_dispatch_type": "slack",
  "output_dispatch_config": {...}
}
```

The `_*`-prefixed keys are stripped when creating callback tasks (`{k:v for k,v if not k.startswith("_")}`)
to prevent infinite loops. `trigger_rag_loop` needs its own boolean column on the model to
prevent the loop, which is where the `getattr(task, "trigger_rag_loop", False)` guard comes from.

### Why it's a problem

- **Mixed concerns**: A dispatcher reading `dispatch_config` sees orchestration noise alongside
  the delivery params it actually needs. If a future dispatcher deserializes the config strictly,
  it will break on unknown keys.
- **`trigger_rag_loop` is a boolean column on the generic `Task` model** for a Slack-specific
  feature. It doesn't belong there.
- **Harness execution config in dispatch_config**: `harness_name`, `working_directory`, etc.
  are inputs to execution, not delivery targets. They're in dispatch_config because that's
  the only config bag that exists on Task.
- **The `_*` stripping hack is fragile**: it works only because we agreed on that convention.
  There's no schema enforcement.

### What the fix achieves

Two JSONB columns with clear ownership:

| Column | Purpose | Who reads it |
|---|---|---|
| `dispatch_config` | Where/how to deliver: channel, token, thread_ts, webhook url, etc. | Dispatchers only |
| `callback_config` | Orchestration state: notify parent, harness execution params, trigger_rag_loop | Task worker only |

Clean contract:
- Dispatchers receive `task.dispatch_config` — no orchestration noise
- Task worker reads `task.callback_config` for post-completion behavior
- No `_*` stripping needed; no boolean columns for single-integration features

```python
# callback_config schema (conceptual)
{
  "notify_parent": true,
  "parent_bot_id": "default",
  "parent_session_id": "uuid",
  "parent_client_id": "slack:C123",
  "trigger_rag_loop": true,          # moved out of Task model column
  "harness_name": "run_tests",       # moved from dispatch_config
  "working_directory": "/src",
  "sandbox_instance_id": "uuid",
  "output_dispatch_type": "slack",
  "output_dispatch_config": {...}
}
```

### Implementation steps

1. **Migration 039**: Add `Task.callback_config JSONB` with `server_default="'{}'::jsonb"`.
   Add `Task.trigger_rag_loop` removal as a separate migration (040) after code is updated.
2. In `DelegationService.run_deferred()`: write `_notify_parent` keys to `callback_config`
   instead of `dispatch_config`.
3. In `run_task()` (tasks.py): read `_notify_parent` et al from `task.callback_config`,
   read `trigger_rag_loop` from `task.callback_config` (not the model column).
4. In `run_harness_task()` (tasks.py): read `harness_name`, `working_directory`,
   `sandbox_instance_id`, `output_dispatch_type`, `output_dispatch_config` from `callback_config`.
5. In `Task` model: keep `trigger_rag_loop` column temporarily; add `callback_config` mapped
   column. After code cutover, drop `trigger_rag_loop` column (migration 040).
6. In `delegate_to_agent` tool (`app/tools/local/delegation.py`): pass `notify_parent`,
   `trigger_rag_loop` in `callback_config` kwarg when creating the task.

**Migration safety**: `dispatch_config` rows that currently have `_notify_parent` etc. will
be stale but harmless — task worker will find nothing in `callback_config` and simply skip the
notify step. No data migration needed for in-flight tasks; they're short-lived.

---

## 3. Drive `_fanout()` through the dispatcher registry

### How it works now

`app/routers/api_v1_sessions.py` `_fanout()` is the delivery leg for the "inject message"
endpoint (`POST /api/v1/sessions/{id}/messages`). When `notify=true`, it checks whether
the session has a Slack target and posts directly:

```python
async def _fanout(session: Session, text: str, source: str | None = None) -> None:
    cfg = session.dispatch_config or {}
    dispatch_type = cfg.get("type")

    if dispatch_type == "slack":
        # ... post to Slack directly
        return

    # Fallback: derive from client_id for Slack sessions without stored dispatch_config
    if session.client_id and session.client_id.startswith("slack:"):
        # ... post to Slack directly
```

This is pure Slack logic sitting in a core router. Adding a Discord integration means editing
this function. Adding a Teams integration means editing it again.

### Why it's a problem

- **Core boundary violation**: `api_v1_sessions.py` is the public `/api/v1/` REST API. It's in
  `/app/routers/`, which is core. It should not contain integration-specific routing logic.
- **Not extensible**: Every new integration must modify this file, violating the open/closed
  principle that the dispatcher registry was built to enable.
- **Inconsistent with task path**: The task worker uses `dispatchers.get(dispatch_type)`.
  The inject path should do the same — they're both "deliver this text somewhere".

### What the fix achieves

`_fanout()` becomes integration-agnostic:

```python
async def _fanout(session: Session, text: str, source: str | None = None) -> None:
    cfg = session.dispatch_config or {}
    dispatch_type = cfg.get("type") or _infer_dispatch_type(session.client_id)
    if not dispatch_type or dispatch_type == "none":
        return
    # Build a synthetic task-like object for the dispatcher
    synthetic = _SyntheticTask(dispatch_type=dispatch_type, dispatch_config=cfg, bot_id=session.bot_id)
    dispatcher = dispatchers.get(dispatch_type)
    await dispatcher.deliver(synthetic, text)
```

New integrations automatically work with `notify=true` message injection without touching
core code.

### Implementation steps

1. Define a lightweight `_SyntheticDelivery` dataclass (or Protocol) in `api_v1_sessions.py`
   that matches the fields dispatchers read (`dispatch_type`, `dispatch_config`, `bot_id`).
   Alternatively, just pass them as named args if the `Dispatcher.deliver()` signature allows it.
2. Replace the `if dispatch_type == "slack"` blocks in `_fanout()` with a dispatcher lookup.
3. Remove the `session.client_id.startswith("slack:")` fallback — this was a crutch for
   sessions created before `dispatch_config` was added. If sessions are properly created via
   `POST /api/v1/sessions` with `dispatch_config`, the fallback is no longer needed. Add a
   deprecation log warning if the fallback fires, then remove it after a few weeks.
4. The `_post_to_slack()` helper function in `api_v1_sessions.py` can be deleted entirely
   once the Slack dispatcher handles it.

**Note**: The Slack dispatcher currently takes a full `Task` object. It may need a small
refactor to accept a duck-typed protocol (just the fields it reads) so `_fanout()` doesn't
have to construct a real `Task`. Or just define the `Dispatcher.deliver()` signature to accept
a protocol type.

---

---

---

## 4. Async compaction — stop compaction events from leaking into integrations

### How it works now

`chat.py` `/chat/stream` does this at the end of `event_generator()`:

```python
await persist_turn(db, ...)

compaction_stream = run_compaction_stream(session_id, bot, messages, ...)
async for event in compaction_stream:
    yield f"data: {json.dumps(event)}\n\n"   # ← streams compaction events to all clients
```

`run_compaction_stream()` yields:
- `compaction_start` — begins the memory phase
- Tool events from `run_agent_tool_loop(compaction=True)` — e.g. `tool_start: save_memory`, `tool_result: Memory saved`
- A `response` event with `compaction=True` — the LLM's final text after saving memories: _"Nothing from this conversation needs to be stored..."_
- `compaction_done` — summary written to DB

The **Slack message handler** (`integrations/slack/message_handlers.py`) processes any `response` event:

```python
elif etype == "response":
    reply = (event.get("text") or "").strip()
    ...
    await client.chat_update(channel, ts=thinking_ts, text=reply)   # ← overwrites Slack message!
```

It does **not** check `event.get("compaction")`. So when the memory phase finishes, its `response` event (talking to itself: "I'll save these memories…") overwrites the real bot response with LLM internal monologue.

The non-streaming `/chat` path already does the right thing: `maybe_compact()` fires compaction as an `asyncio.create_task()` after the response is returned. No events leak.

### Why it's a problem

- **Real response gets overwritten**: Slack shows the memory compaction LLM response instead of the agent's actual answer to the user
- **Compaction tool events pollute UX**: `tool_start: save_memory` shows "🔧 _save_memory..._" in the thinking indicator during compaction, as if it were part of the agent answering the question
- **Core streaming contract is violated**: SSE clients (Slack, native app) are supposed to receive one `response` event — the answer to the user's question. Receiving a second `response` event after `compaction_start` is unexpected and breaks any client that doesn't know about compaction internals
- **Every streaming client needs a workaround**: Currently only Slack is affected, but any future streaming integration (Discord, Teams, web app) would need to filter compaction events

### What the fix achieves

Compaction runs fully in the background, detached from the SSE stream:
- SSE stream contains exactly: context events → tool events → `response` event (real answer). Done.
- Compaction runs asynchronously after `persist_turn()`, same as the non-streaming path
- A brief compaction notification ("🧠 _Context compacted_") is posted as a **separate Slack message** (via dispatcher), not an edit to the bot's response — clearly marked as a system event, not the bot's answer
- No changes needed to the Slack message handler; the bug simply cannot occur

### Implementation steps

1. **`app/routers/chat.py`** streaming path: remove `run_compaction_stream()` from `event_generator()`. Replace with `maybe_compact(session_id, bot, messages, ...)`. One line change.

2. **`app/services/compaction.py` `_drain_compaction()`**: after running compaction successfully, if the session has a `dispatch_target` (dispatch_type + dispatch_config on the session, or passed in), call the dispatcher to post a notification:
   ```python
   # example notification text:
   "🧠 _Context compacted — conversation summarized to free up context window._"
   ```
   The session dispatch info needs to be passed in (the streaming path knows it from `req.dispatch_type` / `req.dispatch_config`). Add params to `maybe_compact()` and `_drain_compaction()`.

3. **Thread-safety**: `maybe_compact()` is fire-and-forget. When compaction is running in the background and the user sends the next message, the next request reads the same `messages` snapshot (from before compaction updates the DB watermark). This is safe — the compaction updates `session.summary_message_id` atomically in the DB, and the next request calls `load_or_create()` which rebuilds the message list from DB. The in-memory snapshot used by `maybe_compact()` is a point-in-time copy, which is fine since it only summarizes what was there.

4. **Remove `compaction_start`/`compaction_done` events from the SSE stream** (they no longer flow through it). If the web client/admin wants to know compaction ran, it can poll or use the trace page.

---

## 5. Back-to-back message queuing — don't silently drop messages

### How it works now

The Slack bot uses a per-channel `asyncio.Lock`. In `message_handlers.py`:

```python
lock = get_channel_lock(channel)
if lock.locked():
    await say("⏳ _Still thinking, try again in a moment._")
    return   # ← message is DROPPED
```

The second message never reaches the agent. The user's text is silently discarded.

For the HTTP API (`/chat` and `/chat/stream`): there is no per-session serialization. Two concurrent requests to the same session-id race to call `load_or_create`, each gets the same message history snapshot, both run the agent, and `persist_turn` is called twice — the second write may clobber the first, leaving duplicate or garbled history.

### Why it's a problem

- **Messages are silently lost**: Users don't get acknowledgement that their message was actually queued. "Try again in a moment" implies they should re-send — but the message was already eaten.
- **Bad UX for anything time-sensitive**: If a user sends a follow-up before the bot finishes, they have to remember to re-type it. This is the thing that makes bots feel broken.
- **HTTP API has no protection**: The race condition can corrupt session history for any programmatic caller that fires concurrent requests.

### What the fix achieves

- Slack: user's second message is queued (small FIFO per channel); bot posts "⏳ _message queued_"; processes it immediately after the current one finishes; posts its response
- HTTP API: concurrent `/chat` requests for the same session are serialized via an in-process session lock; clients can detect this via a `202 Accepted` response (optional, phase 2)
- No messages are silently dropped

### Implementation steps

**Slack bot fix (primary, simpler):**

1. **`integrations/slack/state.py`**: Add `_channel_queues: dict[str, asyncio.Queue]` alongside `_channel_locks`. Add `get_channel_queue(channel)` returning a `Queue(maxsize=5)` (cap prevents unbounded growth from flooding).

2. **`integrations/slack/message_handlers.py`**: Extract the main dispatch body into `_run_dispatch(payload, ...)`. In `dispatch()`:
   ```python
   lock = get_channel_lock(channel)
   queue = get_channel_queue(channel)
   if lock.locked():
       if queue.full():
           await say("_Queue full — please wait a moment._")
           return
       await queue.put(payload)
       await say("⏳ _Message queued, I'll get to it next._", **identity)
       return

   async with lock:
       await _run_dispatch(payload, ...)
       while not queue.empty():
           next_payload = queue.get_nowait()
           await _run_dispatch(next_payload, ...)
   ```

3. The queued dispatch needs to open a fresh `say`/`client` context. Since Slack events are received one at a time, `client` is available at `dispatch()` scope and can be passed through.

**HTTP API fix (secondary, needed for correctness):**

4. **`app/services/sessions.py`**: Add a `_session_locks: dict[UUID, asyncio.Lock]` in-process dict. In `load_or_create()`, acquire the session lock before loading and hold it (or return it to the caller to hold for the duration of the request). Release in `persist_turn()`.

5. **`app/routers/chat.py`**: Acquire session lock before agent run; release after `persist_turn()`. On lock contention, return `202 Accepted` with `{"status": "queued", "session_id": ...}` (optional — could also just wait/serialize silently).

**Note on Slack-specific UX**: When the queued message runs, it should post as a **new** Slack message (its own thinking placeholder), not re-use the previous one. The user should see the full response for each of their messages.

---

## 6. Trace page: show agent response + distinguish compaction events

### How it works now

The trace page merges events from two DB tables:
- `messages` table (role=user/assistant) joined by `correlation_id`
- `tool_calls` + `trace_events` tables joined by `correlation_id`

Merged by `created_at` timestamp.

**Problems observed:**
1. **Response text IS in the trace** (as the `[assistant]` message row from the messages table). But it's visually identical to other assistant messages (tool results, etc.) — hard to spot as "the final answer."
2. **Compaction events are interleaved**: compaction tool calls (save_memory) share the same `correlation_id` as the main turn. They look like regular agent tool calls. There's no visual boundary between "agent answered the question" and "compaction ran."
3. **After fix Item 4**: compaction will run in a background task with its own correlation_id, so it'll be a separate trace automatically. But the trace list page won't link them obviously.
4. **Token usage is collapsed**: actual counts are in the expandable JSON, hard to see at a glance.

### What the fix achieves

- Agent's final text response highlighted prominently (distinct card, not just another `[assistant]` row)
- Compaction section visually separated with a divider or collapsible group
- Token totals shown in the collapsed row (not only on expand)
- Linked correlation entries: trace list shows "(+ 1 compaction run)" when a background compaction shares the same session turn

### Implementation steps

1. **`app/agent/recording.py`**: Record the final agent response as a `TraceEvent` with `event_type="response"` (text field in `data`). This gives the trace page a dedicated event to render prominently in the timeline, not relying on the Message row which has timestamp ordering issues.

2. **`app/templates/admin/trace.html`**: Add a `response` event type variant in the Jinja2 template — larger font, highlighted card, "Final response" label.

3. **Compaction visual grouping**: After fix Item 4, compaction runs with its own correlation_id. The trace list page (`/admin/sessions/{id}/correlations`) can show compaction correlations linked to their parent turn correlation_id (stored in the trace event data).

4. **Token usage inline**: In the trace timeline, show `in: N tok / out: N tok` inline on the collapsed token_usage row without requiring expand.

---

## Priority and Dependencies

```
Item 1 (slack_client.py)      — independent
Item 3 (_fanout dispatcher)   — depends on Item 1
Item 4 (async compaction)     — independent, HIGH PRIORITY (active bug)
Item 5 (message queuing)      — independent, HIGH PRIORITY (UX gap)
Item 6 (trace improvements)   — independent, low effort for item 4 side-effect
```

Item 4 is the most urgent: it actively corrupts the Slack response for any session that hits a compaction. The streaming path fix (step 1) is a single-line change.

Item 5 (Slack queue) is the next highest impact. The HTTP API race fix is correctness-critical but only matters for programmatic concurrent callers.

---

## Already Done (for reference)

- [x] `slack-integration/` folder deleted — `integrations/slack/` is the canonical copy
- [x] Dispatcher registry (`app/agent/dispatchers.py`) — `SlackDispatcher` out of `tasks.py`
- [x] `Bot.slack_*` columns renamed to `display_name`, `avatar_url`, `integration_config`
- [x] `SlackChannelConfig` table dropped, replaced by `IntegrationChannelConfig`
- [x] Integration process auto-discovery (`process.py` + `dev-server.sh`)
- [x] Knowledge session scoping + per-row similarity thresholds
- [x] `KnowledgeWrite.bot_knowledge_id` FK for audit integrity
- [x] `Task.callback_config` JSONB added (migrations 039+040) — orchestration separated from delivery config
- [x] `_post_to_slack()` consolidated — Slack HTTP calls moved to `integrations/slack/client.py`; `app/services/slack_uploads.py` moved to `integrations/slack/uploads.py`; delegation.py and api_v1_sessions.py no longer contain Slack API calls
- [x] `_fanout()` driven through dispatcher registry — no hardcoded Slack logic in core; `post_message()` added to Dispatcher protocol
