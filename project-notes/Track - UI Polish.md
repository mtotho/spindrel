---
tags: [agent-server, track, ui, polish]
status: in-progress
updated: 2026-04-22 (session-aware context headers + compaction metadata across chat/scratch surfaces)
---
# Track — UI Polish

## Motivation
Taking design inspiration from Google Stitch-generated mockups (see [[Stitch Design Reference]]). First pass focuses on the chat page — structural polish, not a full redesign.

## Pass 1: Stitch-Inspired Chat Polish (April 9, 2026)

### Completed
- [x] **Tonal surface depth** — tinted flat neutral grays with subtle blue temperature (dark: #0f1117, light: #f8f9fc). Tokens + CSS variables updated.
- [x] **Header + BadgeBar merge** — unified glass container with single bottom border, backdrop blur. Removed duplicate borders.
- [x] **Input area polish** — larger border-radius (16px), gradient send button (accent→purple), glass bg with backdrop blur, shadow instead of hard border.
- [x] **Typography tightening** — timestamps: uppercase + letter-spacing. Integration badges: uppercase + smaller font. Date separator: capped width, uppercase, wide tracking.
- [x] New `botMessageBg` token added to theme system (unused — bot accent was reverted)
- [x] **Mobile header cleanup** — hid workspace/participants buttons on mobile, smaller back/settings buttons
- [x] **Settings page header** — converted to web-native HTML, matches chat header glass style
- [x] **Context budget clickable** — clicking token numbers in header opens BotInfoPanel
- [x] **BotInfoPanel context budget** — shows live usage bar (% + tokens) with color coding
- [x] **BotInfoPanel footer link** — "View full context details" navigates to settings#context tab
- [x] **Message selection partial fix** — removed `userSelect: "none"` from message headers, added `pointer-events: none` to msg-actions overlay

### Reverted
- ~~Bot message accent (purple left border)~~ — looked like AI slop when every bot message in a conversation had it. Too heavy for conversations that are primarily bot responses.

### Rich Tool Rendering Follow-ups (from Phase A, session 18)
- [ ] **Markdown renderer dedup** — `MarkdownContent.tsx` and `MarkdownViewer.tsx` are two independent markdown parsers with overlapping coverage. Consolidate into one shared component. Low priority.
- [x] ~~**Pinned workspace-file panels (Phase B)**~~ — DONE (session 19, 2026-04-11).
- [ ] **`test_hard_cap_truncates_large_result` mock binding bug** — patch target should be `app.agent.tool_dispatch.settings` not `app.config.settings`.
- [ ] **Architecture Decisions entry**: "Tool results are envelopes, not strings" — write after Phase A validated on e2e.
- [ ] **E2E manual smoke**: deploy to `~/spindrel-e2e/` and validate: read → markdown inline, edit → diff, grep → file-listing, JSON → tree view, compact toggle.

### NOT Fixed — Open Bugs
- [ ] **Full message copy** — bot responses are split into multiple message records (one per streaming chunk or turn segment). There is no way to copy the entire bot response as one unit. Need a "Copy full response" action that concatenates all consecutive messages from the same bot turn.
- [x] **Cross-message text selection is glitchy** — ~~previously caused by `column-reverse` reversing DOM order.~~ **Fixed 2026-04-10** by keeping `column-reverse` on the *outer* scroll container (so the browser still pins the visual bottom natively) and moving the messages into a normal-flow inner `<div>` so DOM order matches visual order inside the wrapper. Best of both worlds: native text selection AND native pin-to-bottom, no JS scroll hacks. See `ChatMessageArea.tsx`.
- [x] **Chat starts scrolled up, then jumps down / stays stuck up** — ~~introduced when a previous session ripped out `column-reverse` and replaced it with imperative `scrollTop = scrollHeight` effects.~~ **Fixed 2026-04-10** as part of the same refactor. The JS scroll anchoring was racing image loads, streaming reflows, and prepend preservation logic; all of it deleted. Browser scroll-anchoring via `column-reverse` handles every case.

### Files Modified
- `ui/src/theme/tokens.ts` — tinted surfaces, new botMessageBg token
- `ui/global.css` — CSS variable updates, msg-actions pointer-events fix
- `ui/src/components/chat/MessageBubble.tsx` — timestamp treatment, removed userSelect:none from headers
- `ui/src/components/chat/StreamingIndicator.tsx` — removed userSelect:none from headers
- `ui/src/components/chat/BotInfoPanel.tsx` — context budget display, footer link to context tab
- `ui/src/components/chat/MessageInput.tsx` — glass bg, rounded editor, gradient send
- `ui/app/(app)/channels/[channelId]/index.tsx` — header wrapper, context budget click → BotInfoPanel
- `ui/app/(app)/channels/[channelId]/ChannelHeader.tsx` — removed border, mobile cleanup, clickable context budget
- `ui/app/(app)/channels/[channelId]/ActiveBadgeBar.tsx` — removed border, uppercase badges
- `ui/app/(app)/channels/[channelId]/ChatMessageArea.tsx` — date separator polish
- `ui/app/(app)/channels/[channelId]/settings.tsx` — header converted to glass style matching chat

### Memory Hygiene UI — Steps 4-6 (deferred from 2026-04-11)
- [ ] **Step 4**: global "next dreaming window" summary card on Overview + effective-schedule preview under Interval/Target Hour fields
- [ ] **Step 5**: cross-link InfoBanners between Settings ↔ Learning Center ↔ Bot admin dreaming surfaces
- [ ] **Step 6**: cadence drift health check (compares expected vs actual interval; would have auto-caught the 48h cadence bug)

### Not Yet Done
- [ ] Sidebar polish (out of scope for pass 1)
- [ ] Admin page polish
- [ ] Full color temperature shift (navy-tinted darks) — taste call, deferred
- [ ] Font family changes (Manrope headlines) — deferred
- [x] **Rich tool result rendering (Phase A)** ✅ 2026-04-11 — `ToolResultEnvelope` dataclass + dispatch wiring, 6 mimetype renderers (text/markdown/json/html/diff/file-listing), all 10 file ops migrated, session-scoped lazy-fetch endpoint, 36 new tests. Per-channel compact toggle in header. See session log 18. **Phase B (pinned panels)** is a follow-up in `.claude/plans/shimmering-fluttering-brook.md`.
- [ ] I should be able to stop a llm mid stream and not have the ui / or the llms context lost progress it made. IE if it was halfway doneand already streamed some messages.

## Pass 2: Channel Terminal Mode (2026-04-21)

### Shipped
- [x] **Per-channel terminal mode** — new `chat_mode` persisted in `channel.config` (`default` | `terminal`) and exposed in both public/admin channel settings APIs. No schema migration.
- [x] **Settings toggle** — General → Layout now includes a Chat mode selector so the channel owner/admin can switch between default chat and terminal mode.
- [x] **Chat feed swap** — `ChatMessageArea`, `MessageBubble`, and streaming indicators now accept `chatMode`; terminal mode renders a more transcript/log-oriented shell with monospace-forward styling and reduced bubble chrome while keeping approvals, widgets, threads, and tool output working.
- [x] **Command-first composer** — `MessageInput` and `TiptapChatInput` now support a terminal-mode variant: more compact control row, slash-command hinting, reduced visible chrome, same send/queue/attach/model plumbing underneath.
- [x] **Configurator parity** — `propose_config_change` now allows `chat_mode`, so the config-fix tool can flip channels into terminal mode using the same guardrails as `pipeline_mode` / `layout_mode`.
- [x] **Slash-command contract scaffolded** — `/api/v1/slash-commands` and `/api/v1/slash-commands/execute` now define a backend-owned result envelope so web, Slack, and CLI can converge on one command semantic layer instead of client-local behavior.
- [x] **`/context` rendered in chat** — web now inserts a synthetic transcript row for typed slash-command results, with a dedicated context-summary card in channel chat plus session/thread chat surfaces.
- [x] **Session/thread parity for slash commands** — chat-session surfaces no longer just advertise `/context`; they execute it against the shared backend contract and merge the synthetic result into the mounted transcript.
- [x] **Server-owned side-effect commands** — `/stop` and `/compact` now execute through the same slash-command API contract; web just applies the minimal local state sync after the server action lands.
- [x] **Client-only scratch shortcut** — `/scratch` stays web-local for now and jumps straight into the scratch-pad route instead of pretending to be a shared backend command.
- [x] **Scratch full-page warning folded into the real chat header** — removed the duplicate standalone scratch banner that was overlapping the header chip strip; scratch routes now show a compact header-owned state pill + amber subtitle in the channel header, with archive sessions rendered as muted read-only state instead of a warning.
- [x] **Scratch view context budget now respects the active session** — the header budget indicator no longer stays pinned to the channel's latest turn while you're inside scratch; backend `context-budget` endpoints now accept optional `session_id`, and the scratch route prefers the scratch session's live SSE budget/store slot plus a session-scoped fallback fetch.
- [x] **Scratch empty state now carries the guidance instead of the header** — removed the extra “messages here…” helper row from the scratch header and replaced the generic empty chat placeholder with scratch-specific copy/treatment in both docked and full-page scratch views.
- [x] **Tool-only streaming stays visibly alive** — `StreamingIndicator` now keeps a blinking cursor footer visible while a turn is still open but the only visible activity is tool cards / thinking / auto-injected skills. This closes the long-conversation “is it still streaming?” gap where repeated tool use hid every liveness affordance until the next text delta arrived.
- [x] **Terminal mode no longer drops assistant text on tool-call messages** — persisted assistant messages in terminal chat mode now render both the terminal tool transcript and the assistant markdown body. Previously the terminal transcript branch short-circuited the text render whenever `tool_calls`/tool envelopes were present, so tool-using replies looked like pure activity logs.
- [x] **Scratch menu reflects the selected session, not an internal "current" pointer** — `ScratchSessionMenu` no longer renders a special "Open current scratch" row or `Current` badges. The menu now shows only the context action (`Open mini chat` / `Return to channel`) plus a recent sessions list, and the backend list ordering was switched to `last_active DESC` so recents are truly activity-based rather than pinned by `is_current`.
- [x] **Live web chat now uses an ordered streaming transcript** — in-flight turns no longer render as separate “thinking section + tool section + text section” buckets. `ui/src/stores/chat.ts` now keeps ordered `transcriptEntries[]` for each live turn, and `StreamingIndicator.tsx` renders that sequence so tool activity stays interleaved with assistant text in the Codex/CUA style instead of grouping all tool cards at the end.
- [x] **Thinking moved to a collapsed top-of-turn block in web chat** — live reasoning stays visible when providers emit it, but it now renders as a compact expandable section above the assistant transcript rather than a permanently open inline dump. Synthetic turn-finalization also carries `metadata.thinking`, so the handoff from live streaming to the settled assistant message is consistent.
- [x] **Web settings copy no longer implies the integration-only thinking knob affects chat** — the channel General tab now labels `thinking_display` as `Integration thinking display` and explicitly says web chat uses the built-in transcript + collapsed thinking layout.
- [x] **Terminal mobile gutters tuned** — the terminal footer lane is now centered through the shared `ChatMessageArea` max-width wrapper, which gives mobile the same left/right gutter for the composer and model label that default chat already had without restyling the composer itself.
- [x] **Terminal input contrast tuned without restyling the composer** — terminal-mode `MessageInput` now uses a slightly brighter existing surface fill only. No border, radius, or footer chrome was added; the change is limited to making the input read a bit more clearly against the page background.
- [x] **Terminal streaming indicator reads like a console status line** — terminal-mode `StreamingIndicator` / `ProcessingIndicator` now render a monospace `(thinking...)` line with animated dots instead of the default bubble-style typing dots / lone blinking cursor whenever the turn is alive but text has not yet arrived.
- [x] **Channel-dashboard mini chat now inherits channel chat mode** — the bottom-right `ChatSession` dock on `/widgets/channel/:id` now threads `channel.config.chat_mode` through the shared chat surface, so terminal-mode channels render the same transcript/composer treatment in the mini chat instead of falling back to default mode.
- [x] **Desktop mini chat is user-resizable and sticky per surface** — `ChatSessionDock` now exposes a top-left resize affordance on desktop, clamps the dock within the viewport, persists the last chosen width/height in `localStorage` per chat surface (`channel`, `thread`, scratch/ephemeral), and uses a larger first-open desktop default (`500x728`) so fresh docks land closer to the intended working size. Mobile keeps the existing bottom-sheet behavior.
- [x] **Mini-chat terminal dock chrome tightened** — terminal-mode `ChatSessionDock` now drops the outer rounded-card treatment/border, uses a subtle header tint instead of a divider line, and gives the top-left resize affordance a visible corner-grip cue.
- [x] **Mini-chat composer now gets the real session plan state** — `ChatSession` channel/thread/ephemeral variants now query `useSessionPlanMode(sessionId)` and pass the same `planMode` / `hasPlan` / `planBusy` / toggle / approve props into `MessageInput`, restoring both terminal-mode plan affordances in docked mini chats instead of rendering nothing there.
- [x] **Mini-chat open animation no longer "snaps in" from mid-screen** — `chat-dock-expand-in` now uses a small bottom-right anchored translate/scale instead of a large viewport-center translate, so opening the dock no longer reads like it first mounted ~100px away from its final corner.
- [x] **Normal chat-screen loads no longer full-page fade after the skeleton swap** — `channels/[channelId]/index.tsx` now applies the screen animation only for the explicit `?from=dock` route transition. The old unconditional `.chat-fade-in` on every mount was causing the whole chat screen to briefly fade right after first paint on ordinary loads, which read as a white/dark "flash" once the page was already mostly visible.
- [x] **Persisted tool presentation contract** — `tool_calls` now carry server-derived `surface` + `summary`, persisted assistant `message.tool_calls[]` are normalized to include those fields, terminal transcript now prefers the normalized summary instead of re-deriving `Loaded skill`/file-diff semantics from raw blobs, and raw result/envelope data remain intact for rich rendering and deep inspection.
- [x] **Persisted tool presentation contract now owns the chat UI path** — default `MessageBubble` partitioning now prefers `tool_call.surface` over envelope heuristics, `ToolBadges` renders summary-first rows so file diffs show inline prettified hunks while file reads stay compact, and `SkillsInContextPanel` now recognizes loaded skills from normalized tool-call summaries before falling back to raw `get_skill` args.
- [x] **Live turns now reuse that same contract end-to-end** — typed `turn_stream_tool_start` / `turn_stream_tool_result` payloads now carry normalized `surface` + `summary`, the live chat store preserves them on `TurnState.toolCalls`, terminal streaming rows read the same summary contract as persisted rows, and `finishTurn()` now synthesizes `message.tool_calls[]` instead of a contract-less assistant message. This removes the streaming vs post-refresh split-brain for `Loaded skill`, file diffs, and widget/rich-result ownership.
- [x] **Refetched session history now keeps the normalized tool contract too** — `/api/v1/sessions/{id}/messages` was still serializing assistant rows through an older stripped `MessageOut` that dropped `tool_calls`, which is why file diffs vanished after refresh even though streaming looked right. The v1 session history serializer now returns `tool_calls`, `tool_call_id`, and `correlation_id`, so refreshed chat rows keep the same normalized tool presentation data as live/synthetic rows.
- [x] **Default and terminal persisted tool rows now share one semantic adapter** — the duplicated `ToolBadges` vs `TerminalToolTranscript` summary/diff/skill parsing has been collapsed into `toolTranscriptModel.ts`. Both modes now derive persisted file reads, file diffs, skill labels, and generic fallback rows from the same `tool_calls + tool_results` adapter, with only the final visual chrome differing between modes.
- [x] **Default live streaming now uses that same shared tool adapter too** — `StreamingIndicator` no longer renders default-mode tool rows through the old `SingleToolCallCard` / grouped-card path. Both default and terminal streaming now derive live tool rows from `buildLiveToolEntries(...)`, so file diffs, file reads, loaded-skill labels, approval rows, and fallback semantics are unified across streaming and persisted chat.
- [x] **Persisted terminal chat no longer drops rich-result tool rows that default chat still shows** — `MessageBubble` now partitions persisted tool rows into the same semantic groups for both chat modes, and `TerminalPersistedToolTranscript` renders the `rich_result` group instead of silently omitting it. Default vs terminal can still differ in component chrome, but they now receive the same owned tool-result sets.
- [x] **Rich tool results now adapt by renderer surface instead of chat-branch ownership** — `RichToolResult` now accepts a surface-level `rendererVariant` (`default-chat` vs `terminal-chat`), terminal chat renders rich envelopes through that shared renderer path instead of flattening them into transcript text, and interactive/widget HTML inherits terminal presentation via the same token pipeline instead of bespoke `MessageBubble` branching.
- [x] **Persisted tool rows no longer auto-open just because the message is latest** — removed the `ToolBadges`/`MessageBubble` "latest bot message" auto-expand path so per-tool display policy is again the only default-open rule: reads stay collapsed, edits keep inline diffs, and manual collapse no longer snaps back open on rerender.
- [x] **Terminal-mode typography tightened again after manual review** — reduced terminal transcript/body/code/thinking font sizes and explicitly applied the terminal font family to streaming thinking/content paths so live rows match the settled transcript more closely instead of briefly falling back to non-terminal typography.
- [x] **Persisted generic tool rows now resolve introspection targets and JSON summaries consistently** — `toolTranscriptModel.ts` now carries the looked-up tool name through `get_tool_info` rows (same shared adapter path used by both default and terminal chat) and emits a compact one-line summary for JSON-only envelopes, which fixes the old `get_current_local_time` split where one call rendered blank while a later one showed raw JSON only because the envelope shape differed.
- [x] **Persisted tool rendering now runs through one ordered shared model** — `toolTranscriptModel.ts` now builds `PersistedRenderItem[]` (`transcript` | `widget` | `rich_result` | `root_rich_result`) from the normalized persisted payload, `MessageBubble` consumes that model once for both chat modes, and widget-broadcast side effects now derive from the same ordered items instead of a separate inline-widget partition. For current rows, `message.tool_calls[]` is the source of truth for ownership and order; `metadata.envelope` is represented as one explicit root rich-result item instead of a separate mode-specific render lane.
- [x] **Default vs terminal persisted chat now differ only at row-shell presentation** — default chat still maps shared ordered items to `ToolBadges` / `WidgetCard` / `RichToolResult(rendererVariant="default-chat")`, terminal chat maps the exact same items to `TerminalPersistedToolTranscript` / terminal widget rows / `RichToolResult(rendererVariant="terminal-chat")`. `MessageBubble` no longer re-partitions tool ownership per mode. Remaining fallback heuristics for older envelope-only rows live only inside `toolTranscriptModel.ts`.
- [x] **Streamed and settled chat now share the same ordered transcript renderer** — the remaining mismatch was not in tool ownership but in the stream→settled handoff: live chat rendered ordered `transcriptEntries[]`, while settled chat flattened into `displayContent` + trailing tool items. `finishTurn()` now carries `metadata.transcript_entries`, new `OrderedTranscript.tsx` renders that sequence, and both `StreamingIndicator` and `MessageBubble` use it when present so tool/text interleaving and row styling survive the handoff.
- [x] **Canonical persisted assistant rows now keep the ordered transcript too** — the previous pass only fixed the optimistic synthetic message; as soon as the session refetch replaced it with the server row, ordering/style regressed because the backend never persisted `transcript_entries`. `app/agent/loop.py` now accumulates ordered text/tool entries during the turn, `persist_turn()` stores them in `message.metadata.transcript_entries`, list filters now keep assistant rows that only have transcript metadata, and settled chat can resolve transcript-owned tool rows by id or source order fallback when `tool_calls[]` is sparse.
- [x] **Terminal streaming header chrome now matches settled terminal rows more closely** — `StreamingIndicator` now uses the same `assistant:<name>` terminal naming treatment instead of a separate title shell, so the remaining streamed-vs-settled difference is pushed further down toward shared row renderers instead of the top-level wrapper.
- [x] **Current assistant turn bodies now render from one ordered model with no legacy reconstruction path** — `toolTranscriptModel.ts` now builds ordered turn-body items directly from `metadata.transcript_entries` plus canonical `message.tool_calls[]` / `metadata.tool_results`, and both `StreamingIndicator` and `MessageBubble` consume that same builder for current rows. `OrderedTranscript.tsx` no longer reconstructs tool semantics; it only maps already-classified items to default-vs-terminal shells. Transcript-positioned diffs/widgets/rich results therefore stay in-place after settle/refetch instead of collapsing back to a weaker transcript badge row.
- [x] **Current-row fallback heuristics were removed instead of preserved** — the new ordered current-turn builder does not read `tools_used`, does not do source-order fallback, and throws if `transcript_entries` reference a missing canonical tool call. Because the feature is unreleased, missing canonical tool/result data is treated as a producer bug rather than a compatibility case the UI should paper over.
- [x] **Ordered current-turn model now has a targeted UI harness** — added a small compile-and-run TypeScript test bundle around `toolTranscriptModel.ts` so this invariant is executable instead of purely visual. It checks transcript order, in-place rich/widget surface resolution, live-vs-persisted item parity, and the expected hard failure when canonical tool-call data is missing.
- [x] **Chat + scratch headers now follow the viewed session, not just the channel active session** — channel header, scratch full-page header, mini-chat/scratch subheaders, and the legacy context tracker widget now accept the selected `session_id` when present. Scratch/session views show the same live token counts as normal chat, plus compact turn metadata (`turns in ctx`, `until compact`) sourced from session diagnostics instead of guessing off the channel default session.

### Verification
- [x] `cd agent-server/ui && npx tsc --noEmit`
- [x] `cd agent-server/ui && timeout 20s ./node_modules/.bin/tsc --noEmit --pretty false`
- [x] `cd agent-server/ui && npx tsc --noEmit` after terminal-mode composer/indicator polish
- [x] `cd agent-server/ui && timeout 20s npx tsc --noEmit --pretty false` after dashboard mini-chat theme + dock resize persistence
- [x] `cd agent-server/ui && timeout 20s npx tsc --noEmit --pretty false` after terminal dock chrome + mini-chat session-plan composer wiring
- [x] `python -m py_compile app/routers/api_v1_channels.py app/routers/api_v1_admin/channels.py app/tools/local/propose_config_change.py`
- [x] `python -m py_compile app/services/slash_commands.py app/routers/api_v1_slash_commands.py tests/integration/test_slash_commands.py`
- [x] `cd agent-server/ui && ./node_modules/.bin/tsc --noEmit --pretty false` after summary/surface UI adoption
- [x] `cd /home/mtoth/personal/agent-server/ui && npx tsc --noEmit` after terminal typography + plan-question transcript widget wiring
- [x] `cd /home/mtoth/personal/agent-server/ui && npx tsc --noEmit` after session-aware context header + scratch session widget plumbing
- [x] `cd agent-server && pytest tests/unit/test_tool_presentation.py -q`
- [x] `cd agent-server && pytest tests/unit/test_turn_event_emit.py tests/unit/test_tool_presentation.py -q`
- [x] `cd agent-server && pytest tests/unit/test_api_v1_sessions_message_out.py tests/unit/test_turn_event_emit.py tests/unit/test_tool_presentation.py -q`
- [x] `python -m py_compile app/domain/payloads.py app/services/turn_event_emit.py app/agent/tool_dispatch.py`
- [x] `python -m py_compile app/routers/api_v1_sessions.py`
- [x] `cd agent-server/ui && ./node_modules/.bin/tsc --noEmit --pretty false` after live/persisted tool contract unification
- [x] `cd agent-server/ui && ./node_modules/.bin/tsc --noEmit --pretty false` after shared persisted tool-transcript adapter unification
- [x] `cd agent-server/ui && ./node_modules/.bin/tsc --noEmit --pretty false` after live default-tool transcript unification
- [x] `cd /home/mtoth/personal/agent-server/ui && npx tsc --noEmit` after renderer-variant split + persisted tool auto-open removal
- [x] `cd /home/mtoth/personal/agent-server/ui && timeout 20s npx tsc --noEmit --pretty false` after persisted ordered-item collapse in `MessageBubble`
- [x] `cd /home/mtoth/personal/agent-server/ui && timeout 20s npx tsc --noEmit --pretty false` after `transcript_entries` stream→settled parity fix
- [x] `cd /home/mtoth/personal/agent-server && pytest tests/unit/test_loop_helpers.py tests/unit/test_sessions.py -q`
- [x] `cd /home/mtoth/personal/agent-server/ui && timeout 20s npx tsc --noEmit --pretty false` after backend `transcript_entries` persistence + settled transcript fallback fix
- [x] `cd /home/mtoth/personal/agent-server/ui && npx tsc -p tsconfig.chat-tests.json`
- [x] `cd /home/mtoth/personal/agent-server/ui && node --test .chat-test-dist/components/chat/toolTranscriptModel.test.js`
- [x] `cd /home/mtoth/personal/agent-server/ui && timeout 30s npx tsc --noEmit --pretty false` after ordered current-turn model unification
- [ ] Targeted pytest remains flaky in this sandbox:
  `tests/e2e/scenarios/test_api_contract.py -k channel_settings_update` blocked on Docker socket permission.
  `tests/unit/test_propose_config_change.py -k chat_mode` timed out here without emitting a Python failure trace.
  `tests/integration/test_slash_commands.py -q` also stalled under the wrapper here without producing a Python failure trace.
- [ ] Follow-up scratch-copy polish verification remains wrapper-limited:
  `cd agent-server/ui && ./node_modules/.bin/tsc --noEmit --pretty false` did not report TypeScript errors here, but the sandbox command wrapper hung until `timeout 5s` terminated it.
- [ ] Session-aware context-header backend regression pytest is still wrapper-limited here:
  targeted `tests/integration/test_context_endpoints_public.py` / `test_context_breakdown_modes.py` runs exited ambiguously under the sandbox shell wrapper without surfacing Python pass/fail output, so manual rerun in a normal repo shell is still needed even though the new regression test was added.
