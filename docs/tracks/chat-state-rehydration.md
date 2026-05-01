---
tags: [spindrel, track, complete]
status: complete
updated: 2026-04-18
---

## Phase 3 shipped 2026-04-18

- **Snapshot endpoint** — new `GET /api/v1/channels/{id}/state` in `app/routers/api_v1_channels.py` returning `ChannelStateOut { active_turns, pending_approvals }`. An *active turn* is any `correlation_id` with a `ToolCall` or `skill_index` `TraceEvent` inside the last 10 minutes AND no terminal assistant `Message`. Per-turn join to `ToolApproval` via the Phase 2 `tool_call_id` FK exposes `approval_id` + capability envelope inline on orphan `awaiting_approval` rows. Skill ids from `TraceEvent.data.auto_injected` resolved against the `Skill` table in a single batch query; unknown ids fall back to the id so the chip still renders. Pending approvals reuse the Phase 1 channel filter.
- **UI rehydrate** — new `ui/src/api/hooks/useChannelState.ts` (`useChannelState(channelId, primaryBotId)`) wired into `useChannelChat` *before* `useChannelEvents`. New `chatStore.rehydrateTurn(...)` action seeds `chatState.turns` idempotently: live SSE state (non-empty `toolCalls` / `autoInjectedSkills`) always wins over a staler snapshot.
- **Replay-lapsed path** — `useChannelEvents.ts` now invalidates `["channel-state", chId]` on `replay_lapsed` so reconnect refetches + reseeds. Together with the mount-seed this deprecates the 256-event replay buffer as a correctness backstop (buffer still delivers fast path; snapshot covers the gap).
- **Phase 3 decision — streaming text stays ephemeral**. No progressive `Message.content` writes during streaming. The turn-end `Message` row is the source of truth; a refresh during mid-stream text shows whatever the persisted ceiling is (user message + any completed turns). The UI's cost of this trade is ~100% covered by Phase 2's durable `ToolCall` rows + Phase 3's snapshot — the visible bits (tool chips, approval cards, skill chips) all rehydrate; only the raw in-flight assistant-text delta lives in memory.
- **Tests** — `tests/unit/test_channel_state_snapshot.py` (8 tests, real-DB): running `ToolCall` → active turn; `awaiting_approval` exposes linked approval + capability from `approval_metadata`; terminal assistant `Message` excludes the correlation_id; 10-min window filters stale rows; `pending_approvals` scoped by channel (other channel + `approved` status both excluded); `auto_injected` skill ids resolved to names with id fallback; channel with no `active_session_id` → empty snapshot; missing channel → 404. All 85 adjacent tests pass (Phase 2 lifecycle, approval system + suggestions + pin, channel events, dispatch core gaps + envelope). UI typecheck clean.

### Track closed

All three phases shipped in a single sitting on 2026-04-18 (Session 11 → Session 13). Kills Loose Ends D2 (streaming refresh / mobile tab-wake) and the "Tool approval prompt is non-inline in web UI" scratch-pad item — both moved to Fix Log. The 256-event replay buffer in `app/services/channel_events.py:343-346` stays for now as a fast-path optimization; the correctness invariant no longer depends on it.

## Phase 2 shipped 2026-04-18

- **Migration 207** — `tool_calls.status` + `completed_at`, `tool_approvals.tool_call_id` (FK) + `approval_metadata` (JSONB). Backfill: historical rows → `status='done'`, `completed_at = created_at`. Index `(bot_id, status)` added.
- **`recording.py`** — split into `_start_tool_call` (insert 'running'/'awaiting_approval') + `_complete_tool_call` (UPDATE to 'done'/'error') + `_record_tool_call` (kept for terminal-state one-shots: auth/policy denials, exec-completion worker).
- **`tool_dispatch.py::dispatch_tool_call`** —
    - Inserts a 'running' row at top of every dispatch (or reuses `existing_record_id` on the post-approval re-dispatch).
    - Approval-required path: inserts 'awaiting_approval' row + links it to ToolApproval via `tool_call_id`.
    - Auth/policy-deny paths: keep one-shot `_record_tool_call` but pass `status='denied'`.
    - Final write: `_complete_tool_call` UPDATE replaces the old end-state INSERT. `result_obj.record_id` is now always populated.
