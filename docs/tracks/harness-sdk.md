---
title: Harness SDK
summary: First-class Claude Code and Codex harness runtimes in Spindrel, with parity, controls, bridge tools, native CLI mirroring, and Project-run automation.
status: active
tags: [spindrel, track, harnesses, integrations, sdk]
created: 2026-04-26
updated: 2026-05-03
---

# Harness SDK

## North Star

Make external coding-agent runtimes feel like first-class Spindrel sessions
without pretending they are normal Spindrel bots. The runtime owns native
agent behavior: CLI/SDK loop, native tools, file edits, and native session id.
Spindrel owns the host experience: browser UI, channel transcript, session
persistence, approvals, workspace/project surface, orchestration, and any
explicitly bridged Spindrel tools or skills.

## Current State

- Claude Code and Codex are implemented harness runtimes in
  `integrations/claude_code/harness.py` and `integrations/codex/harness.py`.
- Claude's public SDK surface is now branded as the Claude Agent SDK. Spindrel
  still uses Claude Code as the runtime/operator label where the installed
  local CLI is the actual execution engine, but docs and UI copy should avoid
  presenting Spindrel as "Claude Code" itself.
- The canonical feature-by-feature parity ledger is
  [Claude Code and Codex Harness Parity](../guides/harness-parity.md). Keep
  that guide updated when parity tests, screenshots, runtime support, or SDK
  support changes.
- Shared harness host contracts live under `app/services/agent_harnesses` and
  must be re-exported through `integrations.sdk` for integration-boundary
  imports.
- Harness turns bypass normal Spindrel context assembly, prompt injection,
  RAG, memory, skills, and fanout unless a narrow bridge path explicitly
  admits the surface.
- Spindrel streams assistant text and native tool breadcrumbs, persists
  transcript rows for refresh/replay, stores runtime session/resume/cost
  metadata, and redacts known secrets at the host boundary.
- Per-session approval mode, model, effort, runtime settings, plan mode,
  native CLI mirroring, queued follow-ups, durable harness question cards,
  `/compact`, `/context`, `/new`, `/clear`, and selected Spindrel bridge tools
  are live.
- Scheduled/manual task runs can execute real harness turns with per-run
  overrides without mutating interactive session settings.
- Project coding runs are expected to use formal session execution
  environments: generated branch/worktree, assigned dev targets, and private
  Docker daemon when provisioned.
- Current local tested tuple is Codex `codex-cli 0.128.0` and Claude Code
  `2.1.126`. `prepare-harness-parity`, smoke, SDK, CLI, and the focused native
  CLI compatibility regressions are green on that tuple; full strict replay is
  still the next baseline artifact to record.

## Status

| Phase | State | Updated | Notes |
|---|---|---|---|
| 1. Claude Code web harness baseline | shipped | 2026-04-26 | Remote Claude Code sessions from the web UI, auth/status, workspace reuse, resume/cost persistence. |
| 2. Resume and approval cleanup | shipped | 2026-04-26 | Per-session resume keying and SDK permission stall cleanup. |
| 3. Harness approvals | shipped | 2026-04-26 | Session approval modes, approval cards, stop/cancel, approve-rest-of-turn. |
| 4. Runtime controls and slash commands | shipped | 2026-04-26 | Runtime capabilities, session-scoped harness settings, `/model`, `/effort`, `/help`, current-session targeting. |
| 5. Native-feel foundation | shipped | 2026-04-27 | Host hints, native compaction, question cards, bridge inventory, queued follow-ups, transcript replay. |
| 6. Codex app-server runtime | shipped | 2026-04-27 | Official `codex app-server` JSON-RPC integration, schema guards, app-server notifications, native command surface. |
| 7. Skill and tool bridge | active | 2026-05-02 | Tagged skills and bridged skill/tool lookup are live. Native skill export/sync remains future work. |
| 8. Usage, observability, and parity automation | active | 2026-05-03 | Usage rows, auth/version status, replay diagnostics, parity loop substrate. Tested-version drift surfacing remains open. |

## Phase Detail

Phases 1-6 are shipped and compressed here by design. Claude Code established
the host contract, session persistence, status/auth, approvals, runtime
settings, native-feel commands, bridge inventory, and transcript replay. Codex
then proved that the same host contract can drive a different native runtime
through the official app-server JSON-RPC protocol rather than a Claude-shaped
adapter.

Phase 7 remains open for bridge shape, not for basic function. Tagged
Spindrel skills and selected tools can already be exposed to Claude through SDK
MCP helpers and to Codex through `dynamicTools`. Native registry sync/export is
deferred until there is a clear user workflow; automatic registry sync would
blur runtime ownership and make parity harder to reason about.

Phase 8 is the active reliability lane. The next meaningful work is to make
runtime drift visible, write a tested-runtime manifest from parity batches,
record a clean full strict replay for the current tuple, and keep app-server
schema/version checks ahead of runtime upgrades.

## Current Green Surface

The detailed evidence belongs in the parity ledger. Current verified surfaces
include:

- core Codex and Claude turns from Spindrel channels with native session/thread
  persistence, stop/cancel, usage rows, model/effort controls, and persisted
  transcript refetch;
- native slash/direct command rendering, including Codex app-server management
  summaries and Claude terminal-handoff behavior for TTY-oriented commands;
- plan-mode round trips, runtime model/effort survival across turns/refetch,
  and native CLI to Spindrel settings sync;
