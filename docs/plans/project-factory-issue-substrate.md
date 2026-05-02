---
title: Plan - Project Factory Issue Substrate
summary: Replace the bespoke IssueWorkPack/Attention-based intake DB with a repo-resident, file-based substrate (or external tracker). Generic skill is convention-discovery; repo-local .agents/skill names the prescriptive bits. Cancels 4AY-b (RunPack rename) since the table goes away.
status: active
tags: [spindrel, plan, projects, project-factory, intake, runbook]
created: 2026-05-02
updated: 2026-05-02
---

# Plan - Project Factory Issue Substrate

## TL;DR

The Project Factory's bespoke intake stack (`IssueWorkPack` table + `WorkspaceAttentionItem(target_kind="issue_intake")` rows + Mission Control issue lane + `publish_issue_intake` write path) is disconnected from source/repo state, isn't visible without Spindrel running, and forces every user into Spindrel's coordination layer instead of meeting them where their work already lives. This plan replaces that substrate with **a file in the user's repo** (or their external tracker - GitHub/Linear/etc.), discovered per-Project via a one-time setup prompt. The generic Spindrel skill is opinion-free on file/folder convention; the user's own `.agents/skills/` carry the prescriptive bits. Cancels Phase 4AY-b (the planned `IssueWorkPack -> RunPack` rename) since the table is deleted instead of renamed.

## Context

- Today, every "issue" the user drops in chat goes through `publish_issue_intake -> WorkspaceAttentionItem -> IssueWorkPack -> ProjectCodingRun`. The first two stops are Spindrel-internal coordination state with no representation in any repo, no version control, no visibility outside the Spindrel UI.
- The user already maintains a working file-based equivalent in this repo: `docs/loose-ends.md` (inbox), `docs/tracks/<slug>.md` (units of work), `docs/fix-log.md` (resolution history). It works. It versions with source. Other agents (Codex without Spindrel) read it. CI sees it.
- The user's mental model: *generic Spindrel = "store somewhere portable"; repo-local skill = "store exactly here in this format."* Spindrel must not impose a recipe.
- The bowl-vs-repo problem: `Project.root_path` (e.g. `common/projects/spindrel/`) is Spindrel's shared workspace path - not necessarily a git repo on its own. Repos live *inside* it via `blueprint.repos[]`. Today there is no clean way for an agent to ask "of these repos, which one do durable docs live in?". This plan introduces a `canonical: true` flag.
- Out of scope (deferred): UI surfaces for the file (the existing widget system + a future file-viewer widget can serve any repo file when the user wants it pinned). Bulk migration of existing intake rows (the user has none worth keeping).

## Goals

- **Generic Spindrel skill is convention-discovery + read/write.** It asks the user where their issues live (repo file, repo folder, GitHub, Linear, other), persists the choice as Project settings, and reads/writes accordingly. It offers Spindrel's own pattern *only* as a suggestion when the user has no convention.
- **Repo-local `.agents/skills/<repo>-issues/SKILL.md`** is the authority for everything prescriptive: file path, schema, branch, commit cadence, GitHub-issue rules. The generic skill always defers when one exists.
- **`Project.canonical_repo_relative_path`** is resolvable. Agents writing durable artifacts (intake file, PRDs, run-pack/track files) target the canonical repo, never the bowl.
- **No DB row is the canonical home for an issue or a run pack** ever again. Coding runs still get DB rows because they have execution state; the *unit of work* they consume is a file pointer.
- The bespoke tables go away cleanly: `IssueWorkPack` deleted, `WorkspaceAttentionItem(target_kind="issue_intake")` rows deleted, `publish_issue_intake` rewritten as file-write, Mission Control lane removed.

## Non-Goals

- A new opinionated unit-of-work format. Tracks (`docs/tracks/<slug>.md`) already work for repos that adopt them; repos that prefer a single `docs/runpacks.md` should be free to. The generic skill stays out of this.
- A file-viewer widget. The widget system can do this later; it doesn't block this plan.
- External-tracker write integration (creating GitHub issues, Linear tickets). Read-side ingestion is a separate later concern; the user said they will add it when they need it.
- Replacing `WorkspaceAttentionItem` for non-issue uses. Bot/system error surfaces (heartbeats, log alerts) keep the table; only the `target_kind="issue_intake"` rows go.

## The Repo-Resident Substrate (this repo as the reference)

Used as the recommended pattern only - other repos are free to pick their own. Documented separately in `.agents/skills/spindrel-issues/SKILL.md`.

### `docs/inbox.md` - rough captures

Replaces the old `docs/loose-ends.md`. Fresh start - no migration of prior content (per user direction).

```markdown
## 2026-05-02 14:32 chat-scroll-jitter
**kind:** bug · **area:** ui/chat · **status:** open
Scroll jumps when new messages arrive while user is mid-scroll. Repro: ...

## 2026-05-02 15:10 widget-iframe-defer
**kind:** tech-debt · **area:** ui/widgets · **status:** → tracks/widget-defer
Offscreen iframes mounted at page load; promoted to a track.
```

