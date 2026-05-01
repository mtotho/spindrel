---
tags: [spindrel, track, ui, polish]
status: in-progress
updated: 2026-04-29 (channel tabs, harness terminal polish)
---
# Track — UI Polish

## Motivation
Taking design inspiration from Google Stitch-generated mockups (see [[Stitch Design Reference]]). First pass focuses on the chat page — structural polish, not a full redesign.

## Shared Control System Reset (2026-04-24)

- [x] Added canonical `SelectDropdown` and migrated the shared model, bot, channel, tool, workflow, and static select wrappers onto it so dropdown chrome, width, selected state, and search behavior are no longer rebuilt per picker.
- [x] Continued dropdown consolidation across prompt templates, task step editing, widget preset configuration, pin-scope bot choice, and widget schema enum/boolean fields so future visual refinements land in the shared primitive.
- [x] Started the Automation > Tasks pass by moving recurrence units, skill chips, and tool multi-pickers to `SelectDropdown`, and lowering the date-time picker popover chrome.
- [x] Promoted date/time controls into the shared catalog: quiet hours now uses `TimePicker` instead of native `type=time`, and `DateTimePicker` has a lower-chrome selected-summary/calendar/quick-pick surface.
- [x] Continued the Memory tab pass by constraining full-row select/model popovers and moving Backfill, Archived Sections, Section Index preview, and Compaction Activity onto shared low-chrome action/status/row primitives.
- [x] Cleaned up Participants by moving primary/member rows and the add-bot picker to shared row/action/pill primitives.
- [x] Clarified Member Bots passive-context behavior in settings and docs so @-mention routing is not confused with isolation from memory compaction or dreaming/learning.
- [x] Swept channel routing / passive-memory copy across Agent and Participants settings plus Slack/Discord/BlueBubbles docs so active reply routing is consistently described separately from passive context absorption.
- [x] Completed a channel-settings consistency sweep: Sessions, Logs, Context preview, Knowledge workspace controls, Tasks filters, Pipeline subscriptions, integration add-ons/bindings, and integration picker rows now use shared low-chrome primitives where the old one-off controls were visually inconsistent.
- [x] Corrected the banner rule: semantic left-border alert stripes are now banned in `ui-design.md` / `spindrel-ui`, and shared `InfoBanner` renders tonal notes without side borders.
- [x] Added the load-stability rule: settings loading states must reserve the final layout footprint instead of using spinner-only swaps that make tabs bounce; Heartbeat now uses a stable low-chrome loading shell.
- [x] Reframed `/admin/learning` as Memory & Knowledge with Overview, Memory, Knowledge, History, Dreaming, and Skills tabs; added read-first unified search across bot memory, bot KB, channel KB, and archived conversation history.
- [x] Cleaned up the missed Dreaming tab/table path: `DreamingBotTable` now uses shared low-chrome empty/pill/badge/action primitives, Tailwind design tokens, no `useThemeTokens()` / inline hex/RGBA, and clear amber vs purple job-type signaling for maintenance vs skill review. Follow-up pattern check replaced the dense table with per-bot rows containing two job lanes; this remains experimental and should not be canonized until the same shape proves useful on at least one other settings/admin surface.
- [x] Updated the Dreaming Recent Runs list to the same compact shared expandable-row style, removing the older inline `useThemeTokens()` implementation from `HygieneHistoryList`.
- [x] Refreshed `/admin/machines` and `/admin/integrations` against the canonical control-surface standard: shared token/Tailwind controls, no route-level `useThemeTokens()`, no inline hex/RGBA, lower-chrome rows/sections, and machine-control provider detail kept summary/link-only.
- [x] Added shared `EmptyState` for low-chrome empty surfaces and moved the new Memory & Knowledge page onto existing shared controls instead of one-off dropdowns/buttons.
- [x] Added shared read-only `SourceFileInspector` and wired Memory & Knowledge file-backed memory/KB rows to open their actual workspace source file in-page; non-file fallbacks now say `Open location`, not `Open source`. Follow-up sweep added inline panel mode and moved read-only bot/channel knowledge-base previews onto the same component; editable file managers and linked prompt editors intentionally stay on richer editor/viewer surfaces.
- [x] Retuned global light-mode neutral tokens so low-chrome shared controls read with more surface depth without adding a second accent or page-local decorative fills.
- [x] Started the post-theme integration detail density pass: high-volume detected asset/env-var chip groups now collapse behind overflow controls, and capability chips read as metadata instead of accent-colored state.
- [x] Added shared `SourceTextEditor` for literal YAML/JSON/code strings and moved the integration manifest YAML tab off its raw textarea while keeping file-inspector ownership separate.
- [x] Rebuilt `/admin/skills` as the canonical fleet-wide skill library: shared low-chrome controls, source-grouped folder tree, advisory frontmatter warnings, read-first detail preview, shared `SourceTextEditor` source inspection, and read-only script summaries from the admin skills API.
- [x] Reframed `/admin/usage` around anomaly investigation instead of billing-only reporting: stat health strip, token timeline markers, trace-burst/top-contributor signals, source/channel filters, shared `TraceInspector` drilldowns, and low-chrome trend charts.
- [x] Added canonical `TraceInspector` and token-driven chart guidance to `ui-components.md` so usage, task, heartbeat, and debugging drilldowns have one shared trace preview path.
- [x] Corrected trace inspection into a global modal drawer instead of a page-local sticky panel: `TraceInspectorRoot` now portals from `AppShell`, usage/traces rows call the global opener, and the drawer/full trace page share one low-chrome `TraceTimeline` renderer.
- [x] Promoted trace drilldowns into a shared action: `TraceActionButton` / `openTraceInspector` now cover user-facing trace buttons across usage alerts, tasks, workflows, channel logs, heartbeat history, dreaming runs, and chat actions, while direct `/admin/logs/:id` navigation remains only for explicit full-page/open-location affordances.
- [x] Refreshed the stale `/admin/usage` Forecast, Limits, and Alerts tabs after the anomaly-dashboard pass: shared settings rows/actions/selects, canonical current/projected meters, trace evidence buttons, and no page-local `useThemeTokens()` in those refreshed tabs.
- [x] Added `SettingsMeter` as the shared current/projected progress primitive and documented that cost/quota/capacity surfaces should use it instead of local progress-bar implementations.
- [x] Rebuilt the settings foundation: `/settings` is now one nested shell with role-aware redirect, Account owns personal/device preferences, Channels/Bots are catalog-first self-service pages, and admin System moved to a domain-first control center with an Advanced registry fallback. Palette/admin deep links now target `/settings/system#...` instead of the retired generic page. The System page now has Overview domain cards plus per-domain stat/link headers so settings stay tied to canonical admin workflow surfaces.
- [x] Fixed `/settings/system` save discoverability: server setting drafts now live at the page level, with Save/Revert in the System header and a sticky Save control beside the domain tabs so Advanced registry edits remain savable while scrolled.
- [x] Restored the shared prompt-setting control on the new System settings page: built-in defaults now render inside a muted read-only prompt window with an explicit Customize path, and custom prompts use the shared `PromptEditor` instead of raw textareas.
- [x] Removed channel-settings autosave from long-lived config drafts: channel settings now keep local changes until explicit Save/Revert, and Heartbeat participates in the same page-level Save/Revert owner so prompt text is not mutated by background PATCH/refetch cycles while typing. `Run Now` remains an explicit heartbeat-local action and is disabled until unsaved heartbeat edits are saved.
- [ ] Follow-up: tighten remaining channel-settings loading shells until skeleton/control placeholders exactly match final content footprint. Heartbeat is improved but still shows minor residual layout movement on some loads.
- [x] Added canonical `PromptEditor` while preserving `LlmPrompt` as the compatibility entrypoint; prompt fields now default to a larger resizable editor with fullscreen expansion and quiet generate controls.
- [x] Added `docs/guides/ui-components.md` and wired `ui-design.md` / `spindrel-ui` skill to require the shared component catalog before creating selectors or prompt editors.
- [x] Reduced Knowledge tab guide-panel density by replacing repeated faded tiles with compact definition rows.
- [x] Trimmed the command palette browse defaults so per-channel `Settings · #channel` entries stay searchable and recent-eligible but no longer appear beside every `Chat · #channel` row in the empty Ctrl+K listing.
- [x] Collapsed noisy command-palette detail families in the empty browse view: tool detail rows, policy detail rows, and recent trace rows now sit behind `Show ...` toggles, while typed search bypasses the collapse and queries the full catalog.
- [x] Reduced typed command-palette tool spam: individual `Tool · name` admin detail pages no longer appear in typed search, while the single top-level Tools page matches installed tool names through hidden search aliases. Channel matches rank above the Tools aggregate for tool-family names like `jell`.
- [x] Tightened mobile/channel palette ergonomics: channel chat rows now render as `#channel` while still matching `chat` in search, channel hamburger drawers default to Jump unless that channel has a remembered tab, empty widget drawers fall through to Jump, and the browse-mode `This Channel` action group shows the first four actions behind a `Show more` toggle.
- [x] Clarified the composer plan control: inactive chat now shows `Start plan` / `Resume plan` as direct actions, while active plan modes show semantic status labels (`Planning`, `Executing`, `Blocked`, `Done`) and keep the dropdown only for active-mode actions.
- [x] Fixed terminal-mode mobile tool rows: result previews no longer force horizontal page scroll, and the primary tool label stays intact while secondary path/preview text truncates within the row.
- [x] Fixed mobile file-tool path overflow: generic file-tool rows now keep operation labels separate from long workspace paths, target paths left-truncate to show the end-most segment, and the row wraps within chat width instead of forcing horizontal page scroll.
- [x] Fixed `/find` chat jumps: default search now matches the active visible session, `--all` makes broader channel-session search explicit, and result clicks load older pages until the target message is mounted before scrolling/highlighting.
- [x] Added desktop channel session tabs sourced from local browser recents, with stable user-reorderable ordering, instant ghost-preview drag, quiet primary/unread indication, immediate pending feedback, saved conjoined split-layout tabs, a right-click split/unsplit action menu, close-to-hide behavior, docs screenshots, and an inline session chooser when every recent tab is hidden.
- [x] Folded channel workspace files into the same top tab strip: opening a file selects/adds a file tab instead of forcing split, file tabs can explicitly split right, direct `open_file=notes/...` links resolve through channel file endpoints, and the screenshot harness now captures the loaded file-tab split state.
- [x] Reworked tab overflow to a VS Code-like single-row model: new files/sessions/splits open at the front, hidden tabs live behind a right-side overflow menu, Explorer `Alt`-click opens files split, and chat file links open the same file tabs.
- [x] Added session-tab rename to the right-click menu and made `Unsplit to` dissolve saved split tabs instead of leaving the conjoined tab behind.
- [x] Portaled the tab overflow menu above channel content and fixed file-tree row markup so delete actions are no longer nested buttons.

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
- [ ] **Step 5**: cross-link InfoBanners between Settings ↔ Memory & Knowledge ↔ Bot admin dreaming surfaces
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
- [x] **Slash-command requests now honor the composer surface** — web previously POSTed both `channel_id` and `session_id` whenever a channel chat also had an active session, which tripped the backend's intentional `Exactly one of channel_id or session_id is required` guard and made `/compact` fail with 422. `useSlashCommandExecutor` now routes through a pure `buildSlashCommandExecuteBody(...)` helper so channel chat sends only `channel_id`, session/thread chat sends only `session_id`, and the contract is pinned by a focused node test.
- [x] **Manual and auto compaction now persist visible operation rows** — `/compact` now creates/reuses a `metadata.kind="compaction_run"` assistant row, queues behind an active turn, updates through the existing `new_message` / `message_updated` bus path, and auto compaction uses the same durable row model. These rows survive refresh but are excluded from model reload, future compaction input, and live-history accounting.
- [x] **Compaction rows now render as live status cards instead of generic fallback panels** — `compaction_run` rows bypass the normal assistant-row suppression while turns are streaming, patch in place on `message_updated`, and carry the actual compaction summary so the feed shows `Compacting...` immediately and expands into the persisted summary/result once complete.
- [x] **Post-compaction header/context totals no longer stay pinned to pre-compaction API usage** — `fetch_latest_context_budget()` now treats any `token_usage` snapshot older than a newer `compaction_done` trace as stale, falls back to a fresh next-turn estimate from the compacted state, and the channel SSE hook invalidates `session-header-stats` plus `channel-context-breakdown` when `compaction_run` rows arrive/update so the header and Context tab refresh immediately instead of sitting on a 60s cache window.
- [x] **Client-only scratch shortcut** — `/scratch` stays web-local for now and jumps straight into the scratch-pad route instead of pretending to be a shared backend command.
- [x] **Scratch full-page warning folded into the real chat header** — removed the duplicate standalone scratch banner that was overlapping the header chip strip; scratch routes now show a compact header-owned state pill + amber subtitle in the channel header, with archive sessions rendered as muted read-only state instead of a warning.
- [x] **Scratch view context budget now respects the active session** — the header budget indicator no longer stays pinned to the channel's latest turn while you're inside scratch; backend `context-budget` endpoints now accept optional `session_id`, and the scratch route prefers the scratch session's live SSE budget/store slot plus a session-scoped fallback fetch.
- [x] **Channel context breakdown now accepts scratch sessions linked via `parent_channel_id`** — `compute_context_breakdown()` no longer rejects ephemeral scratch sessions whose `channel_id` is null but whose `parent_channel_id` matches the channel, so scratch Context tab / header fetches stop throwing false “session does not belong to channel” 422s.
- [x] **History tab copy now matches the real compaction policy with lower-chrome styling** — the channel History settings surface now uses quieter panels instead of stacked warning/code blocks, and the helper text explains interval vs keep-turns vs early token guards consistently across file/structured/summary modes. The canonical guide now also spells out the ratio / live-token / total-utilization guard interaction with the current defaults.
- [x] **Channel settings now have one canonical IA across chat and dashboard** — `/channels/:id/settings` is now the canonical home with tabs grouped by ownership (`Channel`, `Agent`, `Presentation`, `Knowledge`, `Memory`, `Automation`, plus read-only `Context` / `Logs`). The old `General` monolith was split into reusable sections so dashboard appearance, agent behavior, and channel identity no longer live in one catch-all tab.
- [x] **Channel dashboards now point back into canonical settings without duplicating channel config** — `/widgets/channel/:id/settings` redirects to `settings#presentation`, the dashboard action row now links there directly, and the channel-dashboard drawer was narrowed to quick layout controls plus a Presentation deep-link instead of surfacing channel name/icon/config as if the dashboard owned them.
- [x] **Settings docs modal is now shared instead of duplicated** — channel Memory/History, integration guide, and widget-authoring docs all use one shared markdown docs modal primitive so new settings help can reuse the same low-chrome pattern instead of minting one-off guide panels or duplicate modal implementations.
- [x] **Settings tabs no longer trap browser Back by pushing hash history on every tab click** — `useHashTab` now writes hashes with `replaceState`, so switching tabs inside `/channels/:id/settings` behaves like in-page state while preserving direct `#tab` deep links.
- [x] **Channel settings now use one shared save signal instead of a tiny flashing success hint plus a special Heartbeat save button** — the header now shows a durable save-status pill (`Changes pending`, `Saving changes`, `Saved`, `Save failed`), and Heartbeat moved onto the same debounced auto-save model as the rest of channel settings while keeping `Run Now` explicit.
- [x] **The low-chrome settings shell is now driven more by spacing than divider lines** — shared `Section`, `SelectInput`, and `ActionButton` primitives were tightened: no per-section top rule, smaller radii, styled select chevrons, quieter secondary actions, and pill-shaped status chrome. This is the current baseline for channel settings surfaces.
- [x] **Editable channel settings surfaces now share a more consistent low-chrome control language** — the shared form/control primitives were retuned again so inputs, selects, badges, and buttons all sit on the same smaller radius scale, with quieter focus rings and less dashboard-like card treatment across editable settings tabs.
- [x] **Integrations no longer mix autosave flashes with bespoke row chrome** — activation config fields now surface one inline autosave status (`Saving changes...` / `Save failed` / `Saves automatically`) instead of per-field green "Saved" flashes, and dispatcher bindings now use the shared action-button treatment for `Add`, `Edit`, `Remove`, and in-place forms so the bindings list no longer reads like a different app embedded in settings.
- [x] **Channel / Automation / Knowledge cleanup removed several older one-off controls** — tag chips, the danger zone, heartbeat mode switching, heartbeat template reset, attachment stats/rows, and attachment delete affordances now use the same lower-chrome spacing/radius language instead of older raw buttons and raised mini-cards.
- [x] **The channel dashboard quick-controls drawer now reads as a sibling surface, not an older side panel** — the drawer kept its narrowed layout-only role, but its presentation-settings link, preset rows, maintenance/error blocks, and footer actions now use the same lower-radius action treatment as canonical channel settings.
- [x] **Knowledge + Integrations cleanup landed in the new settings language** — Attachments is now a proper settings section with stat tiles + grouped actions instead of a loose horizontal strip, dispatcher bindings keep `Add Binding` inside the section it belongs to, and channel workspace browse affordances were toned down to match the rest of settings.
- [x] **Knowledge tab now centers the actual channel knowledge base instead of the generic workspace tree** — `/channels/:id/settings#knowledge` now lists the real `knowledge-base/` contents with breadcrumb navigation, preview, and retrieval/search guidance, and the workspace deep-link uses a durable `?path=` contract because the admin workspace page's mount reset was wiping any pre-expanded store state.
- [x] **Knowledge-base guidance now matches the actual retrieval model** — the Knowledge tab, `context-management.md`, and the bot-facing `knowledge_bases` skill now distinguish channel KB vs bot KB vs `memory.md` vs broader workspace search. Channel KB remains channel-scoped and bot KB is now auto-retrieved by default as a lower-priority reusable layer, with a bot-level search-only toggle for cases where implicit bot KB should stay off.
- [x] **Bot workspace now has a first-class knowledge-base surface instead of a banner** — bot admin workspace settings now show the real bot-KB path, retrieval mode, file list/preview, and workspace deep-link so the channel Knowledge tab can cross-link to a concrete bot-owned KB surface rather than referring users to an implicit convention they cannot inspect.
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
- [x] **Chat generic rich-result chrome is now chat-shell aware** — `RichToolResult` gained a chat-only `chromeMode` split (`standalone` vs `embedded`) so the same generic result body can render borderless inside chat-owned shells without changing non-chat mounts. `OrderedTranscript` / expanded transcript rows now opt into embedded mode, which removes the default-chat double-border around generic tool results while keeping tight diff/file-listing blocks on their existing single-frame path.
- [x] **Terminal generic rich results now render as flatter transcript-adjacent blocks** — the shared generic text/JSON/file-listing/html renderers now respect terminal-vs-default presentation when embedded in chat. This specifically fixes the remaining terminal mismatch where rows like `Loaded skill` / `Got current local time` still opened into web-card chrome even after the ordered assistant-body/renderer-path unification.
- [x] **Inline tool errors now preserve rich/widget ownership instead of collapsing to transcript rows** — `app/services/tool_presentation.py` now checks the envelope before applying the generic error fallback, so inline widget errors (notably `web_search`) stay `surface="widget"` and inline rich-result errors stay `surface="rich_result"` across streaming, synthetic settle, and refetched persisted rows. Focused regressions now pin both the backend event payload and the shared chat `toolTranscriptModel` parity path.
- [x] **Terminal chat now gives widget-owned tool rows a terminal shell instead of falling back to default web-card chrome** — `OrderedTranscript` now threads `chatMode` into `WidgetCard`, and HTML widgets render through `InteractiveHtmlRenderer(hostSurface="plain")` in terminal mode so streamed `web_search`/widget envelopes no longer flash the default-mode card treatment before settle.
- [x] **Persisted fetches no longer replace richer live assistant rows with weaker DB copies** — `useChannelChatSource` now merges fetched rows through `sessionMessageSync.ts`, which keeps a synthetic assistant row alive when the refetched row only matches on `correlation_id`/content prefix but has fewer structured render items (`widget` / `rich_result`). This specifically prevents live widget/rich rows from vanishing into flat assistant text while persistence catches up.
- [x] **Chat-test Node emit now handles the new settle-reconcile helper** — `sessionMessageSync.ts` uses explicit local `.js` imports so the focused `.chat-test-dist` Node harness can execute the new reconciliation tests without ESM resolution failures.
- [x] **Persisted tool rendering now runs through one ordered shared model** — `toolTranscriptModel.ts` now builds `PersistedRenderItem[]` (`transcript` | `widget` | `rich_result` | `root_rich_result`) from the normalized persisted payload, `MessageBubble` consumes that model once for both chat modes, and widget-broadcast side effects now derive from the same ordered items instead of a separate inline-widget partition. For current rows, `message.tool_calls[]` is the source of truth for ownership and order; `metadata.envelope` is represented as one explicit root rich-result item instead of a separate mode-specific render lane.
- [x] **Default vs terminal persisted chat now differ only at row-shell presentation** — default chat still maps shared ordered items to `ToolBadges` / `WidgetCard` / `RichToolResult(rendererVariant="default-chat")`, terminal chat maps the exact same items to `TerminalPersistedToolTranscript` / terminal widget rows / `RichToolResult(rendererVariant="terminal-chat")`. `MessageBubble` no longer re-partitions tool ownership per mode. Remaining fallback heuristics for older envelope-only rows live only inside `toolTranscriptModel.ts`.
- [x] **Streamed and settled chat now share the same ordered transcript renderer** — the remaining mismatch was not in tool ownership but in the stream→settled handoff: live chat rendered ordered `transcriptEntries[]`, while settled chat flattened into `displayContent` + trailing tool items. `finishTurn()` now carries `metadata.transcript_entries`, new `OrderedTranscript.tsx` renders that sequence, and both `StreamingIndicator` and `MessageBubble` use it when present so tool/text interleaving and row styling survive the handoff.
- [x] **Canonical persisted assistant rows now keep the ordered transcript too** — the previous pass only fixed the optimistic synthetic message; as soon as the session refetch replaced it with the server row, ordering/style regressed because the backend never persisted `transcript_entries`. `app/agent/loop.py` now accumulates ordered text/tool entries during the turn, `persist_turn()` stores them in `message.metadata.transcript_entries`, list filters now keep assistant rows that only have transcript metadata, and settled chat can resolve transcript-owned tool rows by id or source order fallback when `tool_calls[]` is sparse.
- [x] **Terminal streaming header chrome now matches settled terminal rows more closely** — `StreamingIndicator` now uses the same `assistant:<name>` terminal naming treatment instead of a separate title shell, so the remaining streamed-vs-settled difference is pushed further down toward shared row renderers instead of the top-level wrapper.
- [x] **Current assistant turn bodies now render from one ordered model with no legacy reconstruction path** — `toolTranscriptModel.ts` now builds ordered turn-body items directly from `metadata.transcript_entries` plus canonical `message.tool_calls[]` / `metadata.tool_results`, and both `StreamingIndicator` and `MessageBubble` consume that same builder for current rows. `OrderedTranscript.tsx` no longer reconstructs tool semantics; it only maps already-classified items to default-vs-terminal shells. Transcript-positioned diffs/widgets/rich results therefore stay in-place after settle/refetch instead of collapsing back to a weaker transcript badge row.
- [x] **Current-row fallback heuristics were removed instead of preserved** — the new ordered current-turn builder does not read `tools_used`, does not do source-order fallback, and throws if `transcript_entries` reference a missing canonical tool call. Because the feature is unreleased, missing canonical tool/result data is treated as a producer bug rather than a compatibility case the UI should paper over.
- [x] **Ordered current-turn model now has a targeted UI harness** — added a small compile-and-run TypeScript test bundle around `toolTranscriptModel.ts` so this invariant is executable instead of purely visual. It checks transcript order, in-place rich/widget surface resolution, live-vs-persisted item parity, and the expected hard failure when canonical tool-call data is missing.
- [x] **Chat + scratch headers now follow the viewed session, not just the channel active session** — channel header, scratch full-page header, mini-chat/scratch subheaders, and the legacy context tracker widget now accept the selected `session_id` when present. Scratch/session views show the same live token counts as normal chat, plus compact turn metadata (`turns in ctx`, `until compact`) sourced from session diagnostics instead of guessing off the channel default session.
- [x] **Scratch full-page header now favors route clarity over session-preview noise** — the channel header on `/channels/:id/session/:sid?scratch=true` now keeps the normal context subtitle bits visible (`tokens`, `turns in ctx`, `until compact`), shortens the top-row badge to `Scratch`, and stops replacing the subtitle with long scratch preview/summary text. The scratch session's title/timestamp/counts remain available as tooltip/session-menu metadata instead of dominating the header chrome.
- [x] **Primary/session header chrome now survives partial session-budget data** — full-page session routes use subtle `Primary` vs `Session` labeling instead of leaning on “scratch” branding, the header shows token usage even when only gross/current prompt usage is available (`18K tok` instead of hiding the metric entirely), and the route identity line now favors `Session + last active timestamp + compacted explicit title` so long generated titles stop taking over the page header.
- [x] **Session-route context numbers now come from the real session trace stream, not only `channel_id`-bound rows** — the missing token count on `/channels/:id/session/:sid?scratch=true` was not just UI fallback; `fetch_latest_context_budget()` only looked at `Session.channel_id == channel`, so scratch-style sessions linked via `parent_channel_id` always returned `source: none`. The budget lookup now accepts `parent_channel_id` ownership for session-scoped queries, so the header can finally show the same context numbers on those routes.
- [x] **Live and refetched turns now share canonical tool-call identity** — the previous pass only wired real ids onto `tool_start`, but the SSE bridge was still dropping them before the chat store and `tool_result` events still lacked `tool_call_id` entirely. The stream contract now carries real ids on both start and result payloads end-to-end (`tool_dispatch` → `turn_event_emit` → `useChannelEvents` → `chat.ts`), and the live store reconciles results by `tool_call_id` instead of "last running tool with this name", closing the same-name multi-tool ordering/ownership hole.
- [x] **Normal session history now excludes hidden intermediate assistant rows at the source** — the browser chat was consuming `/sessions/{id}/messages` from `app/routers/sessions.py`, not the API-v1 router. That endpoint now filters `metadata.hidden` rows server-side for normal history while preserving `pipeline_step` child rows for sub-session run views, so the final visible assistant row is the canonical persisted owner of the turn body instead of relying on client-only hidden-row filtering.
- [x] **Contract regressions are now pinned with executable end-to-end guards** — added a session-router integration test for hidden intermediate rows + canonical final assistant row shape, extended `test_turn_event_emit.py` to assert `tool_call_id` survives on both tool-start and tool-result payloads, and added a focused UI store test that proves repeated same-name tool calls reconcile to the correct envelopes by id.
- [x] **Terminal/default rendering now goes through a mode-aware view registry** — result envelopes can carry `view_key`, `data`, and `template_id`; `RichToolResult` resolves `view_key + mode` through a registry instead of rewriting terminal widgets into default JSON/card paths. Generic semantic views such as `core.search_results` can provide default and terminal React renderers from the same structured data, and unknown old widget rows fall through to a safe non-crashing fallback instead of mounting default chrome.
- [x] **Composer placement is now a mode contract instead of scattered terminal checks** — `chatModes.ts` defines default as viewport-overlay and terminal as transcript-flow, and `ChatSession` uses that helper for input placement. This preserves default’s sticky/floating composer while terminal’s input remains part of the transcript and scrolls off-screen when reviewing older messages.
- [x] **Terminal palette moved toward one-accent styling** — terminal assistant/user headers now avoid random avatar colors, streamed skill/thinking chrome avoids purple pills, JSON primitive colors are neutralized, and terminal web-search URLs use muted text instead of success green.
- [x] **Channel session switching gained a command-first path** — `/sessions` and This Channel palette actions now open a channel-scoped session picker with primary/scratch rows, search, rename/promote actions, fresh-session entry, and a desktop-only split action. Split scratch sessions persist per channel as up to two side panels, while mobile keeps the main-chat switch behavior.
- [x] **Session switching got an extensibility boundary pass** — primary/scratch session surfaces now route through a pure `channelSessionSurfaces` model that owns descriptors, split-panel normalization, route/source builders, picker entries, labels/stats, and untouched-draft detection. The desktop split panel is extracted from `ChannelPage`, leaving the page to orchestrate activation rather than rebuild scratch session chrome inline.
- [x] **`/sessions` search now has an async deep-search lane** — the picker still filters locally immediately, then debounces a public channel-session search that ranks sessions by live message matches plus archived-section matches. Results stay session-oriented: matching rows move up and show message/section snippets, while inactive channel sessions activate through the existing switch-session endpoint.
- [x] **Session split and slash discovery tightened** — the picker now exposes `Split` as a visible row-level action, and channel-bound session surfaces (scratch route, mini session, split panels, and threads) can open the same `/sessions` picker. Session slash lists now use the backend-supported session command set instead of the old reduced subset.
- [x] **Header sessions button now uses the unified picker** — the top-right `Sessions` button and mobile overflow action open `SessionPickerOverlay` directly instead of the legacy scratch-session menu.
- [x] **Session switching boundary hardening** — slash-command availability now resolves through one pure surface helper, channel-session activation lives behind a route-local controller hook, channel/scratch session API hooks have a dedicated module, and backend channel-session catalog/search construction moved out of the channel router into a service.
- [x] **Generic session split panels are writable and web-only** — the split panel model now accepts both scratch and channel-session surfaces, `ChatSession` has a fixed-session source for historical/non-primary channel sessions, and secondary sends use `external_delivery: none` so only the primary session mirrors to integrations. Channel settings now calls out that dispatcher bindings mirror the primary session only.
- [x] **Session canvas panes replace the temporary split-panel model** — `/sessions` now browses/switches with grouped empty-state rows, `/split` opens the same picker in add-pane mode with already-visible sessions hidden, and the chat area persists up to three first-class panes with headers, close/rename/make-primary actions, focused-pane replacement, and draggable width gutters.
- [x] **Focused chat layout is commandable** — `/focus`, This Channel palette action, and the existing keyboard shortcut now collapse both side panels plus the floating top chip rail into a compact top-edge handle, with prior chrome restored on the next toggle.
- [x] **Session pane boundary cleaned up** — stale side-panel modules were removed, legacy `sessionPanels` remains migration-only, and `channelSessionSurfaces` owns pane normalization, resize math, picker grouping, and route/source helpers.
- [x] **Session picker filters out sub-session noise** — the channel session catalog/search now excludes task, pipeline, eval, thread, delegation, and other child transcripts from `/sessions` and `/split`, while keeping primary/previous user chat sessions plus owned scratch sessions visible.
- [x] **Split-pane chrome merged into the chat surface** — desktop split panes now use slim header strips and vertical gutters instead of framed rounded cards, with aggressive title truncation and flex body sizing so embedded composers stay bottom-aligned.
- [x] **Session picker and split-pane interaction polished** — `/sessions` now exposes split as an in-picker mode/action with persistent keyboard hints, previous-session grouping is labeled as `Previous chats`, slash-command Tab/click completes instead of executing, split pane headers dropped accent/badge chrome, and pane resizing now updates locally during drag then persists once on mouseup.
- [x] **Idle session resume cards** — composer-bearing chat surfaces now show a UI-only session info card above the composer when the latest real visible user/assistant message is at least two hours old. The card is mounted through `ChatMessageArea.sessionResumeSlot`, uses lightweight session metadata, supports dismiss/hide local preferences, and stays out of persisted messages, model context, search, and compaction.
- [x] **Idle session resume cards can open the unified picker** — the resume-card overflow menu now exposes `Open session picker` whenever the host chat can supply a picker callback. Channel pages, split/session surfaces, threads, and the Spatial Canvas mini chat route this to the existing `SessionPickerOverlay`; canvas selection closes the mini chat and navigates to the chosen channel session.
- [x] **Harness-question prompts now render as transcript-owned cards** — terminal chat no longer wraps the card in an extra `assistant:<runtime>` header or duplicates it in the composer lane. Hidden answer transport rows are filtered out of live/page sync, and pending question cards suppress the generic streaming `(thinking...)` row for the blocked turn.
- [x] **Harness approval mode moved to the composer footer** — the old header `edits`/`bypass`/`plan` pill is gone. Harness channels now render the same approval mode as colored footer text beside the plan control in terminal and default composers, and clicking it cycles through `session-approval-mode` with the existing backend mutation.
- [x] **Harness composer mode control is no longer duplicated** — harness chats now suppress the separate `Start plan` composer affordance, leaving the approval-mode footer text as the only bottom-right harness mode control.
- [x] **Harness approval cards are terminal-aware** — live and orphan harness approval prompts now render with transcript-style inline chrome in terminal mode while default mode keeps the full card treatment.
- [x] **Harness context-pressure prompts are explicit-only** — hard native-context pressure no longer auto-runs `/compact` from a React effect. The banner stays an urgent prompt, and the ctx badge labels whether remaining context comes from latest-turn telemetry or latest native compaction.

