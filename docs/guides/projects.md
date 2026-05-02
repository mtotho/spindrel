# Projects

![Project list with shared roots and Blueprint management](../images/project-workspace-list.png)

Projects are named roots inside the shared workspace. Multiple channels can
attach to the same Project so files, terminal cwd, search, harness turns, and
Project instructions resolve from one place while bot-private memory remains
separate through the `memory` tool.

The Project binding is the normal primitive. Channel settings no longer expose
the old path-only configuration; attach a channel to a Project so all
WorkSurface consumers resolve the same root.

## Project Roots

![Project file browser rooted at the shared Project](../images/project-workspace-detail.png)

Open `/admin/projects` to create or inspect shared roots. A Project owns:

- a workspace-relative root path such as `common/projects/spindrel`;
- optional Project instructions and a Project Runbook path such as
  `.spindrel/project-runbook.md`;
- Project-scoped knowledge under `.spindrel/knowledge-base`;
- channel membership for every channel that should use that root.

The Project detail page is the work surface: use **Files** for the rooted file
browser, **Terminal** for a Project-root shell, **Setup** for Blueprint runtime
preparation, **Runs** for agent coding-run launch and receipts, **Instances**
for fresh workspaces created from the applied snapshot, **Settings** for
instructions and Blueprint metadata, and **Channels** for membership.
The Settings tab includes a compact Basics block for the root URI, attached
channel count, setup readiness, Project Runbook, and runtime environment
readiness.

## Project Runbook

The Project Runbook is Spindrel's repo-owned policy file for agent work. The
recommended path is `.spindrel/project-runbook.md`. It plays the same role that
Symphony's `WORKFLOW.md` plays in that service: the repository owns the
instructions that tell agents how to work safely and how to prove completion.

Use the runbook for branch/base-branch expectations, repo-local test commands,
dependency stack usage, dev-target/server instructions, screenshot/e2e evidence
requirements, PR or external-tracker handoff rules, and what a review-ready
receipt should include. Inline Project instructions are still allowed, but the
runbook is the clearer long-term home for policy that should version with the
Project.

From any Project-bound channel, run `/project-init` to get a copyable prompt
for the current agent. That prompt points the agent at the generic
`workspace/project_init` skill and asks it to inspect the repository, create or
repair the applied Blueprint, sanitize repo declarations, enroll the needed
Project workflow skills, configure a Dependency Stack from a Project-local
compose file when the repo needs backing services, and report readiness.

For planning, users should not need to remember a command name. Mention or load
the Project lifecycle skill (`@skill:workspace/project_lifecycle` or
`get_skill("workspace/project_lifecycle")`) when a conversation is becoming a
feature track, PRD, story list, issue-intake sweep, coding run, review, or
follow-up. The `workspace/` prefix is only the runtime skill namespace; the
user-facing concept is Project lifecycle, Project PRD, and Project stories.

## Blueprints

![Project Blueprint library](../images/project-workspace-blueprints.png)

Project Blueprints are reusable recipes for creating Projects. A Blueprint can
declare a default root pattern, Project instructions, Project Runbook path,
starter folders/files, knowledge files, repo declarations, setup commands, a
Dependency Stack spec, env defaults, and required secret binding slots.

![Project Blueprint editor with starter files and declarations](../images/project-workspace-blueprint-editor.png)

Blueprint materializes files and records declarations. Project Setup turns the
applied snapshot into a manual setup plan: it validates repo targets and
Project-relative command cwd values, checks Project-scoped secret slots, clones
missing repos, skips existing repo paths, runs ordered shell setup commands, and
records redacted run history. Secret values stay in the secret vault; Projects
only store bindings to those vault entries.

Blueprints are durable recipes, not per-run copies. A direct Project can create
a Blueprint from its current state; Spindrel records detected child git repos
plus existing Project metadata such as dependency stacks, dev targets, env
defaults, and secret slots, then applies that snapshot back to the Project.
Fresh instances and formal runs use the applied snapshot. The disposable
instance is what changes per run.

![Direct Project setup with Blueprint creation CTA](../images/project-workspace-setup-blueprint-cta.png)

## Applied Blueprints

![Applied Blueprint section on Project settings](../images/project-workspace-settings-blueprint.png)

