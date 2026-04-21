---
tags: [agent-server, track, architecture]
status: active
updated: 2026-04-20 (Phase 6 — message-anchored threads + in-channel scratch chat)
---

# Track — Task Sub-Sessions (pipeline-as-chat refactor)

## Phase 6 — Message-anchored threads + in-channel ephemeral (shipped 2026-04-20)

User ask: "lean into sessions" — reply-in-thread on any message forks a sub-session anchored at that message; separately, a scratch FAB on the channel page opens an ephemeral dock that never touches the main feed. Zero new rendering stack — all three surfaces (channel chat, thread dock, scratch dock) share `ChatSession` → `SessionChatView` → `ChatMessageArea`.

### What shipped

**Backend**
- Migration 229 adds `sessions.parent_message_id` (nullable FK, `ON DELETE SET NULL`) + `ix_sessions_parent_message_id`. New `SESSION_TYPE_THREAD = "thread"` constant.
- `spawn_thread_session()` in `app/services/sub_sessions.py` — resolves parent message → parent session → inherits parent-session walk-up (parent_session_id / root_session_id / depth+1). Seeds a `thread_context` system message with the parent + up to 5 preceding user/assistant messages, chronological order, per-message truncated to 800 chars, parent capped at 2000.
- `app/routers/api_v1_messages.py` — new router with three endpoints:
  - `POST /api/v1/messages/{id}/thread` — spawns thread session. `bot_id` defaults to the parent message's `metadata.bot_id` (assistant messages) or the channel's primary bot (user messages).
  - `GET /api/v1/messages/thread-summaries?message_ids=<csv>` — batched summaries keyed by `message_id`. `reply_count` counts user+assistant messages; `last_reply_preview` is truncated to 140 chars.
  - `GET /api/v1/messages/thread/{session_id}` — thread info (bot, parent preview, parent channel) for direct URL navigation to the full-screen route.
- `Session.messages` relationship + `Message.session` back_populate now pin `foreign_keys="Message.session_id"` to resolve the FK ambiguity introduced by `parent_message_id`.
- 17 new tests (`tests/unit/test_thread_sessions.py` + `tests/integration/test_api_messages_thread.py`) — all green alongside 32 existing sub-session tests.

**Frontend**
- New `ChatSource` variant `{ kind: "thread", threadSessionId, parentChannelId, parentMessageId, botId }` on `ChatSession`. New `ThreadChatSession` internal branch: streams via `SessionChatView`'s SSE pattern (parent-channel stream with `sessionFilter=threadSessionId`), composer submits under `session_id: threadSessionId`, Maximize navigates to `/channels/:channelId/threads/:threadSessionId`. No bot picker; `@botname` chip only.
- `ui/src/api/hooks/useThreads.ts` — `useSpawnThread` (mutation), `useThreadSummaries` (batched query, 15s staleTime, keyed on sorted visible message ids), `useThreadInfo` (single thread lookup for full-screen mount).
- `ThreadAnchor` — compact card styled after `SubSessionAnchor`: 💬 icon, "Thread · N replies · @bot", optional last-reply excerpt, chevron.
- `MessageBubble` gains `threadSummary` + `onReplyInThread` + `canReplyInThread` props. Renders `ThreadAnchor` beneath each bubble when a summary exists. `MessageActions` gets a new hover-row button gated on `canReplyInThread && onReplyInThread`.
- `ChatChannelPage` (`ui/app/(app)/channels/[channelId]/index.tsx`):
  - `useThreadSummaries(visibleMessageIds.slice(0, 50))` drives anchor rendering.
  - `handleReplyInThread(messageId)` — opens the existing thread from summaries or calls `spawnThread.mutateAsync` and sets `activeThread` state.
  - `<ChatSession source={{kind:"thread"}}>` mounts as a dock when `activeThread` is set.
  - Scratch FAB (`StickyNote` icon, bottom-right, z-30) mounts `<ChatSession source={{kind:"ephemeral", sessionStorageKey:"channel:${id}:scratch", ...}}>`. Gated behind "no active thread" so the two docks don't fight for the same corner.
  - `ChannelModalMount` extended: new `ThreadFullScreenMount` branch for `/channels/:channelId/threads/:threadSessionId`. Renders a full-viewport overlay with "Replying to: @bot: <preview>" header + X → navigates back to the channel. Body composes `SessionChatView` + `MessageInput` directly (not `shape="modal"`, which is a centered 820px card).
- Route `/channels/:channelId/threads/:threadSessionId` added to the router alongside the pipeline `runs/` + `pipelines/` sub-routes. Chat page stays mounted underneath (no tear-down on Maximize).

### Key decisions

- **Nesting is UI-only.** Backend `spawn_thread_session` walks `parent_session_id` regardless of depth; the `canReplyInThread` prop is false inside thread/ephemeral views so the hover action doesn't surface. Preserves optionality for future Slack-originated nested threads.
- **Bot default from parent author.** Assistant messages with `metadata.bot_id` spawn threads under that bot; user messages fall back to `channel.bot_id`. No picker on spawn — user can override by passing `bot_id` in the POST body.
- **Ephemeral ≠ thread.** Both are sub-sessions; threads get `session_type="thread"` + anchor cards, ephemerals stay `session_type="ephemeral"` + no parent-feed footprint. Unified storage, unified browser (via `list_sub_sessions`) when we add one.
- **Streaming-reliability fix.** Threads are channel-bound (via parent message → channel), so they ride the already-shipped channel-mode SSE pattern — same path as the pipeline run modal. The three parked dock bugs (4.0a / 4.0b / 4.0c) were channel-less ephemeral specific and do NOT block this phase.

### Scope explicitly deferred

- Slack `thread_ts` mirroring (Phase 7). Outbound: `Session.integration_thread_refs JSONB` + `integrations/slack/renderer.py` reads ref on dispatch. Inbound: map `(channel, thread_ts) → session_id` for routing. `integrations/slack/client.py::post_message` already accepts `thread_ts` — just not wired.
- Thread browser / drawer — wait for adoption signal. `list_sub_sessions` tool already exists; UI comes later.
- Mid-thread bot switching, nested threads in UI, thread @-mentions on the parent feed.

### Files

**Backend**: `migrations/versions/229_session_parent_message_id.py`, `app/db/models.py` (Session.parent_message_id + FK disambiguation on Session.messages / Message.session), `app/services/sub_sessions.py` (+spawn_thread_session, +SESSION_TYPE_THREAD, +THREAD_CONTEXT_PRECEDING), `app/routers/api_v1_messages.py` (new), `app/routers/api_v1.py` (register).