### Verification
- [x] `cd spindrel/ui && npx tsc --noEmit`
- [x] `cd spindrel/ui && timeout 20s ./node_modules/.bin/tsc --noEmit --pretty false`
- [x] `cd spindrel/ui && npx tsc --noEmit` after terminal-mode composer/indicator polish
- [x] `cd spindrel/ui && timeout 20s npx tsc --noEmit --pretty false` after dashboard mini-chat theme + dock resize persistence
- [x] `cd spindrel/ui && timeout 20s npx tsc --noEmit --pretty false` after terminal dock chrome + mini-chat session-plan composer wiring
- [x] `cd spindrel/ui && npx tsc --noEmit` after harness-question terminal stream polish
- [x] `cd spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false && node --test .chat-test-dist/src/components/chat/harnessQuestionMessages.test.js`
- [x] `cd spindrel/ui && npx tsc --noEmit` after moving harness approval mode into the composer footer
- [x] `cd spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false && node --test .chat-test-dist/src/components/chat/harnessApprovalModeControl.test.js`
- [x] `cd spindrel/ui && npx tsc --noEmit` after suppressing duplicate harness `Start plan`
- [x] `cd spindrel/ui && npx tsc --noEmit` after terminal approval-card polish
- [x] `python -m py_compile app/routers/api_v1_channels.py app/routers/api_v1_admin/channels.py app/tools/local/propose_config_change.py`
- [x] `python -m py_compile app/services/slash_commands.py app/routers/api_v1_slash_commands.py tests/integration/test_slash_commands.py`
- [x] `cd spindrel/ui && ./node_modules/.bin/tsc --noEmit --pretty false` after summary/surface UI adoption
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` after terminal typography + plan-question transcript widget wiring
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` after session-aware context header + scratch session widget plumbing
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json`
- [x] `cd /home/mtoth/personal/spindrel/ui && node '.chat-test-dist/app/(app)/channels/[channelId]/sessionHeaderChrome.test.js'`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false` after mobile/channel palette polish
- [x] `cd /home/mtoth/personal/spindrel/ui && node .chat-test-dist/src/components/palette/recent.test.js` after removing the visible `Chat ·` channel prefix
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` after primary/session header clarification + partial-budget token fallback
- [x] `cd spindrel && pytest tests/unit/test_tool_presentation.py -q`
- [x] `cd spindrel && pytest tests/unit/test_turn_event_emit.py tests/unit/test_tool_presentation.py -q`
- [x] `cd spindrel && pytest tests/unit/test_api_v1_sessions_message_out.py tests/unit/test_turn_event_emit.py tests/unit/test_tool_presentation.py -q`
- [x] `python -m py_compile app/domain/payloads.py app/services/turn_event_emit.py app/agent/tool_dispatch.py`
- [x] `python -m py_compile app/routers/api_v1_sessions.py`
- [x] `cd spindrel/ui && ./node_modules/.bin/tsc --noEmit --pretty false` after live/persisted tool contract unification
- [x] `cd spindrel/ui && ./node_modules/.bin/tsc --noEmit --pretty false` after shared persisted tool-transcript adapter unification
- [x] `cd spindrel/ui && ./node_modules/.bin/tsc --noEmit --pretty false` after live default-tool transcript unification
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` after renderer-variant split + persisted tool auto-open removal
- [x] `cd /home/mtoth/personal/spindrel/ui && timeout 20s npx tsc --noEmit --pretty false` after persisted ordered-item collapse in `MessageBubble`
- [x] `cd /home/mtoth/personal/spindrel/ui && timeout 20s npx tsc --noEmit --pretty false` after `transcript_entries` stream→settled parity fix
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` after session canvas panes + focus layout
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json`
- [x] `cd /home/mtoth/personal/spindrel/ui && node .chat-test-dist/src/lib/channelSessionSurfaces.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/src/components/chat/slashCommandSurfaces.test.js`
- [x] `cd /home/mtoth/personal/spindrel && python -m py_compile app/services/slash_commands.py`
- [x] `cd /home/mtoth/personal/spindrel && env PYTHONPYCACHEPREFIX=/tmp/spindrel-pycache python -m py_compile app/services/channel_sessions.py app/routers/api_v1_channels.py`
- [x] `cd /home/mtoth/personal/spindrel && pytest tests/integration/test_api_search_history.py -q -k "SessionSearchEndpoint"` — skipped locally on SQLite; PostgreSQL fixture owns execution.
- [x] `cd /home/mtoth/personal/spindrel && pytest tests/unit/test_loop_helpers.py tests/unit/test_sessions.py -q`
- [x] `cd /home/mtoth/personal/spindrel/ui && timeout 20s npx tsc --noEmit --pretty false` after backend `transcript_entries` persistence + settled transcript fallback fix
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json`
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/components/chat/toolTranscriptModel.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && timeout 30s npx tsc --noEmit --pretty false` after ordered current-turn model unification
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/components/chat/toolTranscriptModel.test.js .chat-test-dist/stores/chat.test.js`
- [x] `cd /home/mtoth/personal/spindrel && pytest tests/unit/test_compaction.py tests/unit/test_compaction_core_gaps.py::TestMaybeCompact -q`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` after terminal mobile tool-row overflow fix
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` after `/sessions` picker + session split panels
- [x] `python -m py_compile spindrel/app/services/slash_commands.py`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` after session-surface boundary hardening
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false`
- [x] `cd /home/mtoth/personal/spindrel/ui && node .chat-test-dist/src/lib/channelSessionSurfaces.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` after async session search
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false --noEmit`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false --outDir /tmp/agent-chat-test-dist && node /tmp/agent-chat-test-dist/src/lib/channelSessionSurfaces.test.js`
- [x] `PYTHONPYCACHEPREFIX=/tmp/spindrel-pycache python -m py_compile app/routers/api_v1_channels.py app/tools/local/search_history.py app/services/slash_commands.py`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` after session split/slash discoverability follow-up
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false --noEmit`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` after session picker/split-pane polish
- [x] `cd /home/mtoth/personal/spindrel && env PYTHONPYCACHEPREFIX=/tmp/spindrel-pycache python -m py_compile app/routers/api_v1_sessions.py` after idle session resume card metadata endpoint
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false` after idle session resume card helpers
- [x] `cd /home/mtoth/personal/spindrel/ui && node .chat-test-dist/src/lib/sessionResume.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` — former admin-bot page blockers resolved by the 2026-04-25 admin bot catalog/editor sweep.
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --noEmit --pretty false`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false && node .chat-test-dist/src/components/chat/slashCommands.test.js && node .chat-test-dist/src/lib/channelSessionSurfaces.test.js`
- [x] `PYTHONPYCACHEPREFIX=/tmp/spindrel-pycache python -m py_compile app/services/slash_commands.py`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` after header Sessions button unification
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json` after writable generic session split panels
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --outDir /tmp/agent-chat-test-dist && node /tmp/agent-chat-test-dist/src/lib/channelSessionSurfaces.test.js`
- [x] `cd /home/mtoth/personal/spindrel && python -m py_compile app/routers/chat/_schemas.py app/routers/chat/_helpers.py app/routers/chat/_routes.py app/agent/tasks.py`
- [ ] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` still blocked by unrelated `UsageCharts.tsx` / `LineChartProps` prop mismatch in the dirty tree.
- [ ] `cd /home/mtoth/personal/spindrel && pytest tests/integration/test_chat_202.py -q` skipped all 11 tests in this local harness; focused secondary-session delivery assertions are in place for a normal integration run.
- [ ] `pytest tests/integration/test_api_search_history.py -q -k 'session_search or session_catalog'` skipped in this local SQLite-backed harness; the file is PostgreSQL-only because it relies on `ILIKE`.
- [ ] Targeted pytest remains flaky in this sandbox:
  `tests/e2e/scenarios/test_api_contract.py -k channel_settings_update` blocked on Docker socket permission.
  `tests/unit/test_propose_config_change.py -k chat_mode` timed out here without emitting a Python failure trace.
  `tests/integration/test_slash_commands.py -q` also stalled under the wrapper here without producing a Python failure trace.
- [ ] Session-history contract pytest is still wrapper-limited here:
  focused `pytest tests/unit/test_turn_event_emit.py tests/integration/test_sessions_router.py -q` reached full test-dot progress in the sandbox but the shell wrapper never surfaced the normal pytest summary line before `timeout` terminated the process. The new assertions are in place and should be rerun once in a normal repo shell to capture a clean pass/fail summary.
- [ ] Follow-up scratch-copy polish verification remains wrapper-limited:
  `cd spindrel/ui && ./node_modules/.bin/tsc --noEmit --pretty false` did not report TypeScript errors here, but the sandbox command wrapper hung until `timeout 5s` terminated it.
- [ ] Session-aware context-header backend regression pytest is still wrapper-limited here:
  targeted `tests/integration/test_context_endpoints_public.py` / `test_context_breakdown_modes.py` runs exited ambiguously under the sandbox shell wrapper without surfacing Python pass/fail output, so manual rerun in a normal repo shell is still needed even though the new regression test was added.
- [ ] Post-compaction context-budget regression pytest is still wrapper-limited here:
  focused `tests/integration/test_context_breakdown_modes.py -k 'stale_api_usage_after_compaction or falls_back_to_forecast_after_compaction'` and even smaller `context-budget` endpoint slices still time out under the sandbox wrapper without surfacing pytest output. The regression tests are in place; rerun in a normal repo shell for a clean summary line.

- [x] **Ordered transcript rows have started collapsing onto one shared renderer path** — after visual review confirmed terminal/default were still using separate transcript components, this pass routed ordered transcript rows through `DefaultToolRows` with `chatMode` controlling shell styling and removed terminal-only transcript/widget branches from `OrderedTranscript.tsx` and `MessageBubble.tsx`.
- [x] **File diff/edit outcomes now resolve to canonical rich-result surfaces** — `app/services/tool_presentation.py` no longer stamps edit/diff file operations as lightweight transcript rows, the frontend surface resolver forces inline diff envelopes to `rich_result`, and the focused transcript-model + tool-presentation tests now pin that contract.
- [x] **Assistant turn bodies now ride one canonical `assistant_turn_body` contract end-to-end** — `app/agent/loop.py` now stamps `_assistant_turn_body`, `persist_turn()` stores `metadata.assistant_turn_body`, legacy `_transcript_entries` upgrade once for old rows, and `finishTurn()` writes the same shape so live, synthetic-settled, and refetched rows all feed one assistant-body model instead of parallel transcript reconstruction paths.
- [x] **Streaming and persisted assistant rows now share one canonical builder without live-only drift** — both `StreamingIndicator` and `MessageBubble` now call `buildAssistantTurnBodyItems(...)`, backend-selected `surface` wins for canonical tool calls, and `buildLiveToolEntries(...)` no longer force-tints completed tool rows, so streaming/persisted transcript rows match in order, surfaces, labels, previews, and default detail behavior.
- [x] **Terminal/default assistant body rendering now goes through one row path** — `TerminalToolTranscript.tsx` is gone, `MessageBubble`'s persisted fallback renderer was removed, and both modes route ordered assistant-body items through `OrderedTranscript` with `chatMode` only affecting shell/style.
- [x] **Terminal rich-result polish keeps composer styling stable** — terminal input/composer styling remains on its existing implementation, terminal diffs keep semantic green/red bands, and terminal generic JSON/surface renderers now clip with a `... more` affordance instead of nested scrollbars.
- [x] **Terminal diff headers now use owned tool-call summaries** — ordered rich-result items carry `ToolCallSummary` into `RichToolResult` / `DiffRenderer`, so terminal `Edited ... (+N -M)` headers come from the normalized tool-call contract, not unified-diff body parsing.
- [x] **Terminal truncated-output affordances are text-only stacked actions** — truncated previews render the preview first, then put `Show full output` on its own non-wrapping line without button chrome, while default mode keeps its existing inline button treatment.
- [x] **Non-diff transcript tools now keep useful inline detail after settle/reload** — `tool_presentation.py` now emits `preview_text` for `get_current_local_time` / `get_current_time`, `get_skill` / `load_skill`, and generic transcript rows, and the shared transcript-row model carries that preview inline or via expansion instead of degrading to lightweight settled rows.
- [x] **Default-mode composer width is now centralized instead of page-wrapper drift** — `ChatComposerShell` owns the `max-w-[820px] px-4` constraint and wraps every `MessageInput` mount in the main channel page and `ChatSession`, so default mode follows one width/container path while terminal mode remains a pass-through shell.
- [x] **Default mobile composer gutters and send button tightened** — mobile default chat now uses a narrower shared `ChatComposerShell` gutter plus reduced input-card side padding, and the default send button drops the accent→purple gradient/fill for a backgroundless ghost icon with token accent/danger state. Terminal mode remains on its existing pass-through/simple treatment.
- [x] **Chat send ordering and queue editing now behave like one transcript** — web sends create a stable optimistic user row before secret-check / POST, carry `client_local_id` through `msg_metadata`, and reconcile server `NEW_MESSAGE(user)` by that id so the assistant typing indicator cannot visually overtake the user row. The main composer now supports one editable queued message: Escape cancels queued/local state first, Up Arrow recalls the queued row into an empty composer, and queued rows can be edited/cancelled from the queue bar.
- [x] **Stopped turns now clean up without noisy error rows** — cancelled typing-only turns disappear, while cancelled partial turns preserve streamed text/tool progress and show a quiet `Stopped by user` note instead of a red failure banner.
- [x] **Session plan cards now preserve historical revisions instead of collapsing to “latest only”** — `PlanResultRenderer` keeps the transcript card’s published revision as the display artifact, while `useSessionPlanMode` supplies current session state/revision metadata separately so old plan cards render as historical views instead of silently acting on the newest draft.
- [x] **Session plan state is now event-driven instead of 3s polling** — `useSessionPlanMode` subscribes to session SSE, consumes `session_plan_updated`, and updates both plan-state + plan queries from the pushed payload; stale-revision conflicts now surface explicitly instead of quietly invalidating beneath old cards.
- [x] **Plan revision history/diff is visible in the chat surface** — session plan responses now carry snapshot-backed revision metadata, `SessionPlanCard` renders a revision-history section, and the card can fetch/display unified diffs between revisions without leaving the transcript.
- [x] **Command palette recents now preserve full scratch/session routes instead of collapsing to channel paths** — page-visit capture, current-page comparison, and persisted recent migration now all use full `pathname + search + hash`, so scratch full-page recents reopen `/channels/:id/session/:sid?scratch=true` instead of dropping the `scratch=true` context.
- [x] **Recent session entries no longer show GUID labels** — shared recent-route resolution now recognizes channel sessions/threads, falls back to `Session · #channel` / `Thread · #channel` instead of route ids, and lets scratch/session headers refine those labels with live session titles when available.
- [x] **Command palette now indexes durable channel/admin/widget detail pages through one shared catalog** — the home grid + modal palette both consume the same route-aware item catalog, which now includes channel chat/settings/dashboard destinations, widget dashboards/dev, provider/MCP/tool/webhook/API-key/workflow/workspace/docker-stack detail pages, integration deep pages, and recent traces.
- [x] **Palette recents and exact-path opening now share one canonical route registry** — aliases like `/profile`, `/channels`, `/admin/carapaces`, `/admin/widget-packages/:id`, and `/admin/upcoming` normalize to their durable targets; typed recent rows now render `Chat · #channel`, `Session · <title>`, `Dashboard · …`, `Provider · …`, etc.; and pasted app paths/URLs can open any modeled durable route without relying on GUID-first labels.
- [x] **Transient channel overlay routes are excluded from recents** — `/channels/:id/pipelines/:pipelineId` and `/channels/:id/runs/:taskId` remain valid exact-path destinations but are no longer persisted as noisy recent entries.

