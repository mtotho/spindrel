---
title: Plan - Project Factory Issue Substrate
summary: Replace the bespoke IssueWorkPack/Attention-based intake DB with a repo-resident, file-based substrate (or external tracker). Generic skill is convention-discovery; repo-local .agents/skill names the prescriptive bits. Cancels 4AY-b (RunPack rename) since the table goes away.
status: active
tags: [spindrel, plan, projects, project-factory, intake, runbook]
created: 2026-05-02
updated: 2026-05-02 (4BD.0 + 4BD.1 + 4BD.2 + 4BD.3 shipped)
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

### Phase 4BD.1 - Project intake convention settings *(shipped 2026-05-02)*

- New columns on `Project`:
  - `intake_kind`: `"unset" | "repo_file" | "repo_folder" | "external_tracker"` (server default `"unset"`, NOT NULL)
  - `intake_target`: `Text` nullable. Relative path (for `repo_file`/`repo_folder`) or URL (for `external_tracker`).
  - `intake_metadata`: `JSONB`, server default `'{}'`. Free-form per-kind config (e.g. external tracker name, format hint).
- Migration `292_project_intake_config` adds the columns. No backfill (no usable existing data).
- Pydantic schemas: `ProjectOut` carries the three fields; `ProjectWrite` accepts them on create + PATCH. `normalize_project_intake_kind` enforces the enum (422 on bad kind).
- Service: `project_intake_config(project)` returns `{kind, target, metadata, host_target, configured}` - the resolved view agents read. `host_target` joins the canonical repo path with the relative target for repo-file / repo-folder kinds, None for external trackers and unset projects.
- Factory-state: `get_project_factory_state` payload gains `intake_config: {...}` next to `canonical_repo`, so the generic intake skill reads the convention once.
- UI types: `ui/src/types/api.ts` mirrors the new fields on `Project` + `ProjectWrite`.

### Phase 4BD.2 - Setup-time convention prompt *(shipped 2026-05-02)*

- New mutating tool `update_project_intake_config(kind, target?, metadata?, project_id?)` in `app/tools/local/project_intake_config.py`. Validates the kind via `normalize_project_intake_kind` (rejects unknown values *before* the DB hit), persists the three columns, returns the resolved `intake_config` payload (kind/target/metadata/host_target/configured) plus the `previous_kind` so callers can detect overwrites.
- `skills/project/setup/init.md` Step 11 walks the user through the four choices (repo_file / repo_folder / external_tracker / skip), reading `intake_config.kind` from `get_project_factory_state` to skip when already configured.
- Idempotency lives in the skill, not the tool: the tool always writes what it is given. The skill checks `intake_kind != "unset"` before re-prompting and only re-asks when the user explicitly says "reconfigure intake."
- Strict invariant captured in the skill: setup records the convention only - it never writes the inbox file or creates the tracker on the user's behalf. The first real write happens via `project/intake` (4BD.3).
- Suggested defaults when the user has no preference: `docs/inbox.md` for repo_file, `docs/inbox/` for repo_folder. The skill mentions that an existing repo-local `.agents/skills/<repo>-issues/SKILL.md` may name a different file.

### Phase 4BD.3 - Generic intake skill rewrite *(shipped 2026-05-02)*

- New service `app/services/project_intake_writer.py`:
  - `CapturedIntakeNote` dataclass (title, kind, area, status, body, captured_at) with `.normalized()`.
  - `kebab_slug(value, max_len=60)` for grep-stable headings.
  - `render_inbox_entry(note)` -> the canonical schema:
    `## YYYY-MM-DD HH:MM <slug>` + `**kind:** ... · **area:** ... · **status:** ...` tag line + body. The `area: -` placeholder keeps the tag line greppable when no area is set.
  - `append_to_repo_file(canonical_host, intake_target, note)` -> creates parents, preserves prior content, appends after a single blank line. Returns `IntakeWriteResult` with host_path/relative_path/appended/created_file/slug/timestamp.
  - `write_to_repo_folder(canonical_host, intake_target, note)` -> filename `<YYYYMMDD-HHMM>-<slug>.md` with `-2`, `-3`... collision suffixes for same-minute captures.
- New mutating tool `capture_project_intake(title, kind?, area?, body?, project_id?)` in `app/tools/local/capture_project_intake.py` reads `intake_config` and routes:
  - `repo_file` -> `append_to_repo_file`. Returns `wrote: {host_path, relative_path, appended, slug, timestamp}`.
  - `repo_folder` -> `write_to_repo_folder`.
  - `external_tracker` -> returns `handoff: {tracker, target, instructions}`. **Does not call any external API.**
  - `unset` -> returns `ok: True` with a warning telling the user to run `project/setup/init`; echoes the captured note so it isn't lost.
- `skills/project/intake.md` rewritten:
  - Calls `capture_project_intake` instead of `publish_issue_intake`.
  - Reads `intake_config` from `get_project_factory_state` first.
  - Lists all four routing branches explicitly so the agent narrates the right confirmation.
  - **Defers to repo-local `.agents/skills/<repo>-issues/SKILL.md`** when one exists.
  - Marks `publish_issue_intake` as deprecated (kept until 4BD.6 retires it).
- `publish_issue_intake` tool itself is **not** rewritten in this slice - we leave the old DB write path in place so any in-flight Mission Control intake still drains. 4BD.6 deletes the table + tool + UI lane in one transactional move once nothing reads it.

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
