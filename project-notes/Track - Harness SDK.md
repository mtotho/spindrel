---
tags: [agent-server, track, harnesses, integrations, sdk]
status: active
created: 2026-04-26
updated: 2026-04-26
---
# Track - Harness SDK

## North Star

Make external agent harnesses feel like first-class Spindrel sessions without pretending they are normal Spindrel bots. A harness owns the coding-agent loop, native tools, file edits, and native session id; Spindrel owns the browser UI, channel transcript, workspace path, session persistence, approvals, and any explicitly bridged Spindrel tools/skills.

This track covers the stable host contract used by Claude Code today and Codex later: approvals, per-session runtime controls, slash-command filtering, and optional bridges from harness runtimes back into Spindrel's tool and skill systems.

## Current State

- Claude Code is the only implemented harness runtime. It lives in `integrations/claude_code/harness.py`.
- Harness discovery/registration lives under `app/services/agent_harnesses`; active integration harness modules register runtime instances on import.
- Harness bots reuse standard Spindrel bot workspaces. The bot workspace directory is the harness cwd.
- A harness turn bypasses normal Spindrel context assembly, model selection, prompt injection, skills, knowledge bases, memory, and fanout. Host hints, manual compact continuity summaries, and selected Spindrel tools now have narrow bridge paths back into the runtime.
- Spindrel currently streams assistant text and live tool breadcrumbs into the channel, persists the final assistant message with tool breadcrumbs, and stores harness resume/cost metadata on assistant-message metadata for the Spindrel session.
- Phase 2 shipped the in-app terminal and per-session resume keying, plus a broad auto-approve `can_use_tool` shim so Claude Code does not stall on SDK permission prompts.
- Known-secret and common-pattern redaction now applies at the host boundary for harness streams and persisted final assistant text. Native harness tools still execute outside Spindrel's tool dispatcher, so a token printed by the harness should be treated as compromised even if the UI/transcript redacts it afterward.
- Phase 3 planning is converging on per-session approval modes that reuse `ToolApproval` rows and approval cards without creating linked `ToolCall` rows for native harness tools.
- The integration import boundary matters here: harness runtime modules should import host contracts through `integrations.sdk`, not directly from `app.*`, so the boundary test can stay meaningful.

## Invariants

- Runtime implementations live in `integrations/<id>/`; shared host contracts live in `app/services/agent_harnesses` and are re-exported through `integrations.sdk`.
- No Claude-only tool names or permission assumptions belong in core `app/` abstractions. Runtime adapters own tool classification and SDK-specific translation.
- Harness settings are session-scoped first. Multi-pane, scratch-session, and concurrent-session views must not accidentally mutate the channel primary. `channel.active_session_id` means primary/mirrored integration session only; web UI commands and harness controls must target the current component/querystring session id when one is present, falling back to `active_session_id` only when no explicit session is supplied.
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
| 5 | Native-feel foundation | in progress | Session-bound harness context hints, `/compact` resume reset + continuity summary, `/context`/status endpoint, heartbeat hint injection, channel settings cleanup, first Spindrel tool bridge via Claude SDK in-process MCP, durable harness question cards, and persisted harness tool breadcrumbs. Landed locally 2026-04-26; needs SDK smoke test on the harness image. |
| 6 | Codex runtime | planned | Implement Codex against the same `TurnContext`, approval, settings, status, tool-bridge, and runtime-capability contracts. |
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
- `TurnContext` extended with `model`, `effort`, `runtime_settings`. Claude adapter threads `ctx.model` → `ClaudeAgentOptions(model=...)`; effort/runtime_settings reserved for future runtimes.
- REST endpoints `GET/POST /api/v1/sessions/{id}/harness-settings` (`approvals:read` / `approvals:write` scopes — same tier as approval-mode; explicitly noted as v1 expedience that may move to a dedicated `harness:write` later) + `GET /api/v1/runtimes/{name}/capabilities` (user auth).
- Header chrome: `HarnessHeaderChrome` now renders model pill (freeform popover when `model_is_freeform`, dropdown cycle when `supported_models` set) + effort pill (only when `effort_values.length > 0`) + Phase 3 approval-mode pill. All target the surface's own `sessionId`.
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
- Harness `/compact` no longer runs normal Spindrel compaction. It stores a compact summary, sets a resume-reset marker so the next turn starts a fresh native harness session, and injects that summary as a one-shot hint.
- Harness `/context` reports native harness state: runtime, selected model, approval mode, resume id, pending host hints, last turn, compact reset, and usage metadata.
- Heartbeats on harness channels do not launch the normal Spindrel loop. They store the heartbeat prompt/preamble as a one-shot hint for the channel's primary session.
- Channel settings now hide normal-loop prompt/model/RAG/memory/tool-enrollment surfaces for harness bots and show a runtime summary instead. The hidden surfaces should come back only when they have harness-native semantics.
- Claude Code gets a best-effort Spindrel tool bridge through SDK in-process MCP helpers. Tool definitions are resolved dynamically from the same effective channel/bot tool configuration as the normal loop, and invocation routes through `dispatch_tool_call` so policy, approval, trace rows, redaction, and result summarization stay centralized.
- Claude Code `AskUserQuestion` now routes through a durable Spindrel native card (`core/harness_question`) instead of the SDK's transient prompt surface. The card is a persisted assistant message scoped to the current Spindrel session and renders in both default and terminal chat modes. Answering it writes a suppress-outbox user answer message, resolves the live SDK callback when present, or starts a fresh harness task in the same session if the callback disappeared after restart.
- Harness live tool breadcrumbs are now persisted on the synthetic assistant message as canonical `tool_calls` plus `assistant_turn_body`, so refresh keeps the native tool transcript instead of collapsing to final text only.

Open verification:

- Smoke test the Claude SDK MCP helper names on the deployed harness image. The code degrades by disabling the bridge if the installed SDK lacks `create_sdk_mcp_server` / `tool`, but the exact helper signature needs runtime verification.
- Exercise a mutating bridged tool in ask mode and verify the existing Spindrel approval card flow resolves back into the harness tool result.
- Decide whether heartbeat hints should target only the primary session forever or fan out to recently active scratch/split sessions when a channel has no obvious primary human context.
- Add richer harness context telemetry if/when a runtime exposes native context-window usage; current status is resume/usage/hint metadata, not a full token budget.
- Smoke test Claude `AskUserQuestion` with the installed SDK and confirm `PermissionResultAllow(updated_input=...)` is accepted by the runtime version in the harness image.

## Later - Skill Bridge

The tool bridge is now the base adapter for Spindrel-owned behavior. Skill work should build on it:

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