**Frontend**: `ui/src/components/chat/ThreadAnchor.tsx` (new), `ui/src/api/hooks/useThreads.ts` (new — useSpawnThread / useThreadSummaries / useThreadInfo), `ui/src/components/chat/ChatSession.tsx` (+ThreadChatSession branch + ChatSource variant), `ui/src/components/chat/MessageBubble.tsx` (+threadSummary / onReplyInThread / canReplyInThread), `ui/src/components/chat/MessageActions.tsx` (+MessageCircle button), `ui/src/router.tsx` (threads/:threadSessionId route), `ui/app/(app)/channels/[channelId]/index.tsx` (+activeThread state + scratch FAB + ThreadFullScreenMount + ThreadFullScreenBody).

Plan: `~/.claude/plans/transient-hatching-tarjan.md`.



## Phase 3.14 — `ChatSession` primitive + channel-mode dock (shipped 2026-04-20)

User ask: evolve `EphemeralSession` into a more general `ChatSession` component that can tap into any channel/session. First consumer: the channel widget dashboard at `/widgets/channel/:channelId` — its bottom-right dock should **be** the channel's chat, not a separate ephemeral. Maximize → full channel screen.

### What shipped

- **Renames** — `EphemeralSession.tsx` → `ChatSession.tsx`, `EphemeralSessionDock.tsx` → `ChatSessionDock.tsx`, `EphemeralSessionModal.tsx` → `ChatSessionModal.tsx`. Export names track the filenames. `PipelineRunModal` import path updated; behavior unchanged.
- **Source discriminator** — `ChatSession` props now take `source: { kind: "channel"; channelId } | { kind: "ephemeral"; ... }`. The controller dispatches to one of two internal components (`ChannelChatSession` / `EphemeralChatSession`) so hook calls stay stable across renders.
- **Channel mode** — new `useChannelChatSource(channelId)` hook (`ui/src/api/hooks/useChannelChatSource.ts`). Pulls `active_session_id` + `bot_id` via `useChannel`, subscribes to the channel's SSE with a session filter (identical to `useChannelChat`), fetches DB pages via `useInfiniteQuery(["session-messages", active_session_id])` — deduping with the full screen's query by key, submits via `useSubmitChat` with `channel_id`. Chat store slot keyed by `channelId` — shared with the full channel view.
- **Channel-mode header** — no bot picker (channel has a fixed bot; a subtle `@botname` chip shows instead). Maximize button navigates to `/channels/:channelId` (single behavior, no intermediate modal size). Reset button hidden (channel reset belongs to `/clear` on the full screen). Overhead dot reuses `useChannelConfigOverhead`.
- **Mount** — `ui/app/(app)/widgets/index.tsx` renders `<ChatSession source={{kind:"channel", channelId}} shape="dock">` when `isChannelScoped && !kiosk && !isMobile`. Commented-out ephemeral block + stale bookkeeping deleted.
- **Ephemeral mode** — unchanged behavior from the pre-rename `EphemeralSession`. Pipelines still render through `ChatSessionModal` (shape-only shell). Global-dashboard ephemeral mount stays deferred.

### Key decision

**Channel mode does NOT reuse `SessionChatView`.** SessionChatView owns its own SSE via `useSessionEvents` and routes dispatches under a non-channel key. Channel mode renders `ChatMessageArea` directly against the channel store slot — the same way the full channel screen does, minus the queue/slash/secret-check chrome.

### Files touched

- `ui/src/components/chat/ChatSession.tsx` (new — source discriminator)
- `ui/src/components/chat/ChatSessionDock.tsx` (rename of EphemeralSessionDock)
- `ui/src/components/chat/ChatSessionModal.tsx` (rename of EphemeralSessionModal)
- `ui/src/api/hooks/useChannelChatSource.ts` (new)
- `ui/app/(app)/channels/[channelId]/PipelineRunModal.tsx` (import rename)
- `ui/app/(app)/widgets/index.tsx` (mount + cleanup)
- Deleted: `ui/src/components/chat/EphemeralSession{,Dock,Modal}.tsx`

### Verification