When a Project is created from a Blueprint, the Project stores an applied
snapshot. Editing or deleting the Blueprint later does not rewrite existing
Projects. Use the Project settings Blueprint section to inspect the snapshot,
repo/env declarations, materialization result, and required secret bindings.

Commits do not require Blueprint edits. Fresh instances clone the declared
branch when created, and Project coding agents still inspect git state and
update from the configured base branch when safe. Update the Blueprint only
when the recipe changes: repo URL/path/branch, setup commands, dependency
stack, env slots, secret bindings, dev targets, or starter files.

The Project runtime environment is derived from the applied snapshot, not from
later Blueprint edits. Env defaults and bound Project secrets are injected into
Project terminals, `exec_command`, and harness-backed Project turns. Settings
show key names and missing bindings only; secret values are not returned by the
Project API or rendered in the UI. Missing required secrets warn in readiness
surfaces but do not block general Project runtimes.

## Fresh Instances

Project Instances are temporary roots created from a Project's frozen Blueprint
snapshot. They live under `common/project-instances/{project-slug}/{id}` and
reuse the parent Project policy: prompt, runtime env, secret bindings,
knowledge-prefix locality, and harness cwd all resolve through the same
work-surface service.

Tasks can opt into a fresh Project instance for each run. The task worker
creates and prepares the instance before invoking the agent, stores the
`project_instance_id` on the task, and sets a run-scoped context override so
file, exec, search, terminal, and harness tools resolve to the instance root
without mutating the shared channel session. Sessions can also be explicitly
bound to a fresh instance through the session Project-instance API. Project
session composers expose that binding as quiet work-surface text near the
composer controls, not as channel header chrome; creating or clearing a fresh
copy affects future turns only.

Ad hoc Project sessions stay on the shared Project root by default. Use an
isolated Project session when two ad hoc sessions may edit, test, or restart
the same repo in parallel. Formal coding runs already isolate files, branch,
Dependency Stack, and dev target ports by default.

Task-owned instances expire by policy but are not deleted while the owning task
is still pending or running. The Project Instances tab exposes cleanup
readiness, task status, expiry, and blockers; run cleanup destroys the
task-scoped Dependency Stack before deleting the fresh Project root and records
an `instance.cleanup` receipt. The background cleanup worker sweeps expired
task-owned instances after their runs leave the active states. Manual instances
and session-owned instances stay explicit operator/session actions.

Agents and review surfaces should use the work-surface payload instead of
guessing from cwd. `list_agent_capabilities().project.work_surface` reports the
current channel/session/task root, and Project run rows expose the run's
expected and actual root. Formal coding and review tasks should become
`project_instance` / `isolated` before the first agent turn; if instance setup
fails, the task should block visibly rather than falling back to the shared
Project root.

## Agent Coding Runs

![Project coding run launcher and receipts](../images/project-workspace-runs.png)

Project coding runs are launched through `/api/v1/projects/{id}/coding-runs`.
The service validates that the selected channel belongs to the Project, creates
a normal background task from the `project_coding_run` preset, and records a
secret-safe handoff config in `execution_config.project_coding_run`: request,
repo, base branch, generated work branch, runtime target key names, new-session
policy, fresh-instance policy, work-surface readiness, optional bounded loop
policy, and any task-scoped machine target grant. The prompt tells the agent to
update from the base branch, switch to the generated branch, use Project
runtime env, use the granted e2e/machine target only when attached to the task,
run e2e checks when relevant, and publish `publish_project_run_receipt`
evidence.

Bounded loops are an optional launch policy for exploratory or repeated repair
work. They deliberately reuse the existing continuation primitive instead of a
hidden orchestrator: every iteration is a normal Project coding run on the same
lineage, branch, PR/handoff, Project instance, dependency stack, and receipt
trail. The implementation agent controls the loop with receipt fields:
`loop_decision=continue` starts the next continuation while budget remains,
`done` stops as review-ready, `needs_review` stops for human decision, and
`blocked` stops with the recorded blocker. Missing receipts or missing loop
decisions stop the loop and surface as needs-review state.

Spindrel records coordination state, not the canonical external issue tracker.
Issue Intake captures rough notes, Work Packs turn those notes into launchable
task packets, Project coding runs track execution/review, and receipts preserve
evidence. When GitHub, Linear, or another tracker is linked, that external
system remains the durable source of truth for issues, PRs, comments, and
long-term project planning; Spindrel should link to it and coordinate around it
rather than duplicating it.