### Additional Verification
- [x] `cd /home/mtoth/personal/spindrel && pytest tests/unit/test_tool_presentation.py tests/unit/test_turn_event_emit.py -q`
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/components/chat/toolTranscriptModel.test.js .chat-test-dist/stores/chat.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && timeout 30s npx tsc --noEmit --pretty false`
- [x] `cd /home/mtoth/personal/spindrel/ui && node_modules/.bin/tsc -p tsconfig.chat-tests.json`
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/components/chat/slashCommandRequest.test.js .chat-test-dist/components/chat/toolTranscriptModel.test.js .chat-test-dist/components/chat/renderArchitecture.test.js .chat-test-dist/stores/chat.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` after slash-command surface scoping fix (`StreamingIndicator` stale `hasTranscriptEntries` reference cleaned up in the same pass)
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` after native widget renderer split (`NativeAppRenderer` → registry + per-widget modules)
- [x] `cd /home/mtoth/personal/spindrel && pytest tests/unit/test_tool_presentation.py tests/unit/test_turn_event_emit.py tests/unit/test_sessions.py tests/unit/test_loop_helpers.py -q`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json`
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/components/chat/toolTranscriptModel.test.js .chat-test-dist/stores/chat.test.js .chat-test-dist/components/chat/renderArchitecture.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` after session-plan SSE sync + revision-history UI
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false` after chat send/queue polish
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/stores/chat.test.js .chat-test-dist/components/chat/renderArchitecture.test.js` after chat send/queue polish
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` after chat send/queue polish
- [x] `python -m py_compile /home/mtoth/personal/spindrel/app/services/session_plan_mode.py /home/mtoth/personal/spindrel/app/routers/sessions.py /home/mtoth/personal/spindrel/app/domain/payloads.py /home/mtoth/personal/spindrel/app/domain/channel_events.py /home/mtoth/personal/spindrel/app/tools/local/publish_plan.py`
- [x] `pytest /home/mtoth/personal/spindrel/tests/unit/test_session_plan_mode.py -q`
- [ ] `timeout 30s pytest /home/mtoth/personal/spindrel/tests/integration/test_sessions_router.py -q -k 'plan_endpoints_return_revision_history_and_reject_stale_approve or get_session_messages_hides_internal_rows_but_keeps_pipeline_steps'` remained wrapper-limited here again; rerun in a normal repo shell is still needed for a clean summary line even though the focused assertions landed.
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json` after chat-only generic rich-result chrome split
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/components/chat/renderArchitecture.test.js .chat-test-dist/components/chat/toolTranscriptModel.test.js .chat-test-dist/stores/chat.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` after embedded-vs-standalone chat chrome wiring
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json` after recent-route/session-label recents fix
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/components/chat/slashCommandRequest.test.js .chat-test-dist/components/chat/toolTranscriptModel.test.js .chat-test-dist/components/chat/renderArchitecture.test.js .chat-test-dist/stores/chat.test.js .chat-test-dist/components/palette/recent.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` after recent-route/session-label recents fix
- [ ] `cd /home/mtoth/personal/spindrel && timeout 30s pytest tests/integration/test_sessions_router.py::TestSessionMessagesRouter::test_get_session_messages_hides_internal_rows_but_keeps_pipeline_steps -q` timed out under the sandbox wrapper without surfacing pytest output; rerun in a normal shell is still needed for a clean summary line.
- [x] `cd /home/mtoth/personal/spindrel && pytest tests/unit/test_tool_presentation.py tests/unit/test_turn_event_emit.py -q` after inline tool-error surface preservation
- [x] `cd /home/mtoth/personal/spindrel/ui && node_modules/.bin/tsc -p tsconfig.chat-tests.json`
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/components/chat/toolTranscriptModel.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit`
- [x] `cd /home/mtoth/personal/spindrel/ui && node_modules/.bin/tsc --module ESNext --target ES2022 --moduleResolution bundler --types node --outDir .chat-test-dist src/types/api.ts src/components/chat/messageUtils.ts src/components/chat/toolTranscriptModel.ts src/components/chat/sessionMessageSync.ts src/components/chat/sessionMessageSync.test.ts src/components/chat/renderArchitecture.test.ts`
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/components/chat/sessionMessageSync.test.js .chat-test-dist/components/chat/renderArchitecture.test.js .chat-test-dist/components/chat/toolTranscriptModel.test.js`
- [ ] `cd /home/mtoth/personal/spindrel && timeout 30s pytest tests/integration/test_sessions_router.py::TestSessionMessagesRouter::test_get_session_messages_preserves_widget_owned_tool_rows -q` timed out under the sandbox wrapper without surfacing pytest output; rerun in a normal repo shell is still needed for a clean summary line.
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json && node --test .chat-test-dist/lib/paletteRoutes.test.js .chat-test-dist/components/palette/items.test.js .chat-test-dist/components/palette/recent.test.js` after command palette route-registry/catalog overhaul
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` after command palette route-registry/catalog overhaul
- [x] **Persisted tool envelopes now have explicit ownership instead of positional pairing** — `ToolResultEnvelope` carries `tool_call_id`, tool dispatch/finalization stamp each envelope with its owning call id, `tool_presentation.normalize_persisted_tool_calls(...)` resolves by id first with legacy index fallback, and the chat transcript model mirrors that same rule so widget/rich-result ownership survives stream → persist → refetch without array-order hacks.
- [x] **Final assistant collapse is now current-turn scoped instead of whole-history scavenging** — `_collapse_final_assistant_tool_turn(...)` only inspects assistant tool rows created during the active turn, orders the visible turn’s `tool_calls` from `assistant_turn_body.items[].toolCallId`, and stops leaking older assistant tool rows into the newest persisted message.
- [x] **Chat message hover actions now expose raw grouped response JSON** — `getTurnMessages(...)` is the shared assistant-group boundary for both `Copy full response` text extraction and the new `Copy JSON` action, so copied JSON matches the exact grouped assistant bundle shown in the transcript instead of a separate ad hoc selection path.
- [x] **Terminal chat now demotes widget-owned tool rows into terminal-friendly rich results instead of mounting iframe/widget chrome** — the shared `buildAssistantTurnBodyItems(...)` model now accepts the chat render mode, and terminal mode rewrites `surface="widget"` rows to `rich_result` while `RichToolResult` renders widget envelopes as generic JSON/plain terminal output instead of interactive cards/iframes.
- [x] **Widget-template/state-poll envelopes now use a normalized builder instead of zero-default `ToolResultEnvelope(...)` calls** — `app/services/widget_templates.py` now routes both initial template renders and state-poll refresh renders through `_build_widget_template_envelope(...)`, which consistently serializes the body and populates `byte_size` for persisted/live widget envelopes.
- [x] **Terminal web-search widget output now renders as search results, not a JSON tree** — `RichToolResult` recognizes search-result-shaped `window.spindrel.toolResult` payloads extracted from interactive HTML widget envelopes and renders query + ranked title/url/snippet rows in terminal chat.
- [x] **Web Search now uses the generic core search-result renderer** — replaced the `web_search.results` app special case with `core.search_results`, moved default/terminal search result rendering into a reusable React renderer, and changed the Web Search manifest to opt into that view key with a component fallback instead of an iframe HTML widget.
- [x] **Copy JSON omits bulky inline widget HTML bodies** — `MessageActions` now stringifies grouped assistant bundles through `messageJsonCopy.ts`, preserving envelope ownership/debug metadata while replacing large interactive HTML bodies with `body: null`, `body_omitted: true`, and a short preview.
- [x] `cd /home/mtoth/personal/spindrel/ui && node_modules/.bin/tsc -p tsconfig.chat-tests.json` after explicit `tool_call_id` envelope ownership + `Copy JSON`
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/src/components/chat/toolTranscriptModel.test.js .chat-test-dist/src/components/chat/renderArchitecture.test.js .chat-test-dist/app/(app)/channels/[channelId]/chatUtils.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && node_modules/.bin/tsc -p tsconfig.chat-tests.json` after terminal widget demotion + terminal rich-result fallback
- [x] `cd /home/mtoth/personal/spindrel/ui && node .chat-test-dist/src/components/chat/toolTranscriptModel.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && timeout 60s npx tsc --noEmit`
- [x] `cd /home/mtoth/personal/spindrel && pytest tests/unit/test_widget_templates.py -q -k 'html_template_sets_byte_size or renders_template_and_carries_display_label'`
- [x] `python -m py_compile /home/mtoth/personal/spindrel/app/services/widget_templates.py`
- [x] `cd /home/mtoth/personal/spindrel/ui && node .chat-test-dist/src/components/chat/messageJsonCopy.test.js && node .chat-test-dist/src/components/chat/toolTranscriptModel.test.js`
- [ ] `cd /home/mtoth/personal/spindrel && pytest tests/unit/test_persisted_tool_call_presentation.py -q -k matches_tool_envelopes_by_tool_call_id_before_position` remained wrapper-limited again in this sandbox; rerun in a normal repo shell for the clean summary line.
- [x] `cd /home/mtoth/personal/spindrel && pytest tests/unit/test_loop_helpers.py -q`
- [x] `cd /home/mtoth/personal/spindrel/ui && timeout 60s npx tsc --noEmit`
- [ ] `cd /home/mtoth/personal/spindrel && timeout 30s pytest tests/unit/test_persisted_tool_call_presentation.py -q` remained wrapper-limited in this sandbox shell without surfacing a pytest summary line; rerun once in a normal repo shell to capture the clean pass/fail output for the new `tool_call_id` ownership regression.

## Pass 3: Channel Dashboard + Settings SKILL Adoption + Two-Gear Unification (2026-04-23)

First application of `spindrel-ui` SKILL (shipped same day) to a real screen. Structural + visual in one commit.

### Shipped — structural
- [x] **Two-gear unification on channel dashboard** — removed the left gear from `ChannelDashboardBreadcrumb.tsx`. Channel-scoped dashboards now show exactly one gear (right, Channel Settings). Non-channel (user/global) dashboards still use `DashboardTabs` with its own gear to open `EditDashboardDrawer`.
- [x] **New "Dashboard" tab in channel settings** — added between Presentation and Knowledge. Wraps extracted `<DashboardConfigForm>` so users configure grid preset / rail pin / borderless / hover scrollbars / hide-titles / icon without leaving settings.
- [x] **Shared `DashboardConfigForm`** — form body extracted from `EditDashboardDrawer`. Drawer becomes a thin shell around it; the Settings Dashboard tab renders the same form inline. One save path, one state machine.
- [x] **Router redirect** — `/widgets/channel/:id/settings` now lands on `#dashboard` (was `#presentation`). The right gear on the dashboard still goes to the same URL, just lands on the new tab.
- [x] **Cross-link callout in Presentation tab** — short note at the top pointing at the Dashboard tab so users with `#presentation` muscle memory find the moved controls.

