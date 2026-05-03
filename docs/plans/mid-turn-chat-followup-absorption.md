---
title: Mid-Turn Chat Followup Absorption
summary: Plan to let normal chat agents absorb user followups at the next LLM/tool boundary instead of always answering them through a delayed queued task.
status: planned
tags: [spindrel, plan, agents, chat, context, quality]
created: 2026-05-03
updated: 2026-05-03
---

# Mid-Turn Chat Followup Absorption

## Summary

Normal Spindrel chat currently handles "user sent more messages while the bot
is responding" by persisting the followups and coalescing them into one delayed
`api` task. That is durable and safe, but it is less natural than CLI agents
such as Codex, which can incorporate new user input after a tool call and
before the next model call.

This plan keeps the current queued-task fallback, but adds a mid-turn absorption
path for normal LLM/tool-loop chat turns. When the active turn reaches a
pre-LLM checkpoint, it claims pending chat-burst followups, injects them into
the current model context, marks the queued task absorbed so it cannot answer
separately, and emits trace evidence.

## Goals

- Followups sent while a bot is working can affect the same active turn at the
  next model boundary.
- Multiple followups are still coalesced and answered once, in order.
- User `Message` rows remain durable and visible in the conversation timeline.
- No duplicate user-message persistence and no duplicate assistant responses.
- Existing queued-task behavior remains the fallback when the active turn has no
  model boundary before completion.

## Non-Goals

- Do not interrupt or cancel an in-flight provider stream in v1.
- Do not change public `/chat` response shape in v1.
- Do not implement native harness interruption for Codex/Claude runtimes in v1.
- Do not solve unrelated memory, skill, or prompt quality issues in this slice.

## Current State

- `/chat` calls `start_turn`; active sessions are protected by
  `session_locks`.
- If `start_turn` raises `SessionBusyError`, the route persists the new user
  message and creates or appends to a pending `Task` with:
  - `task_type="api"`
  - `execution_config.chat_burst=true`
  - `execution_config.burst_user_msg_ids=[...]`
  - `execution_config.pre_user_msg_id=<first queued message id>`
- The task worker later runs that `api` task after the session lock is free.
- `task_run_host` already carries queued burst images and recent image context
  into the fallback task path.
- `persist_turn` skips exactly one pre-persisted user message via
  `pre_user_msg_id`, but it does not yet skip arbitrary already-persisted
  late-user messages injected into the active model context.

## Design

### Late Input Service

Add a small service for normal chat burst absorption. Suggested home:
`app/services/chat_late_input.py`.

Responsibilities:

- Find pending `chat_burst` API tasks matching the active session, channel, and
  bot.
- Claim at most one task at a time inside a DB transaction.
- Only claim `status="pending"` tasks. If a task is already `running`, leave it
  alone.
- Mark claimed tasks terminal immediately so the task worker cannot answer them:
  - `status="complete"`
  - `completed_at=now`
  - `result="[absorbed into active turn]"`
  - `execution_config.absorbed_by_correlation_id=<active turn id>`
  - `execution_config.absorbed_at=<iso timestamp>`
  - `execution_config.absorbed_message_ids=[...]`
- Return ordered user messages and image attachment payloads for the active loop.

The service should not know about model prompting beyond returning a structured
bundle:

```python
@dataclass
class AbsorbedChatBurst:
    task_id: uuid.UUID
    message_ids: list[uuid.UUID]
    messages: list[Message]
    attachment_payloads: list[dict]
```

### Pre-LLM Drain Hook

Run the drain before each normal LLM call, including iteration 0 and later
iterations after tool results. Suggested integration point:
`app/agent/loop_pre_llm.py`.

If a burst is absorbed:

- Append a system note or hidden user-context preamble that says the user sent
  more messages while the agent was working and they should be considered now.
- Append each absorbed user message as a `role="user"` entry in order.
- Mark injected user messages with:
  - `_skip_persist=True`
  - `_internal_kind="late_chat_burst"`
  - `_source_message_id=<persisted message id>`
- Attach queued image payloads to model input using the same shape as normal
  image attachments. Preserve attachment IDs and MIME metadata.
- Emit a `late_chat_burst_absorbed` trace event with task id, message ids,
  iteration, attachment count, and whether the task was session-scoped.

