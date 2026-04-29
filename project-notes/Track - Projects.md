---
tags: [agent-server, track, projects]
status: active
updated: 2026-04-29
---

# Track - Projects

Evergreen scope for first-class Project roots inside the singleton SharedWorkspace. Projects are named workspace-relative roots that multiple channels can attach to; they are not replacement workspaces and are not limited to one Git repo.

## Invariants

- `projects` owns the reusable root, prompt settings, and metadata; `channels.project_id` is the primary binding.
- `projects.WorkSurface` is the shared policy object for root path, display path, index root, workspace search prefix, knowledge prefix, Project prompt, and channel/project identity.
- Project-bound turns use the Project root for files, search, terminal, exec, harness cwd, context injection, and channel workspace search.
- Bot-private workspace-files memory remains separate and is written through the dedicated `memory` tool.
- Project-scoped knowledge lives under `.spindrel/knowledge-base` inside the Project root.

## Phase Log

- [x] **Phase 1 - First-class primitive** — Projects API/model, channel binding, Project-rooted file/search/terminal/exec/harness/context behavior, Project prompt injection, and compatibility fallback for legacy `project_path` shipped. Architecture locked in [[Architecture Decisions#Projects are shared roots inside the singleton Workspace]].
- [x] **Phase 1.5 - UI repair** — Project list/detail/channel-settings moved to low-chrome admin rows/sections and the screenshot bundle verifies the memory tool envelope remains visible.
- [x] **Phase 2A - Workspace surface** — Project detail became the actual work surface: embedded Project-root file browser, inline Project-root terminal tab, settings/channels tabs, screenshot coverage, and focused runtime tests. Screenshot fixture now seeds a real Project-root README via the workspace file API.
- [x] **Phase 2B - Project membership** — Project detail Channels tab became actionable: create Project-bound channels, attach existing channels, detach members, open channel/settings, and screenshot coverage for the membership flow. Channel creation now accepts `project_id` directly.
- [x] **Phase 2C - WorkSurface interface** — Project-root policy is centralized behind `projects.WorkSurface`; context assembly, file tools, exec tools, channel search/knowledge search, channel indexing, harness cwd, and admin validation now consume the same root/prefix/prompt contract. Added architecture and regression tests to keep callers off the low-level root helpers.
- [x] **Phase 3A - Blueprints v0** — Project Blueprints are first-class reusable recipes with DB-backed CRUD, Project creation from a blueprint, starter folder/file/knowledge-file materialization, applied blueprint snapshots, repo/env declarations, and Project-level secret binding slots. v0 intentionally records repo/env/secret declarations without cloning repos, running setup, or injecting secret values into runtimes.
- [x] **Phase 3B - Blueprint management surface** — Blueprints now have dedicated admin routes for library/detail editing, richer editors for starter files, knowledge files, repo declarations, env defaults, and required secrets, DELETE support that clears live references while preserving Project snapshots, and Project creation preview for selected recipes. The Project Workspace screenshot bundle now covers Blueprint library, editor, and applied-Blueprint settings artifacts.

## Queued Follow-Ups

- Blueprint runtime preparation: decide how repo/env/secret declarations become executable setup plans without leaking secret values into prompts or persisted snapshots.
- Fresh instances: task/session-scoped disposable Project roots, with Docker sidecars considered only after filesystem/worktree semantics are proven.
