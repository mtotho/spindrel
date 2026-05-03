---
tags: [spindrel, track, streaming, architecture]
status: complete
updated: 2026-04-15
---
# Track — Streaming Architecture Rectification

## Why this track exists

The chat / agent-loop / RAG / UI streaming pipeline grew up in layers as the project pivoted from CLI → voice → Slack → web. Each layer added a workaround instead of refactoring the foundation, and the result is one architectural decision short of right.

The end goal is what an expert would build for a modern AI chat system: **one delivery hub, dumb subscribers, agent loop broadcasts, UI listens.** Conceptually identical to a SignalR/WebSocket hub or what claude.ai / ChatGPT do internally — the wire format (SSE vs WebSocket vs SignalR) doesn't matter.

## The fundamental flaw (one decision, seven symptoms)

We have **two parallel streaming systems running side by side**, and the agent loop dual-writes to both:

1. **POST /chat → SSE response**: long-poll the client holds open for the entire generation. Tokens are yielded directly.
2. **GET /channels/{id}/events → SSE channel-events bus**: in-memory pub/sub bus, every channel has a set of subscriber `asyncio.Queue`s.

Smoking gun at `app/routers/chat/_routes.py:763-766`:

```python
event_with_session = {**event, "session_id": str(session_id)}
yield f"data: {json.dumps(event_with_session)}\n\n"
# Relay to observers (other tabs/devices on the same channel)
_publish_stream(channel_id, "stream_event", {"stream_id": _primary_stream_id, "event": event_with_session})
```

Every event is sent to **both** paths. The local tab — the one that initiated the chat — receives every event twice and has explicit suppression logic at `useChannelEvents.ts:190-194` to ignore its own events via `isLocalStream`.

The bus exists. We just don't trust it. `channel_events.py:7` even says: *"Events are notification-only — consumers refetch from DB."* That's the contract — and it forces every notification to become an `invalidateQueries` call which, with TanStack Query v5 infinite queries, refetches every loaded page (the session-9 storms).

### The 7 symptoms that descend from this one decision

1. **The bus is a "go look again" notification, not delivery.** UI calls `invalidateQueries(["session-messages"])` on every event → O(pages) HTTP refetches.
2. **The sender has its own private channel.** POST /chat is a long-poll, separate from the bus. Drop mid-stream → synthetic-message preservation hack at `useChannelChat.ts:155-170`.
3. **Persistence not transactional with publishing.** `persist_turn` commits, then separately fires `_publish_event(...)`. If publish fails (queue full → silently dropped at `channel_events.py:99`) the UI never knows the row exists.
4. **Backpressure → silent drops.** `asyncio.Queue(maxsize=512)` + `put_nowait`. Slow tab → dropped events → corrupted view.
5. **No reconnect/replay.** No sequence numbers, no cursor, no replay endpoint. SSE drop = lost events. This forces the periodic-refetch pattern as the only recovery mechanism.
6. **UI has two cache layers fighting.** TanStack Query infinite query holds `pages`, Zustand chat store holds `messages`, synced via a fragile `useEffect` at `useChannelChat.ts:135-174`.
7. **Streaming endpoint mixes business logic and transport.** `_routes.py` is 850 lines combining auth, validation, persistence, agent invocation, SSE serialization, integration mirroring, mention chaining. Can't unit-test the agent loop without faking SSE machinery.

All seven cascade from one missed call: **make the bus the source of truth for live messages instead of treating it as a hint.**

## Reference architecture (target end state)

1. **One channel, one delivery path.** Sender, observer — everyone reads from the same hub. Sender is just another subscriber.
2. **Send is a write, not a stream.** POST /chat returns 202 with a turn id. UI doesn't wait on its response — it watches the channel.
3. **Agent loop publishes to the channel.** Tokens, tool calls, thinking, errors, completion, persisted Message rows — all flow through the same hub. Persistence and publishing are coupled.
4. **UI is a dumb subscriber.** Open one connection per channel, receive events, append to local state. No "is this mine vs theirs" branching. History loaded once via REST as bootstrap; live messages stream.
5. **Reconnect uses a sequence cursor.** Each event has a per-channel seq number; client tracks last-seen, on reconnect requests `?since=<seq>`. Server keeps a small ring buffer per channel.
6. **Backpressure is real.** Either publishers slow down when subscribers can't keep up, or events buffer + replay. Never silently dropped.

