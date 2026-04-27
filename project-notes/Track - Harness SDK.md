---
tags: [agent-server, track, harnesses, integrations, sdk]
status: active
created: 2026-04-26
updated: 2026-04-27 (harness stop cancellation)
---
# Track - Harness SDK

## North Star

Make external agent harnesses feel like first-class Spindrel sessions without pretending they are normal Spindrel bots. A harness owns the coding-agent loop, native tools, file edits, and native session id; Spindrel owns the browser UI, channel transcript, workspace path, session persistence, approvals, and any explicitly bridged Spindrel tools/skills.

This track covers the stable host contract used by Claude Code and Codex today, and by future runtimes later: approvals, per-session runtime controls, slash-command filtering, and optional bridges from harness runtimes back into Spindrel's tool and skill systems.

## Current State

- Claude Code and Codex are both implemented harness runtimes. They live in `integrations/claude_code/harness.py` and `integrations/codex/harness.py`.
- Harness discovery/registration lives under `app/services/agent_harnesses`; active integration harness modules register runtime instances on import.
- Harness bots reuse standard Spindrel bot workspaces. The bot workspace directory is the harness cwd.
- A harness turn bypasses normal Spindrel context assembly, prompt injection, skills, knowledge bases, memory, and fanout. Host hints, manual compact continuity summaries, selected Spindrel tools, and per-run model/effort overrides now have narrow bridge paths back into the runtime.
- Spindrel currently streams assistant text and live tool breadcrumbs into the channel, persists the final assistant message with tool breadcrumbs, and stores harness resume/cost metadata on assistant-message metadata for the Spindrel session.
- Phase 2 shipped the in-app terminal and per-session resume keying, plus a broad auto-approve `can_use_tool` shim so Claude Code does not stall on SDK permission prompts.
- Known-secret and common-pattern redaction now applies at the host boundary for harness streams and persisted final assistant text. Native harness tools still execute outside Spindrel's tool dispatcher, so a token printed by the harness should be treated as compromised even if the UI/transcript redacts it afterward.
- Per-session approval modes, session-scoped model/effort/runtime settings, durable harness question cards, `/compact` / `/context` / `/new` / `/clear`, host hints, and the first Spindrel tool/skill bridge lane are all real.
- The integration import boundary matters here: harness runtime modules should import host contracts through `integrations.sdk`, not directly from `app.*`, so the boundary test can stay meaningful.

## Invariants

- Runtime implementations live in `integrations/<id>/`; shared host contracts live in `app/services/agent_harnesses` and are re-exported through `integrations.sdk`.
- No Claude-only tool names or permission assumptions belong in core `app/` abstractions. Runtime adapters own tool classification and SDK-specific translation.
- Harness settings are session-scoped first. Multi-pane, scratch-session, and concurrent-session views must not accidentally mutate the channel primary. `channel.active_session_id` means primary/mirrored integration session only; web UI commands and harness controls must target the current component/querystring session id when one is present, falling back to `active_session_id` only when no explicit session is supplied.
- Scheduled harness runs inherit the target session's model/effort settings unless the heartbeat/task explicitly supplies per-run overrides. Per-run overrides must not mutate `Session.metadata_['harness_settings']`.
- Normal bot/channel tool pickers remain visible for harness bots. For harnesses they define the Spindrel bridge tool set, not normal-loop context injection.
- Existing Spindrel model/provider controls are not automatically valid for harnesses. Each runtime exposes its own supported controls and value hints.
- Harness-native tools remain native. If Spindrel tools are later exposed to a harness, they must execute through the existing Spindrel dispatch, policy, approval, trace, and widget-result paths.
- Harness host events must pass through Spindrel's secret redactor before publication or persistence. This covers accidental display/logging; it does not make printed credentials safe to keep using.
- Approval mode and model/effort controls should be usable from both UI controls and slash commands, with one backend settings contract.

## Phases

