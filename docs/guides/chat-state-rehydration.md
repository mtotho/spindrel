# Chat State Rehydration

Close a tab mid-turn and come back. Answer an approval prompt on your phone hours after the bot asked. Let the laptop sleep while a tool is still running. The chat should look the same when you come back — because nothing in the system *actually* went away, only your subscription to it did.

This guide explains how Spindrel rebuilds a chat's in-flight state on mount, tab-wake, and reconnect, and why that replaced the old fragile 256-event replay buffer.

---

## What rehydration covers

When you open a channel (or the tab re-focuses, or a dropped SSE reconnects), Spindrel rebuilds four things:

| Thing | Lives where | Rehydrates from |
|---|---|---|
| Recent messages | `Message` rows in Postgres | Normal `/api/v1/channels/{id}/messages` pagination |
| In-flight tool calls | `ToolCall` rows (`status` in `{running, awaiting_approval}`) | **Channel state snapshot** (below) |
| Pending approvals inline in chat | `ToolApproval` rows linked to `ToolCall.id` | Channel state snapshot |
| Orphan approvals (no matching turn) | Same `ToolApproval` rows | Inline "Orphan Approvals" section |
| Auto-injected skill chips for a live turn | `TraceEvent` rows (`event_type="skill_index"`) | Channel state snapshot |

The key move: the baseline comes from **authoritative Postgres rows**, not from replaying old SSE events. The SSE stream still delivers deltas thereafter — it just no longer has to carry history.

---

## The snapshot endpoint

```
GET /api/v1/channels/{channel_id}/state
```

Returns a point-in-time snapshot of what's *in-flight right now*:

```json
{
  "active_turns": [
    {
      "turn_id": "…uuid…",          // correlation_id threading through SSE
      "bot_id": "curator",
      "is_primary": true,
      "tool_calls": [
        {
          "id": "…",
          "tool_name": "search_channel_archive",
          "arguments": {"q": "incidents last week"},
          "status": "running",
          "is_error": false,
          "approval_id": null,
          "approval_reason": null,
          "capability": null
        }
      ],
      "auto_injected_skills": [
        {
          "skill_id": "bots/curator/triage-playbook",
          "skill_name": "Triage playbook",
          "similarity": 0.84,
          "source": "rag"
        }
      ]
    }
  ],
  "pending_approvals": [
    { "id": "…", "tool_name": "delete_file", "tool_call_id": "…", "status": "pending", ... }
  ]
}
```

### What counts as "active"

An active turn is a correlation_id that has at least one `ToolCall` or a `skill_index` / `turn_started` `TraceEvent` in the last **10 minutes** *and* has **not yet produced a terminal `assistant` Message**. Once the assistant Message lands, the turn is complete — the snapshot excludes it.

Lifecycle-only turns (`turn_started` / `skill_index` with no durable `ToolCall`) are only considered active while the session lock is active. This preserves refresh support for pure text turns while preventing stale typing indicators from rehydrating after the turn is already idle.

The 10-minute window is a practical ceiling: tool calls that legitimately take longer get rehydrated by their next event, and anything older than that is considered stale enough to re-start rather than resume.

### What counts as "pending"

Any `ToolApproval` row for the channel in `status="pending"`, ordered newest-first, capped at 50. These include:

- **Linked approvals** — `tool_call_id` is set, so the UI renders the approval *inline* on the matching tool-call card in the turn.
- **Orphan approvals** — `tool_call_id` is null (e.g. legacy rows, or the linking UPDATE lost to a crash). The UI renders these in a dedicated "Orphan Approvals" section at the top of the channel so they're still resolvable.

Auth: requires `channels:read`. See `app/routers/api_v1_channels.py:1104` for the endpoint, `_snapshot_active_turns` and `_snapshot_pending_approvals` for the implementation.

---

## The client side — `useChannelState` + `rehydrateTurn`

```ts
// ui/src/api/hooks/useChannelState.ts
const snapshot = useChannelState(channelId, primaryBotId);
```

The hook:

1. Fetches `/api/v1/channels/{id}/state` via React Query.
2. On every successful fetch, seeds each active turn into `useChatStore` via `store.rehydrateTurn(...)`.
3. Reconciles **ghosts** — local turns that are *not* in the snapshot and older than a 3-second grace window. Those get finished. The grace window catches the race where an SSE `turn_started` arrives before the DB `TraceEvent` row is committed.

`rehydrateTurn` is **idempotent**: if a live SSE turn is already in the store for that turn_id with real content, the snapshot doesn't clobber it. Live-SSE-wins — the snapshot is a baseline, not the truth. See `ui/src/stores/chat.ts` (search for `rehydrateTurn`) for the merge rules.

### `rehydrateTurn` inputs

The hook passes the server shape into the store action:

