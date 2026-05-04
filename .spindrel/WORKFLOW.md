---
name: Spindrel Development Workflow
summary: Repo-local contract for agents working on Spindrel through local CLI sessions or Spindrel Project sessions.
updated: 2026-05-03
---

# Spindrel Development Workflow

This file is the repo-owned workflow contract for agents working on Spindrel.
It is intentionally source-controlled so local CLI agents, Spindrel
Project-bound chat sessions, scheduled Project runs, and looped Project runs
share the same artifact boundaries.

`AGENTS.md` remains the session-start index and repo rule book. This file is
the Spindrel-owned Project contract for this repo: artifact homes, run policy,
intake rules, hooks, and dependency expectations. Runtime `skills/project/*`
are fallback recipes; this file wins for repo-specific workflow.

## Start Here

1. Read `AGENTS.md` or `CLAUDE.md`.
2. Read `docs/roadmap.md` for active work.
3. Read the relevant `docs/guides/<area>.md` before changing a subsystem.
4. For multi-session work, read the owning `docs/tracks/<slug>.md`.
5. For Project coding runs, also follow the runtime `project/*` skills and
   the run's injected readiness/environment data.

## Policy

- Work from repo-local source state. Do not require private vault notes for
  startup, planning, execution, or handoff.
- Read `AGENTS.md`, this file, `docs/roadmap.md`, and the relevant guide or
  track before changing a subsystem.
- Keep roadmap rows short. Durable detail belongs in tracks, plans, audits,
  receipts, or run artifacts.
- Use deterministic repo checks when a rule needs enforcement. Do not rely on
  private operator memory for portable agent behavior.
- Spindrel reads this file but does not silently rewrite it. The only automatic
  write path is the explicit starter creation for Projects that do not already
  have a `.spindrel/WORKFLOW.md`.

## Work Discovery

`docs/roadmap.md` is the canonical work index. An agent or operator should be
able to answer "what's next?" without scanning every track and plan file. The
roadmap carries four lean sections:

- **`## Up Next`** — 5–8 ready-to-launch items (decision-complete plans or
  queued track phases that someone could pick up today). One line per item,
  link to the owning plan or track. Add an item when it becomes pickable;
  remove it when the work starts (it moves into `## Active`) or stalls.
- **`## Plans`** — one-line entry per `docs/plans/<slug>.md` with
  `status: active` or `status: planned`, pointing at the file. Surfaces
  decision-complete work that isn't yet a track.
- **`## Active`** — in-flight tracks, one line each, link to the track.
  Implementation detail belongs in the track, not in the row.
- **`## Recently Completed`** plus `docs/completed-tracks.md` and
  `docs/fix-log.md` — last few shipped items so the index also answers
  "what just landed?".

If a row needs a paragraph, the paragraph belongs in the linked artifact, not
in the roadmap. When a row drifts into shipped milestones + queued phases +
historical detail, fold the detail back into its track and trim the row.

### Plan and track lifecycle

- Plans live at `docs/plans/<slug>.md` while `status: active` or `planned`.
  When a plan finishes (`status: executed`), move the file to
  `docs/plans/completed/<slug>.md` in the same edit. Do not delete — completed
  plans stay as decision history.
- Tracks stay in `docs/tracks/` for their full lifetime. A track marked
  `status: complete` is read-only history; if work resumes in that domain,
  flip the status back to `active` and add a new phase rather than spawning a
  sibling track. `docs/guides/tracks.md` is the canonical contract.

### Verification Queue

`docs/verify.md` is the canonical queue for shipped behavior that needs live or
e2e proof beyond automated tests. Unit/integration tests prove code correctness;
the verification queue tracks feature correctness against real users and real
infrastructure.

- **When to add a row.** When a plan moves to `docs/plans/completed/` or a
  track flips to `status: complete` AND its acceptance criteria call for live
  or manual proof, add a row to `docs/verify.md` in the same edit. If the
  plan's "Acceptance Criteria" section explicitly says "automated tests are
  sufficient," no row needed.
- **Row shape.** `## <slug> — shipped YYYY-MM-DD`, then bullets for
  `What to verify`, `Method`, `Source`, `Status`. See the file's "How to use"
  section for the full schema and recommended methods.
- **Lifecycle.** `queued` → `in-progress` → `verified YYYY-MM-DD` (with a
  one-line note on what passed) OR `failed YYYY-MM-DD → inbox#…`. Failed
  entries leave the queue as soon as a corresponding `docs/inbox.md` row is
  filed.
- **Pruning.** Verified entries are deleted 30 days after they pass, or moved
  to `docs/audits/verification-archive.md` if a paper trail is wanted. The
  queue should stay short; if it grows past ~10 entries, prune before adding
  more.

## Artifacts

Use the smallest durable artifact that fits the work:

| Need | Home | Rule |
|---|---|---|
| Rough bug, idea, tech debt, or question | `docs/inbox.md` | Capture lightly; promote or delete during triage. |
| Multi-session effort / epic current state | `docs/tracks/<slug>.md` | Current state, phase/status, invariants, links. Not a session log. |
| Concrete design or implementation plan | `docs/plans/<slug>.md` | Use when a task needs a decision-complete plan before implementation. |
| Investigation, audit, parity ledger, evidence history | `docs/audits/<slug>.md` | Preserve findings and historical proof outside the active track. |
| Resolved bug one-liner | `docs/fix-log.md` | Add in the same edit that removes the inbox item. |
| Product behavior guide | `docs/guides/<area>.md` | Canonical contract for subsystem behavior. Guides win when docs disagree. |
| Project-run prompt scope | Run prompt, `docs/plans/`, `.spindrel/prds/`, or `.spindrel/audits/` | Use a Run Brief for track/doc-driven work; no separate file is required unless the brief must be reused. |
| Project-run plan or receipt generated by Spindrel | `.spindrel/runs/` or `.spindrel/audits/` | Run-scoped source artifacts and receipts; link from tracks or plans when durable. |
| Project-local run continuity | `.spindrel/runs/`, `.spindrel/audits/`, and Project receipts | Portable run evidence and handoff state. Keep private operator notes out of agent startup. |

## Tracks

Tracks live in `docs/tracks/`. A track is the current canonical state for a
multi-session effort, similar to an epic brief plus status page. It is not the
place to paste every session transcript, command log, or dated implementation
diary.

A good track contains:

- north star and scope;
- current state;
- phase/status table;
- key invariants and decisions;
- active gaps or next work;
- links to plans, audits, parity tables, receipts, PRs, and architecture
  decisions.

When a track accumulates long dated history, move that history into
`docs/audits/` or a focused plan and leave a short link. Follow
`docs/guides/tracks.md` for lifecycle and split rules.

## Intake, Run Briefs, And Run Packs

Rough captures start in `docs/inbox.md`. Promotion paths:

- Small fix: implement, remove the inbox item, add a `docs/fix-log.md` line.
- Multi-session work: promote to a `docs/tracks/<slug>.md` track.
- Launchable Project work: write or update a source artifact in
  `docs/plans/`, `.spindrel/prds/`, or `.spindrel/audits/`, then launch a
  Project coding run from that artifact.

Do not leave the same active item as a full entry in multiple places. Keep a
one-line pointer when history matters.

### Inbox Git Cadence

For this Spindrel repo, the workflow branch for inbox-only work is
`development`.

When the user asks an agent to check, triage, or add issues in `docs/inbox.md`:

1. Inspect Git state first: current branch, `git status --short`, and
   `git fetch origin development`.
2. Before writing to `docs/inbox.md`, make sure local `development` includes
   `origin/development`. Use a fast-forward update only. If the branch cannot
   be made current without touching unrelated dirty work, stop and report that
   blocker instead of editing a stale inbox.
3. If the request only reads or summarizes the inbox, do not commit.
4. If the request adds, deletes, promotes, or otherwise edits inbox entries,
   commit the inbox change immediately on `development` unless the user
   explicitly says not to commit.
5. The inbox commit must stage only the intended inbox/fix-log artifacts:
   usually `docs/inbox.md`; for an inline fixed item, `docs/inbox.md` plus
   `docs/fix-log.md`. Never include unrelated dirty files in an inbox commit.
6. If unrelated files are dirty, leave them dirty. Use path-limited staging and
   commit commands such as `git add docs/inbox.md` and
   `git commit -- docs/inbox.md` after verifying the staged diff.

A Run Brief is the minimum contract for a track/doc-driven Project run,
especially an overnight or loop-enabled run. It may live directly in the run
prompt. Use this shape:

- **Source document:** the track, plan, audit, inbox item, or PRD path.
- **Mission:** the one bounded outcome for this run.
- **Stop when:** the concrete condition that makes this run complete.
- **Stay inside:** files, subsystem, issue class, or phase boundaries.
- **Evidence:** required tests, screenshots, PR, receipt, or audit output.
- **Update:** the artifact and section to update before handoff.
- **Review handoff:** what the human should inspect next.

If a source document has endless possible follow-up, the Run Brief is the
scope limiter. Continue a loop only when the same mission still has concrete
remaining work. Mark the run `done` when the stop condition is met,
`needs_review` when the next useful work changes scope, and `blocked` when
access or dependencies are unavailable.

Loop continuations get a new task/session. In `isolated_worktree` mode that
also means a newly prepared session worktree and private Docker daemon; in
`shared_repo` mode the continuation stays on the shared Project root. The
handoff does not reset: reuse the same logical work branch, PR/handoff,
Project source context, dependency contract, and receipt lineage. The next
iteration should prepare or fast-forward the existing handoff branch and add
one focused commit. If the branch/PR cannot be reused, stop with
`needs_review` or `blocked` instead of opening a replacement PR.

