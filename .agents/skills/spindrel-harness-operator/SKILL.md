---
name: spindrel-harness-operator
description: "Use when editing Spindrel agent harness support: Codex and Claude runtime adapters, native command metadata, slash commands, approvals, harness sessions, task execution, and runtime capability tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel Harness Operator

This is a repo-dev skill for agents editing Spindrel source. It is not a Spindrel runtime skill and must not be imported into app skill tables.

## Start Here

1. Read `CLAUDE.md` and `docs/guides/agent-harnesses.md`.
2. Read `docs/guides/tool-policies.md` before changing approvals or
   permissions.
3. Read `docs/guides/task-sub-sessions.md` and `docs/guides/projects.md` when
   harness execution is task-backed or Project-rooted.
4. Inspect both Codex and Claude paths before changing a shared runtime
   contract.

## Do

- Keep runtime adapters thin around the native harness capabilities they expose.
- Preserve approval, cancellation, trace, model, effort, cwd, and session
  metadata across the bridge.
- Prefer capability inventory and native metadata over mirroring another
  runtime's internal skill or plugin registry into Spindrel tables.
- Add tests for native command parity, runtime params, approval requests, and
  task execution when those surfaces change.

## Avoid

- Do not claim repo `.agents/skills` are visible to in-app channel bots.
- Do not add folder sync, runtime import, or bridge mounting unless the task is
  explicitly about that runtime boundary.
- Do not silently degrade approval semantics to make a harness call easier.
- Do not fork Codex and Claude behavior unless their native contracts differ.

## Completion Standard

Run the focused harness runtime tests for the adapter touched, then any shared
slash-command or runtime-capability tests that cover the changed contract.