- **`loop.py`** — passes `existing_record_id=tc_result.record_id` on the post-approval re-dispatch (sequential + parallel branches). On approval-timeout, marks linked ToolCall row 'expired' alongside the ToolApproval.
- **`api_v1_approvals.py::decide_approval`** — flips linked `ToolCall.status` from 'awaiting_approval' → 'running' (approve) or 'denied' (deny, with `completed_at` stamp). Schema now exposes `approval_metadata` + `tool_call_id`.
- **Capability metadata persistence** — `_create_approval_record` now writes `extra_metadata` to the new `approval_metadata` column. `useApprovals.ts` schema + `ChannelPendingApprovals.tsx` updated to read from `approval_metadata._capability` (was `dispatch_metadata._capability`, which was UI-only — never written). Orphan capability cards now show the friendly capability name on refresh instead of `"activate_capability"`.

### TraceEvent write-point audit

Each ChannelEventKind the UI consumes has a persistent corollary, so no new write points were needed in Phase 2:

| Kind | Persistent corollary |
|---|---|
| `TURN_STARTED`, `TURN_ENDED` | `Message` row (user + assistant) is the snapshot for turn boundaries |
| `TURN_STREAM_TOOL_START`, `TURN_STREAM_TOOL_RESULT` | `ToolCall` row (Phase 2 write) |
| `APPROVAL_REQUESTED`, `APPROVAL_RESOLVED` | `ToolApproval` row (Phase 1 + Phase 2 link) |
| `SKILL_AUTO_INJECT` | `TraceEvent(event_type='skill_index')` with `auto_injected` payload (`context_assembly.py:1449`) |
| `CONTEXT_BUDGET`, `MEMORY_SCHEME_BOOTSTRAP`, `LLM_STATUS` | Ephemeral by design — fallback/retry/budget reconstruct on next turn |
| `TOOL_ACTIVITY`, `WORKFLOW_PROGRESS`, `HEARTBEAT_TICK`, `EPHEMERAL_MESSAGE`, `MODAL_SUBMITTED` | Ephemeral by design |

`DISCOVERY_SUMMARY` listed in original Phase 2 plan does **not** exist as a `ChannelEventKind` — `discovery_summary` is only a `TraceEvent.event_type` (already persisted at `context_assembly.py:2086`).

### Tests

`tests/unit/test_tool_call_status_lifecycle.py` (new, 5 tests, real-DB):

1. `test_start_writes_running_row_and_complete_flips_to_done` — primary success criterion.
2. `test_complete_with_error_marks_status_error` — error path.
3. `test_approve_flips_tool_call_status_to_running` — decide endpoint approve.
4. `test_deny_flips_tool_call_status_to_denied` — decide endpoint deny + `completed_at` stamp.
5. `test_skill_index_trace_event_is_persisted_and_queryable` — TraceEvent retrievability.

Plus 84 adjacent tests pass: approval system, approval pin, dispatch core gaps, dispatch envelope, dispatch timeout, tool policies, parallel tool execution, message metadata, retrieval cache.

`tests/unit/conftest.py::patched_async_sessions` now includes `app.agent.recording.async_session` so future tests can fire-and-forget recording functions against the SQLite test engine.

# Track — Chat State Rehydration

## North Star

Make the chat screen server-authoritative. Every persistent thing we've added over the past months (`Message`, `ToolCall`, `TraceEvent`, `Attachment`, `ToolApproval`) is already correlation-keyed and already server-side — the chat UI just doesn't read from it on mount. Unify the read path so refresh, mobile re-mount, and background-originated events all produce the same UI as a live SSE stream.

**One write path. Two read paths.** SSE for deltas, endpoint for snapshots. No duplicate state.

## Why Now

Three bugs trace to the same root cause — chat UI state lives only in memory (`chatState.turns` in `ui/src/stores/chat.ts`), rebuilt from SSE deltas:

- Inline tool-approval card vanishes on page refresh (Loose Ends: *Tool approval prompt is non-inline in web UI* — misdiagnosed; the card exists at `ui/src/components/chat/StreamingIndicator.tsx:244-297` but only during the live turn)
- Mobile streaming response disappears then reappears (Loose Ends D2 — ring-buffer eviction in `app/services/channel_events.py:343`)
- Background/task-originated approvals never land inline, only as `ApprovalToast` linking to `/admin/approvals`