### Shipped — visual (SKILL adoption)
- [x] **`ChannelDashboardBreadcrumb.tsx`** — dropped `useThemeTokens()`; scratch-session chip now uses `border-surface-border` / `bg-surface-overlay` / `text-text-dim` Tailwind classes.
- [x] **`channels/[channelId]/settings.tsx` header (lines ~271-331)** — dropped `backdropFilter: blur(12px)`, dropped `border-b` between header and tab strip (per SKILL §6), migrated all inline `style={{}}` + `useThemeTokens()` to Tailwind. `header-icon-btn` class retained. Spacing + `bg-surface` now separates the header from the tab strip.
- [x] **`channels/[channelId]/settings.tsx` tab strip (lines ~336-440)** — dropped `border-b`, migrated to Tailwind with `data-active` attribute driving the underline via `after:` pseudo-element (no more absolute-positioned child div). Edge fades now use Tailwind `from-surface to-transparent` gradients.
- [x] **`ChannelSettingsSections.tsx` first-landing sections** — TagEditor chips migrated to `rounded-full bg-surface-overlay text-text-muted`. Category suggestion chips migrated. Owner row migrated. `ChannelMetadataFooter` migrated. `DashboardSettingsLink` drops inline style override. `DangerZoneSection` migrated to `bg-danger/10` / `border-danger/40` / `bg-input` tokens. `AgentIdentitySection` AlertTriangle `color="#f59e0b"` → `className="text-warning-muted"`. File no longer imports `useThemeTokens`.
- [x] **Spinner in loading state** — dropped `color={t.accent}` override; uses default (visually indistinguishable accent blue).