- Heading: `## <ISO-date> <HH:MM> <kebab-slug>` - natural ordering, scannable, unique-ish.
- Tag line: `**kind:** bug | idea | tech-debt | question · **area:** <module/path> · **status:** open | → tracks/<slug> | stale`
- Body: 1-10 lines, free-form.
- Promoted to a Track -> status flips to `→ tracks/<slug>`; one-line stub stays in inbox as a pointer.
- Dismissed -> deleted outright.
- Fixed inline -> deleted from inbox; one-liner appended to `docs/fix-log.md`.
- Stale (no touch in N days; default 30) -> agent flips status to `stale` next triage and prompts the user.

### `docs/tracks/<slug>.md` - units of work

Unchanged. Already specified by `docs/guides/tracks.md`. A "Run Pack" in the new world *is* a Track (or, for repos without the tracks pattern, a section in a single `docs/runpacks.md`).

### `docs/fix-log.md` - resolution history

Unchanged. Existing pattern. Append-only one-liners.

## Phases

### Phase 4BD.0 - Canonical repo flag *(foundational; everything else depends)*

- New schema: `blueprint.repos[].canonical: bool` (defaults to false). Validation: at most one entry per blueprint may be flagged. Resolution rule: explicit canonical wins; otherwise the first repo entry.
- New computed property `Project.canonical_repo_relative_path` reading from the applied snapshot.
- New helper `project_canonical_repo_host_path(project)` returning the absolute on-disk path or None.
- `get_project_factory_state` payload gains `canonical_repo` (relative + host path) so any agent can ask "where do I commit?" without rederiving.
- Blueprint editor UI gets a "Canonical" checkbox per repo row; only one can be checked.
- Unit tests cover validation, resolution fallback, and the computed property.

### Phase 4BD.1 - Project intake convention settings

- New columns on `Project`:
  - `intake_kind`: `"unset" | "repo_file" | "repo_folder" | "external_tracker"` (server default `"unset"`)
  - `intake_target`: `Text` nullable. Relative path (for `repo_file`/`repo_folder`) or URL (for `external_tracker`).
  - `intake_metadata`: `JSONB` nullable. Free-form per-kind config (e.g. external tracker name, format hint).
- Migration adds the columns nullable. No backfill (no usable existing data).
- Pydantic schemas + API exposure.
- Factory-state inclusion: `get_project_factory_state` returns the resolved intake config so agents read it once.

### Phase 4BD.2 - Setup-time convention prompt

- Extend `project/setup/init` skill: after blueprint application, if `intake_kind == "unset"`, the agent asks the user where issues should live. Choices:
  - "A file in this repo" -> ask for path; if user has no preference, suggest `docs/inbox.md` (or whatever the repo-local skill recommends if one exists).
  - "A folder in this repo" -> ask for path; suggest `docs/inbox/` if no preference.
  - "GitHub issues" / "Linear" / "Notion" / "Other" -> ask for the canonical link/identifier; record in `intake_metadata`.
  - "Skip / decide later" -> leaves `intake_kind = "unset"`; intake skill warns next time it is invoked.
- Persists the choice via a new `update_project_intake_config` tool. Idempotent: re-running setup re-uses the stored choice unless the user explicitly says "reconfigure intake."
- Strict invariant: the setup skill **never** writes the file or creates the tracker on the user's behalf - it just records the convention. Subsequent `project/intake` invocations are what actually write.

### Phase 4BD.3 - Generic intake skill rewrite

- `project/intake` reads `intake_kind`/`intake_target` from factory-state, then:
  - `repo_file`: reads/writes the file at `<canonical_repo>/<intake_target>`. No DB write.
  - `repo_folder`: writes a new file per item under `<canonical_repo>/<intake_target>/<timestamp>-<slug>.md`. Reads by listing the folder.
  - `external_tracker`: emits the captured note as a hand-off message ("Open <intake_target>, paste this:") - does not call any external API.
  - `unset`: warns the user, points at `project/setup/init`, captures the note in chat as a fallback so it isn't lost.
- Defers entirely to repo-local `.agents/skills/<repo>-issues/SKILL.md` when one exists - the repo-local skill names the schema, the commit cadence, anything else.
- `publish_issue_intake` tool is rewritten to call the new write path (file or hand-off). Old DB write path deleted.

### Phase 4BD.4 - Run Pack stops being a table row

- `project/plan/run_packs` rewrites: triage produces or updates an artifact in the same convention the user picked. For `repo_file`/`repo_folder` repos, the artifact is whatever the repo-local skill says (Track files for spindrel; sections in a single file for repos that prefer that). Generic skill stays opinion-free on the unit shape.
- `create_issue_work_packs` tool renamed to `propose_run_packs` and rewritten to *write to the artifact path the repo-local skill nominates* rather than creating DB rows. Returns the file path + section heading as provenance.
- Triage receipt becomes a section in the same artifact, not a separate DB record.

### Phase 4BD.5 - Launch reads from the file

