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
| 3 | Harness approvals | planning | Per-session approval modes: `bypassPermissions`, `acceptEdits`, `default`, `plan`; approval cards for ask paths; stop-turn cancellation; boundary re-exports. |
| 4 | Harness control surface | planning | Runtime capabilities, per-session model/effort/settings endpoints, header/composer dropdowns, harness-aware `/model` and `/effort`, filtered slash-command UX. |
| 5 | Codex runtime | planned | Implement Codex against the same `TurnContext`, approval, settings, and runtime-capability contracts. |
| 6 | Spindrel tool bridge | planned | Adapter/MCP layer that exposes selected Spindrel tools to harnesses while preserving dispatch, policy, approval, traces, and result envelopes. |
| 7 | Skill bridge | planned | Export simple skills to harness-native skill folders and/or expose searchable Spindrel skills as bridged tools/resources. |
| 8 | Usage + observability | planned | Aggregate harness usage/cost into admin usage, expose runtime version/auth/health, and improve post-refresh tool-call rehydration. |

## Phase 3 - Approval Contract

Phase 3 introduces a shared approval helper in `app/services/agent_harnesses/approvals.py` and lets each runtime translate Spindrel's `AllowDeny` result into its SDK-native permission shape.

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

## Phase 4 - Controls + Slash Commands

Harness channels should expose runtime-native controls rather than hiding model controls entirely.

Planned contract:

- Add runtime capabilities such as display name, configurable controls, supported model suggestions, effort values, approval modes, and slash-command policy.
- Store per-session harness settings under `Session.metadata["harness_settings"]`, with channel-level defaults deferred.
- Extend `TurnContext` with resolved harness model, effort, and opaque runtime settings.
- Claude maps settings to `ClaudeAgentOptions(model=..., effort=...)`; Codex maps the same host settings to its own adapter later.
- Replace the current `hideModelOverride` behavior with harness-aware model and effort pills/dropdowns.
- Filter slash commands for harness sessions. Keep broadly useful commands such as `/help`, `/rename`, `/stop`, `/style`, `/theme`, `/clear`, `/scratch`, `/sessions`, `/split`, and `/focus`; hide misleading normal-agent commands that imply Spindrel context/tool control.
- Make `/model`, `/effort`, and `/approval-mode` session-scoped and harness-aware when the active bot has a harness runtime.
- Fix `/help` so it reflects the filtered command catalog for the current surface/runtime.

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
