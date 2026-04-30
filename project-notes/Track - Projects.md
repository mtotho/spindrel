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
- Project Instances are disposable Project roots created from an applied Blueprint snapshot. They reuse the parent Project work-surface policy and are selected by session binding or run-scoped task context, not by mutating the channel Project binding.
- Bot-private workspace-files memory remains separate and is written through the dedicated `memory` tool.
- Project-scoped knowledge lives under `.spindrel/knowledge-base` inside the Project root.
- Project runtime env is derived from the applied Blueprint snapshot plus Project secret bindings. UI/API surfaces expose key names and readiness only; values are injected process-local into Project terminals, exec, and harness turns and are redacted from tool/harness event output.

## Phase Log

- [x] **Phase 1 - First-class primitive** — Projects API/model, channel binding, Project-rooted file/search/terminal/exec/harness/context behavior, Project prompt injection, and compatibility fallback for legacy `project_path` shipped. Architecture locked in [[Architecture Decisions#Projects are shared roots inside the singleton Workspace]].
- [x] **Phase 1.5 - UI repair** — Project list/detail/channel-settings moved to low-chrome admin rows/sections and the screenshot bundle verifies the memory tool envelope remains visible.
- [x] **Phase 2A - Workspace surface** — Project detail became the actual work surface: embedded Project-root file browser, inline Project-root terminal tab, settings/channels tabs, screenshot coverage, and focused runtime tests. Screenshot fixture now seeds a real Project-root README via the workspace file API.
- [x] **Phase 2B - Project membership** — Project detail Channels tab became actionable: create Project-bound channels, attach existing channels, detach members, open channel/settings, and screenshot coverage for the membership flow. Channel creation now accepts `project_id` directly.
- [x] **Phase 2C - WorkSurface interface** — Project-root policy is centralized behind `projects.WorkSurface`; context assembly, file tools, exec tools, channel search/knowledge search, channel indexing, harness cwd, and admin validation now consume the same root/prefix/prompt contract. Added architecture and regression tests to keep callers off the low-level root helpers.
- [x] **Phase 3A - Blueprints v0** — Project Blueprints are first-class reusable recipes with DB-backed CRUD, Project creation from a blueprint, starter folder/file/knowledge-file materialization, applied blueprint snapshots, repo/env declarations, and Project-level secret binding slots. v0 intentionally records repo/env/secret declarations without cloning repos, running setup, or injecting secret values into runtimes.
- [x] **Phase 3B - Blueprint management surface** — Blueprints now have dedicated admin routes for library/detail editing, richer editors for starter files, knowledge files, repo declarations, env defaults, and required secrets, DELETE support that clears live references while preserving Project snapshots, and Project creation preview for selected recipes. The Project Workspace screenshot bundle now covers Blueprint library, editor, and applied-Blueprint settings artifacts.
- [x] **Phase 3C - Blueprint setup runs** — Project Setup now turns the applied Blueprint snapshot into a clone-only runtime plan with Project-scoped secret-slot readiness, persisted setup-run history, conservative repo path safety, existing-path skip behavior, and redacted logs. The Project detail surface has a Setup tab and the Project Workspace screenshot bundle has setup readiness/run-history specs queued for the e2e server once that instance has the current Project Blueprint routes.
- [x] **Phase 3D - Runtime environment** — Project runtime env now has a backend work-surface service, safe readiness API, Project Settings readiness card, setup-plan integration, Project terminal/exec injection, Codex/Claude harness env handoff, and runtime-value redaction across exec and harness event envelopes. Screenshot spec now asserts runtime readiness and no secret leakage; live e2e capture is waiting on the e2e backend deployment of `/api/v1/projects/{id}/runtime-env`.
- [x] **Phase 3E - Blueprint setup commands** — Project Blueprints can now declare ordered shell setup commands that run after repo preparation through Project Setup. Commands use Project-relative cwd, bounded timeouts, Project runtime env and secret bindings, redacted output, persisted run history, and screenshot coverage in the Blueprint editor and Setup tab. E2E staging passes; full screenshot recapture is waiting on the e2e backend deployment of `setup_commands`.
- [x] **Phase 4A - Fresh Project instances** — Added `project_instances`, session/task bindings, creation/list APIs, shared work-surface resolution for instance roots, task-run opt-in via `execution_config.project_instance.mode=fresh`, session binding APIs, a Project Instances tab, task form work-surface controls, docs, and screenshot staging/spec coverage. Live e2e screenshot staging is waiting on the e2e backend deployment of `/api/v1/projects/{id}/instances`.
- [x] **Phase 4B - Session fresh workspace control** — Added a readable session Project-instance state API, session summary fields, composer-level work-surface control, split-pane session menu actions, and screenshot assertion coverage for the Project-bound channel composer. The UI deliberately avoids header chips; session work-surface state lives near the command surface that will use it.
- [x] **Phase 4C - Agent coding runs v0** — Fresh Project instances now flow through the same work-surface policy as shared Projects for file/exec/harness/context/index behavior. Added Project coding-run presets, Project run receipts, a `publish_project_run_receipt` bot tool, Project receipt API/UI, Agent Doctor coding-run readiness, and screenshot bundle coverage for the Runs tab.

## Queued Follow-Ups

- Fresh instances: add expiration cleanup and explicit delete/retry controls after the first deployed e2e screenshot pass.
- Blueprint setup observability: split clone/command run phases into clearer progress events and add rerun controls after deployed E2E validates setup-command history.
- Agent coding runs: add automatic branch/MR helpers, richer run progress, and e2e server update/capture automation once the receipt surface has a deployed screenshot baseline.