Project coding agents that use Codex or Claude Code are harness agents: native
tools own file edits and repo-local commands inside the Project root, including
unit tests. Do not wrap unit tests in Docker, Dockerfile.test, or docker
compose. E2e-testing, screenshots, server/machine actions, and Docker/compose
dependency control must go through task-scoped Spindrel grants. See
[Agent E2E Development](agent-e2e-development.md) for the full boundary.

## Dev Targets

Projects can declare source-run dev targets in Project metadata or Blueprint
snapshot metadata under `dev_targets`. Each target can name a `key`, `label`,
`port_env`, `url_env`, and `port_range`. Project coding runs allocate concrete
ports from those ranges, inject the resulting `SPINDREL_DEV_*_PORT` and
`SPINDREL_DEV_*_URL` values into the task runtime environment, and show the
assigned URLs in Project Runs. Agents start the app/dev server processes
themselves; Spindrel only assigns non-colliding targets and records evidence.

## Dependency Stacks

Project Dependency Stacks are Docker-backed database/service stacks declared by
a Project's applied Blueprint snapshot. They are not raw Docker access. The
Project declares a compose source such as `docker-compose.project.yml`, exported
connection env, and named commands. Spindrel reads the compose file from the
Project work surface, validates Docker red lines, applies it through the
managed Docker stack service, and returns dependency env, service status, logs,
health, and command results.

Coding runs use run-scoped stack instances by default. The reusable spec belongs
to the Project, but the actual Docker Compose project, network, volumes, logs,
and lifecycle belong to the task/fresh Project Instance. Parallel coding runs
therefore do not restart or mutate the same database/service stack. Agents run
their own app/dev server processes from source on assigned or unused ports. A
manual shared Project dependency stack is available from the Project Setup
surface for interactive development.

When a Project coding run starts and the Project has a dependency stack,
Spindrel preflights the task-scoped stack before the first harness turn. The run
prompt and Runs API expose only secret-safe readiness fields: status, source,
declared commands, and env key names. The actual connection values are injected
into Project terminals, exec, and harness turns through the Project runtime env
so project-local commands can use values such as `DATABASE_URL` immediately.

Agents may adjust stack shape during a session by editing the Project compose
file and calling `manage_project_dependency_stack(action="reload")`. The compose
file diff is then reviewable in the same PR as the code change. Phase 1 keeps
the Docker red line at Spindrel: harness shells should not call raw `docker` or
`docker compose`, and dependency stack validation rejects Docker sockets,
privileged containers, host networking, dangerous host mounts, and mounts
outside the Project root or dependency scratch path. Dependency stacks are for
backing services, not for running unit tests.

![Project coding run execution access](../images/project-workspace-execution-access.png)

Execution access deliberately uses the same task machine-grant primitive as
normal scheduled tasks. The Project does not gain ambient machine power; the
operator grants one existing target to the run being launched, with explicit
inspect/exec capabilities and an optional LLM-tool toggle.

The Runs tab reads `/api/v1/projects/{id}/coding-runs` as the review cockpit. It
shows the launch form, recent API-launched runs, branch/base/repo state, recent
activity, task links, handoff links, and the latest receipt for each run. The
receipt records the implementation summary, changed files, tests, screenshots,
branch or review handoff, and task/session linkage so a later session can pick
up from durable Project state instead of searching chat history.

Supplemental smoke artifacts cover the coding-run cockpit and its channel-side
handoff: [Runs tab smoke](../images/project-coding-run-smoke-runs.png) and
[channel smoke](../images/project-coding-run-smoke-channel.png).

Reviewers can request changes from an existing coding run. The continuation
endpoint creates a linked follow-up task that keeps the same Project, channel,
repo, branch, and PR handoff while adding reviewer feedback, parent/root task
lineage, and prior evidence context to the new task prompt. Follow-up agents
should update the same branch/PR, rerun relevant tests or screenshots, and
publish a new Project run receipt.

The run detail page exposes the same recovery state used by agents: whether a
run can be continued, why recovery is blocked, and the latest follow-up task
when one already exists. Use that page for human review and
`get_project_coding_run_details` when an agent needs to answer "what happened
with the latest run?" in chat.
When recovery is open, the detail page can start the follow-up run directly and
then links to the created task. The follow-up uses the existing continuation
path, preserving Project, channel, repo, branch, PR handoff, parent/root
lineage, and prior evidence context.

