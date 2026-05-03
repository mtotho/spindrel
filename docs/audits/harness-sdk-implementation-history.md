---
title: Harness SDK Implementation History
summary: Compressed history extracted from the Harness SDK track so the active track can remain a current-state epic instead of a session log.
status: reference
tags: [spindrel, audit, harnesses, history]
created: 2026-05-03
updated: 2026-05-03
---

# Harness SDK Implementation History

This audit preserves the historical shape of the Harness SDK effort after the
active track was compressed on 2026-05-03. The current source of truth for
active status is `docs/tracks/harness-sdk.md`; feature-by-feature parity lives
in `docs/guides/harness-parity.md`.

## Extracted From Track

Before compression, `docs/tracks/harness-sdk.md` had grown to roughly 800 lines
and mixed five kinds of information:

- active current-state track content;
- dated implementation diary entries;
- parity rerun and screenshot proof notes;
- SDK/app-server investigation notes;
- Project-run loop and local e2e workflow notes.

The current track now links here instead of carrying that history inline.

## Phase History

| Phase | Historical Summary |
|---|---|
| 1. Claude Code baseline | Established Claude Code as a web-accessible harness runtime with workspace reuse, auth/status surface, terminal login, resume metadata, and transcript persistence. |
| 2. Resume and approval cleanup | Stabilized per-session resume keying and broad auto-approval cleanup so SDK permission stalls did not block ordinary turns. |
| 3. Approval contract | Added harness-specific approval cards backed by Spindrel `ToolApproval` rows, runtime-owned tool classification, approve-rest-of-turn, stop/cancel handling, and UI support for pending/expired cards. |
| 4. Controls and slash commands | Added `RuntimeCapabilities`, session-scoped harness settings, runtime model/effort controls, capabilities endpoints, harness-aware `/model` and `/effort`, and current-session targeting for multi-pane/session surfaces. |
| 5. Native-feel foundation | Added host hints, native compaction, `/context`, `/new`, `/clear`, channel setting cleanup, bridge status, durable `AskUserQuestion` cards, persisted native tool breadcrumbs, queued follow-ups, native auto-compaction, and bridge tool/skill discovery. |
| 6. Codex app-server runtime | Implemented Codex through the official `codex app-server` JSON-RPC protocol over stdio. Added schema constants, event translation, approval mapping, dynamic Spindrel tools, app-server management summaries, model/usage telemetry, and native CLI fallback paths. |
| 7. Skill bridge | Added tagged skill hints and bridged `get_skill` / `get_skill_list`. Future work remains for exporting simple Markdown skills into runtime-native skill directories. |
| 8. Parity loop automation | Added repo-dev scripts and skills for harness parity iteration, local batch presets, tested-runtime observations, and Project coding-run loop receipts. The loop uses existing Project run/schedule primitives rather than adding a product-only parity surface. |

## Notable Verification History

- Local and deployed harness parity runs covered core turns, bridge tools,
  native slash commands, terminal/default transcript rendering, replay/refetch,
  plan mode, native CLI mirroring, queued follow-ups, model/effort survival,
  SDK surfaces, image input, browser automation, and Project cwd instruction
  discovery.
- Durable screenshots were captured under `docs/images/harness-*.png` and are
  referenced from harness guides rather than stored in the track.
- Codex app-server schema inspection and unit tests guard method drift for the
  surfaces Spindrel depends on.
- Claude adapter tests guard installed Python SDK option-shape behavior and
  avoid claiming TypeScript-only Agent SDK surfaces.
- Local e2e/parity scripts eventually moved toward agent-owned native API ports
  and private state directories to avoid shared scratch/env collisions.

## Historical Decisions

- Codex uses the official installed `codex app-server` binary over stdio, not a
  third-party Python SDK.
- Runtime adapters own native option construction and SDK/app-server
  translation. Core host code owns generic `TurnContext`, session settings,
  approval plumbing, transcript persistence, and bridge dispatch.
- Spindrel bridge tools execute through normal Spindrel dispatch, policy,
  approval, trace, redaction, and result summarization.
- Claude local/first-party auth is operator-owned for this self-hosted path.
  Spindrel should not imply that hosted third-party Claude SDK deployment is
  supported through local Claude Code login.
- Native CLI mirroring is evidence and continuity; runtime-specific resume
  semantics still decide whether a later SDK/app-server turn can see CLI-created
  leaves.

## Current Pointers

- Active track: `docs/tracks/harness-sdk.md`
- Parity matrix: `docs/guides/harness-parity.md`
- Harness guide: `docs/guides/agent-harnesses.md`
- Project run workflow: `.spindrel/WORKFLOW.md`
- Open bugs and follow-ups: `docs/inbox.md`