### Invariants established
- Every channel dashboard page shows exactly ONE gear.
- Migrated files (`settings.tsx`, `ChannelDashboardBreadcrumb.tsx`, `ChannelSettingsSections.tsx`, `DashboardConfigForm.tsx`, `EditDashboardDrawer.tsx`, `DashboardTab.tsx`) have 0 `useThemeTokens()` callers, 0 inline hex literals, 0 `border-b` between stacked bars.

### Deferred to next opportunistic pass (still in SKILL §8)
- `ChannelHeader.tsx` (chat-view header) inline hex at lines ~219 (`#f87171`, `#fbbf24`) + `animate-pulse` at ~495.
- Deeper tab panels remaining after later Pass 4 updates: `HeartbeatTab`, `PipelinesTab`, `AttachmentsTab`, `HistoryTab`, `ChannelWorkspaceTab`, `ChannelFileBrowser`, `ContextTab`, `LogsTab`, `AutomationTabSections`, `AgentTabSections`. Migrate on next touch.
- Other SKILL §8 debt entries (`MarkdownContent`, `StepsJsonEditor`, `SystemPauseBanner`, `ApprovalToast`, `MemoryHygieneGroupBanner`, `DelegationCard`, `IndexStatusBadge`, `ToolsInContextPanel`, `TaskStepEditor`).