Run Packs are optional published batches of Run Briefs. Use them when the user
needs to review or launch multiple PR-sized slices together. Do not require a
Run Pack file for a single flexible run from a track or plan.

## Conversational Planning

When a user starts dumping ideas in a Project-bound channel, keep the
conversation lightweight until the shape is clear. Do not immediately create a
track or launch a coding run.

Use this routing:

- rough bug, idea, tech debt, or question -> capture in `docs/inbox.md` or the
  Project's configured intake home;
- coherent feature or design discussion -> draft or update a plan in
  `docs/plans/` or `.spindrel/prds/`;
- broad investigation, parity check, security/performance sweep, or evidence
  ledger -> write an audit in `docs/audits/` or `.spindrel/audits/`;
- multi-session product/architecture effort with durable status -> update the
  owning `docs/tracks/<slug>.md`;
- implementation-ready slice -> frame a Run Brief and launch or schedule a
  Project coding run only after the user asks to launch.

If an existing track owns the area, update that track's current state, status
table, active gaps, or links instead of creating a sibling track. Ask one
clarifying question when the right artifact home is ambiguous.

## Runs

Formal Project coding runs should behave like normal Claude/Codex sessions
with orchestration around them:

- use the assigned work surface/cwd and branch;
- use the session execution environment and private Docker daemon when
  provided;
- run repo-local commands from source;
- restate the Run Brief before editing when the run is track/doc-driven or
  loop-enabled;
- publish receipts with changed files, tests, screenshots, dev targets,
  blockers, branch/PR, linked source artifact, and the artifact section
  updated before handoff.

Receipts, run logs, and captured Git summaries are evidence. They should link
back to the plan, track, or audit that owns the durable state instead of
expanding the track.

## Hooks

There is no required automatic hook runner for this repo. If a run prompt or
operator asks for a named phase hook, execute the documented repo-local command
with normal shell tools and record the result in the receipt. Add a typed hook
tool only after a concrete run needs repeatable hook execution.

## Dependencies

- Unit tests run from the native repo environment; do not wrap unit tests in
  Docker.
- Project coding runs use their assigned work surface, execution environment,
  private Docker daemon, and dev target ports when provided.
- Spindrel-managed dependency stacks are for backing services. App/dev servers
  are started by the agent from source on assigned or unused ports.
- Project run environment profiles own any pre-agent setup that must exist
  before the model starts: repo setup commands, declared bootstrap helpers,
  env artifacts, app/dev server preparation, and readiness checks. Agent turns
  consume the prepared surface and should not improvise host/bootstrap setup.

### Run Environment Profiles

Profile definitions live in `.spindrel/profiles/<id>.yaml` (or `.yml` /
`.toml`) inside the Project repo, with the applied Blueprint snapshot's
`run_environment_profiles[<id>]` as the fallback when no trusted repo file is
declared. Project metadata may select a default profile with
`default_run_environment_profile`, but V1 does not allow Project metadata to
define executable profile bodies.

Repo-file profile execution is opt-in per Project through
`trust_repo_environment_profiles`. When enabled, the run loads the profile from
the resolved run work surface and requires the file bytes to match the
operator-approved hash recorded in Project metadata before any command runs.
Unapproved profile changes block before the model starts and emit a
`run_environment_preflight` receipt/message. Admins approve reviewed hashes via
the Project run-environment profile approval API.

In `shared_repo` mode, profiles are for non-mutating env/readiness/artifact
checks unless their `work_surface_modes` explicitly includes `shared_repo`.
Isolated worktree runs are the normal home for setup commands and background
processes.

Profile YAML must not contain literal secret values. Put secrets in Project
secret bindings and let profile commands read them from OS env.

Use `validate_project_run_environment_profile` (or the matching admin API) to
check profile source, trust/approval state, schema, and work-surface
compatibility before scheduling unattended work. Schedule create/update rejects
profile selections that the validator knows would block.
If two consecutive scheduled runs hit the same preflight blocker identity, the
schedule stops with `status=needs_review` and records a
`run_environment_loop_stop` receipt linking the two failed runs.

## Runtime Skills Boundary

`skills/` is product behavior for all Spindrel users and their Projects.
Repo-specific Spindrel development workflow belongs here, in `AGENTS.md`, in
`docs/`, or in `.agents/skills/`. Do not copy Spindrel source-development
commands, local paths, or private operator workflow into runtime skills unless
normal Spindrel users should receive that behavior for their own repositories.

## Completion Checklist

Before ending a non-trivial implementation pass:

- update the owning guide, track, plan, audit, inbox, or fix-log entry;
- keep roadmap rows short and link to the owning artifact;
- report tests, screenshots, branch/PR, live run/receipt status, and blockers;
- avoid moving or rewriting unrelated dirty worktree changes.