- ordered native tool transcripts in default and terminal chat modes;
- selected Spindrel bridge tools via Claude SDK MCP helpers and Codex
  `dynamicTools`;
- browser automation calls through the shared Playwright runtime;
- native image input/semantic reasoning;
- Claude SDK filesystem surfaces such as project instructions, skills,
  plugins, programmatic agents/MCP, selected hooks, `TodoWrite`,
  `ToolSearch`, `AskUserQuestion`, and native subagents;
- Codex app-server surfaces such as dynamic tools, MCP startup/status,
  account/model/auth/rate-limit lifecycle, terminal interaction notifications,
  app/config/fs/plugin/skill/native inventory summaries, granular permission
  request handling, CLI-first resume fallback, and schema drift checks.

## Active Gaps

- **Runtime version drift.** Codex has a minimum-version guard; both runtimes
  still need a tested-runtime manifest surfaced in auth/status/capabilities so
  operators can see "tested on X, installed Y" before parity fails.
- **Full strict replay baseline.** The current Claude/Codex tuple is green for
  prepare, smoke, SDK, CLI, focused CLI regressions, and unit coverage, but a
  full strict parity replay has not yet been recorded as the post-upgrade
  artifact.
- **Claude Agent SDK naming and auth boundary.** Upstream docs now call this
  the Claude Agent SDK, and Anthropic's SDK docs distinguish API-key/provider
  auth from locally operator-owned claude.ai login. Spindrel should keep the
  local auth path explicit and avoid product copy that implies Spindrel is
  itself Claude Code.
- **Claude SDK asymmetry.** Some public Claude Agent SDK hook/events are
  TypeScript-only. Python adapter claims must stay limited to installed Python
  SDK support.
- **Claude file checkpointing/forking.** Advanced passthrough knobs exist, but
  there is no Spindrel UI workflow or parity scenario for checkpoint browsing,
  rewind, or conflict semantics.
- **Codex experimental app-server APIs.** `dynamicTools` remains experimental;
  Spindrel must keep bridge tools opt-in and degrade clearly on method/schema
  drift.
- **Codex app-server stable surface follow-up.** Recent docs include account
  rate-limit updates, granular permission request semantics, fs/watch
  notifications, and stable-vs-experimental schema generation. Existing support
  covers the main notifications and permission flow; the track should keep
  parity rows current as these become user-visible in Spindrel.
- **Codex native `/context`.** Current app-server support has no read-only
  native context equivalent to Claude SDK `/context`; terminal handoff remains
  the honest result.
- **Live collaboration/subagent proof.** Unit/event rendering exists, but
  deterministic live Codex collaboration/subagent proof is still thin.
- **Project-run Docker isolation.** Formal Project runs should use the session
  execution environment and private daemon. Raw host Docker remains outside
  normal harness-run expectations.

## Key Invariants

- Runtime implementations live in `integrations/<id>/`; shared host contracts
  live under `app/services/agent_harnesses` and are re-exported through
  `integrations.sdk`.
- No Claude-only tool names, Codex method names, or permission assumptions
  belong in core `app/` abstractions. Runtime adapters own translation.
- Harness settings are session-scoped first. Multi-pane, secondary sessions,
  and concurrent sessions must not mutate the channel primary unless the user
  explicitly targets that primary.
- Scheduled/task harness runs inherit session model/effort unless the task
  supplies per-run overrides. Per-run overrides must not mutate
  `Session.metadata_["harness_settings"]`.
- Normal tool pickers remain visible for harness bots, but they define the
  Spindrel bridge tool set rather than normal-loop context injection.
- Harness-native tools remain native. Bridged Spindrel tools must execute
  through Spindrel policy, approval, trace, redaction, and result rendering.
- Host events must pass through Spindrel redaction before publication or
  persistence. Redaction does not make a printed credential safe to keep using.
- Project coding runs must not infer isolation from cwd text alone; they should
  read execution-environment/work-surface readiness.

## References

- [Harness parity ledger](../guides/harness-parity.md)
- [Agent harnesses guide](../guides/agent-harnesses.md)
- [WorkSurface isolation](../guides/worksurface-isolation.md)
- [Project workflow contract](../../.spindrel/WORKFLOW.md)
- [Implementation history audit](../audits/harness-sdk-implementation-history.md)
- Claude Agent SDK overview: <https://code.claude.com/docs/en/agent-sdk/overview>
- Claude Agent SDK filesystem features: <https://code.claude.com/docs/en/agent-sdk/claude-code-features>
- Claude Agent SDK hooks: <https://code.claude.com/docs/en/agent-sdk/hooks>
- Claude Agent SDK checkpointing: <https://code.claude.com/docs/en/agent-sdk/file-checkpointing>
- Codex app-server protocol: <https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md>

## Verification Gates

- `tests/unit/test_integration_import_boundary.py` stays green.
- Claude and Codex harness behavior remains stable in bypass/default/plan
  sessions.
- `prepare-harness-parity --skip-ui-build`, smoke, SDK, and CLI presets stay
  green before the tested-runtime manifest is bumped.
- Two concurrent sessions for one harness bot can hold different model, effort,
  approval, and runtime settings.
- Approval deny, timeout, stop-turn, approve-rest-of-turn, queued follow-up,
  replay, and native CLI mirror paths stay covered.
- Bridged Spindrel tool calls produce the same policy/approval/trace/result
  behavior as normal Spindrel tool calls.