- `cd ui && npx tsc --noEmit` — clean.
- Manual smoke on test server still pending (React #185 FAB-click reproduction + cross-page continuity + maximize navigation). Plan: `~/.claude/plans/hazy-growing-sketch.md`.

### Invariants preserved

- No parallel chat renderer — `ChatMessageArea` + `MessageInput` shared across channel-mode dock, ephemeral dock, and full channel screen.
- No backend changes, no DB, no migration.
- Channel chat store slot keyed by `channelId` — full screen and dock share it transparently.
- Pipeline modal chrome unchanged (Modal shell is shape-only).

### Scope explicitly deferred

- Re-enabling ephemeral dock on global (non-channel) widget dashboards — still blocked by §4.0a (first-turn streaming) + §4.0c (React #185 FAB loop) below.
- App-shell ephemeral dock across settings pages — Phase 4.1 (see below) now builds on `ChatSession`, not `EphemeralSession`.
- Queue / slash / secret-check in the dock composer — users keep the full channel screen for those.

## Phase 3.13 — Dock UX polish + streaming observer fix (shipped 2026-04-19)

Follow-up to Phase 3.12's channel-less dock. Cluster of fit-and-finish
issues the user hit on first real use, plus a real streaming regression
that was mis-scoped as "monitor only" in Phase 3.12.

| Phase | Area | Status |
|---|---|---|
| 3.13.1 | **Streaming observer timer now resets on every alive-proof event.** `useChannelEvents.ts` `OBSERVER_TURN_TIMEOUT` (60 s) was only being reset on `turn_started` / `llm_status`. Long tool calls + slow generations hit the timeout and force-finished still-live turns — symptom: tool badges appear, then progress disappears mid-turn, page refresh restores canonical content. Fix adds `startObserverTimeout(chId, turnId)` to `turn_stream_token`, `turn_stream_tool_start`, `turn_stream_tool_result`, `approval_requested`, `approval_resolved`, and `skill_auto_inject` branches. Affects all chat surfaces, not just the dock. | ✅ done |
| 3.13.2 | Single-row header inside body owns all actions (bot picker, overhead dot, expand, reset, close). `EphemeralSessionDock` stops painting its absolute X — no more overlap. `EphemeralSessionDock` expansion state lifted to controlled props (`expanded` + `onExpandedChange`) so the header X can collapse to FAB. | ✅ done |
| 3.13.3 | Expand-to-modal at runtime. Controller owns `mode: "dock" \| "modal"`; header's `Maximize2` button promotes dock → modal (reuses `EphemeralSessionModal` shell), `Minimize2` returns. Same session survives the transition. | ✅ done |
| 3.13.4 | Shared `BotPicker` (`ui/src/components/shared/BotPicker.tsx`) gained `compact` prop — 11 px trigger, no inline model badge (shown in the dropdown list instead). `EphemeralBotPicker` deleted. | ✅ done |
| 3.13.5 | Model override wired through. Controller owns `modelOverride` / `modelProviderId` state (persisted in `StoredEphemeralState` across reloads), forwards to `MessageInput` + `submitChat.mutateAsync({model_override, model_provider_id_override})`. | ✅ done |
| 3.13.6 | New `GET /api/v1/sessions/{id}/config-overhead` mirrors the channel endpoint; inherits channel overrides when session is channel-scoped, falls back to bot defaults for channel-less. `useSessionConfigOverhead` hook feeds `MessageInput.configOverhead` so the existing yellow/red dot renders in the dock. 2 new integration tests. | ✅ done |
| 3.13.7 | Reset (`RotateCcw`) has a two-click speed-bump — first click arms (red pulse, 3 s TTL), second click nukes. Prevents accidental session loss. | ✅ done |
| 3.13.8 | `isSending` in the dock now derives from `selectIsStreaming(chatState) \|\| submitChat.isPending` — the composer stays in streaming state through the entire backend turn, not just the POST round-trip. | ✅ done |

**Files:** `ui/src/api/hooks/useChannelEvents.ts` (observer fix), `ui/src/api/hooks/useEphemeralSession.ts` (+model override fields), `ui/src/api/hooks/useSessionConfigOverhead.ts` (new), `ui/src/components/shared/BotPicker.tsx` (compact), `ui/src/components/chat/EphemeralSession.tsx` (rewrite), `ui/src/components/chat/EphemeralSessionDock.tsx` (controlled expansion), `ui/src/components/chat/EphemeralSessionModal.tsx` (unchanged), `ui/src/components/chat/EphemeralBotPicker.tsx` (deleted). Backend: `app/routers/api_v1_sessions.py` (+config-overhead route), `tests/integration/test_api_sessions.py` (+TestSessionConfigOverhead).

**Closes §4.0a** — first-turn streaming should have been working all along; the reported failure was the same observer-timer bug on a long first turn.

## Phase 4 — Orchestrator "Home" redesign: settings lattice + ubiquitous ephemeral chat (PARKED 2026-04-20)

**Status: parked.** Superseded for now by the configurator skill path shipped 2026-04-20 (see [[Roadmap#Configurator skill + `propose_config_change` (2026-04-20)]] and `~/.claude/plans/scalable-prancing-music.md`). The skill-driven organic approach — "user asks in chat → skill loads → bot investigates + emits `propose_config_change` → user approves inline" — answers the same "configure the system conversationally" ask without needing the app-shell dock primitive, the route-level settings pages, or the `change_setting` tool from sub-phase 4.6.

Revisit Phase 4 only if the skill path falls over for use cases that genuinely need ambient chat bound to a specific settings page (e.g. a multi-turn investigation that benefits from staying mounted while the user tabs between Dreaming / Memory / Schedules views). The three ephemeral-dock bugs (§4.0a streaming, §4.0b model dropdown, §4.0c React #185) still block Phase 4 whenever it resumes — configurator doesn't need the dock, so they stay parked.

### Original plan (for reference if Phase 4 resumes)

**Big idea:** replace the orchestrator's standard channel chat view on the home/landing screen with a **lattice of domain pages** (Pipelines, Dreaming, Integrations, Memory, Schedules, etc.). Each page is light-chrome, shows its domain's settings/state, and mounts the **ephemeral session dock (bottom-right only)** pre-seeded with that page's context and a curated `tool_hints` list. The chat dock follows the user across pages — same session, context updates per page — and the bot can propose setting changes that surface through the existing approval UI before applying.

**Why now:**
- Phase 3 already proved the ephemeral dock pattern on the widget dashboard. Generalising to every settings page costs us one shell component, not a new primitive.
- The orchestrator home channel is increasingly a settings surface anyway (the audit pipelines ship tunables there). Treating the home as an app-shell of domain settings pages + one persistent assistant dock matches how the user actually uses it.
- Single write point for approvals: every setting mutation the ephemeral bot makes runs through one approval-gated tool, so we don't spread PATCH permissions across N tiny tools.

**North Star UX:**
1. `/` (orchestrator home) shows a gallery of tiles — one per domain page. No chat composer.
2. Each tile → `/settings/<domain>` with a light-chrome page (not full-width chat). Shows that domain's current state + controls.
3. Bottom-right `EphemeralSession shape="dock"` is mounted at the app shell level. Context updates on route change (`page_name`, current-page data snapshot, `tool_hints`). The session persists across navigation — user can start the dock on `/settings/dreaming`, navigate to `/settings/pipelines`, and the same assistant keeps the conversation with updated context.
4. The assistant can call a setting-mutation tool. Tool is `safety_tier="mutating"`; every call publishes an `APPROVAL_REQUESTED` event rendered in the dock's approval slot; user approves or denies in-dock; on approve, the patch applies and the page live-refreshes.

### Known Phase 3 bugs — fix BEFORE starting the redesign

These are regressions from Phase 3 / 3.12 that the user hit on the widget-dashboard dock on 2026-04-19. The app-shell generalisation in Phase 4 will amplify them — fix first.

- **4.0a — Streaming on the channel-less dock is broken.** User sent a message from the widget-dashboard dock, then had to refresh the page to see the assistant's reply. Symptom: SSE events for the first turn aren't reaching the dock. Likely cause: `EphemeralSession` spawns the session lazily on first send; `useSessionEvents(parentChannelId, sessionId)` only subscribes once `sessionId` is set (post-spawn). The subscription establishes AFTER the turn has started publishing to the bus under the new session_id — events are missed. Replay-on-reconnect covers SSE drops, but this is first-connect (no `since` cursor), so the buffer isn't consulted. **Fix options:** (a) establish the SSE subscription against the freshly-spawned session_id *before* firing POST /chat — e.g. spawn synchronously, wait for the subscription to connect, then submit; (b) refactor so the session is always spawned on mount rather than on first send; (c) after first-send, fetch `/sessions/{id}/events?since=0` so the replay buffer is read. (a) is the cleanest; (b) regresses the "no empty ghost sessions" guarantee; (c) is a retrofit band-aid. Phase 3.12 added the route + bus-key routing but didn't validate live streaming end-to-end — that's the gap.
- **4.0b — Ephemeral dock doesn't use the shared model dropdown.** `MessageInput` accepts `modelOverride` / `onModelOverrideChange` props and renders the shared `LlmModelDropdown` under those controls; `EphemeralSession.tsx` doesn't pass either — dock chat always runs on the bot's default model with no UI to override. Fix: wire `modelOverride` state (local useState + optional storage persistence) and forward both props into `MessageInput`. Also forward into `submitChat.mutateAsync({..., model_override, model_provider_id_override})` so the override actually reaches the backend. Phase 3.8 planned a bot picker but didn't mention the model picker — this is genuinely unscoped Phase 3 debt, not a new feature.
- **4.0c — React error #185 (Maximum update depth exceeded) on FAB click.** Clicking the bottom-right dock FAB on the widget dashboard throws React #185. Multiple fix attempts failed to identify the loop source. **Workaround applied 2026-04-19:** `<EphemeralSession>` commented out in `ui/app/(app)/widgets/index.tsx` — the FAB no longer renders. The component itself (`EphemeralSession.tsx`, hooks, stores) is untouched. Re-enable by uncommenting the import and JSX block once the loop is diagnosed. Suspect: something in the child tree (`BotPicker`, `MessageInput`, `TiptapChatInput`, or a Zustand selector) creates a new object reference on every render that feeds a `useEffect` dep, triggering an infinite setState cycle on first mount.

These three together are the "this doesn't work" signal on the Phase 3 dock MVP. Any Phase 4 consumer (home-screen app-shell dock, every settings-page mount) inherits these bugs until fixed.

### Sub-phases

| Phase | Area | Notes |
|---|---|---|
| 4.1 | **App-shell ephemeral dock.** Move `<EphemeralSession shape="dock">` out of `ui/app/(app)/widgets/index.tsx` into an app-shell component that mounts on every authenticated route. `context` is a route-derived value; the same session_id (from `sessionStorageKey="home"` or similar) survives navigation. | Relies on Phase 3.12 channel-less fix. |
| 4.2 | **Home page redesign.** New `ui/app/(app)/index.tsx` (or replace existing orchestrator-channel landing) with a tile gallery — one tile per domain page. Tile content: tiny live status (e.g. "Last dream: 2h ago"), domain icon, navigation link. No chat composer. | Requires a design call on the tile set. |
| 4.3 | **Domain settings pages.** Each page is a thin React file at `ui/app/(app)/settings/<domain>/index.tsx`, using a shared `<SettingsPageShell>` (title, breadcrumb, light chrome, no channel scroll). Candidates: `pipelines` (gallery with run/edit), `dreaming` (maintenance + skill_review cadence + last runs), `integrations`, `memory` (compaction knobs + memory hygiene cadence), `schedules` (cron-backed tasks + heartbeats), `providers` (LLM provider/model settings). | Many pages ALREADY exist under `/admin/*`. Phase 4.3 is mostly re-skinning them with the new shell. |
| 4.4 | **Per-page context feeder.** Each settings page computes its `EphemeralContextPayload` — `page_name`, `url`, a `payload` dict with the domain's current settings snapshot (read-only API call), and `tool_hints` naming the tools the bot should prefer for this domain. Wire via React context so the app-shell dock reads it without per-page plumbing. | Auth question: the page fetches settings with the user's JWT; the bot runs as the user-selected bot. The `payload` is the user's authoritative view; the bot reads it from the system message. No credential leak. |
| 4.5 | **Session portability across routes.** `sessionStorageKey` is stable across navigation. When the dock is mid-conversation and the user navigates, the context payload updates (the new page injects a fresh system message — reusing the `"ephemeral_context"` metadata.kind pattern) and the session keeps going. Open question: do we append or replace? Leaning toward **append with a visible `New context:` chip in the transcript** so the user can see what changed. | Needs a small backend addition: `POST /sessions/{id}/context` to append a new system message mid-session. Or we re-use the existing inject-message endpoint with `kind="ephemeral_context"`. |
| 4.6 | **Generic approval-gated setting tool.** New `change_setting(scope, target_id, field, value)` local tool. `scope ∈ {"bot", "channel", "integration", "provider", "workspace"}`. `safety_tier="mutating"`. Always requires approval — publishes `APPROVAL_REQUESTED` with a human-readable diff in the payload ("Set `crumb.tool_similarity_threshold` from 0.35 → 0.25"). On `APPROVED`, routes to a per-scope PATCH handler. Refuses scopes/fields the current bot isn't authorized for (bot-scoped keys shouldn't patch `workspace` fields). Audit pipeline whitelists become this tool's argument validator. | The audit pipelines already produce `{proposals: [...]}` — Phase 4.6 generalises that mechanism out of the pipeline `user_prompt` step into a chat-time tool. Existing pipeline path stays; new path is additive. |
| 4.7 | **Approval UI in the dock.** The dock already mounts `SessionChatView`, which already renders `APPROVAL_REQUESTED` events inline. Verify the render works in the dock's narrower (380px) layout; add a `pendingApprovalsSlot` render prop to the dock if a sticky header is needed. | Likely zero code — inline approvals already work in `ChatMessageArea`. |
| 4.8 | **Domain-specific helper tools.** On top of `change_setting`, each domain page can expose **read-only** helper tools scoped to its concern: `get_dreaming_state()`, `list_recent_runs()`, `get_provider_usage()`, `get_memory_inventory(bot_id)`. These land as `tool_hints` in the page's context so the bot fetches them first. No mutation power — they just assemble domain state into a compact summary the bot can reason over. | Each page's helper tool is small — scope creep risk. Cap at one read-tool per page unless the UX clearly needs more. |

### Open questions (for next session)

- **Session identity.** One home session or per-page? Leaning one (for continuity) with per-page `context` injection on navigation. If we need per-page isolation (e.g. `/settings/secrets` shouldn't leak into `/settings/pipelines`), switch to per-page sessionStorageKeys with a "bring last session along" action.
- **Which pages ship first?** Candidates with the clearest settings-shaped surface: Pipelines, Dreaming, Memory. Start with those three + the home tile gallery; everything else is follow-on.
- **Orchestrator channel fate.** Does the existing orchestrator Channel row still exist in the DB? We probably want to keep it as the implicit parent for audit pipelines, but hide its chat view. Or: the home ephemeral session reuses the orchestrator channel as its parent when ambient, and audit pipelines keep landing anchor cards there (invisible to the home UI, visible if the user ever navigates into the channel detail view).
- **Approval diff rendering.** `change_setting` needs a human-readable preview. Simple `before → after` text, or a structured diff viewer? Start with text; escalate if nested-object fields show up.
- **Settings authorization.** Most settings changes today require admin scope. The ephemeral bot won't have that by default. Decide: does `change_setting` elevate via approval-only (user's approval acts as the authz), or does the user need to explicitly pick an "admin-capable" bot from the dock's bot picker?

### Design invariants (preserved)

- Ephemeral session reuses Phase 3 primitives verbatim. No new parallel chat path.
- Approvals flow through the existing `tool_approvals` table + `APPROVAL_REQUESTED/RESOLVED` events. No new approval primitive.
- Setting mutations go through one tool (`change_setting`) with per-scope validator — not N per-setting tools.
- No new DB tables. No new auth primitive. This is pure UI rewiring + one local tool.

### References

- Phase 3 pattern: `ui/src/components/chat/EphemeralSession.tsx`, widget-dashboard consumer at `ui/app/(app)/widgets/index.tsx:464`
- Audit pipeline PATCH whitelist prior art: `app/data/system_pipelines/orchestrator.analyze_memory_quality.yaml` + siblings
- ToolApproval system: `app/routers/api_v1_approvals.py`, `app/domain/channel_events.py` (`APPROVAL_REQUESTED` / `APPROVAL_RESOLVED`)
- Existing admin settings endpoints: `app/routers/api_v1_admin/` (bots, channels, integrations, providers)

---

## Phase 5 — Pipeline run-view polish (disarray leftovers, parked)

Session 11 (`2026-04-19-11-pipeline-modal-disarray.md`) closed 4 visible bugs but left 3 pieces of UX polish that needed design calls, not code calls. Revisit when next pointed at the modal.

| Item | Notes |
|---|---|
| Step prompts render dense `MarkdownContent` | "Look a little nicer." Options: collapse by default behind a step-name chip, quieter-smaller-font variant. Needs design call. |
| Agent-step final responses lack step-card chrome | Tool steps get a step-card wrapper via `emit_step_output_message`; agent steps skip it — the child task's `persist_turn` writes the assistant Message directly. Would require stamping pipeline-step metadata on the assistant message + a new branch in `MessageBubble` (or `SessionChatView`) to wrap it. Needs design call. |
| `GET_TRACE` empty `[]` cards visually confusing | Analyze-memory-quality re-run may have resolved this after the yaml rewrite; verify on next run. Pure cosmetic if it persists. |

---

## Phase 3 — Extensible Ephemeral Session primitive (planned, 2026-04-19)

User ask: generalize the sub-session substrate so surfaces other than the pipeline wizard can summon an ad-hoc bot chat. First concrete consumer: the widget dashboard at `ui/app/(app)/widgets/index.tsx` — currently no way to ask a bot to create a widget without opening a channel first. Design is a reusable `<EphemeralSession>` with two display shapes (modal + bottom-right dock), a per-session bot picker with sticky localStorage default, and an optional `context={page_name, url, payload, tool_hints}` prop each calling surface supplies. Pipeline wizard migrates onto the same modal shell.

**Hard invariant:** ephemeral sessions reuse the exact `MessageInput` → `SessionChatView` → `ChatMessageArea` → `renderMessage` pipeline that powers channel chat and the pipeline wizard today. No parallel renderer, no parallel streaming path. Bug fixes land in one place. Only change to that tree is moving `ChatMessageArea` out of `channels/[channelId]/` and parameterizing the lone channel-specific element (`ChannelPendingApprovals`) as a slot prop.

Plan: `~/.claude/plans/snappy-honking-candle.md`.

| Phase | Area | Status |
|---|---|---|
| 3.1 | Backend: `spawn_ephemeral_session()` helper in `app/services/sub_sessions.py`; `SESSION_TYPE_EPHEMERAL` constant. (No migration needed — `sessions.session_type` is plain `Text` with no CHECK.) | ✅ done |
| 3.2 | Backend: new `POST /api/v1/sessions/ephemeral` router at `app/routers/api_v1_sessions.py`; register in `app/main.py`; context payload persisted as system message with `metadata.kind="ephemeral_context"`. | ✅ done |
| 3.3 | Backend tests: `tests/unit/test_sub_sessions.py` cases (with/without parent_channel_id, with context); `tests/integration/test_api_v1_sessions.py` happy path + auth. | ✅ done |
| 3.4 | Frontend relocation: move `ChatMessageArea.tsx` from `ui/app/(app)/channels/[channelId]/` to `ui/src/components/chat/`; replace `{channelId && <ChannelPendingApprovals/>}` with additive `pendingApprovalsSlot?: ReactNode` prop; rewrite imports in `ChannelChat` and `PipelineRunLive`. | ✅ done |
| 3.5 | New: `ui/src/components/chat/EphemeralSession.tsx` (controller — spawn-on-first-send, storage persistence, shape dispatch); reuses `SessionChatView` + `MessageInput` verbatim. | ✅ done |
| 3.6 | New: `ui/src/components/chat/EphemeralSessionModal.tsx` extracted from current `PipelineRunModal.tsx` portal shell; `PipelineRunModal` becomes a thin wrapper. No pipeline behavior change. | ✅ done |
| 3.7 | New: `ui/src/components/chat/EphemeralSessionDock.tsx` bottom-right pop-out (FAB collapsed / 380×560 expanded desktop / bottom-sheet mobile). | ✅ done |
| 3.8 | New: `ui/src/components/chat/EphemeralBotPicker.tsx` — Listbox, `useBots()`-backed, localStorage-sticky, disabled once session has messages (mid-session bot switching deferred). | ✅ done |
| 3.9 | New: `ui/src/api/hooks/useEphemeralSession.ts` — spawn mutation + session id resolution + storage key wiring. | ✅ done |
| 3.10 | Widget dashboard integration: mount `<EphemeralSession shape="dock">` in `ui/app/(app)/widgets/index.tsx` with `context={page_name, dashboard_slug, pinned_widget_ids, tool_hints}`. First non-pipeline consumer. | ✅ done |
| 3.11 | Verification: `cd ui && npx tsc --noEmit` clean. Backend tests: 64/64 sub_sessions + api_sessions + chat_202 + bus_bridge green on 2026-04-19. | ✅ done |
| 3.12 | **Channel-less dock unblock.** `TurnHandle.channel_id: Optional[UUID]` + `bus_key` property (falls back to session_id). `turn_worker.run_turn` uses bus_key for publish; gates outbox, multi-bot @-mention fanout, and delegation on `has_channel`. `_enqueue_sub_session_turn` removes the 400 and passes `channel_id=None` through. New SSE route `GET /api/v1/sessions/{id}/events` mirrors the channels one, keyed on session_id. UI: `useChannelEvents` gains `subscribePath: "channels" \| "sessions"`; `useSessionEvents` branches — channel-scoped stays on parent channel SSE with session_id filter, channel-less subscribes to the session SSE route. `SessionChatView.parentChannelId` now optional. `EphemeralSession` render guard relaxed to `sessionId` only. Regression test `test_channel_less_ephemeral_posts_with_null_channel_id`. | ✅ done 2026-04-19 |

**Deferred (explicitly not v1):** mid-session bot switching, right-side drawer and inline-expanding shapes, automatic DOM/route scraping for context, cross-device session sync, mounting the dock on all authenticated pages (only widget dashboard + pipeline modal migration in v1).

**Design invariants (preserved):**
- Sub-sessions remain `sessions.channel_id IS NULL`. Ephemeral sessions add `session_type="ephemeral"` and `source_task_id=NULL`.
- Parent-channel scoped auth still applies when `parent_channel_id` supplied; for channel-less surfaces (widget dashboard), authenticated user is sufficient.
- Bot workspace model unchanged — `/workspace/bots/<bot_id>/` is the bot's private area, `/workspace/` is shared; no new workspace binding for non-channel sessions.
- Render/streaming pipeline is single-implementation across channel, pipeline wizard, and ephemeral.

## Phase 2 — post-terminal composer + session-scoped chat (shipped 2026-04-19)

User ask: "unlock that input to allow user to type when pipeline finishes and interact with orchestrator on the same context? and maybe orchestrator has the tools to do ad hoc apply thats I have to approve?" Plan: `~/.claude/plans/linked-churning-cake.md`. Phase A + B shipped.

**Phase A — backend session-scoped chat entry:**

| Phase | Area | Status |
|---|---|---|
| A1 | `app/services/sub_session_bus.py` — new `SubSessionEntry` dataclass + `resolve_sub_session_entry()` that validates a session_id names a sub-session with a non-null parent channel + live source task. | ✅ done |
| A2 | `app/routers/chat/_helpers.py` — new `_try_resolve_sub_session_chat()` — detects sub-session POSTs, gates on terminal task status (409), parent-channel membership (403), forces `req.bot_id = task.bot_id`, loads Messages from the sub-session only (scope = sub-session history). | ✅ done |
| A3 | `app/routers/chat/_routes.py` — short-circuit branch in `_enqueue_chat_turn`: if resolver returns an entry, dispatch `_enqueue_sub_session_turn` instead of the regular channel-scoped flow. Returns 202 with `session_scoped:true`. | ✅ done |
| A4 | `TurnHandle.session_scoped` flag + `start_turn(session_scoped=...)` kwarg + `turn_worker` propagation so `persist_turn(suppress_outbox=True)` and `_persist_and_publish_user_message(suppress_outbox=True)` skip dispatcher fan-out. Follow-ups stay modal-only; Slack/Discord bindings don't receive them. | ✅ done |
| A5 | `app/domain/payloads.py` — `session_id` added to `TurnStreamTokenPayload` / `TurnStreamToolStartPayload` / `TurnStreamToolResultPayload` / `ApprovalRequestedPayload` / `ApprovalResolvedPayload` (default None for back-compat). `turn_event_emit.emit_run_stream_events()` accepts and stamps it so parent-chat UI filters drop them and the modal's session filter picks them up. `TurnStarted` / `TurnEnded` already had the field. | ✅ done |
| A6 | `app/services/sessions.py::persist_turn` — new `suppress_outbox=False` kwarg. Skips outbox enqueue when True; SSE bus publish still fires (via parent walk-up in the `_bus_channel is None` path, or directly when channel_id is the parent). | ✅ done |
| A7 | Tests: 9 new in `test_sub_sessions.py` (TestResolveSubSessionEntry × 5 + TestSubSessionChatResolver × 4). 3 new in `test_chat_202.py` (TestChatSubSessionFollowUp: terminal happy path, 409 on running, fallthrough for unknown session). 53 total green across phase A. | ✅ done |

**Phase B — frontend composer:**

| Phase | Area | Status |
|---|---|---|
| B1 | `ui/app/(app)/channels/[channelId]/PipelineRunLive.tsx` — disabled placeholder replaced with live `MessageInput` when `isTerminal`. Draft key = `runSessionId` (isolated from parent channel drafts). `handleSend` routes through `useSubmitChat` with `{session_id: runSessionId, bot_id: task.bot_id, client_id: "web"}`. Error banner surfaces server 4xx. | ✅ done |
| B2 | Streaming state reads from chat store slot keyed by `runSessionId` (already populated by `useSessionEvents` subscription — no additional wiring needed). | ✅ done |
| B3 | `tsc --noEmit` clean. | ✅ done |

**Why this was tractable:** Every piece the sub-session follow-up needed was already built. Bus bridge routes events to parent channel filtered by session_id (Phase 1 work). `SessionChatView` already mounts the real chat renderer on an arbitrary session_id. Tool approval already publishes via `resolve_bus_channel_id`. Chat store already keys by arbitrary string. `MessageInput` is self-contained. The new code is mostly the resolver / 409 gate / outbox suppression.

**Design invariants (preserved):**
- Sub-sessions remain non-channel-bound (`sessions.channel_id IS NULL`).
- Follow-up history = sub-session Messages only. No parent-channel splicing into the prompt.
- Approvals / tool calls / streams publish on parent bus with `session_id` tag so parent chat drops them and the modal catches them.
- External renderers (Slack/Discord) never receive follow-up turns.

**Phase C (shipped 2026-04-19):** Follow-up count hint on the parent anchor card. `SubSessionAnchor` in `ui/src/components/chat/TaskRunEnvelope.tsx` queries `useSessionMessages(run_session_id)` when `isTerminal`, counts user-role messages whose `metadata.sender_type !== "pipeline"` (pipeline step prompts are excluded), renders as `· N follow-ups` chip next to the step count. No backend changes.

**Phase D (shipped 2026-04-19):** Orchestrator-facing discovery tools. New `app/tools/local/sub_sessions.py`:
- `list_sub_sessions(channel_id?, limit?, only_with_follow_ups?)` — lists recent sub-session tasks on a channel with task_id, status, step count, follow-up count (non-pipeline user messages), and title. Defaults channel_id to the current ContextVar channel.
- `read_sub_session(session_id, limit?)` — renders header (task id/status/type/title, result excerpt or error) + messages in chronological order, labeling pipeline step prompts vs step-output vs user/assistant turns.

Registered via the auto-import in `app/tools/local/__init__.py`; no routing changes. Tests in `tests/unit/test_sub_session_discovery_tools.py` (7/7 green).

**Phase E (parked):** Mid-run push-back — composer active while a pipeline is still running. Requires step pause/resume in the backend and is a separate effort.

## Phase 1 completion — step output now uses real tool cards (2026-04-19)

Reported by user: the run-view modal was dumping `{"status": 200, "body": {...}}` as raw JSON for the `fetch_bot` step in `analyze_memory_quality`. Root cause: `emit_step_output_message` wrote only `content = state.result`; never built a `ToolResultEnvelope`, so `MessageBubble` skipped the `RichToolResult` path and fell through to `MarkdownContent`. This is explicitly the pipeline-as-chat invariant — sub-session view must reuse the chat rendering machinery, not reinvent it. Fix stamps a default envelope built by `_build_default_envelope(result_text)` onto `metadata.envelope` plus `metadata.source` for the header chip. JSON steps now get JsonTreeRenderer; markdown gets MarkdownContent; plain text gets TextRenderer — identical to how regular chat tool results render. Fix log entry has full detail.

**Future work (explicitly scoped out of this fix):**
- Currently we build a default envelope from the raw text. Tool steps that opt into structured `_envelope` payloads (via `_build_envelope_from_optin`) don't get that richer shape here because `_run_tool_step` uses `call_local_tool` and discards any opt-in metadata. Post-freeze, unify local + dispatched tool paths so step execution captures the real `ToolCallResult.envelope`.
- Eval and exec steps likely want mimetype-aware envelopes too (diffs, file listings). Covered by the same `_build_default_envelope` fallback for now.
- User stated this sub-session chat view should eventually evolve into a multi-purpose ephemeral-session thing (shared between pipeline runs, evals, and other short-lived contexts). Current abstraction already supports that — `SessionChatView` takes an arbitrary `sessionId` and `parentChannelId`.

## Phase 1 regression — modal stuck "Spinning up the run session..." (fixed 2026-04-19)

Child task created via `/run` returns with `run_session_id=null` (sub-session spawns lazily inside `run_task_pipeline → ensure_anchor_message`). `PipelineRunLive` called `useTask` once and the hook had no `refetchInterval` despite a comment claiming one existed. Without a re-fetch, the modal never picked up the populated `run_session_id` and never mounted `SessionChatView` — so SSE never got a chance either (the session filter needs the id first). Fix: `useTask(id, { refetchInterval })` now accepts a dynamic interval; `PipelineRunLive` polls 1.5s while `run_session_id` null, 3s while running, halts on terminal. See [[Fix Log]].

## Phase 1 regression — `run_session_id` propagation (fixed 2026-04-18, session 17)

User ran Analyze Discovery → modal opened → no live updates → closed → anchor progressed to "Your review needed" → reopened modal → empty ("Send a message to start the conversation"). Root cause: `ensure_anchor_message` mutated a re-fetched Task row (`t`) inside its own db session, but the caller's in-memory `task` (threaded through `run_task_pipeline` → `_advance_pipeline` → `_spawn_agent_step` / `emit_step_output_message`) stayed stale with `run_session_id=None`. Child agent-step tasks spawned with `session_id=None` → `load_or_create` created orphan throwaway sessions → every Message landed on a fresh random session_id instead of the one linked on `task.run_session_id`. Fix: mirror `task.run_session_id = t.run_session_id` onto the caller's object after `spawn_sub_session`. Regression test `tests/unit/test_task_run_anchor.py::TestEnsureAnchorMessageSubSession::test_sub_session_spawn_mirrors_run_session_id_to_caller`. See [[Fix Log]].

## Phase 1 — UI (shipped 2026-04-18)

| Phase | Area | Status |
|---|---|---|
| B1/B2 | Sub-session bus bridge: `app/services/sub_session_bus.py::resolve_bus_channel_id` walks `parent_session_id` to find the bus channel; `persist_turn` uses it when `channel_id` arg is None; `emit_step_output_message` publishes on the resolved channel; `_publish_turn_ended` + `TURN_STARTED` in `tasks.py` route sub-session pipeline children to the parent channel's bus (tagged with session_id in the payload) | ✅ done |
| B3 | `tests/unit/test_sub_session_bus_bridge.py` — 7 new tests + updated `test_persist_turn_publish_to_bus.py` to cover sub-session walkup + orphan drop | ✅ done |
| F1 | `useChannelEvents` gained `sessionFilter` + `dispatchChannelId` options; `useSessionEvents` thin wrapper subscribes to parent channel but dispatches under `runSessionId` | ✅ done |
| F2 | `ui/src/components/chat/SessionChatView.tsx` — read-only chat renderer for an arbitrary session_id; composes `useSessionMessages` + `useSessionEvents` + `ChatMessageArea` | ✅ done |
| F3 | `PipelineRunModal.tsx` — createPortal shell, large centered on desktop / full-screen on mobile, ESC + backdrop close, delegates to PreRun or Live panes by mode | ✅ done |
| F4 | `PipelineRunPreRun.tsx` — description + param form (via new shared `PipelineParamForm`) + Start button, navigates to `/runs/:taskId` on launch | ✅ done |
| F5 | `PipelineRunLive.tsx` — header with status pill + step counter + "Raw task" link; mounts `SessionChatView` against `task.run_session_id`; disabled-composer placeholder when non-terminal | ✅ done |
| F6 | `TaskRunEnvelope` branches on `run_isolation === "sub_session"` → new `SubSessionAnchor` component (terse card: icon · title · status · N steps · Open →, with summary excerpt when complete). Inline anchors untouched | ✅ done |
| F7 | `OrchestratorLaunchpad.handleLaunch` replaced: navigates to `/channels/:id/pipelines/:pipelineId`. Inline `TaskRunModal` component deleted | ✅ done |
| F8 | Router `channels/:channelId` gains `pipelines/:pipelineId` + `runs/:taskId` sub-routes; `ChannelModalMount` inside the channel page uses `useMatch` to mount the portal on top (chat subscription stays alive) | ✅ done |
| F9 | Backend: 195+ tests green (sub_sessions, bus_bridge, persist_turn_publish, channel_events, task_run_anchor, step_executor, tasks_core_gaps). UI: `tsc --noEmit` clean. Component tests deferred (no vitest config in ui yet) | ✅ done |

## Files touched — Phase 1

### Backend
- `app/services/sub_session_bus.py` (new) — parent-channel resolver
- `app/services/sub_sessions.py` — `emit_step_output_message` publishes on resolved bus
- `app/services/sessions.py` — `persist_turn` walks up for bus channel when arg is None
- `app/agent/tasks.py` — `_publish_turn_ended` (now async) + `TURN_STARTED` block route sub-session children to parent bus
- `app/routers/api_v1_admin/tasks.py` — `TaskDetailOut` surfaces `run_isolation` + `run_session_id`
- `tests/unit/test_sub_session_bus_bridge.py` (new) — 7 tests
- `tests/unit/test_persist_turn_publish_to_bus.py` — updated semantics

### Frontend
- `ui/src/api/hooks/useChannelEvents.ts` — `sessionFilter` + `dispatchChannelId` options
- `ui/src/api/hooks/useSessionEvents.ts` (new) — thin wrapper for sub-session SSE
- `ui/src/components/chat/SessionChatView.tsx` (new)
- `ui/src/components/shared/PipelineParamForm.tsx` (new, extracted from inline TaskRunModal)
- `ui/src/components/chat/TaskRunEnvelope.tsx` — `SubSessionAnchor` render branch
- `ui/src/api/hooks/useTasks.ts` — `TaskDetail` type gains `run_isolation` + `run_session_id`
- `ui/app/(app)/channels/[channelId]/PipelineRunModal.tsx` (new)
- `ui/app/(app)/channels/[channelId]/PipelineRunPreRun.tsx` (new)
- `ui/app/(app)/channels/[channelId]/PipelineRunLive.tsx` (new)
- `ui/app/(app)/channels/[channelId]/OrchestratorEmptyState.tsx` — tile wires to modal URL; inline TaskRunModal deleted
- `ui/app/(app)/channels/[channelId]/index.tsx` — `ChannelModalMount` mounts modal on sub-routes
- `ui/src/router.tsx` — two nested routes

## Phase 0 (backend groundwork, shipped 2026-04-18)

## North Star

A pipeline run IS a chat. Each step's work produces real Messages in a real Session; the run-view modal is just `ChatMessageArea` mounted on that sub-session. The parent channel sees one compact anchor card. Every rendering primitive — tool widgets, thinking blocks, approvals, Markdown, JSON — carries over for free. Generalized to all Tasks via opt-in `run_isolation` field; pipelines + evals default to `sub_session`, everything else stays `inline`.

Source plan: `~/.claude/plans/snazzy-gliding-rain.md` (approved 2026-04-18).

## Status

| Phase | Area | Status |
|---|---|---|
| 0.1 | Model + migration (Session.session_type, Task.run_isolation, Task.run_session_id, idx) | ✅ done 2026-04-18 |
| 0.1b | `spawn_sub_session(parent, bot, session_type)` helper (`app/services/sub_sessions.py`) | ✅ done 2026-04-18 |
| 0.2 | `step_executor` routes step output to sub-session when `run_isolation='sub_session'`; `emit_step_output_message` writes Messages for tool/exec/evaluate steps; agent steps go via child Task `session_id=run_session_id` | ✅ done 2026-04-18 |
| 0.3 | `task_run_anchor.py` slim metadata (drop embedded `steps[]`; carry `run_session_id`); auto-spawns sub-session on first `ensure_anchor_message` | ✅ done 2026-04-18 |
| 0.4 | `useSessionMessages(sessionId)` extracted to `ui/src/api/hooks/useSessionMessages.ts` | ✅ done 2026-04-18 |
| 0.5 | `ChatMessageArea` accepts `sessionId` prop + `mode: "channel" \| "ephemeral"` | 🟡 **deferred to Phase 1** — big refactor; hook scaffolding in place, actual ChatMessageArea split lands with the modal |
| 0.6 | `/sessions/{id}/messages` auth via parent; parent listing excludes sub-session rows | ✅ no-op — architecture already satisfies: router filters by `Message.session_id == session_id`, so sub-session rows can never leak into a parent-session listing |
| 0.7 | Parent-session context sees a summary of the run, not sub-session noise | ✅ done 2026-04-18 — `_fallback_text` enriched: for sub_session runs, the anchor Message.content includes a truncated result/error excerpt that the parent bot reads via ordinary history replay |
| 0.8 | `channel_events` payload carries `session_id`; parent subscribers drop sub-session events | ✅ no-op — Message payloads already carry session_id; child tasks run with `channel_id=None` so their turn events never publish to the parent channel bus |
| 0.9 | `TaskRunEnvelope` metadata types updated (`run_isolation`, `run_session_id`, `awaiting_count`); actual UI branch for sub_session anchors (open modal) | 🟡 types done; render branch lands with Phase 1 modal |
| 0.10 | Tests — 10 new tests in `test_sub_sessions.py` (spawn helper linkage, step-output message emission, metadata shape discrimination, fallback_text summary); 190 combined passing | ✅ done 2026-04-18 |

Phase 3 (interactive push-back) remains a separate plan — it needs backend step pause/resume + composer enable.

## Schema (landed 2026-04-18, migration 209)

- `sessions.session_type TEXT NOT NULL DEFAULT 'channel'` — `channel | pipeline_run | eval | …`
- `tasks.run_isolation TEXT NOT NULL DEFAULT 'inline'` — `inline | sub_session`
- `tasks.run_session_id UUID NULL FK→sessions ON DELETE SET NULL`
- Index `ix_sessions_parent_id_session_type` on `(parent_session_id, session_type)`
- Backfill: `task_type IN ('pipeline','eval') → run_isolation='sub_session'`

## Key invariants (non-negotiable across remaining phases)

- **Sub-session Messages never flood the parent transcript.** The UI fetches parent messages by `session_id` — sub-sessions have a different `session_id`, so the list endpoint naturally excludes them. The parent-session messages endpoint must stay scoped to exactly one session (no joining through `parent_session_id`).
- **Parent context assembly emits a summary, not raw sub-session Messages.** When `context_assembly` walks history and hits an anchor Message with `metadata_["run_session_id"]`, it emits one compact summary block into the prompt — never splices the sub-session's Messages in. Summary is cheap: terminal assistant text + Task.result, truncated to ~400 chars.
- **Inline Tasks are a no-op path.** `run_isolation='inline'` preserves today's behavior byte-for-byte. The gate lives at exactly one place in `step_executor` + `task_run_anchor`.
- **Historic anchor Messages keep rendering.** Old rows with embedded `metadata_["steps"]` arrays must continue to work; `TaskRunEnvelope` picks the renderer based on presence of `run_session_id` vs `steps[]`.
- **Don't add code paths that switch on `task_type == 'pipeline'`.** Gate on `run_isolation`. Pipelines are not special — they're Tasks that default to isolated.

## Why this matters

Today the pipeline tile on the Orchestrator channel launches runs that render as a one-line collapsed step summary inline in chat. You can't see the LLM's actual reasoning for `analyze`, the rich tool output of `fetch_traces`, or the intermediate state. No "cool" moment, no pre-run context. The naive fix (build a bespoke chat-style timeline inside a modal) would reinvent every primitive in `ChatMessageArea`. By treating the run as a real Session and mounting the real chat component on it, Phase 1's modal becomes almost-trivial UI work, and Phase 3's "push back on a step" is free (the composer is already there).

## What remains for Phase 1 (UI)

The backend is complete; sub-sessions spawn, routing works, parent-context summary is in place, migration is safe. Phase 1 is pure UI:

1. `PipelineRunModal` — portal + backdrop + pre-run (description + params + Start) / live / complete panes.
2. Split `ChatMessageArea` into `<ChannelShell>` + `<ChatMessageArea sessionId mode>` so the modal can mount the chat UI against an arbitrary sub-session. Pair with a `useSessionEvents(channelId, sessionFilter)` shim that filters `useChannelEvents` by `payload.session_id`.
3. Extend `TaskRunEnvelope` to render sub_session anchors as a terse card with "Open run" → opens modal at `run_session_id`. Legacy `steps[]` anchors keep their current render.
4. Wire `PipelineTile` click to open modal (pre-run for idle, live for active/awaiting).
5. `usePipelineModalStore` zustand store.

Everything in #2-5 uses data that already lands on the sub-session today (step_output Messages, child agent-step Messages, ToolApproval rows via existing paths). No further backend changes expected.

## References

- Plan: `~/.claude/plans/snazzy-gliding-rain.md`
- Migration: `migrations/versions/209_task_sub_sessions.py`
- Model changes: `app/db/models.py` — Session:293-309, Task:1100-1108
- Sub-session helper: `app/services/sub_sessions.py` (`spawn_sub_session`, `emit_step_output_message`, `resolve_sub_session`)
- Anchor changes: `app/services/task_run_anchor.py` — `_build_metadata` shape discrimination, `_fallback_text` summary enrichment, `ensure_anchor_message` auto-spawn
- Routing changes: `app/services/step_executor.py` — `_spawn_agent_step` session_id gate; `_advance_pipeline` emits step-output Messages for tool/exec/evaluate
- Tests: `tests/unit/test_sub_sessions.py` (10 new tests)
- Frontend hook: `ui/src/api/hooks/useSessionMessages.ts`
- Envelope types: `ui/src/components/chat/TaskRunEnvelope.tsx` (TaskRunMeta extended)
- Existing subagent pattern (template for sub-session spawn): `app/agent/tasks.py:905-911` (child session with parent + root + source_task_id)
- Eval ephemeral-session pattern: `app/services/eval_evaluator.py:_create_eval_task`
- Channel SSE: `app/services/channel_events.py`