All three share the same fix: rehydrate from the DB on channel mount.

## Status

| Phase | Title | Status | Session |
|---|---|---|---|
| 1 | Approvals-only rehydrate inline | **shipped** | 2026-04-18 |
| 2 | Upsert `ToolCall` + `TraceEvent` at-start | **shipped** | 2026-04-18 |
| 3 | `GET /channels/{id}/state` snapshot endpoint + UI rehydrate | **shipped** | 2026-04-18 |

### Phase 1 shipped 2026-04-18

- **Backend**: `GET /api/v1/approvals` now accepts `channel_id` (`app/routers/api_v1_approvals.py:82`). New integration test `test_approvals_list_filters_by_channel` covers filter + `status=` combination. 45/45 approvals suite green.
- **Frontend**: `useChannelPendingApprovals(channelId)` (`ui/src/api/hooks/useApprovals.ts`). `ChannelPendingApprovals` component (`ui/app/(app)/channels/[channelId]/ChannelPendingApprovals.tsx`) dedupes against `liveApprovalIds` so it only renders orphans. Wired into `ChatMessageArea` above `turnIndicators`. `ApprovalToast` subtracts current-channel pending via `useMatch("/channels/:channelId")` so the toast count doesn't double-signal.
- **Event invalidation**: `useChannelEvents` now invalidates `["approvals", "channel", chId]` + `["approvals", undefined, "pending"]` on `approval_requested` / `approval_resolved` — Phase 1's orphan cards animate the same as the live-turn cards. TS clean.
- **Known gap for Phase 2/3**: `ToolApproval.dispatch_metadata` does not persist the `_capability` envelope today (only passed to the bus publish at `tool_dispatch.py:876`). Orphan capability approvals show `tool_name="activate_capability"` instead of the friendly capability label. Fix: persist `extra_metadata` on the DB row; small, future-safe.

## Phase 1 — Approvals-only rehydrate inline

**Scope**: the narrowest surface that validates the pattern. `ToolApproval` already has `channel_id` + status + full payload, so Phase 1 is all reads — no schema changes, no write-path changes.

**Backend**
- `app/routers/api_v1_approvals.py::list_approvals` — add `channel_id: Optional[uuid.UUID] = Query(None)` + matching `where` clause.

**Frontend**
- New hook `useChannelPendingApprovals(channelId)` in `ui/src/api/hooks/useApprovals.ts` — fetches `?status=pending&channel_id=...`, invalidated by `approval_requested` / `approval_resolved` channel events (subscribe in `useChannelEvents.ts:349-399`).
- New component `ChannelApprovalsSection` rendered in `ui/app/(app)/channels/[channelId]/ChatMessageArea.tsx` after the `turnIndicators` loop. Filters out approvals whose `approval_id` is already represented in `chatState.turns[*].toolCalls[*].approvalId` (live card already covers them).
- Reuse `SingleToolCallCard` visuals — extract to a shared callsite or pass the approval row as a synthesized `ToolCallItem`.
- `ApprovalToast` (`ui/src/components/layout/ApprovalToast.tsx`) gains a channel-scoped mute: when on `/channels/:id`, exclude approvals for that channel from the count so the toast doesn't double-signal.

**Tests**
- Router: `tests/unit/test_approvals_router.py` — `channel_id` filter returns only matching rows, combines with `status`.
- UI: visual test not strictly needed; the data flow is verifiable by unit test on the dedup logic if extracted.

**Out of scope for Phase 1**
- Active-turn rehydrate (Phase 3)
- In-flight tool-call state (Phase 2)
- Streaming text persistence (open question, likely never — see Phase 3 open questions)

## Phase 2 — Upsert `ToolCall` + `TraceEvent` at-start

**North star for this phase**: a row exists for every tool call AND every skill auto-injection AS SOON AS the event happens on the server — not when the turn ends. That's the invariant Phase 3's snapshot endpoint relies on.

