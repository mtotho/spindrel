---
name: spindrel-harness-operator
description: "Use when editing Spindrel agent harness support: Codex and Claude runtime adapters, native command metadata, slash commands, approvals, harness sessions, task execution, and runtime capability tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel Harness Operator

This is a repo-dev skill for any agent editing this checkout: local CLI on the
operator's box, in-app Spindrel agent on the server, or a Project coding run.
It is not a Spindrel runtime skill and must not be imported into app skill
tables.

## Start Here

1. Read `CLAUDE.md` and `docs/guides/agent-harnesses.md`.
2. Read `docs/guides/tool-policies.md` before changing approvals or
   permissions.
3. Read `docs/guides/task-sub-sessions.md` and `docs/guides/projects.md` when
   harness execution is task-backed or Project-rooted.
4. Inspect both Codex and Claude paths before changing a shared runtime
   contract.

## Triage primitives

| Need | Primitive |
|---|---|
| Codex adapter | `rg -n "" app/agent/ \| grep -i codex` (start with `codex_*` modules) |
| Claude adapter | `rg -n "" app/agent/ \| grep -i claude` |
| Approval / cancellation contract | shared services under `app/services/` (approvals, tasks) |
| Native command metadata | the runtime adapter's command registry |
| Parity tests | `tests/unit/test_harness_*` and `tests/unit/test_*_parity*` |
| Run the parity suite | `./scripts/run_harness_parity_local.sh --tier core` (see `spindrel-e2e-development`) |

## Named patterns to grep for

- **Native command parity drift** — Codex registers a slash command Claude doesn't, or vice versa. The parity test should fail; if it doesn't, the test is missing the command.
- **Approval-request envelope dropped across the bridge** — task or tool approval emitted by the runtime but not surfaced to Spindrel's approval queue. Trace: look for the approval `correlation_id` in both runtimes' adapters.
- **Trace `correlation_id` not threaded through** — the runtime turn produces a trace that doesn't link back to the harness session. Adapter must thread it explicitly.
- **Slash-command metadata diverging between runtimes** — same command, different param names / help text. Should mirror native; if native diverges, document the difference rather than silently aliasing.

## Worked example: add a new slash command supported by both runtimes

1. Confirm the native command exists in both Codex and Claude (or document why it's runtime-specific).
2. Register in both adapters with mirrored param names + help text.
3. Add a parity test that asserts the command surface matches in both adapters.
4. Preserve approval/cancellation/trace metadata across the bridge — the command must not silently drop any of these.
5. Run `./scripts/run_harness_parity_local.sh --tier core -k <command_name>` until green.

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
