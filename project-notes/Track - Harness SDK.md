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
- A harness turn bypasses normal Spindrel context assembly, model selection, prompt injection, tools, skills, knowledge bases, memory, compaction, and fanout.
- Spindrel currently streams assistant text and live tool breadcrumbs into the channel, persists the final assistant message, and stores harness resume/cost metadata on the bot/session state.
- Phase 2 shipped the in-app terminal and per-session resume keying, plus a broad auto-approve `can_use_tool` shim so Claude Code does not stall on SDK permission prompts.
- Known-secret and common-pattern redaction now applies at the host boundary for harness streams and persisted final assistant text. Native harness tools still execute outside Spindrel's tool dispatcher, so a token printed by the harness should be treated as compromised even if the UI/transcript redacts it afterward.
- Phase 3 planning is converging on per-session approval modes that reuse `ToolApproval` rows and approval cards without creating linked `ToolCall` rows for native harness tools.
- The integration import boundary matters here: harness runtime modules should import host contracts through `integrations.sdk`, not directly from `app.*`, so the boundary test can stay meaningful.

## Invariants

- Runtime implementations live in `integrations/<id>/`; shared host contracts live in `app/services/agent_harnesses` and are re-exported through `integrations.sdk`.
- No Claude-only tool names or permission assumptions belong in core `app/` abstractions. Runtime adapters own tool classification and SDK-specific translation.
- Harness settings are session-scoped first. Multi-pane, scratch-session, and concurrent-session views must not accidentally mutate a channel-wide active session.
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
| 4 | Harness control surface | shipped | `RuntimeCapabilities` Protocol; per-session `harness_settings` (model/effort/runtime_settings); `GET /runtimes/{name}/capabilities`; `GET/POST /sessions/{id}/harness-settings`; header model + effort pills (per-session, alongside Phase 3 approval-mode pill); harness-aware `/model` (resolves `channel.active_session_id` from channel surface) and `/effort` (friendly no-op when runtime declares no effort knob — never mutates `channel.config`); `?bot_id=` filter on `/api/v1/slash-commands` and `/help`. Shipped 2026-04-26. |
| 5 | Codex runtime | planned | Implement Codex against the same `TurnContext`, approval, settings, and runtime-capability contracts. |
| 6 | Spindrel tool bridge | planned | Adapter/MCP layer that exposes selected Spindrel tools to harnesses while preserving dispatch, policy, approval, traces, and result envelopes. |
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
- Slash commands: `/model` server-handled (drop `local_only=True`); harness path resolves `channel.active_session_id` from a channel-surface POST so the composer's `/model X` works; `/effort` harness branch returns a friendly no-op when runtime declares no effort knob and **never** writes `channel.config['effort_override']`; `/help` and the catalog endpoint share one bot-id-aware filter via `useSlashCommandList(botId)` plumbed through 5 callers.
- Claude allowlist (conservative): `help, rename, stop, style, theme, clear, sessions, scratch, split, focus, model`. Excluded: `compact, plan, context, find, effort, skills` (Spindrel-loop or runtime-conflicting semantics).

Tests:

- `tests/unit/test_harness_settings.py` — load/patch round-trip, null-clears, oversized-model guard, partial patches.
- `tests/unit/test_runtime_capabilities.py` — Claude capabilities shape, slash-policy intersection helper.
- `tests/unit/test_slash_commands_harness.py` — harness `/effort low` does NOT mutate `channel.config`, harness `/model` writes `harness_settings`, channel-surface fallback to `active_session_id`, non-harness `/model` writes `channel.model_override`, harness-filtered `/help`, catalog endpoint intersection.
- `tests/integration/test_harness_settings_endpoints.py` — auth scopes, `_authorize_session_read` boundary, length guard, capabilities endpoint shape.

Known follow-ups (not blocking shipped):

- `tests/integration/test_turn_worker_harness_branch.py` — two persistence tests (`test_when_harness_succeeds_then_assistant_message_persisted_*`) fail on the committed baseline pre-Phase 4. Pre-existing; unrelated to this work.
- Per-runtime SDK kwarg shape (`ClaudeAgentOptions(model=...)`) is verified by smoke run only — if the SDK renames the kwarg, fix is local to `integrations/claude_code/harness.py`.

## Later - Tool Bridge

A harness tool bridge should be explicit and opt-in. The recommended adapter is a server-side bridge, likely MCP for Claude, that converts selected Spindrel tools into harness-visible tool definitions and routes invocation back through Spindrel.

Required properties:

- Tool definitions are derived from existing Spindrel registry schemas.
- Invocation goes through existing dispatch paths, not direct Python function calls from the harness.
- Tool policies, capability approvals, scoped auth, trace events, and widget/result envelopes continue to apply.
- Mutating tools are not exposed until approval semantics are proven end-to-end.
- Tool names should be namespaced, probably `spindrel__<tool_name>`, to avoid collisions with native harness tools.

Suggested rollout:

1. Expose a tiny read-only tool set first, such as search/list/get operations with JSON/text results.
2. Add mutating tools only after approval cards and denial behavior are stable.
3. Add widget/result envelope handling as a follow-up so bridged tools can still pin dashboards or render rich cards when invoked by a harness.

## Later - Skill Bridge

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