Review sessions use the `workspace/project_coding_runs` runtime skill and should
call `get_project_coding_run_review_context` before finalizing selected runs.
That read-only manifest returns the selected run list, evidence counts, handoff
URLs, runtime/e2e/GitHub readiness, merge defaults, and finalization rules from
fresh server state. `finalize_project_coding_run_review` keeps accepted-only
reviewed semantics and returns structured error fields when a run was not
selected or a merge/finalization step is blocked.

Normal Project-bound agents can also turn a planning conversation into proposed
work packs before any coding run launches. `publish_issue_intake` captures a
single rough note for later triage; `create_issue_work_packs` creates one or
more proposed work packs from the current conversation and automatically creates
backing issue-intake source records when the agent does not provide existing
source item ids. `report_issue_work_packs` stays reserved for scheduled
issue-intake triage tasks.
Agent Capabilities recommends `workspace/project_lifecycle`,
`workspace/project_stories`, and `workspace/issue_intake` during Project-bound
planning sessions so ordinary Codex/Claude agents can use the LLM to turn a PRD,
plan, or rough issue list into proposed packs without a separate triage bot. The
work-pack launch prompt should carry enough verification expectations for a
later coding run: repo-local tests, screenshots when relevant, handoff/PR
intent, and receipt evidence.
Each grouping pass should also publish a triage receipt. Conversational
`create_issue_work_packs` calls and scheduled `report_issue_work_packs` calls
store `triage_receipt_id` / `triage_receipt` on the created packs and mirror the
receipt summary back to source item `evidence.issue_triage`. The receipt is
provenance, not approval: it explains why items were grouped, what is
launch-ready, what needs info, and what was excluded or classified as non-code
work.

Work Packs are reviewed before launch from the Issue Intake workspace. The
review cockpit lets an operator refine title, summary, category, confidence,
launch prompt, Project/channel target, and source items; dismiss the pack; mark
it needs-info; or reopen it. These are not separate approval states: the only
launchable status remains `proposed`. Every review mutation appends
`metadata.review_actions` and updates `latest_review_action`; launched packs are
immutable except for launch provenance.

Operators can launch several proposed Work Packs together from the same Issue
Intake workspace. Batch launch is intentionally all-or-nothing: every selected
pack must still be `proposed`, have a launch prompt, and target a channel that
belongs to the selected Project before any Project coding-run task is created.
Successful batches store the same `launch_batch_id` on each Work Pack and its
launch review action, so later review sessions can group the overnight runs
back to the human-approved launch set.

Project Runs exposes that launch batch on each coding run and shows grouped
batch context when two or more runs share the same id. Launching a batch review
agent starts the normal `project_coding_run_review` task with every run from the
launch batch selected; it is not a separate review system. When the review
agent accepts a run, finalization marks the run reviewed and appends a
`reviewed` action back to the source Work Pack metadata with the review
task/session ids, outcome, summary, merge method, and `launch_batch_id`.

Project Runs exposes a Needs your review queue above running work and run history
list. The queue is a derived read model, not a new state machine: each coding
run is classified into the operator queue states `ready_for_review`,
`changes_requested`, `missing_evidence`, `follow_up_running`,
`follow_up_created`, `reviewing`, `blocked`, or `reviewed`. Launch-batch
provenance stays visible below the queue so morning review can still select a
batch's runs, start the normal review session, or reopen the active review task
if one already exists.

The same derived state powers `/api/v1/projects/review-inbox`, which aggregates
attention across every Project. Home uses that endpoint as a compact Project
Factory pulse: it appears only when runs need operator attention and links
directly back to the relevant Project run or Runs page.

Raw conversational issue notes published by Project-bound agents are reviewed
before they become runs. Home's Project Factory pulse links to Mission Control
Issue Intake when raw notes or active Work Packs exist, and every Project
Overview has an Issue intake entry beside the run review queue. That entry opens
`/hub/attention?mode=issues`, where the operator can review raw notes, start an
issue-triage run, inspect triage receipts, edit/dismiss/needs-info Work Packs,
choose Project/channel launch targets, and launch one or several packs into
Project coding runs.

