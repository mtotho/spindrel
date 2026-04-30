# Projects

![Project list with shared roots and Blueprint management](../images/project-workspace-list.png)

Projects are named roots inside the shared workspace. Multiple channels can
attach to the same Project so files, terminal cwd, search, harness turns, and
Project instructions resolve from one place while bot-private memory remains
separate through the `memory` tool.

## Project Roots

![Project file browser rooted at the shared Project](../images/project-workspace-detail.png)

Open `/admin/projects` to create or inspect shared roots. A Project owns:

- a workspace-relative root path such as `common/projects/spindrel`;
- optional Project instructions and prompt-file path;
- Project-scoped knowledge under `.spindrel/knowledge-base`;
- channel membership for every channel that should use that root.

The Project detail page is the work surface: use **Files** for the rooted file
browser, **Terminal** for a Project-root shell, **Setup** for Blueprint runtime
preparation, **Instances** for fresh workspaces created from the applied
snapshot, **Settings** for instructions and Blueprint metadata, and **Channels**
for membership.

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
bound to a fresh instance through the session Project-instance API.

## Channels And Memory

![Project-bound channel settings](../images/project-workspace-channel-settings.png)

Project-bound channels use the Project root for workspace tools and harness
cwd. Bot memory is still owned by the memory system, not the Project root.

![Memory tool transcript in a Project-bound channel](../images/project-workspace-memory-tool.png)