| Phase | Title | Status | Notes |
|---|---|---|---|
| 1 | Claude Code web harness baseline | shipped | Remote Claude Code sessions from the web UI, workspace reuse, auth-status surface, terminal login, resume/cost persistence. |
| 2 | Resume + broad auto-approval cleanup | shipped | Per-session resume keying and auto-approve `can_use_tool` shim to avoid SDK permission stalls. |
| 3 | Harness approvals | shipped | Per-session approval modes: `bypassPermissions`, `acceptEdits`, `default`, `plan`; approval cards for ask paths; stop-turn cancellation; boundary re-exports. Phase 3a (backend) and Phase 3b (UI) both shipped 2026-04-26. |
| 4 | Harness control surface | shipped | `RuntimeCapabilities` Protocol; per-session `harness_settings` (model/effort/runtime_settings); `GET /runtimes/{name}/capabilities`; `GET/POST /sessions/{id}/harness-settings`; header model + effort pills (per-session, alongside Phase 3 approval-mode pill); harness-aware `/model` and `/effort`; `?bot_id=` filter on `/api/v1/slash-commands` and `/help`. Follow-up fixed channel-surface slash requests to carry `current_session_id` so scratch/split/thread panes target their own session, with `active_session_id` only as the default primary fallback. Shipped 2026-04-26. |
| 5 | Native-feel foundation | shipped (follow-up verification open) | Session-bound harness context hints, harness-aware `/compact` / `/context` / `/new` / `/clear`, heartbeat/workspace-files hints, channel/admin settings cleanup, normal tool pickers as bridge source, first Spindrel tool bridge, durable harness question cards, persisted harness tool breadcrumbs, and model-scoped effort controls all landed on 2026-04-26. Remaining work is runtime smoke-testing and polish, not missing core plumbing. |
| 6 | Codex runtime | shipped 2026-04-27 (v1 + finish-line pass) | Codex via the official `codex app-server` JSON-RPC protocol over stdio (no third-party Python SDK). Spawns the user-installed `codex` binary; same `TurnContext`/approval/settings/capabilities/tool-bridge contracts as Claude. Includes Phase A host-seam cleanup (single `build_turn_context`, shared `apply_tool_bridge`, public `resolve_approval_verdict`, `format_question_answer_for_runtime`, `HarnessToolSpec`/`HarnessBridgeInventory` on `base.py`). Follow-up wired Spindrel session plan mode into Codex `collaborationMode: plan`, per-turn `sandboxPolicy`, live model/effort options, and Codex token-window telemetry. Plan: `~/.claude/plans/partitioned-conjuring-finch.md`. See [[#Phase 6 - Codex App-Server Harness V1]]. Remaining live checks: dynamicTools call path, approval routing under a mutating command, native compaction on a non-empty thread. |
| 7 | Skill bridge | planned | Export simple skills to harness-native skill folders and/or expose searchable Spindrel skills as bridged tools/resources. |
| 8 | Usage + observability | planned | Aggregate harness usage/cost into admin usage, expose runtime version/auth/health, and improve post-refresh tool-call rehydration. |

## Phase 3 - Approval Contract — shipped 2026-04-26

Phase 3a (backend) and Phase 3b (UI) shipped same day. Shared approval helper in `app/services/agent_harnesses/approvals.py`. Each runtime translates Spindrel's `AllowDeny` result into its SDK-native permission shape (Claude → `PermissionResultAllow`/`PermissionResultDeny`).

UI surface: per-session mode pill in `ChannelHeader` (cycles `bypass → edits → ask → plan`), live + orphan harness approval cards with tool-specific arg previews (Bash command, Edit diff, Write file/content, ExitPlanMode plan), `Approve all this turn` button that sends `bypass_rest_of_turn` and grants the in-memory turn bypass, `expired` decision wired through the chat reducer.

Planned shape:

- `TurnContext` carries Spindrel session id, channel id, bot id, turn id, workspace, harness resume id, permission mode, and a DB session factory.
- Runtime classification methods answer which tools are readonly, which prompt in `acceptEdits`, and which auto-approve in plan mode.
- Native harness approval requests create `ToolApproval` rows with `tool_type="harness"` and no linked `ToolCall`.
- `ApprovalRequestedPayload` carries `tool_type` so live and orphan cards can render a harness-specific approval card.
- `ApprovalResolvedPayload` gains `expired` so timeout/stop-turn cards do not remain pending.
- `Approve all this turn` is an in-memory turn bypass keyed by turn id, granted before resolving the first approval and revoked in `_run_harness_turn` finally cleanup.
- Stop-turn cancellation must cover both the slash-command path and the visible `/chat/cancel` path.

Open implementation checks:

- `/approval-mode` slash command cannot bypass `approvals:write` expectations just because slash commands currently lack request auth context.
- Session approval-mode endpoints must reuse normal session visibility/ownership checks, not only scope checks.
- Bypass-mode audit events should use a transcript shape the UI reducer actually keeps.
- Any background event publish should use primitive snapshots, not ORM objects crossing awaits.

## Phase 4 - Controls + Slash Commands — shipped 2026-04-26

What landed:

- `RuntimeCapabilities` + `HarnessSlashCommandPolicy` dataclasses on `app/services/agent_harnesses/base.py`; new `HarnessRuntime.capabilities()` Protocol method; both re-exported through `integrations.sdk`.
- Per-session `harness_settings` storage in `app/services/agent_harnesses/settings.py` — `load_session_settings`, `patch_session_settings` (PATCH semantics: missing key = no change, JSON `null` = clear, value = set; 256-char `model` guard).
- `TurnContext` extended with `model`, `effort`, `runtime_settings`. Claude adapter threads `ctx.model` → `ClaudeAgentOptions(model=...)`; Phase 5 changes Claude effort from "unsupported" to a runtime-owned model-scoped option mapped by the adapter after inspecting the installed SDK shape.
- REST endpoints `GET/POST /api/v1/sessions/{id}/harness-settings` (`approvals:read` / `approvals:write` scopes — same tier as approval-mode; explicitly noted as v1 expedience that may move to a dedicated `harness:write` later) + `GET /api/v1/runtimes/{name}/capabilities` (user auth).
- Header chrome: `HarnessHeaderChrome` now renders model pill (freeform popover when `model_is_freeform`, dropdown cycle when `model_options`/`supported_models` are set) + effort pill (model-scoped where available) + Phase 3 approval-mode pill. All target the surface's own `sessionId`.
- Slash commands: `/model` server-handled (drop `local_only=True`); channel-surface slash POSTs now carry `current_session_id` for the UI-current pane/session, validated against the channel, with `channel.active_session_id` only as the primary fallback. Harness `/model`, future harness `/effort`, `/stop`, `/compact`, `/plan`, `/context`, and default `/find` resolve through that current-session helper. `/effort` harness branch returns a friendly no-op when runtime declares no effort knob and **never** writes `channel.config['effort_override']`; `/help` and the catalog endpoint share one bot-id-aware filter via `useSlashCommandList(botId)` plumbed through 5 callers.
- Claude allowlist (conservative): `help, rename, stop, style, theme, clear, sessions, scratch, split, focus, model`; Phase 5 adds harness-aware `compact` and `context`. Excluded: `plan, find, effort, skills` (Spindrel-loop or runtime-conflicting semantics).

Tests:

- `tests/unit/test_harness_settings.py` — load/patch round-trip, null-clears, oversized-model guard, partial patches.
- `tests/unit/test_runtime_capabilities.py` — Claude capabilities shape, slash-policy intersection helper.
- `tests/unit/test_slash_commands_harness.py` — harness `/effort low` does NOT mutate `channel.config`, harness `/model` writes `harness_settings`, channel-surface explicit `current_session_id` wins over `active_session_id`, fallback to `active_session_id` still works, non-harness `/model` writes `channel.model_override`, harness-filtered `/help`, catalog endpoint intersection.
- `tests/integration/test_harness_settings_endpoints.py` — auth scopes, `_authorize_session_read` boundary, length guard, capabilities endpoint shape.

Known follow-ups (not blocking shipped):

- `tests/integration/test_turn_worker_harness_branch.py` — two persistence tests (`test_when_harness_succeeds_then_assistant_message_persisted_*`) fail on the committed baseline pre-Phase 4. Pre-existing; unrelated to this work.
- Per-runtime SDK kwarg shape (`ClaudeAgentOptions(model=...)`) is verified by smoke run only — if the SDK renames the kwarg, fix is local to `integrations/claude_code/harness.py`.

## Phase 5 - Native-Feel Foundation — in progress 2026-04-26

What is landing:

- `TurnContext.context_hints` plus `HarnessContextHint` for one-shot host context injection into runtime adapters.
- `app/services/agent_harnesses/session_state.py` owns per-session hint queue, compact reset timestamp, latest harness metadata lookup, and compact continuity summary generation.
- Harness `/compact` now means native runtime compaction only. For Claude Code it dispatches SDK `/compact`, records native compact status/metadata, and does not queue a Spindrel continuity summary or fake a new native session.
- `/new` and `/clear` open a fresh Spindrel session without deleting the old one. They are generic chat-session commands, not harness-only commands, and they do not mutate the channel primary/default pointer.
- Harness `/context` reports native harness state: runtime, selected model, approval mode, resume id, pending host hints, last turn, compact reset, and usage metadata.
- Bare harness `/model` and `/effort` render interactive picker cards; direct `/model <id>` and `/effort <level>` still mutate session settings.
- Heartbeats now have a `ChannelHeartbeat.runner_mode` switch. Harness channels default to harness-runner mode, which executes a real harness turn in the channel's primary session; opting into the Spindrel-agent runner exposes the normal heartbeat workflow/dispatch controls and requires an explicit heartbeat model. Harness heartbeat model/effort are per-run overrides and blank means inherit session/runtime defaults.
- Channel settings now hide normal-loop prompt/model/RAG/memory/context surfaces for harness bots and show runtime-oriented controls instead. Tool enrollment stays visible and is labeled as the Spindrel bridge source.
- Harness composer plan control is the canonical visible plan affordance; header duplicate state stays out of the harness chrome.
- Pending durable `core/harness_question` cards now get a sticky lane immediately above the composer in default and terminal chat modes, and freeform send is blocked until the pending interaction is answered.
- Workspace-files memory on a harness bot injects a host hint pointing the runtime at durable memory files; reads/writes still require native filesystem access or selected bridged tools.
- Claude Code gets a best-effort Spindrel tool bridge through SDK in-process MCP helpers. Tool definitions are resolved dynamically from the same effective channel/bot tool configuration as the normal loop, and invocation routes through `dispatch_tool_call` so policy, approval, trace rows, redaction, and result summarization stay centralized.
- Bridge/context visibility is no longer count-only: harness status and `/context` expose pending hint previews, bridge health, exported tools, ignored client tools, explicit one-turn tools, tagged skills, last bridge error, native compact status, and estimated native context remaining when usage/window telemetry exists. The existing ctx header status opens these details instead of adding another chip.
- Bridge inventory degrades visibly: local tool resolution and each MCP server list are isolated, inventory errors are recorded on bridge status, and harness `/context` caps live inventory at 3s before showing the last recorded bridge state. Broken MCP discovery should not make `/context` feel dead or collapse the whole bridge to an opaque generic error.
- Slash-command UX has an immediate pending path: remote commands toast as soon as submitted, harness `/compact` inserts a pending transcript card, and native compaction result cards summarize usage with raw JSON hidden behind a details disclosure. Harness status also marks latest native compaction as the context-remaining source when it is newer than the last harness turn.
- Harness channel settings include native auto-compaction prompts: default on, prompt below 60% remaining context, auto-run native compact below 10% remaining context when telemetry is available.
- Composer `+ -> Tools` can insert `@tool:<name>` for one-turn bridge exposure. Harness bridge execution is constrained to the exported tool set through `dispatch_tool_call(allowed_tool_names=...)`.
- Composer `+ -> Skills` / explicit `@skill:<id>` adds a tagged-skill index hint for the turn. Skill bodies remain progressive via bridged `get_skill` / `get_skill_list`; no native `.claude/skills` sync in Phase 5.
- Harness `/compact` renders an inspectable transcript card with continuity summary preview while still queuing the summary as a one-shot host hint.
- Claude Code `AskUserQuestion` now routes through a durable Spindrel native card (`core/harness_question`) instead of the SDK's transient prompt surface. The card is a persisted assistant message scoped to the current Spindrel session and renders in both default and terminal chat modes. Answering it writes a suppress-outbox user answer message, resolves the live SDK callback when present, or starts a fresh harness task in the same session if the callback disappeared after restart.
- 2026-04-27 follow-up: harness question answer rows are now hidden transport/audit rows, not transcript messages. The original question card is the durable read-only answer record, and Codex user-input expiry/cancel now ends the active turn instead of leaving the app-server notification wait stuck.
- 2026-04-27 follow-up: Stop now targets the visible harness session (`channel_id` + `session_id`) and `_run_harness_turn` cancels the runtime task when the shared session lock is cancelled. Cancelled harness turns persist a `turn_cancelled` assistant row with any partial tool transcript so refresh does not resurrect stale `(thinking...)` turns.
- Harness live tool breadcrumbs are now persisted on the synthetic assistant message as canonical `tool_calls` plus `assistant_turn_body`, so refresh keeps the native tool transcript instead of collapsing to final text only.
- 2026-04-27 follow-up: scheduled tasks targeting harness bots now run through `_run_harness_turn` instead of the normal Spindrel LLM loop. Task `model_override` and `harness_effort` live in `execution_config` as per-run overrides, with channel-targeted tasks resolving the channel's current primary session before execution.

Open verification:

- Smoke test the Claude SDK MCP helper names on the deployed harness image. The code degrades by disabling the bridge if the installed SDK lacks `create_sdk_mcp_server` / `tool`, but the exact helper signature needs runtime verification.
- Exercise a mutating bridged tool in ask mode and verify the existing Spindrel approval card flow resolves back into the harness tool result.
- Decide whether scheduled harness turns should target only the primary session forever or fan out to recently active scratch/split sessions when a channel has no obvious primary human context.
- Keep improving native context telemetry. Claude Code now has a best-effort context-window estimate and native compact event visibility, but runtime-provided pressure data would be better than deriving remaining percent from the latest usage payload.
- Smoke test Claude `AskUserQuestion` with the installed SDK and confirm `PermissionResultAllow(updated_input=...)` is accepted by the runtime version in the harness image.

## Phase 6 - Codex App-Server Harness V1 — shipped 2026-04-27

Plan file: `~/.claude/plans/partitioned-conjuring-finch.md`. Implemented the same day; see session log `vault/Sessions/agent-server/2026-04-27-N-codex-harness-integration.md` for the execution record.

### Locked decisions

- **No third-party Python SDK.** Talk to the official `codex app-server` JSON-RPC protocol over stdio (`${CODEX_BIN:-codex} app-server`). The third-party `codex-app-server-sdk` PyPI package is unofficial + AGPL and is rejected as a runtime dep.
- **Cleanup scope** = blockers only (the 6 smells below). Other smells filed for separate cleanup.
- **Approval contract** = thread-level Codex `approvalPolicy` + sandbox profile + Codex server-initiated approval requests routed into existing harness approval cards via `request_harness_approval`. Spindrel `dynamicTools` calls flow through `execute_harness_spindrel_tool` only — that already runs Spindrel policy/approval via `dispatch_tool_call`, so no second prompt.
- **Schema discipline** = all method names + enum values + envelope shapes live in `integrations/codex/schema.py`, sourced from the installed `codex` binary. No protocol literals in `harness.py` / `events.py` / `approvals.py`.
- **Capabilities** = sync, static fallback only. Live `model/list` is async and routes through `list_models()`.
- **Deployment** = `codex` binary is a server-side prerequisite. `auth_status()` distinguishes binary-missing from not-logged-in. Baking the binary into the harness image is a follow-up Loose End.

### Blocker smells to fix BEFORE adding Codex (Phase A)

1. UI hardcoded `claude-code` / `claude_code` literals: `ui/src/components/shared/BotPicker.tsx:17-18`, `ui/src/components/shared/ToolSelector.tsx:15`, `ui/src/utils/format.ts:10`. Capabilities endpoint already returns `display_name`; UI consumes it via new `useRuntimeCapabilities(runtime_id)` hook.
2. `_maybe_attach_spindrel_tool_bridge` in `integrations/claude_code/harness.py:530-649` mixes host-side bookkeeping with Claude-MCP wrapping. Lift host concerns into `app/services/agent_harnesses/tools.py::apply_tool_bridge(ctx, runtime, *, attach)`; runtime adapter passes a closure that wraps its own SDK shape.
3. `_build_ask_user_question_updated_input` (Claude `harness.py:474-510`) is generic. Move to `app/services/agent_harnesses/interactions.py::format_question_answer_for_runtime`.
4. `TurnContext` constructed in 3 drift-prone places (`turn_worker.py::_run_harness_turn:241-256`, `session_state.py::run_native_harness_compact:469-481`, `api_v1_sessions.py:986+`). Add `app/services/agent_harnesses/context.py::build_turn_context(...)` and wire all three callers.
5. `_apply_effort_option` host-side `inspect.signature` sniffer is brittle and incompatible with Codex. **Fix is NOT a `translate_options` Protocol** — keep all option construction inside each runtime's `start_turn`. Drop the host sniffer.
6. `app/services/agent_harnesses/tools.py:24` imports private `_resolve_approval_verdict` from `loop_dispatch`. Promote to public `resolve_approval_verdict`.

Also: move `HarnessToolSpec` + `HarnessBridgeInventory` from `tools.py` to `base.py` to avoid circular imports when the Protocol grows.

### New Codex integration files (Phase B)

```
integrations/codex/
  integration.yaml        # id: codex, provides: [harness], no settings
  __init__.py
  README.md
  app_server.py           # stdio JSON-RPC client (no third-party deps)
  schema.py               # constants from installed codex binary
  harness.py              # CodexRuntime — implements HarnessRuntime; self-registers
  events.py               # notification → ChannelEventEmitter
  approvals.py            # mode → (approvalPolicy, sandbox); server-request → Spindrel cards
```

Approval mapping intent (final values from schema):

| Spindrel mode | Codex `approvalPolicy` | Sandbox profile |
|---|---|---|
| `bypassPermissions` | most-permissive ("never"-equivalent) | most-permissive write |
| `acceptEdits` | on-request equivalent | workspace-write equivalent |
| `default` | on-request equivalent | workspace-write equivalent |
| `plan` | most-restrictive | read-only equivalent (+ host instruction) |

### Tests (Phase C)

`test_codex_app_server_client.py`, `test_codex_runtime_capabilities.py`, `test_codex_runtime_events.py`, `test_codex_runtime_bridge.py` (incl. dynamic-tools-unsupported path + no-double-prompt assertion), `test_codex_runtime_approvals.py`, plus updates to `test_runtime_capabilities.py` and the integration import boundary test.

### Open verification questions (resolve from installed binary, not docs)

- Confirm real `dynamicTools` tool-call path against the deployed runtime. `initialize` on local `codex-cli 0.125.0` does not advertise a capability map, so the adapter remains optimistic and records unsupported only when attach fails.
- Confirm Codex approval routing under a native mutating command in `default` mode.
- Confirm native compaction on a non-empty Codex thread.
- Confirm whether `turn/diff/updated` should become a user-visible breadcrumb/state update.

### Finish-line pass — 2026-04-27

- Fixed Spindrel planning not reaching Codex: `TurnContext` now carries the Spindrel session plan mode, and Codex sends `turn/start.collaborationMode = plan` plus read-only `sandboxPolicy` while the Spindrel session is `planning`, including resumed native threads.
- Updated Codex runtime controls to parse live `model/list` from `codex-cli 0.125.0`; model pickers now get `gpt-5.5`/`gpt-5.4`/`gpt-5.4-mini` with per-model effort values and defaults.
- Normalized Codex `thread/tokenUsage/updated` inside the Codex adapter, mapping `modelContextWindow` to Spindrel's generic `context_window_tokens`, so the ctx pill and `/context` can show estimated native context remaining instead of "unknown" once usage telemetry exists.
- Rechecked provider boundaries after review: core harness state reads normalized usage only and has no Codex raw-token branch.
- Treated Codex native plan items as plan text, not fake tool results, preserving the plan fallback without polluting the tool transcript.
- Local binary checks confirmed `account/read` and `model/list` shapes; focused Codex unit tests pass. DB-backed turn-worker harness tests skip under the local Python 3.14 harness as expected.
- Stabilized the Codex/Claude finish-line review findings: Codex user-input now uses the app-server response schema; app-server EOF wakes consumers instead of hanging turns; Codex dynamic-tool inventory changes force a fresh native thread; compact usage reuses normalized token telemetry; generated-schema drift checks cover the fields Spindrel depends on; Claude gets the documented streaming `PreToolUse` continue hook when supported.
- Fixed the shared harness turn worker regression where `build_turn_context(..., harness_metadata=harness_meta)` referenced an undefined local. The worker now loads latest persisted harness metadata before constructing `TurnContext`, so Claude Code turns no longer crash and Codex can still compare prior dynamic-tool signatures.
- Fixed Codex native-compact context status: Codex compact telemetry can report cumulative thread totals, so latest completed compacts now prefer post-compact `last_total_tokens` when present and otherwise treat oversized totals as historical reset telemetry instead of showing `0% left`.
- Fixed the related auto-compact loop: generic harness context pressure now prefers explicit current/context totals (`context_tokens`, `context_total_tokens`, `last_total_tokens`) before cumulative `total_tokens`, so Codex no longer retriggers native compaction after every response simply because the native thread's historical token counter exceeds the model window.

## Later - Skill Bridge

The tool bridge is now the base adapter for Spindrel-owned behavior. Phase 5 includes a first progressive lookup lane (`@skill` index hint + bridged `get_skill` / `get_skill_list`). Remaining skill work should build on it:

- simple Markdown skills can be exported/synced into harness-native skill directories;
- dynamic Spindrel skills should remain in Spindrel and be exposed through bridged `list/search/get skill` tools/resources;
- tool-backed skills should advertise which Spindrel bridge tools they require before export.

Two lanes are likely needed:

- **Export/sync lane:** simple Markdown skills can be copied or generated into harness-native skill folders such as `.claude/skills/`.
- **Lookup lane:** dynamic Spindrel skills remain in Spindrel and are exposed through bridge tools/resources such as `spindrel_list_skills`, `spindrel_search_skills`, and `spindrel_get_skill`.

Do not assume every Spindrel skill can be exported. Some skills reference Spindrel-only tools, policies, memories, or context that a native harness will not have unless the tool bridge is enabled.

## Docs To Keep In Sync

- `agent-server/docs/guides/agent-harnesses.md` remains the public operational guide and should be updated as Phase 3/4 land.
- `vault/Projects/agent-server/Architecture Decisions.md` should get short entries for load-bearing contract decisions, especially ToolApproval-without-ToolCall and runtime-owned tool classification.
- `vault/Projects/agent-server/Roadmap.md` should only carry the short current-state pointer to this track.

## Open Questions

- Should harness model/effort values be free-form, enumerated by runtime, or both?
- Should harness-native slash commands be cataloged for completion, passed through as raw text, or left entirely to the harness prompt?
- Should channel-level harness defaults exist, or should everything remain per-session until real duplication appears?
- Should the Spindrel tool bridge use MCP only, or keep a generic `HarnessToolAdapter` contract with MCP as Claude's transport?
- What is the minimal post-refresh transcript rehydration needed for native harness tool calls?

## Verification Gates

- `tests/unit/test_integration_import_boundary.py` stays green.
- Claude harness behavior remains unchanged in bypass/default sessions.
- Two concurrent sessions for one harness bot can hold different model, effort, and approval settings.
- Approval-deny, approval-timeout, stop-turn, and approve-rest-of-turn behavior are covered by tests.
- Bridged Spindrel tool calls, once implemented, produce the same policy/approval/trace behavior as normal Spindrel tool calls.