![Project review session launched from selected coding runs](../images/project-workspace-review-launched.png)

Launching a review session creates a normal task from the
`project_coding_run_review` preset and links it back to the selected runs. The
review task receives the selected task ids, Project/repo context, review prompt,
merge method default, and optional task-scoped machine grant in
`execution_config.project_coding_run_review`.

![Project review execution access](../images/project-workspace-review-execution-access.png)

![Project coding run after accepted review and merge](../images/project-workspace-review-finalized.png)

After the review agent accepts and merges a run, the run row shows the durable
provenance the human needs to audit: reviewed status, PR merged state, check
status, merge method, merge commit, review task link, handoff link, and the
evidence receipt that was reviewed.

Receipts are idempotent by task, handoff URL, git handoff metadata, or an
explicit `idempotency_key`. Retrying `publish_project_run_receipt` updates the
same review record instead of creating a stack of duplicate receipts. The
Project Factory verification loop is Project-defined: agents run repo-local
commands and tests from the Project work surface, use injected runtime and
Dependency Stack env, start app/dev servers on assigned dev target ports, and
attach screenshots plus command results to the receipt.
Each coding run exposes a secret-safe `readiness` manifest in the Runs API with
runtime blockers, dependency-stack status, assigned dev targets, handoff branch
details, machine-target grant summary, and required receipt-evidence fields.
Agents should inspect that manifest before starting work and reflect any blocker
or missing evidence in the final Project run receipt.
Ordinary Project runs must not bootstrap or restart the host Spindrel e2e/API
server; source-run app processes belong on the run's own assigned or unused
ports.

### Review-Agent Evidence

The current Project factory path is covered by source-controlled screenshot
artifacts, not ad hoc local captures:

| Artifact | What it proves |
|---|---|
| [Project work hub](../images/project-workspace-detail.png) | Project detail opens as an agent-work home with Factory Status, Project Runbook, runs, readiness, channels, work-surface entry points, and both coding-run review plus raw Issue Intake/work-pack review links. |
| [Home Action Inbox](../images/home.png) | Home separates actionable replies, Project reviews, issue intake, Mission Control findings, and health from raw Attention noise. |
| [Rail Inbox](../images/home-inbox.png) | The left rail Inbox groups review-ready work and unread replies without making raw Attention counts look urgent. |
| [Project Human Review Queue](../images/project-workspace-review-inbox.png) | Operator queue with ready, changes-requested, follow-up, missing-evidence, and blocked states plus source Work Pack launch-batch provenance. |
| [Project Run detail](../images/project-workspace-run-detail.png) | Canonical review page for one coding run, including problem statement, implementation/review agent visibility, receipt, review decision, changed files, tests, screenshots, dev targets, dependency stack, activity, and raw metadata. |
| [Project Run follow-up](../images/project-workspace-run-follow-up.png) | Recovery flow for a changes-requested run: suggested feedback, Start follow-up, and the created follow-up task link. |
| [Project Review Ledger](../images/project-workspace-review-ledger.png) | Review-session audit rows with selected runs, source Work Packs, outcome counts, merge settings, summaries, evidence, and active/finalized review links. |
| [Project Runs cockpit](../images/project-workspace-runs.png) | Human-first review queue, running agent visibility, explicit Ask agent to review actions, batch tools, branch/PR progress, continuation action, PR links, and receipt evidence. |
| [Coding-run execution access](../images/project-workspace-execution-access.png) | Launching a coding run can grant one existing e2e/machine target with explicit inspect/exec and agent-tool controls. |
| [Review session launched](../images/project-workspace-review-launched.png) | Launching an agent review on a selected run returns a review task and surfaces the task link in the cockpit. |
| [Review execution access](../images/project-workspace-review-execution-access.png) | Launching a review session can carry the same task-scoped e2e/machine grant for tests, screenshots, and merge verification. |
| [Review finalized and merged](../images/project-workspace-review-finalized.png) | Accepted review provenance after merge: reviewed status, merged PR, check status, merge method, merge commit, review task, and handoff. |
| [Project memory-tool transcript](../images/project-workspace-memory-tool.png) | Project-bound channels still render the memory tool result envelope with the expected `path` and completion message. |
| [Project context mentions](../images/project-workspace-context-mentions.png) | A Project-bound channel composer can fuzzy-select a Project-local file through the `@` picker and attach it as explicit harness context. |
| [Project channel header badge](../images/project-workspace-channel-header.png) | Project-bound channel headers expose a subtle Project badge that links back to the Project work hub. |
| [Project composer without Fresh copy action](../images/project-channel-composer-no-fresh-copy.png) | Project-bound channels keep the composer focused on message composition; fresh-instance lifecycle actions stay on Project run/instance surfaces. |
| [Project Factory dogfood planning](../images/project-factory-dogfood-planning.png) | A Project-bound planning chat uses explicit Project file/dependency context and records `create_issue_work_packs` output before launch. |
| [Project Factory dogfood live Work Packs](../images/project-factory-dogfood-live-work-packs.png) | The opt-in live Codex dogfood run shows the real planning session creating the dogfood code and needs-info Work Packs. |
| [Project Factory dogfood live receipt](../images/project-factory-dogfood-live-run-receipt.png) | The launched Project coding run publishes command results, dependency evidence, dev-target verification, changed files, and receipt status. |
| [Project Factory dogfood live review](../images/project-factory-dogfood-live-runs.png) | The Project Runs page shows the dogfood launch batch, finalized review session, reviewed coding run, evidence counts, and provenance links. |
| [Issue intake work-pack review](../images/spatial-check-issue-intake-work-packs.png) | Mission Control Issue Intake renders raw issue notes, Work Pack review controls, selected batch launch, source provenance, and Project/channel launch targets before coding-run launch. |
| [Project files](../images/project-workspace-files.png) | The shared Project-rooted file explorer remains available as a secondary tab. |
| [Project terminal](../images/project-workspace-terminal.png) | Project-rooted terminal cwd resolves through the Project work surface. |
| [Project channel settings](../images/project-workspace-channel-settings.png) | Non-harness channel settings bind to the Project primitive instead of a path-only workspace override. |
| [Project instances](../images/project-workspace-instances.png) | Fresh Project instance readiness and file handoff are visible from the Project work surface. |
| [Codex project terminal](../images/harness-codex-project-terminal.png) | A live Codex project-build e2e run on the main server created and verified files under the Project cwd. |
| [Codex mobile context](../images/harness-codex-mobile-context.png) | The same live Codex session exposes Project cwd, context, and bridge inventory in the mobile inspector. |
| [Codex plan-mode switcher](../images/harness-codex-plan-mode-switcher.png) | The live Codex session preserves the Spindrel plan/implement mode control while using Project cwd. |

