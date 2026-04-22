---
tags: [agent-server, track, ui, polish]
status: in-progress
updated: 2026-04-22 (mini chat inherits chat mode, terminal dock chrome tightened, session-plan composer affordances restored)
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

### Verification
- [x] `cd agent-server/ui && npx tsc --noEmit`
- [x] `cd agent-server/ui && timeout 20s ./node_modules/.bin/tsc --noEmit --pretty false`
- [x] `cd agent-server/ui && npx tsc --noEmit` after terminal-mode composer/indicator polish
- [x] `cd agent-server/ui && timeout 20s npx tsc --noEmit --pretty false` after dashboard mini-chat theme + dock resize persistence
- [x] `cd agent-server/ui && timeout 20s npx tsc --noEmit --pretty false` after terminal dock chrome + mini-chat session-plan composer wiring
- [x] `python -m py_compile app/routers/api_v1_channels.py app/routers/api_v1_admin/channels.py app/tools/local/propose_config_change.py`
- [x] `python -m py_compile app/services/slash_commands.py app/routers/api_v1_slash_commands.py tests/integration/test_slash_commands.py`
- [ ] Targeted pytest remains flaky in this sandbox:
  `tests/e2e/scenarios/test_api_contract.py -k channel_settings_update` blocked on Docker socket permission.
  `tests/unit/test_propose_config_change.py -k chat_mode` timed out here without emitting a Python failure trace.
  `tests/integration/test_slash_commands.py -q` also stalled under the wrapper here without producing a Python failure trace.
- [ ] Follow-up scratch-copy polish verification remains wrapper-limited:
  `cd agent-server/ui && ./node_modules/.bin/tsc --noEmit --pretty false` did not report TypeScript errors here, but the sandbox command wrapper hung until `timeout 5s` terminated it.