### Verification
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` — clean.
- [x] `grep -n "useThemeTokens" settings.tsx ChannelDashboardBreadcrumb.tsx ChannelSettingsSections.tsx DashboardConfigForm.tsx DashboardTab.tsx EditDashboardDrawer.tsx` — 0 hits.
- [ ] Visual dark/light toggle pass (manual, by user).

## Pass 4a: Agent/Channel tab supplements (2026-04-23)

Finishes the first-landing continuity started in Pass 3 — when a user opens settings and lands on the Channel or Agent tab, the panels above and below the first-landing sections now share the same visual vocabulary.

### Shipped
- [x] **`ParticipantsTab.tsx`** — dropped `useThemeTokens()`; all inline `style={{}}` migrated. Member badges use `rounded-full bg-surface-overlay text-text-dim` uppercase chip per SKILL §4. `BotPicker` lost `boxShadow: "0 4px 16px rgba(0,0,0,0.15)"` (SKILL §3 shadow = "almost never") — uses `border + bg-surface-raised` tonal lift instead. MemberCard collapsed header now a single `<button>` with full-row hover, accessibility preserved. Remove (X) icon uses `text-text-dim hover:text-danger`. Input fields unified via shared `INPUT_CLASS` constant (`bg-input border-input-border rounded-md focus:border-accent focus:ring-2 focus:ring-accent/40`).
- [x] **`ToolsOverrideTab.tsx`** — dropped `useThemeTokens()` from all 4 call sites (SectionLabel, ToolChip, SkillChip, main). `SectionLabel` uses canonical `uppercase text-[10px] tracking-[0.08em] text-text-dim/70` per SKILL §3; dropped the hairline filler line after the label (was `flex-1 h-px bg-surface-border` — admin-chrome noise). Tool/MCP chips migrated to `rounded-full bg-surface-overlay text-text-muted font-mono` per SKILL §4 badges. `SkillChip` uses `bg-accent/[0.08]` fill per SKILL §4 low-opacity accent pattern; dashed bottom-borders on preview triggers dropped. Search input uses `bg-input border-input-border` with `focus-within:` ring. Addable-skill rows use `rounded-md bg-surface-raised hover:bg-surface-overlay/60` card pattern.
- [x] **`IntegrationsTab.tsx`** — verified already clean (5-line re-export wrapper; real chrome lives in `integrations/BindingsSection.tsx`, deferred).

### Invariants established
- Channel tab (`ChannelTabSections` + `ParticipantsTab` + `IntegrationsTab`) renders with one visual voice top-to-bottom.
- Agent tab (`AgentTabSections` + `ToolsOverrideTab`) likewise.
- 0 `useThemeTokens()` callers and 0 inline hex in `ParticipantsTab.tsx`, `ToolsOverrideTab.tsx`, `IntegrationsTab.tsx`.

### Deferred (updated)
Pass 4b/4c remaining candidates (Automation + Memory block): `HistoryTab`, `HeartbeatTab` (+ `HeartbeatHistoryList`, `HeartbeatContextPreview`), `PipelinesTab` (+ `PipelineRunLive`, `PipelineRunPreRun`), `QuietHoursPicker`.
Pass 4c candidate (dirtiest, 10 hex): `ContextTab.tsx`.
Pass 4d (multi-session, own plan): `ChannelWorkspaceTab` + `AttachmentsTab` + file-browser trio.

### Verification
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` — clean (exit 0).
- [x] 0 `useThemeTokens` / 0 `style={{` / 0 inline hex in the 3 touched files.
- [ ] Visual dark/light toggle pass (manual, by user).