**Why before Phase 3**: if `ToolCall` / `TraceEvent` rows only land at end-of-turn, the Phase 3 snapshot query for an in-flight turn returns empty → refresh still shows a blank chat. Phase 2 is the prerequisite write path.

### Work items (order doesn't matter, all small)

**1. Migration 207** (`migrations/versions/207_tool_calls_status_completed_at.py`)
- Add `tool_calls.status TEXT NOT NULL DEFAULT 'running'` + index on `(status)` or `(bot_id, status)`.
- Add `tool_calls.completed_at TIMESTAMP(timezone=True) NULL`.
- `created_at` semantically becomes "started_at" — no rename to avoid churn; document in migration comment.
- Backfill existing rows: `status='done'`, `completed_at = created_at` (they all completed historically).
- Downgrade: drop both.

**2. `app/db/models.py::ToolCall`** — add the two fields. Match migration exactly.

**3. `app/agent/tool_dispatch.py::dispatch_tool_call`**
- Today: `_record_tool_call` fires via `safe_create_task` at three points (line 288 deny, 325 policy-deny, 678 normal complete) — all END states.
- Change: at the top of `dispatch_tool_call` (after the skip-policy guard but before any dispatch), insert a `ToolCall` row with `status='running'`, `arguments`, `started_at=now`, `completed_at=NULL`, `result=NULL`. Stash the inserted row's `id` on the `result_obj`.
- Replace the three existing `_record_tool_call` call sites with an UPDATE that sets `status`, `result`/`error`, `duration_ms`, `completed_at=now` on the existing row id.
- Approval-gated path (line 340+ `require_approval`) — set `status='awaiting_approval'`. Resolution path (in `resolve_approval`, `app/agent/approval_pending.py`) needs to flip it back to `'running'` on approve / `'denied'` on deny.
- `_record_tool_call` in `app/agent/recording.py` — refactor to `_start_tool_call(...) -> row_id` and `_complete_tool_call(row_id, ...)`. Keep fire-and-forget `safe_create_task` semantics on both.

**4. `TraceEvent` write-point audit**
- Goal: every event the UI's `useChannelEvents` consumes should have a corresponding DB row written synchronously (or via `safe_create_task`) at the point it's published to the bus.
- Check each `publish_typed(..., ChannelEvent(kind=…))` call site:
  - `TURN_STARTED`, `TURN_ENDED` — turn.py / turn_worker.py
  - `TURN_STREAM_TOOL_START`, `TURN_STREAM_TOOL_RESULT` — `turn_event_emit.py:117/132` (ToolCall covers these after item 3)
  - `SKILL_AUTO_INJECT` — should write a `TraceEvent(event_type='skill_auto_inject')` row. Grep for existing `_record_trace_event` calls; confirm coverage or add.
  - `APPROVAL_REQUESTED`, `APPROVAL_RESOLVED` — already persisted via `ToolApproval` row (Phase 1 relies on it).
  - `DISCOVERY_SUMMARY` — already a TraceEvent, confirm.
  - `LLM_STATUS` — probably not persisted. Either add `TraceEvent(event_type='llm_status')` writes, or accept it's ephemeral (fallback/retry badges reconstruct on next attempt).
- Deliverable: either a ✓ against each kind confirming coverage, or a new write-point.

**5. Persist capability extra_metadata on `ToolApproval`** (Phase 1 known-gap followup)
- `app/agent/tool_dispatch.py::_create_approval_record` receives `extra_metadata` but never writes it to the row; the `_capability` envelope only rides the bus publish. Orphan capability approvals in the UI show `"activate_capability"` instead of the friendly name.
- Fix: merge `extra_metadata` into `dispatch_metadata` on insert (or add a new `approval_metadata` JSONB column if overloading `dispatch_metadata` feels wrong — today it holds `dispatch_config` for routing, so a separate column is cleaner).
- UI `ChannelPendingApprovals.tsx` already reads from `approval.dispatch_metadata?._capability` — will start showing the right label for free once the row is written.

### Success criteria

