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
- optional Project instructions and prompt-file path;
- Project-scoped knowledge under `.spindrel/knowledge-base`;
- channel membership for every channel that should use that root.

The Project detail page is the work surface: use **Files** for the rooted file
browser, **Terminal** for a Project-root shell, **Setup** for Blueprint runtime
preparation, **Runs** for agent coding-run launch and receipts, **Instances**
for fresh workspaces created from the applied snapshot, **Settings** for
instructions and Blueprint metadata, and **Channels** for membership.
The Settings tab includes a compact Basics block for the root URI, attached
channel count, setup readiness, and runtime environment readiness.

## Blueprints

![Project Blueprint library](../images/project-workspace-blueprints.png)

Project Blueprints are reusable recipes for creating Projects. A Blueprint can
declare a default root pattern, Project prompt, starter folders/files, knowledge
files, repo declarations, setup commands, env defaults, and required secret
binding slots.

![Project Blueprint editor with starter files and declarations](../images/project-workspace-blueprint-editor.png)

Blueprint materializes files and records declarations. Project Setup turns the
applied snapshot into a manual setup plan: it validates repo targets and
Project-relative command cwd values, checks Project-scoped secret slots, clones
missing repos, skips existing repo paths, runs ordered shell setup commands, and
records redacted run history. Secret values stay in the secret vault; Projects
only store bindings to those vault entries.

## Applied Blueprints

![Applied Blueprint section on Project settings](../images/project-workspace-settings-blueprint.png)

When a Project is created from a Blueprint, the Project stores an applied
snapshot. Editing or deleting the Blueprint later does not rewrite existing
Projects. Use the Project settings Blueprint section to inspect the snapshot,
repo/env declarations, materialization result, and required secret bindings.

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

## Agent Coding Runs

![Project coding run launcher and receipts](../images/project-workspace-runs.png)

Project coding runs are launched through `/api/v1/projects/{id}/coding-runs`.
The service validates that the selected channel belongs to the Project, creates
a normal background task from the `project_coding_run` preset, and records a
secret-safe handoff config in `execution_config.project_coding_run`: request,
repo, base branch, generated work branch, runtime target key names, new-session
policy, and fresh-instance policy. The prompt tells the agent to update from the
base branch, switch to the generated branch, use Project runtime env, run e2e
checks when relevant, and publish `publish_project_run_receipt` evidence.

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

Review sessions use the `workspace/project_coding_runs` runtime skill and should
call `get_project_coding_run_review_context` before finalizing selected runs.
That read-only manifest returns the selected run list, evidence counts, handoff
URLs, runtime/e2e/GitHub readiness, merge defaults, and finalization rules from
fresh server state. `finalize_project_coding_run_review` keeps accepted-only
reviewed semantics and returns structured error fields when a run was not
selected or a merge/finalization step is blocked.

![Project review session launched from selected coding runs](../images/project-workspace-review-launched.png)

Launching a review session creates a normal task from the
`project_coding_run_review` preset and links it back to the selected runs. The
review task receives the selected task ids, Project/repo context, review prompt,
and merge method default in `execution_config.project_coding_run_review`.

![Project coding run after accepted review and merge](../images/project-workspace-review-finalized.png)

After the review agent accepts and merges a run, the run row shows the durable
provenance the human needs to audit: reviewed status, PR merged state, check
status, merge method, merge commit, review task link, handoff link, and the
evidence receipt that was reviewed.

Receipts are idempotent by task, handoff URL, git handoff metadata, or an
explicit `idempotency_key`. Retrying `publish_project_run_receipt` updates the
same review record instead of creating a stack of duplicate receipts. The
`run_e2e_tests` tool resolves the same `E2E_*` target used by the test harness,
so agents running on the main server can probe or execute tests against the
configured e2e-testing server before adding screenshot evidence.

### Review-Agent Evidence

The current Project factory path is covered by source-controlled screenshot
artifacts, not ad hoc local captures:

| Artifact | What it proves |
|---|---|
| [Project Runs cockpit](../images/project-workspace-runs.png) | Coding-run launch, selected-run review prompt, batch mark-reviewed/review-session controls, branch/PR progress, continuation action, handoff links, and receipt evidence. |
| [Review session launched](../images/project-workspace-review-launched.png) | Clicking Start review on a selected run returns a review task and surfaces the task link in the cockpit. |
| [Review finalized and merged](../images/project-workspace-review-finalized.png) | Accepted review provenance after merge: reviewed status, merged PR, check status, merge method, merge commit, review task, and handoff. |
| [Project memory-tool transcript](../images/project-workspace-memory-tool.png) | Project-bound channels still render the memory tool result envelope with the expected `path` and completion message. |
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

![Memory tool transcript in a Project-bound channel](../images/project-workspace-memory-tool.png)