## Constraint: web UI and Slack must keep working

CLI/voice/other pathways are not actively tested — issues with them get noted, not blocked on.

## Phases

### Phase 1 — Make the bus the source of truth (FOUNDATION) — DONE 2026-04-10 (session 11)
**Goal**: events carry data, not hints. Add sequence numbers and replay. No client behavior change yet.

**Status**: All changes landed in session 11. 4979 tests passing (3 pre-existing failures unrelated to this work). Client unchanged — forward-compatible. Session log: `vault/Sessions/spindrel/2026-04-10-11-streaming-architecture-audit.md`.

- `channel_events.py`: add per-channel monotonic sequence number, ring buffer (256 events) for replay, `subscribe(channel_id, since: int | None = None)` semantics, `publish_message(...)` and `publish_message_updated(...)` helpers that serialize a `Message` row via `MessageOut`. Existing `publish(channel_id, event_type, metadata)` keeps working for non-message events (stream_start/event/end).
- `api_v1_channels.py`: SSE endpoint accepts `?since=<seq>` query param and replays missed events from the ring buffer before tailing live.
- 9 publish sites migrate from `_publish_event(channel_id, "new_message")` to the new helper that ships the row:
  - `app/routers/chat/_routes.py:227` (non-streaming pre-persist)
  - `app/routers/chat/_routes.py:586` (queued message)
  - `app/routers/chat/_routes.py:662` (streaming pre-persist)
  - `app/routers/chat/_multibot.py:339` — REMOVE (already double-published; `persist_turn` covers it)
  - `app/services/sessions.py:494` — `persist_turn` emits one event per persisted row
  - `app/services/sessions.py:661` — `store_passive_message`
  - `app/services/workflow_executor.py:171` → `publish_message_updated` (in-place edit)
  - `app/services/workflow_executor.py:189` → `publish_message`
  - `app/agent/dispatchers.py:139` (internal dispatcher delivery)
- `MessageOut` moves to a schemas module to break the cycle (`channel_events` ↔ `routers/sessions`).
- Tests: `test_channel_events.py` expanded for sequence numbers, ring buffer, replay-since, publish_message helper. `test_sessions.py` for per-row emission. Mocks in `test_multi_bot_channels.py` updated for new signature.
- **Client unchanged.** The SSE payload gains a `message` field; the existing client either ignores it or (later) uses it. Forward-compatible.

**Verification**: e2e suite still passes, web UI still works, Slack still posts and receives.

### Phase 2 — Collapse the two delivery paths — SUPERSEDED 2026-04-11
**Status:** Folded into Phase E of [[integration-delivery]]. The work below is still correct in spirit but is now done in lockstep with the renderer abstraction so Slack/Discord/BlueBubbles all migrate together. See that track for the current plan.

**Goal**: kill the dual-write. The bus is the only path.

- `_routes.py`: agent loop stops yielding to its own POST response, only publishes to the bus. POST /chat returns 202 with `{turn_id, session_id, stream_id}` immediately after enqueuing the agent run as a background task.
- `useChannelChat.ts`: drop `useChatStream` and the entire `chatStream.onEvent/onError/onComplete` apparatus. The local tab subscribes via `useChannelEvents` like everyone else.
- `useChannelEvents.ts`: drop the `isLocalStream` suppression. Drop `respondingBotId`, `primaryBotIdRef`, `memberStreams` demuxing — there's now only one event source so all streams come through the same path keyed by `stream_id`.
- Delete the synthetic-message preservation logic at `useChannelChat.ts:155-170` — no more synthetic, the hub is authoritative.
- Delete the `correlation_id` dedupe foot-gun — there's only one arrival path per row.
- Multi-bot fan-out (`_run_member_bot_reply`) already publishes to the same bus — no change required there.
- ~~The integration mirror path (`_mirror_to_integration`) still happens server-side after the agent loop — Slack/etc are unaffected.~~ **Superseded 2026-04-11:** Slack/Discord/BlueBubbles are NOT unaffected — they have the same dual-path disease as the web UI. Phase 2 of this track is now subsumed into Phase E of [[integration-delivery]], which collapses the dual paths for every integration simultaneously and replaces `_mirror_to_integration` with a unified outbox + renderer model. Do not work this phase in isolation.

