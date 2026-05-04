---
name: spindrel-harness-parity-loop
description: "Use when the user asks to fix harness parity, run the parity loop, make Codex match the terminal, make Claude match the CLI, or run a harness parity sweep. Bounded supervised loop driving Codex/Claude harness chats toward feature parity with their native CLIs — one fix per iteration. Concrete instance of `spindrel-supervised-loop`. Repo-dev skill — not a Spindrel runtime skill."
---

# Harness Parity Loop

This is a repo-dev skill. It is not a Spindrel runtime skill and must not be
imported into app skill tables.

This skill runs inside a normal Project coding-run session. The session should
already have its isolated work surface and private Docker daemon prepared by
Spindrel before the first turn starts. Do not bootstrap or restart the host
Spindrel API from inside the iteration agent.

For continuation iterations, expect a new Project task/session and a newly
prepared isolated worktree/private Docker daemon. Reuse the same logical work
branch and existing PR/handoff from the loop lineage: prepare or fast-forward
that branch, make one focused commit, and update the same PR. If branch or PR
reuse is impossible, publish `needs_review` or `blocked` instead of creating a
replacement PR.

For scheduled Project runs, the run should select the `harness-parity` run
environment profile. That profile owns `prepare-harness-parity`, writes
`scratch/agent-e2e/harness-parity.env`, and records pre-agent setup evidence
before the model starts. The iteration agent should consume that prepared
surface; it should not create a second stack or restart another run's server.

It is a concrete configuration of `.agents/skills/spindrel-supervised-loop/SKILL.md` —
read that parent recipe before running this; it owns the procedure shape,
the mode matrix, and the stop conditions.

**Prerequisite**: `scratch/agent-e2e/harness-parity.env` exists in this
session work surface. If it is missing, publish a blocked receipt that says
the `harness-parity` run environment profile did not prepare the surface; do
not run repo-dev bootstrap helpers from the agent turn.

## Run Brief

Use this bounded brief unless the user provides a narrower one:

- **Source document:** `docs/guides/harness-parity.md` plus the generated gap
  report under `.spindrel/audits/harness-parity/`.
- **Mission:** fix one concrete harness parity gap from the selected tier.
- **Stop when:** the selected gap is fixed, tested, committed, pushed, and a
  loop receipt is published; or the tier is green; or the next useful action
  requires spec changes, missing infrastructure, or human review.
- **Stay inside:** harness adapter/runtime modules named by the gap report.
  Do not edit the parity spec to make the failure disappear.
- **Evidence:** gap report, focused test command, verification result, commit,
  branch/PR when available, and Project run receipt.
- **Update:** write the per-iteration audit report and keep any active track
  update concise; do not paste command history into the track.
- **Review handoff:** summarize fixed gap, remaining count, blockers, and the
  next Run Brief if more parity work remains.

The parity loop is not "keep improving harnesses forever." Each iteration is
one selected parity gap inside this brief.

## Slot-in declarations

Per the supervised-iteration contract:

- **`mode`**: `plan_heavy`. Parity fixes harness-adapter code (Codex JSON-RPC,
  Claude SDK plumbing); there is no UX surface to sample-screenshot.
- **`suite_runner`**:
  ```bash
  python scripts/harness_parity_loop_iteration.py --tier <tier>
  ```
  Default tier is `core`. The script reads
  `scratch/agent-e2e/harness-parity.env`, invokes
  `./scripts/run_harness_parity_local_batch.sh` with `--junitxml` pointed at
  a per-iteration path, parses the JUnit, and writes the gap report under
  `.spindrel/audits/harness-parity/<YYYYMMDD-HHMM>.md` of the canonical
  Spindrel repo. Stdout = the report path.
- **`spec_source`**: `docs/guides/harness-parity.md` — the 76-row matrix of
  Native / Partial / Terminal handoff / Missing labels per surface. The
  loop runner already grep-matches each failing test name back to its row;
  open that row plus the linked Evidence anchor before changing code.
- **`owning_module_heuristic`**: see
  `scripts/harness_parity_loop_iteration.py::_OWNING_HEURISTICS`. Codex
  failures route to `integrations/codex/harness.py`; Claude SDK failures to
  `integrations/claude_code/harness.py`; native CLI mirror failures to
  `app/services/agent_harnesses/native_cli_mirror.py`; etc. The script
  passes its best guess on each gap.
- **`gap_artifact_path`**: `.spindrel/audits/harness-parity/<ts>.md`.

## First action

1. Confirm `scratch/agent-e2e/harness-parity.env` exists.
2. If it is missing, publish a blocked loop receipt that points at the missing
   `harness-parity` run environment profile/preflight and stop.
3. If it exists, hand off to the supervised-iteration procedure with the
   slot-ins above.

## Default budget

When the user does not specify, run:

- `tier=core`
- `max_iterations=5`
- `max_time_minutes=60`

Bigger sweeps (`tier=bridge` and beyond) usually want
`max_iterations=10 max_time_minutes=180` and an overnight schedule rather
than a manual kickoff — the user can ask for that explicitly.

## Stop conditions specific to this loop

In addition to the parent skill's stop list:

- **`reason: "stack_unhealthy"`** if the e2e stack stops responding mid-loop
  (the parity script will exit non-zero with no JUnit; the runner reports
  this and the loop stops).
- **`reason: "spec_drift_detected"`** if a fix would require editing
  `docs/guides/harness-parity.md` itself (the loop is for code fixes;
  spec drift is a separate slice that goes to the user).

## Out of scope

- Touching `docs/guides/harness-parity.md` to relabel a surface from
  `Missing` to `Native`. The loop only fixes code; the matrix update is a
  separate edit per the parent skill's "no spec edits" boundary.
- Auto-merging the per-iteration PR. Merges happen in the morning review
  pass.
- Running `prepare-harness-parity`, `start-api`, or other repo-dev bootstrap
  helpers from inside the loop. Harness lifecycle belongs to the Project run
  environment profile/preflight, not to the iteration agent.