## Pass 4b: UI design guide reset + integration control proof (2026-04-24)

Corrective pass after the canonical guide and project skill failed to prevent gradient/shadow settings chrome. The existing chat channel header is explicitly preserved as a reference surface.

### Shipped
- [x] **`docs/guides/ui-design.md` reset** — surface taxonomy is now command / app-shell-content / control. Added control-surface rules, a chrome-budget rule, and an explicit note that sidebar, rail, channel header, and terminal mini-chat are reference surfaces. Decorative gradients/shadowed CTAs are banned for settings/admin/control surfaces.
- [x] **`spindrel-ui` skill corrected** — removed the non-canonical "signature moves" section that required accent→purple gradients and shadow stacks. The skill now derives from the guide instead of extending it.
- [x] **Low-chrome settings actions** — `SettingsControls.ActionButton` primary variant now uses transparent accent text with tonal hover (`bg-transparent text-accent hover:bg-accent/[0.08]`). Filled accent buttons are no longer the default for routine settings rows.
- [x] **Channel tab dispatcher binding proof** — `BindingForm`, `SuggestionsPicker`, and `MultiSelectPicker` now use Tailwind tokens, low-radius control chrome, no inline style color machinery, and no repeated list dividers. This completes the Channel tab proof path with `ParticipantsTab` + `BindingsSection`.
- [x] **Agent tab visible example** — `ActivationCard`, `ActivationConfigFields`, and `ActivationsSection` now show the same control-surface language directly on the Integration Add-ons list: borderless tonal rows, inline accent actions, small status dot/chip, one divider only for expanded config, token-only autosave status, and a split Added/Available flow with a quiet filter for larger catalogs.
- [x] **Channel Tasks tab proof** — `TasksTab` now uses a quiet segmented filter, grouped task sections (`Needs attention`, `Active`, `Other tasks`), low-chrome task rows, token-backed status/type badges, and no `useThemeTokens()`/inline style color machinery in the visible task list path. `TaskConstants` also dropped Bootstrap-blue status/type badge classes in favor of semantic tokens.

### Invariants established
- Channel header is not part of the redesign target; preserve it unless a future task explicitly asks to change header behavior.
- Control-surface work must pass the chrome budget: spacing/typography first, then tonal step, then one neutral hairline. No border + shadow + gradient stacks.
- Routine control actions must not use Bootstrap-like filled blue rectangles. The default is inline/ghost accent text; filled accent is reserved for rare final confirmation moments.
- Control-surface work must improve flow when needed, not only row styling. Mixed current/available catalogs should be grouped and searchable before polishing row chrome.
- Integration settings flow has 0 `useThemeTokens()` callers across `ActivationsSection`, `ActivationCard`, `ActivationConfigFields`, `BindingsSection`, `BindingForm`, `SuggestionsPicker`, and `MultiSelectPicker`.
- Channel Tasks proof path has 0 `useThemeTokens()`, inline hex, Bootstrap-blue classes, `rgba(...)`, gradients, or decorative shadows across `TasksTab`, `TaskCardRow`, `TaskConstants`, and `Spinner`; remaining inline styles there are dynamic sizing/color plumbing for spinner/bot-dot primitives only.

### Deferred
- Manual dark/light visual review remains user-run.

### Verification
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` — clean after guide reset + binding proof; clean again after activation proof; clean again after Tasks tab proof.
- [x] `git -C /home/mtoth/personal/spindrel diff --check` on touched files — clean.
- [x] `git -C /home/mtoth/personal/vault diff --check` on touched vault files — clean.
- [x] Targeted grep checks for `useThemeTokens`, inline hex, `bg-gradient`, decorative `shadow-`, and inline style in the integration proof files — 0 matches.

## Pass 4c: Channel settings shared control primitives (2026-04-24)

Follow-through on Pass 4b after visual review showed piecemeal tab work was not enough. This pass makes the settings page harder to drift by moving common control-surface shapes into shared primitives and applying them across multiple tabs.

### Shipped
- [x] **Shared low-chrome primitives** — `SettingsControls` now owns group labels, quiet search, segmented filters, control rows, and stat grids in addition to action buttons/badges/banners.
- [x] **Holistic channel settings sweep** — Dashboard, Pipelines, Attachments, Knowledge/workspace, Logs, Context, Automation/Heartbeat, Tools/Add Skills, and top-level Memory/History surfaces now use the shared low-chrome vocabulary instead of bespoke bordered rows/search/buttons.
- [x] **Automation/Memory proof path** — Heartbeat mode switch, run controls, quiet hours, context/template previews, recent heartbeat runs, history mode, and section search now avoid filled blue actions and older theme-token card chrome.
- [x] **Action semantics tightened** — `TurnCard` is keyboard-activatable without being a nested button wrapper, and routine settings actions remain transparent/tonal rather than Bootstrap-like filled CTAs.

### Invariants established
- New settings/admin control surfaces should compose `SettingsGroupLabel`, `SettingsSearchBox`, `SettingsSegmentedControl`, `SettingsControlRow`, `SettingsStatGrid`, `ActionButton`, `StatusBadge`, and `InfoBanner` before introducing new local chrome.
- Settings search/filter/action rows should be flow improvements first, styling second: split current vs available catalogs, add quiet filters for large lists, and avoid one flat add/remove stack.
- The existing channel header remains a reference surface and was intentionally not redesigned in this pass.

### Verification
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` — clean.
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` — clean again after Memory/Automation follow-up edits.

### Heartbeat limits follow-up (2026-04-25)
- [x] Channel Settings → Automation → Heartbeat → Advanced Settings → Limits now exposes execution-depth rows (`Low`, `Medium`, `High`, `Custom`) with visible budgets instead of only a compact raw select.
- [x] Tool-surface selection (`Focused escape`, `Strict`, `Full`) is visible on the same surface and persists through the existing heartbeat `execution_policy`.
- [x] Execution controls split into `HeartbeatExecutionControls.tsx`; `HeartbeatTab.tsx` stays under the 1000-line UI file limit.
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` — clean.

## Pass 4d: Admin bot catalog/editor sweep (2026-04-25)

- [x] `/admin/bots` now uses the dense admin catalog pattern instead of the old card grid, fixing mobile horizontal overflow and surfacing model, owner, usage, source, workspace, API-scope, and file-backed prompt/persona signals in-row.
- [x] `/admin/bots/:botId` now uses grouped workflow navigation: Overview, Identity & Model, Prompt & Persona, Tools & Skills, Memory & Learning, Workspace & Files, Access & Automation, and Advanced. Legacy hashes map into the new groups.
- [x] Added an operational bot overview with 30-day calls/tokens/cost and recent trace drilldowns via the shared `TraceActionButton`.
- [x] Bot prompt/persona editing now uses the shared prompt editor/read-only source viewer instead of the local giant textarea.
- [x] Cleaned up the bot-scoped Memory & Learning and Workspace & Files groups: legacy inline-style panels/tables became shared-control rows, stat strips, quiet filters, segmented sort, low-chrome hygiene job expanders, and `SourceFileInspector` previews for bot knowledge files.
- [x] Bot creation Workspace & Files now reflects the shared-workspace invariant: new bots show pending enrollment into the default shared workspace, save responses include the shared membership, and obsolete standalone/Docker-vs-host workspace controls are no longer exposed on the bot editor.
- [x] `docs/guides/ui-components.md` now canonizes dense admin entity catalogs and grouped detail editors.