- Coding-run launch path takes `source_artifact: {path, section?}` instead of `source_work_pack_id`.
- `ProjectCodingRun` gains a `source_artifact` JSON column (path + section + commit SHA at launch time, for reproducibility).
- Run rows in the UI link to the source artifact in the repo (deep-link to `<canonical_repo>/<path>#<section>`).

### Phase 4BD.6 - Drop the bespoke tables

- Migration drops `issue_work_packs` table.
- `WorkspaceAttentionItem` rows where `target_kind = "issue_intake"` get deleted (one-shot data migration).
- Mission Control issue lane deleted from UI.
- Phase 4AY-b in the cohesion plan is **cancelled** - the table is gone, there is nothing to rename.
- `IssueWorkPack` Python class + all related serialization deleted.

### Phase 4BD.7 - Repo-local skill for this repo

- New `.agents/skills/spindrel-issues/SKILL.md` that:
  - Names `docs/inbox.md` as the inbox file.
  - Names `docs/tracks/<slug>.md` as the unit-of-work file (one Track per launchable unit).
  - Specifies the lightweight schema (the `## <date> <time> <slug>` + tag line + body shape above).
  - Says "auto-commit just this file to the active branch on every change" and points at the existing vault-auto-push hook (or its equivalent) for the commit mechanism. Spindrel itself has a manual-commit policy (per `feedback_git_workflow.md`); the inbox file is the one exception, gated by the user's hook.
  - Confirms "no GitHub issues for now; agent + MD schema is enough."
  - Says how to query inbox: `grep '^\*\*kind:\*\* bug' docs/inbox.md` etc.
- Becomes the reference template for users wanting to set up the same pattern in their own repos.

## Order and dependencies

| Phase | Depends on | Notes |
|---|---|---|
| 4BD.0 - canonical flag | nothing | foundational; everything else needs it |
| 4BD.1 - intake settings | 4BD.0 | columns + factory-state |
| 4BD.2 - setup prompt | 4BD.1 | first user-visible UX |
| 4BD.3 - generic intake skill rewrite | 4BD.0 + 4BD.1 + 4BD.2 | can ship before 4BD.4 if launch keeps reading from old DB during transition |
| 4BD.4 - run-pack file artifact | 4BD.3 | propose_run_packs writes to artifact |
| 4BD.5 - launch reads file | 4BD.4 | source_artifact column on coding run |
| 4BD.6 - drop tables | 4BD.5 | once nothing reads the old tables |
| 4BD.7 - repo-local skill | parallel with any of the above | becomes the reference |

## Migration of current state

- Per user direction: **no preservation**. Current `docs/loose-ends.md` is deleted (the fix-log keeps the *resolved* history; everything still-open is acceptable to lose). A fresh `docs/inbox.md` is created at 4BD.0/4BD.7 time with a header comment block documenting the schema so the next agent reads it cold.
- No `IssueWorkPack` data is preserved.
- No `WorkspaceAttentionItem(target_kind="issue_intake")` data is preserved.

## Risks

- **Setup friction**: every new Project now hits a one-time convention prompt. Mitigation: 4BD.2 stores the choice in the Blueprint default so cloning a Blueprint copies the intake convention; users only answer once per Blueprint, not once per Project instance.
- **Repo-local skill drift**: if every repo writes its own `.agents/skills/<repo>-issues/SKILL.md`, conventions diverge. Mitigation: the spindrel template (4BD.7) is documented as a copyable reference; users with multiple repos can symlink or vendor it.
- **Auto-commit interactions**: the inbox file changes constantly. The repo-local skill carries the commit-on-change policy; if the user has a hook that batches/skips commits, the inbox file should be on the explicit allowlist. For *this* repo the hook explicitly excludes spindrel from auto-push, so the inbox commit is opt-in (manual commit needed). Surface this in the repo-local skill so the agent doesn't expect auto-pushed history.
- **External-tracker fallback is hand-off only**: `intake_kind = external_tracker` does not call APIs in this plan. Users picking that path see "open this URL, paste this" prompts - acceptable as v0; API integration is a future phase.

## Exit criteria

- A brand-new Project with no convention configured prompts the user once, persists the answer, and never asks again.
- An agent in a Project-bound channel can capture an issue with no DB write - the file (or external-tracker hand-off) is the durable record.
- `IssueWorkPack` table no longer exists; no code references it.
- Mission Control has no issue intake lane.
- This repo's `docs/inbox.md` is the live home for this repo's open-item list, with the documented schema.
- A second repo (e.g. `bennie-loggins`) can be set up with a *different* intake_kind (say, GitHub issues) and the agent respects that choice without code changes.

## Open questions

- Should the auto-commit policy for the inbox file be enforced by Spindrel (a server-side hook on `update_project_intake_file`) or left entirely to the repo-local skill + the user's own git hooks? Current lean: leave it to the user; Spindrel writes the file, doesn't manage VCS.
- Stale-item TTL: 30 days is a guess. Should this be configurable per Project, or hard-coded?
- For repos with multiple canonical-eligible repos (rare), do we need a per-artifact override (e.g., "this Track lives in the docs repo, that Run lives in the app repo")? Defer until a user actually has this need.
