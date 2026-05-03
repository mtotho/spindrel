---
name: Harness Parity Loop
description: >
  Bounded supervised loop that drives Codex/Claude harness chats toward
  feature parity with their native CLIs. Each iteration runs the parity
  suite against a leased ephemeral e2e stack, picks one failure, opens the
  spec row, makes the smallest fix, commits, and publishes a loop receipt.
  Concrete instance of the supervised-iteration recipe.
triggers: fix harness parity, run the parity loop, make codex match the terminal, make claude match the cli, harness parity sweep
category: project
---

# Harness Parity Loop

This skill runs inside a normal Project coding-run session. The session should
already have its isolated work surface and private Docker daemon prepared by
Spindrel before the first turn starts. Do not bootstrap or restart the host
Spindrel API from inside the iteration agent.

It is a concrete configuration of `.agents/skills/spindrel-supervised-loop/SKILL.md` —
read that parent recipe before running this; it owns the procedure shape,
the mode matrix, and the stop conditions.

**Prerequisite**: `scratch/agent-e2e/harness-parity.env` exists in this
session work surface. If it is missing, publish a blocked receipt that says
the parity harness was not pre-seeded; do not run repo-dev bootstrap helpers.

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
2. If it is missing, publish a blocked loop receipt and stop.
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
  helpers from inside the loop. Harness lifecycle belongs to the host/session
  provisioner, not to the iteration agent.