| Field | Meaning |
|---|---|
| `channelId` | Scope |
| `turn_id` | The correlation_id — SSE events use this same id to thread deltas |
| `bot_id` + `botName` | Which bot is running the turn (resolved from `useBots()`) |
| `isPrimary` | Whether this is the channel's primary bot or a delegated/multi-bot turn |
| `toolCalls` | Each with `name`, `args`, `status`, `approvalId`, `capability`, `isError` |
| `skills` | Auto-injected skill chips, deduped by `skill_id` |

Server-side `error` and `expired` tool-call states collapse to `done` with `isError=true` — the UI only needs four render states (`running` / `done` / `awaiting_approval` / `denied`).

---

## When rehydration fires

### 1. Channel mount

`useChannelState(channelId)` runs on the first render of any channel view. Seeds turns once, then the SSE stream takes over.

### 2. Reconnect — `replay_lapsed`

When the SSE stream reconnects and the server indicates a replay gap (`replay_lapsed`), the channel event hook calls `invalidateChannelState(...)` — React Query refetches the snapshot, `useEffect` re-seeds turns. Turns that completed during the gap are reconciled as ghosts and finished.

### 3. Tab-wake

Mobile Safari / mobile Chrome aggressively suspend background tabs. When the tab wakes, the service worker may have torn down the SSE connection. The same `replay_lapsed` path handles this cleanly — on reconnect, snapshot, reseed.

---

## Why the old replay buffer went away

The previous design carried a ring buffer of the last 256 SSE events per channel. Reconnect replayed them in order. Problems:

- **Hard ceiling.** Long-running multi-step pipelines could emit more than 256 events in a turn. The buffer would roll, and reconnect would silently resurrect stale UI state while missing newer events.
- **State is implicit.** Rebuilding turn cards by replaying events is correct only if *every* event from turn-start is still in the buffer. Off-by-one = broken turn forever.
- **No durability across restarts.** Process restarts blew the buffer. Any open tab with an unresolved approval saw nothing after a deploy.

The snapshot + delta model fixes all three: the baseline is a consistent read from Postgres, deltas flow over SSE, and a lost SSE doesn't cost the UI anything except a brief re-fetch.

---

## Approvals — the tightly-coupled case

Because an approval prompt can be the *only* thing the UI is waiting for, and because phones drop SSE aggressively, the approval side of rehydration gets extra care:

- **Inline rendering.** Every approval with a `tool_call_id` renders on the matching tool-call card in the turn, with a mini approve/deny UI. No separate admin queue to hunt for.
- **Orphan fallback.** Approvals with no linked tool call render in a dedicated section at the top of the channel so they're always reachable.
- **Persistent.** `ToolApproval` rows are durable until decided — closing the tab, restarting the server, switching devices, all leave the approval intact.
- **Channel-scoped.** The `/approvals` endpoint is channel-scoped, so rehydrating a specific channel only pulls its approvals. No cross-channel noise.

See `app/routers/api_v1_approvals.py` for the endpoint, `ui/src/api/hooks/useApprovals.ts` for the hook, and `InlineApprovalReview` for the in-turn renderer.

---

## Migration 207 — persisted tool-call state

Rehydration relies on `ToolCall` rows being an accurate mirror of reality. Migration 207 added `status` and `completed_at` columns and wired the agent loop to:

- **Upsert at start.** When a tool call begins, insert/update with `status="running"`.
- **UPDATE on completion.** On finish (success, error, or denial), UPDATE status + `completed_at`.
- **Link approvals.** `tool_approvals.tool_call_id` joins approvals back to their call so the snapshot query can render them inline.
- **Persist capability metadata.** Capability-gated tools stamp their capability into `approval_metadata._capability` so the approval card can show "Run Capability X" instead of "Run tool Y".

The take-away: the DB is the source of truth for turn state. The snapshot endpoint is just a structured read of those rows.

---

## Reference

| What | Where |
|---|---|
| Snapshot endpoint | `app/routers/api_v1_channels.py:1104` |
| Active-turn query | `_snapshot_active_turns` (same file) |
| Pending-approval query | `_snapshot_pending_approvals` (same file) |
| Client hook | `ui/src/api/hooks/useChannelState.ts` |
| Store merge rules | `useChatStore.rehydrateTurn` in `ui/src/stores/chat.ts` |
| Inline approval renderer | `ui/src/components/chat/InlineApprovalReview.tsx` |
| Reconnect trigger | `ui/src/api/hooks/useChannelEvents.ts` (search `replay_lapsed`) |

## See also

- [Chat History](chat-history.md) — how messages, sessions, and `MEMORY.md` flushes persist.
- [Task Sub-Sessions](task-sub-sessions.md) — pipeline run transcripts rehydrate via `useSessionEvents` on the same bus.
- [How Spindrel Works](how-spindrel-works.md) — top-level architecture including capability gating and approval pipeline.
