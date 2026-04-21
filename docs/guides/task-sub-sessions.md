# Task Sub-Sessions

A **sub-session** is a dedicated chat session that lives *inside* a parent channel. Pipeline runs, ephemeral ad-hoc chats, and (eventually) interactive agent runs all use the same primitive: a `Session` row with `channel_id=None` and `parent_session_id` pointing at an ancestor that is a channel session.

The model says: *a pipeline run is a conversation.* It has a transcript. It has tool calls, LLM thinking, rich widgets, Markdown output. The user can watch it live or come back to it later and scroll through. It just happens to be a conversation with one specific author (the pipeline) and a predetermined script (the pipeline's steps).

This guide explains how the sub-session primitive works, how events are routed between parent channels and sub-sessions, how the UI renders them, and how to hook into them.

---

## The mental model

```
Channel (channel_id=X)
└─ Session A (main channel session) ─── channel_id=X
   └─ Session B (sub-session — pipeline run)   channel_id=None, parent_session_id=A
      └─ Session C (eval/sandbox child of B)   channel_id=None, parent_session_id=B
```

- **Channel sessions** have `channel_id` set. That's the normal chat you type in.
- **Sub-sessions** have `channel_id=None` and a `parent_session_id`. They are reachable only through their parent; there is no independent URL to `/channels/none/...`.
- **The bus** for ambient streaming (SSE, typed events) is keyed by `channel_id`. So sub-sessions publish events on **the parent channel's bus**, tagged with their own `session_id`. Subscribers discriminate by payload.

Sub-sessions aren't a separate system: they use the same `Session`, `Message`, `ToolCall`, `Task`, and `TraceEvent` tables, the same agent loop, the same context assembly, the same tool dispatch. The only thing that differs is the routing layer on top.

---

## Anchor cards — the parent-channel view

When a pipeline run starts, the backend writes an **anchor Message** into the parent channel's transcript. It carries `metadata.kind = "task_run"` with enough information to render a compact card:

```
┌──────────────────────────────────────────────────┐
│  ⚙  Nightly Ingest Audit                         │
│  running · 3 of 5 steps · bot: curator           │
│  [ Open → ]                                      │
└──────────────────────────────────────────────────┘
```

Two anchor flavors exist:

| Flavor | When | Metadata |
|---|---|---|
| `run_isolation: "inline"` | Small, self-contained pipelines — steps embed as a summary array on the anchor itself | `steps[]`, `step_count` |
| `run_isolation: "sub_session"` | Full pipeline runs — the anchor is a **door**, not a transcript | `run_session_id`, `awaiting_count` |

A `sub_session` anchor is deliberately sparse. It gives you a tile ("3 steps · running · bot") and an **Open →** link. Clicking the link transitions to `/channels/<id>/runs/<taskId>` which mounts the run-view modal over the chat — you see the full transcript there, and the parent channel stays where it was.

See `ui/src/components/chat/TaskRunEnvelope.tsx` for the renderer. The renderer tolerates missing fields deliberately — a backend one release behind still produces a reasonable card.

---

## Two modal shells: run view + ephemeral dock

Sub-sessions surface in the UI through two shells, both built on a shared `EphemeralSessionModal` primitive (`ui/src/components/chat/EphemeralSessionModal.tsx`):

### Run modal — full-screen portal

Used for pipeline runs. Mounted on:

- `/channels/:channelId/pipelines/:pipelineId` → **pre-run**: description + param fields + Start button.
- `/channels/:channelId/runs/:taskId` → **live** (streaming) or **complete** (browse) transcript.

The portal shell (`PipelineRunModal.tsx`) routes between `PipelineRunPreRun` and `PipelineRunLive`. Closing the modal navigates back (history-aware — falls back to the parent channel if there's nothing to pop).

### Bottom-right dock — compact overlay

Used for ephemeral ad-hoc chats (e.g. the "ask a bot about this widget" panel on a widget dashboard). Same session primitive, different chrome — a small docked overlay in the bottom-right that doesn't take the screen. Implemented in `EphemeralSessionDock.tsx`.

As of the April 21 pass, scratch sessions also have a **history view** and a **server-owned current pointer** so the same scratch chat follows you across devices for a given `(user, channel)`.

Both shells reuse the **normal chat renderer** — `SessionChatView` + `ChatMessageArea` + `MessageInput`. There is no parallel streaming pipeline, no parallel renderer, no duplicate bus wiring. Message lists, thinking indicators, tool widgets, approvals — all behave the same as the parent channel.

---

## Event routing — `sub_session_bus`

The in-process channel event bus is keyed by `channel_id`. Sub-sessions don't have a `channel_id`, so `app/services/sub_session_bus.py` bridges them onto the parent channel's bus:

```python
# app/services/sub_session_bus.py
async def resolve_bus_channel_id(db, session_id) -> UUID | None:
    """Walks parent_session_id up to MAX_WALK_DEPTH levels until it finds
    a Session with channel_id set. Cycle-guarded."""
```

Every producer that emits events (`persist_turn`, `emit_step_output_message`, turn-lifecycle events in `tasks.py`) calls `resolve_bus_channel_id(db, session.id)` to find the bus it should publish on, and always stamps `session_id` on the payload.

### Subscribers discriminate by `session_id`

- **Parent channel view** — subscribes to the parent channel's bus via `useChannelEvents(channelId, { sessionFilter })`. Events where `payload.session_id !== parentSessionId` are **filtered out** (the channel doesn't want pipeline-child noise mixed into its chat).
- **Run-view modal** — mounts `useSessionEvents(runSessionId)`, which also subscribes to the parent channel's bus but keeps only events whose `payload.session_id === runSessionId`.

The key insight: one bus, two filters. That's how the same event stream feeds the channel chat and the N pipeline-run modals the user might have open, without fan-out duplication.

```
     ┌────────────────────────────────┐
     │  Parent channel bus (ch_X)     │
     └──────────┬────────────┬────────┘
                │            │
        drops   │            │  keeps
     session=B  │            │  session=B
                ▼            ▼
    ChannelChatView    PipelineRunLive
    (session=A only)   (session=B)
```

See `ui/src/api/hooks/useChannelEvents.ts` (with `sessionFilter`, `dispatchChannelId`) and `useSessionEvents.ts` for the subscriber side.

---

## Lifecycle: start → stream → settle

### 1. Tile click → pre-run modal

Clicking a pipeline tile in the launchpad routes to `/channels/:id/pipelines/:pipelineId`. The pre-run modal fetches the pipeline definition, renders its description and declared params, and waits for **Start**.

### 2. Start → child task created

POSTing to the run endpoint:
- creates a new **child Task** with `parent_task_id` set, `task_type="pipeline"`, and the resolved param values,
- creates a sub-session `Session` with `parent_session_id=<main channel session>`, `channel_id=None`,
- writes the sub-session anchor Message into the parent channel (`run_isolation="sub_session"`),
- starts the task loop.

The URL transitions to `/channels/:id/runs/:taskId` (the `replace: true` is deliberate — the pre-run modal isn't worth keeping in history).

### 3. Streaming transcript

`PipelineRunLive` mounts `useSessionEvents(runSessionId)` and renders the sub-session's message list. Every step's events (LLM thinking, tool calls, widget outputs, Markdown chunks) stream in as real `Message` rows on the sub-session. The parent channel sees none of it — only the anchor card updates to reflect `running` / `completed` status.

### 4. Settle — browsable transcript

When the task finishes, the live modal transitions to a browsable transcript. The anchor card in the parent channel updates (`completed`, duration, optional `result` preview). The transcript is permanent — the user can reopen `/channels/:id/runs/:taskId` days later and scroll through the whole run.

---

## Follow-up turns — posting back to a sub-session

The chat router supports a `session_id` parameter to target a follow-up turn at a specific sub-session instead of the parent channel's active session. `resolve_sub_session_entry` (in `sub_session_bus.py`) validates that the target is a sub-session and extracts its parent + source task for authorization.

Today this is used for:

- **Ephemeral sessions** (`session_type="ephemeral"`) — composer is always enabled; the user types freely to whatever bot is assigned to the ephemeral session (widget-dashboard ad-hoc chat, etc.).
- **Pipeline runs** — composer is **disabled** in the live transcript. A future phase adds an interactive **push-back composer** (backed by a step pause/resume primitive) so a user can answer a pipeline's `user_prompt` step or nudge a running agent step mid-run. The session model is ready for it today; the UI gate is not yet lifted.

---

## Scratch sessions — current pointer + history

Scratch sessions are the main user-facing ephemeral sub-session today. They are no longer just a client-local modal state; the server owns a **current scratch session** per `(user, channel)` and keeps older scratch sessions queryable.

### Current scratch session

`GET /api/v1/sessions/scratch/current` resolves or creates the current scratch session for:

- the authenticated user
- the current channel
- the selected bot

That means the scratch panel you open on desktop is the same scratch conversation you can reopen on another device later.

### Reset

`POST /api/v1/sessions/scratch/reset` archives the current scratch session and spawns a fresh one. The old conversation does not disappear; it simply leaves the "current" slot.

### History

`GET /api/v1/sessions/scratch/list` returns newest-first scratch history for the current user/channel pair. The UI exposes this via `ScratchHistoryModal`, and older sessions open in a read-only `ScratchViewer` route at:

`/channels/:channelId/scratch/:sessionId`

This is intentionally different from the live dock:

- **Current scratch** = interactive, docked, composer enabled
- **Scratch history entry** = browsable transcript, no composer

### Why the pointer lives on the server

The old localStorage-only model broke down across devices and tabs. The DB-backed `is_current` pointer makes scratch feel like a first-class conversation surface instead of a per-browser toy.

---

## Ephemeral skill / tool injection

Pipeline steps can declare ephemeral skills or tools in their `execution_config` that apply to the agent runs inside the sub-session only:

```yaml
- type: agent
  prompt: "Summarize the week's incidents."
  execution_config:
    skills: [bots/incident-reviewer/triage-playbook]
    tools:  [search_channel_archive, get_trace]
```

The task loop calls `set_ephemeral_skills(...)` and the context assembler injects them as "Webhook skill context" — **scoped to this sub-session's turns only**, no enrollment on the bot, no leakage into the parent channel's other sessions. See [Bot-Authored Skills → Ephemeral Skill Injection](bot-skills.md#ephemeral-skill-injection-pipelines-tasks-and--tags) for the full mechanism.

---

## Why this design

1. **One renderer.** Reusing `SessionChatView` / `ChatMessageArea` / `MessageInput` means any improvement to the chat renderer — new widget types, better scroll behavior, accessibility fixes — immediately applies to pipeline runs and ephemeral chats too. No parallel maintenance.
2. **One bus.** Subscribers see the same event stream whether they're watching the channel or a pipeline. The discriminator is `payload.session_id`, not a separate transport.
3. **One data model.** Pipeline messages are `Message` rows. Step outputs are `Message` rows. Tool calls are `ToolCall` rows. Everything the rest of the system already knows how to load, search, compact, and render — works.
4. **Parent-channel visibility is cheap.** The anchor card is one Message. If the user never opens the run, they never load the sub-session's transcript; nothing about the model forces pre-fetching.

---

## Reference

| What | Where |
|---|---|
| Sub-session bus bridge | `app/services/sub_session_bus.py` |
| Task loop event routing | `app/agent/tasks.py` (search `resolve_bus_channel_id`) |
| Anchor Message writer | `app/services/task_run_anchor.py` |
| Run modal shell | `ui/app/(app)/channels/[channelId]/PipelineRunModal.tsx` |
| Pre-run shell | `ui/app/(app)/channels/[channelId]/PipelineRunPreRun.tsx` |
| Live shell | `ui/app/(app)/channels/[channelId]/PipelineRunLive.tsx` |
| Shared modal primitive | `ui/src/components/chat/EphemeralSessionModal.tsx` |
| Bottom-right dock | `ui/src/components/chat/EphemeralSessionDock.tsx` |
| Scratch history modal | `ui/src/components/chat/ScratchHistoryModal.tsx` |
| Scratch viewer route | `ui/app/(app)/channels/[channelId]/ScratchViewer.tsx` |
| Anchor renderer | `ui/src/components/chat/TaskRunEnvelope.tsx` |
| Channel event hook (filter) | `ui/src/api/hooks/useChannelEvents.ts` |
| Session event hook | `ui/src/api/hooks/useSessionEvents.ts` |
| Scratch hooks | `ui/src/api/hooks/useEphemeralSession.ts` |

## See also

- [Pipelines](pipelines.md) — step types, scheduling, the task engine.
- [Bot-Authored Skills](bot-skills.md#ephemeral-skill-injection-pipelines-tasks-and--tags) — ephemeral skill injection scoped to a sub-session.
- [Chat History](chat-history.md) — how messages and sessions persist; how rehydration works on reconnect.
- [Delegation](delegation.md) — `delegate_to_agent` vs sub-agents vs pipeline sub-sessions — when to use each.