### Verification
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit` — clean.
- [x] Bot detail touched-file grep for `useThemeTokens`, inline styles, inline hex, and RGBA — 0 matches.

## Small copy fixes (2026-04-24)

- [x] Fixed channel settings escape routes (2026-05-01): the settings header back arrow now targets the owning channel directly instead of browser history, except dashboard-origin settings still return to the channel dashboard. The header also exposes an explicit `Open channel` link for accidental settings-page navigation from search/palette flows.
- [x] Fixed channel-settings autosave textarea clobbering (2026-04-26): heartbeat and parent channel settings now keep a local dirty draft through save/refetch races, and a completed save only clears dirty state if the saved snapshot still matches what the user is currently editing. This preserves Heartbeat Prompt and other textarea edits while autosave remains enabled.
- [x] `/settings` Chat History `Compaction Model` description is provider-neutral now: "Model used for context compaction." The old "LiteLLM model alias" wording was misleading because the shared picker spans all LLM providers.
- [x] Fixed stale post-compaction typing indicators: channel-state rehydration now treats lifecycle-only `turn_started` / `skill_index` trace rows as active only while the session lock is active, so reopening a compacted idle thread does not show a phantom bot thinking until the 10-minute TTL expires.
- [x] Fixed scratch/session context-budget bleed: `context_budget` typed bus payloads now carry `session_id`, and primary/member turn lifecycle streams tag the real session so scratch/session subscribers drop sibling parent-channel budget events instead of showing the parent channel's gross token total.
- [x] Fixed split-session identity bleed: focused scratch/previous panes now drive the session picker current row and top header mode, while each split pane header owns its own session-specific token/turn/compaction stats.
- [x] Hardened session canvas semantics: 2+ visible panes use a channel/canvas header, single/maximized panes use session chrome, pane headers expose direct maximize/minimize/close controls, minimized panes occupy the single mini-chat slot, and fixed-session sends now show immediate processing feedback after submit acknowledgement.
- [x] Polished split-pane window controls: minimize now uses a traditional `-`, pane actions are grouped as layout vs session actions, `Make primary` is now `Set as channel primary`, panes can move left/right, and minimized sessions collapse into a labeled bottom mini-chat chip that expands upward and can restore to the canvas.
- [x] Tightened mobile channel header priority: mobile hides inline session title/meta and long turn/compaction details, keeping the channel identity plus compact mode/token signals.
- [x] Reset session navigation boundaries: `/sessions` switch now navigates to a route-level single-session page, `/split` explicitly creates canvas state from the current page, and close/minimize collapse one remaining pane back to a route-level page instead of leaving a nested one-pane canvas.
- [x] Clarified session picker state: current/visible session badges now distinguish `Current` from `Open`, previous-channel sessions get stable `?surface=channel` routes, and `Set as channel primary` is visible as an explicit row action for scratch/previous sessions.
- [x] Clarified full-screen session picker state: the current route-level chat is grouped as `This chat`, cannot be re-selected or split against itself, and primary remains visible as an escape hatch even if the catalog omits it.
- [x] Removed session navigation implementation leakage: split/session chrome no longer labels previous-channel sessions as `WEB-ONLY`; integration mirroring remains a primary-session concern rather than picker copy.
- [x] Clarified Memory tab conversation-history scope: current-session archive is the default/runtime mirror, all-sessions is an explicit grouped inventory view, and section search/index preview no longer imply the bot sees a flattened channel archive.
- [x] Tightened `/settings/system` constrained-width header behavior: sticky domain tabs stay single-line in a horizontal scroller, and the Save cluster drops to a clean second row until there is enough width to share the toolbar.
- [x] Polished default/terminal chat transcript ergonomics: terminal mode now gets a wider inner content lane without changing side-panel layout math, adjacent lightweight tool transcript rows collapse into one expandable trace strip, approval rows stay visible, global shortcuts ignore editable targets, and Cmd/Ctrl+Enter submits from the composer while mobile Enter still inserts a newline.
- [x] Restored user scroll ownership during streaming: when a live turn grows at the visual bottom and the reader has scrolled up, `ChatMessageArea` now compensates the column-reverse scroll delta instead of pulling the viewport back toward the newest token. Bottom-pinned auto-follow remains unchanged, and local optimistic sends still jump to newest via `client_local_id` keyed detection.
- [x] Fixed default approval-row regressions from grouped live tool rows: live transcript entries now use canonical tool-call ids for stable unique keys, approval cards state the requested action/target file without expansion, and successful decisions locally clear the pending row while the stream catches up.
- [x] Added attachment screenshot checks as their own `scripts/screenshots --only attachment-checks` bundle, with staged drag/drop coverage for the overlay, pending routing tray, and post-send optimistic receipts.
- [x] Polished attachment pending/sent receipts after visual review: default mode now uses a compact low-chrome shelf/receipt treatment, terminal mode keeps image thumbnails but drops boxed row chrome, and optimistic image thumbs persist through send/stream settle.
- [x] Added the terminal attachment screenshot artifact `docs/images/chat-attachments-terminal-sent-receipts.png` and referenced it from the canonical "How Spindrel works" guide alongside the default attachment screenshots.
- [x] Tightened harness terminal-mode chrome: harness composer plan controls present as an implement/plan mode switcher, mobile context is available through a bounded context chip instead of hidden behind the bot-info path, and soft context pressure no longer shows alert-style warning chrome.
- [x] Moved terminal-mode harness rich results back through transcript-owned rows: diff/code previews stay inline and sequential, while default chat still uses the trace strip/card treatment. Claude Code native `Write` now supplies the written content envelope so terminal can render code instead of a plain white summary blob.
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false && node .chat-test-dist/src/lib/channelSessionSurfaces.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc -p tsconfig.chat-tests.json --pretty false && node --test .chat-test-dist/src/components/chat/orderedTranscriptGrouping.test.js .chat-test-dist/src/components/chat/chatKeyboard.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false`
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/src/components/chat/reverseScrollPinning.test.js .chat-test-dist/src/components/chat/orderedTranscriptGrouping.test.js .chat-test-dist/src/components/chat/chatKeyboard.test.js`
- [x] `cd /home/mtoth/personal/spindrel/ui && node --test .chat-test-dist/src/components/chat/toolTranscriptModel.test.js .chat-test-dist/src/components/chat/reverseScrollPinning.test.js .chat-test-dist/src/components/chat/orderedTranscriptGrouping.test.js .chat-test-dist/src/components/chat/chatKeyboard.test.js`

## Pass 4e: Admin Tasks + pipeline builder cleanup (2026-04-25)

- [x] `/admin/tasks` list, definitions, schedule, calendar, and cron surfaces now use lower-chrome rows/actions with token-driven status; refreshed paths have no `useThemeTokens()`, inline hex/RGBA, native `<select>`, decorative shadows, or colored left rails.
- [x] Task detail/create/edit flows now use spacing-led sections, quieter task notices/actions, and shared dropdowns while preserving existing routes and task API payloads.
- [x] `TaskStepEditor.tsx` was split by moving builder metadata/helpers into `TaskStepEditorModel.tsx`, bringing the main component under the 1000-line UI limit.
- [x] Pipeline builder visual mode keeps the vertical sequence but drops Bootstrap-blue running chrome, `animate-pulse`, colored step badges, dashed nesting rails, and heavy card borders in favor of semantic dots/pills and tonal rows.
- [x] `StepsJsonEditor` and `JsonObjectEditor` now use CSS design tokens for syntax colors and editor chrome instead of hard-coded dark-theme hex/RGBA.
- [x] Channel pipeline pre-run/live modal pieces now match the same task status/error/action vocabulary.
- [x] Follow-up: `/admin/tasks` header controls now sit in a separate compact toolbar, and the shared Schedule/Event/Manual trigger section uses neutral segmented controls/source rows instead of filled tabs, colored rails, and hard-coded integration colors.
- [x] Follow-up 2: `/admin/tasks` top chrome now follows the settings/channel pattern directly — title/action header only, bounded bot/system controls, then shared segmented view subnav. The previous right-floating toolbar layout is removed.

### Verification
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` — clean.
- [x] Targeted grep over refreshed task surfaces for `useThemeTokens`, inline hex/RGBA, native `<select>`, Bootstrap-blue classes, `animate-pulse`, decorative shadow classes, and colored left-border patterns — 0 matches.

## Native Plan Card Polish (2026-04-29)

- [x] Native session plan cards now follow the low-chrome chat surface rules: default mode uses token-only tonal surfaces and compact semantic controls, terminal mode uses a dedicated monospace/dense presentation, and terminal transcripts render plan envelopes inline through the shared rich-result path instead of compact fallback rows.
- [x] The native plan screenshot harness now captures default/mobile plus terminal plan states for base, answered-question, execution-progress, replan-pending, and pending-outcome scenarios against the live Spindrel channel.

## Project Workspace UI Repair (2026-04-29)

- [x] `/admin/projects` now uses the dense admin catalog pattern instead of a bordered create card plus project card grid.
- [x] `/admin/projects/:projectId` now uses spacing-led sections, `PromptEditor`, quiet header links, and shared settings rows for root URI, Project knowledge, and attached channels.
- [x] Channel Agent settings replaced the blue Project summary banner with a compact `SettingsControlRow` that keeps Project, file, terminal, and memory-separation affordances visible.
- [x] E2E Project workspace screenshots were recaptured through the patched local UI against the `10.10.30.208:18000` E2E API and visually inspected: list/detail/channel-settings no longer use the boxed card/panel treatment, and the memory tool envelope remains visible.

### Verification
- [x] `cd /home/mtoth/personal/spindrel/ui && npx tsc --noEmit --pretty false` — clean.
- [x] `PYTHONPYCACHEPREFIX=/tmp/codex-pycache python -m py_compile scripts/screenshots/capture/specs.py` — clean.
- [x] `PYTHONPATH=. pytest scripts/screenshots/tests/test_pure_units.py -q` — 28 passed.
- [x] `SPINDREL_UI_URL=http://127.0.0.1:5175 SPINDREL_BROWSER_URL=http://127.0.0.1:5175 python -m scripts.screenshots stage --only project-workspace` — passed.
- [x] `SPINDREL_UI_URL=http://127.0.0.1:5175 SPINDREL_BROWSER_URL=http://127.0.0.1:5175 python -m scripts.screenshots capture --only project-workspace` — 4/4 passed.
- [x] `python -m scripts.screenshots check` — 78/78 refs present.