**Verification**: web UI still works end-to-end. Slack still posts and receives. The 850-line `_routes.py` should drop substantially.

### Phase 3 — Split UI cache layers
**Goal**: one source of truth in the UI.

- History fetched on mount via REST (paginated by cursor, scrollback only loads more).
- Live messages append to the Zustand store from the bus.
- Drop the TanStack Query infinite query for `session-messages`.
- Drop the sync `useEffect` at `useChannelChat.ts:135-174`.
- Drop the message-filter in that effect — server never sends filtered rows in the first place since it streams what was actually persisted.

### Phase 4 — Separate domain from transport
**Goal**: agent loop is a pure async generator. Bus and SSE are adapters.

- Extract the agent invocation out of `_routes.py` into a service module: `start_turn(channel_id, message, ...) -> turn_id` that enqueues and returns immediately.
- A worker task runs the agent loop and publishes to the bus.
- `_routes.py` becomes thin — auth, validation, enqueue, return 202.
- SSE endpoint in `api_v1_channels.py` is the only transport adapter; subscribes to the bus and serializes.
- Now `agent_loop` can be unit-tested without faking SSE.

### Phase 5 — Backpressure and outbox
**Goal**: no silent drops, no lost events on commit.

- Replace `put_nowait` silent-drop with bounded backpressure: slow subscribers either block the publisher (briefly) or get marked stale and forced to resync via the replay buffer.
- Transactional outbox for `persist_turn`: write to `messages` table AND an `outbox` table in the same transaction, separate worker drains outbox to the bus. Survives process crashes between commit and publish.
- (Optional, if multi-process ever happens) Swap in-memory bus for Redis pub/sub or NATS. Keep the `channel_events` interface so callers don't change.

## Notes & Risks

- **Slack path is the safety net**. Slack messages flow in through dispatchers that call `store_passive_message` → `persist_turn`, both of which already publish to the bus. Slack posts go out via `_mirror_to_integration` server-side — no client involvement. Slack should keep working through every phase as long as we don't break those server-side functions.
- **Workflow lifecycle messages** (`workflow_executor.py`) are the trickiest — they update an existing message in-place (Phase 1 introduces `publish_message_updated` for this). The patching client logic comes in Phase 2.
- **Multi-bot member streams** (`_run_member_bot_reply`) already publish to the bus correctly. They're the *only* place that does it the "right" way today, and they're a useful template for what every code path should look like after Phase 2.
- **Sequence number monotonicity**: must be assigned at publish time, not at commit time, to handle interleaved concurrent publishes for the same channel (e.g., parallel multibot turns).
- **Ring buffer sizing**: 256 events covers ~30s of multibot streaming. Configurable. Not infinite — clients reconnecting after >5min get a "buffer expired, refetch from DB" hint and trigger a full reload.
- **Web UI tests**: there are no e2e tests for the chat UI itself — the e2e suite tests the API. Manual smoke required after Phase 2.

## Cross-references

- [[loose-ends]] — entry "Chat UI session-messages refetch storms" is a symptom of this; will be marked superseded once Phase 1 lands.
- Session log: `vault/Sessions/spindrel/2026-04-10-9-chat-ui-network-bloat.md` — the session that surfaced the symptom
- Session log: `vault/Sessions/spindrel/2026-04-10-11-streaming-architecture-audit.md` — the audit that produced this track
- [[architecture-decisions]] — to be updated with the "bus is source of truth" decision once Phase 1 ships