`get_project_coding_run_review_context` is a runtime tool contract rather than a
visual surface. Its source-controlled evidence is the focused unit coverage for
selected-run manifests, readiness fields, and structured finalizer errors, plus
the Runs cockpit screenshot that shows the selected-review workflow that invokes
it.

## Channels And Memory

![Project-bound channel settings](../images/project-workspace-channel-settings.png)

Project-bound channels use the Project root for workspace tools and harness
cwd. Bot memory is still owned by the memory system, not the Project root.
If the Project binding or selected fresh instance cannot be resolved, file,
exec, context, indexing, and harness paths fail visibly instead of falling back
to a different workspace root.

Existing Project-bound harness chats keep normal CLI-like behavior. Spindrel
does not auto-load a broad Project-development skill for every ad hoc turn.
When a user wants to point the agent at repo-local instructions, the composer
`@` picker can attach Project files as `@file:<path>` mentions; the harness turn
receives the Project-relative path plus a bounded preview and should inspect the
file directly with normal tools before relying on details. Users can also
attach `@project:dependencies` to provide the current Dependency Stack summary
and remind the agent to use `get_project_dependency_stack` /
`manage_project_dependency_stack` for Docker-backed services.

![Project file context mention in the channel composer](../images/project-workspace-context-mentions.png)

![Project-bound composer without Fresh copy action](../images/project-channel-composer-no-fresh-copy.png)

![Project Factory dogfood planning chat](../images/project-factory-dogfood-planning.png)

![Project Factory dogfood live Work Packs](../images/project-factory-dogfood-live-work-packs.png)

![Project Factory dogfood live run receipt](../images/project-factory-dogfood-live-run-receipt.png)

![Project Factory dogfood live review provenance](../images/project-factory-dogfood-live-runs.png)

![Memory tool transcript in a Project-bound channel](../images/project-workspace-memory-tool.png)