This hook must only run for normal chat turns. It should be disabled for
heartbeat/task profiles unless explicitly opted in later.

### Persistence Contract

Update message persistence filtering so messages with `_skip_persist=True` are
never written to the database. The original queued `Message` rows are already
the durable records.

This is the key safety rule: the active loop may use late messages as model
context, but it must not create duplicate user rows.

### Fallback Path

If the active turn ends before a pre-LLM drain can claim the pending burst task,
the task remains `pending` and the existing task worker path answers it later.

This preserves current behavior for:

- one-shot text responses with no tool call;
- provider streams that do not return control until final response;
- harness-native turns not covered by this v1;
- any claim failure or DB error in the late-input drain.

### Observability

Add trace events:

- `late_chat_burst_absorbed`
  - `event_name="pre_llm"`
  - `count=<absorbed message count>`
  - data: task id, message ids, iteration, attachment count, session scoped,
    task scheduled age.
- `late_chat_burst_absorb_failed`
  - emitted only when a claim/drain failure occurs and the queued task remains
    as fallback.

Do not include message text, image bytes, base64, or secret-bearing payloads in
trace data.

## Edge Cases

- **Double answer:** the claimed task must become terminal before injected
  messages reach the model.
- **Task worker race:** claim pending tasks transactionally; never mutate a
  running task.
- **Duplicate persistence:** `_skip_persist` must be honored by `persist_turn`.
- **Ordering:** preserve `burst_user_msg_ids` order, not DB fetch order.
- **Attachments:** image payloads for queued messages must be deduped by
  attachment id and admitted without losing recent-image context behavior.
- **Session-scoped chat:** preserve suppress-outbox/external-delivery behavior.
- **Cancellation:** if the active turn is cancelled after absorbing messages,
  the absorbed task should remain terminal; the trace and task metadata are the
  evidence that the followups were consumed by the cancelled turn.
- **Multiple bursts:** drain at most one pending burst per pre-LLM checkpoint,
  then allow the next checkpoint to claim any later burst.
- **Model budget:** absorbed user messages increase the prompt. Existing prompt
  budget/pruning guards still run after drain and should remain authoritative.

## Implementation Slices

### Slice 1 - Durable Claim and Persistence Safety

- Add the late-input service with a transactionally claimed pending burst.
- Add `_skip_persist` support to `_filter_messages_to_persist`.
- Unit test claim success, no-op on running task, and `_skip_persist` filtering.

### Slice 2 - Loop Integration

- Wire the drain into the normal pre-LLM path.
- Inject ordered user context and queued image payloads.
- Emit `late_chat_burst_absorbed` trace events.
- Unit test that the next LLM call sees absorbed followups and the task is
  terminal before model continuation.

### Slice 3 - Fallback and Regression Coverage

- Prove existing queued task fallback still runs when no pre-LLM boundary occurs.
- Prove existing busy coalescing response shape is unchanged.
- Prove recent image context and queued image context still work.
- Add regression coverage for no duplicate assistant response.

## Test Plan

- `tests/unit/test_chat_late_input.py`
  - claims one matching pending burst task and marks it complete;
  - preserves `burst_user_msg_ids` ordering;
  - does not claim running or non-matching tasks;
  - returns image attachments without trace-unsafe payloads.
- `tests/unit/test_sessions_core_gaps.py` or equivalent
  - `_skip_persist` user messages are filtered.
- `tests/unit/test_loop_pre_llm.py`
  - absorbed messages are appended before the LLM iteration;
  - trace event contains ids/counts but no content/base64;
  - failures leave the queued task pending.
- `tests/integration/test_chat_202.py`
  - busy followups still return the same 202 queued/coalesced response shape.
- New integration coverage
  - a tool-loop turn absorbs followups after a tool result and produces one
    assistant answer;
  - a no-tool turn leaves the burst task to answer later;
  - queued image followup is visible to the active turn.

## Acceptance Criteria

- Live normal chat test: send message A that triggers a tool call, then B/C
  while A is running. The final assistant response incorporates B/C without a
  second queued assistant response later.
- Live fallback test: send A that produces a direct one-shot response, then B/C
  while A is running. The existing queued task answers B/C once after A.
- Trace inspection clearly distinguishes absorbed vs fallback behavior.
- No duplicate persisted user rows for absorbed messages.
- No changes to `.spindrel/WORKFLOW.md`.