- Unit test: `test_tool_call_row_appears_before_completion` — start a tool, assert `status='running'` row exists in DB, complete, assert `status='done'` on same row id.
- Unit test: `test_approval_transitions_tool_call_status` — policy gates a tool, row is `'awaiting_approval'`; resolve approve → `'running'`; resolve deny → `'denied'`.
- Unit test: `test_skill_auto_inject_persists_trace_event` — trigger injection, confirm `TraceEvent` row.
- Existing ToolCall-based tests (admin trace views, learning center, token_usage queries) still pass without schema change hits — backfill covers historical rows.
- Capability approval from a fresh webhook: refresh the page → orphan card in `ChannelPendingApprovals` shows the capability's display name, not `"activate_capability"`.

### Files to touch

- `migrations/versions/207_tool_calls_status_completed_at.py` (new)
- `app/db/models.py` (ToolCall: add 2 fields)
- `app/agent/tool_dispatch.py` (dispatch_tool_call upsert + _create_approval_record extra_metadata persist)
- `app/agent/recording.py` (split `_record_tool_call` → `_start_tool_call` + `_complete_tool_call`)
- `app/agent/approval_pending.py` (flip ToolCall.status on resolve)
- `app/services/turn_event_emit.py` (audit, maybe add `_record_trace_event` calls)
- `tests/unit/test_tool_call_status_lifecycle.py` (new)
- `tests/unit/test_approval_transitions_tool_call_status.py` (new)

### Out of scope for Phase 2

- Streaming assistant text persistence (Phase 3 open question — currently leaning "stays ephemeral, turn-end Message row is good enough").
- `GET /channels/{id}/state` endpoint itself (Phase 3).
- UI changes — Phase 2 is write-side only. UI continues consuming the SSE stream as today.

### Done when

All five work items merged, tests green, Roadmap entry updated to show Phase 2 shipped, session log written for session that shipped it. Then Phase 3 can start fresh.

## Phase 3 — `GET /api/v1/channels/{id}/state` snapshot endpoint

**Scope**: one endpoint that answers "what's the current state of this channel?" — returns what the UI would have built up from live SSE events.

**Backend**
- New router `app/routers/api_v1_channel_state.py` (or fold into existing channel router).
- Query shape: find active turns = correlation_ids with no terminal assistant `Message` yet, within the last N minutes. Join to `ToolCall` (running + awaiting_approval), `TraceEvent` (skill_auto_inject), `ToolApproval` (pending, reuses Phase 1), recent `Message` rows.
- Response: `{ active_turns: [...], pending_approvals: [...], recent_messages: [...] }`.

**Frontend**
- `useChannelState(channelId)` called on channel mount. Seeds `chatState.turns` + orphan approvals BEFORE `useChannelEvents` connects.
- On SSE reconnect, re-fetch the snapshot + restart subscription rather than relying on `channel_events.py:343-346` replay buffer (which evicts at 256 events).

**Kills**
- Loose Ends D2 (streaming refresh / mobile tab-wake)
- Background-task approvals surfacing inline
- Anything that currently relies on the 256-event replay buffer

**Open questions**
- Partial streaming text: progressively write `Message.content` every ~500ms during streaming, or accept "text is ephemeral until turn ends"? Start with the latter — covers 90% of UX for 10% of the engineering cost. Text typically reaches a terminal `Message` row within seconds anyway; if a refresh catches the gap, the SSE replay buffer usually covers it for the small window.
- Turn TTL: define "active turn" for the query. Candidate: correlation_ids with a `TraceEvent` or `ToolCall` in the last 10 min and no terminal `Message` row.

## References

- `ui/src/stores/chat.ts:190-298` — in-memory turn state
- `ui/src/components/chat/StreamingIndicator.tsx:160-297` — `SingleToolCallCard` + inline approval buttons
- `ui/src/components/layout/ApprovalToast.tsx` — fallback path today
- `app/agent/tool_dispatch.py:340-373, 792-895` — approval create + publish
- `app/services/channel_events.py:343-346` — 256-event replay buffer (to be deprecated in Phase 3)
- `app/domain/channel_events.py:52-76` — `APPROVAL_REQUESTED`, `APPROVAL_RESOLVED`
- `app/db/models.py:317-522` — `Message`, `ToolCall`, `TraceEvent`
- `app/db/models.py:1409-1431` — `ToolApproval`
- `app/routers/api_v1_approvals.py:79-102` — `list_approvals` (Phase 1 target)
